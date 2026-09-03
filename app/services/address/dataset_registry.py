"""M5 Phase 1 — Dataset registry control (CA Directive 104).

Duong DUY NHAT thay doi admin_unit_dataset/status + con tro active_version. Control CA yeu cau:
- authorization fail-closed: actor + reason + ticket;
- immutable AUDIT qua audit_service.record (fail-closed neu audit_log chua provision);
- SoD (PO Decision #2): custodian ingest != reviewer != PO owner (accept/activate/rollback). Enforce bang
  cach so actor cua tung buoc (ingested_by/reviewed_by/approved_by phai khac nhau o cac vai xung dot);
- acceptance gate 8 kiem tra phai passed truoc accept; khong auto-activate;
- publish active_version NGUYEN TU: set con tro + set version -> active + retire version active cu, trong 1
  transaction; rollback tro con tro ve version truoc, active hien tai -> rolled_back.

KHONG dung production signing/Activation Gate. KHONG cham customer data. Dataset dormant cho toi khi activate.
"""
from __future__ import annotations

import json

from app.services import audit_service
from app.services.address import acceptance_gate


def _loads(v) -> dict:
    """JSONB tu asyncpg co the la str (chua set codec) hoac dict. Chuan hoa ve dict."""
    if v is None:
        return {}
    if isinstance(v, str):
        return json.loads(v or "{}")
    return v


class RegistryError(Exception):
    """Fail-closed. Khong leak secret."""


def _require_auth(actor: str | None, reason: str | None, ticket: str | None) -> None:
    if not (actor and actor.strip()):
        raise RegistryError("thieu actor (nguoi thuc hien, dinh danh khong bi mat)")
    if not (reason and reason.strip()):
        raise RegistryError("thieu reason")
    if not (ticket and ticket.strip()):
        raise RegistryError("thieu ticket (change/authorization reference)")


async def _assert_audit_ready(conn) -> None:
    if not await audit_service.audit_exists(conn):
        raise RegistryError("audit_log chua provision — tu choi dataset change khong co audit (fail-closed)")


async def _row(conn, version: str) -> dict | None:
    r = await conn.fetchrow("SELECT * FROM admin_unit_dataset WHERE version=$1", version)
    return dict(r) if r else None


async def get_active(conn) -> str | None:
    return await conn.fetchval("SELECT value FROM address_dataset_config WHERE key='active_version'")


async def ingest(
    conn, *, version: str, source_url: str, source_kind: str, license: str, sha256: str,
    provenance: dict, units: list[dict], aliases: list[dict], actor: str, reason: str, ticket: str,
    release_tag: str | None = None, commit_ref: str | None = None, downloaded_at=None,
    apply: bool = False,
) -> dict:
    """Custodian nap goi dataset -> draft. Dry-run neu apply=False. KHONG accept/activate."""
    _require_auth(actor, reason, ticket)
    await _assert_audit_ready(conn)
    if source_kind not in ("authoritative", "cross_reference"):
        raise RegistryError("source_kind phai authoritative|cross_reference")
    existing = await _row(conn, version)
    if existing:
        raise RegistryError(f"version {version} da ton tai (status={existing['status']}) — dung version moi")
    plan = {"action": "ingest", "version": version, "units": len(units), "aliases": len(aliases),
            "source_kind": source_kind}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        await conn.execute(
            "INSERT INTO admin_unit_dataset (version,status,source_url,source_kind,release_tag,commit_ref,"
            "downloaded_at,sha256,license,provenance,ingested_by,ticket) "
            "VALUES ($1,'draft',$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11)",
            version, source_url, source_kind, release_tag, commit_ref, downloaded_at, sha256.lower(),
            license, _json(provenance), actor, ticket)
        for u in units:
            await conn.execute(
                "INSERT INTO admin_unit (dataset_version,level,code,name,name_normalized,parent_code,"
                "effective_from,effective_to) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                version, u["level"], u["code"], u["name"], acceptance_gate.normalize(u["name"]),
                u.get("parent_code"), u.get("effective_from"), u.get("effective_to"))
        for a in aliases:
            await conn.execute(
                "INSERT INTO admin_unit_alias (dataset_version,unit_code,alias_name,alias_normalized,"
                "alias_kind,source,confidence) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                version, a["unit_code"], a["alias_name"], acceptance_gate.normalize(a["alias_name"]),
                a["alias_kind"], a.get("source"), a.get("confidence"))
        await audit_service.record(
            conn, actor_type="cli", action="address.dataset.ingest", actor_ref=actor,
            entity_type="admin_unit_dataset", entity_id=version, before=None,
            after={"status": "draft", "units": len(units), "aliases": len(aliases),
                   "source_kind": source_kind, "sha256": sha256.lower(), "ticket": ticket}, reason=reason)
    plan["applied"] = True
    return plan


