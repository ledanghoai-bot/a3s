#!/usr/bin/env python3
"""M7 Amendment 273 DoD rehearsal — large-order guard + timeout/reminder timeline (FAKE CLOCK).

CA Amendment 273 §5. Chay tren m5lab (schema >= 065 revised). Dung `now` inject cho run_due (khong cho 15' that).
Gates:
  Large-order: qty 99/100/101, mixed unit, missing unit.
  Timeline: bien 6:59/7:00/12:59/13:00/14:59/15:00; scheduler duplicate; worker restart -> thang timeout;
            confirm truoc bien; dung 2 reminder max; escalation duy nhat; delayed confirm sau timeout.
  Templates: 4 reason nguyen van 273; khong template nao noi "da nhan tien".
Re-runnable (RUN suffix). KHONG PII/secret.
"""
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import asyncpg

from app.services.fulfillment import conversation as C

RUN = str(int(time.time()))
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
FAILS = []
_SEQ = [0]
T0 = datetime(2026, 9, 14, 3, 0, 0, tzinfo=timezone.utc)   # moc gia lap co dinh


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


async def _mk_order(conn, *, items, ward="24169"):
    """items = list[(qty, sales_unit)]. ward 24169 = self-delivery (fee 0)."""
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'T','0900000000') RETURNING id",
                              f"tg:m7-273-{tag}")
    total = 0
    oid = await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',0,"
        "'telegram_customer') RETURNING id", cid)
    for i, (qty, unit) in enumerate(items):
        pid = await conn.fetchval(
            "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
            "VALUES($1,'CF',100000,9999,100,$2) RETURNING id", f"M7-273-{tag}-{i}", unit)
        await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,$3,100000)",
                           oid, pid, qty)
        total += qty * 100000
    await conn.execute("UPDATE orders SET total_vnd=$2 WHERE id=$1", oid, total)
    rid = await conn.fetchval(
        "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
        "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,'66',$1,'current',1.0) RETURNING id",
        ward)
    await conn.execute(
        "INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,dataset_version,"
        "verification_method,bound_by) VALUES($1,$2,'66',$3,'VN-TEST','test','rehearsal')", oid, rid, ward)
    return oid


async def _route(conn, oid):
    await C.ensure_started(conn, oid, channel="telegram_customer", customer_ref=f"tg:m7-273-{oid}",
                           command_key=f"start:{oid}")
    async with conn.transaction():
        await C.advance_routing(conn, oid, ghn_result=None)
    return await C.get(conn, oid)


async def _bank_id(conn):
    bid = await conn.fetchval("SELECT id FROM bank_accounts WHERE holder_name=$1", f"M7273 {RUN}")
    if bid is None:
        bid = await conn.fetchval(
            "INSERT INTO bank_accounts(bank,account_number,holder_name,version,active,is_test) "
            "VALUES('TESTBANK','000000',$1,1,false,true) RETURNING id", f"M7273 {RUN}")
    return bid


async def _seed_awaiting_transfer(conn, *, started, confirmed=False):
    """Tao 1 order/payment/instruction/conversation o awaiting_transfer voi transfer_started_at=started."""
    oid = await _mk_order(conn, items=[(2, "hũ")])
    await conn.execute("UPDATE orders SET total_vnd=200000 WHERE id=$1", oid)
    pid = await conn.fetchval(
        "INSERT INTO payments(order_id,method,amount_due_vnd,status) VALUES($1,'BANK_TRANSFER',200000,$2) RETURNING id",
        oid, "confirmed" if confirmed else "awaiting")
    iid = await conn.fetchval(
        "INSERT INTO payment_instructions(order_id,payment_id,bank_account_id,account_version,bank_snapshot,"
        "account_number_snapshot,holder_snapshot,transfer_content,amount_vnd,is_test,created_at) "
        "VALUES($1,$2,$5,1,'TESTBANK','000','H',$3,200000,true,$4) RETURNING id",
        oid, pid, f"3SCF {oid}", started, await _bank_id(conn))
    await conn.execute(
        "INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,method,instruction_id,"
        "policy_version,transfer_started_at,transfer_deadline_at) "
        "VALUES($1,'telegram_customer',$2,'awaiting_transfer','BANK_TRANSFER',$3,1,$4,$5)",
        oid, f"tg:m7-273-{oid}", iid, started, started + timedelta(minutes=15))
    return oid, iid


async def _reminders(conn, iid):
    return [r["reminder_no"] for r in await conn.fetch(
        "SELECT reminder_no FROM fulfillment_reminders WHERE payment_instruction_id=$1 ORDER BY reminder_no", iid)]


