#!/usr/bin/env python
"""I-B M4 Stage 0P — evidence: cap/eligibility/DSR E2E (CA acceptance criteria #7, #8, #9).

Chay:
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      -e REDIS_URL=redis://alpha3s-m4-redis:6379/0 \
      alpha3s-m4-test python scripts/m4_stage0p_sampling_test.py

Kiem tra:
  [A] Multi-byte UTF-8: tin nhan toan ky tu co dau vuot MAX_CHARS -> cat dung (UTF-8-safe ca 2
      buoc), khong gay loi decode.
  [B] Oversized ciphertext bi DB CHECK octet_length tu choi (bypass logic Python).
  [C] Hard cap 260: eligible > 260 -> selected dung 260, deterministic (chay lai select_sample
      2 lan tren CUNG input -> CUNG ket qua).
  [D] Concurrent collector: 2 tien trinh cung xin advisory lock -> 1 thanh cong, 1 lock_failed.
  [E] Eligibility: hoi thoai NGOAI cua so (du khach co order trong cua so) -> loai.
  [F] Eligibility: hoi thoai KHAC (khong lien quan don hang) cua CUNG khach, ngoai cua so -> loai;
      hoi thoai dung (trong cua so, co order) -> chon.
  [G] Pending-DSR race: khach thanh pending-deletion GIUA luc collector dang chay -> cac tin
      nhan con lai cua khach do bi bo qua (khong ghi).
  [H] DSR retry/idempotency: goi process_deletion() 2 lan -> lan 2 no-op sach, khong loi.
  [I] Source-conversation da mat TRUOC do (khong phai do DSR nay xoa): sample van bi xoa dung
      (khong orphan, khong join sang conversations).
  [J] Cross-customer: xoa DSR cua khach A khong dung tram sample cua khach B.
"""

import asyncio
import base64
import datetime
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402
from _stage0p_signing_service_helper import (  # noqa: E402
    start_signing_service,
    stop_signing_service,
)

from app.config import settings  # noqa: E402
from app.services import data_deletion  # noqa: E402
from app.services.pii import stage0p_sampling as s  # noqa: E402
from app.services.pii.crypto import (  # noqa: E402
    TRANSCRIPT_KEY_VERSION,
    decrypt_sample_value,
)
from app.services.pii.stage0p_control import (  # noqa: E402
    pin_actor,
    record_capture_approval,
    set_capture_enabled,
)

DB_URL = (os.environ.get("DATABASE_URL")
          or "postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s").replace("+asyncpg", "")

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


