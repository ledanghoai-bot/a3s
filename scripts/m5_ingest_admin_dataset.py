"""M5 Gate A — Ingestion tooling cho dataset hanh chinh THAT (CA Guidance 121 §2).

Doc 1 file dataset do Ops/PO cung cap (nguon authoritative: GSO danh muc + van ban phap ly), tinh sha256
canonical, chay registry ingest (dry-run mac dinh) + acceptance gate 8 kiem tra, in report. KHONG tu tao/bia
du lieu dia danh — CHI doc file dau vao. KHONG activate (accept/activate qua control rieng + CA directive).

Dinh dang file JSON dau vao:
{
  "version": "VN-ADMIN-YYYY-MM-vN",
  "source_url": "...", "source_kind": "authoritative",
  "release_tag": "...", "commit_ref": "...", "downloaded_at": "YYYY-MM-DD",
  "license": "...",
  "provenance": {"source_url": "...", "source_kind": "authoritative", "downloaded_at": "YYYY-MM-DD",
                 "license": "...", "first_version": true|false,
                 "expected_counts": {"province": N, "district": N, "ward": N}},
  "units":   [{"level","code","name","parent_code","effective_from","effective_to"}, ...],
  "aliases": [{"unit_code","alias_name","alias_kind","source","confidence"}, ...]
}

Chay:
  DATABASE_URL=postgresql://... python scripts/m5_ingest_admin_dataset.py <file.json> \
    --actor <custodian> --reviewer <reviewer> --ticket <T> [--apply-ingest] [--run-gate]
Mac dinh: dry-run (khong ghi). --apply-ingest de ghi draft (staging). --run-gate de chay acceptance gate.
KHONG co co accept/activate o day (co chu dich: accept/activate can PO + CA directive).
"""
import argparse
import asyncio
import json
import os

import asyncpg

from app.services.address import acceptance_gate as gate
from app.services.address import dataset_registry as reg


async def run(path, actor, reviewer, ticket, apply_ingest, run_gate):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    units, aliases = d.get("units", []), d.get("aliases", [])
    computed = gate.canonical_checksum(units, aliases)
    print(f"version           : {d.get('version')}")
    print(f"source_kind       : {d.get('source_kind')}")
    print(f"units / aliases   : {len(units)} / {len(aliases)}")
    print(f"declared sha256   : {d.get('sha256', '(none)')}")
    print(f"computed sha256   : {computed}")
    print(f"provenance keys   : {sorted((d.get('provenance') or {}).keys())}")

    # Acceptance gate offline (khong DB) — xem truoc pass/fail truoc khi cham DB
    rep = gate.run(version=d.get("version", ""), units=units, aliases=aliases,
                   provenance=d.get("provenance") or {}, declared_sha256=computed,
                   regression=d.get("regression"),
                   has_rollback_target=bool((d.get("provenance") or {}).get("first_version")))
    print("\n== acceptance gate (offline preview) ==")
    for c in rep["checks"]:
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['check']}  {c['detail']}")
    print(f"  => passed={rep['passed']}")

    dburl = os.environ.get("DATABASE_URL")
    if not (apply_ingest or run_gate) or not dburl:
        print("\n(dry-run: khong cham DB. Dat DATABASE_URL + --apply-ingest/--run-gate de ingest staging.)")
        return
    conn = await asyncpg.connect(dburl.replace("+asyncpg", ""))
    try:
        if apply_ingest:
            r = await reg.ingest(conn, version=d["version"], source_url=d["source_url"],
                                 source_kind=d["source_kind"], license=d["license"], sha256=computed,
                                 provenance=d.get("provenance") or {}, units=units, aliases=aliases,
                                 release_tag=d.get("release_tag"), commit_ref=d.get("commit_ref"),
                                 downloaded_at=d.get("downloaded_at"), actor=actor,
                                 reason="Gate A dataset ingest (staging)", ticket=ticket, apply=True)
            print(f"\ningest applied: {r}")
        if run_gate:
            rg = await reg.run_gate(conn, version=d["version"], actor=reviewer,
                                    reason="Gate A validation", ticket=ticket,
                                    regression=d.get("regression"))
            print(f"gate (DB) passed={rg['passed']} "
                  f"failed={[c['check'] for c in rg['checks'] if not c['ok']]}")
    finally:
        await conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--actor", required=True, help="custodian (Dev/Ops) — khong tu accept")
    ap.add_argument("--reviewer", default="", help="reviewer doc lap (chay gate)")
    ap.add_argument("--ticket", required=True)
    ap.add_argument("--apply-ingest", action="store_true", help="ghi draft vao DB staging")
    ap.add_argument("--run-gate", action="store_true", help="chay acceptance gate tren DB")
    a = ap.parse_args()
    asyncio.run(run(a.file, a.actor, a.reviewer, a.ticket, a.apply_ingest, a.run_gate))


if __name__ == "__main__":
    main()
