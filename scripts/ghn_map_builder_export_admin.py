"""CA Directive 377 §4 — export INPUT versioned cho map builder: danh muc hanh chinh Alpha3s (READ-ONLY).
Chay trong container api (doc DB): python - < ghn_map_builder_export_admin.py > admin_export.json
Chi ten/ma dia gioi hanh chinh cong khai + alias legacy + co self-zone. KHONG du lieu khach/don/secret."""
import asyncio
import json

import asyncpg

from app.config import settings


async def main():
    from app.services.fulfillment import routing as R
    c = await asyncpg.connect(settings.database_url.replace("+asyncpg", ""))
    try:
        ds = await c.fetchval("SELECT version FROM admin_unit_dataset WHERE status='active' ORDER BY version DESC LIMIT 1")
        provinces = [dict(r) for r in await c.fetch(
            "SELECT code, name FROM admin_unit WHERE dataset_version=$1 AND level='province' ORDER BY code", ds)]
        wards = [dict(r) for r in await c.fetch(
            "SELECT code, name, parent_code FROM admin_unit WHERE dataset_version=$1 AND level='ward' ORDER BY code", ds)]
        aliases = {}
        for r in await c.fetch("SELECT unit_code, alias_name, source FROM admin_unit_alias WHERE dataset_version=$1 "
                               "AND alias_kind='legacy' ORDER BY unit_code, alias_name", ds):
            src = r["source"]
            try:
                src = json.loads(src) if isinstance(src, str) else src
            except ValueError:
                src = {"raw": src}
            aliases.setdefault(r["unit_code"], []).append({"name": r["alias_name"],
                                                           "old_codes": (src or {}).get("old_codes")})
        rver = await R.active_version(c)
        allow = await R.load_allowlist(c, rver) if rver is not None else set()
        self_zone = sorted(f"{pc}/{wc}" for pc, wc in allow) if allow and isinstance(next(iter(allow)), tuple) \
            else sorted(str(x) for x in allow)
        out = {"dataset_version": ds, "routing_version": rver, "provinces": provinces, "wards": wards,
               "legacy_aliases": aliases, "self_zone_allowlist": self_zone,
               "counts": {"province": len(provinces), "ward": len(wards),
                          "alias": sum(len(v) for v in aliases.values()), "self_zone": len(self_zone)}}
        print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    finally:
        await c.close()

asyncio.run(main())
