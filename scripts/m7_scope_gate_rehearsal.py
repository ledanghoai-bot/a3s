#!/usr/bin/env python3
"""M7 tester-scope gate DB rehearsal (CA Directive 286 §4 — AC-2/3/5/6/7). Chay m5lab. Fake-driven, KHONG PII/secret.

Kiem enforcement o worker cron (run_routing/run_due) + orchestrator path (enabled_for_psid) voi customer_id that:
  AC-2 tester allowlisted -> conversation ADVANCE (khoi routing).
  AC-3 non-tester -> KHONG advance, KHONG prompt/attention (skipped_scope).
  AC-5 Gate E full-scope ON KHONG bypass M7 tester gate (van skip non-tester).
  AC-6 run_routing 2 lan / retry -> khong duplicate advance/prompt (idempotent).
  AC-7 remove tester mid-flow (allowlist rong) -> run_routing skip, state giu (van routing).
  + run_due non-tester -> KHONG reminder. + enabled_for_psid map psid->customer_id.
"""
import asyncio
import os
import sys
import time

import asyncpg

from app.config import settings
from app.services.fulfillment import conversation as FC
from app.services.fulfillment import m7_scope as S

RUN = str(int(time.time()))
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")
FAILS = []
_SEQ = [0]


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


async def _self_ward(conn):
    from app.services.fulfillment import routing as R
    av = await R.active_version(conn)
    return await conn.fetchval("SELECT ward_code FROM delivery_self_wards WHERE routing_version=$1 LIMIT 1", av)


async def _order_convo(conn, ward, *, step="routing"):
    """Seed customer + order + snapshot + fulfillment_conversation o step cho truoc. Tra (order_id, customer_id, psid)."""
    _SEQ[0] += 1
    tag = f"{RUN}-{_SEQ[0]}"
    psid = f"tg:scope-{tag}"
    cid = await conn.fetchval("INSERT INTO customers (psid, channel, external_chat_id, name,phone) VALUES ($1, 'telegram_customer', $1, 'SC','0900000000') RETURNING id", psid)
    pid = await conn.fetchval("INSERT INTO products(sku,name,price_vnd,stock,shipping_weight_g,sales_unit) "
                              "VALUES($1,'CF',100000,999,300,'hũ') RETURNING id", f"SC-{tag}")
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                              "VALUES($1,'confirmed',200000,'telegram_customer') RETURNING id", cid)
    await conn.execute("INSERT INTO order_items(order_id,product_id,quantity,unit_price_vnd) VALUES($1,$2,2,100000)",
                       oid, pid)
    rid = await conn.fetchval(
        "INSERT INTO address_resolution(subject_type,status,candidates,rules_applied,province_code,ward_code,"
        "method,confidence) VALUES('order','auto_verified','[]'::jsonb,'[]'::jsonb,'66',$1,'current',1.0) RETURNING id",
        ward)
    await conn.execute("INSERT INTO order_address_snapshot(order_id,resolution_id,province_code,ward_code,"
                       "dataset_version,verification_method,bound_by) VALUES($1,$2,'66',$3,'VN-TEST','test','scope')",
                       oid, rid, ward)
    await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,policy_version) "
                       "VALUES($1,'telegram_customer',$2,$3,1)", oid, psid, step)
    return oid, cid, psid


async def _step(conn, oid):
    return await conn.fetchval("SELECT step FROM fulfillment_conversations WHERE order_id=$1", oid)


