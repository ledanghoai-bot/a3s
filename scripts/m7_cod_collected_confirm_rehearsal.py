"""M7 COD-collected confirmation — DB rehearsal (CA Directive 293 §6). Chay tren m5lab (schema hien hanh, throwaway).

Chung minh qua SERVICE THAT (payment_service/notify/conversation) + DB:
 T1 exact cod_collected -> received tang DUNG 1 lan, status collected, conversation completed, DUNG 1 confirmation.
 T2 duplicate cung command_key/payload -> cung receipt, 0 amount/outbox them.
 T3 concurrent duplicate (2 conn, cung key) -> 1 event/effect/notification.
 T4 cung command_key khac amount -> reject (idempotency mismatch), khong mutation phu.
 T5 partial / excess -> discrepancy, 0 confirmation, staff handling.
 T6 missing due / zero / negative amount -> reject/fail-closed, 0 notification.
 T7 reconciled sau exact collected -> reconciled, amount khong doi, 0 notification moi.
 T8 reconcile truoc collected / khi discrepancy -> reject.
 T9 retry/concurrent reconcile -> idempotent, khong double transition/notify.
 T10 outbox dispatch retry -> khach nhan toi da 1 confirmation (dedupe key on-dinh theo order+version).
 T11 status reply dung o awaiting/collected/reconciled/discrepancy.
 T13 CK regression: customer_reported KHONG xac nhan tien; shop exact -> 1 notify; mismatch -> khong confirm.
(T12 historical no-retro-notify: khong replay event lich su -> khong sinh outbox; T14 tester-scope/SILENT/reminder do
 rehearsal khac phu.)
Khong PII/secret. Re-runnable (RUN suffix).
"""
import asyncio
import os
import sys
import time

import asyncpg

from app.services.fulfillment import shipment_service as ship
from app.services.payment import payment_service as pay

RUN = str(int(time.time()))
FAILS = []
_SEQ = [0]
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


def key(label):
    return f"{RUN}:{label}"


async def _mk_cod_order(conn, *, ward="24169", weight=300, qty=2, total=200000, convo=True, method="COD"):
    """Order da quote (bmt_inner fee 0 -> due=total) + payment (method) + (tuy chon) conversation cod_handoff."""
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    psid = f"tg:cod-{tag}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'Test COD','0900000000') RETURNING id",
                              psid)
    pid = await conn.fetchval(
        "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) VALUES($1,'CF',$2,999,$3,'hũ') "
        "RETURNING id", f"COD-{tag}", total, weight)
    oid = await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',$2,'telegram_customer') "
        "RETURNING id", cid, total)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,$3,$4)",
                       oid, pid, qty, total)
    rid = await conn.fetchval(
        "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
        "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,'66',$1,'current',1.0) RETURNING id",
        ward)
    await conn.execute("INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,"
                       "dataset_version,verification_method,bound_by) VALUES($1,$2,'66',$3,'VN-TEST','test','r')",
                       oid, rid, ward)
    await ship.auto_quote(conn, oid, actor="staff1")
    p = await pay.ensure_payment(conn, oid, method=method, actor="staff1")
    if convo:
        await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,method,"
                           "policy_version) VALUES($1,'telegram_customer',$2,'cod_handoff','COD',1)", oid, psid)
    return oid, cid, psid, p["amount_due_vnd"]


async def _confirmed_notify(conn, oid):
    return await conn.fetchval("SELECT count(*) FROM outbox_events WHERE (payload->>'order_id')::bigint=$1 "
                               "AND event_type='payment.confirmed.notify'", oid)


async def _convo_step(conn, oid):
    return await conn.fetchval("SELECT step FROM fulfillment_conversations WHERE order_id=$1", oid)


async def _rec(conn, oid, **kw):
    async with conn.transaction():
        return await pay.record_evidence(conn, oid, **kw)


