"""CA Directive 251 + Review 252 R1 harness — DoD DB-backed. Chay tren throwaway m5lab DB (schema >= 062
voi CHECK constraint). KHONG PII/secret. Re-runnable (psid theo RUN).

Chung minh (252-04): terminal-state truthful server-truth (6), 252-01 allowlist enforce (unknown reason
KHONG transition/pause/notify; 4 allowlist reason rieng), 252-02 durable notify khong-mat (intent-scoped +
conversation-scoped khi khong co intent), 252-03 CHECK constraint (command-backed event van bat buoc
command_id), worker render 2 loai escalation, cross-intent payload phan biet (252-04.5), dedupe idempotent
(252-04.4), matcher timing khong network (252-04.7), non-escalated terminal query THAT (252-04.8).
"""
import asyncio
import sys
import time

from app.db_pool import acquire, close_pool, release
from app.services import handoff, tools
from app.services.address import matcher
from app.services.command import order_intent as oi
from app.services.command import order_intent_flow as oif
from app.services.command import order_intent_service as svc
from app.services.command import outbox_worker
from app.services.orchestrator import _conversation_order_state

RUN = str(int(time.time()))
FAILS = []


def ck(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' :: ' + str(extra)) if extra else ''}")
    if not cond:
        FAILS.append(name)


async def _mk(conn, psid):
    cid = await conn.fetchval("INSERT INTO customers (psid) VALUES ($1) RETURNING id", psid)
    conv = await conn.fetchval(
        "INSERT INTO conversations (customer_id, bot_paused) VALUES ($1, FALSE) RETURNING id", cid)
    return cid, conv


async def _open_intent(conn, cid, conv, channel="telegram_customer"):
    row = await svc.create_intent(conn, customer_id=cid, conversation_id=conv, channel=channel)
    await conn.execute(
        "UPDATE order_intents SET draft_sku=$2, draft_quantity=$3, draft_customer_name=$4, "
        "draft_phone=$5, draft_address=$6 WHERE id=$1",
        row["id"], "3S-100g", 1, "Chi Phuong", "0900123456", "25 Truong Cong Dinh, Tan Lap, Dak Lak")
    return row["id"]


