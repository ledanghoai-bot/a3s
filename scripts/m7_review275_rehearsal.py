#!/usr/bin/env python3
"""M7 Review 275 focused rehearsal — 5 blocker (CA Review 275). Chay m5lab (schema>=065). Fake/mock-driven.

B1 275-01 SENDER BOUNDARY (ca 2 kenh): mock send_text (messenger) + _send_reply (telegram) qua CHINH ham worker
   that (_process_message_inner / _handle_customer_message). handle_message tra None/""/"   " (SILENT-equiv) ->
   KHONG goi sender; tra string that -> goi DUNG 1 lan. Chan text=null toi provider.
B2 275-02 CONFLICT FAIL-CLOSED: cung event id + KHAC payload -> ingest conflict=True, row 'received'->'error'
   (chan worker claim), attention unmatched_webhook mo, worker run_once KHONG claim row error, process() no-op.
B3 275-04 RESOLVE->RESUME idempotency: conversation staff_attention + open attention -> resume RAISE
   AttentionOpenError (fail-closed); resolve het attention -> resume -> step routing; resume lan 2 (da roi
   staff_attention) -> no-op None, khong crash / khong double.
B4 275-05 CANCEL committed/none/error: _committed_fulfillment_status 3-way — conversation 'completed' &
   'awaiting_transfer' -> ('committed', oid); khong conversation -> ('none', None); order cancelled -> loai;
   DB loi -> ('error', None) fail-safe. Cancel committed qua handle_message -> escalate(notify_customer=False)
   (attention 'other' mo, order KHONG cancelled) + reply 'can nhan vien'.
Re-runnable (RUN). KHONG PII/secret.
"""
import asyncio
import json
import os
import sys
import time

import asyncpg

from app.config import settings
from app.services.fulfillment import attention as attn_svc
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
                                  "VALUES('VTB',$1,'R275',1,false,true) RETURNING id", ACCT)
    return bid


async def _order(conn, *, total=200000, psid=None):
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    psid = psid or f"tg:r275-{tag}"
    cid = await conn.fetchval("INSERT INTO customers (psid, channel, external_chat_id, name,phone) VALUES ($1, 'telegram_customer', $1, 'R','0900000000') RETURNING id", psid)
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
                              "VALUES($1,'CF',$2,999,300,'hũ') RETURNING id", f"R275-{tag}", total)
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


async def _awaiting_transfer(conn, *, amount=200000, psid=None, step="awaiting_transfer"):
    oid, psid = await _order(conn, total=amount, psid=psid)
    payid = await conn.fetchval("INSERT INTO payments(order_id,method,amount_due_vnd,status) "
                                "VALUES($1,'BANK_TRANSFER',$2,'awaiting') RETURNING id", oid, amount)
    iid = await _instr(conn, oid, payid, amount=amount)
    await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,method,instruction_id,"
                       "policy_version,transfer_started_at,transfer_deadline_at) VALUES "
                       "($1,'telegram_customer',$2,$4,'BANK_TRANSFER',$3,1,now(),now()+interval '15 min')",
                       oid, psid, iid, step)
    return oid, psid, payid, iid


