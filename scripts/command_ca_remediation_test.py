#!/usr/bin/env python3
"""CA Submission-1 remediation evidence (I-B M1). Map trực tiếp CA-CONSOLIDATED-REVIEW-1.

  CR-01  auto-retry -> dead-letter -> manual retry -> delivered; attempt_no LIÊN TỤC, KHÔNG trùng.
  CR-02  worker compare-and-set: event 'delivering' thuộc lease worker khác -> finalize KHÔNG đè.
  CR-03  customer receipt DURABLE qua outbox (messenger): commit tạo event; send lỗi -> retry -> delivered.
  CR-05  audit fail-closed: audit_log hỏng -> order mutation ROLLBACK (không order/không command).

  docker exec -e DATABASE_URL=...m1_itest -e PYTHONPATH=/srv -w /srv api python scripts/command_ca_remediation_test.py
"""
import asyncio
import json
import sys

import asyncpg

from app.config import settings
from app.services import auth_service
from app.services.command import order_gateway, order_service, outbox_worker, recovery
from app.services.command.envelope import Actor, build_order_create_envelope
from app.services.command.outbox_worker import WORKER_ID, SendResult

C = {"customer_name": "CA Rem", "phone": "0900555777", "address": "9 CA"}


def _db():
    return settings.database_url.replace("+asyncpg", "")


async def ins_outbox(conn, cid, dedupe, status, max_attempts=2):
    return await conn.fetchval(
        "INSERT INTO outbox_events (id,command_id,event_type,event_version,destination,dedupe_key,"
        "payload,status,available_at,max_attempts) VALUES (gen_random_uuid(),$1,'x',1,'telegram_admin',"
        "$2,$3::jsonb,$4,now(),$5) RETURNING id",
        cid, dedupe, json.dumps({"order_id": 1}), status, max_attempts)


async def ev_row(conn, eid):
    return await conn.fetchrow("SELECT status, attempt_count, max_attempts FROM outbox_events WHERE id=$1", eid)


async def attempt_nos(conn, eid):
    rows = await conn.fetch("SELECT attempt_no FROM delivery_attempts WHERE outbox_event_id=$1 "
                            "ORDER BY attempt_no", eid)
    return [r["attempt_no"] for r in rows]


async def err500(dest, payload):
    return SendResult(ok=False, http_status=500, error_class="http_500")


async def ok_send(dest, payload):
    return SendResult(ok=True, http_status=200, provider_message_id="ok")