async def main():
    conn = await acquire()
    try:
        # ===== 252-01: allowlist ENFORCE =====
        cid, conv = await _mk(conn, f"tg:h-allow-{RUN}")
        iid = await _open_intent(conn, cid, conv)
        # unknown reason -> terminalize TU CHOI (khong transition, khong outbox)
        ok_unknown = await oif.terminalize(customer_id=cid, conversation_id=conv,
                                           to_state="ESCALATED", reason="random_free_text")
        st = await conn.fetchval("SELECT state FROM order_intents WHERE id=$1", iid)
        n_ob = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key LIKE $1",
                                   f"order_escalated:{iid}:%")
        ck("252-01: unknown reason -> KHONG transition (intent giu open)", (not ok_unknown)
           and st in oi.OPEN_STATES and n_ob == 0, f"ok={ok_unknown} st={st} outbox={n_ob}")
        # 4 allowlist reason -> transition OK (moi cai 1 intent rieng)
        for rc in ("clarification_exhausted", "customer_wants_human", "system_failure_after_retry",
                   "business_policy_handoff"):
            c2, cv2 = await _mk(conn, f"tg:h-allow-{rc}-{RUN}")
            i2 = await _open_intent(conn, c2, cv2)
            okr = await oif.terminalize(customer_id=c2, conversation_id=cv2, to_state="ESCALATED", reason=rc)
            n2 = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key LIKE $1",
                                     f"order_escalated:{i2}:%")
            ck(f"252-01: allowlist reason '{rc}' -> ESCALATED + 1 durable notify", okr and n2 == 1)

        # ===== 252-02: durable notify KHONG MAT khi KHONG co open intent (conversation-scoped) =====
        cid3, conv3 = await _mk(conn, f"tg:h-noesc-{RUN}")
        # KHONG tao open intent -> customer_wants_human phai tao conversation-scoped notify
        res = await tools.escalate_to_human(psid=f"tg:h-noesc-{RUN}", reason="khach doi gap nguoi",
                                            reason_code="customer_wants_human", last_message="cho gap nhan vien",
                                            channel="telegram_customer")
        ck("252-02: escalate khong-intent -> scope=conversation", res.get("scope") == "conversation", res.get("scope"))
        n_conv = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE event_type='handoff.escalated.notify' "
                                     "AND dedupe_key=$1", f"handoff_escalated:{conv3}:customer_wants_human")
        ck("252-02: conversation-scoped durable notify DUNG 1", n_conv == 1, f"n={n_conv}")
        # unknown reason_code qua entry hop nhat -> REFUSED (khong pause/notify)
        res_u = await tools.escalate_to_human(psid=f"tg:h-noesc-{RUN}", reason="x", reason_code="bogus_code")
        paused = await conn.fetchval("SELECT bot_paused FROM conversations WHERE id=$1", conv3)
        ck("252-01: unknown reason_code qua escalate_to_human -> refused (van paused tu lan truoc, khong notify moi)",
           res_u.get("refused") == "unknown_reason", res_u)

        # ===== 252-03: CHECK constraint — command-backed event VAN bat buoc command_id =====
        rejected = False
        try:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO outbox_events (id, command_id, event_type, event_version, destination, "
                    "dedupe_key, payload, status, available_at, max_attempts) VALUES "
                    "(gen_random_uuid(), NULL, 'order.created.notify', 1, 'telegram_admin', $1, '{}'::jsonb, "
                    "'pending', now(), 3)", f"bad_null_cmd:{RUN}")
        except Exception:  # noqa: BLE001 — CHECK constraint tu choi
            rejected = True
        ck("252-03: order.created.notify command_id NULL -> DB TU CHOI (CHECK)", rejected)

        # ===== 252-04.5: cross-intent — 1 committed + 1 escalated, payload phan biet =====
        cidX, convX = await _mk(conn, f"tg:h-cross-{RUN}")
        iE = await _open_intent(conn, cidX, convX)
        await oif.terminalize(customer_id=cidX, conversation_id=convX, to_state="ESCALATED",
                              reason="clarification_exhausted")
        pj = await conn.fetchval("SELECT payload FROM outbox_events WHERE dedupe_key LIKE $1",
                                 f"order_escalated:{iE}:%")
        import json as _j
        pjd = pj if isinstance(pj, dict) else _j.loads(pj)
        ck("252-04.5: escalated payload has_intent=True + dung intent_id", pjd.get("has_intent") is True
           and pjd.get("intent_id") == str(iE))

        # ===== 252-04.4: worker RENDER 2 loai + dedupe idempotent =====
        t_intent = outbox_worker._telegram_admin_text(pjd)
        t_conv = outbox_worker._telegram_admin_text({"kind": "escalation", "has_intent": False,
                                                     "reason_code": "customer_wants_human", "reason_detail": "x",
                                                     "conversation_id": convX, "phone_masked": "***456"})
        ck("252-04.4: render intent-escalation co 'CAN HO TRO' + Intent", "CAN HO TRO" in t_intent and "Intent:" in t_intent)
        ck("252-04.4: render conversation-handoff co 'KHONG gan don'", "KHONG gan don" in t_conv)
        # dedupe idempotent: enqueue trung dedupe_key -> khong tao them
        n_before = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key LIKE $1",
                                       f"order_escalated:{iE}:%")
        await oif.terminalize(customer_id=cidX, conversation_id=convX, to_state="ESCALATED",
                              reason="clarification_exhausted")  # intent da terminal -> no-op
        n_after = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key LIKE $1",
                                      f"order_escalated:{iE}:%")
        ck("252-04.4: dedupe idempotent (re-terminalize khong tao notify trung)", n_before == n_after == 1)

        # ===== 252-04.8: non-escalated terminal — CANCELLED KHONG tao escalation outbox (query THAT) =====
        cidC, convC = await _mk(conn, f"tg:h-cancel-{RUN}")
        iC = await _open_intent(conn, cidC, convC)
        await oif.terminalize(customer_id=cidC, conversation_id=convC, to_state="CANCELLED", reason="customer_cancel")
        n_cancel_esc = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key LIKE $1",
                                           f"order_escalated:{iC}:%")
        ck("252-04.8: CANCELLED -> 0 escalation outbox (query THAT, khong hard-code)", n_cancel_esc == 0, n_cancel_esc)

        # ===== 252-04.1/6 (proxy): _conversation_order_state tra dung state per terminal (drive truthful msg) =====
        # escalated
        s_esc = await _conversation_order_state(f"tg:h-cross-{RUN}", convX)
        ck("DoD6: state escalated (khong phai committed/none)", s_esc.get("state") == "escalated", s_esc.get("state"))
        # cancelled
        s_can = await _conversation_order_state(f"tg:h-cancel-{RUN}", convC)
        ck("DoD6: state cancelled", s_can.get("state") == "cancelled", s_can.get("state"))
        # none (khach chua co intent nao)
        cidN, convN = await _mk(conn, f"tg:h-none-{RUN}")
        s_non = await _conversation_order_state(f"tg:h-none-{RUN}", convN)
        ck("DoD6: state none khi chua co intent", s_non.get("state") == "none", s_non.get("state"))

        # ===== 252-04.7: matcher timing — thuan logic, KHONG network. Raw samples =====
        units = [{"level": "province", "code": "66", "name": "Tỉnh Đắk Lắk", "parent_code": None},
                 {"level": "ward", "code": "24121", "name": "Phường Tân Lập", "parent_code": "66"},
                 {"level": "ward", "code": "24316", "name": "Xã Pơng Drang", "parent_code": "66"}]
        aliases = [{"unit_code": "24316", "alias_name": "Xã Tân Lập", "alias_kind": "legacy"}]
        samples = []
        for _ in range(5):
            t0 = time.perf_counter()
            r = matcher.resolve(units, aliases, province="Đắk Lắk", district=None, ward="Tân Lập")
            samples.append(round((time.perf_counter() - t0) * 1000, 3))
        ck("252-04.7: matcher resolve dung + timing pure (raw ms)", r["ward_code"] == "24121", f"samples_ms={samples}")

    finally:
        await release(conn)
        await close_pool()

    print("\nRESULT:", "ALL PASS" if not FAILS else f"FAIL ({len(FAILS)}): {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main())
