"""CA Directive 345 — tool van hanh chuan bi G1 (GHN staging master-data + carrier_address_map). KHONG runtime.

Mac dinh DRY-RUN: khong goi mang, khong ghi DB, khong giai ma token. Chi thuc thi khi co --execute (va CHI trong
operational closure CA cho phep). Khong bao gio in/log token.

  python scripts/ghn_g1_prep.py plan
  python scripts/ghn_g1_prep.py snapshot --target "Gia Lai=Pleiku" --target "Đắk Lắk=Krông Pắc" [--cap 10] [--execute --actor X]
  python scripts/ghn_g1_prep.py build-map [--address 66/24490 ...] [--execute --actor X]
  python scripts/ghn_g1_prep.py import-map --file rows.json --source-note "portal GHN staging 22/09" [--execute --actor X]

Chay tren VPS: docker compose -f docker-compose.prod.yml exec -T api python scripts/ghn_g1_prep.py ...
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone

import asyncpg

from app.config import settings
from app.services.providers import ghn_master_data as md


def _p(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


async def _addresses(conn, explicit: list[str] | None) -> list[tuple[str, str]]:
    """--address PC/WC hoac mac dinh: dia chi cua tester M7 (allowlist) — chi dia chi DI GHN (bo self-zone)."""
    from app.services.fulfillment import m7_scope
    if explicit:
        out = []
        for a in explicit:
            pc, _, wc = a.partition("/")
            if not pc or not wc:
                raise SystemExit(f"--address sai dinh dang PC/WC: {a}")
            out.append((pc.strip(), wc.strip()))
        return out
    ids = sorted(m7_scope.tester_ids())
    if not ids:
        raise SystemExit("khong co tester id (m7_tester_customer_ids) — dung --address")
    rows = await conn.fetch(
        "SELECT DISTINCT s.province_code, s.ward_code FROM order_address_snapshot s JOIN orders o ON o.id=s.order_id "
        "WHERE o.customer_id = ANY($1::bigint[]) ORDER BY 1,2", ids)
    out = []
    for r in rows:
        if not await md._is_self_zone(conn, r["province_code"], r["ward_code"]):
            out.append((r["province_code"], r["ward_code"]))
    return out


async def cmd_plan(conn, a) -> int:
    ds = await md._active_dataset(conn)
    addrs = await _addresses(conn, a.address)
    res = []
    for pc, wc in addrs:
        au = await md._admin_ward(conn, ds, pc, wc) if ds else None
        res.append({"address": f"{pc}/{wc}", "ward": au and au["ward_name"], "province": au and au["province_name"],
                    "legacy_aliases": au and au["aliases"]})
    _p({"dataset": ds, "ghn_addresses": res, "note": "plan: KHONG network, KHONG ghi DB"})
    return 0


async def cmd_snapshot(conn, a) -> int:
    targets = md.parse_targets(a.target)
    need = md.planned_requests(targets)
    plan = {"targets": targets, "planned_requests": need, "cap": a.cap,
            "endpoints": sorted(md.ALLOWED_PATHS), "execute": bool(a.execute)}
    if need > a.cap:
        _p({**plan, "result": "REFUSED: planned > cap"})
        return 2
    if not a.execute:
        _p({**plan, "result": "DRY-RUN — khong goi mang, khong doc token, khong ghi DB"})
        return 0
    if not a.actor:
        raise SystemExit("--execute can --actor")
    if not settings.settings_integrations_enabled:
        raise SystemExit("settings_integrations_enabled=OFF — khong co cau hinh Dashboard, dung")
    from app.services.providers import ghn as _ghn
    from app.services.settings import integrations as S
    saved = await S.load_saved_ghn_config(conn)   # thieu/decrypt loi -> raise (fail-closed); KHONG enable
    cp = saved["config"]
    cfg = {"base": (cp.get("base_url") or _ghn.STAGING_BASE).rstrip("/"), "token": saved["token"],
           "shop_id": str(cp.get("shop_id") or ""), "timeout": float(cp.get("timeout_seconds") or 8.0), "retries": 0}
    if cfg["base"] != _ghn.STAGING_BASE:
        raise SystemExit("base_url khong phai staging — dung")
    ver = a.snapshot_version or ("ghn-g1-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    result = await md.fetch_scoped(cfg, targets, post=_ghn._post, cap=a.cap)
    del cfg, saved
    async with conn.transaction():
        counts = await md.persist_snapshot(conn, result, snapshot_version=ver, targets=targets, actor=a.actor,
                                           cap=a.cap)
    _p({**plan, "snapshot_version": ver, "status": result["status"], "reason": result["reason"],
        "request_count": len(result["calls"]), "requests": result["calls"], "report": result["report"],
        "persisted": counts})
    return 0 if result["status"] == "completed" else 2


async def cmd_build_map(conn, a) -> int:
    addrs = await _addresses(conn, a.address)
    rows, report = await md.build_map_rows(conn, addrs)
    snap = await conn.fetchval("SELECT snapshot_version FROM carrier_master_snapshot WHERE provider='ghn' AND "
                               "status='completed' ORDER BY id DESC LIMIT 1")
    out = {"source_snapshot": snap, "report": report, "rows": rows, "execute": bool(a.execute)}
    if not a.execute:
        _p({**out, "result": "DRY-RUN — khong ghi DB"})
        return 0
    if not a.actor:
        raise SystemExit("--execute can --actor")
    if not rows:
        raise SystemExit("khong co dong nao de ghi")
    async with conn.transaction():
        ver = await md.write_map_version(conn, rows, actor=a.actor, source=f"snapshot:{snap}")
    _p({**out, "map_version": ver, "note": "Cap nhat Dashboard GHN 'Map version' = map_version neu khac."})
    return 0


async def cmd_import_map(conn, a) -> int:
    with open(a.file, encoding="utf-8") as fh:
        items = json.load(fh)
    staff_rows = await md.validate_manual_rows(conn, items, source_note=a.source_note)
    base_ver, base_rows = await md.latest_map_rows(conn) if a.base == "latest" else (None, [])
    rows = md.apply_overrides(base_rows, staff_rows)
    out = {"base_version": base_ver, "staff_rows": staff_rows, "total_rows": len(rows), "execute": bool(a.execute)}
    if not a.execute:
        _p({**out, "result": "DRY-RUN — khong ghi DB"})
        return 0
    if not a.actor:
        raise SystemExit("--execute can --actor")
    async with conn.transaction():
        ver = await md.write_map_version(conn, rows, actor=a.actor, source=f"manual:{a.source_note}")
    _p({**out, "map_version": ver, "note": "Cap nhat Dashboard GHN 'Map version' = map_version neu khac."})
    return 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "snapshot", "build-map", "import-map"):
        s = sub.add_parser(name)
        s.add_argument("--execute", action="store_true", help="thuc thi that (mac dinh dry-run)")
        s.add_argument("--actor", help="nguoi thuc hien (bat buoc khi --execute)")
        if name in ("plan", "build-map"):
            s.add_argument("--address", action="append", help="PC/WC (lap lai); mac dinh = dia chi tester di GHN")
        if name == "snapshot":
            s.add_argument("--target", action="append", required=True, help='"Tinh=Quan|Quan"')
            s.add_argument("--cap", type=int, default=md.DEFAULT_CAP)
            s.add_argument("--snapshot-version")
        if name == "import-map":
            s.add_argument("--file", required=True)
            s.add_argument("--source-note", required=True)
            s.add_argument("--base", choices=("latest", "empty"), default="latest")
    return ap


async def main(argv=None) -> int:
    a = _parser().parse_args(argv)
    if getattr(a, "cap", 1) is not None and getattr(a, "cap", 1) <= 0:
        raise SystemExit("--cap phai > 0")
    conn = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        fn = {"plan": cmd_plan, "snapshot": cmd_snapshot, "build-map": cmd_build_map, "import-map": cmd_import_map}
        return await fn[a.cmd](conn, a)
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
