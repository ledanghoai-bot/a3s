#!/usr/bin/env python3
"""Command/outbox recovery + RBAC + audit fail-closed evidence (I-B M1 Slice 8). Spec §9.3, §11.

  R  RBAC mapping (020): admin co ca 5; support co retry/cancel/view KHONG replay; viewer view-only.
  G  require_permission gate: support -> outbox.replay 403, outbox.retry pass; admin -> replay pass.
  A  recovery: retry(dead->retry_scheduled+reset+audit) / cancel(pending->cancelled+audit) /
     replay(new event+audit) / guards (retry non-dead 409, cancel delivered 409) / reason required 422.
  F  audit fail-closed: break audit_log -> retry raise + event GIU NGUYEN dead_lettered (rollback).

  docker exec -e DATABASE_URL=...m1_itest -e PYTHONPATH=/srv -w /srv api python scripts/command_recovery_rbac_test.py
"""
import asyncio
import json
import sys

import asyncpg
from fastapi import HTTPException

from app.api.auth import require_permission
from app.config import settings
from app.services import auth_service
from app.services.command import errors, order_service, recovery
from app.services.command.envelope import Actor, build_order_create_envelope

C = {"customer_name": "Rec Test", "phone": "0933444555", "address": "3 Test", "sku": "3S-100G"}


def _db():
    return settings.database_url.replace("+asyncpg", "")


async def perms_of(conn, role):
    rows = await conn.fetch("SELECT permission_key FROM role_permissions WHERE role_key=$1", role)
    return {r["permission_key"] for r in rows}


async def ins_event(conn, cid, dedupe, status):
    payload = json.dumps({"order_id": 1, "correlation_id": "c", "sku": "3S-100G"})
    st_extra = ", dead_lettered_at=now()" if status == "dead_lettered" else (
        ", delivered_at=now()" if status == "delivered" else "")
    eid = await conn.fetchval(
        "INSERT INTO outbox_events (id, command_id, event_type, event_version, destination, dedupe_key, "
        "payload, status, available_at, max_attempts) VALUES (gen_random_uuid(),$1,'x',1,'telegram_admin',"
        "$2,$3::jsonb,$4,now(),8) RETURNING id", cid, dedupe, payload, status)
    if st_extra:
        await conn.execute(f"UPDATE outbox_events SET status=$2{st_extra} WHERE id=$1", eid, status)
    return eid


async def status_of(conn, eid):
    return await conn.fetchval("SELECT status FROM outbox_events WHERE id=$1", eid)


async def audit_n(conn, action):
    return await conn.fetchval("SELECT count(*) FROM audit_log WHERE action=$1", action)


async def gate_ok(perm, staff) -> bool:
    try:
        await require_permission(perm)(staff=staff)
        return True
    except HTTPException:
        return False


