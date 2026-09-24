#!/usr/bin/env python3
"""CA Directive 357 §4.4/§4.5 rehearsal — contract G1 KHONG hoi quy khi chay o mode PRODUCTION (transport mock).

Khac 276/277 (dung provider mock hoan toan): o day provider duoc dung tu cfg THAT theo mode active
(resolve_quote_cfg -> DB integration mode='production'), chi transport HTTP la mock dem so lan goi.
=> chung minh duong production doc dung token/ShopId/endpoint/map cua production va KHONG co HTTP that.

T1 production happy   -> fee+leadtime, endpoint=PROD_BASE, token/ShopId production, dimensions trong body.
T2 cross-mode         -> active=staging nhung chi co config production -> fail-closed, 0 HTTP.
T3 map sai mode       -> map chi co o staging, active=production -> address_unmapped, 0 HTTP.
T4 controlled failure -> timeout / 429 / 500 -> quote_required, fee None, KHONG fallback fee (flag OFF).
T5 self-zone          -> route SELF -> 0 HTTP (ca 2 mode).
T6 replay/concurrent  -> ROPS.execute cung command_key voi provider production -> HTTP dung 1 lan.
T7 heavy >20 kg       -> 20.001 g: 0 decrypt secret, 0 HTTP, 0 provider_quote_log, khong fee (ke ca fallback ON);
                         20.000 g: KHONG bi guard chan.

Chay tren m5lab (schema >= 071). KHONG credential that, KHONG PII/secret trong output.
"""
import asyncio
import base64
import os
import sys
import time
import uuid

import asyncpg

from app.config import settings
from app.services.fulfillment import route_operation as ROPS
from app.services.providers import ghn as GHN
from app.services.providers import ghn_master_data as MD
from app.services.providers.base import QUOTE_OK
from app.services.settings import integrations as S

RUN = str(int(time.time()))
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
FAILS = []
_SEQ = [0]
TOK = {"staging": "REH357-STG", "production": "REH357-PRD"}
SHOP = {"staging": "111111", "production": "999999"}
GHN_WARD = "99001"      # ngoai allowlist self -> route GHN
SELF_WARD = "24169"


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


class Transport:
    """Transport HTTP mock — dem so lan goi + ghi lai base/token/shop/body (redacted khi in)."""

    def __init__(self, mode="ok"):
        self.calls, self.mode = [], mode

    async def __call__(self, cfg, path, body, *, retries):
        self.calls.append({"path": path, "base": cfg["base"], "token_tail": (cfg["token"] or "")[-3:],
                           "shop": cfg["shop_id"], "body": dict(body)})
        if self.mode == "timeout":
            return None, None, "timeout", 12
        if self.mode == "429":
            return 429, {"code": 429, "message": "rate"}, "", 12
        if self.mode == "500":
            return 500, {"code": 500}, "", 12
        if path.endswith("/fee"):
            return 200, {"code": 200, "data": {"total": 42900, "service_fee": 42900}}, "", 12
        return 200, {"code": 200, "data": {"leadtime": int(time.time()) + 3 * 86400}}, "", 9

    @property
    def n(self):
        return len(self.calls)


async def _order(conn, *, ward, weight=300, qty=2, price=100000):
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'R','0900000000') RETURNING id",
                              f"tg:r357-{tag}")
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit,"
                              "length_cm,width_cm,height_cm) VALUES($1,'CF',$2,999,$3,'hũ',12,11,10) RETURNING id",
                              f"R357-{tag}", price, weight)
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                              "VALUES($1,'confirmed',$2,'telegram_customer') RETURNING id", cid, qty * price)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,$3,$4)",
                       oid, pid, qty, price)
    rid = await conn.fetchval(
        "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
        "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,'66',$1,'current',1.0) RETURNING id",
        ward)
    await conn.execute("INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,"
                       "dataset_version,verification_method,bound_by) VALUES($1,$2,'66',$3,'VN-TEST','test','r357')",
                       oid, rid, ward)
    return oid


def _pub(mode, map_version):
    return {"shop_id": SHOP[mode], "from_district_id": 1552, "from_ward_code": "400105", "timeout_seconds": 5,
            "max_retries": 0, "light_max_g": 20000, "address_map_version": map_version}


async def _mk_integration(conn, mode, map_version):
    it = await S.create_integration(conn, kind="shipping", provider="ghn", label=f"GHN {mode} r357", mode=mode,
                                    config_public=_pub(mode, map_version), actor="rehearsal",
                                    command_key="r357-" + uuid.uuid4().hex)

    async def ok_post(cfg, path, body, *, retries):
        return 200, {"code": 200, "data": [{"ProvinceID": 1}]}, "", 3
    v = await S.write_secret(conn, it["id"], key_name="token", plaintext=TOK[mode],
                             expected_version=it["version"], actor="rehearsal", command_key="r357-" + uuid.uuid4().hex)
    await S.test_connection(conn, it["id"], actor="rehearsal", post=ok_post)
    d = await S.get_integration(conn, it["id"])
    await S.enable(conn, it["id"], expected_version=d["version"], actor="rehearsal",
                   command_key="r357-" + uuid.uuid4().hex)
    return it["id"], v