async def main() -> int:  # noqa: C901
    conn = await asyncpg.connect(_db())
    fails: list[str] = []
    try:
        await conn.execute("TRUNCATE order_items, orders, command_executions, outbox_events, "
                           "delivery_attempts, price_overrides RESTART IDENTITY CASCADE")
        await conn.execute("UPDATE products SET stock=1000 WHERE sku='3S-100G'")
        st = await auth_service.create_staff_user("carem_staff", "pw12345678", "CA", role_key="admin")
        actor = {"id": st["id"], "username": "carem_staff"}

        def dash_env(key):
            return build_order_create_envelope(
                raw_payload=dict(C, sku="3S-100G", quantity=1, unit_price_vnd=150000),
                actor=Actor("staff", str(st["id"])), channel="dashboard", idempotency_key=key)

        await order_service.execute_order_create(dash_env("carem-seed-000001"))
        cid = await conn.fetchval("SELECT id FROM command_executions LIMIT 1")
        # dọn outbox admin của order seed để test sạch
        await conn.execute("TRUNCATE outbox_events, delivery_attempts RESTART IDENTITY CASCADE")

        # === CR-01: auto-retry -> dead-letter (max 2) -> manual retry -> delivered, attempt_no liên tục ===
        e1 = await ins_outbox(conn, cid, "cr01", "pending", max_attempts=2)
        await outbox_worker.run_once(send_fn=err500)                                   # attempt 1
        await conn.execute("UPDATE outbox_events SET available_at=now() WHERE id=$1", e1)
        await outbox_worker.run_once(send_fn=err500)                                   # attempt 2 -> dead
        row = await ev_row(conn, e1)
        if row["status"] != "dead_lettered":
            fails.append(f"CR-01: chưa dead_lettered sau 2 attempt: {dict(row)}")
        await recovery.retry_outbox(str(e1), actor, "manual retry sau khi khôi phục")  # CR-01 fix
        row = await ev_row(conn, e1)
        if not (row["status"] == "retry_scheduled" and row["attempt_count"] == 2 and row["max_attempts"] == 10):
            fails.append(f"CR-01: manual retry sai (giữ attempt_count=2, max->10): {dict(row)}")
        await outbox_worker.run_once(send_fn=ok_send)                                  # attempt 3 -> delivered
        row = await ev_row(conn, e1)
        nos = await attempt_nos(conn, e1)
        if not (row["status"] == "delivered" and nos == [1, 2, 3]):
            fails.append(f"CR-01: sau manual retry không delivered / attempt_no không liên tục: "
                         f"status={row['status']} attempts={nos}")

        # === CR-02: worker CAS — event 'delivering' thuộc lease worker KHÁC -> finalize không đè ===
        e2 = await ins_outbox(conn, cid, "cr02", "pending", max_attempts=8)
        await conn.execute("UPDATE outbox_events SET status='delivering', lease_owner='ghost-worker', "
                           "attempt_count=5 WHERE id=$1", e2)
        ev = await conn.fetchrow("SELECT id, command_id, destination, dedupe_key, payload, attempt_count, "
                                 "max_attempts FROM outbox_events WHERE id=$1", e2)
        await outbox_worker._send_and_record(conn, ev, ok_send)   # gửi OK nhưng lease_owner != WORKER_ID
        row = await ev_row(conn, e2)
        if row["status"] != "delivering":
            fails.append(f"CR-02: CAS thất bại — event bị đè thành {row['status']} (mong giữ delivering)")
        if WORKER_ID == "ghost-worker":
            fails.append("CR-02: WORKER_ID trùng ghost (test không hợp lệ)")

        # === CR-03: customer receipt durable qua outbox (messenger), commit-ok + send-fail -> retry ===
        await conn.execute("TRUNCATE outbox_events, delivery_attempts RESTART IDENTITY CASCADE")

        msg_env = build_order_create_envelope(
            raw_payload=dict(C, sku="3S-100G", quantity=1, psid="psid-carem"),
            actor=Actor("customer", "psid-carem"), channel="messenger", idempotency_key="carem-msg-0001")
        rm = await order_service.execute_order_create(msg_env)
        oid = rm.resource["id"]
        cust = await conn.fetchrow(
            "SELECT id, payload, status FROM outbox_events WHERE destination='messenger' AND dedupe_key=$1",
            f"order_receipt:{oid}")
        if cust is None:
            fails.append("CR-03: KHÔNG tạo customer-receipt outbox event (messenger)")
        else:
            payload = cust["payload"] if isinstance(cust["payload"], str) else json.dumps(cust["payload"])
            if "Đơn #" not in payload or "psid-carem" not in payload:
                fails.append(f"CR-03: payload receipt khách sai: {payload}")
            # send lỗi -> retry_scheduled (không mất), rồi ok -> delivered
            await outbox_worker.run_once(send_fn=err500)
            st1 = await conn.fetchval("SELECT status FROM outbox_events WHERE id=$1", cust["id"])
            if st1 != "retry_scheduled":
                fails.append(f"CR-03: send lỗi -> mong retry_scheduled, được {st1}")
            await conn.execute("UPDATE outbox_events SET available_at=now() WHERE id=$1", cust["id"])
            await outbox_worker.run_once(send_fn=ok_send)
            st2 = await conn.fetchval("SELECT status FROM outbox_events WHERE id=$1", cust["id"])
            if st2 != "delivered":
                fails.append(f"CR-03: sau retry ok -> mong delivered, được {st2}")

        # === CR-04R: AI idempotency ổn định — cùng provider message + cùng nội dung -> ĐÚNG 1 order
        #     (không phụ thuộc tool_call_id); provider message khác -> order mới ===
        def gw(pmid):
            return order_gateway.create_order_command(
                channel="messenger", actor_type="customer", actor_id="psid-r", idempotency_key=None,
                provider_message_id=pmid, customer_name=C["customer_name"], phone=C["phone"],
                address=C["address"], sku="3S-100G", quantity=1, psid="psid-r")

        r_a = await gw("mid-R1")
        r_b = await gw("mid-R1")   # "re-execution" cùng inbound message -> gateway derive CÙNG key
        if not (r_a.get("order_id") and r_b.get("order_id") == r_a.get("order_id") and r_b.get("duplicate")):
            fails.append(f"CR-04R: cùng message không idempotent: a={r_a.get('order_id')} b={r_b}")
        r_c = await gw("mid-R2")   # provider message khác -> key khác -> order mới
        if not (r_c.get("order_id") and r_c.get("order_id") != r_a.get("order_id") and not r_c.get("duplicate")):
            fails.append(f"CR-04R: message khác phải tạo order mới: c={r_c}")

        # === CR-05: audit fail-closed — audit_log hỏng -> order mutation rollback ===
        n_before = await conn.fetchval("SELECT count(*) FROM orders")
        await conn.execute("ALTER TABLE audit_log ADD CONSTRAINT _ff5 CHECK (false) NOT VALID")
        raised = False
        try:
            await order_service.execute_order_create(dash_env("carem-cr05-00001"))
        except Exception:
            raised = True
        await conn.execute("ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS _ff5")
        if not raised:
            fails.append("CR-05: audit hỏng KHÔNG raise")
        if await conn.fetchval("SELECT count(*) FROM orders") != n_before:
            fails.append("CR-05: order VẪN tạo dù audit hỏng (không fail-closed)")
        if await conn.fetchval("SELECT count(*) FROM command_executions "
                               "WHERE idempotency_key='carem-cr05-00001'") != 0:
            fails.append("CR-05: command row còn dù audit hỏng (rollback hỏng)")
    finally:
        await conn.close()

    if fails:
        print("CA-REMEDIATION FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("CA-REMEDIATION PASS: CR-01 manual retry attempt_no liên tục [1,2,3] delivered; "
          "CR-02 worker CAS không đè lease khác; CR-03 customer receipt durable (messenger) fail->retry->delivered; "
          "CR-04R idempotency ổn định (cùng message=1 order, message khác=order mới); "
          "CR-05 audit fail-closed rollback.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
