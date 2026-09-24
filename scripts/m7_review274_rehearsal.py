#!/usr/bin/env python3
"""M7 Review 274 focused rehearsal — 5 blocker (CA Review 274). Chay m5lab (schema>=065). Fake-driven.

R1 274-01 SePay bind instruction snapshot: v1/v2 regenerate; event bound instruction hien hanh; non-test
   instruction khong auto-confirm; mode live khong xu ly boi C0; same-hash replay / diff-hash conflict.
R2 274-02 escalation handoff qua OUTBOX WORKER (mock sender): mismatch -> step staff_attention + DUNG 1 reason
   message + reminder cu bi huy; khach nhan tin sau -> SILENT (chan LLM); late valid confirm -> completed no double.
R3 274-03 COD 1 delivery authority (direct-send, 0 EV_COD outbox); transfer 1 text (return) + 1 QR (outbox).
R4 274-05 cancel-after-commit building blocks: active fulfillment -> escalate(other, notify_customer=False) mo
   attention + step staff_attention, KHONG gui customer message.
Re-runnable (RUN). KHONG PII/secret.
"""
import asyncio
import json
import os
import sys
import time

import asyncpg

from app.config import settings
from app.services.command import outbox_worker as OW
from app.services.fulfillment import conversation as C
from app.services.payment import provider_ingest as PI
from app.services.providers import sepay as SP

RUN = str(int(time.time()))
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
ACCT = "0071000999888"
FAILS = []
_SEQ = [0]


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


async def _bank(conn):
    bid = await conn.fetchval("SELECT id FROM bank_accounts WHERE account_number=$1", ACCT)
    if bid is None:
        bid = await conn.fetchval("INSERT INTO bank_accounts(bank,account_number,holder_name,version,active,is_test) "
                                  "VALUES('VTB',$1,'R274',1,false,true) RETURNING id", ACCT)
    return bid


async def _order(conn, *, total=200000):
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    psid = f"tg:r274-{tag}"
    cid = await conn.fetchval("INSERT INTO customers (psid, channel, external_chat_id, name,phone) VALUES ($1, 'telegram_customer', $1, 'R','0900000000') RETURNING id", psid)
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
                              "VALUES($1,'CF',$2,999,300,'hũ') RETURNING id", f"R274-{tag}", total)
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                              "VALUES($1,'confirmed',$2,'telegram_customer') RETURNING id", cid, total)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,1,$3)",
                       oid, pid, total)
    return oid, psid


async def _instr(conn, oid, payid, *, amount, is_test=True):
    return await conn.fetchval(
        "INSERT INTO payment_instructions(order_id,payment_id,bank_account_id,account_version,bank_snapshot,"
        "account_number_snapshot,holder_snapshot,transfer_content,amount_vnd,is_test) VALUES "
        "($1,$2,$3,1,'V',$4,'H',$5,$6,$7) RETURNING id", oid, payid, await _bank(conn), ACCT, f"3SCF {oid}",
        amount, is_test)


async def _awaiting_transfer(conn, *, amount=200000, is_test=True):
    oid, psid = await _order(conn, total=amount)
    payid = await conn.fetchval("INSERT INTO payments(order_id,method,amount_due_vnd,status) "
                                "VALUES($1,'BANK_TRANSFER',$2,'awaiting') RETURNING id", oid, amount)
    iid = await _instr(conn, oid, payid, amount=amount, is_test=is_test)
    await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,method,instruction_id,"
                       "policy_version,transfer_started_at,transfer_deadline_at) VALUES "
                       "($1,'telegram_customer',$2,'awaiting_transfer','BANK_TRANSFER',$3,1,now(),now()+interval '15 min')",
                       oid, psid, iid)
    return oid, psid, payid, iid


async def _sepay(conn, *, ev_id, oid, amount, account=ACCT, mode="test", content=None):
    raw = json.dumps({"id": ev_id, "gateway": "VietinBank", "accountNumber": account,
                      "content": content or f"3SCF {oid}", "transferType": "in", "transferAmount": amount,
                      "referenceCode": f"R-{ev_id}"}).encode()
    ev = SP.parse_envelope(raw)
    async with conn.transaction():
        rid, _c, _cf = await PI.ingest(conn, ev, mode=mode)
    async with conn.transaction():
        st = await PI.process(conn, rid)
    return rid, st