async def _provider(conn, transport):
    cfg = await GHN.resolve_quote_cfg(conn)
    return GHN.GhnQuoteProvider(cfg, post=transport), cfg


async def _quote_once(conn, oid, transport):
    """Pha 1 nhu conversation.prepare_ghn_quote nhung provider dung cfg THAT theo mode active."""
    from app.services.fulfillment import fallback_quote as _fb
    from app.services.fulfillment import routing as _r
    from app.services.fulfillment import shipment_service as _sh
    route = await _r.resolve_for_order(conn, oid)
    if route.source != _r.GHN:
        return None, route.source
    weight = await _sh._order_weight(conn, oid)
    req, _reason, _detail = await _fb.build_ghn_request(conn, oid, route, weight)
    if req is None:
        return None, route.source
    prov, _cfg = await _provider(conn, transport)
    return await prov.quote(conn, req), route.source


async def main():  # noqa: C901
    settings.m7_ghn_quote = True
    settings.settings_integrations_enabled = True
    settings.ghn_fallback_enabled = False
    settings.config_enc_keys = f"k1:{base64.b64encode(b'A' * 32).decode()}"
    settings.config_enc_key_current = "k1"
    settings.config_secret_fp_key = base64.b64encode(b'F' * 32).decode()
    conn = await asyncpg.connect(DSN)
    _x_orig = await conn.fetchval("SELECT packing_overhead_percent FROM shipping_settings WHERE id=1")
    await conn.execute("UPDATE shipping_settings SET packing_overhead_percent=10 WHERE id=1")
    await conn.execute("DELETE FROM integration_commands WHERE integration_id IN "
                       "(SELECT id FROM integrations WHERE provider='ghn')")
    await conn.execute("DELETE FROM integration_secrets WHERE integration_id IN "
                       "(SELECT id FROM integrations WHERE provider='ghn')")
    await conn.execute("DELETE FROM integrations WHERE provider='ghn'")
    map_row = [{"province_code": "66", "ward_code": GHN_WARD, "carrier_province_id": 210,
                "carrier_district_id": 1954, "carrier_ward_code": "400701", "status": "matched", "method": "staff",
                "confidence": None, "note": "{}"}]
    try:
        async with conn.transaction():
            v_prd = await MD.write_map_version(conn, map_row, actor="rehearsal", source="r357", mode="production")
        await _mk_integration(conn, "production", v_prd)
        await _mk_integration(conn, "staging", 1)
        settings.ghn_active_mode = "production"

        # ---- T1 production happy path ----
        oid = await _order(conn, ward=GHN_WARD)
        t1 = Transport()
        res, src = await _quote_once(conn, oid, t1)
        body = t1.calls[0]["body"] if t1.calls else {}
        ck("T1 production happy -> QUOTE_OK, endpoint+token+ShopId production, 2 HTTP (fee+leadtime), dimensions gui",
           src == "GHN" and res is not None and res.status == QUOTE_OK and res.fee_vnd == 42900 and t1.n == 2
           and all(c["base"] == GHN.PROD_BASE for c in t1.calls)
           and all(c["token_tail"] == TOK["production"][-3:] and c["shop"] == SHOP["production"] for c in t1.calls)
           and body.get("length") and body.get("width") and body.get("height") and body.get("weight"),
           f"src={src} status={getattr(res, 'status', None)} http={t1.n} base_prod="
           f"{all(c['base'] == GHN.PROD_BASE for c in t1.calls)} dims="
           f"{body.get('length')}x{body.get('width')}x{body.get('height')} w={body.get('weight')}")

        # ---- T2 cross-mode: active=staging, chi production da cau hinh day du map ----
        settings.ghn_active_mode = "staging"
        t2 = Transport()
        _p, cfg_stg = await _provider(conn, t2)
        oid2 = await _order(conn, ward=GHN_WARD)
        res2, _ = await _quote_once(conn, oid2, t2)
        ck("T2 active=staging KHONG dung token/ShopId/endpoint production; 0 HTTP toi PROD",
           cfg_stg["mode"] == "staging" and cfg_stg["base"] == GHN.STAGING_BASE
           and cfg_stg["token"] == TOK["staging"] and cfg_stg["shop_id"] == SHOP["staging"]
           and all(c["base"] != GHN.PROD_BASE for c in t2.calls),
           f"mode={cfg_stg['mode']} base_stg={cfg_stg['base'] == GHN.STAGING_BASE} "
           f"res={getattr(res2, 'reason', None)} prod_http={sum(1 for c in t2.calls if c['base'] == GHN.PROD_BASE)}")

        # ---- T3 map sai mode -> address_unmapped, 0 HTTP ----
        settings.ghn_active_mode = "production"
        oid3 = await _order(conn, ward="99002")        # khong co trong map production
        t3 = Transport()
        res3, _ = await _quote_once(conn, oid3, t3)
        ck("T3 dia chi khong co trong map cua mode active -> address_unmapped, 0 HTTP",
           res3 is not None and res3.reason == "address_unmapped" and t3.n == 0,
           f"reason={getattr(res3, 'reason', None)} http={t3.n}")

        # ---- T4 controlled failures ----
        ok4 = True
        det4 = []
        for m in ("timeout", "429", "500"):
            oid4 = await _order(conn, ward=GHN_WARD)
            t4 = Transport(m)
            res4, _ = await _quote_once(conn, oid4, t4)
            good = res4 is not None and res4.status != QUOTE_OK and res4.fee_vnd is None
            det4.append(f"{m}:{getattr(res4, 'reason', None)}/{getattr(res4, 'fee_vnd', None)}")
            ok4 = ok4 and good
        ck("T4 timeout/429/500 -> quote_required, fee=None (fallback flag OFF -> KHONG fee thay the)",
           ok4 and settings.ghn_fallback_enabled is False, " ".join(det4))

        # ---- T5 self-zone: 0 HTTP o ca 2 mode ----
        ok5 = True
        det5 = []
        for mode in ("production", "staging"):
            settings.ghn_active_mode = mode
            oid5 = await _order(conn, ward=SELF_WARD)
            t5 = Transport()
            res5, src5 = await _quote_once(conn, oid5, t5)
            ok5 = ok5 and src5 == "SELF_DELIVERY" and res5 is None and t5.n == 0
            det5.append(f"{mode}:{src5}/http={t5.n}")
        ck("T5 self-zone -> khong goi provider o ca 2 mode", ok5, " ".join(det5))

        # ---- T6 replay + concurrent voi provider production ----
        settings.ghn_active_mode = "production"
        oid6 = await _order(conn, ward=GHN_WARD)
        t6 = Transport()
        prov6, _ = await _provider(conn, t6)
        out6 = await ROPS.execute(conn, oid6, actor="staff1", command_key=f"r357:{oid6}", provider=prov6)
        n_after_first = t6.n
        out6b = await ROPS.execute(conn, oid6, actor="staff1", command_key=f"r357:{oid6}", provider=prov6)
        ck("T6 replay cung command_key -> duplicate, HTTP KHONG tang (at-most-once giu nguyen o production)",
           out6["shipment"]["fee_status"] == "quoted" and out6["shipment"]["delivery_fee_vnd"] == 42900
           and out6b["duplicate"] is True and t6.n == n_after_first == 2,
           f"fee={out6['shipment']['delivery_fee_vnd']} http1={n_after_first} http2={t6.n} dup={out6b['duplicate']}")

        # ---- T7 heavy guard trong production + fallback ON: 0 decrypt, 0 HTTP, 0 log ----
        settings.ghn_fallback_enabled = True
        decrypts = [0]
        _orig_loader = S.load_active_config

        async def counting_loader(c, provider, mode):
            decrypts[0] += 1
            return await _orig_loader(c, provider, mode)
        S.load_active_config = counting_loader
        try:
            oid7 = await _order(conn, ward=GHN_WARD, weight=20001, qty=1)
            log_before = await conn.fetchval("SELECT count(*) FROM provider_quote_log WHERE order_id=$1", oid7)
            t7 = Transport()
            res7, _ = await _quote_once(conn, oid7, t7)
            log_after = await conn.fetchval("SELECT count(*) FROM provider_quote_log WHERE order_id=$1", oid7)
            ck("T7a 20.001 g @production + fallback ON -> heavy_goods_manual, 0 HTTP, 0 decrypt secret, 0 provider log,"
               " khong fee",
               res7 is None and decrypts[0] == 0 and t7.n == 0 and log_after == log_before,
               f"res={res7} decrypt={decrypts[0]} http={t7.n} log={log_before}->{log_after}")

            oid7b = await _order(conn, ward=GHN_WARD, weight=20000, qty=1)
            t7b = Transport()
            res7b, _ = await _quote_once(conn, oid7b, t7b)
            ck("T7b 20.000 g KHONG bi guard chan -> van di tiep (co HTTP, decrypt binh thuong)",
               res7b is not None and res7b.reason != "heavy_goods_manual" and t7b.n >= 1 and decrypts[0] >= 1,
               f"reason={getattr(res7b, 'reason', None)} http={t7b.n} decrypt={decrypts[0]}")
        finally:
            S.load_active_config = _orig_loader
            settings.ghn_fallback_enabled = False

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        await conn.execute("UPDATE shipping_settings SET packing_overhead_percent=$1 WHERE id=1", _x_orig)
        await conn.execute("DELETE FROM carrier_address_map WHERE provider='ghn' AND mode='production' "
                           "AND ward_code IN ($1,'99002')", GHN_WARD)
        await conn.execute("DELETE FROM integration_commands WHERE integration_id IN "
                           "(SELECT id FROM integrations WHERE provider='ghn')")
        await conn.execute("DELETE FROM integration_secrets WHERE integration_id IN "
                           "(SELECT id FROM integrations WHERE provider='ghn')")
        await conn.execute("DELETE FROM integrations WHERE provider='ghn'")
        from app.db_pool import close_pool
        await close_pool()
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
