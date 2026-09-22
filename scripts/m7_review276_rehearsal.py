#!/usr/bin/env python3
"""M7 Review 276 focused rehearsal — blocker 276-01 route/quote server-side idempotency. Chay m5lab (schema>=066).

GHN mock dem so lan goi. Xac minh: GHN call count == DUNG 1 cho cung logical command; apply 1 lan; crash-recovery.

T1 owner (GHN) -> quoted, GHN=1, done, duplicate=False.
T2 replay cung key -> duplicate=True, GHN VAN =1 (khong goi lai), ket qua giu.
T3 hai request dong thoi cung key -> DUNG 1 owner apply + 1 in_flight, GHN=1.
T4 cung key khac fingerprint (payload khac) -> conflict.
T5 crash sau claim (chua goi provider) + lease het han -> takeover re-execute, GHN=1 (chi lan recovery).
T6 crash sau provider_recorded -> recover apply KHONG goi GHN lai (GHN=1 tu truoc), quote van ap dung.
T7 self/manual deterministic -> done, GHN=0; replay -> GHN=0 (khong regression).
T8 thieu command_key -> ShipmentError.
Re-runnable (RUN). KHONG PII/secret.
"""
import asyncio
import os
import sys
import time

import asyncpg

from app.config import settings
from app.services.fulfillment import conversation as FC
from app.services.fulfillment import route_operation as ROPS
from app.services.fulfillment import shipment_service as SH
from app.services.providers.base import QUOTE_OK, QuoteResult

RUN = str(int(time.time()))
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
FAILS = []
_SEQ = [0]


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


class CountingGhn:
    """Mock GHN provider — dem so lan goi quote(). Tra fee co dinh, request_fingerprint khop req (de route_and_quote ap)."""
    provider = "ghn"
    name = "ghn"

    def __init__(self):
        self.calls = 0

    async def quote(self, conn, req):
        self.calls += 1
        return QuoteResult(status=QUOTE_OK, provider="ghn", fee_vnd=30000, eta_text="2-3 ngay",
                           leadtime_days=2, request_fingerprint=req.fingerprint(),
                           carrier_ids={"to_ward_code": req.ward_code})


async def _order(conn, *, ward, weight=300, qty=2, price=100000):
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    psid = f"tg:r276-{tag}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'R','0900000000') RETURNING id", psid)
    # CA 341-01: request GHN dung kich thuoc dong thung -> san pham PHAI co kich thuoc (thieu -> khong goi provider).
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit,"
                              "length_cm,width_cm,height_cm) VALUES($1,'CF',$2,999,$3,'hũ',10,10,10) RETURNING id",
                              f"R276-{tag}", price, weight)
    total = qty * price
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                              "VALUES($1,'confirmed',$2,'telegram_customer') RETURNING id", cid, total)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,$3,$4)",
                       oid, pid, qty, price)
    rid = await conn.fetchval(
        "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
        "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,'66',$1,'current',1.0) RETURNING id",
        ward)
    await conn.execute("INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,"
                       "dataset_version,verification_method,bound_by) VALUES($1,$2,'66',$3,'VN-TEST','test','r276')",
                       oid, rid, ward)
    return oid


async def _route_source(conn, oid):
    from app.services.fulfillment import routing as R
    r = await R.resolve_for_order(conn, oid)
    return r.source


