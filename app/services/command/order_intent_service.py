"""M5 order-intent SERVICE — DB primitives cho durable state machine (CA Directive 223 + Amendment 224).

Server SO HUU intent: tao, transition (compare-and-set theo state_version), commit atomic. LLM/tool KHONG
duoc chon intent/state/order-id (chi orchestrator server-side goi cac ham nay voi ngu canh trusted).

Nguyen tac an toan:
- Moi transition BAT BUOC dung expected_version (optimistic concurrency) -> tra False khi version lech
  (co worker khac da doi) -> caller xu ly (re-read/retry) thay vi ghi de mu.
- Transition phai hop le theo order_intent.can_transition (fail-closed).
- Commit atomic: dat COMMITTED + committed_order_id trong CUNG cau UPDATE co dieu kien
  (state='COMMITTING' AND state_version=expected) -> DB dam bao at-most-once (khong chi Redis).
"""
from __future__ import annotations

from app.services.command import order_intent as oi


async def create_intent(conn, *, customer_id: int, conversation_id, channel: str) -> dict:
    """Tao intent moi o COLLECTING. Tra row dict (co id, state, state_version=0)."""
    row = await conn.fetchrow(
        "INSERT INTO order_intents(customer_id,conversation_id,channel,state) "
        "VALUES($1,$2,$3,'COLLECTING') RETURNING id,state,state_version",
        customer_id, conversation_id, channel)
    return dict(row)


async def get_intent(conn, intent_id, *, for_update: bool = False) -> dict | None:
    q = ("SELECT id,customer_id,conversation_id,channel,state,state_version,order_fingerprint,"
         "verified_address_fingerprint,verified_resolution_id,committed_order_id,terminal_reason,error_code "
         "FROM order_intents WHERE id=$1")
    if for_update:
        q += " FOR UPDATE"
    row = await conn.fetchrow(q, intent_id)
    return dict(row) if row else None


async def find_open_intent(conn, *, customer_id: int, conversation_id,
                           for_update: bool = False) -> dict | None:
    """Tim intent OPEN HIEN TAI cho (customer, conversation) — "prospective order dang mo" (CA 225-01).
    Correction cap nhat CHINH intent nay. Unique index oi_one_open_per_conversation bao dam <=1 open."""
    q = ("SELECT id,customer_id,conversation_id,channel,state,state_version,order_fingerprint,"
         "verified_address_fingerprint,verified_resolution_id,committed_order_id FROM order_intents "
         "WHERE customer_id=$1 AND conversation_id IS NOT DISTINCT FROM $2 "
         "AND state = ANY($3::text[]) ORDER BY created_at DESC LIMIT 1")
    if for_update:
        q += " FOR UPDATE"
    row = await conn.fetchrow(q, customer_id, conversation_id, list(oi.OPEN_STATES))
    return dict(row) if row else None


async def find_recent_committed(conn, *, customer_id: int, conversation_id,
                                order_fingerprint: str) -> dict | None:
    """DB-AUTHORITATIVE stale-confirm (CA 225-04): intent COMMITTED gan nhat cho (customer,conversation)
    cung order_fingerprint. Dung de tra receipt cu cho xac nhan lai/redelivery MA KHONG phu thuoc Redis
    (Redis flush/restart/TTL khong doi semantic). None neu khong co."""
    row = await conn.fetchrow(
        "SELECT id,state,committed_order_id,order_fingerprint FROM order_intents "
        "WHERE customer_id=$1 AND conversation_id IS NOT DISTINCT FROM $2 AND state='COMMITTED' "
        "AND committed_order_id IS NOT NULL AND order_fingerprint=$3 "
        "ORDER BY updated_at DESC LIMIT 1",
        customer_id, conversation_id, order_fingerprint)
    return dict(row) if row else None