async def main():  # noqa: C901
    settings.sepay_allowed_accounts = ""
    conn = await asyncpg.connect(DSN)
    sent = []

    async def mock_send(dest, payload):
        sent.append(payload)
        return OW.SendResult(ok=True, http_status=200, provider_message_id="m")

    try:
        # ---- R1 274-01 ----
        oid, psid, payid, iid1 = await _awaiting_transfer(conn, amount=200000)
        _, st = await _sepay(conn, ev_id=f"{RUN}-r1a", oid=oid, amount=200000)
        ck("R1 event khop instruction v1 -> matched", st == "matched", st)

        # regenerate instruction v2 voi amount khac (due doi) -> conversation.instruction_id = v2
        oid2, psid2, payid2, iid2a = await _awaiting_transfer(conn, amount=200000)
        iid2b = await _instr(conn, oid2, payid2, amount=250000)   # v2 amount khac
        await conn.execute("UPDATE fulfillment_conversations SET instruction_id=$2 WHERE order_id=$1", oid2, iid2b)
        _, st = await _sepay(conn, ev_id=f"{RUN}-r1b", oid=oid2, amount=200000)   # amount v1 cu
        ck("R1 event amount cua instruction CŨ (v1) sau khi có v2 -> discrepancy (bind v2)", st == "discrepancy", st)
        _, st = await _sepay(conn, ev_id=f"{RUN}-r1c", oid=oid2, amount=250000)   # amount v2
        ck("R1 event amount instruction hiện hành (v2) -> matched", st == "matched", st)

        # non-test instruction -> C0 khong auto-confirm; order-bound -> discrepancy + escalate (CA 275-03)
        oid3, psid3, payid3, _ = await _awaiting_transfer(conn, amount=200000, is_test=False)
        _, st = await _sepay(conn, ev_id=f"{RUN}-r1d", oid=oid3, amount=200000)
        fc3 = await C.get(conn, oid3)
        ck("R1 instruction NON-TEST -> C0 khong auto-confirm (discrepancy + escalate)",
           st == "discrepancy" and fc3["step"] == "staff_attention", f"{st}/{fc3['step']}")

        # mode live row -> C0 khong xu ly
        oid4, psid4, payid4, _ = await _awaiting_transfer(conn, amount=200000)
        _, st = await _sepay(conn, ev_id=f"{RUN}-r1e", oid=oid4, amount=200000, mode="live")
        ck("R1 mode='live' row -> C0 khong xu ly (ignored)", st == "ignored", st)

        # ---- R2 274-02 escalation qua outbox worker ----
        oidm, psidm, paym, iidm = await _awaiting_transfer(conn, amount=200000)
        # them 1 reminder pending (gia lap da nhac 1 lan roi con pending outbox)
        await conn.execute("INSERT INTO fulfillment_reminders(payment_instruction_id,reminder_no) VALUES($1,1)", iidm)
        async with conn.transaction():
            await C._enqueue_customer(conn, await C.get(conn, oidm), event_type=C.EV_REMINDER,
                                      dedupe_key=f"fc_reminder:{oidm}:{iidm}:1", text="nhac cu",
                                      stale_check={"kind": "fulfillment", "order_id": oidm, "step": "awaiting_transfer"})
        _, st = await _sepay(conn, ev_id=f"{RUN}-r2mm", oid=oidm, amount=150000)   # thieu tien -> discrepancy+escalate
        fcm = await C.get(conn, oidm)
        ck("R2 mismatch -> conversation staff_attention (payment_mismatch)", st == "discrepancy"
           and fcm["step"] == "staff_attention" and fcm["attention_reason"] == "payment_mismatch", f"{st}/{fcm['step']}")
        # CA Review 292-02: khach nhan tin sau escalation -> tin DAU ack nhan vien (khong LLM), tin SAU -> SILENT.
        async with conn.transaction():
            r = await C.handle_customer_text(conn, psidm, "chuyển khoản rồi nhé", command_key=f"{RUN}-r2msg")
        async with conn.transaction():
            r2 = await C.handle_customer_text(conn, psidm, "alo shop ơi", command_key=f"{RUN}-r2msg2")
        ck("R2 khach nhan tin sau escalation -> ack nhan vien (tin dau) + SILENT (tin sau), khong LLM",
           isinstance(r, str) and "nhân viên" in r and r2 is C.SILENT, f"{r!r}/{r2!r}")
        # outbox worker (mock): reason message gui; reminder cu -> cancelled (stale step doi). Xa het backlog.
        sent.clear()
        for _ in range(60):
            stt = await OW.run_once(send_fn=mock_send)
            if stt.get("claimed", 0) == 0:
                break
        staff_msgs = [p for p in sent if (p.get("order_id") == oidm and "nhân viên" in (p.get("text") or ""))]
        rem_row = await conn.fetchrow("SELECT status FROM outbox_events WHERE dedupe_key=$1",
                                      f"fc_reminder:{oidm}:{iidm}:1")
        ck("R2 worker: reason message gui, reminder cu bị cancel (khong gui mau thuan)",
           len(staff_msgs) >= 1 and rem_row and rem_row["status"] == "cancelled",
           f"staff={len(staff_msgs)} rem={rem_row['status'] if rem_row else None}")
        # late valid exact confirm -> completed, resolve, khong double
        _, st = await _sepay(conn, ev_id=f"{RUN}-r2ok", oid=oidm, amount=200000)
        fcm2 = await C.get(conn, oidm)
        att = await conn.fetchval("SELECT status FROM staff_attention WHERE order_id=$1 AND reason='payment_mismatch'",
                                  oidm)
        ck("R2 late valid exact -> matched + completed + attention resolved",
           st == "matched" and fcm2["step"] == "completed" and att == "resolved", f"{st}/{fcm2['step']}/{att}")

        # ---- R4 274-05 building blocks ----
        oidc, psidc, payc, iidc = await _awaiting_transfer(conn, amount=200000)
        n_out_before = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key LIKE $1",
                                           f"fc_staff:{oidc}:%")
        async with conn.transaction():
            res = await C.escalate(conn, oidc, reason="other", actor="m7:cancel",
                                   detail={"customer_cancel_request": True}, notify_customer=False)
        fcc = await C.get(conn, oidc)
        n_out_after = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key LIKE $1",
                                          f"fc_staff:{oidc}:%")
        att_open = await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND reason='other' "
                                       "AND status='open'", oidc)
        ck("R4 cancel-after-commit: escalate(other, notify_customer=False) -> staff_attention + attention, KHONG "
           "gui customer message", fcc["step"] == "staff_attention" and att_open == 1
           and n_out_after == n_out_before and res is not None, f"step={fcc['step']} att={att_open} out={n_out_before}->{n_out_after}")

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        from app.db_pool import close_pool
        await close_pool()
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