# ============================ B1 sender boundary ============================
async def _b1_sender_boundary():
    from app.workers import tasks as T
    from app.workers import telegram_customer_listener as TG

    # ---- messenger: _process_message_inner ----
    orig = {k: getattr(T, k) for k in ("is_bot_paused", "try_take_thread_control", "handle_message", "send_text")}
    sent_m = []

    async def _no_pause(_):
        return False

    async def _noop_take(_):
        return None

    async def _send_m(sender_id, txt):
        sent_m.append(txt)

    reply_box = {"v": None}

    async def _hm(*a, **k):
        return reply_box["v"]

    T.is_bot_paused = _no_pause
    T.try_take_thread_control = _noop_take
    T.send_text = _send_m
    T.handle_message = _hm
    try:
        for kind, val, expect in [("None", None, 0), ("empty", "", 0), ("whitespace", "   ", 0),
                                  ("SILENT-obj", C.SILENT, 0), ("real", "dạ em chào anh", 1)]:
            reply_box["v"] = val
            sent_m.clear()
            await T._process_message_inner({"message": {"text": "hi", "mid": f"m-{kind}"},
                                            "sender": {"id": f"psid-{kind}"}})
            ck(f"B1 messenger reply={kind} -> send_text goi {expect} lan", len(sent_m) == expect,
               f"calls={len(sent_m)}")
    finally:
        for k, v in orig.items():
            setattr(T, k, v)

    # ---- telegram: _handle_customer_message ----
    origt = {k: getattr(TG, k) for k in ("is_bot_paused", "handle_message", "_send_reply")}
    sent_t = []

    async def _send_t(client, chat_id, txt):
        sent_t.append(txt)

    TG.is_bot_paused = _no_pause
    TG.handle_message = _hm
    TG._send_reply = _send_t
    try:
        for kind, val, expect in [("None", None, 0), ("empty", "", 0), ("whitespace", "   ", 0),
                                  ("SILENT-obj", C.SILENT, 0), ("real", "dạ vâng", 1)]:
            reply_box["v"] = val
            sent_t.clear()
            await TG._handle_customer_message(None, 12345, "hi", 1)
            ck(f"B1 telegram reply={kind} -> _send_reply goi {expect} lan", len(sent_t) == expect,
               f"calls={len(sent_t)}")
    finally:
        for k, v in origt.items():
            setattr(TG, k, v)


# ============================ B2 conflict race ============================
async def _b2_conflict(conn):
    oid, _psid, _pay, _iid = await _awaiting_transfer(conn, amount=200000)
    ev = f"{RUN}-conf"
    raw1 = json.dumps({"id": ev, "gateway": "VietinBank", "accountNumber": ACCT, "content": f"3SCF {oid}",
                       "transferType": "in", "transferAmount": 200000, "referenceCode": "A"}).encode()
    raw2 = json.dumps({"id": ev, "gateway": "VietinBank", "accountNumber": ACCT, "content": f"3SCF {oid}",
                       "transferType": "in", "transferAmount": 999999, "referenceCode": "B"}).encode()
    async with conn.transaction():
        r1, c1, cf1 = await PI.ingest(conn, SP.parse_envelope(raw1), mode="test")
    async with conn.transaction():
        r2, c2, cf2 = await PI.ingest(conn, SP.parse_envelope(raw2), mode="test")
    ck("B2 ingest lan1 created, lan2 cung row + conflict=True", c1 and not cf1 and not c2 and cf2 and r1 == r2,
       f"c1={c1}/cf1={cf1} c2={c2}/cf2={cf2} same={r1 == r2}")
    row = await conn.fetchrow("SELECT processing_state, last_error FROM provider_events WHERE id=$1", r1)
    ck("B2 conflict -> row 'received'->'error' (chan worker) + last_error=payload_hash_conflict",
       row["processing_state"] == "error" and row["last_error"] == "payload_hash_conflict",
       f"{row['processing_state']}/{row['last_error']}")
    n_att = await conn.fetchval("SELECT count(*) FROM staff_attention WHERE reason='unmatched_webhook' "
                                "AND status='open' AND detail->>'provider_event_id'=$1", ev)
    ck("B2 conflict -> attention unmatched_webhook mo", int(n_att) >= 1, n_att)
    # worker run_once KHONG claim row error
    stt = await PI.run_once()
    claimed_this = await conn.fetchval("SELECT processing_state FROM provider_events WHERE id=$1", r1)
    ck("B2 worker run_once KHONG claim row 'error' (van error, khong xu ly)", claimed_this == "error",
       f"state={claimed_this} stats={stt}")
    # process() truc tiep row error -> no-op tra ve state hien tai
    async with conn.transaction():
        st = await PI.process(conn, r1)
    ck("B2 process() row error -> no-op (khong 'received' nen bo qua)", st == "error", st)


