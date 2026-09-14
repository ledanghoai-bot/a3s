"""M7 Conversational Fulfillment — DB rehearsal (CA Directive 272 §5). Chay tren m5lab (schema >= 065, throwaway).

Chung minh qua SERVICE THAT (conversation/shipment/payment/provider_ingest/attention) + DB:
 G1 Routing: allowlist -> SELF (fee 0) / ngoai list -> GHN (flag OFF -> quote_required + attention) / khong snapshot ->
    MANUAL + attention address / doi version KHONG doi snapshot quote cu.
 G2 COD: ensure_started -> advance_routing -> prompt outbox -> "COD" -> cod_handoff + payment COD due=goods+fee;
    duplicate inbound -> cung reply, 1 payment, 1 cod notify.
 G3 CK: "chuyen khoan" -> awaiting_transfer + instruction bat bien + VietQR decode khop; duplicate -> 1 instruction;
    "da chuyen" -> reported (khong notify trung); shop confirm -> confirmed + 1 notify + conversation completed.
 G4 Mo ho: "ok" x3 -> 2 lan hoi lai, lan 3 -> staff_attention(method).
 G5 Doi method: CK->COD khi awaiting (cho phep) ; COD->CK (instruction version 2) ; sau evidence -> staff.
 G6 Timeout: qua han -> DUNG 1 reminder + attention timeout; run lai -> 0; provider confirm sau timeout -> completed +
    attention auto-resolved, KHONG notify mau thuan.
 G7 SePay C0 matrix: exact / duplicate id / retry / concurrent duplicate / out-of-order / partial / excess / code
    missing / code multiple / wrong account / direction out / order not found / closed payment.
 G8 Money: weight thieu -> fee unknown -> due NULL -> staff_attention(quote), khach chon CK -> khong effect.
 G9 Truthfulness: khong text "da xac nhan nhan thanh toan" truoc confirmed; confirmed dung 1 notify.
 G10 Resume: staff manual quote + resume -> prompt dung phi thu cong (khong bi re-route ghi de).
 G11 Requote sau prompt -> staff_attention(quote).
 G12 Stale-check kind=fulfillment.
Fixture tag m7-<RUN>; bank fixture is_test (can M6_TEST_DB=1). Khong dung production.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import asyncpg

from app.config import settings
from app.services.command import outbox_worker as ow
from app.services.fulfillment import conversation as fc
from app.services.fulfillment import shipment_service as ship
from app.services.payment import payment_service as pay
from app.services.payment import provider_ingest as pi
from app.services.payment import vietqr as vq
from app.services.providers import sepay as sp

DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
RUN = str(int(time.time()))
_SEQ = [0]
FAILS: list[str] = []
BIN, ACCT = "970415", "0071000123456"


def ck(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' :: ' + str(extra)) if extra else ''}")
    if not cond:
        FAILS.append(name)


async def _mk_order(conn, *, ward: str | None, weight: int | None, qty=2, price=100000):
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    psid = f"tg:m7-{tag}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'Test M7','0900000000') RETURNING id", psid)
    pid = await conn.fetchval(
        "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) VALUES($1,'CF M7',$2,999,$3,'hũ') "
        "RETURNING id", f"M7-{tag}", price, weight)
    total = qty * price
    oid = await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',$2,'telegram_customer') "
        "RETURNING id", cid, total)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,$3,$4)",
                       oid, pid, qty, price)
    if ward is not None:
        rid = await conn.fetchval(
            "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
            "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,'66',$1,'current',1.0) RETURNING id",
            ward)
        await conn.execute(
            "INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,dataset_version,"
            "verification_method,bound_by) VALUES($1,$2,'66',$3,'VN-ADMIN-2025-07-v2','test','rehearsal')", oid, rid, ward)
    return oid, psid, total


async def _start(conn, oid, psid, *, ghn=None):
    async with conn.transaction():
        created = await fc.ensure_started(conn, oid, channel="telegram_customer", customer_ref=psid,
                                          command_key=f"start:{RUN}:{oid}")
        out = await fc.advance_routing(conn, oid, ghn_result=ghn)
    return created, out


async def _say(conn, psid, text, key):
    async with conn.transaction():
        return await fc.handle_customer_text(conn, psid, text, command_key=f"msg:{RUN}:{key}")


async def _outbox(conn, oid, event_type=None):
    rows = await conn.fetch(
        "SELECT event_type, dedupe_key, payload, status FROM outbox_events WHERE (payload->>'order_id')::bigint=$1 "
        "AND ($2::text IS NULL OR event_type=$2) ORDER BY created_at", oid, event_type)
    out = []
    for r in rows:
        p = r["payload"]
        if isinstance(p, str):
            p = json.loads(p)
        out.append({"event_type": r["event_type"], "dedupe_key": r["dedupe_key"], "payload": p, "status": r["status"]})
    return out


async def _attn(conn, oid, reason=None):
    return [dict(r) for r in await conn.fetch(
        "SELECT id, reason, status FROM staff_attention WHERE order_id=$1 AND ($2::text IS NULL OR reason=$2) ORDER BY id",
        oid, reason)]


async def _sepay(conn, *, ev_id, order_id, amount, account=ACCT, direction="in", content=None, code=None):
    raw = json.dumps({"id": ev_id, "gateway": "VietinBank", "transactionDate": "2026-09-13 21:00:00",
                      "accountNumber": account, "code": code,
                      "content": content if content is not None else f"3SCF {order_id} test",
                      "transferType": direction, "transferAmount": amount, "referenceCode": f"REF-{RUN}-{ev_id}"}).encode()
    ev = sp.parse_envelope(raw)
    async with conn.transaction():
        rid, created = await pi.ingest(conn, ev, mode="test")
    async with conn.transaction():
        st = await pi.process(conn, rid)
    return rid, created, st


async def main() -> int:
    if os.environ.get("M6_TEST_DB") != "1":
        print("can M6_TEST_DB=1 (khang dinh DB throwaway) — bank fixture is_test")
        return 2
    settings.m7_conversational_fulfillment = True
    settings.m7_sepay_test_connector = True
    settings.m7_ghn_quote = False
    settings.sepay_allowed_accounts = ""
    conn = await asyncpg.connect(DSN)
    try:
        # idempotency across re-runs: don awaiting_transfer ton dong -> completed (khoi nhieu run_due chen G6)
        await conn.execute("UPDATE fulfillment_conversations SET step='completed', completed_at=now() "
                           "WHERE step='awaiting_transfer'")
        # ---- fixture bank (is_test, co BIN) ----
        async with conn.transaction():
            bank = await pay.set_bank_account(conn, bank="VietinBank (TEST)", account_number=ACCT,
                                              holder_name=f"ROBANME TEST [M7:{RUN}]", actor=f"m7:{RUN}",
                                              is_test=True, bin_code=BIN)
        ck("fixture bank is_test + bin", bank["is_test"] and bank["bin"] == BIN)
        ver = await conn.fetchval("SELECT max(version) FROM delivery_routing_versions WHERE effective_from<=now() "
                                  "AND (effective_to IS NULL OR effective_to>now())")
        ck("G1 seed routing version hieu luc", ver is not None, ver)

        # ================= G1 Routing =================
        o_self, p_self, t_self = await _mk_order(conn, ward="24121", weight=300)
        o_ghn, p_ghn, _ = await _mk_order(conn, ward="24316", weight=300)
        o_nosnap, p_nosnap, _ = await _mk_order(conn, ward=None, weight=300)
        async with conn.transaction():
            r1 = await ship.route_and_quote(conn, o_self, actor="t")
            r2 = await ship.route_and_quote(conn, o_ghn, actor="t")
            r3 = await ship.route_and_quote(conn, o_nosnap, actor="t")
        ck("G1 allowlist ward -> SELF_DELIVERY fee 0 quoted", r1["routing_source"] == "SELF_DELIVERY" and
           r1["fee_status"] == "quoted" and r1["delivery_fee_vnd"] == 0 and r1["routing_version"] == ver,
           f"{r1['routing_source']}/{r1['fee_status']}/{r1['delivery_fee_vnd']}/v{r1['routing_version']}")
        ck("G1 ngoai allowlist -> GHN, flag OFF -> quote_required (khong 0d) + attention quote",
           r2["routing_source"] == "GHN" and r2["fee_status"] == "quote_required" and r2["delivery_fee_vnd"] is None
           and r2["attention_reason"] == "quote" and len(await _attn(conn, o_ghn, "quote")) == 1,
           f"{r2['routing_source']}/{r2['fee_status']}/{json.loads(r2['quote_snapshot'])['fee'].get('reason')}")
        ck("G1 khong snapshot -> MANUAL_REVIEW + attention address",
           r3["routing_source"] == "MANUAL_REVIEW" and r3["fee_status"] == "quote_required"
           and len(await _attn(conn, o_nosnap, "address")) == 1, r3["routing_reason"])
        ck("G1 quote_snapshot mang route/version/inputs/quoted_at",
           r1["quoted_at"] is not None and json.loads(r1["quote_snapshot"])["route"]["ward_code"] == "24121")
        # doi version: v(ver+1) them 24316 -> don MOI SELF; snapshot cu giu v cu + quote cu
        newv = (await conn.fetchval("SELECT max(version) FROM delivery_routing_versions")) + 1
        await conn.execute(
            "INSERT INTO delivery_routing_versions(version,effective_from,dataset_version,note,created_by) "
            "VALUES($1,now()-interval '1 second','VN-ADMIN-2025-07-v2','rehearsal','m7:test') ON CONFLICT DO NOTHING", newv)
        await conn.execute("INSERT INTO delivery_self_wards(routing_version,province_code,ward_code,ward_name) "
                           "SELECT $1,province_code,ward_code,ward_name FROM delivery_self_wards WHERE routing_version=$2 "
                           "ON CONFLICT DO NOTHING", newv, ver)
        await conn.execute("INSERT INTO delivery_self_wards(routing_version,province_code,ward_code,ward_name) "
                           "VALUES($1,'66','24316','Xa Pong Drang (rehearsal)') ON CONFLICT DO NOTHING", newv)
        o_ghn2, _, _ = await _mk_order(conn, ward="24316", weight=300)
        async with conn.transaction():
            r4 = await ship.route_and_quote(conn, o_ghn2, actor="t")
        old = await conn.fetchrow("SELECT routing_source, routing_version, fee_status FROM shipments WHERE order_id=$1", o_ghn)
        ck("G1 version moi -> don moi SELF v+1; don cu giu snapshot GHN v cu",
           r4["routing_source"] == "SELF_DELIVERY" and r4["routing_version"] == newv and old["routing_source"] == "GHN"
           and old["routing_version"] == ver, f"new v{r4['routing_version']} old v{old['routing_version']}")
        await conn.execute("UPDATE delivery_routing_versions SET effective_to=now() WHERE version=$1", newv)

        # ================= G2 COD =================
        o2, p2, t2 = await _mk_order(conn, ward="24133", weight=300)
        created, out = await _start(conn, o2, p2)
        ck("G2 ensure_started + advance_routing -> awaiting_method", created and out and out["step"] == "awaiting_method")
        created2, out2 = await _start(conn, o2, p2)
        ck("G2 start lai -> idempotent (khong tao/khong advance)", not created2 and out2 is None)
        prompts = await _outbox(conn, o2, fc.EV_PROMPT)
        ck("G2 prompt outbox dung 1, mang tong tien = goods+fee", len(prompts) == 1 and f"TỔNG {t2:,}".replace(",", ".") in prompts[0]["payload"]["text"],
           prompts[0]["payload"]["text"][:80] if prompts else "none")
        rep = await _say(conn, p2, "COD nhé", "g2-1")
        c2 = await fc.get(conn, o2)
        pay2 = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", o2)
        ck("G2 'COD' -> cod_handoff + payment COD due = goods + 0", c2["step"] == "cod_handoff" and c2["method"] == "COD"
           and pay2 and pay2["method"] == "COD" and pay2["amount_due_vnd"] == t2, f"{c2['step']} due={pay2['amount_due_vnd'] if pay2 else None}")
        rep_dup = await _say(conn, p2, "COD nhé", "g2-1")
        n_pay = await conn.fetchval("SELECT count(*) FROM payments WHERE order_id=$1", o2)
        ck("G2 duplicate inbound (cung command_key) -> cung reply, 1 payment, 1 cod notify",
           rep_dup == rep and n_pay == 1 and len(await _outbox(conn, o2, fc.EV_COD)) == 1)
        ck("G2 reply COD khong noi da nhan tien", "đã nhận thanh toán" not in rep.lower() and "COD" in rep)

        # ================= G3 CK + VietQR =================
        o3, p3, t3 = await _mk_order(conn, ward="24154", weight=300)
        await _start(conn, o3, p3)
        rep3 = await _say(conn, p3, "chuyển khoản", "g3-1")
        c3 = await fc.get(conn, o3)
        instr = await conn.fetchrow("SELECT * FROM payment_instructions WHERE order_id=$1 ORDER BY id DESC LIMIT 1", o3)
        ck("G3 'chuyen khoan' -> awaiting_transfer + deadline 30' + instruction", c3["step"] == "awaiting_transfer"
           and c3["instruction_id"] == instr["id"] and c3["transfer_deadline_at"] is not None)
        d = vq.decode(instr["qr_payload"])
        ck("G3 VietQR decode khop BIN/account(0 dau)/amount/content + CRC", d.crc_ok and d.bin_code == BIN and
           d.account_number == ACCT and d.amount_vnd == t3 and d.add_info == f"3SCF {o3}", f"{d.account_number}/{d.amount_vnd}/{d.add_info}")
        png = vq.png_bytes(instr["qr_payload"])
        ck("G3 PNG QR sinh duoc (segno)", png is not None and png[:4] == b"\x89PNG")
        qr_ev = await _outbox(conn, o3, fc.EV_INSTRUCTION)
        ck("G3 outbox instruction.notify 1 event mang qr_payload + nhan TEST", len(qr_ev) == 1 and
           qr_ev[0]["payload"].get("qr_payload") == instr["qr_payload"] and "TEST" in qr_ev[0]["payload"]["text"])
        ck("G3 reply instruction co so TK/so tien/noi dung + nhan TEST", ACCT in rep3 and f"3SCF {o3}" in rep3 and "TEST" in rep3)
        rep3d = await _say(conn, p3, "chuyển khoản", "g3-1")
        n_instr = await conn.fetchval("SELECT count(*) FROM payment_instructions WHERE order_id=$1", o3)
        ck("G3 duplicate inbound -> 1 instruction, cung reply", rep3d == rep3 and n_instr == 1)
        # doi active bank -> instruction cu giu nguyen
        async with conn.transaction():
            await pay.set_bank_account(conn, bank="VietinBank (TEST 2)", account_number="0099000000001",
                                       holder_name=f"ROBANME TEST2 [M7:{RUN}]", actor=f"m7:{RUN}", is_test=True, bin_code=BIN)
        instr_after = await conn.fetchrow("SELECT account_number_snapshot, qr_payload FROM payment_instructions WHERE id=$1", instr["id"])
        ck("G3 doi active bank KHONG sua instruction/QR cu", instr_after["account_number_snapshot"] == ACCT and
           instr_after["qr_payload"] == instr["qr_payload"])
        async with conn.transaction():
            await pay.set_bank_account(conn, bank="VietinBank (TEST)", account_number=ACCT,
                                       holder_name=f"ROBANME TEST [M7:{RUN}]", actor=f"m7:{RUN}", is_test=True, bin_code=BIN)
        rep3r = await _say(conn, p3, "em đã chuyển rồi", "g3-2")
        st3 = await conn.fetchval("SELECT status FROM payments WHERE order_id=$1", o3)
        ck("G3 'da chuyen' -> reported, reply ack, KHONG notify check_request trung (notify=False)",
           st3 == "reported" and "đang kiểm tra" in rep3r and len(await _outbox(conn, o3, "payment.check_request.notify")) == 0)
        before_conf = [e["payload"]["text"] for e in await _outbox(conn, o3)]
        ck("G9 truoc confirmed: khong outbox text 'da xac nhan nhan thanh toan'",
           all("đã xác nhận nhận thanh toán" not in t for t in before_conf))
        async with conn.transaction():
            res = await pay.record_evidence(conn, o3, kind="shop_confirmed_received", amount_vnd=t3, recorded_by="po",
                                            command_key=f"{RUN}:conf-{o3}")
        c3b = await fc.get(conn, o3)
        ck("G3 shop confirm du tien -> confirmed + conversation completed + dung 1 payment.confirmed notify",
           res["status"] == "confirmed" and c3b["step"] == "completed" and
           len(await _outbox(conn, o3, "payment.confirmed.notify")) == 1)

        # ================= G4 Mo ho =================
        o4, p4, _ = await _mk_order(conn, ward="24163", weight=300)
        await _start(conn, o4, p4)
        r41 = await _say(conn, p4, "ok", "g4-1")
        r42 = await _say(conn, p4, "cod hay ck cũng được", "g4-2")
        c4 = await fc.get(conn, o4)
        ck("G4 mo ho x2 -> hoi lai, van awaiting_method", "chưa rõ" in r41 and "chưa rõ" in r42 and c4["step"] == "awaiting_method"
           and c4["method_prompts"] == 2)
        r43 = await _say(conn, p4, "sao cũng được", "g4-3")
        c4 = await fc.get(conn, o4)
        ck("G4 mo ho lan 3 -> staff_attention(method) + attention open", c4["step"] == "staff_attention" and
           c4["attention_reason"] == "method" and len(await _attn(conn, o4, "method")) == 1 and "nhân viên" in r43)
        ck("G4 text khong lien quan khi awaiting -> None (luong cu)", (await _say(conn, p2, "shop có cà phê hạt không", "g4-x")) is None)

        # ================= G5 Doi method =================
        o5, p5, t5 = await _mk_order(conn, ward="24169", weight=300)
        await _start(conn, o5, p5)
        await _say(conn, p5, "ck", "g5-1")
        r52 = await _say(conn, p5, "thôi cho em COD", "g5-2")
        c5 = await fc.get(conn, o5)
        pay5 = await conn.fetchrow("SELECT method, status FROM payments WHERE order_id=$1", o5)
        ck("G5 CK->COD khi awaiting (chua evidence) -> cod_handoff, payment COD", c5["step"] == "cod_handoff" and
           pay5["method"] == "COD" and "COD" in r52)
        r53 = await _say(conn, p5, "đổi lại chuyển khoản", "g5-3")
        c5 = await fc.get(conn, o5)
        iv = await conn.fetchval("SELECT max(instruction_version) FROM payment_instructions WHERE order_id=$1", o5)
        ck("G5 COD->CK -> awaiting_transfer, instruction version 2 (row moi, khong sua cu)", c5["step"] == "awaiting_transfer"
           and iv == 2 and ACCT in r53)
        await _say(conn, p5, "đã chuyển", "g5-4")
        r55 = await _say(conn, p5, "COD", "g5-5")
        c5 = await fc.get(conn, o5)
        ck("G5 doi method SAU evidence (reported) -> staff_attention(method)", c5["step"] == "staff_attention" and
           len(await _attn(conn, o5, "method")) == 1 and "nhân viên" in r55)

        # ================= G6 Timeout =================
        o6, p6, t6 = await _mk_order(conn, ward="24121", weight=300)
        await _start(conn, o6, p6)
        await _say(conn, p6, "chuyển khoản", "g6-1")
        # (Chi tiet timeline moc t+7/t+13/t+15 + fake clock o scripts/m7_amendment273_rehearsal.py; day la tich hop e2e)
        async with conn.transaction():
            s0 = await fc.run_due(conn)
        ck("G6 truoc moc -> khong nhac/escalate", s0["reminded"] == 0 and s0["escalated"] == 0
           and (await fc.get(conn, o6))["step"] == "awaiting_transfer")
        # ep qua timeout: transfer_started_at = now - 16' (> t+15 CA 273)
        await conn.execute("UPDATE fulfillment_conversations SET transfer_started_at=now()-interval '16 minutes' "
                           "WHERE order_id=$1", o6)
        async with conn.transaction():
            s1 = await fc.run_due(conn)
        c6 = await fc.get(conn, o6)
        ck("G6 qua timeout -> escalate payment_timeout, khong huy don", s1["escalated"] >= 1
           and c6["step"] == "staff_attention" and len(await _attn(conn, o6, "payment_timeout")) == 1
           and (await conn.fetchval("SELECT status FROM orders WHERE id=$1", o6)) == "confirmed")
        async with conn.transaction():
            s2 = await fc.run_due(conn)
        ck("G6 run lai -> khong double escalate", s2["escalated"] == 0)
        # provider confirm SAU timeout -> confirmed, completed, attention payment_timeout auto-resolved, 1 notify
        rid6, cr6, st6 = await _sepay(conn, ev_id=f"{RUN}-6", order_id=o6, amount=t6)
        c6 = await fc.get(conn, o6)
        a6 = await _attn(conn, o6, "payment_timeout")
        ck("G6 provider exact match sau timeout -> matched/confirmed/completed + attention auto-resolved + 1 notify",
           st6 == "matched" and (await conn.fetchval("SELECT status FROM payments WHERE order_id=$1", o6)) == "confirmed"
           and c6["step"] == "completed" and a6 and a6[0]["status"] == "resolved"
           and len(await _outbox(conn, o6, "payment.confirmed.notify")) == 1, f"{st6}/{c6['step']}")

        # ================= G7 SePay matrix =================
        o7, p7, t7 = await _mk_order(conn, ward="24133", weight=300)
        await _start(conn, o7, p7)
        await _say(conn, p7, "chuyển khoản", "g7-1")
        # partial
        _, _, st = await _sepay(conn, ev_id=f"{RUN}-7a", order_id=o7, amount=t7 - 10000)
        ck("G7 thieu tien -> discrepancy state + attention payment_mismatch, payment van awaiting (khong auto-confirm)",
           st == "discrepancy" and (await conn.fetchval("SELECT status FROM payments WHERE order_id=$1", o7)) == "awaiting"
           and len(await _attn(conn, o7, "payment_mismatch")) == 1)
        _, _, st = await _sepay(conn, ev_id=f"{RUN}-7b", order_id=o7, amount=t7 + 5000)
        ck("G7 thua tien -> discrepancy, khong auto-confirm", st == "discrepancy" and
           (await conn.fetchval("SELECT status FROM payments WHERE order_id=$1", o7)) == "awaiting")
        rid7c, _, st = await _sepay(conn, ev_id=f"{RUN}-7c", order_id=o7, amount=t7, content="chuyen tien ca phe")
        n_att_7c = await conn.fetchval("SELECT count(*) FROM staff_attention WHERE reason='unmatched_webhook' AND status='open' "
                                       "AND detail->>'provider_event_id'=$1", f"{RUN}-7c")
        ck("G7 thieu ma -> unmatched + attention unmatched_webhook (khong gan don)", st == "unmatched" and n_att_7c == 1)
        _, _, st = await _sepay(conn, ev_id=f"{RUN}-7d", order_id=o7, amount=t7, content=f"3SCF {o7} 3SCF {o6}")
        ck("G7 trung/nhieu ma -> unmatched", st == "unmatched")
        _, _, st = await _sepay(conn, ev_id=f"{RUN}-7e", order_id=o7, amount=t7, account="0000000000")
        ck("G7 sai account -> unmatched", st == "unmatched")
        _, _, st = await _sepay(conn, ev_id=f"{RUN}-7f", order_id=o7, amount=t7, direction="out")
        ck("G7 tien ra -> ignored", st == "ignored")
        _, _, st = await _sepay(conn, ev_id=f"{RUN}-7g", order_id=999999999, amount=t7)
        ck("G7 khong tim thay don -> unmatched", st == "unmatched")
        rid, cr, st = await _sepay(conn, ev_id=f"{RUN}-7h", order_id=o7, amount=t7)
        ck("G7 exact -> matched + confirmed + completed", st == "matched" and
           (await conn.fetchval("SELECT status FROM payments WHERE order_id=$1", o7)) == "confirmed"
           and (await fc.get(conn, o7))["step"] == "completed")
        rid2, cr2, st2 = await _sepay(conn, ev_id=f"{RUN}-7h", order_id=o7, amount=t7)
        n_ev = await conn.fetchval("SELECT count(*) FROM payment_events WHERE payment_id=(SELECT id FROM payments WHERE order_id=$1) "
                                   "AND kind='bank_auto_confirmed'", o7)
        ck("G7 duplicate event id (retry) -> ingest duplicate, cung row, 1 bank_auto_confirmed, 1 notify",
           rid2 == rid and not cr2 and st2 == "matched" and n_ev == 1 and
           len(await _outbox(conn, o7, "payment.confirmed.notify")) == 1)
        _, _, st = await _sepay(conn, ev_id=f"{RUN}-7i", order_id=o7, amount=t7)
        ck("G7 event khac id sau khi da confirmed (out-of-order/closed) -> unmatched, khong 2 effect",
           st == "unmatched" and (await conn.fetchval("SELECT amount_received_vnd FROM payments WHERE order_id=$1", o7)) == t7)
        # concurrent duplicate ingest (2 connection)
        o7c, p7c, t7c = await _mk_order(conn, ward="24133", weight=300)
        await _start(conn, o7c, p7c)
        await _say(conn, p7c, "ck", "g7c-1")
        raw = json.dumps({"id": f"{RUN}-7conc", "accountNumber": ACCT, "content": f"3SCF {o7c}", "transferType": "in",
                          "transferAmount": t7c, "referenceCode": f"REF-{RUN}-conc"}).encode()
        ev = sp.parse_envelope(raw)

        async def _ing():
            c = await asyncpg.connect(DSN)
            try:
                async with c.transaction():
                    return await pi.ingest(c, ev, mode="test")
            finally:
                await c.close()
        outs = await asyncio.gather(_ing(), _ing(), _ing())
        ck("G7 concurrent duplicate ingest -> dung 1 created, cung id", sum(1 for _, c in outs if c) == 1 and
           len({r for r, _ in outs}) == 1)
        async with conn.transaction():
            st = await pi.process(conn, outs[0][0])
        async with conn.transaction():
            st_again = await pi.process(conn, outs[0][0])
        ck("G7 process 2 lan cung row -> matched, lan 2 no-op", st == "matched" and st_again == "matched" and
           (await conn.fetchval("SELECT count(*) FROM payment_events WHERE payment_id=(SELECT id FROM payments WHERE order_id=$1)", o7c)) == 1)
        # run_once worker path (db_pool) — event received con lai? (tao 1 event received moi)
        o7w, p7w, t7w = await _mk_order(conn, ward="24133", weight=300)
        await _start(conn, o7w, p7w)
        await _say(conn, p7w, "ck", "g7w-1")
        raw = json.dumps({"id": f"{RUN}-7w", "accountNumber": ACCT, "content": f"3SCF {o7w}", "transferType": "in",
                          "transferAmount": t7w, "referenceCode": f"REF-{RUN}-w"}).encode()
        async with conn.transaction():
            await pi.ingest(conn, sp.parse_envelope(raw), mode="test")
        stw = await pi.run_once()
        ck("G7 run_once (worker path) xu ly event received -> matched", stw.get("matched", 0) >= 1 and
           (await conn.fetchval("SELECT processing_state FROM provider_events WHERE provider_event_id=$1", f"{RUN}-7w")) == "matched", stw)

        # ================= G8 Money unknown =================
        o8, p8, _ = await _mk_order(conn, ward="24121", weight=None)
        _, out8 = await _start(conn, o8, p8)
        pay8 = await conn.fetchrow("SELECT amount_due_vnd FROM payments WHERE order_id=$1", o8)
        ck("G8 weight thieu -> fee unknown -> staff_attention(quote), khong prompt tong, khong 0d",
           out8["step"] == "staff_attention" and out8["attention_reason"] == "quote" and
           len(await _outbox(conn, o8, fc.EV_PROMPT)) == 0 and (pay8 is None or pay8["amount_due_vnd"] is None))
        ck("G8 khach chon CK khi staff_attention -> None (khong tao instruction)", (await _say(conn, p8, "chuyển khoản", "g8-1")) is None
           and (await conn.fetchval("SELECT count(*) FROM payment_instructions WHERE order_id=$1", o8)) == 0)

        # ================= G10 Resume voi manual quote =================
        async with conn.transaction():
            await ship.set_manual_quote(conn, o_ghn, actor="staff1", fee_vnd=25000, eta_text="2-3 ngày")
        async with conn.transaction():
            await fc.ensure_started(conn, o_ghn, channel="telegram_customer", customer_ref=p_ghn, command_key=f"start:{RUN}:{o_ghn}")
            await conn.execute("UPDATE fulfillment_conversations SET step='staff_attention' WHERE order_id=$1", o_ghn)
            rs = await fc.resume(conn, o_ghn, actor="staff1")
        async with conn.transaction():
            out10 = await fc.advance_routing(conn, o_ghn)
        sh10 = await conn.fetchrow("SELECT delivery_fee_vnd, quote_source FROM shipments WHERE order_id=$1", o_ghn)
        pr10 = await _outbox(conn, o_ghn, fc.EV_PROMPT)
        ck("G10 resume -> routing -> advance dung quote thu cong 25.000d (khong re-route ghi de)", rs and rs["step"] == "routing"
           and out10["step"] == "awaiting_method" and sh10["delivery_fee_vnd"] == 25000 and sh10["quote_source"] == "staff_manual"
           and pr10 and "25.000đ" in pr10[-1]["payload"]["text"])

        # ================= G11 Requote sau prompt =================
        async with conn.transaction():
            await ship.set_manual_quote(conn, o_ghn, actor="staff1", fee_vnd=35000)
        c11 = await fc.get(conn, o_ghn)
        ck("G11 staff doi phi sau khi da gui tong -> staff_attention(quote) (can reconfirm), khong tu gui tong moi",
           c11["step"] == "staff_attention" and c11["attention_reason"] == "quote" and len(pr10) == len(await _outbox(conn, o_ghn, fc.EV_PROMPT)))

        # ================= G12 Stale-check =================
        sc_ok = {"kind": "fulfillment", "order_id": o2, "step": "cod_handoff"}
        sc_stale = {"kind": "fulfillment", "order_id": o2, "step": "awaiting_method"}
        ck("G12 stale-check fulfillment: step trung -> gui; step khac -> stale",
           (await ow._is_stale(conn, sc_ok)) is False and (await ow._is_stale(conn, sc_stale)) is True)

        # ================= G9 Truthfulness tong hop =================
        all_ev = await conn.fetch(
            "SELECT event_type, payload FROM outbox_events WHERE payload->>'customer_ref' LIKE $1", f"tg:m7-{RUN}-%")
        bad = [r["event_type"] for r in all_ev if "đã xác nhận nhận thanh toán" in (json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]).get("text", "")
               and r["event_type"] != "payment.confirmed.notify"]
        ck("G9 chi payment.confirmed.notify moi noi da nhan thanh toan", not bad, bad)
    finally:
        await conn.close()
    print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
