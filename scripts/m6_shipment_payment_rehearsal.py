"""M6 shipment + payment — DB rehearsal V02 (CA Directive 265 §5 + Review 266). Chay tren m5lab (schema >= 064).

Chung minh (V02):
 G1 auto_quote (bmt_inner fee 0 / province 30k, rule_version snapshot)
 G2 COD e2e (collected->reconciled du tien) + eta_start=cod_confirmed
 G3 transfer e2e (reported->confirmed) + instruction + eta_start=transfer_received
 G4 partial -> discrepancy (khong auto-confirm)
 G5 idempotency: command_key replay + reference replay (khong cong lan 2)
 G6 max 3 attempts (co payment du dieu kien handover)
 G7 wrong transition reject
 G8 notify tao + dedupe + stale-check (version cu bi cancel o worker)
 G9 version CAS (stale expected_version reject)
 G10 handover eligibility: transfer CHUA confirmed -> khong cho in_transit
 G11 excess -> discrepancy + correction (tro ve event goc + ly do) -> ve confirmed
 G12 amount_due resync sau quote khi chua settled; KHONG resync khi da confirmed (-> discrepancy reopen)
KHONG PII/secret. Re-runnable (RUN suffix). command_key on-dinh per intent.
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
    """command_key on-dinh cho 1 intent trong 1 lan chay."""
    return f"{RUN}:{label}"


async def _mk_order(conn, *, ward, weight, qty, total):
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'Test','0900000000') RETURNING id",
                              f"tg:m6-{tag}")
    pid = await conn.fetchval(
        "INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g) VALUES($1,'CF',$2,999,$3) "
        "ON CONFLICT(sku) DO UPDATE SET shipping_weight_g=$3 RETURNING id", f"M6-{tag}", total, weight)
    oid = await conn.fetchval(
        "INSERT INTO orders(customer_id,status,total_vnd,origin_channel) VALUES($1,'confirmed',$2,"
        "'telegram_customer') RETURNING id", cid, total)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,$3,$4)",
                       oid, pid, qty, total)
    rid = await conn.fetchval(
        "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
        "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,'66',$1,'current',1.0) "
        "RETURNING id", ward)
    await conn.execute(
        "INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,dataset_version,"
        "verification_method,bound_by) VALUES($1,$2,'66',$3,'VN-TEST','test','rehearsal')", oid, rid, ward)
    return oid


async def _drive_to_transit(conn, oid, *, method="COD"):
    """quote + payment du dieu kien -> ready_to_ship -> in_transit."""
    await ship.auto_quote(conn, oid, actor="staff1")
    await pay.ensure_payment(conn, oid, method=method, actor="staff1")
    if method == "BANK_TRANSFER":
        await pay.record_evidence(conn, oid, kind="customer_reported", amount_vnd=None, recorded_by="customer",
                                  command_key=key(f"rep-{oid}"))
        due = await conn.fetchval("SELECT amount_due_vnd FROM payments WHERE order_id=$1", oid)
        await pay.record_evidence(conn, oid, kind="shop_confirmed_received", amount_vnd=due, recorded_by="po",
                                  command_key=key(f"conf-{oid}"))
    await ship.change_status(conn, oid, "ready_to_ship", actor="staff1")
    await ship.change_status(conn, oid, "in_transit", actor="staff1")


async def main():
    conn = await asyncpg.connect(DSN)
    try:
        await conn.execute("INSERT INTO delivery_zones(province_code,ward_code,zone) VALUES('66','24169','bmt_inner') "
                           "ON CONFLICT DO NOTHING")
        await conn.execute("INSERT INTO delivery_zones(province_code,ward_code,zone) VALUES('66',NULL,'province') "
                           "ON CONFLICT DO NOTHING")

        # G1: auto_quote + rule_version snapshot
        oid_bmt = await _mk_order(conn, ward="24169", weight=300, qty=2, total=200000)  # 600g bmt_inner -> fee 0
        q1 = await ship.auto_quote(conn, oid_bmt, actor="staff1")
        ck("G1 bmt_inner 600g -> fee 0 quoted", q1["zone"] == "bmt_inner" and q1["delivery_fee_vnd"] == 0
           and q1["fee_status"] == "quoted", f"{q1['zone']}/{q1['delivery_fee_vnd']}/{q1['fee_status']}")
        ck("G1 quote_rule_version duoc snapshot", q1["quote_rule_version"] is not None, q1["quote_rule_version"])
        oid_prov = await _mk_order(conn, ward="99999", weight=300, qty=2, total=200000)  # province -> fee 30000
        q2 = await ship.auto_quote(conn, oid_prov, actor="staff1")
        ck("G1 province 600g -> fee 30000 quoted", q2["zone"] == "province" and q2["delivery_fee_vnd"] == 30000,
           f"{q2['zone']}/{q2['delivery_fee_vnd']}")

        # G2: COD e2e + eta_start
        p_cod = await pay.ensure_payment(conn, oid_prov, method="COD", actor="staff1")
        ck("G2 COD amount_due = total+fee = 230000", p_cod["amount_due_vnd"] == 230000, p_cod["amount_due_vnd"])
        es = await conn.fetchrow("SELECT eta_start_at, eta_start_source FROM shipments WHERE order_id=$1", oid_prov)
        ck("G2 COD ensure -> eta_start=cod_confirmed", es["eta_start_at"] is not None
           and es["eta_start_source"] == "cod_confirmed", es["eta_start_source"])
        await ship.change_status(conn, oid_prov, "ready_to_ship", actor="staff1")
        s_it = await ship.change_status(conn, oid_prov, "in_transit", actor="staff1")
        ck("G2 in_transit set handover_at", s_it["handover_at"] is not None)
        a = await ship.record_attempt(conn, oid_prov, actor="delivery1", result="success", command_key=key("g2-att"))
        ck("G2 attempt success -> delivered", a["shipment_status"] == "delivered", a["shipment_status"])
        r = await pay.record_evidence(conn, oid_prov, kind="cod_collected", amount_vnd=230000,
                                      recorded_by="delivery1", command_key=key("g2-coll"))
        ck("G2 cod_collected -> collected", r["status"] == "collected", r["status"])
        r2 = await pay.record_evidence(conn, oid_prov, kind="reconciled", amount_vnd=230000, recorded_by="po",
                                       command_key=key("g2-rec"))
        ck("G2 reconciled(du tien) -> reconciled", r2["status"] == "reconciled" and r2["discrepancy"] is None,
           r2["status"])

        # G3: transfer e2e + instruction + eta_start
        await pay.set_bank_account(conn, bank="TEST BANK", account_number="00012345",
                                   holder_name="ROBANME TEST", actor="po", is_test=True)
        p_tr = await pay.ensure_payment(conn, oid_bmt, method="BANK_TRANSFER", actor="staff1")
        ck("G3 transfer amount_due = 200000 (fee 0)", p_tr["amount_due_vnd"] == 200000, p_tr["amount_due_vnd"])
        instr = await pay.generate_instruction(conn, oid_bmt, actor="staff1")
        ck("G3 instruction deterministic content + acct 0-dau giu",
           instr["transfer_content"] == f"3SCF {oid_bmt}" and instr["account_number_snapshot"] == "00012345"
           and instr["is_test"] is True, instr["transfer_content"])
        rr = await pay.record_evidence(conn, oid_bmt, kind="customer_reported", amount_vnd=200000,
                                       recorded_by="customer", reference="FT123", command_key=key("g3-rep"))
        ck("G3 customer_reported -> reported (khong tu confirmed)", rr["status"] == "reported", rr["status"])
        rc = await pay.record_evidence(conn, oid_bmt, kind="shop_confirmed_received", amount_vnd=200000,
                                       recorded_by="po", command_key=key("g3-conf"))
        ck("G3 shop_confirmed(du) -> confirmed", rc["status"] == "confirmed", rc["status"])
        es3 = await conn.fetchrow("SELECT eta_start_source FROM shipments WHERE order_id=$1", oid_bmt)
        ck("G3 transfer confirmed -> eta_start=transfer_received", es3["eta_start_source"] == "transfer_received",
           es3["eta_start_source"])

        # G4: partial -> discrepancy (khong auto-confirm)
        oid_p = await _mk_order(conn, ward="99999", weight=300, qty=2, total=200000)
        await ship.auto_quote(conn, oid_p, actor="staff1")
        await pay.ensure_payment(conn, oid_p, method="BANK_TRANSFER", actor="staff1")
        await pay.record_evidence(conn, oid_p, kind="customer_reported", amount_vnd=100000, recorded_by="customer",
                                  command_key=key("g4-rep"))
        rp = await pay.record_evidence(conn, oid_p, kind="shop_confirmed_received", amount_vnd=100000,
                                       recorded_by="po", command_key=key("g4-conf"))
        ck("G4 partial (100k/230k) -> discrepancy", rp["status"] == "discrepancy"
           and rp["discrepancy"] and rp["discrepancy"]["kind"] == "partial", rp["status"])

        # G5: idempotency — command_key replay + reference replay
        n_before = await conn.fetchval(
            "SELECT count(*) FROM payment_events pe JOIN payments p ON p.id=pe.payment_id WHERE p.order_id=$1 "
            "AND pe.reference='FT123'", oid_bmt)
        dup_ck = await pay.record_evidence(conn, oid_bmt, kind="customer_reported", amount_vnd=200000,
                                           recorded_by="customer", reference="FT123", command_key=key("g3-rep"))
        dup_ref = await pay.record_evidence(conn, oid_bmt, kind="customer_reported", amount_vnd=200000,
                                            recorded_by="customer", reference="FT123", command_key=key("g5-newkey"))
        n_after = await conn.fetchval(
            "SELECT count(*) FROM payment_events pe JOIN payments p ON p.id=pe.payment_id WHERE p.order_id=$1 "
            "AND pe.reference='FT123'", oid_bmt)
        ck("G5 command_key replay -> duplicate", dup_ck["duplicate"] is True)
        ck("G5 reference replay (key moi) -> duplicate", dup_ref["duplicate"] is True)
        ck("G5 khong ghi/cong lan 2", n_after == n_before, f"{n_before}->{n_after}")

        # G6: max 3 attempts (co payment du dieu kien)
        oid_f = await _mk_order(conn, ward="99999", weight=300, qty=2, total=200000)
        await _drive_to_transit(conn, oid_f, method="COD")
        for i in range(3):
            if i > 0:  # retry can re-dispatch tuong minh (delivery_failed -> in_transit) truoc khi ghi attempt
                await ship.change_status(conn, oid_f, "in_transit", actor="staff1")
            res = await ship.record_attempt(conn, oid_f, actor="delivery1", result="failed", reason="no answer",
                                            command_key=key(f"g6-att{i}"))
        ck("G6 luot 3 fail -> return_pending", res["shipment_status"] == "return_pending", res["shipment_status"])
        st_f = await conn.fetchval("SELECT status FROM shipments WHERE order_id=$1", oid_f)
        ck("G6 het 3 luot -> return_pending (terminal)", st_f == "return_pending", st_f)
        # het luot roi: re-dispatch cung bi chan (khong cho in_transit lan 4)
        try:
            await ship.change_status(conn, oid_f, "in_transit", actor="staff1")
            ck("G6 het luot -> chan re-dispatch", False, "khong raise")
        except ship.ShipmentError:
            ck("G6 het luot -> chan re-dispatch", True)
        try:
            await ship.record_attempt(conn, oid_f, actor="delivery1", result="failed", command_key=key("g6-att4"))
            ck("G6 attempt thu 4 bi tu choi", False, "khong raise")
        except ship.ShipmentError:
            ck("G6 attempt thu 4 bi tu choi (khong in_transit)", True)

        # G7: wrong transition (oid_prov dang delivered)
        try:
            await ship.change_status(conn, oid_prov, "in_transit", actor="staff1")
            ck("G7 delivered->in_transit reject", False, "khong raise")
        except ship.ShipmentError:
            ck("G7 transition sai bi reject", True)

        # G8: notify tao + dedupe + stale-check o worker
        n_handover = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key=$1",
                                         f"shipment_handover:{oid_prov}")
        n_delivered = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key=$1",
                                          f"shipment_delivered:{oid_prov}")
        n_payconf = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key=$1",
                                        f"payment_confirmed:{oid_bmt}")
        ck("G8 notify handover+delivered+confirmed tao (1 moi loai)",
           n_handover == 1 and n_delivered == 1 and n_payconf == 1,
           f"h{n_handover} d{n_delivered} pf{n_payconf}")
        # payload mang stale_check (transition+version) de worker doi chieu
        pl = await conn.fetchval("SELECT payload FROM outbox_events WHERE dedupe_key=$1",
                                 f"shipment_delivered:{oid_prov}")
        import json as _json
        sc = (_json.loads(pl) if isinstance(pl, str) else pl).get("stale_check")
        ck("G8 payload mang stale_check{kind,version}", sc and sc["kind"] == "shipment"
           and sc["version"] is not None, sc)
        # stale-check logic: version luc enqueue < version hien tai -> stale (bo qua); == hoac moi hon -> gui
        from app.services.command import outbox_worker as ow
        cur_ver = await conn.fetchval("SELECT version FROM shipments WHERE order_id=$1", oid_prov)
        is_stale_old = await ow._is_stale(conn, {"kind": "shipment", "order_id": oid_prov, "version": cur_ver - 3})
        is_stale_cur = await ow._is_stale(conn, {"kind": "shipment", "order_id": oid_prov, "version": cur_ver})
        ck("G8 stale-check: version cu -> stale(bo qua), version hien tai -> gui",
           is_stale_old is True and is_stale_cur is False, f"old={is_stale_old} cur={is_stale_cur}")

        # G9: version CAS
        oid_c = await _mk_order(conn, ward="99999", weight=300, qty=2, total=200000)
        sh0 = await ship.ensure_shipment(conn, oid_c, actor="staff1")
        v0 = sh0["version"]
        await ship.change_status(conn, oid_c, "ready_to_ship", actor="staff1", expected_version=v0)
        try:
            await ship.change_status(conn, oid_c, "in_transit", actor="staff1", expected_version=v0)
            ck("G9 stale version bi reject", False, "khong raise")
        except ship.ShipmentError:
            ck("G9 stale expected_version (concurrency) bi reject", True)

        # G10: handover eligibility — transfer CHUA confirmed khong cho in_transit
        oid_e = await _mk_order(conn, ward="99999", weight=300, qty=2, total=200000)
        await ship.auto_quote(conn, oid_e, actor="staff1")
        await pay.ensure_payment(conn, oid_e, method="BANK_TRANSFER", actor="staff1")
        await ship.change_status(conn, oid_e, "ready_to_ship", actor="staff1")
        try:
            await ship.change_status(conn, oid_e, "in_transit", actor="staff1")
            ck("G10 transfer chua confirmed -> chan handover", False, "khong raise")
        except ship.ShipmentError as ex:
            ck("G10 transfer chua confirmed -> chan handover", "chua duoc shop xac nhan" in str(ex)
               or "confirmed" in str(ex), str(ex)[:60])

        # G11: excess -> discrepancy, correction tro ve goc + ly do -> confirmed
        oid_x = await _mk_order(conn, ward="99999", weight=300, qty=2, total=200000)
        await ship.auto_quote(conn, oid_x, actor="staff1")       # due = 230000
        await pay.ensure_payment(conn, oid_x, method="BANK_TRANSFER", actor="staff1")
        await pay.record_evidence(conn, oid_x, kind="customer_reported", amount_vnd=250000, recorded_by="customer",
                                  command_key=key("g11-rep"))
        ex_conf = await pay.record_evidence(conn, oid_x, kind="shop_confirmed_received", amount_vnd=250000,
                                            recorded_by="po", command_key=key("g11-conf"))
        ck("G11 thua (250k/230k) -> discrepancy excess", ex_conf["status"] == "discrepancy"
           and ex_conf["discrepancy"]["kind"] == "excess", ex_conf["status"])
        orig_ev = int(ex_conf["event_id"])
        try:
            await pay.record_evidence(conn, oid_x, kind="correction", amount_vnd=-20000, recorded_by="po",
                                      command_key=key("g11-corr-noreason"))
            ck("G11 correction thieu ly do bi tu choi", False, "khong raise")
        except pay.PaymentError:
            ck("G11 correction BAT BUOC ly do", True)
        corr = await pay.record_evidence(conn, oid_x, kind="correction", amount_vnd=-20000, recorded_by="po",
                                         note="khach chuyen du 20k, tru lai", corrects_event_id=orig_ev,
                                         command_key=key("g11-corr"))
        ck("G11 correction (-20k) tro ve goc -> confirmed", corr["status"] == "confirmed"
           and corr["discrepancy"] is None, corr["status"])
        corr_db = await conn.fetchval("SELECT corrects_event_id FROM payment_events WHERE id=$1",
                                      int(corr["event_id"]))
        ck("G11 correction luu tham chieu event goc", corr_db == orig_ev, f"{corr_db} vs {orig_ev}")

        # G12: resync amount_due — chua settled thi doi theo fee; da confirmed thi reopen discrepancy
        oid_r = await _mk_order(conn, ward="99999", weight=300, qty=2, total=200000)
        await ship.auto_quote(conn, oid_r, actor="staff1")       # fee 30000 -> due 230000
        await pay.ensure_payment(conn, oid_r, method="BANK_TRANSFER", actor="staff1")
        await ship.set_manual_quote(conn, oid_r, actor="staff1", fee_vnd=50000)  # doi fee -> due 250000
        due_r = await conn.fetchval("SELECT amount_due_vnd FROM payments WHERE order_id=$1", oid_r)
        ck("G12 chua settled: quote doi -> amount_due resync 250000", due_r == 250000, due_r)
        # confirm du roi doi fee -> reopen discrepancy
        await pay.record_evidence(conn, oid_r, kind="customer_reported", amount_vnd=250000, recorded_by="customer",
                                  command_key=key("g12-rep"))
        await pay.record_evidence(conn, oid_r, kind="shop_confirmed_received", amount_vnd=250000, recorded_by="po",
                                  command_key=key("g12-conf"))
        await ship.set_manual_quote(conn, oid_r, actor="staff1", fee_vnd=60000)  # doi fee sau khi confirmed
        prow = await conn.fetchrow("SELECT status, amount_due_vnd FROM payments WHERE order_id=$1", oid_r)
        ck("G12 da confirmed: quote doi -> reopen discrepancy + due moi", prow["status"] == "discrepancy"
           and prow["amount_due_vnd"] == 260000, f"{prow['status']}/{prow['amount_due_vnd']}")

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        sys.exit(1 if FAILS else 0)
    finally:
        await conn.close()


asyncio.run(main())