async def main() -> int:  # noqa: C901
    conn = await asyncpg.connect(_db())
    fails: list[str] = []
    try:
        await conn.execute("TRUNCATE order_items, orders, command_executions, outbox_events, "
                           "delivery_attempts, price_overrides RESTART IDENTITY CASCADE")
        await conn.execute("UPDATE products SET stock=1000 WHERE sku='3S-100G'")

        # R: RBAC mapping (migration 020)
        admin_p, support_p, viewer_p = (await perms_of(conn, "admin"), await perms_of(conn, "support"),
                                        await perms_of(conn, "viewer"))
        need = {"commands.view", "outbox.view", "outbox.retry", "outbox.replay", "outbox.cancel"}
        if not need.issubset(admin_p):
            fails.append(f"R: admin thieu perm: {need - admin_p}")
        if "outbox.replay" in support_p or not {"outbox.retry", "outbox.cancel"}.issubset(support_p):
            fails.append(f"R: support sai (co replay? / thieu retry-cancel): {support_p}")
        if not {"commands.view", "outbox.view"}.issubset(viewer_p) or (
                viewer_p & {"outbox.retry", "outbox.replay", "outbox.cancel"}):
            fails.append(f"R: viewer sai (thieu view / co mutation perm): {viewer_p}")

        # G: gate
        support_staff = {"id": 9001, "rbac_provisioned": True, "permissions": support_p}
        admin_staff_d = {"id": 9002, "rbac_provisioned": True, "permissions": admin_p}
        if await gate_ok("outbox.replay", support_staff):
            fails.append("G: support KHONG duoc replay nhung gate cho qua")
        if not await gate_ok("outbox.retry", support_staff):
            fails.append("G: support phai duoc retry nhung gate chan")
        if not await gate_ok("outbox.replay", admin_staff_d):
            fails.append("G: admin phai duoc replay")

        # staff that de audit FK
        st = await auth_service.create_staff_user("rec_admin", "pw12345678", "RA", role_key="admin")
        actor = {"id": st["id"], "username": "rec_admin"}
        env = build_order_create_envelope(raw_payload=dict(C, quantity=1, unit_price_vnd=150000),
                                          actor=Actor("staff", str(st["id"])), channel="dashboard",
                                          idempotency_key="rec-seed-key-00001")
        await order_service.execute_order_create(env)
        cid = await conn.fetchval("SELECT id FROM command_executions LIMIT 1")

        # A: retry dead-letter -> retry_scheduled + audit. CR-01: attempt_count KHÔNG reset (đơn điệu),
        # cấp budget bằng max_attempts += fresh (tránh trùng attempt_no).
        e_dl = await ins_event(conn, cid, "dl1", "dead_lettered")
        await conn.execute("UPDATE outbox_events SET attempt_count=8, max_attempts=8 WHERE id=$1", e_dl)
        await recovery.retry_outbox(str(e_dl), actor, "thu lai sau su co Telegram")
        r = await conn.fetchrow(
            "SELECT status, attempt_count, max_attempts FROM outbox_events WHERE id=$1", e_dl)
        if not (r["status"] == "retry_scheduled" and r["attempt_count"] == 8 and r["max_attempts"] == 16):
            fails.append(f"A/CR-01: retry sai (attempt_count giữ 8, max_attempts->16): {dict(r)}")
        if await audit_n(conn, "outbox.retry") != 1:
            fails.append("A: khong audit outbox.retry")

        # CR-02: cancel khi 'delivering' -> 409 (không cho đè worker đang gửi)
        e_delv = await ins_event(conn, cid, "delv", "pending")
        await conn.execute("UPDATE outbox_events SET status='delivering' WHERE id=$1", e_delv)
        try:
            await recovery.cancel_outbox(str(e_delv), actor, "x")
            fails.append("CR-02: cancel delivering KHÔNG raise 409")
        except errors.CommandError as e:
            if e.http_status != 409:
                fails.append(f"CR-02: cancel delivering sai code {e.http_status}")

        # guard: retry non-dead -> 409
        e_pg = await ins_event(conn, cid, "pg1", "pending")
        try:
            await recovery.retry_outbox(str(e_pg), actor, "x")
            fails.append("A: retry pending KHONG raise 409")
        except errors.CommandError as e:
            if e.http_status != 409:
                fails.append(f"A: retry pending sai code {e.http_status}")

        # cancel pending -> cancelled + audit
        e_pg2 = await ins_event(conn, cid, "pg2", "pending")
        await recovery.cancel_outbox(str(e_pg2), actor, "khach huy")
        if await status_of(conn, e_pg2) != "cancelled" or await audit_n(conn, "outbox.cancel") != 1:
            fails.append("A: cancel pending sai / khong audit")

        # cancel delivered -> 409
        e_dv = await ins_event(conn, cid, "dv1", "delivered")
        try:
            await recovery.cancel_outbox(str(e_dv), actor, "x")
            fails.append("A: cancel delivered KHONG raise 409")
        except errors.CommandError as e:
            if e.http_status != 409:
                fails.append(f"A: cancel delivered sai code {e.http_status}")

        # replay -> new event + audit (CR-06: cần confirm_business_effect + source dead_lettered/cancelled)
        e_dl2 = await ins_event(conn, cid, "dl2", "dead_lettered")
        res = await recovery.replay_outbox(str(e_dl2), actor, "gui lai cho admin",
                                           confirm_business_effect=True)
        new_id = res["new_outbox_id"]
        newrow = await conn.fetchrow("SELECT status, dedupe_key FROM outbox_events WHERE id=$1", new_id)
        if not (newrow and newrow["status"] == "pending" and ":replay:" in newrow["dedupe_key"]):
            fails.append(f"A: replay khong tao event moi dung: {dict(newrow) if newrow else None}")
        if await audit_n(conn, "outbox.replay") != 1:
            fails.append("A: khong audit outbox.replay")

        # reason required -> 422
        e_dl3 = await ins_event(conn, cid, "dl3", "dead_lettered")
        try:
            await recovery.retry_outbox(str(e_dl3), actor, None)
            fails.append("A: reason=None KHONG raise 422")
        except errors.CommandError as e:
            if e.code != "reason_required" or e.http_status != 422:
                fails.append(f"A: reason sai {e.code}/{e.http_status}")

        # CR-06: replay không confirm -> 422; replay từ trạng thái không hợp lệ (pending) -> 409
        e_dl6 = await ins_event(conn, cid, "dl6", "dead_lettered")
        try:
            await recovery.replay_outbox(str(e_dl6), actor, "x", confirm_business_effect=False)
            fails.append("CR-06: replay không confirm KHÔNG raise")
        except errors.CommandError as e:
            if e.code != "reconcile_confirmation_required" or e.http_status != 422:
                fails.append(f"CR-06: replay no-confirm sai {e.code}/{e.http_status}")
        e_pend = await ins_event(conn, cid, "pend6", "pending")
        try:
            await recovery.replay_outbox(str(e_pend), actor, "x", confirm_business_effect=True)
            fails.append("CR-06: replay từ pending KHÔNG raise 409")
        except errors.CommandError as e:
            if e.http_status != 409:
                fails.append(f"CR-06: replay pending sai {e.http_status}")

        # F: audit fail-closed -> retry raise + event GIU dead_lettered
        e_dl4 = await ins_event(conn, cid, "dl4", "dead_lettered")
        await conn.execute("ALTER TABLE audit_log ADD CONSTRAINT _ff CHECK (false) NOT VALID")
        raised = False
        try:
            await recovery.retry_outbox(str(e_dl4), actor, "se fail vi audit")
        except Exception:
            raised = True
        await conn.execute("ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS _ff")
        if not raised:
            fails.append("F: audit fail KHONG raise")
        if await status_of(conn, e_dl4) != "dead_lettered":
            fails.append("F: event DA doi du audit fail (rollback hong)")
    finally:
        await conn.close()

    if fails:
        print("RECOVERY-RBAC FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("RECOVERY-RBAC PASS: R mapping(admin all/support no-replay/viewer view-only); "
          "G gate(support!replay,retry ok; admin replay); A retry/cancel/replay+audit+guards+reason; "
          "F audit fail-closed rollback.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