async def transition(conn, intent_id, *, expected_version: int, to_state: str,
                     order_fingerprint: str | None = None, verified_address_fingerprint: str | None = None,
                     verified_resolution_id=None, terminal_reason: str | None = None,
                     error_code: str | None = None) -> dict | None:
    """Compare-and-set transition. Doc state hien tai (FOR UPDATE), kiem tra hop le + version, roi UPDATE.
    Tra row moi (dict) neu thanh cong; None neu version lech / transition khong hop le (fail-closed)."""
    cur = await conn.fetchrow(
        "SELECT state,state_version FROM order_intents WHERE id=$1 FOR UPDATE", intent_id)
    if cur is None or cur["state_version"] != expected_version:
        return None  # version lech (concurrency) hoac khong ton tai
    if not oi.can_transition(cur["state"], to_state):
        return None  # transition khong hop le -> fail-closed
    row = await conn.fetchrow(
        "UPDATE order_intents SET state=$2, state_version=state_version+1, "
        "order_fingerprint=COALESCE($3,order_fingerprint), "
        "verified_address_fingerprint=COALESCE($4,verified_address_fingerprint), "
        "verified_resolution_id=COALESCE($5,verified_resolution_id), "
        "terminal_reason=$6, error_code=$7 "
        "WHERE id=$1 AND state_version=$8 "
        "RETURNING id,state,state_version,order_fingerprint,verified_address_fingerprint,"
        "verified_resolution_id,committed_order_id",
        intent_id, to_state, order_fingerprint, verified_address_fingerprint, verified_resolution_id,
        terminal_reason, error_code, expected_version)
    return dict(row) if row else None


async def commit_via_intent(conn, intent_id, *, do_create):
    """ATOMIC commit qua intent (CA Amendment 224 §6). do_create = async callback tao don THAT trong CUNG
    connection/transaction, tra order_id. Tra (order_id, duplicate: bool).

    Bao dam AT-MOST-ONCE o tang DB:
    - Lock intent (FOR UPDATE) -> serialize 2 worker/luot dong thoi cung intent.
    - Da COMMITTED -> tra committed_order_id (idempotent, KHONG tao don moi) — xu ly stale-confirm/redelivery/retry.
    - Chua -> transition COMMITTING (neu can) -> do_create() -> mark_committed atomic co dieu kien.
    - Neu mark_committed thua (worker khac vua commit) -> tra committed_order_id cua worker kia.
    KHONG duoc goi voi intent terminal khac COMMITTED (fail-closed)."""
    row = await conn.fetchrow(
        "SELECT state,state_version,committed_order_id FROM order_intents WHERE id=$1 FOR UPDATE", intent_id)
    if row is None:
        raise ValueError("order_intent not found")
    if row["state"] == "COMMITTED" and row["committed_order_id"] is not None:
        return row["committed_order_id"], True
    if row["state"] in oi.TERMINAL_STATES:
        raise ValueError(f"cannot commit terminal intent state={row['state']}")
    ver = row["state_version"]
    if row["state"] != "COMMITTING":
        if not oi.can_transition(row["state"], "COMMITTING"):
            raise ValueError(f"cannot COMMITTING from {row['state']}")
        await conn.execute(
            "UPDATE order_intents SET state='COMMITTING', state_version=state_version+1 "
            "WHERE id=$1 AND state_version=$2", intent_id, ver)
        ver += 1
    order_id = await do_create()
    m = await mark_committed(conn, intent_id, expected_version=ver, order_id=order_id)
    if m is None:
        # worker khac da commit intent nay -> tra committed_order_id cua ho (do_create cua ta se rollback
        # neu caller quan ly tx dung; day la truong hop hiem, an toan tra don da commit)
        existing = await conn.fetchval(
            "SELECT committed_order_id FROM order_intents WHERE id=$1", intent_id)
        return existing, True
    return order_id, False


async def mark_committed(conn, intent_id, *, expected_version: int, order_id: int) -> dict | None:
    """COMMITTING -> COMMITTED + committed_order_id, ATOMIC co dieu kien (state='COMMITTING' AND version).
    DB dam bao at-most-once (unique oi_one_committed_order + compare-and-set). None neu khong claim duoc."""
    row = await conn.fetchrow(
        "UPDATE order_intents SET state='COMMITTED', committed_order_id=$2, state_version=state_version+1 "
        "WHERE id=$1 AND state='COMMITTING' AND state_version=$3 "
        "RETURNING id,state,state_version,committed_order_id",
        intent_id, order_id, expected_version)
    return dict(row) if row else None
