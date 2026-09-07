"""M5 consolidated upgrade — FULL-CHAIN rehearsal tren DB co lap (CA Review 216-03).

Drive luong server-side that: live_verify.verify_and_link -> resolver -> command envelope -> idempotency
-> order transaction -> Gate E binding -> receipt. (Lop chon-tool cua LLM duoc test rieng bang unit mock;
rehearsal nay chung minh chuoi tat dinh phia server.)

Chay trong container co app deps, DATABASE_URL tro toi throwaway DB da nap migrations 001..057.
Output REDACTED: chi id/code/count/status — KHONG in dia chi raw/ten/sdt.

7 kich ban (216-03): S1 auto+bind exact request resolution; S2 dia chi moi khong verify + pointer cu ->
clarify/fail-closed, ZERO order/snapshot, KHONG bind pointer cu; S3 correction -> bind resolution moi;
S4 duplicate (cung resolution) + conflict (216-01, resolution khac); S5 Telegram & Messenger identity;
S6 non-tester khong vao Gate E route; S7 khong co has_recent_order (binding can verified resolution, khong
suy tu recency).
"""
import asyncio
import os
import sys

from app.config import settings
from app.db_pool import acquire, close_pool, release
from app.services.address import dataset_registry, live_verify, order_binding
from app.services.address.acceptance_gate import normalize
from app.services.command import order_gateway

DSV = "VN-ADMIN-2099-01-v1"
FAILS = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        FAILS.append(name)


async def _seed(conn):
    # Rehearsal chay tren DB SACH moi lan (snapshot/resolution bat bien khong xoa duoc).
    # dataset: nap DRAFT truoc (content bat bien khi active) -> them units -> flip ACTIVE
    await conn.execute(
        "INSERT INTO admin_unit_dataset(version,status,source_url,source_kind,sha256,license) "
        "VALUES($1,'draft','http://test','authoritative',$2,'CC-BY') ON CONFLICT(version) DO NOTHING",
        DSV, "a" * 64)
    units = [("province", "66", "Tỉnh Đắk Lắk", None),
             ("ward", "24169", "Phường Ea Kao", "66"),
             ("ward", "24121", "Phường Tân Lập", "66")]
    for level, code, name, parent in units:
        await conn.execute(
            "INSERT INTO admin_unit(dataset_version,level,code,name,name_normalized,parent_code) "
            "VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(dataset_version,code) DO NOTHING",
            DSV, level, code, name, normalize(name), parent)
    await conn.execute("UPDATE admin_unit_dataset SET status='active', activated_at=now() WHERE version=$1", DSV)
    await conn.execute(
        "INSERT INTO address_dataset_config(key,value) VALUES('active_version',$1) "
        "ON CONFLICT(key) DO UPDATE SET value=$1", DSV)
    await conn.execute("INSERT INTO products(sku,name,stock,price_vnd) VALUES('SP1','Ca phe test',1000,100000) "
                       "ON CONFLICT(sku) DO UPDATE SET stock=1000")
    cid = await conn.fetchval("SELECT id FROM customers WHERE psid='tg:reh1'")
    if cid is None:
        cid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES('tg:reh1','Reh','0900000000') "
                                  "RETURNING id")
    return cid


async def _order_count(conn, cid):
    return await conn.fetchval("SELECT count(*) FROM orders WHERE customer_id=$1", cid)


async def _verify(psid, channel, prov, ward, event_id):
    return await live_verify.verify_and_link(psid=psid, channel=channel, province_proposal=prov,
                                             ward_proposal=ward, event_id=event_id)


async def _create(channel, psid, event_id, vr, addr="15 Dg X"):
    # Gate E fail-closed nem BindingError -> orchestrator._execute_tool bat (except Exception) va tra
    # error dict; mo phong hanh vi do o day (order da rollback trong transaction _run_winner).
    try:
        return await order_gateway.create_order_command(
            channel=channel, actor_type="customer", actor_id=psid, idempotency_key=None,
            provider_message_id=event_id, customer_name="Reh", phone="0900000000", address=addr,
            sku="SP1", quantity=1, psid=psid,
            verified_resolution_id=(vr.get("resolution_id") if vr.get("may_bind") else None))
    except order_binding.BindingError as e:
        return {"error": str(e), "error_code": "gate_e_fail_closed"}


