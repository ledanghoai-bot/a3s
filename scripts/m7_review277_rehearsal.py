#!/usr/bin/env python3
"""M7 Review 277 focused rehearsal — 277-01 (at-most-once provider) + 277-02 (immutable replay). m5lab (schema>=067).

GHN mock dem so lan goi. Xac minh at-most-once: total provider call count == 1 cho moi window fault + concurrency.

277-01 A: crash NGAY SAU provider response nhung TRUOC record_provider -> row 'provider_started'(ghn). Retry sau
   lease -> AMBIGUOUS (KHONG goi GHN lan hai; total==1), mo attention reconciliation, receipt -> failed.
277-01 A2: retry cung key lan nua -> RouteOpAmbiguous (idempotent, total==1).
277-01 B: provider mock chay LAU hon lease + concurrent retry -> total GHN==1 (request thu hai KHONG goi provider
   vi 'provider_started' khong takeover-goi-provider).
277-01 C: crash TRUOC provider_started (state 'claimed') van recover duoc (owner re-run, total==1).
277-01 D: self/manual (khong goi external) crash+lease-expired -> an toan re-run (KHONG ambiguous), GHN=0.
277-02: key A done (version_A); key B re-quote (version bump); retry key A tra CHINH XAC result/version cua A
   (bat bien), KHONG goi/apply lai.
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
    provider = "ghn"
    name = "ghn"

    def __init__(self, sleep_s=0.0):
        self.calls = 0
        self.sleep_s = sleep_s

    async def quote(self, conn, req):
        self.calls += 1
        if self.sleep_s:
            await asyncio.sleep(self.sleep_s)
        return QuoteResult(status=QUOTE_OK, provider="ghn", fee_vnd=30000, eta_text="2-3 ngay",
                           leadtime_days=2, request_fingerprint=req.fingerprint())


async def _order(conn, *, ward, weight=300, qty=2, price=100000):
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    psid = f"tg:r277-{tag}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'R','0900000000') RETURNING id", psid)
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
                              "VALUES($1,'CF',$2,999,$3,'hũ') RETURNING id", f"R277-{tag}", price, weight)
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                              "VALUES($1,'confirmed',$2,'telegram_customer') RETURNING id", cid, qty * price)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,$3,$4)",
                       oid, pid, qty, price)
    rid = await conn.fetchval(
        "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
        "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,'66',$1,'current',1.0) RETURNING id",
        ward)
    await conn.execute("INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,"
                       "dataset_version,verification_method,bound_by) VALUES($1,$2,'66',$3,'VN-TEST','test','r277')",
                       oid, rid, ward)
    return oid


async def _state(conn, oid, key):
    return await conn.fetchval("SELECT state FROM fulfillment_route_operations WHERE order_id=$1 AND command_key=$2",
                               oid, key)


async def _n_att(conn, oid, reason):
    return await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND reason=$2 AND status='open'",
                               oid, reason)


async def main():  # noqa: C901
    settings.m7_ghn_quote = True
    conn = await asyncpg.connect(DSN)
    GW = "99001"  # ward NGOAI allowlist -> GHN
    try:
        # ===== 277-01 A: crash sau provider response, truoc record_provider -> ambiguous, total GHN==1 =====
        oidA = await _order(conn, ward=GW)
        gA = CountingGhn()
        ownerA = ROPS.new_owner_token()
        keyA = f"a:{oidA}"
        async with conn.transaction():
            cA = await ROPS.claim(conn, oidA, command_key=keyA, request_fingerprint=ROPS.fingerprint(oidA),
                                  owner_token=ownerA)
        async with conn.transaction():
            await ROPS.mark_provider_started(conn, cA["op"]["id"], provider="ghn", expected_owner=ownerA)
        _ = await FC.prepare_ghn_quote(conn, oidA, provider=gA)   # provider goi 1 lan (response ve)
        # <<< CRASH ngay day: KHONG record_provider. Gia lap owner chet -> lease het han.
        await conn.execute("UPDATE fulfillment_route_operations SET lease_expires_at=now()-interval '1 min' "
                           "WHERE order_id=$1 AND command_key=$2", oidA, keyA)
        gA2 = CountingGhn()
        amb = False
        try:
            await ROPS.execute(conn, oidA, actor="staff1", command_key=keyA, provider=gA2)
        except ROPS.RouteOpAmbiguous:
            amb = True
        st = await _state(conn, oidA, keyA)
        natt = await _n_att(conn, oidA, "provider_error")
        ck("277-01 A crash sau provider/truoc record -> AMBIGUOUS, total GHN==1 (KHONG goi lai), receipt failed, "
           "attention mo", amb and gA.calls == 1 and gA2.calls == 0 and st == "failed" and int(natt) == 1,
           f"amb={amb} ghn={gA.calls}/{gA2.calls} state={st} att={natt}")
        # A2: retry cung key -> van ambiguous (idempotent, total==1)
        gA3 = CountingGhn()
        amb2 = False
        try:
            await ROPS.execute(conn, oidA, actor="staff1", command_key=keyA, provider=gA3)
        except ROPS.RouteOpAmbiguous:
            amb2 = True
        ck("277-01 A2 retry cung key -> RouteOpAmbiguous idempotent, total GHN VAN==1", amb2 and gA3.calls == 0,
           f"amb2={amb2} ghn={gA3.calls}")

        # ===== 277-01 B: provider mock LAU hon lease + concurrent retry -> total GHN==1 =====
        oidB = await _order(conn, ward=GW)
        gB = CountingGhn(sleep_s=0.6)   # provider cham -> owner con trong HTTP khi request 2 toi
        keyB = f"b:{oidB}"

        async def run_owner(cc):
            try:
                r = await ROPS.execute(cc, oidB, actor="s", command_key=keyB, provider=gB, lease_seconds=60)
                return ("ok", r["duplicate"])
            except ROPS.RouteOpInFlight:
                return ("in_flight", None)
            except ROPS.RouteOpAmbiguous:
                return ("ambiguous", None)

        async def run_second(cc):
            await asyncio.sleep(0.15)   # den SAU khi owner da provider_started (dang trong HTTP)
            return await run_owner(cc)

        c1 = await asyncpg.connect(DSN)
        c2 = await asyncpg.connect(DSN)
        try:
            resB = await asyncio.gather(run_owner(c1), run_second(c2))
        finally:
            await c1.close()
            await c2.close()
        oks = [r for r in resB if r[0] == "ok"]
        shB = await SH.get_shipment(conn, oidB)
        ck("277-01 B provider LAU hon window + concurrent -> total GHN==1, DUNG 1 apply (request 2 KHONG goi provider)",
           gB.calls == 1 and len(oks) == 1 and shB["fee_status"] == "quoted",
           f"ghn={gB.calls} res={resB}")

        # ===== 277-01 C: crash TRUOC provider_started ('claimed') -> an toan re-run, total==1 =====
        oidC = await _order(conn, ward=GW)
        gC = CountingGhn()
        ownerC = ROPS.new_owner_token()
        keyC = f"c:{oidC}"
        async with conn.transaction():
            await ROPS.claim(conn, oidC, command_key=keyC, request_fingerprint=ROPS.fingerprint(oidC),
                             owner_token=ownerC)
        # crash TRUOC khi goi provider -> lease het han
        await conn.execute("UPDATE fulfillment_route_operations SET lease_expires_at=now()-interval '1 min' "
                           "WHERE order_id=$1 AND command_key=$2", oidC, keyC)
        outC = await ROPS.execute(conn, oidC, actor="staff1", command_key=keyC, provider=gC)
        ck("277-01 C crash truoc provider_started ('claimed') -> re-run an toan, GHN==1, done + quoted",
           gC.calls == 1 and outC["op_state"] == "done" and outC["shipment"]["fee_status"] == "quoted",
           f"ghn={gC.calls} state={outC['op_state']}")

        # ===== 277-01 D: self route crash+lease-expired -> KHONG ambiguous (khong goi external), re-run =====
        oidD = await _order(conn, ward="24169")   # SELF
        gD = CountingGhn()
        ownerD = ROPS.new_owner_token()
        keyD = f"d:{oidD}"
        async with conn.transaction():
            cD = await ROPS.claim(conn, oidD, command_key=keyD, request_fingerprint=ROPS.fingerprint(oidD),
                                  owner_token=ownerD)
        async with conn.transaction():
            await ROPS.mark_provider_started(conn, cD["op"]["id"], provider="none", expected_owner=ownerD)
        await conn.execute("UPDATE fulfillment_route_operations SET lease_expires_at=now()-interval '1 min' "
                           "WHERE order_id=$1 AND command_key=$2", oidD, keyD)
        outD = await ROPS.execute(conn, oidD, actor="staff1", command_key=keyD, provider=gD)
        ck("277-01 D self provider_started='none' + lease-expired -> re-run an toan (KHONG ambiguous), GHN=0, done",
           outD["op_state"] == "done" and gD.calls == 0 and outD["shipment"]["fee_status"] == "quoted",
           f"ghn={gD.calls} state={outD['op_state']}")

        # ===== 277-02: replay tra result BAT BIEN cua command cu (khong doc current shipment) =====
        oidR = await _order(conn, ward=GW)
        gR = CountingGhn()
        keyRA = f"ra:{oidR}"
        outA = await ROPS.execute(conn, oidR, actor="staff1", command_key=keyRA, provider=gR)
        verA = outA["shipment"]["version"]
        # key B khac -> route/quote lai order -> version tang
        keyRB = f"rb:{oidR}"
        outB = await ROPS.execute(conn, oidR, actor="staff1", command_key=keyRB, provider=gR)
        verB = outB["shipment"]["version"]
        cur = await SH.get_shipment(conn, oidR)
        # retry key A -> replay result BAT BIEN cua A (version_A), KHONG goi/apply lai
        gR_before = gR.calls
        outA2 = await ROPS.execute(conn, oidR, actor="staff1", command_key=keyRA, provider=gR)
        cur2 = await SH.get_shipment(conn, oidR)
        ck("277-02 key B doi version sau key A; retry key A tra CHINH XAC version_A (bat bien), KHONG re-apply",
           verB == verA + 1 and outA2["duplicate"] is True and outA2["shipment"]["version"] == verA
           and outA2["shipment"]["version"] != cur["version"] and cur2["version"] == verB and gR.calls == gR_before,
           f"verA={verA} verB={verB} replayA={outA2['shipment']['version']} cur={cur2['version']} ghn_recall={gR.calls - gR_before}")

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        from app.db_pool import close_pool
        await close_pool()
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
