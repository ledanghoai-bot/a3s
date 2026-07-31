#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: kill rehearsal DUNG DB commit boundary (F-M4-0P-01B).

Chay:
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      -e REDIS_URL=redis://alpha3s-m4-redis:6379/0 \
      alpha3s-m4-test python scripts/m4_stage0p_kill_test.py

REV 2 (CA Technical Review #1, T1-01): xmin/txid_current() DB-native boundary, "0 row dua"
nghiem ngat (khong con "toi da 1").

REV 3 (CA Technical Review #2, F-M4-0P-T2-01): CA chi ro REV2 van CHUA DU — fenced work unit
(khoa 4013003) giu tu fetch->pending-check->encrypt->insert TRONG CUNG transaction co the bi giu
VO THOI HAN neu 1 buoc ben trong treo (Redis hang, DB row-lock contention, process chet giua
chung) — luc do `m4_stage0p_set_capture(OFF)` cho CUNG 1 lock se KHONG BAO GIO commit duoc, phu
nhan toan bo bao dam "OFF dat cai tran thoi gian". Thiet ke moi (stage0p_sampling.py REV3): tach
`peek_next_candidate` (khong lock) khoi `fetch_message_content`+`record_sample` (fenced, boc
trong `asyncio.wait_for(FENCE_UNIT_DEADLINE_SECONDS)`); pending-check co timeout tuong minh o CA
2 lop (truoc fence + recheck ngan trong fence). Script nay THEM 3 kich ban CA yeu cau ro: mo
phong Redis hang, DB write hang, va process death trong luc giu lock — chung minh OFF dat cai
tran thoi gian THAT SU (khong phai chi ly thuyet) va khong co post-hang commit.

Kiem tra:
  [1] OFF NGAY TU DAU -> 0 raw fetch + 0 insert.
  [2] Kill GIUA luc collector dang chay that (asyncio interleave that).
  [3] DB-native boundary NGHIEM NGAT: 0 row dua (T1-01).
  [4] captured_count (T1-02/T2-06) khop dung so INSERT thuc te.
  [5] Fail-to-read=OFF cho read_capture_enabled (ham hien thi/tham khao).
  [6] Thu hoi quyen reviewer doc lap voi cong tac capture.
  [7] REV3 T2-01: Redis hang (socket khong routable) trong pending-check -> fail-closed (pending=
      True) TRONG thoi gian bounded (khong vo han).
  [8] REV3 T2-01: DB write hang (row FOR UPDATE tu 1 session khac chan UPDATE ben trong
      record_sample) -> fenced unit TIMEOUT dung han (asyncio.wait_for + asyncpg cancel query
      that su), transaction rollback (0 sample luu), VA set_capture(OFF) van thanh cong nhanh
      NGAY SAU DO (lock 4013003 da duoc nha khi transaction abort).
  [9] REV3 T2-01: process death — connection giu pg_advisory_xact_lock(4013003) bi dong dot ngot
      (khong COMMIT/ROLLBACK) -> Postgres tu phat hien mat ket noi, abort transaction, nha lock;
      set_capture(OFF) ngay sau do van thanh cong nhanh (khong bi ro ri lock vinh vien).
"""

import asyncio
import datetime
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402
from _stage0p_signing_service_helper import (  # noqa: E402
    start_signing_service,
    stop_signing_service,
)

from app.config import settings  # noqa: E402
from app.services.pii import stage0p_sampling as s  # noqa: E402
from app.services.pii.crypto import TRANSCRIPT_KEY_VERSION  # noqa: E402
from app.services.pii.stage0p_control import (  # noqa: E402
    pin_actor,
    read_capture_enabled,
    record_capture_approval,
    set_capture_enabled,
)
from app.services.pii.stage0p_eligibility import is_pending_deletion  # noqa: E402

DB_URL = (os.environ.get("DATABASE_URL")
          or "postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s").replace("+asyncpg", "")

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


PIN_SECRET = "kill-test-pin-secret"


async def _provision_pin_secret(admin, *, staff_id, pin_secret=PIN_SECRET) -> None:
    """T5-01/T6-01: cap pin_secret NGOAI LUONG (khong qua pin_actor) — mo phong buoc
    provisioning. pin_secret_hash — KHONG con luu plaintext (T6-01)."""
    await admin.execute(
        "INSERT INTO m4_stage0p_actor_credentials (staff_id, pin_secret_hash, provisioned_by) "
        "VALUES ($1, crypt($2, gen_salt('bf')), $1) "
        "ON CONFLICT (staff_id) DO UPDATE SET pin_secret_hash=crypt($2, gen_salt('bf')), "
        "failed_attempts=0, locked_until=NULL", staff_id, pin_secret)


async def _pin(conn, staff_id: int) -> None:
    """T5-01: pin actor vao session (role alpha3s_m4_actor_binder), roi RESET ROLE — khoa boi
    pg_backend_pid() cua CHINH connection nay, sinh ton qua lan SET ROLE tiep theo cua caller."""
    await conn.execute("SET ROLE alpha3s_m4_actor_binder")
    await pin_actor(conn, staff_id=staff_id, pin_secret=PIN_SECRET)
    await conn.execute("RESET ROLE")


async def _grant_approval(admin, *, approval_ref: str, staff_id: int, now: datetime.datetime) -> None:
    conn = await asyncpg.connect(DB_URL)
    await _pin(conn, staff_id)
    await conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    try:
        await record_capture_approval(
            conn, approval_ref=approval_ref, requested_enabled=True,
            valid_from=now - datetime.timedelta(hours=1), valid_until=now + datetime.timedelta(hours=1))
    finally:
        await conn.execute("RESET ROLE")
        await conn.close()


async def main() -> int:
    # REV11 T10-02: KHONG con dat m4_sample_key_b64/m4_transcript_hmac_key_b64 trong process nay
    # (dong vai collector) - 2 khoa CHI ton tai trong tien trinh signing service RIENG (xem
    # start_signing_service()), chung minh collector process THAT SU khong giu khoa.
    signing_socket = f"/tmp/m4-signing-{os.getpid()}/sock"  # T11-02: thu muc RIENG, khong dat truc tiep duoi /tmp (mode 1777 bi tu choi)
    signing_proc, _sample_key, transcript_key = await start_signing_service(socket_path=signing_socket)
    settings.m4_stage0p_signing_socket = signing_socket
    real_redis_url = settings.redis_url

    admin = await asyncpg.connect(DB_URL)
    # REV10 T8-02: provision ban sao khoa HMAC ky transcript de DB verifier doi chieu duoc
    # (SELECT chi GRANT cho alpha3s_m4_definer - xem migration 039 §3b2).
    await admin.execute(
        "INSERT INTO m4_stage0p_transcript_signing_keys (key_version, hmac_key) VALUES ($1, $2) "
        "ON CONFLICT (key_version) DO UPDATE SET hmac_key = EXCLUDED.hmac_key, retired_at = NULL",
        TRANSCRIPT_KEY_VERSION, transcript_key)
    await admin.execute("DELETE FROM m4_shadow_review_samples")
    await admin.execute("DELETE FROM m4_stage0p_capture_progress")
    await admin.execute("DELETE FROM m4_selection_batches")
    await admin.execute("DELETE FROM m4_stage0p_capture_approvals WHERE approval_ref LIKE 'kill-test-%'")
    await admin.execute("DELETE FROM audit_log")
    await admin.execute(
        "DELETE FROM m4_stage0p_staff_permissions WHERE staff_id IN "
        "(SELECT id FROM staff_users WHERE username LIKE 'm4-kill-test%')")
    await admin.execute(
        "DELETE FROM m4_stage0p_actor_session WHERE staff_id IN "
        "(SELECT id FROM staff_users WHERE username LIKE 'm4-kill-test%')")
    await admin.execute(
        "DELETE FROM m4_stage0p_actor_credentials WHERE staff_id IN "
        "(SELECT id FROM staff_users WHERE username LIKE 'm4-kill-test%')")
    await admin.execute("DELETE FROM staff_users WHERE username LIKE 'm4-kill-test%'")
    await admin.execute("UPDATE m4_stage0p_control SET capture_enabled=false WHERE id=1")

    staff = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-kill-test-staff', 'x', 'x', true) RETURNING id"
    )
    for perm in ("m4.stage0p.approve", "m4.stage0p.operate"):
        await admin.execute(
            "INSERT INTO m4_stage0p_staff_permissions (staff_id, permission, granted_by) "
            "VALUES ($1,$2,$1) ON CONFLICT DO NOTHING", staff["id"], perm)
    await _provision_pin_secret(admin, staff_id=staff["id"])
    now = datetime.datetime.now(datetime.timezone.utc)
    await _grant_approval(admin, approval_ref="kill-test-approval", staff_id=staff["id"], now=now)

    cust = await admin.fetchrow("INSERT INTO customers (psid, name) VALUES ('kill-test','X') RETURNING id")
    conv = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust["id"])
    await admin.execute("INSERT INTO orders (customer_id, created_at) VALUES ($1, now())", cust["id"])
    N_MESSAGES = 15
    for i in range(N_MESSAGES):
        await admin.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer',$2)",
            conv["id"], f"tin nhan so {i} cua khach de test kill switch giua chung",
        )

    collector_conn = await asyncpg.connect(DB_URL)
    await collector_conn.execute("SET ROLE alpha3s_m4_sample_collector")
    control_conn = await asyncpg.connect(DB_URL)
    pending_conn = await asyncpg.connect(DB_URL)
    await pending_conn.execute("SET ROLE alpha3s_m4_pending_checker")
    cp_conn = await asyncpg.connect(DB_URL)

    async def _set_capture(*, enabled, approval_ref):
        """T4-04: pin actor TRUOC (role alpha3s_m4_actor_binder), roi SET ROLE control_plane."""
        await _pin(cp_conn, staff["id"])
        await cp_conn.execute("SET ROLE alpha3s_m4_control_plane")
        try:
            return await set_capture_enabled(cp_conn, enabled=enabled, approval_ref=approval_ref)
        finally:
            await cp_conn.execute("RESET ROLE")

    window_start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    window_end = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)

    print("== [1] OFF NGAY TU DAU (chua tung ON) -> 0 raw fetch + 0 insert ==")
    eligible0 = await s.select_eligible_conversations(collector_conn, pending_conn,
                                                       window_start=window_start, window_end=window_end)
    selected0 = s.select_sample(eligible0)
    batch_off_start = await s.lock_batch(collector_conn, window_start=window_start, window_end=window_end,
                                         eligible_count=len(eligible0), selected=selected0)
    still_off = await admin.fetchval("SELECT capture_enabled FROM m4_stage0p_control WHERE id=1")
    check(still_off is False, "precondition: control van OFF (chua tung bat)")
    result_off_start = await s.run_collector(collector_conn, pending_conn, batch_id=batch_off_start)
    check(result_off_start["inserted"] == 0, "OFF tu dau -> 0 insert")
    check(result_off_start["aborted_control_off"] is True, "OFF tu dau -> aborted_control_off=True")
    raw_fetch_count = await admin.fetchval(
        "SELECT count(*) FROM audit_log WHERE action='m4_message_fetch' AND entity_id=$1",
        str(batch_off_start))
    check(raw_fetch_count == 0, "OFF tu dau -> 0 audit row m4_message_fetch (0 RAW FETCH, "
          "khong chi 0 insert — chung minh content khong bao gio roi DB)")

    print("== BAT control that su (approval hop le) de chuan bi kich ban [2] ==")
    await _set_capture(enabled=True, approval_ref="kill-test-approval")

    eligible = await s.select_eligible_conversations(collector_conn, pending_conn,
                                                       window_start=window_start, window_end=window_end)
    selected = s.select_sample(eligible)
    batch_id = await s.lock_batch(collector_conn, window_start=window_start, window_end=window_end,
                                   eligible_count=len(eligible), selected=selected)

    off_txid_holder: dict = {}

    async def _flip_off_mid_run():
        """Tat NGAY SAU KHI collector da bat dau (>=1 row)."""
        watch_conn = await asyncpg.connect(DB_URL)
        try:
            for _ in range(500):
                n = await watch_conn.fetchval(
                    "SELECT count(*) FROM m4_shadow_review_samples WHERE selection_batch=$1", batch_id)
                if n >= 1:
                    break
                await asyncio.sleep(0.001)
            await _pin(cp_conn, staff["id"])  # session-scoped — phai commit truoc, TACH BIET transaction duoi day
            await cp_conn.execute("SET ROLE alpha3s_m4_control_plane")
            async with cp_conn.transaction():
                await set_capture_enabled(cp_conn, enabled=False, approval_ref="kill-test-off-mid-run")
                row = await cp_conn.fetchrow("SELECT txid_current() AS txid")
                off_txid_holder["txid"] = row["txid"]
            await cp_conn.execute("RESET ROLE")
        finally:
            await watch_conn.close()

    print("== [2] Kill giua luc collector dang chay (asyncio interleave that) ==")
    collector_task = asyncio.create_task(
        s.run_collector(collector_conn, pending_conn, batch_id=batch_id))
    flip_task = asyncio.create_task(_flip_off_mid_run())
    result, _ = await asyncio.gather(collector_task, flip_task)
    print(f"  collector result: {result}")
    check(result["aborted_control_off"] is True, "collector dung vi control OFF (khong phai het viec)")
    check(0 < result["inserted"] < N_MESSAGES,
          f"dung GIUA chung: 0 < inserted({result['inserted']}) < tong({N_MESSAGES})")

    print("== [3] DB-native boundary NGHIEM NGAT: 0 row dua (T1-01 fixed, khong con 'toi da 1') ==")
    off_txid = off_txid_holder["txid"]
    rows = await admin.fetch(
        "SELECT sample_id, xmin FROM m4_shadow_review_samples WHERE selection_batch=$1", batch_id)
    check(len(rows) == result["inserted"], "so row trong DB khop voi so collector bao cao")
    xids = sorted(int(r["xmin"]) for r in rows)
    racing = [x for x in xids if x >= off_txid]
    check(len(racing) == 0,
          f"0 row co xid >= off_txid={off_txid} (thuc te: {len(racing)} row: {racing})")

    print("== [4] captured_count (T1-02/T2-06, dem BEN VUNG tai DB) khop dung so insert thuc te ==")
    captured_count = await admin.fetchval(
        "SELECT captured_count FROM m4_selection_batches WHERE batch_id=$1", batch_id)
    check(captured_count == result["inserted"],
          f"captured_count DB ({captured_count}) == inserted thuc te ({result['inserted']})")

    print("== [5] Fail-to-read = OFF (ham hien thi/tham khao read_capture_enabled) ==")
    broken_conn = await asyncpg.connect(DB_URL)
    await broken_conn.close()
    result_broken = await read_capture_enabled(broken_conn)
    check(result_broken is False, "connection da dong -> doc that bai -> coi la OFF (fail closed)")

    print("== [7] REV3 T2-01: Redis hang -> pending-check fail-closed TRONG thoi gian bounded ==")
    settings.redis_url = "redis://10.255.255.1:6399/0"  # dia chi khong routable — mo phong hang
    t0 = time.monotonic()
    hang_result = await is_pending_deletion(pending_conn, cust["id"], timeout=1.0)
    elapsed_redis = time.monotonic() - t0
    settings.redis_url = real_redis_url
    check(hang_result is True, "Redis khong routable -> fail-closed (pending=True)")
    check(elapsed_redis < 3.0,
          f"Redis hang bi chan trong thoi gian bounded (thuc te {elapsed_redis:.2f}s < 3.0s, "
          f"khong phai vo han)")

    print("== [8] REV3 T2-01: DB write hang (row FOR UPDATE) -> fenced unit TIMEOUT dung han, rollback ==")
    cust_h = await admin.fetchrow("INSERT INTO customers (psid, name) VALUES ('kill-test-hang','H') RETURNING id")
    conv_h = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust_h["id"])
    msg_h = await admin.fetchrow(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer','tin nhan hang') RETURNING id",
        conv_h["id"])
    hang_batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start, window_end, eligible_count, selected_count, "
        "algorithm_seed, locked_conversation_ids, purpose_code, normalization_version) VALUES (now()-interval '1 day', now(), "
        "1, 1, 'kill-test-hang', ARRAY[$1]::bigint[], 'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id",
        conv_h["id"])
    await _set_capture(enabled=True, approval_ref="kill-test-approval")

    lock_holder = await asyncpg.connect(DB_URL)
    tr = lock_holder.transaction()
    await tr.start()
    await lock_holder.fetchrow("SELECT * FROM m4_selection_batches WHERE batch_id=$1 FOR UPDATE",
                               hang_batch["batch_id"])
    try:
        collector_conn2 = await asyncpg.connect(DB_URL)
        await collector_conn2.execute("SET ROLE alpha3s_m4_sample_collector")
        timed_out = False
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(
                s._run_fenced_unit(collector_conn2, pending_conn, batch_id=hang_batch["batch_id"],
                                   conversation_id=conv_h["id"], message_id=msg_h["id"],
                                   customer_id=cust_h["id"]),
                timeout=s.FENCE_UNIT_DEADLINE_SECONDS,
            )
        except asyncio.TimeoutError:
            timed_out = True
        elapsed_hang = time.monotonic() - t0
        check(timed_out, "DB write hang (row FOR UPDATE tu session khac) -> fenced unit TIMEOUT dung han")
        check(elapsed_hang < s.FENCE_UNIT_DEADLINE_SECONDS + 3.0,
              f"elapsed ({elapsed_hang:.1f}s) gan deadline ({s.FENCE_UNIT_DEADLINE_SECONDS}s), khong vo han")
        await collector_conn2.close()
    finally:
        await tr.rollback()  # nha row lock — mo phong session giu lock ket thuc
    await lock_holder.close()

    count_after_hang = await admin.fetchval(
        "SELECT captured_count FROM m4_selection_batches WHERE batch_id=$1", hang_batch["batch_id"])
    check(count_after_hang == 0, "DB write hang -> transaction rollback, 0 sample duoc luu (khong nua-ghi)")
    sample_count_after_hang = await admin.fetchval(
        "SELECT count(*) FROM m4_shadow_review_samples WHERE selection_batch=$1", hang_batch["batch_id"])
    check(sample_count_after_hang == 0, "DB write hang -> 0 row sample trong bang (INSERT cung rollback theo)")

    t0 = time.monotonic()
    await _set_capture(enabled=False, approval_ref="kill-test-off-after-hang")
    elapsed_off = time.monotonic() - t0
    check(elapsed_off < 3.0,
          f"set_capture(OFF) SAU KHI DB write hang timeout -> thanh cong NHANH ({elapsed_off:.2f}s, "
          f"lock 4013003 da duoc nha khi fenced unit bi cancel)")

    print("== [9] REV3 T2-01: process death — connection giu lock 4013003 bi dong dot ngot ==")
    dying_conn = await asyncpg.connect(DB_URL)
    dying_tr = dying_conn.transaction()
    await dying_tr.start()
    await dying_conn.fetchval("SELECT pg_advisory_xact_lock(4013003)")
    await dying_conn.close()  # mo phong crash: dong THAT SU, khong COMMIT/ROLLBACK tuong minh

    t0 = time.monotonic()
    off_conn = await asyncpg.connect(DB_URL)
    await _pin(off_conn, staff["id"])
    await off_conn.execute("SET ROLE alpha3s_m4_control_plane")
    off_after_death_row = await off_conn.fetchrow(
        "SELECT * FROM m4_stage0p_set_capture($1,$2)", False, "kill-test-off-after-death")
    elapsed_death = time.monotonic() - t0
    await off_conn.execute("RESET ROLE")
    await off_conn.close()
    check(off_after_death_row["after_enabled"] is False,
          "set_capture(OFF) thanh cong SAU KHI connection giu lock 'chet' dot ngot")
    check(elapsed_death < 3.0,
          f"set_capture(OFF) hoan tat nhanh ({elapsed_death:.2f}s) — lock KHONG bi ro ri sau process death")

    print("== [6] Thu hoi quyen reviewer doc lap voi cong tac capture ==")
    reviewer_conn = await asyncpg.connect(DB_URL)
    await reviewer_conn.execute("SET ROLE alpha3s_m4_sample_reviewer_api")
    can_select_before = True
    try:
        await reviewer_conn.fetchval("SELECT count(*) FROM m4_shadow_review_samples")
    except asyncpg.InsufficientPrivilegeError:
        can_select_before = False
    await admin.execute("REVOKE SELECT ON m4_shadow_review_samples FROM alpha3s_m4_sample_reviewer_api")
    can_select_after_revoke = True
    try:
        await reviewer_conn.fetchval("SELECT count(*) FROM m4_shadow_review_samples")
    except asyncpg.InsufficientPrivilegeError:
        can_select_after_revoke = False
    control_still_off_state = await read_capture_enabled(control_conn)
    check(can_select_before and not can_select_after_revoke,
          "revoke SELECT cua reviewer co hieu luc ngay (khong can dung capture)")
    check(control_still_off_state is False,
          "capture control KHONG bi anh huong boi viec revoke quyen reviewer (2 lever doc lap)")
    await admin.execute(
        "GRANT SELECT (sample_id, encrypted_message, canonical_text_len, normalization_version, "
        "customer_ref, conversation_ref, captured_at, label_status, selection_batch, labeled_slots) "
        "ON m4_shadow_review_samples TO alpha3s_m4_sample_reviewer_api")
    await reviewer_conn.close()

    print("== Xac nhan control ve OFF cuoi script ==")
    final_state = await admin.fetchval("SELECT capture_enabled FROM m4_stage0p_control WHERE id=1")
    check(final_state is False, "control ve OFF truoc khi script ket thuc")

    await admin.execute("DELETE FROM m4_shadow_review_samples")
    await admin.execute("DELETE FROM m4_stage0p_capture_progress")
    await admin.execute("DELETE FROM m4_selection_batches")
    await admin.execute("DELETE FROM audit_log")
    await admin.execute("DELETE FROM messages")
    await admin.execute("DELETE FROM orders")
    await admin.execute("DELETE FROM conversations")
    await admin.execute("DELETE FROM customers")
    await admin.execute("DELETE FROM m4_stage0p_capture_approvals WHERE approval_ref LIKE 'kill-test-%'")
    await admin.execute("DELETE FROM m4_stage0p_staff_permissions WHERE staff_id=$1", staff["id"])
    await admin.execute("DELETE FROM m4_stage0p_actor_session WHERE staff_id=$1", staff["id"])
    await admin.execute("DELETE FROM m4_stage0p_actor_credentials WHERE staff_id=$1", staff["id"])
    await admin.execute("DELETE FROM staff_users WHERE id=$1", staff["id"])
    await admin.close()
    await collector_conn.close()
    await control_conn.close()
    await pending_conn.close()
    await cp_conn.close()
    await stop_signing_service(signing_proc, signing_socket)

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