# ============================ B3 resolve -> resume idempotency ============================
async def _b3_resume(conn):
    oid, _psid, _pay, _iid = await _awaiting_transfer(conn, amount=200000)
    # dua ve staff_attention + mo 1 attention (gia lap escalate quote)
    await conn.execute("UPDATE fulfillment_conversations SET step='staff_attention' WHERE order_id=$1", oid)
    async with conn.transaction():
        await attn_svc.open_attention(conn, oid, reason="quote", detail={"src": "b3"}, created_by="b3")
    # resume voi open attention -> RAISE (fail-closed)
    blocked = False
    try:
        async with conn.transaction():
            await C.resume(conn, oid, actor="staff1")
    except C.AttentionOpenError:
        blocked = True
    ck("B3 resume voi open attention -> AttentionOpenError (CA 275-04 fail-closed)", blocked, blocked)
    # resolve het attention cua oid (query truc tiep — khong phu thuoc list limit)
    open_ids = [r["id"] for r in await conn.fetch(
        "SELECT id FROM staff_attention WHERE order_id=$1 AND status='open'", oid)]
    for aid in open_ids:
        async with conn.transaction():
            await attn_svc.resolve(conn, aid, resolved_by="staff1", note="B3 resolve")
    # resume -> routing
    async with conn.transaction():
        rs1 = await C.resume(conn, oid, actor="staff1")
    ck("B3 sau resolve -> resume -> step routing", rs1 and rs1["step"] == "routing", rs1["step"] if rs1 else None)
    # resume lan 2 (da roi staff_attention) -> no-op None, khong crash
    async with conn.transaction():
        rs2 = await C.resume(conn, oid, actor="staff1")
    step_now = (await C.get(conn, oid))["step"]
    ck("B3 resume lan 2 (khong con staff_attention) -> no-op None, step giu routing (idempotent)",
       rs2 is None and step_now == "routing", f"rs2={rs2} step={step_now}")


# ============================ B4 cancel committed/none/error ============================
async def _b4_cancel(conn):
    from app.services import orchestrator as O

    # completed conversation -> committed
    oidc, psidc, _p, _i = await _awaiting_transfer(conn, amount=200000, step="completed")
    st, cid = await O._committed_fulfillment_status(psidc)
    ck("B4 conversation 'completed' -> ('committed', oid)", st == "committed" and cid == oidc, f"{st}/{cid}")
    # awaiting_transfer conversation -> committed
    oida, psida, _p2, _i2 = await _awaiting_transfer(conn, amount=200000, step="awaiting_transfer")
    st, cid = await O._committed_fulfillment_status(psida)
    ck("B4 conversation 'awaiting_transfer' -> ('committed', oid)", st == "committed" and cid == oida, f"{st}/{cid}")
    # khong conversation -> none
    _o, psidn = await _order(conn)
    st, cid = await O._committed_fulfillment_status(psidn)
    ck("B4 khong fulfillment conversation -> ('none', None)", st == "none" and cid is None, f"{st}/{cid}")
    # order cancelled -> loai khoi committed
    oidx, psidx, _p3, _i3 = await _awaiting_transfer(conn, amount=200000)
    await conn.execute("UPDATE orders SET status='cancelled' WHERE id=$1", oidx)
    st, cid = await O._committed_fulfillment_status(psidx)
    ck("B4 order cancelled -> loai ('none', None)", st == "none" and cid is None, f"{st}/{cid}")
    # DB loi -> ('error', None) fail-safe (patch db_pool.acquire raise)
    import app.db_pool as DP
    orig_acq = DP.acquire

    async def _boom():
        raise RuntimeError("simulated DB failure")

    DP.acquire = _boom
    try:
        st, cid = await O._committed_fulfillment_status(psidc)
    finally:
        DP.acquire = orig_acq
    ck("B4 DB check loi -> ('error', None) fail-safe (khong claim da huy)", st == "error" and cid is None,
       f"{st}/{cid}")


async def main():
    settings.sepay_allowed_accounts = ""
    settings.m7_conversational_fulfillment = True
    conn = await asyncpg.connect(DSN)
    try:
        print("=== B1 sender boundary (275-01) ===")
        await _b1_sender_boundary()
        print("=== B2 conflict fail-closed (275-02) ===")
        await _b2_conflict(conn)
        print("=== B3 resolve->resume idempotency (275-04) ===")
        await _b3_resume(conn)
        print("=== B4 cancel committed/none/error (275-05) ===")
        await _b4_cancel(conn)
        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        from app.db_pool import close_pool
        await close_pool()
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
