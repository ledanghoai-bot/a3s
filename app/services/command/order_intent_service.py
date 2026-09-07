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

import re

from app.services.command import order_intent as oi

# Sentinel: field KHONG duoc cung cap o luot nay (giu nguyen). Phan biet voi explicit-clear (None/"" tuong
# minh -> xoa field). CA 233-04: "distinguish omitted field from explicit clear/correction".
_UNSET: object = object()

# VN phone shape (CA 233-04 validate truoc READY, khong chi non-null). Cho phep 0xxxxxxxxx / +84xxxxxxxxx.
_PHONE_RE = re.compile(r"^(?:0|\+?84)\d{8,10}$")

# TTL abandoned open intent (CA 225-01: terminalize deterministically). Chi GC/recovery, KHONG dinh nghia
# 2 don co giong nhau khong (§7 TTL is cleanup only).
OPEN_INTENT_TTL_SECONDS = 24 * 3600


async def create_intent(conn, *, customer_id: int, conversation_id, channel: str) -> dict:
    """Tao intent moi o COLLECTING + expires_at (TTL GC abandoned). Tra row dict (id, state, state_version=0)."""
    row = await conn.fetchrow(
        "INSERT INTO order_intents(customer_id,conversation_id,channel,state,expires_at) "
        f"VALUES($1,$2,$3,'COLLECTING', now() + interval '{OPEN_INTENT_TTL_SECONDS} seconds') "
        "RETURNING id,state,state_version",
        customer_id, conversation_id, channel)
    return dict(row)


# Cot draft + summary (CA 232 §3/§6). draft_address = PROTECTED business data (khong in raw ra log/evidence).
_DRAFT_COLS = ("draft_sku,draft_quantity,draft_customer_name,draft_phone,draft_address,"
               "summary_version,summary_fingerprint")
_DRAFT_FIELDS = ("sku", "quantity", "customer_name", "phone", "address")


def draft_complete(row: dict) -> bool:
    """True neu draft du field bat buoc de commit (SKU/qty/contact/address). Chi kiem tra ton tai."""
    return all(row.get(f"draft_{f}") not in (None, "") for f in _DRAFT_FIELDS)


def _norm_phone(phone) -> str:
    return re.sub(r"[ .\-()]", "", phone) if isinstance(phone, str) else ""


def draft_valid(row: dict) -> bool:
    """CA 233-04: VALIDATE draft (khong chi non-null) truoc READY: sku la chuoi non-empty, quantity int
    duong, ten non-empty, phone dung dang VN, address du dai (>=6). SKU-EXISTENCE kiem o flow (can DB)."""
    sku = row.get("draft_sku")
    qty = row.get("draft_quantity")
    name = row.get("draft_customer_name")
    addr = row.get("draft_address")
    if not (isinstance(sku, str) and sku.strip()):
        return False
    if not (isinstance(qty, int) and not isinstance(qty, bool) and qty > 0):
        return False
    if not (isinstance(name, str) and name.strip()):
        return False
    if not _PHONE_RE.match(_norm_phone(row.get("draft_phone"))):
        return False
    if not (isinstance(addr, str) and len(addr.strip()) >= 6):
        return False
    return True


def draft_invalid_fields(row: dict) -> list[str]:
    """Danh sach field THIEU hoac SAI DANG (CA 233-04) — de hoi khach bo sung/sua dung field."""
    bad = []
    if not (isinstance(row.get("draft_sku"), str) and row["draft_sku"].strip()):
        bad.append("sku")
    q = row.get("draft_quantity")
    if not (isinstance(q, int) and not isinstance(q, bool) and q > 0):
        bad.append("quantity")
    if not (isinstance(row.get("draft_customer_name"), str) and row["draft_customer_name"].strip()):
        bad.append("customer_name")
    if not _PHONE_RE.match(_norm_phone(row.get("draft_phone"))):
        bad.append("phone")
    if not (isinstance(row.get("draft_address"), str) and len(row["draft_address"].strip()) >= 6):
        bad.append("address")
    return bad


async def get_intent(conn, intent_id, *, for_update: bool = False) -> dict | None:
    q = ("SELECT id,customer_id,conversation_id,channel,state,state_version,order_fingerprint,"
         "verified_address_fingerprint,verified_resolution_id,committed_order_id,terminal_reason,error_code,"
         f"{_DRAFT_COLS} FROM order_intents WHERE id=$1")
    if for_update:
        q += " FOR UPDATE"
    row = await conn.fetchrow(q, intent_id)
    return dict(row) if row else None