async def main():  # noqa: C901
    settings.m7_ghn_quote = True
    conn = await asyncpg.connect(DSN)
    # CA 341-01: packing overhead x phai cau hinh (thieu -> khong goi provider). Luu goc, khoi phuc o finally.
    _x_orig = await conn.fetchval("SELECT packing_overhead_percent FROM shipping_settings WHERE id=1")
    await conn.execute("UPDATE shipping_settings SET packing_overhead_percent=10 WHERE id=1")
    try:
        # xac dinh 1 ward NGOAI allowlist -> GHN, va ward 24169 -> SELF (browser seed da chung minh)
        GHN_WARD = "99001"
        oid = await _order(conn, ward=GHN_WARD)
        src = await _route_source(conn, oid)
        if src != "GHN":
            ck("PRECOND: ward 99001 route GHN", False, src)
            print("RESULT:", f"FAIL {FAILS}")
            return 1

        # ---- T1 owner ----
        g = CountingGhn()
        out = await ROPS.execute(conn, oid, actor="staff1", command_key=f"k1:{oid}", provider=g)
        sh = out["shipment"]
        ck("T1 owner GHN -> quoted fee=30000, GHN goi=1, done, duplicate=False",
           sh["fee_status"] == "quoted" and sh["delivery_fee_vnd"] == 30000 and g.calls == 1
           and out["op_state"] == "done" and out["duplicate"] is False,
           f"fee={sh['fee_status']}/{sh['delivery_fee_vnd']} ghn={g.calls} dup={out['duplicate']}")

        # ---- T2 replay same key ----
        out2 = await ROPS.execute(conn, oid, actor="staff1", command_key=f"k1:{oid}", provider=g)
        ck("T2 replay cung key -> duplicate=True, GHN VAN=1 (khong goi lai)",
           out2["duplicate"] is True and g.calls == 1 and out2["shipment"]["fee_status"] == "quoted",
           f"dup={out2['duplicate']} ghn={g.calls}")

        # ---- T3 concurrent same key ----
        oidc = await _order(conn, ward=GHN_WARD)
        gc = CountingGhn()
        c1 = await asyncpg.connect(DSN)
        c2 = await asyncpg.connect(DSN)
        try:
            async def run(cc):
                try:
                    r = await ROPS.execute(cc, oidc, actor="staff1", command_key=f"kc:{oidc}", provider=gc)
                    return ("ok", r["duplicate"])
                except ROPS.RouteOpInFlight:
                    return ("in_flight", None)
                except ROPS.RouteOpConflict:
                    return ("conflict", None)
            res = await asyncio.gather(run(c1), run(c2))
        finally:
            await c1.close()
            await c2.close()
        oks = [r for r in res if r[0] == "ok"]
        inflight = [r for r in res if r[0] == "in_flight"]
        shc = await SH.get_shipment(conn, oidc)
        ck("T3 hai request dong thoi cung key -> DUNG 1 owner apply + 1 in_flight, GHN=1, quoted 1 lan",
           len(oks) == 1 and len(inflight) == 1 and gc.calls == 1 and shc["fee_status"] == "quoted",
           f"res={res} ghn={gc.calls}")

        # ---- T4 conflict (same key, khac fingerprint) ----
        oidx = await _order(conn, ward=GHN_WARD)
        await conn.execute(
            "INSERT INTO fulfillment_route_operations(order_id,action,command_key,request_fingerprint,state,"
            "owner_token,lease_expires_at) VALUES($1,'route_quote',$2,'OTHER_FP','claimed','someone',now()+interval '1 hour')",
            oidx, f"kx:{oidx}")
        gx = CountingGhn()
        conflict = False
        try:
            await ROPS.execute(conn, oidx, actor="staff1", command_key=f"kx:{oidx}", provider=gx)
        except ROPS.RouteOpConflict:
            conflict = True
        ck("T4 cung key khac fingerprint -> conflict (khong goi GHN)", conflict and gx.calls == 0,
           f"conflict={conflict} ghn={gx.calls}")

        # ---- T5 crash sau claim (chua provider) + lease het han -> takeover re-execute ----
        oid5 = await _order(conn, ward=GHN_WARD)
        g5 = CountingGhn()
        owner_dead = ROPS.new_owner_token()
        async with conn.transaction():
            c5 = await ROPS.claim(conn, oid5, command_key=f"k5:{oid5}", request_fingerprint=ROPS.fingerprint(oid5),
                                  owner_token=owner_dead)
        ck("T5a claim dau -> owner (state claimed)", c5["kind"] == "owner", c5["kind"])
        # gia lap crash: lease het han
        await conn.execute("UPDATE fulfillment_route_operations SET lease_expires_at=now()-interval '1 min' "
                           "WHERE order_id=$1 AND command_key=$2", oid5, f"k5:{oid5}")
        out5 = await ROPS.execute(conn, oid5, actor="staff1", command_key=f"k5:{oid5}", provider=g5)
        ck("T5b lease het han -> takeover re-execute, GHN=1 (chi lan recovery), done + quoted",
           out5["op_state"] == "done" and g5.calls == 1 and out5["shipment"]["fee_status"] == "quoted",
           f"ghn={g5.calls} state={out5['op_state']}")

        # ---- T6 crash sau provider_recorded -> recover KHONG goi GHN lai ----
        oid6 = await _order(conn, ward=GHN_WARD)
        g6 = CountingGhn()
        owner6 = ROPS.new_owner_token()
        async with conn.transaction():
            c6 = await ROPS.claim(conn, oid6, command_key=f"k6:{oid6}", request_fingerprint=ROPS.fingerprint(oid6),
                                  owner_token=owner6)
        async with conn.transaction():
            await ROPS.mark_provider_started(conn, c6["op"]["id"], provider="ghn", expected_owner=owner6)
        ghn_res = await FC.prepare_ghn_quote(conn, oid6, provider=g6)   # goi GHN 1 lan (ghi nhan)
        async with conn.transaction():
            rec = await ROPS.record_provider(conn, c6["op"]["id"],
                                             provider_result=ghn_res.snapshot(), expected_owner=owner6)
        ck("T6a provider_recorded (GHN goi 1 lan, luu ket qua)", rec is not None and g6.calls == 1,
           f"rec={rec is not None} ghn={g6.calls}")
        # gia lap crash TRUOC khi apply: owner cu 'chet' -> lease het han (recovery chi khi lease expired)
        await conn.execute("UPDATE fulfillment_route_operations SET lease_expires_at=now()-interval '1 min' "
                           "WHERE order_id=$1 AND command_key=$2", oid6, f"k6:{oid6}")
        # execute lai (provider khac chi de chac chan KHONG goi)
        g6b = CountingGhn()
        out6 = await ROPS.execute(conn, oid6, actor="staff1", command_key=f"k6:{oid6}", provider=g6b)
        sh6 = out6["shipment"]
        ck("T6b recover -> apply KHONG goi GHN lai (GHN recovery=0), quote ap dung (fee=30000), done",
           g6b.calls == 0 and sh6["fee_status"] == "quoted" and sh6["delivery_fee_vnd"] == 30000
           and out6["op_state"] == "done", f"ghn_recover={g6b.calls} fee={sh6['delivery_fee_vnd']}")

        # ---- T6c provider_recorded + lease CON hieu luc (owner dang apply) -> in_flight (KHONG takeover) ----
        oid6c = await _order(conn, ward=GHN_WARD)
        g6c = CountingGhn()
        owner6c = ROPS.new_owner_token()
        async with conn.transaction():
            cc6 = await ROPS.claim(conn, oid6c, command_key=f"k6c:{oid6c}",
                                   request_fingerprint=ROPS.fingerprint(oid6c), owner_token=owner6c)
        async with conn.transaction():
            await ROPS.mark_provider_started(conn, cc6["op"]["id"], provider="ghn", expected_owner=owner6c)
        gr = await FC.prepare_ghn_quote(conn, oid6c, provider=g6c)
        async with conn.transaction():
            await ROPS.record_provider(conn, cc6["op"]["id"],
                                       provider_result=gr.snapshot(), expected_owner=owner6c)
        # lease CON hieu luc -> request khac phai in_flight (khong cuop quyen owner dang apply)
        inflight6 = False
        try:
            await ROPS.execute(conn, oid6c, actor="staff2", command_key=f"k6c:{oid6c}", provider=CountingGhn())
        except ROPS.RouteOpInFlight:
            inflight6 = True
        ck("T6c provider_recorded + lease con hieu luc -> in_flight (khong takeover, tranh double-apply)", inflight6,
           inflight6)

        # ---- T7 self route deterministic, khong goi GHN ----
        oid7 = await _order(conn, ward="24169")
        src7 = await _route_source(conn, oid7)
        g7 = CountingGhn()
        out7 = await ROPS.execute(conn, oid7, actor="staff1", command_key=f"k7:{oid7}", provider=g7)
        out7b = await ROPS.execute(conn, oid7, actor="staff1", command_key=f"k7:{oid7}", provider=g7)
        ck("T7 self route deterministic -> done, GHN=0; replay GHN=0 (khong regression)",
           src7 == "SELF_DELIVERY" and out7["op_state"] == "done" and out7b["duplicate"] is True and g7.calls == 0,
           f"src={src7} ghn={g7.calls} dup2={out7b['duplicate']}")

        # ---- T8 thieu command_key ----
        bad = False
        try:
            await ROPS.execute(conn, oid7, actor="staff1", command_key="   ", provider=CountingGhn())
        except SH.ShipmentError:
            bad = True
        ck("T8 thieu command_key -> ShipmentError", bad, bad)

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        await conn.execute("UPDATE shipping_settings SET packing_overhead_percent=$1 WHERE id=1", _x_orig)
        from app.db_pool import close_pool
        await close_pool()
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