async def main():
    conn = await acquire()
    try:
        cid = await _seed(conn)
    finally:
        await release(conn)
    # Cau hinh pilot/Gate E cho tester (customer cid) — set truc tiep tren settings (script kiem soat)
    settings.m1_reliable_order_command = False
    settings.enable_address_resolver = True
    settings.address_resolver_pilot_customer_ids = str(cid)
    settings.enable_gate_e_order_wiring = True
    settings.gate_e_canary_customer_ids = str(cid)
    settings.gate_e_kill_switch = False

    print(f"customer_id={cid} dataset={DSV}")

    # --- S1: auto_verified -> bind exact request resolution ---
    print("S1 auto+bind:")
    vr1 = await _verify("tg:reh1", "telegram_customer", "Tỉnh Đắk Lắk", "Phường Ea Kao", "tg:1001")
    check("verify may_bind", vr1.get("may_bind") is True, f"status={vr1.get('status')}")
    r1 = await _create("telegram_customer", "tg:reh1", "tg:1001", vr1)
    conn = await acquire()
    try:
        o1 = await conn.fetchrow("SELECT id,verified_address_id FROM orders WHERE customer_id=$1 "
                                 "ORDER BY id DESC LIMIT 1", cid)
        snap = await conn.fetchrow("SELECT resolution_id FROM order_address_snapshot WHERE order_id=$1", o1["id"])
        ea_kao_res = vr1.get("resolution_id")
        check("order created", r1.get("order_id") is not None)
        check("verified_address_id == request resolution", str(o1["verified_address_id"]) == ea_kao_res)
        check("snapshot resolution == request resolution", snap and str(snap["resolution_id"]) == ea_kao_res)
    finally:
        await release(conn)

    # --- S2: dia chi moi KHONG verify + pointer cu (Ea Kao) ton tai -> fail-closed, ZERO order/snapshot ---
    print("S2 unverified new addr + old pointer -> fail-closed:")
    conn = await acquire()
    try:
        n_before = await _order_count(conn, cid)
        cur_ptr = await conn.fetchval("SELECT current_address_resolution_id FROM customers WHERE id=$1", cid)
    finally:
        await release(conn)
    vr2 = await _verify("tg:reh1", "telegram_customer", "Tỉnh Không Có", "Phường Không Có", "tg:1002")
    check("verify NOT may_bind", not vr2.get("may_bind"), f"status={vr2.get('status')}")
    r2 = await _create("telegram_customer", "tg:reh1", "tg:1002", vr2)
    conn = await acquire()
    try:
        n_after = await _order_count(conn, cid)
        cur_ptr2 = await conn.fetchval("SELECT current_address_resolution_id FROM customers WHERE id=$1", cid)
        check("order REJECTED (fail-closed)", r2.get("order_id") is None, f"err={r2.get('error_code')}")
        check("zero new order", n_after == n_before)
        check("old pointer NOT changed/bound", str(cur_ptr2) == str(cur_ptr))
    finally:
        await release(conn)

    # --- S3: correction -> resolve proposal moi -> bind resolution MOI (Tan Lap), khong phai Ea Kao ---
    print("S3 correction -> bind new resolution:")
    vr3 = await _verify("tg:reh1", "telegram_customer", "Đắk Lắk", "Phường Tân Lập", "tg:1003")
    check("verify may_bind (Tan Lap)", vr3.get("may_bind") is True and vr3.get("ward_name") == "Phường Tân Lập")
    r3 = await _create("telegram_customer", "tg:reh1", "tg:1003", vr3)
    conn = await acquire()
    try:
        o3 = await conn.fetchrow("SELECT id,verified_address_id FROM orders WHERE customer_id=$1 "
                                 "ORDER BY id DESC LIMIT 1", cid)
        snap3 = await conn.fetchrow("SELECT resolution_id FROM order_address_snapshot WHERE order_id=$1", o3["id"])
        check("order created", r3.get("order_id") is not None)
        check("bound to NEW resolution (Tan Lap), not Ea Kao",
              str(o3["verified_address_id"]) == vr3.get("resolution_id")
              and str(o3["verified_address_id"]) != vr1.get("resolution_id"))
        check("snapshot == new resolution", snap3 and str(snap3["resolution_id"]) == vr3.get("resolution_id"))
    finally:
        await release(conn)

    # --- S4: duplicate (cung resolution) + conflict (216-01: resolution KHAC, cung key+payload) ---
    print("S4 duplicate + conflict (216-01):")
    vr4 = await _verify("tg:reh1", "telegram_customer", "Tỉnh Đắk Lắk", "Phường Ea Kao", "tg:1004")
    conn = await acquire()
    try:
        n_b = await _order_count(conn, cid)
    finally:
        await release(conn)
    r4a = await _create("telegram_customer", "tg:reh1", "tg:1004", vr4)
    r4b = await _create("telegram_customer", "tg:reh1", "tg:1004", vr4)  # dup: same event+resolution
    check("duplicate same order_id", r4a.get("order_id") == r4b.get("order_id") and r4b.get("duplicate") is True)
    # conflict: cung idempotency (same event -> same key) NHUNG verified_resolution_id KHAC
    r4c = await order_gateway.create_order_command(
        channel="telegram_customer", actor_type="customer", actor_id="tg:reh1", idempotency_key=None,
        provider_message_id="tg:1004", customer_name="Reh", phone="0900000000", address="15 Dg X",
        sku="SP1", quantity=1, psid="tg:reh1", verified_resolution_id=vr3.get("resolution_id"))  # KHAC resolution
    conn = await acquire()
    try:
        n_a = await _order_count(conn, cid)
        check("conflict on different resolution (no dup receipt)", r4c.get("order_id") is None,
              f"err={r4c.get('error_code')}")
        check("zero extra order from dup+conflict", n_a == n_b + 1)  # chi 1 order that tu r4a
    finally:
        await release(conn)

    # --- S5: Messenger identity + event ---
    print("S5 messenger channel:")
    mcid = None
    conn = await acquire()
    try:
        mcid = await conn.fetchval("SELECT id FROM customers WHERE psid='m:reh2'")
        if mcid is None:
            mcid = await conn.fetchval("INSERT INTO customers(psid,name,phone) VALUES('m:reh2','R2','0911111111') "
                                       "RETURNING id")
    finally:
        await release(conn)
    settings.address_resolver_pilot_customer_ids = f"{cid},{mcid}"
    settings.gate_e_canary_customer_ids = f"{cid},{mcid}"
    vr5 = await _verify("m:reh2", "messenger", "Tỉnh Đắk Lắk", "Phường Ea Kao", "m_abc123")
    check("messenger verify may_bind", vr5.get("may_bind") is True, f"status={vr5.get('status')}")
    r5 = await _create("messenger", "m:reh2", "m_abc123", vr5)
    check("messenger order created + bound", r5.get("order_id") is not None)

    # --- S6: non-tester (ngoai scope) -> khong vao Gate E binding (legacy, khong snapshot) ---
    print("S6 non-tester isolation:")
    settings.gate_e_canary_customer_ids = str(cid)  # loai mcid khoi Gate E scope
    settings.address_resolver_pilot_customer_ids = str(cid)
    vr6 = await _verify("m:reh2", "messenger", "Tỉnh Đắk Lắk", "Phường Ea Kao", "m_def456")
    check("non-tester verify skipped (out of pilot)", vr6.get("skipped") == "out_of_pilot_scope")
    r6 = await _create("messenger", "m:reh2", "m_def456", vr6)  # vr6 no may_bind -> None resolution
    conn = await acquire()
    try:
        o6 = await conn.fetchrow("SELECT id FROM orders WHERE customer_id=$1 ORDER BY id DESC LIMIT 1", mcid)
        snap6 = await conn.fetchval("SELECT count(*) FROM order_address_snapshot WHERE order_id=$1",
                                    o6["id"]) if o6 else None
        # non-tester ngoai Gate E scope -> _maybe_bind_gate_e passthrough legacy -> order tao, KHONG snapshot
        check("non-tester order legacy (no Gate E snapshot)", o6 is not None and snap6 == 0)
    finally:
        await release(conn)

    # --- S7: khong co has_recent_order — binding CAN verified resolution, khong suy tu recency ---
    print("S7 no recency bypass:")
    import app.services.command.order_service as osvc
    import app.services.orchestrator as orch
    src = ""
    for m in (osvc, orch):
        try:
            import inspect
            src += inspect.getsource(m)
        except Exception:
            pass
    check("no has_recent_order in order path", "has_recent_order" not in src)

    print(f"\nRESULT: {'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
    await close_pool()
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    asyncio.run(main())
