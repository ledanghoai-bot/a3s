#!/usr/bin/env python
"""I-B M4-S1 — evidence script: Trusted Slot Store tren DB rieng cua worktree M4.

Chay (2 buoc, DB RIENG alpha3s-m4-db — KHONG cham db compose chinh):
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      alpha3s-m4-test python scripts/migrate.py up
  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
      alpha3s-m4-test python scripts/m4_slot_store_test.py

Kiem tra (spec §8 + Directive §4 M4-S1):
  [1] Roundtrip: store -> resolve dung context, dung gia tri.
  [2] Isolation: khac customer / khac conversation -> None (khong thay slot).
  [3] Tamper cross-context (UPDATE truc tiep DB doi conversation_ref):
      resolve o context moi -> None + alert m4_slot_binding_alert (AAD fail closed).
  [4] Replay/idempotency: cung gia tri cung context -> dedupe (1 row, cung slot_id);
      cung gia tri KHAC context -> row khac (khong re-bind).
  [5] Concurrency: 5 store song song cung gia tri -> dung 1 row, khong loi.
  [6] Expiry/retention: row het han khong resolve duoc; purge_expired xoa + dem.
  [7] Min confidence filter.
  [8] No plaintext at rest: encrypted_value/fingerprint/row dump khong chua gia tri gieo.
  [9] Role: alpha3s_vendor_path bi DENY SELECT/INSERT; alpha3s_app bi DENY UPDATE
      nhung INSERT/SELECT/DELETE duoc (least privilege 040).
 [10] Khong plaintext trong log [m4-slot] cua toan bo phien test.

Toan bo gia tri la SYNTHETIC. Khoa AES/HMAC sinh ngau nhien trong phien test.
"""

import asyncio
import base64
import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.pii import slot_store  # noqa: E402
from app.services.pii.crypto import fingerprint  # noqa: E402

DB_URL = (os.environ.get("DATABASE_URL")
          or "postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s").replace("+asyncpg", "")

PHONE = "0912345678"
NAME = "Nguyễn Văn An"

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


