#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: kill rehearsal DUNG DB commit boundary (F-M4-0P-01B).

Chay:
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      -e REDIS_URL=redis://alpha3s-m4-redis:6379/0 \
      alpha3s-m4-test python scripts/m4_stage0p_kill_test.py

REV 2 (CA Technical Review #1, F-M4-0P-T1-01): ban goc dung `xmin`/`txid_current()` va CHAP
NHAN "toi da 1 row dua" — CA tu choi ro: "Kiem tra bang xmin va cho phep mot row dua khong chung
minh kill boundary". Thiet ke moi (migration 039 §5a/§5b) dung `pg_advisory_xact_lock(4013003)`
CUNG 1 lock key giua `m4_stage0p_fetch_next_message` va `m4_stage0p_set_capture` — ai giu lock
truoc PHAI hoan tat/rollback (COMMIT/ROLLBACK, tuc la nha lock) TRUOC KHI ben kia duoc tiep tuc.
Vi xid duoc Postgres cap phat theo thu tu TANG DAN toan cluster tai lan ghi DAU TIEN cua transaction
(XidGenLock, dam bao toan cuc — xem ghi chu trong ham `_flip_off_mid_run`), va OFF-transaction
CHI ghi (cap phat xid) SAU KHI da giu duoc lock (tuc la SAU KHI collector transaction dang giu
lock da commit/rollback), MOI row sample da INSERT trong luc dua PHAI co xid < off_txid — dung
"0 tuyet doi", KHONG con la "toi da 1" nhu ban goc.

Kiem tra:
  [1] OFF NGAY TU DAU (chua tung bat ON) -> 0 raw fetch (audit_log khong co row m4_message_fetch
      nao cho batch nay) + 0 insert — CA yeu cau rieng, tach biet voi kich ban mid-run.
  [2] Kill GIUA luc collector dang chay that (2 task asyncio dan xen qua await point that —
      khong phai dung truoc khi bat dau). aborted_control_off=True va 0 < inserted < tong so.
  [3] DB-native boundary NGHIEM NGAT: TAT CA row da insert deu co xmin < off_txid — 0 row dua,
      khong con "toi da 1" (T1-01 fixed).
  [4] captured_count tren m4_selection_batches (T1-02, dem BEN VUNG tai DB) khop dung so INSERT
      thuc te — khong chi dua vao Python counter.
  [5] Fail-to-read=OFF cho `read_capture_enabled` (ham hien thi/tham khao, KHONG con nam tren
      duong quyet dinh doc plaintext — quyet dinh THAT nam trong ham DB, da kiem lai o
      m4_stage0p_permissions_test.py).
  [6] Thu hoi quyen reviewer doc lap voi cong tac capture (revoke permission khong dung
      m4_stage0p_capture_enabled).
"""

import asyncio
import base64
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.pii import stage0p_sampling as s  # noqa: E402
from app.services.pii.stage0p_control import (  # noqa: E402
    read_capture_enabled,
    set_capture_enabled,
)

DB_URL = (os.environ.get("DATABASE_URL")
          or "postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s").replace("+asyncpg", "")

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


async def main() -> int:
    settings.m4_sample_key_b64 = base64.b64encode(os.urandom(32)).decode()

    admin = await asyncpg.connect(DB_URL)
    await admin.execute("DELETE FROM m4_shadow_review_samples")
    await admin.execute("DELETE FROM m4_selection_batches")
    await admin.execute("DELETE FROM audit_log")
    await admin.execute("DELETE FROM staff_users WHERE username LIKE 'm4-kill-test%'")
    await admin.execute("UPDATE m4_stage0p_control SET capture_enabled=false WHERE id=1")

    staff = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-kill-test-staff', 'x', 'x', true) RETURNING id"
    )

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
    await cp_conn.execute("SET ROLE alpha3s_m4_control_plane")

    import datetime
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

    print("== BAT control that su (qua ham, actor/approval hop le) de chuan bi kich ban [2] ==")
    await set_capture_enabled(cp_conn, enabled=True, actor_staff_id=staff["id"],
                              approval_ref="KILL-REHEARSAL-ON")

    eligible = await s.select_eligible_conversations(collector_conn, pending_conn,
                                                       window_start=window_start, window_end=window_end)
    selected = s.select_sample(eligible)
    batch_id = await s.lock_batch(collector_conn, window_start=window_start, window_end=window_end,
                                   eligible_count=len(eligible), selected=selected)

    off_txid_holder: dict = {}

    async def _flip_off_mid_run():
        """Tat NGAY SAU KHI collector da bat dau (>=1 row) — cho collector THAT SU dang chay,
        khong phai tat truoc khi bat dau. off_txid duoc doc SAU KHI set_capture_enabled() da
        thuc thi UPDATE (cung 1 transaction — txid da duoc cap phat luc do, SELECT txid_current()
        sau do chi tra lai CUNG gia tri, khong cap phat moi) — KHONG doc txid_current() TRUOC khi
        goi ham (se cap phat xid som hon luc thuc su giu duoc advisory lock, lam sai lech thu tu
        so sanh)."""
        watch_conn = await asyncpg.connect(DB_URL)
        try:
            for _ in range(500):
                n = await watch_conn.fetchval(
                    "SELECT count(*) FROM m4_shadow_review_samples WHERE selection_batch=$1", batch_id)
                if n >= 1:
                    break
                await asyncio.sleep(0.001)
            async with cp_conn.transaction():
                await set_capture_enabled(cp_conn, enabled=False, actor_staff_id=staff["id"],
                                          approval_ref="KILL-REHEARSAL-OFF-MID-RUN")
                row = await cp_conn.fetchrow("SELECT txid_current() AS txid")
                off_txid_holder["txid"] = row["txid"]
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
          f"0 row co xid >= off_txid={off_txid} (fence bang advisory lock 4013003 dam bao ranh "
          f"gioi TUYET DOI — khong con 'toi da 1' — thuc te: {len(racing)} row: {racing})")

    print("== [4] captured_count (T1-02, dem BEN VUNG tai DB) khop dung so insert thuc te ==")
    captured_count = await admin.fetchval(
        "SELECT captured_count FROM m4_selection_batches WHERE batch_id=$1", batch_id)
    check(captured_count == result["inserted"],
          f"captured_count DB ({captured_count}) == inserted thuc te ({result['inserted']})")

    print("== [5] Fail-to-read = OFF (ham hien thi/tham khao read_capture_enabled) ==")
    broken_conn = await asyncpg.connect(DB_URL)
    await broken_conn.close()  # dong truoc khi dung -> moi query se loi
    result_broken = await read_capture_enabled(broken_conn)
    check(result_broken is False, "connection da dong -> doc that bai -> coi la OFF (fail closed)")

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
          "capture control KHONG bi anh huong boi viec revoke quyen reviewer (2 lever doc lap) "
          "— van OFF vi [2] da tat lai giua chung")
    # khoi phuc quyen cho cac evidence script khac chay sau
    await admin.execute(
        "GRANT SELECT (sample_id, encrypted_message, canonical_text_len, normalization_version, "
        "customer_ref, conversation_ref, captured_at, label_status, selection_batch, labeled_slots) "
        "ON m4_shadow_review_samples TO alpha3s_m4_sample_reviewer_api")
    await reviewer_conn.close()

    await admin.execute("DELETE FROM m4_shadow_review_samples")
    await admin.execute("DELETE FROM m4_selection_batches")
    await admin.execute("DELETE FROM audit_log")
    await admin.execute("DELETE FROM messages")
    await admin.execute("DELETE FROM orders")
    await admin.execute("DELETE FROM conversations")
    await admin.execute("DELETE FROM customers")
    await admin.execute("DELETE FROM staff_users WHERE id=$1", staff["id"])
    await admin.close()
    await collector_conn.close()
    await control_conn.close()
    await pending_conn.close()
    await cp_conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
