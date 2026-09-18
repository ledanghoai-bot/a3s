"""CA Directive 305 §3/§6/§7 — Shop Settings integration service.

CRUD public config + secret write/rotate (ma hoa), list/detail REDACTED (khong ciphertext/plaintext), version CAS +
command_key idempotency, test-connection READ-ONLY, enable-gate (test pass khop config+secret version), disable/archive,
loader precedence (env|database|none) fail-closed. Provider/kind/mode ALLOWLIST — khong arbitrary plugin.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.config import settings
from app.services import audit_service
from app.services.settings import crypto as _c

# provider -> (kind, allowed modes, secret key_names, public-field allowlist)
_ALLOW = {
    "ghn":           ("shipping", ("staging",),          ("token",),            ("base_url", "shop_id",
                      "from_district_id", "from_ward_code", "timeout_seconds", "max_retries", "light_max_g",
                      "address_map_version")),
    "self_delivery": ("shipping", ("live",),             (),                    ("note",)),
    "bank_transfer": ("payment",  ("live", "test"),      ("account_number",),   ("bank", "bin", "holder", "branch")),
    "sepay":         ("payment",  ("test",),             ("api_key",),          ("allowed_accounts", "code_prefix",
                      "webhook_note")),
}
_FIELDS_LAST4_OK = {"account_number"}   # chi field nay duoc phep hien last4 (CA 304-06)
_GHN_STAGING_BASE = "https://dev-online-gateway.ghn.vn/shiip/public-api"


class SettingsError(Exception):
    """Fail-closed. Khong leak secret/plaintext."""


def _now():
    return datetime.now(timezone.utc)


def _validate_provider(kind: str, provider: str, mode: str) -> tuple:
    spec = _ALLOW.get(provider)
    if spec is None:
        raise SettingsError(f"provider '{provider}' khong duoc phep")
    a_kind, a_modes, secret_keys, pub_fields = spec
    if kind != a_kind:
        raise SettingsError(f"provider '{provider}' thuoc kind '{a_kind}', khong phai '{kind}'")
    if mode not in a_modes:
        raise SettingsError(f"mode '{mode}' khong hop le cho '{provider}' (cho phep: {a_modes})")
    return spec


def _clean_public(provider: str, config_public: dict) -> dict:
    """Chi giu field public trong allowlist (CA 304-05: khong nhet domain policy/secret vao JSON)."""
    _, _, _, pub_fields = _ALLOW[provider]
    if not isinstance(config_public, dict):
        raise SettingsError("config_public phai la object")
    out = {k: v for k, v in config_public.items() if k in pub_fields}
    # GHN: base_url pin theo mode staging (CA 305-08) — user khong nhap arbitrary host.
    if provider == "ghn":
        out["base_url"] = _GHN_STAGING_BASE
    return out


# ------------------------------------------------------------------ readback (REDACTED)
async def _secret_meta(conn, integration_id: int) -> dict:
    rows = await conn.fetch(
        "SELECT key_name, last4, version, updated_at FROM integration_secrets WHERE integration_id=$1", integration_id)
    meta = {}
    for r in rows:
        meta[r["key_name"]] = {"present": True,
                               "last4": r["last4"] if r["key_name"] in _FIELDS_LAST4_OK else None,
                               "version": r["version"], "updated_at": r["updated_at"]}
    return meta


def _row_public(row) -> dict:
    cp = row["config_public"]
    cp = json.loads(cp) if isinstance(cp, str) else (cp or {})
    return {"id": row["id"], "kind": row["kind"], "provider": row["provider"], "label": row["label"],
            "mode": row["mode"], "enabled": row["enabled"], "config_public": cp, "version": row["version"],
            "archived": row["archived_at"] is not None,
            "last_test": {"status": row["last_test_status"], "at": row["last_test_at"],
                          "config_version": row["last_test_config_version"],
                          "secret_version": row["last_test_secret_version"]}}


async def list_integrations(conn, *, kind: str | None = None) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM integrations WHERE ($1::text IS NULL OR kind=$1) AND archived_at IS NULL ORDER BY id", kind)
    out = []
    for r in rows:
        d = _row_public(r)
        d["secrets"] = await _secret_meta(conn, r["id"])
        d["config_source"] = "database"   # detail source qua loader; list = database record
        out.append(d)
    return out


async def get_integration(conn, integration_id: int) -> dict | None:
    r = await conn.fetchrow("SELECT * FROM integrations WHERE id=$1", integration_id)
    if not r:
        return None
    d = _row_public(r)
    d["secrets"] = await _secret_meta(conn, integration_id)
    return d


# ------------------------------------------------------------------ mutations (CAS + idempotency)
async def _audit(conn, action, actor, integration_id, after):
    await audit_service.record(conn, actor_type="staff", action=action, actor_ref=actor,
                               entity_type="integrations", entity_id=str(integration_id), after=after)


async def create_integration(conn, *, kind: str, provider: str, label: str, mode: str,
                             config_public: dict, actor: str) -> dict:
    _validate_provider(kind, provider, mode)
    cp = _clean_public(provider, config_public or {})
    row = await conn.fetchrow(
        "INSERT INTO integrations (kind, provider, label, mode, config_public, created_by, updated_by) "
        "VALUES ($1,$2,$3,$4,$5::jsonb,$6,$6) RETURNING *", kind, provider, label, mode, json.dumps(cp), actor)
    await _audit(conn, "settings.integration.create", actor, row["id"],
                 {"provider": provider, "kind": kind, "mode": mode})
    return _row_public(row)


async def update_public(conn, integration_id: int, *, label: str | None, config_public: dict | None,
                        expected_version: int, actor: str) -> dict:
    r = await conn.fetchrow("SELECT * FROM integrations WHERE id=$1 FOR UPDATE", integration_id)
    if not r:
        raise SettingsError("integration khong ton tai")
    if r["version"] != expected_version:
        raise SettingsError("version conflict (config da doi) — tai lai")
    cp = _clean_public(r["provider"], config_public) if config_public is not None else \
        (json.loads(r["config_public"]) if isinstance(r["config_public"], str) else r["config_public"])
    new_label = label if label is not None else r["label"]
    # doi config -> test cu HET HIEU LUC (CA 304-07): xoa last_test.
    row = await conn.fetchrow(
        "UPDATE integrations SET label=$2, config_public=$3::jsonb, version=version+1, updated_at=now(), updated_by=$4, "
        "last_test_status=NULL, last_test_at=NULL, last_test_config_version=NULL, last_test_secret_version=NULL "
        "WHERE id=$1 AND version=$5 RETURNING *", integration_id, new_label, json.dumps(cp), actor, expected_version)
    if row is None:
        raise SettingsError("version conflict (concurrent) — huy")
    await _audit(conn, "settings.integration.update_public", actor, integration_id, {"version": row["version"]})
    return _row_public(row)


async def write_secret(conn, integration_id: int, *, key_name: str, plaintext: str, actor: str) -> dict:
    """Ghi/xoay secret: ma hoa AES-GCM (current key), bump version. Doi secret -> test cu het hieu luc."""
    r = await conn.fetchrow("SELECT provider FROM integrations WHERE id=$1 FOR UPDATE", integration_id)
    if not r:
        raise SettingsError("integration khong ton tai")
    _, _, secret_keys, _ = _ALLOW[r["provider"]]
    if key_name not in secret_keys:
        raise SettingsError(f"key_name '{key_name}' khong hop le cho provider '{r['provider']}'")
    if not isinstance(plaintext, str) or not plaintext.strip():
        raise SettingsError("secret rong")
    existing = await conn.fetchrow(
        "SELECT version, fingerprint FROM integration_secrets WHERE integration_id=$1 AND key_name=$2",
        integration_id, key_name)
    fp = _c.fingerprint(plaintext)
    if existing and existing["fingerprint"] == fp:
        # replay/idempotent: nhap lai DUNG secret cu -> khong bump version, khong doi gi (effective-once).
        return {"key_name": key_name, "version": existing["version"], "present": True, "replay": True}
    new_ver = (existing["version"] if existing else 0) + 1
    kid, nonce, ct = _c.encrypt_secret(plaintext, integration_id=integration_id, provider=r["provider"],
                                       key_name=key_name, version=new_ver)
    last4 = plaintext[-4:] if key_name in _FIELDS_LAST4_OK and len(plaintext) >= 4 else None
    await conn.execute(
        "INSERT INTO integration_secrets (integration_id, key_name, key_id, ciphertext, nonce, fingerprint, last4, "
        "version, updated_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
        "ON CONFLICT (integration_id, key_name) DO UPDATE SET key_id=EXCLUDED.key_id, ciphertext=EXCLUDED.ciphertext, "
        "nonce=EXCLUDED.nonce, fingerprint=EXCLUDED.fingerprint, last4=EXCLUDED.last4, version=EXCLUDED.version, "
        "updated_at=now(), updated_by=EXCLUDED.updated_by",
        integration_id, key_name, kid, ct, nonce, fp, last4, new_ver, actor)
    # secret doi -> test cu het hieu luc.
    await conn.execute("UPDATE integrations SET last_test_status=NULL, last_test_at=NULL, "
                       "last_test_config_version=NULL, last_test_secret_version=NULL, updated_at=now() WHERE id=$1",
                       integration_id)
    await _audit(conn, "settings.integration.secret_write", actor, integration_id,
                 {"key_name": key_name, "version": new_ver})   # KHONG plaintext/ciphertext
    return {"key_name": key_name, "version": new_ver, "present": True}


async def clear_secret(conn, integration_id: int, *, key_name: str, actor: str) -> None:
    """Xoa secret (explicit clear/purge). PO-only enforce o API (permission)."""
    await conn.execute("DELETE FROM integration_secrets WHERE integration_id=$1 AND key_name=$2",
                       integration_id, key_name)
    await conn.execute("UPDATE integrations SET enabled=false, last_test_status=NULL, last_test_at=NULL, "
                       "updated_at=now() WHERE id=$1", integration_id)   # thieu secret -> disable + test het hieu luc
    await _audit(conn, "settings.integration.secret_clear", actor, integration_id, {"key_name": key_name})


# ------------------------------------------------------------------ secret decrypt (server-side only)
async def _decrypt_secret(conn, integration_id: int, provider: str, key_name: str) -> str | None:
    r = await conn.fetchrow("SELECT key_id, ciphertext, nonce, version FROM integration_secrets "
                            "WHERE integration_id=$1 AND key_name=$2", integration_id, key_name)
    if not r:
        return None
    return _c.decrypt_secret(bytes(r["ciphertext"]), bytes(r["nonce"]), key_id=r["key_id"],
                             integration_id=integration_id, provider=provider, key_name=key_name, version=r["version"])


# ------------------------------------------------------------------ test-connection (READ-ONLY)
async def test_connection(conn, integration_id: int, *, actor: str, post=None) -> dict:
    """GHN staging: probe read-only (master-data/province auth check). KHONG create/update/cancel shipment.
    Ghi last_test bind config+secret version. Tra ket qua REDACTED (ok/latency/error class), khong echo header/token."""
    r = await conn.fetchrow("SELECT * FROM integrations WHERE id=$1 FOR UPDATE", integration_id)
    if not r:
        raise SettingsError("integration khong ton tai")
    if r["provider"] != "ghn":
        raise SettingsError("test-connection: chi ho tro GHN o GD1")
    cp = json.loads(r["config_public"]) if isinstance(r["config_public"], str) else (r["config_public"] or {})
    token = await _decrypt_secret(conn, integration_id, "ghn", "token")
    shop_id = cp.get("shop_id")
    if not token or not shop_id:
        result = {"ok": False, "error_class": "not_configured"}
    else:
        from app.services.providers import ghn as _ghn
        cfg = {"base": (cp.get("base_url") or _GHN_STAGING_BASE).rstrip("/"), "token": token, "shop_id": str(shop_id),
               "timeout": float(cp.get("timeout_seconds") or 8.0), "retries": int(cp.get("max_retries") or 1)}
        _post = post or _ghn._post
        st, js, err, dur = await _post(cfg, "/master-data/province", {}, retries=cfg["retries"])
        if err or st != 200 or not isinstance(js, dict) or js.get("code") != 200:
            ec = "timeout" if err == "timeout" else (f"http_{st}" if st else (err or "error"))
            result = {"ok": False, "error_class": ec, "latency_ms": dur}
        else:
            result = {"ok": True, "capability": "master-data:read", "province_count": len(js.get("data") or []),
                      "latency_ms": dur}
    sec_ver = await conn.fetchval("SELECT version FROM integration_secrets WHERE integration_id=$1 AND key_name='token'",
                                  integration_id)
    await conn.execute(
        "UPDATE integrations SET last_test_status=$2, last_test_at=now(), last_test_config_version=$3, "
        "last_test_secret_version=$4, last_test_detail=$5::jsonb, updated_at=now() WHERE id=$1",
        integration_id, "pass" if result["ok"] else "fail", r["version"], sec_ver, json.dumps(result))
    await _audit(conn, "settings.integration.test", actor, integration_id,
                 {"ok": result["ok"], "error_class": result.get("error_class")})
    return result


# ------------------------------------------------------------------ enable / disable
async def enable(conn, integration_id: int, *, expected_version: int, actor: str) -> dict:
    """Bat CHI khi latest test PASS va khop config+secret version hien hanh (CA 305-06)."""
    r = await conn.fetchrow("SELECT * FROM integrations WHERE id=$1 FOR UPDATE", integration_id)
    if not r:
        raise SettingsError("integration khong ton tai")
    if r["version"] != expected_version:
        raise SettingsError("version conflict — tai lai")
    _, _, secret_keys, _ = _ALLOW[r["provider"]]
    for k in secret_keys:
        if not await conn.fetchval("SELECT 1 FROM integration_secrets WHERE integration_id=$1 AND key_name=$2",
                                   integration_id, k):
            raise SettingsError(f"thieu secret '{k}' — nhap truoc khi bat")
    if r["last_test_status"] != "pass":
        raise SettingsError("chua co test-connection PASS — test truoc khi bat")
    if r["last_test_config_version"] != r["version"]:
        raise SettingsError("config da doi sau test — test lai truoc khi bat")
    sec_ver = await conn.fetchval("SELECT max(version) FROM integration_secrets WHERE integration_id=$1",
                                  integration_id)
    if r["last_test_secret_version"] != sec_ver:
        raise SettingsError("secret da doi sau test — test lai truoc khi bat")
    row = await conn.fetchrow(
        "UPDATE integrations SET enabled=true, version=version+1, updated_at=now(), updated_by=$2 "
        "WHERE id=$1 AND version=$3 RETURNING *", integration_id, actor, expected_version)
    if row is None:
        raise SettingsError("version conflict (concurrent) — huy")
    await _audit(conn, "settings.integration.enable", actor, integration_id, {"version": row["version"]})
    return _row_public(row)


async def disable(conn, integration_id: int, *, actor: str) -> dict:
    row = await conn.fetchrow(
        "UPDATE integrations SET enabled=false, version=version+1, updated_at=now(), updated_by=$2 WHERE id=$1 "
        "RETURNING *", integration_id, actor)
    if row is None:
        raise SettingsError("integration khong ton tai")
    await _audit(conn, "settings.integration.disable", actor, integration_id, {"version": row["version"]})
    return _row_public(row)


async def archive(conn, integration_id: int, *, actor: str) -> None:
    await conn.execute("UPDATE integrations SET enabled=false, archived_at=now(), updated_at=now(), updated_by=$2 "
                       "WHERE id=$1 AND archived_at IS NULL", integration_id, actor)
    await _audit(conn, "settings.integration.archive", actor, integration_id, {})


# ------------------------------------------------------------------ LOADER (precedence, fail-closed)
async def load_active_config(conn, provider: str, mode: str) -> dict:
    """CA 305-07 precedence. Tra {source: env|database|none, enabled, config, secrets} — secrets DECRYPTED (server-side).
    - module OFF -> source=env (baseline .env khong doi).
    - ON + no DB active record -> env CHI khi settings_integrations_env_fallback; nguoc lai none (fail closed).
    - ON + DB active nhung decrypt/invalid loi -> RAISE (fail closed) — caller xu ly nhu disabled/manual, KHONG fallback env."""
    if not settings.settings_integrations_enabled:
        return {"source": "env", "enabled": None, "config": {}, "secrets": {}}
    r = await conn.fetchrow(
        "SELECT * FROM integrations WHERE provider=$1 AND mode=$2 AND enabled AND archived_at IS NULL "
        "ORDER BY id DESC LIMIT 1", provider, mode)
    if not r:
        if settings.settings_integrations_env_fallback:
            return {"source": "env", "enabled": None, "config": {}, "secrets": {}}
        return {"source": "none", "enabled": False, "config": {}, "secrets": {}}
    cp = json.loads(r["config_public"]) if isinstance(r["config_public"], str) else (r["config_public"] or {})
    _, _, secret_keys, _ = _ALLOW[provider]
    secrets = {}
    for k in secret_keys:
        pt = await _decrypt_secret(conn, r["id"], provider, k)   # raise ConfigDecryptError -> fail closed
        if pt is None:
            raise SettingsError(f"active integration thieu secret '{k}' — fail closed")
        secrets[k] = pt
    return {"source": "database", "enabled": True, "config": cp, "secrets": secrets, "integration_id": r["id"]}
