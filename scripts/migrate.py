#!/usr/bin/env python3
"""Alpha3S lightweight migration runner (I-B Milestone 0) — hardened v2.

Lenh:
  status                          — liet ke applied/pending + canh bao checksum drift
  up [--manifest P]               — ap pending theo thu tu; SAU do chay post-migration
                                    validations (fail-closed). Exit != 0 neu apply/validate loi.
  baseline [--manifest P]         — ghi cac version <= manifest.baseline_through la applied
                                    (KHONG chay), CHI sau khi verify TOAN BO manifest.
  validate [--manifest P]         — chi chay post-migration validations (operational, khong ap gi).
  fresh-validate [--manifest P]   — chi chay FRESH-INSTALL-ONLY validations (manifest.fresh_install_validations);
                                    goi TUONG MINH o fresh-DB bootstrap/test. KHONG nam trong `up` deploy path.

Safety (theo CA-REVIEW-M0-DEV-001):
- §4 baseline KHONG nhan threshold tuy y: chi baseline toi `manifest.baseline_through`; version trong
  `never_baseline` KHONG bao gio duoc baseline; corrective (014) luon > threshold nen phai CHAY that.
  Baseline chay checksum-drift check truoc, va insert trong MOT transaction (atomic).
- §5 manifest enforcement DAY DU: expected_tables, expected_columns, expected_constraints,
  expected_indexes, prebaseline_data_assertions — moi cai fail-closed. Khong field mo ta bi bo qua.
- §7 validation duoc noi vao runner: `up` tu chay `post_migration_validations`; loi -> exit != 0
  (one-shot migrate service dua vao exit code nay -> API/worker phu thuoc service_completed_successfully).
- §9 advisory lock: pg_try_advisory_lock = FAIL-FAST (khong cho lock). Da chon fail-fast cho M0.

DATABASE_URL tu env. KHONG dung cho production khi chua co PO gates + CA release approval.
"""
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"
DEFAULT_MANIFEST = ROOT / "scripts" / "baseline_manifest.json"
LOCK_KEY = 4013001  # namespace co dinh cho Alpha3S migration


def db_url() -> str:
    url = os.environ.get("DATABASE_URL") or "postgresql://alpha3s:alpha3s@db:5432/alpha3s"
    return url.replace("+asyncpg", "")


def _num(version: str) -> int:
    return int(version.split("_", 1)[0])


def _arg_manifest() -> Path:
    if "--manifest" in sys.argv:
        return Path(sys.argv[sys.argv.index("--manifest") + 1])
    return DEFAULT_MANIFEST