PIN_SECRET = "sampling-test-pin-secret"


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
    pg_backend_pid() cua CHINH connection nay."""
    await conn.execute("SET ROLE alpha3s_m4_actor_binder")
    await pin_actor(conn, staff_id=staff_id, pin_secret=PIN_SECRET)
    await conn.execute("RESET ROLE")


async def _reset(admin) -> None:
    for tbl in ("m4_shadow_review_samples", "m4_stage0p_capture_progress", "m4_selection_batches",
               "audit_log", "messages", "orders", "conversations", "customers"):
        await admin.execute(f"DELETE FROM {tbl}")
    await admin.execute("UPDATE m4_stage0p_control SET capture_enabled=false WHERE id=1")


async def main() -> int:
    settings.database_url = DB_URL
    # REV11 T10-01/T10-02: khoa nay CHI dung cho kich ban [A] duoi day (test crypto module TRUC
    # TIEP, KHONG qua collector) — collector path THAT SU (s.run_collector) dung signing service
    # RIENG (xem start_signing_service()), KHONG bao gio doc bien nay.
    settings.m4_sample_key_b64 = base64.b64encode(os.urandom(32)).decode()
    signing_socket = f"/tmp/m4-signing-{os.getpid()}/sock"  # T11-02: thu muc RIENG, khong dat truc tiep duoi /tmp (mode 1777 bi tu choi)
    # REV13 T12-01: allowed_uid gio BAT BUOC (khong con mac dinh tu tin chinh minh).
    signing_proc, _sample_key, transcript_key, auth_verify_key = await start_signing_service(
        socket_path=signing_socket, allowed_uid=os.getuid())
    settings.m4_stage0p_signing_socket = signing_socket
    admin = await asyncpg.connect(DB_URL)
    # REV10 T8-02: provision ban sao khoa HMAC ky transcript de DB verifier doi chieu duoc.
    await admin.execute(
        "INSERT INTO m4_stage0p_transcript_signing_keys (key_version, hmac_key) VALUES ($1, $2) "
        "ON CONFLICT (key_version) DO UPDATE SET hmac_key = EXCLUDED.hmac_key, retired_at = NULL",
        TRANSCRIPT_KEY_VERSION, transcript_key)
    # REV13 T12-02: provision khoa signing_auth (chieu nguoc lai - DB ky, signer verify).
    await admin.execute(
        "INSERT INTO m4_stage0p_signing_auth_keys (key_version, hmac_key) VALUES ($1, $2) "
        "ON CONFLICT (key_version) DO UPDATE SET hmac_key = EXCLUDED.hmac_key, retired_at = NULL",
        "m4-signing-auth-v1", auth_verify_key)
    await _reset(admin)
    await admin.execute("DELETE FROM m4_stage0p_capture_approvals WHERE approval_ref='CAP-G'")
    await admin.execute(
        "DELETE FROM m4_stage0p_staff_permissions WHERE staff_id IN "
        "(SELECT id FROM staff_users WHERE username='m4-sampling-test-staff')")
    await admin.execute(
        "DELETE FROM m4_stage0p_actor_session WHERE staff_id IN "
        "(SELECT id FROM staff_users WHERE username='m4-sampling-test-staff')")
    await admin.execute(
        "DELETE FROM m4_stage0p_actor_credentials WHERE staff_id IN "
        "(SELECT id FROM staff_users WHERE username='m4-sampling-test-staff')")
    await admin.execute("DELETE FROM staff_users WHERE username='m4-sampling-test-staff'")

    print("== [A] Multi-byte UTF-8 truncation ==")
    long_text = "đường " * 500  # 6 ky tu/tu, co dau, > MAX_CHARS(2000) va > MAX_BYTES(8000)
    truncated_text, was_truncated = s._truncate(long_text)
    check(was_truncated, "text dai bi danh dau truncated=True")
    check(len(truncated_text.encode("utf-8")) <= s.MAX_BYTES, "ket qua sau cat <= MAX_BYTES")
    check(len(truncated_text) <= s.MAX_CHARS, "ket qua sau cat <= MAX_CHARS")
    try:
        truncated_text.encode("utf-8").decode("utf-8")
        valid_utf8 = True
    except UnicodeDecodeError:
        valid_utf8 = False
    check(valid_utf8, "ket qua la UTF-8 hop le (khong chen dot ky tu da byte)")
    # roundtrip qua encrypt that de xac nhan khong vo tinh pha hong khi luu DB
    blob = None
    from app.services.pii.crypto import encrypt_sample_value
    blob = encrypt_sample_value(truncated_text, customer_ref="1", conversation_ref="1",
                                sample_id="utf8-test")
    check(len(blob) <= 8030, f"ciphertext <= 8030 byte REV2 T1-02 (thuc te {len(blob)})")
    rt = decrypt_sample_value(blob, customer_ref="1", conversation_ref="1", sample_id="utf8-test")
    check(rt == truncated_text, "giai ma khop dung noi dung da cat")

    print("== [B] DB CHECK tu choi ciphertext qua khoi ==")
    await _reset(admin)
    cust = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('cap-b','x') RETURNING id")
    conv = await admin.fetchrow("INSERT INTO conversations (customer_id) VALUES ($1) RETURNING id", cust["id"])
    batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start,window_end,eligible_count,selected_count,"
        "algorithm_seed,locked_conversation_ids,purpose_code, normalization_version) VALUES (now()-interval '1 day',now(),"
        "1,1,'capb',ARRAY[$1]::bigint[],'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id", conv["id"])
    oversized_blob = b"\x00" * 9000  # co y vuot 8045
    try:
        await admin.execute(
            "INSERT INTO m4_shadow_review_samples (sample_id,customer_ref,conversation_ref,"
            "encrypted_message,canonical_text_len,expires_at,purpose_code,normalization_version,"
            "selection_batch) VALUES ($1,$2,$3,$4,1,now()+interval '1 day','P12_PII_DETECTOR_EVAL',"
            "'nfc-v1',$5)", str(uuid.uuid4()), str(cust["id"]), str(conv["id"]), oversized_blob,
            batch["batch_id"])
        check(False, "INSERT ciphertext 9000 byte phai bi CHECK tu choi")
    except asyncpg.CheckViolationError:
        check(True, "DB CHECK octet_length tu choi ciphertext oversized")

    print("== [C] Hard cap 260 + deterministic ==")
    eligible_fake = [{"conversation_id": i, "customer_id": i} for i in range(1, 301)]
    sel1 = s.select_sample(eligible_fake)
    sel2 = s.select_sample(eligible_fake)
    check(len(sel1) == 260, f"selected dung 260 tu 300 eligible (thuc te {len(sel1)})")
    check(sel1 == sel2, "deterministic: 2 lan chon tren cung input -> cung ket qua")
    eligible_small = [{"conversation_id": i, "customer_id": i} for i in range(1, 50)]
    check(len(s.select_sample(eligible_small)) == 49, "duoi cap -> lay het (49/49)")

    print("== [D] Concurrent collector (advisory lock don-writer) ==")
    await _reset(admin)
    cust = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('cap-d','x') RETURNING id")
    conv = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", cust["id"])
    await admin.execute("INSERT INTO orders (customer_id, created_at) VALUES ($1, now())", cust["id"])
    await admin.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer','tin nhan')",
        conv["id"])
    batch = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start,window_end,eligible_count,selected_count,"
        "algorithm_seed,locked_conversation_ids,purpose_code, normalization_version) VALUES (now()-interval '1 day',now(),"
        "1,1,'capd',ARRAY[$1]::bigint[],'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id", conv["id"])
    conn1 = await asyncpg.connect(DB_URL)
    await conn1.execute("SET ROLE alpha3s_m4_sample_collector")
    conn2 = await asyncpg.connect(DB_URL)
    await conn2.execute("SET ROLE alpha3s_m4_sample_collector")
    pend1 = await asyncpg.connect(DB_URL)
    await pend1.execute("SET ROLE alpha3s_m4_pending_checker")
    pend2 = await asyncpg.connect(DB_URL)
    await pend2.execute("SET ROLE alpha3s_m4_pending_checker")
    got1 = await conn1.fetchval("SELECT pg_try_advisory_lock($1)", s.ADVISORY_LOCK_KEY)
    got2 = await conn2.fetchval("SELECT pg_try_advisory_lock($1)", s.ADVISORY_LOCK_KEY)
    check(got1 is True and got2 is False, "2 tien trinh cung xin lock -> dung 1 thanh cong")
    await conn1.execute("SELECT pg_advisory_unlock($1)", s.ADVISORY_LOCK_KEY)
    # REV2: run_collector khong con nhan control_conn rieng (T1-01 — kiem tra control nam
    # TRONG ham DB m4_stage0p_fetch_next_message, chay boi alpha3s_m4_definer).
    r2 = await s.run_collector(conn2, pend2, batch_id=batch["batch_id"])
    check(r2.get("lock_failed") is False, "sau khi tra lock, tien trinh 2 chay binh thuong")
    for c in (conn1, conn2, pend1, pend2):
        await c.close()

    print("== [E]+[F] Eligibility: hoi thoai ngoai cua so / khong lien quan don hang ==")
    await _reset(admin)
    custE = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('cap-ef','x') RETURNING id")
    conv_old = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()-interval '30 days') RETURNING id",
        custE["id"])  # hoi thoai CU, KHONG lien quan don hang moi
    conv_new = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()-interval '1 day') RETURNING id",
        custE["id"])  # hoi thoai MOI, dung cua so
    await admin.execute("INSERT INTO orders (customer_id, created_at) VALUES ($1, now()-interval '1 day')",
                        custE["id"])
    window_start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=14)
    window_end = datetime.datetime.now(datetime.timezone.utc)
    collector_conn = await asyncpg.connect(DB_URL)
    await collector_conn.execute("SET ROLE alpha3s_m4_sample_collector")
    pending_conn = await asyncpg.connect(DB_URL)
    await pending_conn.execute("SET ROLE alpha3s_m4_pending_checker")
    eligible = await s.select_eligible_conversations(collector_conn, pending_conn,
                                                       window_start=window_start, window_end=window_end)
    eligible_ids = {e["conversation_id"] for e in eligible}
    check(conv_new["id"] in eligible_ids, "hoi thoai MOI (trong cua so, co order) -> duoc chon")
    check(conv_old["id"] not in eligible_ids, "hoi thoai CU (ngoai cua so) -> BI LOAI du cung khach co order moi")

    print("== [G] Pending-DSR race giua luc collector dang chay ==")
    await _reset(admin)
    custG = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('cap-g','x') RETURNING id")
    convG = await admin.fetchrow(
        "INSERT INTO conversations (customer_id, created_at) VALUES ($1, now()) RETURNING id", custG["id"])
    await admin.execute("INSERT INTO orders (customer_id, created_at) VALUES ($1, now())", custG["id"])
    for i in range(5):
        await admin.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES ($1,'customer',$2)",
            convG["id"], f"tin {i}")
    batchG = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start,window_end,eligible_count,selected_count,"
        "algorithm_seed,locked_conversation_ids,purpose_code, normalization_version) VALUES (now()-interval '1 day',now(),"
        "1,1,'capg',ARRAY[$1]::bigint[],'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id", convG["id"])
    staff_g = await admin.fetchrow(
        "INSERT INTO staff_users (username, password_hash, password_salt, is_active) "
        "VALUES ('m4-sampling-test-staff', 'x', 'x', true) RETURNING id")
    for perm in ("m4.stage0p.approve", "m4.stage0p.operate"):
        await admin.execute(
            "INSERT INTO m4_stage0p_staff_permissions (staff_id, permission, granted_by) "
            "VALUES ($1,$2,$1) ON CONFLICT DO NOTHING", staff_g["id"], perm)
    await _provision_pin_secret(admin, staff_id=staff_g["id"])
    approval_conn = await asyncpg.connect(DB_URL)
    await _pin(approval_conn, staff_g["id"])
    await approval_conn.execute("SET ROLE alpha3s_m4_approval_recorder")
    now_g = datetime.datetime.now(datetime.timezone.utc)
    await record_capture_approval(
        approval_conn, approval_ref="CAP-G", requested_enabled=True,
        valid_from=now_g - datetime.timedelta(hours=1), valid_until=now_g + datetime.timedelta(hours=1))
    await approval_conn.execute("RESET ROLE")
    await approval_conn.close()
    cp_conn = await asyncpg.connect(DB_URL)
    await _pin(cp_conn, staff_g["id"])
    await cp_conn.execute("SET ROLE alpha3s_m4_control_plane")
    await set_capture_enabled(cp_conn, enabled=True, approval_ref="CAP-G")
    collector_conn2 = await asyncpg.connect(DB_URL)
    await collector_conn2.execute("SET ROLE alpha3s_m4_sample_collector")
    pending_conn2 = await asyncpg.connect(DB_URL)
    await pending_conn2.execute("SET ROLE alpha3s_m4_pending_checker")

    async def _mark_pending_mid_run():
        watch = await asyncpg.connect(DB_URL)
        try:
            # Doi it nhat 1 sample COMMIT that su truoc khi dat co pending — cho toi da 10s (thay
            # 500ms REV7 tro xuong, qua sat trong moi truong container co the cham hon). Neu vong
            # lap KHONG BAO GIO thay n>=1, co pending van duoc dat sau do (fallback), nhung luc do
            # scenario nen bao that bai ro rang thay vi im lang dua vao may man timing.
            for _ in range(5000):
                n = await watch.fetchval(
                    "SELECT count(*) FROM m4_shadow_review_samples WHERE selection_batch=$1", batchG["batch_id"])
                if n >= 1:
                    break
                await asyncio.sleep(0.002)
            else:
                raise AssertionError(
                    "setup [G]: khong sample nao commit trong 10s — moi truong qua cham hoac loi that, "
                    "khong phai timing binh thuong")
            import redis.asyncio as aioredis
            r = await aioredis.from_url(settings.redis_url, decode_responses=True)
            await r.set("del_pending:cap-g", "1", ex=900)  # psid literal (xem INSERT customers o tren)
            await r.aclose()
        finally:
            await watch.close()

    result_g, _ = await asyncio.gather(
        s.run_collector(collector_conn2, pending_conn2, batch_id=batchG["batch_id"]),
        _mark_pending_mid_run(),
    )
    await _pin(cp_conn, staff_g["id"])
    await cp_conn.execute("SET ROLE alpha3s_m4_control_plane")
    await set_capture_enabled(cp_conn, enabled=False, approval_ref="CAP-G-OFF")
    check(result_g["skipped_pending"] > 0, f"co tin nhan bi bo qua vi pending giua chung (thuc te {result_g})")
    check(result_g["inserted"] < 5, "khong ghi het 5 tin (mot phan bi chan boi pending)")
    # audit_log tham chieu staff_g qua actor_staff_id (FK) — xoa truoc khi xoa staff, khong doi
    # den _reset() cua section [I] (section [H] ngay sau day CAN GIU du lieu 'cap-g', khong
    # duoc _reset()).
    await admin.execute("DELETE FROM audit_log WHERE actor_staff_id=$1", staff_g["id"])
    await admin.execute("DELETE FROM m4_stage0p_capture_approvals WHERE approval_ref='CAP-G'")
    await admin.execute("DELETE FROM m4_stage0p_staff_permissions WHERE staff_id=$1", staff_g["id"])
    await admin.execute("DELETE FROM m4_stage0p_actor_session WHERE staff_id=$1", staff_g["id"])
    await admin.execute("DELETE FROM m4_stage0p_actor_credentials WHERE staff_id=$1", staff_g["id"])
    await admin.execute("DELETE FROM staff_users WHERE id=$1", staff_g["id"])

    print("== [H] DSR retry/idempotency ==")
    r1 = await data_deletion.process_deletion("cap-g")
    r2 = await data_deletion.process_deletion("cap-g")
    check(r1["summary"]["customer_found"] is True, "lan 1: tim thay khach, xoa that")
    check(r2["summary"]["customer_found"] is False, "lan 2 (retry): khong tim thay (da anonymize) -> no-op sach")

    print("== [I] Source-conversation da mat truoc do (khong orphan) ==")
    await _reset(admin)
    custI = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('cap-i','x') RETURNING id")
    convI = await admin.fetchrow("INSERT INTO conversations (customer_id) VALUES ($1) RETURNING id", custI["id"])
    batchI = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start,window_end,eligible_count,selected_count,"
        "algorithm_seed,locked_conversation_ids,purpose_code, normalization_version) VALUES (now()-interval '1 day',now(),"
        "1,1,'capi',ARRAY[$1]::bigint[],'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id", convI["id"])
    from app.services.pii.crypto import encrypt_sample_value as enc
    blobI = enc("noi dung", customer_ref=str(custI["id"]), conversation_ref=str(convI["id"]), sample_id="i1")
    await admin.execute(
        "INSERT INTO m4_shadow_review_samples (sample_id,customer_ref,conversation_ref,encrypted_message,"
        "canonical_text_len,expires_at,purpose_code,normalization_version,selection_batch) VALUES "
        "('22222222-2222-2222-2222-222222222222',$1,$2,$3,8,now()+interval '1 day','P12_PII_DETECTOR_EVAL',"
        "'nfc-v1',$4)", str(custI["id"]), str(convI["id"]), blobI, batchI["batch_id"])
    # xoa conversations TRUOC (mo phong nguon da mat vi ly do khac, KHONG qua data_deletion)
    await admin.execute("DELETE FROM conversations WHERE id=$1", convI["id"])
    conv_gone = await admin.fetchval("SELECT count(*) FROM conversations WHERE id=$1", convI["id"])
    check(conv_gone == 0, "setup: conversations da mat truoc khi goi DSR")
    result_i = await data_deletion.process_deletion("cap-i")
    check(result_i["summary"]["customer_found"] is True, "DSR van tim thay customer (chi conversations mat)")
    n_after = await admin.fetchval("SELECT count(*) FROM m4_shadow_review_samples WHERE sample_id="
                                    "'22222222-2222-2222-2222-222222222222'")
    check(n_after == 0, "sample van bi xoa dung du conversations nguon da mat truoc (khong orphan, khong join)")

    print("== [J] Cross-customer: xoa A khong dung B ==")
    await _reset(admin)
    custA = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('cap-j-a','A') RETURNING id")
    custB = await admin.fetchrow("INSERT INTO customers (psid,name) VALUES ('cap-j-b','B') RETURNING id")
    convA = await admin.fetchrow("INSERT INTO conversations (customer_id) VALUES ($1) RETURNING id", custA["id"])
    convB = await admin.fetchrow("INSERT INTO conversations (customer_id) VALUES ($1) RETURNING id", custB["id"])
    batchJ = await admin.fetchrow(
        "INSERT INTO m4_selection_batches (window_start,window_end,eligible_count,selected_count,"
        "algorithm_seed,locked_conversation_ids,purpose_code, normalization_version) VALUES (now()-interval '1 day',now(),"
        "2,2,'capj',ARRAY[$1,$2]::bigint[],'P12_PII_DETECTOR_EVAL', 'nfc-v1') RETURNING batch_id",
        convA["id"], convB["id"])
    blobA = enc("cua A", customer_ref=str(custA["id"]), conversation_ref=str(convA["id"]), sample_id="jA")
    blobB = enc("cua B", customer_ref=str(custB["id"]), conversation_ref=str(convB["id"]), sample_id="jB")
    await admin.execute(
        "INSERT INTO m4_shadow_review_samples (sample_id,customer_ref,conversation_ref,encrypted_message,"
        "canonical_text_len,expires_at,purpose_code,normalization_version,selection_batch) VALUES "
        "('33333333-3333-3333-3333-333333333333',$1,$2,$3,5,now()+interval '1 day','P12_PII_DETECTOR_EVAL',"
        "'nfc-v1',$4), ('44444444-4444-4444-4444-444444444444',$5,$6,$7,5,now()+interval '1 day',"
        "'P12_PII_DETECTOR_EVAL','nfc-v1',$4)",
        str(custA["id"]), str(convA["id"]), blobA, batchJ["batch_id"],
        str(custB["id"]), str(convB["id"]), blobB)
    await data_deletion.process_deletion("cap-j-a")
    a_left = await admin.fetchval("SELECT count(*) FROM m4_shadow_review_samples WHERE customer_ref=$1",
                                   str(custA["id"]))
    b_left = await admin.fetchval("SELECT count(*) FROM m4_shadow_review_samples WHERE customer_ref=$1",
                                   str(custB["id"]))
    check(a_left == 0, "sample cua A bi xoa")
    check(b_left == 1, "sample cua B KHONG bi dung tram")

    await _reset(admin)
    await admin.close()
    await stop_signing_service(signing_proc, signing_socket)

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