async def main():  # noqa: C901
    settings.m7_conversational_fulfillment = True   # master ON
    settings.m7_ghn_quote = False
    conn = await asyncpg.connect(DSN)
    try:
        ward = await _self_ward(conn)
        if not ward:
            ck("PRECOND self ward", False, ward)
            print("RESULT:", f"FAIL {FAILS}")
            return 1

        # Seed 1 tester + 1 non-tester, ca hai o step=routing
        oidT, cidT, psidT = await _order_convo(conn, ward)
        oidN, cidN, psidN = await _order_convo(conn, ward)
        settings.m7_conversational_scope = "tester"
        settings.m7_tester_customer_ids = str(cidT)   # chi tester

        # enabled_for check
        ck("AC eligibility: tester enabled, non-tester disabled",
           S.m7_enabled_for(cidT) is True and S.m7_enabled_for(cidN) is False, f"{cidT}/{cidN}")
        et = await S.enabled_for_psid(conn, psidT)
        en = await S.enabled_for_psid(conn, psidN)
        ck("enabled_for_psid map psid->customer_id (tester True, non-tester False)", et is True and en is False)

        # AC-5: Gate E full-scope ON KHONG bypass M7 gate
        settings.gate_e_fullscope_telegram_customer = True
        ck("AC-5 Gate E full-scope ON khong bypass M7 tester gate (non-tester van disabled)",
           S.m7_enabled_for(cidN) is False)

        # run_routing: tester advance, non-tester skip
        st = await FC.run_routing(limit=50)
        stepT, stepN = await _step(conn, oidT), await _step(conn, oidN)
        promptsN = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE (payload->>'order_id')::bigint=$1", oidN)
        ck("AC-2 tester advance (khoi routing) + AC-3 non-tester skip (van routing, 0 outbox, skipped_scope>=1)",
           stepT != "routing" and stepN == "routing" and int(promptsN) == 0 and st.get("skipped_scope", 0) >= 1,
           f"T={stepT} N={stepN} outN={promptsN} skip={st.get('skipped_scope')}")

        # AC-6 idempotent: run_routing lan 2 -> tester khong advance them (da roi routing), khong dup
        stepT_before = stepT
        st2 = await FC.run_routing(limit=50)
        ck("AC-6 run_routing lan 2 -> khong duplicate (tester da roi routing, non-tester van skip)",
           (await _step(conn, oidT)) == stepT_before and st2.get("advanced", 0) == 0,
           f"advanced2={st2.get('advanced')}")

        # AC-7 remove tester mid-flow: reset 1 tester conversation ve routing, xoa khoi allowlist -> skip
        oidR, cidR, _ = await _order_convo(conn, ward)
        settings.m7_tester_customer_ids = str(cidR)   # cidR eligible truoc
        ck("AC-7 setup: cidR eligible", S.m7_enabled_for(cidR) is True)
        settings.m7_tester_customer_ids = ""          # remove mid-flow -> allowlist rong
        await FC.run_routing(limit=50)
        ck("AC-7 remove tester mid-flow (allowlist rong) -> skip, state giu (van routing)",
           (await _step(conn, oidR)) == "routing" and S.m7_enabled_for(cidR) is False, await _step(conn, oidR))

        # run_due: non-tester awaiting_transfer -> khong reminder
        settings.m7_tester_customer_ids = str(cidT)
        oidD, cidD, _ = await _order_convo(conn, ward, step="awaiting_transfer")
        await conn.execute("UPDATE fulfillment_conversations SET transfer_started_at=now()-interval '20 min', "
                           "instruction_id=NULL WHERE order_id=$1", oidD)
        # cidD khong trong allowlist -> run_due skip
        async with conn.transaction():
            due = await FC.run_due(conn)
        ck("AC run_due non-tester -> skipped_scope>=1 (khong reminder/escalation)",
           due.get("skipped_scope", 0) >= 1, due)

        # AC-8 (CA 289-01): malformed allowlist -> fail-closed toan bo, KE CA token "dung" cung khong eligible;
        # cron KHONG advance/prompt/attention. cidM la positive canonical hop le NHUNG bi "bad" lam hong config.
        oidM, cidM, psidM = await _order_convo(conn, ward)                 # step=routing
        oidMd, cidMd, _ = await _order_convo(conn, ward, step="awaiting_transfer")
        await conn.execute("UPDATE fulfillment_conversations SET transfer_started_at=now()-interval '20 min', "
                           "instruction_id=NULL WHERE order_id=$1", oidMd)
        settings.m7_tester_customer_ids = f"{cidM},bad,{cidMd}"            # malformed (co token rac)
        ck("AC-8 malformed config -> allowlist_valid False, cidM (canonical) van disabled (fail-closed)",
           S.allowlist_valid() is False and S.m7_enabled_for(cidM) is False and S.tester_ids() == set(), cidM)
        stM = await FC.run_routing(limit=50)
        outM = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE (payload->>'order_id')::bigint=$1", oidM)
        attnM = await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1", oidM)
        ck("AC-8 malformed -> run_routing KHONG advance/outbox/attention (skipped_scope)",
           (await _step(conn, oidM)) == "routing" and int(outM) == 0 and int(attnM) == 0
           and stM.get("skipped_scope", 0) >= 1 and stM.get("advanced", 0) == 0,
           f"stepM={await _step(conn, oidM)} out={outM} attn={attnM} skip={stM.get('skipped_scope')}")
        async with conn.transaction():
            dueM = await FC.run_due(conn)
        remM = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE (payload->>'order_id')::bigint=$1 "
                                   "AND event_type='fulfillment.reminder.notify'", oidMd)
        ck("AC-8 malformed -> run_due KHONG reminder (skipped_scope)",
           dueM.get("skipped_scope", 0) >= 1 and int(remM) == 0, f"skip={dueM.get('skipped_scope')} rem={remM}")

        print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
        return 1 if FAILS else 0
    finally:
        from app.db_pool import close_pool
        await close_pool()
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
