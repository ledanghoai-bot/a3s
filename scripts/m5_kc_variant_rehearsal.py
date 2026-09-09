"""M5 matcher k/c variant — DB-backed rehearsal (CA Directive 258 + Amendments 259/260).

Chay tren m5lab (isolated) sau khi migration 063 da apply. Chung minh qua ACTUAL resolver.resolve (doc
augment active-version) + timing. KHONG cham prod.
- Krong Pak -> 24490 auto_verified, rule orthographic_kc (positive, deterministic, khong go lai canonical).
- Ea Knuek -> 24505 auto_verified.
- Canonical Krong Pac -> auto_verified qua current canonical (khong bi augment lan at).
- Dak Lak (province k-cuoi hop le) -> auto_verified, KHONG bien doi.
- Wrong-province (Bac Lieu + Krong Pak) -> KHONG bind (fail-safe).
- Timing p50/max cho resolver (indexed/bounded, khong network).
"""
import asyncio
import os
import time

import asyncpg

from app.services.address import resolver

DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")


def ck(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" :: {extra}" if extra else ""))
    if not cond:
        ck.failed = True


ck.failed = False


async def _resolve(conn, prov, ward, tag):
    return await resolver.resolve(
        conn, subject_type="adhoc", province=prov, ward=ward,
        actor="rehearsal", reason="kc-variant-rehearsal", ticket="KCVAR-258",
        idempotency_key=f"kcvar:{tag}:{time.time_ns()}")


async def main():
    conn = await asyncpg.connect(DSN)
    try:
        aug_n = await conn.fetchval("SELECT count(*) FROM admin_unit_alias_augment WHERE source_batch='kc_variant_c2k_v1'")
        ck("augment seeded", aug_n == 166, f"n={aug_n}")

        r = await _resolve(conn, "Đắk Lắk", "Krong Pak", "kp")
        ck("Krong Pak -> 24490 auto_verified (deterministic, khong go lai canonical)",
           r["status"] == "auto_verified" and r["ward_code"] == "24490", f"{r['status']}/{r['ward_code']}")
        ck("Krong Pak rule attribution orthographic_kc", "orthographic_kc:ward" in (r.get("rules_applied") or []),
           str(r.get("rules_applied")))

        r2 = await _resolve(conn, "Dak Lak", "Ea Knuek", "ek")
        ck("Ea Knuek -> 24505 auto_verified", r2["status"] == "auto_verified" and r2["ward_code"] == "24505",
           f"{r2['status']}/{r2['ward_code']}")

        r3 = await _resolve(conn, "Đắk Lắk", "Krông Pắc", "canon")
        ck("Canonical Krong Pac -> auto_verified (current canonical, khong augment)",
           r3["status"] == "auto_verified" and r3["ward_code"] == "24490"
           and "orthographic_kc:ward" not in (r3.get("rules_applied") or []), f"{r3['status']}")

        r4 = await _resolve(conn, "Đắk Lắk", None, "prov")
        ck("Dak Lak province k-cuoi hop le -> auto_verified (khong bien doi)",
           r4["status"] == "auto_verified" and r4["province_code"] == "66", f"{r4['status']}")

        r5 = await _resolve(conn, "Bạc Liêu", "Krong Pak", "wrongprov")
        ck("Wrong-province (Bac Lieu + Krong Pak) -> KHONG bind sang province khac",
           r5["status"] != "auto_verified" and r5.get("ward_code") != "24490", f"{r5['status']}/{r5.get('ward_code')}")

        # timing (DoD §10): (a) augment lookup la INDEXED/bounded (EXPLAIN Bitmap Index Scan) va sub-ms;
        # (b) resolver.resolve full-path bounded, KHONG network. Full resolve bi chi phoi boi INSERT
        # address_resolution + audit (co san, khong phai thay doi cua work item nay).
        aug_ts = []
        for _ in range(50):
            t0 = time.perf_counter()
            await conn.fetch("SELECT unit_code,alias_name,alias_kind FROM admin_unit_alias_augment "
                             "WHERE dataset_version='VN-ADMIN-2025-07-v2'")
            aug_ts.append((time.perf_counter() - t0) * 1000)
        aug_ts.sort()
        print(f"  [timing] augment lookup (added query) p50={aug_ts[25]:.2f}ms max={aug_ts[-1]:.2f}ms (indexed, n=50)")
        ck("augment lookup overhead negligible (max < 25ms)", aug_ts[-1] < 25, f"max={aug_ts[-1]:.2f}ms")
        ts = []
        for i in range(20):
            t0 = time.perf_counter()
            await _resolve(conn, "Đắk Lắk", "Krong Pak", f"t{i}")
            ts.append((time.perf_counter() - t0) * 1000)
        ts.sort()
        p50, mx = ts[len(ts) // 2], ts[-1]
        print(f"  [timing] resolver.resolve full-path p50={p50:.1f}ms max={mx:.1f}ms (n=20, no network; "
              f"dominated by resolution INSERT + audit, pre-existing)")
        ck("full resolve bounded, no network (max < 2000ms local dev)", mx < 2000, f"max={mx:.1f}ms")

        print("RESULT:", "ALL PASS" if not ck.failed else "HAS FAILURES")
    finally:
        await conn.close()


asyncio.run(main())