async def _step(conn, oid):
    return await conn.fetchval("SELECT step FROM fulfillment_conversations WHERE order_id=$1", oid)


async def main():  # noqa: C901
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute("INSERT INTO delivery_zones(province_code,ward_code,zone) VALUES('66','24169','bmt_inner') "
                           "ON CONFLICT DO NOTHING")
        # idempotency across re-runs: chi v1 active; don awaiting_transfer ton dong -> completed (khoi nhieu run_due)
        await conn.execute("UPDATE fulfillment_policy_versions SET effective_to = effective_from + interval '1 second' "
                           "WHERE version <> 1")
        await conn.execute("UPDATE fulfillment_conversations SET step='completed', completed_at=now() "
                           "WHERE step='awaiting_transfer'")

        # ---------- Large-order guard ----------
        oid = await _mk_order(conn, items=[(50, "hũ"), (49, "hũ")])   # 99
        fc = await _route(conn, oid)
        q = await conn.fetchval("SELECT large_order_qty FROM fulfillment_conversations WHERE order_id=$1", oid)
        ck("LO 99 hũ -> KHONG large_order (qua guard)", fc["attention_reason"] != "large_order_review" and q == 99,
           f"reason={fc['attention_reason']} qty={q}")

        oid = await _mk_order(conn, items=[(100, "hũ")])              # 100
        fc = await _route(conn, oid)
        ck("LO 100 hũ -> large_order_review + staff_attention", fc["step"] == "staff_attention"
           and fc["attention_reason"] == "large_order_review", f"{fc['step']}/{fc['attention_reason']}")

        oid = await _mk_order(conn, items=[(60, "hũ"), (41, "hũ")])   # 101
        fc = await _route(conn, oid)
        ck("LO 101 hũ -> large_order_review", fc["attention_reason"] == "large_order_review",
           fc["attention_reason"])

        oid = await _mk_order(conn, items=[(50, "hũ"), (5, "gói")])   # mixed unit
        fc = await _route(conn, oid)
        ck("LO mixed unit -> quantity_unit_review", fc["step"] == "staff_attention"
           and fc["attention_reason"] == "quantity_unit_review", fc["attention_reason"])

        oid = await _mk_order(conn, items=[(3, None)])               # missing unit
        fc = await _route(conn, oid)
        ck("LO missing unit -> quantity_unit_review", fc["attention_reason"] == "quantity_unit_review",
           fc["attention_reason"])

        # config version change: order cu giu snapshot v1; order moi lay v2 (nguong thap hon)
        oidA = await _mk_order(conn, items=[(60, "hũ")])             # 60 < v1(100) -> proceeds
        fcA = await _route(conn, oidA)
        await conn.execute(
            "INSERT INTO fulfillment_policy_versions(version,effective_from,effective_to,large_order_threshold,"
            "large_order_unit,reminder1_minutes,reminder2_minutes,timeout_minutes,created_by) "
            "VALUES(2, now() - interval '1 minute', NULL, 50,'hũ',7,13,15,'m7-273-test') "
            "ON CONFLICT (version) DO UPDATE SET effective_from=now()-interval '1 minute', effective_to=NULL, "
            "large_order_threshold=50")
        oidB = await _mk_order(conn, items=[(60, "hũ")])             # 60 >= v2(50) -> large_order_review
        fcB = await _route(conn, oidB)
        ck("LO config-version: order cu (v1) proceeds, order moi (v2 nguong 50) escalate",
           fcA["policy_version"] == 1 and fcA["attention_reason"] != "large_order_review"
           and fcB["policy_version"] == 2 and fcB["attention_reason"] == "large_order_review",
           f"A v{fcA['policy_version']}/{fcA['attention_reason']} B v{fcB['policy_version']}/{fcB['attention_reason']}")

        # ---------- Timeline (fake clock) ----------
        oid, iid = await _seed_awaiting_transfer(conn, started=T0)

        async def due(delta_min):
            async with conn.transaction():
                return await C.run_due(conn, now=T0 + timedelta(minutes=delta_min, seconds=0))

        async def due_at(m, s):
            async with conn.transaction():
                return await C.run_due(conn, now=T0 + timedelta(minutes=m, seconds=s))

        s = await due_at(6, 59)
        ck("T 6:59 -> chua nhac", s["reminded"] == 0 and await _reminders(conn, iid) == [], s)
        s = await due_at(7, 0)
        ck("T 7:00 -> reminder #1", s["reminded"] == 1 and await _reminders(conn, iid) == [1]
           and await _step(conn, oid) == "awaiting_transfer", f"{s} rem={await _reminders(conn, iid)}")
        s = await due_at(7, 0)   # scheduler duplicate
        ck("T 7:00 lai (duplicate) -> khong nhac trung", s["reminded"] == 0 and await _reminders(conn, iid) == [1], s)
        s = await due_at(12, 59)
        ck("T 12:59 -> chua reminder #2", s["reminded"] == 0 and await _reminders(conn, iid) == [1], s)
        s = await due_at(13, 0)
        ck("T 13:00 -> reminder #2", s["reminded"] == 1 and await _reminders(conn, iid) == [1, 2], s)
        s = await due_at(14, 59)
        ck("T 14:59 -> chua escalate, khong reminder #3", s["reminded"] == 0 and s["escalated"] == 0
           and await _step(conn, oid) == "awaiting_transfer", s)
        s = await due_at(15, 0)
        ck("T 15:00 -> escalate payment_timeout", s["escalated"] == 1
           and await _step(conn, oid) == "staff_attention", f"{s} step={await _step(conn, oid)}")
        att = await conn.fetchval("SELECT reason FROM staff_attention WHERE order_id=$1 AND status='open'", oid)
        # CA 274-02: escalate handoff dung chung -> dedupe_key fc_staff:{order}:{reason}
        notif = await conn.fetchval(
            "SELECT count(*) FROM outbox_events WHERE dedupe_key=$1", f"fc_staff:{oid}:payment_timeout")
        ck("T escalate: staff_attention(payment_timeout) + notif tao", att == "payment_timeout" and notif == 1,
           f"att={att} notif={notif}")
        s = await due_at(20, 0)   # sau escalate -> khong lay lai
        ck("T sau escalate -> khong double (step khac awaiting_transfer)", s["escalated"] == 0, s)
        ck("T dung 2 reminder max", await _reminders(conn, iid) == [1, 2], await _reminders(conn, iid))

        # confirm truoc bien -> completed, khong nhac
        oid2, iid2 = await _seed_awaiting_transfer(conn, started=T0, confirmed=True)
        s = await due_at(7, 0)
        ck("T confirmed truoc bien -> completed, khong reminder",
           await _step(conn, oid2) == "completed" and await _reminders(conn, iid2) == [], s)

        # worker restart: nhay thang toi sau timeout -> escalate, khong reminder
        oid3, iid3 = await _seed_awaiting_transfer(conn, started=T0)
        s = await due(30)   # worker down qua ca timeout
        ck("T worker restart -> thang escalate, khong reminder", s["escalated"] == 1
           and await _reminders(conn, iid3) == [] and await _step(conn, oid3) == "staff_attention", s)

        # delayed confirm sau timeout: on_payment_confirmed -> completed + resolve payment_timeout
        await conn.execute("UPDATE payments SET status='confirmed' WHERE order_id=$1", oid)
        async with conn.transaction():
            await C.on_payment_confirmed(conn, oid, actor="provider:test")
        att_after = await conn.fetchval(
            "SELECT status FROM staff_attention WHERE order_id=$1 AND reason='payment_timeout'", oid)
        ck("T delayed confirm sau timeout -> completed + attention resolved",
           await _step(conn, oid) == "completed" and att_after == "resolved", f"att={att_after}")

        # ---------- Templates (nguyen van 273; khong 'da nhan tien') ----------
        exact = {
            "large_order_review": "Đơn hàng có số lượng lớn nên shop cần nhân viên kiểm tra và hỗ trợ trực tiếp. "
                                  "Shop sẽ liên hệ lại với bạn.",
            "payment_timeout": "Shop chưa xác nhận được khoản chuyển trong thời gian chờ nên cần nhân viên kiểm tra. "
                               "Shop sẽ liên hệ lại với bạn.",
            "payment_mismatch": "Thông tin thanh toán chưa khớp hoàn toàn nên shop cần nhân viên kiểm tra. "
                                "Shop sẽ liên hệ lại với bạn.",
            "quantity_unit_review": "Thông tin số lượng cần được nhân viên kiểm tra thêm. Shop sẽ liên hệ lại với bạn.",
        }
        ok_tpl = all(C.staff_text(1, k) == v for k, v in exact.items())
        ck("Templates 4 reason nguyen van 273", ok_tpl)
        all_templates = [C.staff_text(1, k) for k in exact] + [C.reminder_text(1, {"amount_vnd": 1, "transfer_content": "x"}),
                                                               C.instruction_text(1, {"bank_snapshot": "B",
                                                               "account_number_snapshot": "1", "holder_snapshot": "H",
                                                               "amount_vnd": 1, "transfer_content": "x"}, wait_minutes=15)]
        ck("Khong template escalation/reminder nao noi 'da nhan tien'",
           not any("đã nhận" in t and "tiền" in t for t in all_templates))

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