async def main():  # noqa: C901
    if os.environ.get("M6_TEST_DB") != "1":
        print("can M6_TEST_DB=1 (DB throwaway)")
        return 2
    conn = await asyncpg.connect(DSN)
    try:
        # ---------------- T1 exact cod_collected ----------------
        oid, cid, psid, due = await _mk_cod_order(conn)
        r = await _rec(conn, oid, kind="cod_collected", amount_vnd=due, recorded_by="delivery1",
                       command_key=key(f"t1-{oid}"))
        recv = await conn.fetchval("SELECT amount_received_vnd FROM payments WHERE order_id=$1", oid)
        ck("T1 exact cod_collected -> status collected, received==due (1 lan), conversation completed, 1 confirmation",
           r["status"] == "collected" and recv == due and (await _convo_step(conn, oid)) == "completed"
           and (await _confirmed_notify(conn, oid)) == 1, f"st={r['status']} recv={recv}/{due}")

        # ---------------- T2 duplicate same key/payload ----------------
        r2 = await _rec(conn, oid, kind="cod_collected", amount_vnd=due, recorded_by="delivery1",
                        command_key=key(f"t1-{oid}"))
        recv2 = await conn.fetchval("SELECT amount_received_vnd FROM payments WHERE order_id=$1", oid)
        ck("T2 duplicate cung key/payload -> replay, 0 amount/outbox them",
           r2.get("duplicate") is True and recv2 == due and (await _confirmed_notify(conn, oid)) == 1,
           f"dup={r2.get('duplicate')} recv={recv2}")

        # ---------------- T3 concurrent duplicate (2 conn cung key) ----------------
        oidC, *_c, dueC = await _mk_cod_order(conn)
        cA = await asyncpg.connect(DSN)
        cB = await asyncpg.connect(DSN)
        try:
            async def one(cc):
                try:
                    async with cc.transaction():
                        return await pay.record_evidence(cc, oidC, kind="cod_collected", amount_vnd=dueC,
                                                         recorded_by="delivery1", command_key=key(f"t3-{oidC}"))
                except Exception as e:
                    return e
            await asyncio.gather(one(cA), one(cB))
        finally:
            await cA.close()
            await cB.close()
        recvC = await conn.fetchval("SELECT amount_received_vnd FROM payments WHERE order_id=$1", oidC)
        nevC = await conn.fetchval("SELECT count(*) FROM payment_events pe JOIN payments p ON p.id=pe.payment_id "
                                   "WHERE p.order_id=$1 AND pe.kind='cod_collected'", oidC)
        ck("T3 concurrent duplicate -> 1 event, received==due, 1 confirmation",
           recvC == dueC and nevC == 1 and (await _confirmed_notify(conn, oidC)) == 1,
           f"recv={recvC} events={nevC} notify={await _confirmed_notify(conn, oidC)}")

        # ---------------- T4 same key different amount -> reject ----------------
        oid4, *_4, due4 = await _mk_cod_order(conn)
        await _rec(conn, oid4, kind="cod_collected", amount_vnd=due4, recorded_by="d", command_key=key(f"t4-{oid4}"))
        rejected = False
        try:
            await _rec(conn, oid4, kind="cod_collected", amount_vnd=due4 + 1, recorded_by="d",
                       command_key=key(f"t4-{oid4}"))
        except pay.PaymentError:
            rejected = True
        recv4 = await conn.fetchval("SELECT amount_received_vnd FROM payments WHERE order_id=$1", oid4)
        ck("T4 cung key khac amount -> reject, khong mutation phu", rejected and recv4 == due4,
           f"rej={rejected} recv={recv4}/{due4}")

        # ---------------- T5 partial / excess -> discrepancy, 0 confirmation ----------------
        oidP, *_p, dueP = await _mk_cod_order(conn)
        rP = await _rec(conn, oidP, kind="cod_collected", amount_vnd=dueP - 1000, recorded_by="d",
                        command_key=key(f"t5p-{oidP}"))
        ck("T5 partial -> discrepancy, 0 confirmation, conversation KHONG completed",
           rP["status"] == "discrepancy" and (await _confirmed_notify(conn, oidP)) == 0
           and (await _convo_step(conn, oidP)) == "cod_handoff", f"st={rP['status']}")
        oidX, *_x, dueX = await _mk_cod_order(conn)
        rX = await _rec(conn, oidX, kind="cod_collected", amount_vnd=dueX + 5000, recorded_by="d",
                        command_key=key(f"t5x-{oidX}"))
        ck("T5 excess -> discrepancy, 0 confirmation",
           rX["status"] == "discrepancy" and (await _confirmed_notify(conn, oidX)) == 0, f"st={rX['status']}")

        # ---------------- T6 missing due / zero / negative -> reject ----------------
        # missing due: order khong quote -> ensure_payment due=None
        _SEQ[0] += 1
        tag = f"{RUN}-nodue-{_SEQ[0]}"
        cidN = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'N','0900000000') RETURNING id",
                                   f"tg:{tag}")
        pidN = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
                                   "VALUES($1,'CF',100000,999,300,'hũ') RETURNING id", f"ND-{tag}")
        oidN = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                                   "VALUES($1,'confirmed',200000,'telegram_customer') RETURNING id", cidN)
        await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,2,100000)",
                           oidN, pidN)
        await pay.ensure_payment(conn, oidN, method="COD", actor="s")  # KHONG quote -> due None
        due_is_none = (await conn.fetchval("SELECT amount_due_vnd FROM payments WHERE order_id=$1", oidN)) is None
        nodue_rej = False
        try:
            await _rec(conn, oidN, kind="cod_collected", amount_vnd=100000, recorded_by="d", command_key=key("t6nd"))
        except pay.PaymentError:
            nodue_rej = True
        oidZ, *_z, dueZ = await _mk_cod_order(conn)
        zero_rej = neg_rej = False
        try:
            await _rec(conn, oidZ, kind="cod_collected", amount_vnd=0, recorded_by="d", command_key=key("t6z"))
        except pay.PaymentError:
            zero_rej = True
        try:
            await _rec(conn, oidZ, kind="cod_collected", amount_vnd=-5, recorded_by="d", command_key=key("t6n"))
        except pay.PaymentError:
            neg_rej = True
        ck("T6 missing due / zero / negative amount -> reject fail-closed, 0 notification",
           due_is_none and nodue_rej and zero_rej and neg_rej and (await _confirmed_notify(conn, oidN)) == 0
           and (await _confirmed_notify(conn, oidZ)) == 0,
           f"nodue={nodue_rej} zero={zero_rej} neg={neg_rej}")

        # ---------------- T7 reconciled after exact collected -> accounting only ----------------
        ver_before = await conn.fetchval("SELECT version FROM payments WHERE order_id=$1", oid)
        rR = await _rec(conn, oid, kind="reconciled", amount_vnd=None, recorded_by="po", command_key=key(f"t7-{oid}"))
        recvR = await conn.fetchval("SELECT amount_received_vnd FROM payments WHERE order_id=$1", oid)
        ck("T7 reconciled sau exact collected -> reconciled, amount khong doi, 0 notification moi",
           rR["status"] == "reconciled" and recvR == due and (await _confirmed_notify(conn, oid)) == 1,
           f"st={rR['status']} recv={recvR} notify={await _confirmed_notify(conn, oid)} ver_before={ver_before}")

        # ---------------- T8 reconcile before collected / on discrepancy -> reject ----------------
        oidB, *_b, dueB = await _mk_cod_order(conn)   # status awaiting (chua collected)
        pre_rej = False
        try:
            await _rec(conn, oidB, kind="reconciled", amount_vnd=None, recorded_by="po", command_key=key("t8pre"))
        except pay.PaymentError:
            pre_rej = True
        # discrepancy: partial collected -> reconcile reject
        await _rec(conn, oidB, kind="cod_collected", amount_vnd=dueB - 100, recorded_by="d", command_key=key("t8part"))
        disc_rej = False
        try:
            await _rec(conn, oidB, kind="reconciled", amount_vnd=None, recorded_by="po", command_key=key("t8disc"))
        except pay.PaymentError:
            disc_rej = True
        ck("T8 reconcile truoc collected / khi discrepancy -> reject",
           pre_rej and disc_rej and (await conn.fetchval("SELECT status FROM payments WHERE order_id=$1", oidB)) ==
           "discrepancy", f"pre={pre_rej} disc={disc_rej}")

        # ---------------- T9 retry/concurrent reconcile -> idempotent ----------------
        oid9, *_9, due9 = await _mk_cod_order(conn)
        await _rec(conn, oid9, kind="cod_collected", amount_vnd=due9, recorded_by="d", command_key=key(f"t9c-{oid9}"))
        r9a = await _rec(conn, oid9, kind="reconciled", amount_vnd=None, recorded_by="po", command_key=key(f"t9r-{oid9}"))
        r9b = await _rec(conn, oid9, kind="reconciled", amount_vnd=None, recorded_by="po", command_key=key(f"t9r-{oid9}"))
        recv9 = await conn.fetchval("SELECT amount_received_vnd FROM payments WHERE order_id=$1", oid9)
        ck("T9 retry reconcile -> idempotent (replay), amount khong doi, 0 new notify",
           r9a["status"] == "reconciled" and r9b.get("duplicate") is True and recv9 == due9
           and (await _confirmed_notify(conn, oid9)) == 1, f"a={r9a['status']} bdup={r9b.get('duplicate')}")

        # ---------------- T10 outbox dedupe: 1 confirmation per monetary evidence ----------------
        rows = await conn.fetch("SELECT dedupe_key FROM outbox_events WHERE (payload->>'order_id')::bigint=$1 "
                                "AND event_type='payment.confirmed.notify'", oid)
        ck("T10 outbox dedupe_key on-dinh (order+version) -> toi da 1 confirmation",
           len(rows) == 1 and len({r["dedupe_key"] for r in rows}) == 1, f"rows={len(rows)}")

        # ---------------- T11 status reply ----------------
        from app.services.fulfillment.status_reply import format_status

        def row(pay_status):
            return {"id": oid, "ship_status": "delivered", "fee_status": "quoted", "delivery_fee_vnd": 0,
                    "method": "COD", "pay_status": pay_status, "amount_due_vnd": due, "carrier": None,
                    "tracking_text": None, "eta_text": None}
        s_col = format_status(row("collected"))
        s_rec = format_status(row("reconciled"))
        s_dis = format_status(row("discrepancy"))
        ck("T11 status reply: collected='đang đối soát' (khong 'đã thanh toán'); reconciled='Đã thanh toán'; "
           "discrepancy khong hua da nhan/thu",
           "đang đối soát" in s_col and "đã thanh toán" not in s_col.lower() and "Đã thanh toán" in s_rec
           and "đã thanh toán" not in s_dis.lower() and "đã thu tiền" not in s_dis.lower(),
           f"col=[{s_col}] rec=[{s_rec}] dis=[{s_dis}]")

        # ---------------- T13 CK regression ----------------
        oidT, _cidT, _psidT, dueT = await _mk_cod_order(conn, convo=False, method="BANK_TRANSFER")
        await _rec(conn, oidT, kind="customer_reported", amount_vnd=None, recorded_by="customer",
                   command_key=key(f"ckrep-{oidT}"))
        ck("T13 CK customer_reported -> KHONG payment.confirmed.notify (chi check_request)",
           (await _confirmed_notify(conn, oidT)) == 0, await _confirmed_notify(conn, oidT))
        rc = await _rec(conn, oidT, kind="shop_confirmed_received", amount_vnd=dueT, recorded_by="po",
                        command_key=key(f"ckconf-{oidT}"))
        ck("T13 CK shop_confirmed_received exact -> confirmed + DUNG 1 payment.confirmed.notify",
           rc["status"] == "confirmed" and (await _confirmed_notify(conn, oidT)) == 1, rc["status"])
        # mismatch CK -> discrepancy, khong confirm
        oidM2, *_m2, dueM2 = await _mk_cod_order(conn, convo=False, method="BANK_TRANSFER")
        await _rec(conn, oidM2, kind="customer_reported", amount_vnd=None, recorded_by="customer",
                   command_key=key(f"ckmisrep-{oidM2}"))
        rm = await _rec(conn, oidM2, kind="shop_confirmed_received", amount_vnd=dueM2 - 1, recorded_by="po",
                        command_key=key(f"ckmis-{oidM2}"))
        ck("T13 CK mismatch -> discrepancy, 0 confirmation",
           rm["status"] == "discrepancy" and (await _confirmed_notify(conn, oidM2)) == 0, rm["status"])

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        from app.db_pool import close_pool
        await close_pool()
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