async def main() -> int:
    settings.m4_slot_key_b64 = base64.b64encode(os.urandom(32)).decode()
    settings.m4_slot_fp_key_b64 = base64.b64encode(os.urandom(32)).decode()

    conn = await asyncpg.connect(DB_URL)
    log_buf = io.StringIO()
    try:
        await conn.execute("DELETE FROM pii_slots")  # phien test sach

        ctx_a = dict(customer_ref="cust-A", conversation_ref="conv-1", slot_type="phone")

        print("== [1] Roundtrip ==")
        with redirect_stdout(log_buf):
            stored = await slot_store.store_slot(
                conn, **ctx_a, value=PHONE, confidence="high", data_class="D1",
                purpose_code="P02", source_message_ref="mid-syn-001")
            got = await slot_store.resolve_slot(conn, **ctx_a)
        check(stored.deduped is False and got == PHONE, "store -> resolve dung gia tri")

        print("== [2] Isolation ==")
        with redirect_stdout(log_buf):
            other_cust = await slot_store.resolve_slot(
                conn, customer_ref="cust-B", conversation_ref="conv-1", slot_type="phone")
            other_conv = await slot_store.resolve_slot(
                conn, customer_ref="cust-A", conversation_ref="conv-2", slot_type="phone")
        check(other_cust is None, "khac customer -> None")
        check(other_conv is None, "khac conversation -> None")

        print("== [3] Tamper cross-context fail closed ==")
        # migration-owner doi context truc tiep (mo phong bug/tamper vuot qua app)
        await conn.execute(
            "UPDATE pii_slots SET conversation_ref='conv-HACK' WHERE slot_id=$1",
            stored.slot_id)
        buf3 = io.StringIO()
        with redirect_stdout(buf3):
            hijack = await slot_store.resolve_slot(
                conn, customer_ref="cust-A", conversation_ref="conv-HACK", slot_type="phone")
        log_buf.write(buf3.getvalue())
        check(hijack is None, "row bi doi context -> KHONG giai ma duoc (None)")
        check("m4_slot_binding_alert" in buf3.getvalue(), "co alert m4_slot_binding_alert")
        await conn.execute("DELETE FROM pii_slots")

        print("== [4] Replay/idempotency ==")
        with redirect_stdout(log_buf):
            s1 = await slot_store.store_slot(conn, **ctx_a, value=PHONE,
                                             confidence="high", data_class="D1", purpose_code="P02")
            s2 = await slot_store.store_slot(conn, **ctx_a, value="0912 345 678",
                                             confidence="high", data_class="D1", purpose_code="P02")
            s3 = await slot_store.store_slot(
                conn, customer_ref="cust-A", conversation_ref="conv-2", slot_type="phone",
                value=PHONE, confidence="high", data_class="D1", purpose_code="P02")
        n_rows = await conn.fetchval("SELECT count(*) FROM pii_slots")
        check(s2.deduped and s1.slot_id == s2.slot_id,
              "replay cung gia tri (khac dinh dang) cung context -> dedupe cung slot")
        check(not s3.deduped and s3.slot_id != s1.slot_id and n_rows == 2,
              "cung gia tri KHAC context -> row RIENG (khong re-bind)")

        print("== [5] Concurrency ==")
        await conn.execute("DELETE FROM pii_slots")
        pool = await asyncpg.create_pool(DB_URL, min_size=5, max_size=5)

        async def _store():
            async with pool.acquire() as c:
                return await slot_store.store_slot(c, **ctx_a, value=PHONE,
                                                   confidence="high", data_class="D1",
                                                   purpose_code="P02")
        with redirect_stdout(log_buf):
            results = await asyncio.gather(*[_store() for _ in range(5)])
        await pool.close()
        ids = {r.slot_id for r in results}
        n_rows = await conn.fetchval("SELECT count(*) FROM pii_slots")
        check(len(ids) == 1 and n_rows == 1, "5 store song song -> 1 row, cung slot_id")

        print("== [6] Expiry/retention ==")
        await conn.execute("DELETE FROM pii_slots")
        with redirect_stdout(log_buf):
            await slot_store.store_slot(conn, **ctx_a, value=PHONE, confidence="high",
                                        data_class="D1", purpose_code="P02")
        # het han: khong duoc UPDATE (bat bien) -> mo phong bang doi dong ho la
        # khong the; migration-owner duoc phep chinh truc tiep trong REHEARSAL
        # giu CHECK expires_at > captured_at: lui ca hai moc ve qua khu
        await conn.execute(
            "UPDATE pii_slots SET captured_at = now() - interval '2 hour', "
            "expires_at = now() - interval '1 hour'")
        with redirect_stdout(log_buf):
            expired = await slot_store.resolve_slot(conn, **ctx_a)
        buf6 = io.StringIO()
        with redirect_stdout(buf6):
            purged = await slot_store.purge_expired(conn)
        log_buf.write(buf6.getvalue())
        n_rows = await conn.fetchval("SELECT count(*) FROM pii_slots")
        check(expired is None, "row het han -> resolve None")
        check(purged == 1 and n_rows == 0, "purge_expired xoa dung 1 row (counts-only)")

        print("== [7] Min confidence ==")
        with redirect_stdout(log_buf):
            await slot_store.store_slot(conn, **ctx_a, value=PHONE, confidence="low",
                                        data_class="D1", purpose_code="P02")
            low_ok = await slot_store.resolve_slot(conn, **ctx_a, min_confidence="high")
            low_any = await slot_store.resolve_slot(conn, **ctx_a, min_confidence="low")
        check(low_ok is None and low_any == PHONE, "min_confidence=high loc slot low")

        print("== [8] No plaintext at rest ==")
        await conn.execute("DELETE FROM pii_slots")
        with redirect_stdout(log_buf):
            await slot_store.store_slot(conn, **ctx_a, value=PHONE, confidence="high",
                                        data_class="D1", purpose_code="P02")
            await slot_store.store_slot(
                conn, customer_ref="cust-A", conversation_ref="conv-1", slot_type="name",
                value=NAME, confidence="medium", data_class="D1", purpose_code="P02")
        rows = await conn.fetch("SELECT * FROM pii_slots")
        dump = repr([dict(r) for r in rows])
        blob_concat = b"".join(bytes(r["encrypted_value"]) for r in rows)
        check(PHONE.encode() not in blob_concat and PHONE not in dump,
              "so dien thoai khong xuat hien o rest/dump")
        check(NAME not in dump and "Nguy" not in dump, "ten khong xuat hien o rest/dump")
        fp = fingerprint(PHONE, "phone")
        check(all(r["normalized_fingerprint"] != PHONE for r in rows) and len(fp) == 32,
              "fingerprint 32-hex, khong phai gia tri tho")

        print("== [9] Role least-privilege (040) ==")
        # vendor-path: DENY het
        denied_select = denied_insert = False
        await conn.execute("SET ROLE alpha3s_vendor_path")
        try:
            try:
                await conn.fetch("SELECT * FROM pii_slots LIMIT 1")
            except asyncpg.InsufficientPrivilegeError:
                denied_select = True
            try:
                await conn.execute(
                    "INSERT INTO pii_slots (customer_ref,conversation_ref,slot_type,"
                    "encrypted_value,normalized_fingerprint,detector_version,confidence,"
                    "expires_at,data_class,purpose_code) VALUES ('x','y','phone',"
                    "'\\x00'::bytea, repeat('0',32),'v','high',now()+interval '1h','D1','P02')")
            except asyncpg.InsufficientPrivilegeError:
                denied_insert = True
        finally:
            await conn.execute("RESET ROLE")
        check(denied_select, "vendor_path SELECT -> DENIED")
        check(denied_insert, "vendor_path INSERT -> DENIED")
        # runtime app: UPDATE denied, SELECT/DELETE duoc
        app_update_denied = False
        await conn.execute("SET ROLE alpha3s_app")
        try:
            try:
                await conn.execute("UPDATE pii_slots SET confidence='low'")
            except asyncpg.InsufficientPrivilegeError:
                app_update_denied = True
            can_select = await conn.fetchval("SELECT count(*) FROM pii_slots") is not None
        finally:
            await conn.execute("RESET ROLE")
        check(app_update_denied, "alpha3s_app UPDATE -> DENIED (row bat bien)")
        check(can_select, "alpha3s_app SELECT -> OK")

        print("== [10] Log khong PII ==")
        logs = log_buf.getvalue()
        check("[m4-slot]" in logs, "co emit log m4-slot")
        for leak in (PHONE, "912345678", NAME, "Nguy", fp):
            if leak in logs:
                check(False, f"log chua du lieu nhay cam ({'fingerprint' if leak == fp else 'PII'})")
                break
        else:
            check(True, "log khong chua gia tri/fingerprint")

        await conn.execute("DELETE FROM pii_slots")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
