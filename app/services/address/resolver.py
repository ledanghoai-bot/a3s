"""M5 Phase 2 — Address resolver (DB + immutable audit). CA Directive 108.

Duong tao address_resolution: chon dataset theo as_of -> nap units/aliases -> matcher (logic thuan) ->
ghi ban ghi BAT BIEN + audit. Fail-closed: khong co active dataset / khong co dataset hop as_of / thieu
province -> ResolveError (khong persist). Idempotency qua idempotency_key. actor tu session (khong tin body).

KHONG customer confirmation/staff queue (054), KHONG order/quote wiring, KHONG order FK. Rehearsal synthetic.
"""
from __future__ import annotations

import json

from app.services import audit_service
from app.services.address import dataset_registry as reg
from app.services.address import matcher


class ResolveError(Exception):
    """Fail-closed. Khong leak secret."""


async def _pick_dataset(conn, as_of) -> str | None:
    """as_of None/now -> active_version. as_of=<date> -> dataset dang active tai thoi diem do
    (activated_at <= as_of < terminal_at, hoac con active)."""
    if as_of is None:
        return await reg.get_active(conn)
    return await conn.fetchval(
        "SELECT version FROM admin_unit_dataset "
        "WHERE status IN ('active','retired','rolled_back') AND activated_at IS NOT NULL "
        "AND activated_at::date <= $1 AND (terminal_at IS NULL OR $1 < terminal_at::date) "
        "ORDER BY activated_at DESC LIMIT 1", as_of)


async def resolve(
    conn, *, subject_type: str, province: str | None, district: str | None = None,
    ward: str | None = None, street_text: str | None = None, subject_id: str | None = None,
    as_of=None, actor: str, reason: str, ticket: str, idempotency_key: str | None = None,
) -> dict:
    if not (actor and actor.strip()):
        raise ResolveError("thieu actor (tu session)")
    if subject_type not in ("customer", "order", "adhoc"):
        raise ResolveError("subject_type phai customer|order|adhoc")
    if not (province and province.strip()):
        raise ResolveError("thieu province (fail-closed)")
    await _assert_audit_ready(conn)

    if idempotency_key:
        ex = await conn.fetchrow("SELECT * FROM address_resolution WHERE idempotency_key=$1", idempotency_key)
        if ex:
            return _row(ex)

    dsv = await _pick_dataset(conn, as_of)
    if not dsv:
        raise ResolveError("khong co dataset active/hop as_of — fail-closed (chua the verify)")

    units = [dict(r) for r in await conn.fetch(
        "SELECT level,code,name,parent_code,effective_from,effective_to FROM admin_unit WHERE dataset_version=$1",
        dsv)]
    aliases = [dict(r) for r in await conn.fetch(
        "SELECT unit_code,alias_name,alias_kind FROM admin_unit_alias WHERE dataset_version=$1", dsv)]

    res = matcher.resolve(units, aliases, province=province, district=district, ward=ward, as_of=as_of)

    row = await conn.fetchrow(
        "INSERT INTO address_resolution (subject_type,subject_id,raw_province,raw_district,raw_ward,"
        "street_text,province_code,district_code,ward_code,dataset_version,as_of,status,method,confidence,"
        "candidates,rules_applied,idempotency_key,resolved_by,reason,ticket) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb,$16::jsonb,$17,$18,$19,$20) "
        "RETURNING *",
        subject_type, subject_id, province, district, ward, street_text,
        res["province_code"], res["district_code"], res["ward_code"], dsv, as_of,
        res["status"], res["method"], res["confidence"],
        json.dumps(res["candidates"], ensure_ascii=False), json.dumps(res["rules_applied"], ensure_ascii=False),
        idempotency_key, actor, reason, ticket)
    await audit_service.record(
        conn, actor_type="cli", action="address.resolve", actor_ref=actor,
        entity_type="address_resolution", entity_id=str(row["id"]), before=None,
        after={"status": res["status"], "method": res["method"], "confidence": res["confidence"],
               "dataset_version": dsv, "rules": res["rules_applied"], "subject_type": subject_type,
               "ticket": ticket}, reason=reason)
    return _row(row)


async def _assert_audit_ready(conn) -> None:
    if not await audit_service.audit_exists(conn):
        raise ResolveError("audit_log chua provision — tu choi resolution khong co audit (fail-closed)")


def _row(r) -> dict:
    d = dict(r)
    d["id"] = str(d["id"])
    for k in ("candidates", "rules_applied"):
        if isinstance(d.get(k), str):
            d[k] = json.loads(d[k] or "[]")
    return d