async def run_gate(conn, *, version: str, actor: str, reason: str, ticket: str,
                   regression: list[dict] | None = None) -> dict:
    """Reviewer doc lap chay acceptance gate 8 kiem tra, luu report, chuyen draft->review.
    SoD: reviewer PHAI khac custodian ingest."""
    _require_auth(actor, reason, ticket)
    await _assert_audit_ready(conn)
    row = await _row(conn, version)
    if not row:
        raise RegistryError(f"version {version} khong ton tai")
    if row["status"] not in ("draft", "review"):
        raise RegistryError(f"chi chay gate khi draft/review (dang {row['status']})")
    if row.get("ingested_by") and actor.strip() == row["ingested_by"].strip():
        raise RegistryError("SoD: reviewer phai KHAC custodian ingest")
    units = [dict(r) for r in await conn.fetch(
        "SELECT level,code,name,parent_code,effective_from,effective_to FROM admin_unit WHERE dataset_version=$1",
        version)]
    aliases = [dict(r) for r in await conn.fetch(
        "SELECT unit_code,alias_name,alias_kind FROM admin_unit_alias WHERE dataset_version=$1", version)]
    active = await get_active(conn)
    report = acceptance_gate.run(
        version=version, units=units, aliases=aliases, provenance=_loads(row["provenance"]),
        declared_sha256=row["sha256"], regression=regression,
        has_rollback_target=(active is not None))
    async with conn.transaction():
        await conn.execute(
            "UPDATE admin_unit_dataset SET status='review', reviewed_by=$2, acceptance_report=$3::jsonb "
            "WHERE version=$1", version, actor, _json(report))
        await audit_service.record(
            conn, actor_type="cli", action="address.dataset.review", actor_ref=actor,
            entity_type="admin_unit_dataset", entity_id=version, before={"status": row["status"]},
            after={"status": "review", "passed": report["passed"],
                   "failed_checks": [c["check"] for c in report["checks"] if not c["ok"]],
                   "ticket": ticket}, reason=reason)
    return report


async def accept(conn, *, version: str, actor: str, reason: str, ticket: str, apply: bool = False) -> dict:
    """PO owner accept dataset (review->accepted). YEU CAU acceptance report passed. SoD: accepter khac
    custodian ingest VA khac reviewer."""
    _require_auth(actor, reason, ticket)
    await _assert_audit_ready(conn)
    row = await _row(conn, version)
    if not row:
        raise RegistryError(f"version {version} khong ton tai")
    if row["status"] != "review":
        raise RegistryError(f"chi accept tu 'review' (dang {row['status']}) — chay gate truoc")
    rep = _loads(row.get("acceptance_report"))
    if not rep.get("passed"):
        raise RegistryError("acceptance gate CHUA passed — tu choi accept (fail-closed)")
    if row.get("ingested_by") and actor.strip() == row["ingested_by"].strip():
        raise RegistryError("SoD: PO accepter phai KHAC custodian ingest")
    if row.get("reviewed_by") and actor.strip() == row["reviewed_by"].strip():
        raise RegistryError("SoD: PO accepter phai KHAC reviewer")
    plan = {"action": "accept", "version": version}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        await conn.execute(
            "UPDATE admin_unit_dataset SET status='accepted', approved_by=$2, accepted_at=now() "
            "WHERE version=$1", version, actor)
        await audit_service.record(
            conn, actor_type="cli", action="address.dataset.accept", actor_ref=actor,
            entity_type="admin_unit_dataset", entity_id=version, before={"status": "review"},
            after={"status": "accepted", "ticket": ticket}, reason=reason)
    plan["applied"] = True
    return plan


