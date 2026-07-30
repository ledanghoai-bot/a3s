#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: pool integration THAT cho pinned-actor lifecycle (F-M4-0P-T8-01).

Chay:
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      alpha3s-m4-test python scripts/m4_stage0p_pool_test.py

CA Technical Re-review #8 (F-M4-0P-T8-01): Correction #8 (T7-01 consume-on-use) chi dong truong
hop actor A HOAN TAT 1 hanh dong nghiep vu THANH CONG. Neu actor A pin THANH CONG roi request bi
huy/loi TRUOC khi lam hanh dong nghiep vu nao, row pin VAN CON — 1 pool THAT tra lai CUNG
connection vat ly (CUNG pg_backend_pid()) cho actor B se de B ke thua pin cua A. Moi evidence
script khac trong repo dung `asyncpg.connect()` MOI cho MOI thao tac (moi "connection" la 1
backend_pid MOI) nen kich ban nay CHUA BAO GIO duoc tai hien THAT SU truoc script nay.

Script nay dung `app/services/pii/stage0p_pool.py` (`create_stage0p_pool` + `pinned_actor_session`)
voi pool `min_size=1, max_size=1` — ep BUOC tai su dung CUNG 1 connection vat ly qua nhieu lan
checkout/checkin lien tiep (khong overlap), dung de chung minh:

  [1] Happy path: pin + 1 hanh dong nghiep vu THANH CONG qua wrapper -> thanh cong binh thuong.
  [2] Abandoned pin (KHONG exception, KHONG hanh dong nghiep vu nao) -> checkin van UNPIN; actor B
      checkout SAU DO (CUNG connection vat ly) khong ke thua pin cua A.
  [3] Exception TRUOC khi lam hanh dong nghiep vu nao -> cleanup van UNPIN (finally chay du
      exception), actor B checkout sau do sach.
  [4] Task bi `cancel()` giua luc dang "trong" wrapper (dang cho 1 await gia lap hanh dong dang
      chay) -> cleanup (boc `asyncio.shield`) VAN chay xong, actor B checkout sau do sach.
  [5] Nhieu chu ky checkin/checkout lien tiep xen ke actor A/B tren CUNG 1 connection vat ly (5
      vong) -> moi vong pin dung actor, khong tich luy trang thai/loi.
  [6] Doi chung (KHONG di qua wrapper — dung `pool.acquire()`/`pin_actor()`/`pool.release()` truc
      tiep, MO PHONG chinh loi CA neu trong Review #8): pin roi release ma KHONG unpin -> actor B
      checkout SAU DO (cung connection) KE THUA duoc pin cu — chung minh khoang cach la THAT va
      wrapper (khong phai TTL/thoi gian ngan cua test) la thu dong no lai.
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

from app.services.pii.stage0p_control import (  # noqa: E402
    ControlChangeRejectedError,
    pin_actor,
    set_capture_enabled,
)
from app.services.pii.stage0p_pool import (  # noqa: E402
    create_stage0p_pool,
    pinned_actor_session,
)

DB_URL = (os.environ.get("DATABASE_URL")
          or "postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s").replace("+asyncpg", "")

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


PIN_SECRET_A = "pool-test-pin-secret-a"
PIN_SECRET_B = "pool-test-pin-secret-b"
BUSINESS_ROLE = "alpha3s_m4_control_plane"


async def _provision_pin_secret(admin, *, staff_id, pin_secret) -> None:
    await admin.execute(
        "INSERT INTO m4_stage0p_actor_credentials (staff_id, pin_secret_hash, provisioned_by) "
        "VALUES ($1, crypt($2, gen_salt('bf')), $1) "
        "ON CONFLICT (staff_id) DO UPDATE SET pin_secret_hash=crypt($2, gen_salt('bf')), "
        "failed_attempts=0, locked_until=NULL", staff_id, pin_secret)


async def _actor_session_owner(admin, backend_pid: int):
    """Doc TRUC TIEP qua superuser (khong qua role bi gioi han) — xac nhan trang thai THAT trong
    DB, khong phai chi suy ra tu hanh vi Python."""
    return await admin.fetchval(
        "SELECT staff_id FROM m4_stage0p_actor_session WHERE backend_pid = $1", backend_pid)


async def main() -> int:
    admin = await asyncpg.connect(DB_URL)
    await admin.execute(
        "DELETE FROM m4_stage0p_actor_session WHERE staff_id IN "
        "(SELECT id FROM staff_users WHERE username LIKE 'm4-pool-test%')")
    await admin.execute(
        "DELETE FROM m4_stage0p_actor_credentials WHERE staff_id IN "
        "(SELECT id FROM staff_users WHERE username LIKE 'm4-pool-test%')")
    await admin.execute(
        "DELETE FROM m4_stage0p_staff_permissions WHERE staff_id IN "
        "(SELECT id FROM staff_users WHERE username LIKE 'm4-pool-test%')")
    await admin.execute("DELETE FROM staff_users WHERE username LIKE 'm4-pool-test%'")
    await admin.execute("UPDATE m4_stage0p_control SET capture_enabled=false WHERE id=1")

    staff_a = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-pool-test-a', 'x', 'x', true) RETURNING id")
    staff_b = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-pool-test-b', 'x', 'x', true) RETURNING id")
    for staff, secret in ((staff_a, PIN_SECRET_A), (staff_b, PIN_SECRET_B)):
        await admin.execute(
            "INSERT INTO m4_stage0p_staff_permissions (staff_id, permission, granted_by) "
            "VALUES ($1,'m4.stage0p.operate',$1) ON CONFLICT DO NOTHING", staff["id"])
        await _provision_pin_secret(admin, staff_id=staff["id"], pin_secret=secret)

    pool = await create_stage0p_pool(DB_URL, min_size=1, max_size=1)

    print("== [1] Happy path: pin + 1 hanh dong nghiep vu THANH CONG qua pinned_actor_session ==")
    async with pinned_actor_session(pool, staff_id=staff_a["id"], pin_secret=PIN_SECRET_A,
                                    business_role=BUSINESS_ROLE) as conn:
        pid_1 = await conn.fetchval("SELECT pg_backend_pid()")
        before = await set_capture_enabled(conn, enabled=False, approval_ref=None)
        check(before is False, "hanh dong nghiep vu qua wrapper thanh cong (set_capture OFF)")
    owner_after_1 = await _actor_session_owner(admin, pid_1)
    check(owner_after_1 is None, "sau khi thoat wrapper (thanh cong) -> KHONG con row pin (T7-01 "
          "consume-on-use + T8-01 cleanup-on-release ca hai deu don sach)")

    print("== [2] Abandoned pin: pin THANH CONG nhung KHONG lam hanh dong nghiep vu nao ==")
    async with pinned_actor_session(pool, staff_id=staff_a["id"], pin_secret=PIN_SECRET_A,
                                    business_role=BUSINESS_ROLE) as conn:
        pid_2 = await conn.fetchval("SELECT pg_backend_pid()")
        # CO Y KHONG goi hanh dong nghiep vu nao - mo phong request bi bo do giua chung.
    owner_after_abandon = await _actor_session_owner(admin, pid_2)
    check(owner_after_abandon is None,
          "sau khi thoat wrapper (KHONG hanh dong nao) -> pin van bi XOA (T8-01 cleanup-on-release, "
          "khac voi T7-01 chi xoa khi THANH CONG)")
    async with pinned_actor_session(pool, staff_id=staff_b["id"], pin_secret=PIN_SECRET_B,
                                    business_role=BUSINESS_ROLE) as conn_b:
        pid_2b = await conn_b.fetchval("SELECT pg_backend_pid()")
        check(pid_2b == pid_2, "pool size=1 -> CUNG 1 connection vat ly duoc tai su dung (khong "
              "phai 2 connection khac nhau tinh co cung ket qua)")
        owner_b = await _actor_session_owner(admin, pid_2b)
        check(owner_b == staff_b["id"], "actor B checkout SAU pin bo do cua A -> la CHINH B duoc "
              "pin (KHONG ke thua A) - T8-01")
        ok_b = await set_capture_enabled(conn_b, enabled=False, approval_ref=None)
        check(ok_b is False, "actor B thuc hien hanh dong nghiep vu binh thuong sau do")

    print("== [3] Exception TRUOC khi lam hanh dong nghiep vu nao -> cleanup van chay ==")
    pid_3 = None
    try:
        async with pinned_actor_session(pool, staff_id=staff_a["id"], pin_secret=PIN_SECRET_A,
                                        business_role=BUSINESS_ROLE) as conn:
            pid_3 = await conn.fetchval("SELECT pg_backend_pid()")
            raise RuntimeError("mo phong loi nghiep vu TRUOC khi goi ham nao")
    except RuntimeError:
        pass
    else:
        check(False, "exception ben trong wrapper phai duoc lan truyen ra ngoai (khong bi nuot)")
    owner_after_exc = await _actor_session_owner(admin, pid_3)
    check(owner_after_exc is None,
          "sau exception (TRUOC hanh dong nghiep vu) -> cleanup van UNPIN (finally chay du loi)")
    async with pinned_actor_session(pool, staff_id=staff_b["id"], pin_secret=PIN_SECRET_B,
                                    business_role=BUSINESS_ROLE) as conn_b:
        pid_3b = await conn_b.fetchval("SELECT pg_backend_pid()")
        check(pid_3b == pid_3, "CUNG connection vat ly duoc tai su dung sau exception")
        owner_b3 = await _actor_session_owner(admin, pid_3b)
        check(owner_b3 == staff_b["id"], "actor B checkout sau exception cua A -> la CHINH B (T8-01)")

    print("== [4] Task bi cancel() giua luc dang 'trong' wrapper -> cleanup (shield) van chay ==")
    pid_4 = None
    entered = asyncio.Event()

    async def _long_running_actor_a():
        nonlocal pid_4
        async with pinned_actor_session(pool, staff_id=staff_a["id"], pin_secret=PIN_SECRET_A,
                                        business_role=BUSINESS_ROLE) as conn:
            pid_4 = await conn.fetchval("SELECT pg_backend_pid()")
            entered.set()
            await asyncio.sleep(30)  # mo phong hanh dong nghiep vu dang "chay" khi bi cancel

    task = asyncio.create_task(_long_running_actor_a())
    await entered.wait()
    task.cancel()
    try:
        await task
        check(False, "task bi cancel() phai nem CancelledError khi await lai")
    except asyncio.CancelledError:
        pass
    owner_after_cancel = await _actor_session_owner(admin, pid_4)
    check(owner_after_cancel is None,
          "sau khi task bi cancel() giua chung -> cleanup (asyncio.shield) van UNPIN thanh cong")
    async with pinned_actor_session(pool, staff_id=staff_b["id"], pin_secret=PIN_SECRET_B,
                                    business_role=BUSINESS_ROLE) as conn_b:
        pid_4b = await conn_b.fetchval("SELECT pg_backend_pid()")
        check(pid_4b == pid_4, "CUNG connection vat ly duoc tai su dung sau cancellation")
        owner_b4 = await _actor_session_owner(admin, pid_4b)
        check(owner_b4 == staff_b["id"], "actor B checkout sau task A bi cancel -> la CHINH B (T8-01)")

    print("== [5] 5 vong checkin/checkout lien tiep xen ke A/B tren CUNG 1 connection vat ly ==")
    cycle_ok = True
    for i in range(5):
        staff_cycle = staff_a if i % 2 == 0 else staff_b
        secret_cycle = PIN_SECRET_A if i % 2 == 0 else PIN_SECRET_B
        async with pinned_actor_session(pool, staff_id=staff_cycle["id"], pin_secret=secret_cycle,
                                        business_role=BUSINESS_ROLE) as conn:
            pid_cycle = await conn.fetchval("SELECT pg_backend_pid()")
            owner_cycle = await _actor_session_owner(admin, pid_cycle)
            if owner_cycle != staff_cycle["id"]:
                cycle_ok = False
            ok = await set_capture_enabled(conn, enabled=False, approval_ref=None)
            if ok is not False:
                cycle_ok = False
    check(cycle_ok, "5 vong xen ke A/B lien tiep - moi vong dung actor, khong tich luy trang thai sai")

    print("== [6a] Doi chung 1: bypass wrapper (acquire/pin/release THO, KHONG unpin) tren asyncpg ==")
    raw_conn = await pool.acquire()
    await raw_conn.execute("SET ROLE alpha3s_m4_actor_binder")
    await pin_actor(raw_conn, staff_id=staff_a["id"], pin_secret=PIN_SECRET_A)
    await raw_conn.execute("RESET ROLE")
    pid_6 = await raw_conn.fetchval("SELECT pg_backend_pid()")
    # CO Y release THANG, KHONG goi unpin_actor() - day CHINH LA loi CA neu trong Review #8.
    await pool.release(raw_conn)
    owner_after_bypass = await _actor_session_owner(admin, pid_6)
    check(owner_after_bypass == staff_a["id"],
          "bypass wrapper (khong unpin truoc release) -> ROW pin cua A THAT SU con song sau "
          "release (khong bi Postgres/asyncpg tu xoa)")

    raw_conn2 = await pool.acquire()
    pid_6b = await raw_conn2.fetchval("SELECT pg_backend_pid()")
    check(pid_6b == pid_6, "CUNG connection vat ly duoc tai su dung (pool size=1)")
    await raw_conn2.execute(f"SET ROLE {BUSINESS_ROLE}")
    try:
        await set_capture_enabled(raw_conn2, enabled=False, approval_ref=None)
        check(False, "doi chung 1: 'actor B' (chua tung tu pin) LE RA phai bi asyncpg tu RESET "
              "session GUC (session_nonce) khi pool.release() -> mismatch -> tu choi; neu THANH "
              "CONG nghia la asyncpg KHONG con hanh vi reset-on-release nhu da xac minh thuc "
              "nghiem, can xem lai phat hien duoi day")
    except ControlChangeRejectedError as e:
        check("session_nonce khong khop" in str(e) or "STALE" in str(e),
              "PHAT HIEN: asyncpg.Pool.release() tu RESET session-scoped GUC (session_nonce) cua "
              "CHINH connection vat ly do — du ROW pin cua A con nguyen (tren), GUC bi xoa lam "
              "T6-01 tu phat hien 'session STALE' va tu choi B ke thua — 1 lop phong thu THEM tu "
              "chinh asyncpg, KHONG phai co che chu dinh cua Stage 0P")
    finally:
        await raw_conn2.execute("RESET ROLE")
    await admin.execute("DELETE FROM m4_stage0p_actor_session WHERE backend_pid=$1", pid_6b)
    await pool.release(raw_conn2)

    print("== [6b] Doi chung 2: mo phong 1 pooler KHONG reset session state (vd PgBouncer session-"
          "pooling/1 pool tu viet khong goi Connection.reset()) — GUC session_nonce duoc GIU LAI "
          "THU CONG qua reacquire, chi ROW pin bi bo lai (khong unpin) — day moi la kich ban that "
          "CA lo ngai trong Review #8, T8-01 phai dong duoc BAT KE hanh vi reset cua tang pool ==")
    raw_conn3 = await pool.acquire()
    await raw_conn3.execute("SET ROLE alpha3s_m4_actor_binder")
    await pin_actor(raw_conn3, staff_id=staff_a["id"], pin_secret=PIN_SECRET_A)
    await raw_conn3.execute("RESET ROLE")
    pid_6c = await raw_conn3.fetchval("SELECT pg_backend_pid()")
    nonce_6c = await admin.fetchval(
        "SELECT session_nonce FROM m4_stage0p_actor_session WHERE backend_pid=$1", pid_6c)
    await pool.release(raw_conn3)  # asyncpg tu RESET GUC o day (xac minh tren) - se GHI DE lai duoi.

    raw_conn4 = await pool.acquire()
    pid_6d = await raw_conn4.fetchval("SELECT pg_backend_pid()")
    check(pid_6d == pid_6c, "CUNG connection vat ly duoc tai su dung (pool size=1)")
    # Ghi de GUC ve gia tri CU - mo phong 1 tang pool KHONG tu reset session state (vd PgBouncer
    # session-pooling giu nguyen session giua cac lan "checkout" logic, hoac driver tu viet
    # khong goi reset). Day la dieu KIEN THUC su ma T8-01 phai chiu duoc, khong duoc gia dinh
    # "asyncpg se lo giup".
    await raw_conn4.execute("SELECT set_config('alpha3s.m4_session_nonce', $1, false)", str(nonce_6c))
    await raw_conn4.execute(f"SET ROLE {BUSINESS_ROLE}")
    try:
        await set_capture_enabled(raw_conn4, enabled=False, approval_ref=None)
        check(True, "doi chung 2: KHI ca ROW lan GUC cung song sot (pooler khong tu reset) va "
              "KHONG di qua pinned_actor_session -> 'actor B' (chua tung tu pin) THANH CONG hanh "
              "dong nghiep vu bang danh tinh BO DO cua A - chung minh khoang cach T8-01 la THAT, "
              "khong phai chi ly thuyet, va KHONG the dua vao hanh vi reset ngoai y muon cua 1 "
              "driver/pooler cu the de dong no")
    except ControlChangeRejectedError:
        check(False, "doi chung 2: mong doi 'B' ke thua duoc pin bo do cua A (ca row lan GUC deu "
              "con) nhung lai bi tu choi - kiem tra lai gia dinh test [6b]")
    finally:
        await raw_conn4.execute("RESET ROLE")
    # don sach pin bo do lai boi doi chung [6b] truoc khi dong pool.
    await raw_conn4.execute("SET ROLE alpha3s_m4_actor_binder")
    await raw_conn4.execute("SELECT m4_stage0p_unpin_actor()")
    await raw_conn4.execute("RESET ROLE")
    await pool.release(raw_conn4)

    # Ghi chu: [1]-[4] o tren da xac nhan TRUC TIEP (qua _actor_session_owner doc ROW, khong dua
    # vao ket qua goi ham nghiep vu) rang pinned_actor_session luon XOA HAN row pin khi cleanup —
    # doc lap voi viec GUC co bi 1 tang pool nao do tu reset hay khong (khac voi doi chung [6a]/
    # [6b] o tren, von CO Y bypass wrapper de do lech giua "chi dua vao GUC reset cua asyncpg" va
    # "wrapper tu xoa row"). Khong can lap lai rieng cho kich ban GUC-khong-bi-reset o day.

    await pool.close()

    await admin.execute(
        "DELETE FROM audit_log WHERE actor_staff_id IN ($1,$2)", staff_a["id"], staff_b["id"])
    await admin.execute(
        "DELETE FROM m4_stage0p_actor_session WHERE staff_id IN ($1,$2)", staff_a["id"], staff_b["id"])
    await admin.execute(
        "DELETE FROM m4_stage0p_actor_credentials WHERE staff_id IN ($1,$2)", staff_a["id"], staff_b["id"])
    await admin.execute(
        "DELETE FROM m4_stage0p_staff_permissions WHERE staff_id IN ($1,$2)", staff_a["id"], staff_b["id"])
    await admin.execute("DELETE FROM staff_users WHERE id IN ($1,$2)", staff_a["id"], staff_b["id"])
    await admin.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