def load_manifest(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"STOP: manifest khong ton tai: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def discover() -> list[dict]:
    out = []
    for f in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql")):
        text = f.read_text(encoding="utf-8")
        transactional = True
        for line in text.splitlines()[:25]:
            low = line.strip().lower()
            if low.startswith("-- transactional:"):
                transactional = "false" not in low
                break
        out.append({
            "version": f.stem,
            "text": text,
            "checksum": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "transactional": transactional,
        })
    return out


async def ensure_table(conn) -> None:
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
             version TEXT PRIMARY KEY,
             checksum TEXT NOT NULL,
             applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
             applied_by TEXT,
             transactional BOOLEAN NOT NULL DEFAULT true
           )"""
    )


async def applied_map(conn) -> dict:
    rows = await conn.fetch("SELECT version, checksum FROM schema_migrations")
    return {r["version"]: r["checksum"] for r in rows}


async def _drift_stop(conn, migs) -> None:
    applied = await applied_map(conn)
    for m in migs:
        if m["version"] in applied and applied[m["version"]] != m["checksum"]:
            raise SystemExit(
                f"STOP: checksum drift tren migration da applied '{m['version']}' "
                f"(file bi sua sau khi apply). Forward-only — sua bang migration moi."
            )


# ---- Manifest enforcement day du (CA §5) ------------------------------------

async def verify_manifest(conn, manifest: dict) -> list[str]:
    missing = []
    for t in manifest.get("expected_tables", []):
        if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{t}"):
            missing.append(f"table {t}")
    for col in manifest.get("expected_columns", []):
        tbl, c = col.split(".")
        if not await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name=$1 AND column_name=$2)", tbl, c):
            missing.append(f"column {col}")
    for con in manifest.get("expected_constraints", []):
        if not await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE conname=$1)", con):
            missing.append(f"constraint {con}")
    for idx in manifest.get("expected_indexes", []):
        if not await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=$1)", idx):
            missing.append(f"index {idx}")
    for a in manifest.get("prebaseline_data_assertions", []):
        try:
            val = await conn.fetchval(a["sql"])
        except Exception as e:  # noqa: BLE001
            missing.append(f"data_assertion '{a.get('name')}' loi: {e}")
            continue
        if val != a.get("expect", True):
            missing.append(f"data_assertion '{a.get('name')}' = {val} (expect {a.get('expect', True)})")
    return missing


async def run_post_validations(conn, manifest: dict) -> None:
    """Chay tung file trong post_migration_validations (DO block RAISE EXCEPTION khi fail).
    Loi -> raise SystemExit (exit != 0). §7."""
    files = manifest.get("post_migration_validations", [])
    for rel in files:
        p = ROOT / rel
        if not p.exists():
            raise SystemExit(f"STOP: post-migration validation khong ton tai: {rel}")
        sql = p.read_text(encoding="utf-8")
        try:
            await conn.execute(sql)
        except asyncpg.PostgresError as e:
            raise SystemExit(f"VALIDATION FAIL ({rel}): {e}")
        print(f"  validation OK: {rel}")
    if files:
        print(f"Post-migration validations pass ({len(files)} file).")


async def run_fresh_validations(conn, manifest: dict) -> None:
    """Chay FRESH-INSTALL-ONLY validations (manifest.fresh_install_validations) — exact canonical seed.
    CHI goi tuong minh qua `fresh-validate`; KHONG chay trong `up` deploy path (CA F-R1-01 §4.2).
    Loi -> raise SystemExit (exit != 0)."""
    files = manifest.get("fresh_install_validations", [])
    for rel in files:
        p = ROOT / rel
        if not p.exists():
            raise SystemExit(f"STOP: fresh-install validation khong ton tai: {rel}")
        sql = p.read_text(encoding="utf-8")
        try:
            await conn.execute(sql)
        except asyncpg.PostgresError as e:
            raise SystemExit(f"FRESH VALIDATION FAIL ({rel}): {e}")
        print(f"  fresh validation OK: {rel}")
    if files:
        print(f"Fresh-install validations pass ({len(files)} file).")


# ---- Commands ---------------------------------------------------------------

async def cmd_status(conn, migs) -> None:
    await ensure_table(conn)
    applied = await applied_map(conn)
    print(f"{'VERSION':40} STATE")
    for m in migs:
        v = m["version"]
        if v in applied:
            state = "applied" if applied[v] == m["checksum"] else "APPLIED (CHECKSUM DRIFT!)"
        else:
            state = "PENDING"
        print(f"{v:40} {state}")


async def cmd_up(conn, migs, manifest, actor) -> None:
    await ensure_table(conn)
    await _drift_stop(conn, migs)
    applied = await applied_map(conn)
    pending = [m for m in migs if m["version"] not in applied]
    for m in pending:
        print(f"Applying {m['version']} (transactional={m['transactional']}) ...")
        if m["transactional"]:
            async with conn.transaction():
                await conn.execute(m["text"])  # DO-block pre/postcondition RAISE -> rollback here
                await conn.execute(
                    "INSERT INTO schema_migrations(version,checksum,applied_by,transactional) "
                    "VALUES($1,$2,$3,$4)", m["version"], m["checksum"], actor, m["transactional"])
        else:
            await conn.execute(m["text"])
            await conn.execute(
                "INSERT INTO schema_migrations(version,checksum,applied_by,transactional) "
                "VALUES($1,$2,$3,$4)", m["version"], m["checksum"], actor, m["transactional"])
        print(f"  OK {m['version']}")
    print(f"Applied {len(pending)} migration(s)." if pending else "Khong co migration pending.")
    # §7: LUON validate sau up (ke ca khi khong co pending) -> exit code phan anh trang thai
    await run_post_validations(conn, manifest)


async def cmd_validate(conn, manifest) -> None:
    await run_post_validations(conn, manifest)


async def cmd_fresh_validate(conn, manifest) -> None:
    await run_fresh_validations(conn, manifest)


async def cmd_baseline(conn, migs, manifest, actor) -> None:
    await ensure_table(conn)
    await _drift_stop(conn, migs)  # §4.5 drift check truoc baseline
    through = manifest.get("baseline_through")
    if through is None:
        raise SystemExit("STOP: manifest thieu 'baseline_through'.")
    never = set(manifest.get("never_baseline", []))
    missing = await verify_manifest(conn, manifest)
    if missing:
        raise SystemExit(
            "STOP: baseline manifest verify FAIL — thieu/không đạt:\n  - "
            + "\n  - ".join(missing) + "\nKhong baseline mu (CA §5)."
        )
    applied = await applied_map(conn)
    target = [m for m in migs
              if _num(m["version"]) <= through
              and m["version"] not in applied
              and m["version"] not in never]
    # §4.6 atomic: tat ca insert trong 1 transaction
    async with conn.transaction():
        for m in target:
            await conn.execute(
                "INSERT INTO schema_migrations(version,checksum,applied_by,transactional) "
                "VALUES($1,$2,$3,$4) ON CONFLICT (version) DO NOTHING",
                m["version"], m["checksum"], f"baseline:{actor}", m["transactional"])
            print(f"  baselined {m['version']}")
    skipped = [m["version"] for m in migs if _num(m["version"]) > through]
    print(f"Baselined {len(target)} migration(s) through {through} (manifest). "
          f"KHONG baseline (phai chay): {', '.join(skipped) or '(none)'}")


_ACTOR_RE = re.compile(r"^[a-z][a-z0-9-]{2,31}$")
# Cac lenh GHI vao `schema_migrations` — chi nhung lenh nay moi can actor.
_LENH_GHI_LEDGER = ("up", "baseline")


def _resolve_actor(cmd: str) -> str:
    """F-MIG-02: KHONG con mac dinh am tham.

    Truoc day dong nay la `os.environ.get("MIGRATE_ACTOR", "rehearsal")`. Mac dinh do la di san tu
    thoi runner chi duoc goi TAY trong rehearsal. Sau F-PR24-01, runner nam trong deploy path, nen
    moi migration ap qua deploy bi ghi `applied_by='rehearsal'` — sai ve truy nguyen audit. Hang
    044 tren production da bi ghi nhu vay (xem evidence PR #25); hang do KHONG duoc sua hoi to.

    Thiet ke moi: **khong co mac dinh nao ca**. Lenh nao ghi ledger thi PHAI co `MIGRATE_ACTOR`
    tuong minh, va gia tri phai hop dang. `deploy.sh`/compose dat `deploy-pipeline`; nguoi chay tay
    phai tu khai minh la ai (`rehearsal`, `operator-hoai`, ...). Nhu vay khong con duong nao de mot
    nhan sai lot vao bang audit ma khong ai chon no.

    Lenh chi doc (`status`/`validate`/`fresh-validate`) khong ghi ledger nen khong doi actor.
    """
    raw = os.environ.get("MIGRATE_ACTOR")
    if cmd not in _LENH_GHI_LEDGER:
        return raw or ""
    if not raw:
        raise SystemExit(
            "STOP (F-MIG-02): thieu MIGRATE_ACTOR. Lenh nay ghi vao schema_migrations nen PHAI khai "
            "ro ai ap migration. Deploy path dat 'deploy-pipeline'; chay tay thi dat vd "
            "MIGRATE_ACTOR=rehearsal hoac MIGRATE_ACTOR=operator-<ten>.")
    if not _ACTOR_RE.match(raw):
        raise SystemExit(
            f"STOP (F-MIG-02): MIGRATE_ACTOR={raw!r} khong hop dang. Yeu cau: chu thuong/so/gach "
            "ngang, bat dau bang chu, dai 3-32 ky tu.")
    return raw


async def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    actor = _resolve_actor(cmd)
    manifest = load_manifest(_arg_manifest()) if cmd in ("up", "baseline", "validate", "fresh-validate") else {}
    conn = await asyncpg.connect(db_url())
    try:
        if not await conn.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY):
            raise SystemExit("STOP: mot process migration khac dang giu advisory lock (fail-fast).")
        try:
            migs = discover()
            if cmd == "status":
                await cmd_status(conn, migs)
            elif cmd == "up":
                await cmd_up(conn, migs, manifest, actor)
            elif cmd == "validate":
                await cmd_validate(conn, manifest)
            elif cmd == "fresh-validate":
                await cmd_fresh_validate(conn, manifest)
            elif cmd == "baseline":
                await cmd_baseline(conn, migs, manifest, actor)
            else:
                raise SystemExit(f"Lenh khong hop le: {cmd}")
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
