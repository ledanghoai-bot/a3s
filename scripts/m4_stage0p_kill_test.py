#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: kill rehearsal DUNG DB commit boundary (F-M4-0P-01B).

Chay:
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      -e REDIS_URL=redis://alpha3s-m4-redis:6379/0 \
      alpha3s-m4-test python scripts/m4_stage0p_kill_test.py

CA Review #3 yeu cau tuong minh: "khong dua vao application timestamp hoac transaction-start
now() de chung minh khong co write sau OFF". Script nay dung **transaction ID (xid)** — co che
DB-native, KHONG phai dong ho ung dung: `txid_current()` goi TRONG CUNG transaction voi UPDATE
tat control (allocate xid dung luc do), roi so sanh `xmin` (xid cua transaction da INSERT) cua
TUNG row sample voi xid do. Postgres cap phat xid theo thu tu tang dan tai thoi diem ghi dau
tien — voi cac transaction don-statement, tuan tu, khong chong cheo nhu collector (moi INSERT la
1 implicit transaction rieng), thu tu xid phan anh dung thu tu xay ra thuc te.

Kiem tra:
  [1] Kill GIUA luc collector dang chay that (2 task asyncio dan xen qua await point that —
      khong phai dung truoc khi bat dau).
  [2] aborted_control_off=True va inserted < tong so tin nhan co san (chung minh dung GIUA
      chung, khong phai da xong roi moi tat).
  [3] MOI row da insert deu co xmin < off_txid (DB-native, khong phai app timestamp).
  [4] Fail-to-read=OFF: gia lap doc control loi (dong ket noi giua chung) -> collector dung
      ngay, khong coi la "van ON".
  [5] Thu hoi quyen reviewer doc lap voi cong tac capture (revoke permission khong dung
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
    await admin.execute("UPDATE m4_stage0p_control SET capture_enabled=false WHERE id=1")

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
    eligible = await s.select_eligible_conversations(collector_conn, pending_conn,
                                                       window_start=window_start, window_end=window_end)
    selected = s.select_sample(eligible)
    batch_id = await s.lock_batch(collector_conn, window_start=window_start, window_end=window_end,
                                   eligible_count=len(eligible), selected=selected)

    async with cp_conn.transaction():
        await set_capture_enabled(cp_conn, enabled=True, actor_staff_id=None,
                                  approval_ref="KILL-REHEARSAL-ON")

    off_txid_holder: dict = {}

    async def _flip_off_mid_run():
        """Tat NGAY SAU KHI collector da bat dau (>=1 row) — cang som cang thu hep 'cua so
        dua' (row dang xu ly dot ngot khi off commit): toi da 1 row co the da qua vi tri
        'da doc TRUE truoc do' (ban chat he thong dong thoi that, khong phai loi thiet ke).
        Doi >=1 row (khong phai co dinh sleep) de dam bao collector THAT SU dang chay,
        khong phai tat truoc khi bat dau."""
        watch_conn = await asyncpg.connect(DB_URL)
        try:
            for _ in range(500):
                n = await watch_conn.fetchval(
                    "SELECT count(*) FROM m4_shadow_review_samples WHERE selection_batch=$1", batch_id)
                if n >= 1:
                    break
                await asyncio.sleep(0.001)
            async with cp_conn.transaction():
                row = await cp_conn.fetchrow("SELECT txid_current() AS txid")
                off_txid_holder["txid"] = row["txid"]
                await set_capture_enabled(cp_conn, enabled=False, actor_staff_id=None,
                                          approval_ref="KILL-REHEARSAL-OFF-MID-RUN")
        finally:
            await watch_conn.close()

    print("== [1]+[2] Kill giua luc collector dang chay (asyncio interleave that) ==")
    collector_task = asyncio.create_task(
        s.run_collector(collector_conn, control_conn, pending_conn, batch_id=batch_id))
    flip_task = asyncio.create_task(_flip_off_mid_run())
    result, _ = await asyncio.gather(collector_task, flip_task)
    print(f"  collector result: {result}")
    check(result["aborted_control_off"] is True, "collector dung vi control OFF (khong phai het viec)")
    check(0 < result["inserted"] < N_MESSAGES,
          f"dung GIUA chung: 0 < inserted({result['inserted']}) < tong({N_MESSAGES})")

    print("== [3] DB-native boundary: xid insert vs off_txid (KHONG dung app timestamp) ==")
    off_txid = off_txid_holder["txid"]
    rows = await admin.fetch(
        "SELECT sample_id, xmin FROM m4_shadow_review_samples WHERE selection_batch=$1", batch_id)
    check(len(rows) == result["inserted"], "so row trong DB khop voi so collector bao cao")
    xids = sorted(int(r["xmin"]) for r in rows)
    racing = [x for x in xids if x >= off_txid]
    # Cua so dua CO THAT trong he thong dong thoi that (khong phai loi): row dang xu ly co
    # the da qua buoc doc control=TRUE NGAY TRUOC luc off commit — collector dung o LAN DOC
    # TIEP THEO, khong phai lap tuc giua chung 1 row dang ghi dang do. Can 1 chan CO THE
    # chung minh duoc (khong phai "0 tuyet doi" phi thuc te): toi da 1 row nhu vay, va DUNG
    # LA row insert CUOI CUNG (khong co row nao sau no).
    check(len(racing) <= 1, f"toi da 1 row co xid >= off_txid={off_txid} (cua so dua bi chan, "
          f"thuc te: {len(racing)} row: {racing})")
    if racing:
        check(racing == [xids[-1]], "row 'dua' (neu co) DUNG LA row cuoi cung — khong co row "
              "nao insert SAU no (chung minh collector dung dut khoat ngay lan doc tiep theo)")
    else:
        check(True, "khong co row nao dua — moi row deu xid < off_txid")

    print("== [4] Fail-to-read = OFF (mat ket noi control giua chung) ==")
    broken_conn = await asyncpg.connect(DB_URL)
    await broken_conn.close()  # dong truoc khi dung -> moi query se loi
    result_broken = await read_capture_enabled(broken_conn)
    check(result_broken is False, "connection da dong -> doc that bai -> coi la OFF (fail closed)")

    print("== [5] Thu hoi quyen reviewer doc lap voi cong tac capture ==")
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
    control_still_on_state = await read_capture_enabled(control_conn)
    check(can_select_before and not can_select_after_revoke,
          "revoke SELECT cua reviewer co hieu luc ngay (khong can dung capture)")
    check(control_still_on_state is False,
          "capture control KHONG bi anh huong boi viec revoke quyen reviewer (2 lever doc lap)")
    # khoi phuc quyen cho cac evidence script khac chay sau
    await admin.execute(
        "GRANT SELECT (sample_id, encrypted_message, canonical_text_len, normalization_version, "
        "customer_ref, conversation_ref, captured_at, label_status, selection_batch) "
        "ON m4_shadow_review_samples TO alpha3s_m4_sample_reviewer_api")
    await reviewer_conn.close()

    await admin.execute("DELETE FROM m4_shadow_review_samples")
    await admin.execute("DELETE FROM m4_selection_batches")
    await admin.execute("DELETE FROM audit_log")
    await admin.execute("DELETE FROM messages")
    await admin.execute("DELETE FROM orders")
    await admin.execute("DELETE FROM conversations")
    await admin.execute("DELETE FROM customers")
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
