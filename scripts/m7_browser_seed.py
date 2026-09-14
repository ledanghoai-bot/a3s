#!/usr/bin/env python3
"""Seed cho browser smoke 274-04: staff token + 1 don M7 o staff_attention(payment_mismatch) co QR + provider event.
In JSON {token, order_id}. Chay m5lab (M6_TEST_DB=1)."""
import asyncio
import json
import os
import sys
import time

import asyncpg

from app.config import settings
from app.services import auth_service
from app.services.fulfillment import conversation as C
from app.services.payment import payment_service as PAY
from app.services.payment import provider_ingest as PI
from app.services.providers import sepay as SP

RUN = str(int(time.time()))
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
ACCT, BIN = "0071000777666", "970415"


async def main():
    settings.m7_conversational_fulfillment = True
    settings.m7_sepay_test_connector = True
    settings.sepay_allowed_accounts = ""
    conn = await asyncpg.connect(DSN)
    try:
        st = await auth_service.create_staff_user(f"m7smoke_{RUN}", "smoke_pw_12345678", "M7 SMOKE", role_key="admin")
        token = await auth_service.create_session(st["id"])
        async with conn.transaction():
            await PAY.set_bank_account(conn, bank="VietinBank (TEST)", account_number=ACCT,
                                      holder_name=f"ROBANME TEST [{RUN}]", actor="seed", is_test=True, bin_code=BIN)
        await conn.execute("INSERT INTO delivery_zones(province_code,ward_code,zone) VALUES('66','24169','bmt_inner') "
                           "ON CONFLICT DO NOTHING")
        psid = f"tg:m7smoke-{RUN}"
        cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES($1,'SMOKE','0900000000') RETURNING id",
                                  psid)
        pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
                                  "VALUES($1,'CF',200000,999,300,'hũ') RETURNING id", f"M7SMOKE-{RUN}")
        oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                                  "VALUES($1,'confirmed',200000,'telegram_customer') RETURNING id", cid)
        await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,2,100000)",
                           oid, pid)
        rid = await conn.fetchval(
            "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
            "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,'66','24169','current',1.0) "
            "RETURNING id")
        await conn.execute("INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,"
                           "dataset_version,verification_method,bound_by) "
                           "VALUES($1,$2,'66','24169','VN-TEST','test','seed')", oid, rid)
        # drive: routing -> awaiting_method -> chuyen khoan -> awaiting_transfer (instruction + QR)
        await C.ensure_started(conn, oid, channel="telegram_customer", customer_ref=psid, command_key=f"s:{oid}")
        async with conn.transaction():
            await C.advance_routing(conn, oid, ghn_result=None)
        async with conn.transaction():
            await C.handle_customer_text(conn, psid, "chuyển khoản", command_key=f"m:{oid}")
        # SePay mismatch (thieu tien) -> discrepancy + escalate staff_attention(payment_mismatch) + provider event
        raw = json.dumps({"id": f"{RUN}-mm", "gateway": "VietinBank", "accountNumber": ACCT,
                          "content": f"3SCF {oid}", "transferType": "in", "transferAmount": 150000,
                          "referenceCode": "R-mm"}).encode()
        ev = SP.parse_envelope(raw)
        async with conn.transaction():
            rid2, _c, _cf = await PI.ingest(conn, ev, mode="test")
        async with conn.transaction():
            await PI.process(conn, rid2)
        print(json.dumps({"token": token, "order_id": oid, "username": f"m7smoke_{RUN}"}))
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
