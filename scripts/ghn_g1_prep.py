"""CA Directive 345 — tool van hanh chuan bi G1 (GHN staging master-data + carrier_address_map). KHONG runtime.

Mac dinh DRY-RUN: khong goi mang, khong ghi DB, khong giai ma token. Chi thuc thi khi co --execute (va CHI trong
operational closure CA cho phep). Khong bao gio in/log token.

MOI lenh PHAI chi dinh --mode staging|production (CA 357 §2.3.1); mode + endpoint duoc in ra truoc khi chay.

  python scripts/ghn_g1_prep.py plan --mode staging
  python scripts/ghn_g1_prep.py snapshot --mode production --target "Gia Lai=Pleiku" [--cap 10] [--execute --actor X]
  python scripts/ghn_g1_prep.py build-map --mode production [--address 66/24490 ...] [--execute --actor X]
  python scripts/ghn_g1_prep.py import-map --mode production --file rows.json --source-note "portal ..." [--execute --actor X]
  python scripts/ghn_g1_prep.py compare-modes --mode production [--base-mode staging]   (doi chieu, khong network)

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


def _mode_banner(a) -> dict:
    """In mode + endpoint (redacted) TRUOC khi chay — CA 357 §2.3.1."""
    from app.services.providers import ghn as _ghn
    md.check_mode(a.mode)
    return {"mode": a.mode, "endpoint_base": _ghn.BASE_BY_MODE[a.mode], "execute": bool(getattr(a, "execute", False))}


async def cmd_plan(conn, a) -> int:
    ds = await md._active_dataset(conn)
    addrs = await _addresses(conn, a.address)
    res = []
    for pc, wc in addrs:
        au = await md._admin_ward(conn, ds, pc, wc) if ds else None
        res.append({"address": f"{pc}/{wc}", "ward": au and au["ward_name"], "province": au and au["province_name"],
                    "legacy_aliases": au and au["aliases"]})
    _p({**_mode_banner(a), "dataset": ds, "ghn_addresses": res, "note": "plan: KHONG network, KHONG ghi DB"})
    return 0


async def cmd_snapshot(conn, a) -> int:
    banner = _mode_banner(a)
    targets = md.parse_targets(a.target)
    need = md.planned_requests(targets)
    plan = {**banner, "targets": targets, "planned_requests": need, "cap": a.cap,
            "endpoints": sorted(md.ALLOWED_PATHS)}
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
    saved = await S.load_saved_ghn_config(conn, a.mode)   # thieu/decrypt loi/mode lech -> raise (fail-closed); KHONG enable
    cp = saved["config"]
    cfg = {"base": (cp.get("base_url") or "").rstrip("/"), "token": saved["token"],
           "shop_id": str(cp.get("shop_id") or ""), "timeout": float(cp.get("timeout_seconds") or 8.0), "retries": 0}
    if cfg["base"] != _ghn.BASE_BY_MODE[a.mode]:
        raise SystemExit(f"base_url khong khop mode {a.mode} — dung")
    ver = a.snapshot_version or (f"ghn-{a.mode}-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    result = await md.fetch_scoped(cfg, targets, post=_ghn._post, cap=a.cap)
    del cfg, saved
    async with conn.transaction():
        counts = await md.persist_snapshot(conn, result, snapshot_version=ver, targets=targets, actor=a.actor,
                                           cap=a.cap, mode=a.mode)
    _p({**plan, "snapshot_version": ver, "status": result["status"], "reason": result["reason"],
        "request_count": len(result["calls"]), "requests": result["calls"], "report": result["report"],
        "persisted": counts})
    return 0 if result["status"] == "completed" else 2


async def cmd_build_map(conn, a) -> int:
    banner = _mode_banner(a)
    addrs = await _addresses(conn, a.address)
    rows, report = await md.build_map_rows(conn, addrs, mode=a.mode)
    snap = await conn.fetchval("SELECT snapshot_version FROM carrier_master_snapshot WHERE provider='ghn' AND "
                               "mode=$1 AND status='completed' ORDER BY id DESC LIMIT 1", a.mode)
    out = {**banner, "source_snapshot": snap, "report": report, "rows": rows}
    if not a.execute:
        _p({**out, "result": "DRY-RUN — khong ghi DB"})
        return 0
    if not a.actor:
        raise SystemExit("--execute can --actor")
    if not rows:
        raise SystemExit("khong co dong nao de ghi")
    async with conn.transaction():
        ver = await md.write_map_version(conn, rows, actor=a.actor, source=f"snapshot:{snap}", mode=a.mode)
    _p({**out, "map_version": ver, "note": "Cap nhat Dashboard GHN 'Map version' = map_version neu khac."})
    return 0


async def cmd_import_map(conn, a) -> int:
    with open(a.file, encoding="utf-8") as fh:
        items = json.load(fh)
    banner = _mode_banner(a)
    staff_rows = await md.validate_manual_rows(conn, items, source_note=a.source_note, mode=a.mode)
    base_ver, base_rows = await md.latest_map_rows(conn, a.mode) if a.base == "latest" else (None, [])
    rows = md.apply_overrides(base_rows, staff_rows)
    out = {**banner, "base_version": base_ver, "staff_rows": staff_rows, "total_rows": len(rows)}
    if not a.execute:
        _p({**out, "result": "DRY-RUN — khong ghi DB"})
        return 0
    if not a.actor:
        raise SystemExit("--execute can --actor")
    async with conn.transaction():
        ver = await md.write_map_version(conn, rows, actor=a.actor, source=f"manual:{a.source_note}", mode=a.mode)
    _p({**out, "map_version": ver, "note": "Cap nhat Dashboard GHN 'Map version' = map_version neu khac."})
    return 0


async def cmd_compare_modes(conn, a) -> int:
    """CA 357 §2.3.3: doi chieu master-data + map giua base_mode va mode. KHONG network, KHONG ghi DB."""
    banner = _mode_banner(a)
    md.check_mode(a.base_mode)
    addrs = await _addresses(conn, a.address)
    cmp_out = await md.compare_modes(conn, addrs, base_mode=a.base_mode, target_mode=a.mode)
    _p({**banner, **cmp_out, "note": "compare: KHONG network, KHONG ghi DB. reusable=true -> map base co the tai dung "
                                     "sau khi CA/PO xac nhan evidence; false -> xu ly entry lech."})
    return 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "snapshot", "build-map", "import-map", "compare-modes"):
        s = sub.add_parser(name)
        s.add_argument("--mode", required=True, choices=md.MODES, help="staging|production (BAT BUOC, CA 357)")
        s.add_argument("--execute", action="store_true", help="thuc thi that (mac dinh dry-run)")
        s.add_argument("--actor", help="nguoi thuc hien (bat buoc khi --execute)")
        if name == "compare-modes":
            s.add_argument("--base-mode", dest="base_mode", default="staging", choices=md.MODES)
        if name in ("plan", "build-map", "compare-modes"):
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
        fn = {"plan": cmd_plan, "snapshot": cmd_snapshot, "build-map": cmd_build_map, "import-map": cmd_import_map,
              "compare-modes": cmd_compare_modes}
        return await fn[a.cmd](conn, a)
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