async def update_draft(conn, intent_id, *, expected_version: int, sku=_UNSET, quantity=_UNSET,
                       customer_name=_UNSET, phone=_UNSET, address=_UNSET) -> dict | None:
    """CA 232 §3 + 233-04: luu/ghi de field draft server-owned. Field = _UNSET (mac dinh) -> KHONG dung
    toi (omitted, giu nguyen). Field co gia tri -> ghi de. Field = None/'' TUONG MINH -> XOA (explicit
    clear/correction). Optimistic version (compare-and-set). state_version TANG de bat ky readiness/summary
    cu bi vo hieu (§3). Tra row moi hoac None (version lech / khong co field nao doi)."""
    sets = ["state_version=state_version+1"]
    vals: list = []
    for col, val in (("draft_sku", sku), ("draft_quantity", quantity),
                     ("draft_customer_name", customer_name), ("draft_phone", phone),
                     ("draft_address", address)):
        if val is _UNSET:
            continue  # omitted -> giu nguyen
        vals.append(None if val in (None, "") else val)  # None/'' tuong minh -> clear
        sets.append(f"{col}=${len(vals) + 2}")
    row = await conn.fetchrow(
        f"UPDATE order_intents SET {', '.join(sets)} "
        "WHERE id=$1 AND state_version=$2 "
        f"RETURNING id,customer_id,conversation_id,channel,state,state_version,order_fingerprint,"
        f"verified_address_fingerprint,verified_resolution_id,committed_order_id,{_DRAFT_COLS}",
        intent_id, expected_version, *vals)
    return dict(row) if row else None


async def clear_address_binding(conn, intent_id, *, expected_version: int) -> dict | None:
    """CA 232 §3/§5: dia chi doi -> XOA verified binding/fingerprint cu truoc khi verify lai (khong bind
    pointer cu). Optimistic version."""
    row = await conn.fetchrow(
        "UPDATE order_intents SET state_version=state_version+1, verified_resolution_id=NULL, "
        "verified_address_fingerprint=NULL, summary_version=NULL, summary_fingerprint=NULL "
        "WHERE id=$1 AND state_version=$2 RETURNING id,state,state_version",
        intent_id, expected_version)
    return dict(row) if row else None


async def present_summary(conn, intent_id, *, expected_version: int, order_fingerprint: str,
                          content_hash: str | None = None) -> dict | None:
    """CA 232 §6 + 234-03: server VUA present deterministic summary READY -> ghi summary_version +
    fingerprint + content_hash (cua text summary DA persist). Xac nhan sau do CHI hop le neu intent VAN o
    dung version/fingerprint/hash nay (correction doi -> vo hieu). KHONG doi state_version."""
    row = await conn.fetchrow(
        "UPDATE order_intents SET summary_version=$3, summary_fingerprint=$4, summary_content_hash=$5, "
        "summary_presented_at=now() WHERE id=$1 AND state_version=$2 AND state='READY_TO_COMMIT' "
        "RETURNING id,state,state_version,summary_version,summary_fingerprint,summary_content_hash",
        intent_id, expected_version, expected_version, order_fingerprint, content_hash)
    return dict(row) if row else None


async def log_message_tx(conn, conversation_id, role: str, content: str,
                         dedupe_key: str | None = None) -> bool:
    """CA 234-03/04: ghi 1 message vao messages TRONG CUNG transaction cua caller (khong pool rieng) ->
    persist server-response + arm confirmation ATOMIC. dedupe_key (neu co) -> ON CONFLICT DO NOTHING =>
    exactly-once row theo stable identity. Tra True neu ghi moi, False neu da ton tai (duplicate)."""
    if role not in ("customer", "bot", "agent"):
        role = "bot"
    r = await conn.fetchval(
        "INSERT INTO messages(conversation_id, role, content, dedupe_key) VALUES($1,$2,$3,$4) "
        "ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING RETURNING id",
        conversation_id, role, content, dedupe_key)
    return r is not None


async def has_committed_intent(conn, *, customer_id: int, conversation_id) -> bool:
    """CA 234-02.5: hoi thoai nay DA co intent COMMITTED chua (bat ke fingerprint)? -> sau COMMITTED, de
    xuat KHONG explicit reorder (ke ca partial/stale) KHONG duoc tao draft moi."""
    return bool(await conn.fetchval(
        "SELECT 1 FROM order_intents WHERE customer_id=$1 AND conversation_id IS NOT DISTINCT FROM $2 "
        "AND state='COMMITTED' LIMIT 1", customer_id, conversation_id))


async def find_open_intent(conn, *, customer_id: int, conversation_id,
                           for_update: bool = False) -> dict | None:
    """Tim intent OPEN HIEN TAI cho (customer, conversation) — "prospective order dang mo" (CA 225-01).
    Correction cap nhat CHINH intent nay. Unique index oi_one_open_per_conversation bao dam <=1 open."""
    q = ("SELECT id,customer_id,conversation_id,channel,state,state_version,order_fingerprint,"
         "verified_address_fingerprint,verified_resolution_id,committed_order_id,summary_presented_at,"
         "summary_content_hash,"
         f"{_DRAFT_COLS},(expires_at IS NOT NULL AND expires_at < now()) AS is_expired FROM order_intents "
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