async def activate(conn, *, version: str, actor: str, reason: str, ticket: str, apply: bool = False) -> dict:
    """PO owner activate (accepted->active) NGUYEN TU: retire active cu + set con tro. KHONG auto (goi tuong minh).
    SoD: activator khac custodian ingest."""
    _require_auth(actor, reason, ticket)
    await _assert_audit_ready(conn)
    row = await _row(conn, version)
    if not row:
        raise RegistryError(f"version {version} khong ton tai")
    if row["status"] != "accepted":
        raise RegistryError(f"chi activate tu 'accepted' (dang {row['status']})")
    if row.get("ingested_by") and actor.strip() == row["ingested_by"].strip():
        raise RegistryError("SoD: activator phai KHAC custodian ingest")
    prev = await get_active(conn)
    plan = {"action": "activate", "version": version, "retire_prev": prev}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        if prev and prev != version:
            await conn.execute(
                "UPDATE admin_unit_dataset SET status='retired', terminal_at=now() "
                "WHERE version=$1 AND status='active'", prev)
        await conn.execute(
            "UPDATE admin_unit_dataset SET status='active', activated_at=now() WHERE version=$1", version)
        await conn.execute(
            "UPDATE address_dataset_config SET value=$1, updated_at=now() WHERE key='active_version'", version)
        await audit_service.record(
            conn, actor_type="cli", action="address.dataset.activate", actor_ref=actor,
            entity_type="admin_unit_dataset", entity_id=version, before={"active": prev},
            after={"active": version, "retired": prev, "ticket": ticket}, reason=reason)
    plan["applied"] = True
    return plan


async def rollback(conn, *, to_version: str, actor: str, reason: str, ticket: str, apply: bool = False) -> dict:
    """PO owner rollback con tro active ve to_version (da RETIRED). Active hien tai -> rolled_back.
    KHONG sua record khach hang. Rehearsal chay tren synthetic."""
    _require_auth(actor, reason, ticket)
    await _assert_audit_ready(conn)
    target = await _row(conn, to_version)
    if not target:
        raise RegistryError(f"to_version {to_version} khong ton tai")
    if target["status"] not in ("retired", "rolled_back", "accepted"):
        raise RegistryError(f"to_version {to_version} khong o trang thai co the rollback ve (dang {target['status']})")
    cur = await get_active(conn)
    plan = {"action": "rollback", "from": cur, "to": to_version}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        if cur and cur != to_version:
            await conn.execute(
                "UPDATE admin_unit_dataset SET status='rolled_back', terminal_at=now() "
                "WHERE version=$1 AND status='active'", cur)
        await conn.execute(
            "UPDATE admin_unit_dataset SET status='active', activated_at=now() WHERE version=$1", to_version)
        await conn.execute(
            "UPDATE address_dataset_config SET value=$1, updated_at=now() WHERE key='active_version'", to_version)
        await audit_service.record(
            conn, actor_type="cli", action="address.dataset.rollback", actor_ref=actor,
            entity_type="admin_unit_dataset", entity_id=to_version, before={"active": cur},
            after={"active": to_version, "rolled_back": cur, "ticket": ticket}, reason=reason)
    plan["applied"] = True
    return plan


async def deactivate(conn, *, version: str, actor: str, reason: str, ticket: str, apply: bool = False) -> dict:
    """PO owner deactivate: dua active_version ve NULL (dormant) + version dang active -> rolled_back.
    Dung cho rollback FIRST version (khong co version truoc de tro ve) — CA G-A-137-05.
    Fail-closed: chi deactivate version DANG active; SoD deactivator != custodian ingest; idempotent
    (version khong active -> tu choi). Immutable audit address.dataset.deactivate."""
    _require_auth(actor, reason, ticket)
    await _assert_audit_ready(conn)
    row = await _row(conn, version)
    if not row:
        raise RegistryError(f"version {version} khong ton tai")
    cur = await get_active(conn)
    if cur != version or row["status"] != "active":
        raise RegistryError(f"version {version} khong phai active hien tai (active={cur}, status={row['status']}) "
                            "— tu choi deactivate (idempotent/fail-closed)")
    if row.get("ingested_by") and actor.strip() == row["ingested_by"].strip():
        raise RegistryError("SoD: deactivator phai KHAC custodian ingest")
    plan = {"action": "deactivate", "version": version, "from_active": cur}
    if not apply:
        plan["dry_run"] = True
        return plan
    async with conn.transaction():
        await conn.execute(
            "UPDATE admin_unit_dataset SET status='rolled_back', terminal_at=now() "
            "WHERE version=$1 AND status='active'", version)
        await conn.execute(
            "UPDATE address_dataset_config SET value=NULL, updated_at=now() WHERE key='active_version'")
        await audit_service.record(
            conn, actor_type="cli", action="address.dataset.deactivate", actor_ref=actor,
            entity_type="admin_unit_dataset", entity_id=version, before={"active": version},
            after={"active": None, "rolled_back": version, "ticket": ticket}, reason=reason)
    plan["applied"] = True
    return plan


def _json(d) -> str:
    return json.dumps(d or {}, ensure_ascii=False, default=str)
