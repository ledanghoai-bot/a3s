"""CA Directive 305 (+ Review 307 V02) — Shop Settings integration service.

CRUD public config + secret write/rotate (ma hoa), list/detail REDACTED (khong ciphertext/plaintext), version CAS +
DURABLE command_key idempotency (bang integration_commands), provider schema validation, test-connection READ-ONLY
HAI PHA (khong giu row-lock qua network), enable-gate bind config_revision (307-05), purge tach khoi write (307-06),
loader precedence (env|database|none) fail-closed. Provider/kind/mode ALLOWLIST — khong arbitrary plugin.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import asyncpg

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


class SettingsConflict(SettingsError):
    """CAS/idempotency/uniqueness conflict — API map 409."""


class SettingsNotFound(SettingsError):
    """Entity khong ton tai — API map 404 (deterministic, khong audit)."""


def _now():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ validation (307-03)
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


# GHN field spec: name -> (kind, validator). Dung CHUNG cho save/test/enable (307-03).
def _as_int(v, name, *, lo=None, hi=None) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        # cho phep chuoi so nguyen tu form
        if isinstance(v, str) and v.strip().lstrip("-").isdigit():
            v = int(v)
        else:
            raise SettingsError(f"{name} phai so nguyen")
    if lo is not None and v < lo:
        raise SettingsError(f"{name} < {lo}")
    if hi is not None and v > hi:
        raise SettingsError(f"{name} > {hi}")
    return v


def _as_num(v, name, *, lo=None, hi=None) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                raise SettingsError(f"{name} phai so")
        else:
            raise SettingsError(f"{name} phai so")
    if lo is not None and v < lo:
        raise SettingsError(f"{name} < {lo}")
    if hi is not None and v > hi:
        raise SettingsError(f"{name} > {hi}")
    return v


def _as_str(v, name) -> str:
    if not isinstance(v, str) or not v.strip():
        raise SettingsError(f"{name} rong")
    return v.strip()


# required GHN pickup/quote fields cho test/enable (khong bat buoc luc save tung phan).
_GHN_REQUIRED = ("shop_id", "from_district_id", "from_ward_code", "timeout_seconds", "max_retries",
                 "light_max_g", "address_map_version")


def _validate_public(provider: str, config_public: dict) -> dict:
    """Chi giu field public trong allowlist + reject unknown/invalid (307-03). Cho phep partial (Save != Enable)."""
    _, _, _, pub_fields = _ALLOW[provider]
    if not isinstance(config_public, dict):
        raise SettingsError("config_public phai la object")
    unknown = [k for k in config_public if k not in pub_fields]
    if unknown:
        raise SettingsError(f"config_public co field khong hop le: {sorted(unknown)}")
    out = dict(config_public)
    if provider == "ghn":
        # base_url pin theo mode staging (CA 305-08) — user khong nhap arbitrary host.
        out["base_url"] = _GHN_STAGING_BASE
        # validate type/bound cho tung field CO MAT (partial cho phep).
        if "shop_id" in out:
            out["shop_id"] = _as_str(out["shop_id"], "shop_id")
        if "from_district_id" in out:
            out["from_district_id"] = _as_int(out["from_district_id"], "from_district_id", lo=1)
        if "from_ward_code" in out:
            out["from_ward_code"] = _as_str(out["from_ward_code"], "from_ward_code")
        if "timeout_seconds" in out:
            out["timeout_seconds"] = _as_num(out["timeout_seconds"], "timeout_seconds", lo=1, hi=60)
        if "max_retries" in out:
            out["max_retries"] = _as_int(out["max_retries"], "max_retries", lo=0, hi=5)
        if "light_max_g" in out:
            out["light_max_g"] = _as_int(out["light_max_g"], "light_max_g", lo=1, hi=2000000)
        if "address_map_version" in out:
            out["address_map_version"] = _as_int(out["address_map_version"], "address_map_version", lo=1)
    return out


def _require_ghn_complete(config: dict) -> None:
    """Truoc test/enable: moi field GHN pickup/quote phai co mat va hop le (307-03)."""
    missing = [k for k in _GHN_REQUIRED if config.get(k) in (None, "")]
    if missing:
        raise SettingsError(f"thieu cau hinh GHN: {missing} — dien du truoc khi test/bat")


# ------------------------------------------------------------------ command idempotency (307-02)
def _payload_fp(action: str, integration_id, parts: dict) -> str:
    """sha256 canonical(action|integration|parts). parts KHONG chua plaintext (secret dung keyed fp)."""
    canon = json.dumps({"a": action, "i": integration_id, "p": parts}, sort_keys=True,
                        separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


async def _run_command(conn, *, command_key: str, action: str, integration_id, payload_fp: str, fn):
    """Durable idempotency. Cung key+payload -> ket qua cu (replay). Cung key+payload khac -> conflict.
    PK integration_commands serialize concurrent same-key. Chay trong transaction cua caller (atomic voi mutation)."""
    if not command_key or not isinstance(command_key, str):
        raise SettingsError("thieu command_key")
    claimed = await conn.fetchrow(
        "INSERT INTO integration_commands (command_key, action, integration_id, request_fingerprint) "
        "VALUES ($1,$2,$3,$4) ON CONFLICT (command_key) DO NOTHING RETURNING command_key",
        command_key, action, integration_id, payload_fp)
    if claimed is None:
        prev = await conn.fetchrow(
            "SELECT action, request_fingerprint, result FROM integration_commands WHERE command_key=$1", command_key)
        if prev is None:  # cuc hiem: bi xoa xen giua — coi nhu conflict, khong chay lai
            raise SettingsConflict("command_key dang xu ly — thu lai")
        if prev["action"] != action or prev["request_fingerprint"] != payload_fp:
            raise SettingsConflict("command_key da dung cho request khac (conflict)")
        res = prev["result"]
        stored = json.loads(res) if isinstance(res, str) else (res or {})
        stored["_replay"] = True
        return stored
    result = await fn()
    await conn.execute("UPDATE integration_commands SET result=$2::jsonb WHERE command_key=$1",
                       command_key, json.dumps(result, default=str))
    return result


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
            "config_revision": row["config_revision"],
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


async def _lock(conn, integration_id: int, expected_version: int | None):
    """SELECT ... FOR UPDATE + kiem tra ton tai + CAS (neu co expected_version)."""
    r = await conn.fetchrow("SELECT * FROM integrations WHERE id=$1 FOR UPDATE", integration_id)
    if not r:
        raise SettingsNotFound("integration khong ton tai")
    if expected_version is not None and r["version"] != expected_version:
        raise SettingsConflict("version conflict (da doi) — tai lai")
    return r


async def create_integration(conn, *, kind: str, provider: str, label: str, mode: str,
                             config_public: dict, actor: str, command_key: str) -> dict:
    _validate_provider(kind, provider, mode)
    cp = _validate_public(provider, config_public or {})
    fp = _payload_fp("create", None, {"kind": kind, "provider": provider, "mode": mode, "label": label, "cp": cp})

    async def _do():
        try:
            row = await conn.fetchrow(
                "INSERT INTO integrations (kind, provider, label, mode, config_public, created_by, updated_by) "
                "VALUES ($1,$2,$3,$4,$5::jsonb,$6,$6) RETURNING *",
                kind, provider, label, mode, json.dumps(cp), actor)
        except asyncpg.UniqueViolationError:
            raise SettingsConflict(f"da ton tai integration cho ({provider},{mode}) — dung ban hien co")
        await _audit(conn, "settings.integration.create", actor, row["id"],
                     {"provider": provider, "kind": kind, "mode": mode})
        return _row_public(row)

    return await _run_command(conn, command_key=command_key, action="create", integration_id=None,
                              payload_fp=fp, fn=_do)


async def update_public(conn, integration_id: int, *, label: str | None, config_public: dict | None,
                        expected_version: int, actor: str, command_key: str) -> dict:
    # payload_fp tu REQUEST THO (khong doc DB) -> journal replay xay ra TRUOC CAS (retry idempotent, khong CAS-conflict).
    fp = _payload_fp("update_public", integration_id,
                     {"v": expected_version, "label": label, "cp": config_public})

    async def _do():
        r = await _lock(conn, integration_id, expected_version)
        cp = _validate_public(r["provider"], config_public) if config_public is not None else \
            (json.loads(r["config_public"]) if isinstance(r["config_public"], str) else r["config_public"])
        new_label = label if label is not None else r["label"]
        # config doi -> config_revision++ + test cu HET HIEU LUC (CA 304-07). version++ (lifecycle CAS).
        row = await conn.fetchrow(
            "UPDATE integrations SET label=$2, config_public=$3::jsonb, version=version+1, "
            "config_revision=config_revision+1, updated_at=now(), updated_by=$4, "
            "last_test_status=NULL, last_test_at=NULL, last_test_config_version=NULL, last_test_secret_version=NULL "
            "WHERE id=$1 AND version=$5 RETURNING *", integration_id, new_label, json.dumps(cp), actor,
            expected_version)
        if row is None:
            raise SettingsConflict("version conflict (concurrent) — huy")
        await _audit(conn, "settings.integration.update_public", actor, integration_id, {"version": row["version"]})
        return _row_public(row)

    return await _run_command(conn, command_key=command_key, action="update_public",
                              integration_id=integration_id, payload_fp=fp, fn=_do)


async def write_secret(conn, integration_id: int, *, key_name: str, plaintext: str, expected_version: int,
                       actor: str, command_key: str) -> dict:
    """Ghi/xoay secret: ma hoa AES-GCM (current key), bump version+config_revision. Doi secret -> test cu het hieu luc."""
    if not isinstance(plaintext, str) or not plaintext.strip():
        raise SettingsError("secret rong")
    fp_secret = _c.fingerprint(plaintext)   # keyed HMAC — dung ca cho replay-check va command payload (KHONG plaintext)
    fp = _payload_fp("secret_write", integration_id, {"v": expected_version, "k": key_name, "fp": fp_secret})

    async def _do():
        r = await _lock(conn, integration_id, expected_version)
        _, _, secret_keys, _ = _ALLOW[r["provider"]]
        if key_name not in secret_keys:
            raise SettingsError(f"key_name '{key_name}' khong hop le cho provider '{r['provider']}'")
        existing = await conn.fetchrow(
            "SELECT version, fingerprint FROM integration_secrets WHERE integration_id=$1 AND key_name=$2",
            integration_id, key_name)
        if existing and existing["fingerprint"] == fp_secret:
            # nhap lai DUNG secret cu: NO-OP that (khong bump version/secret, khong doi test) -> effective-once.
            return {"key_name": key_name, "version": existing["version"], "present": True, "unchanged": True,
                    "integration_version": r["version"]}
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
            integration_id, key_name, kid, ct, nonce, fp_secret, last4, new_ver, actor)
        # secret doi -> config_revision++ (invalidates test) + version++ (lifecycle) + xoa last_test.
        row = await conn.fetchrow(
            "UPDATE integrations SET version=version+1, config_revision=config_revision+1, last_test_status=NULL, "
            "last_test_at=NULL, last_test_config_version=NULL, last_test_secret_version=NULL, updated_at=now(), "
            "updated_by=$2 WHERE id=$1 AND version=$3 RETURNING version", integration_id, actor, expected_version)
        if row is None:
            raise SettingsConflict("version conflict (concurrent) — huy")
        await _audit(conn, "settings.integration.secret_write", actor, integration_id,
                     {"key_name": key_name, "version": new_ver})   # KHONG plaintext/ciphertext
        return {"key_name": key_name, "version": new_ver, "present": True, "integration_version": row["version"]}

    return await _run_command(conn, command_key=command_key, action="secret_write",
                              integration_id=integration_id, payload_fp=fp, fn=_do)


async def purge_secret(conn, integration_id: int, *, key_name: str, expected_version: int, actor: str,
                       command_key: str) -> dict:
    """Xoa HAN secret (explicit purge) — PO/owner-only enforce o API (permission secret_purge, 307-06).
    CAS + idempotency + deterministic 404/conflict. Purge -> disable + config_revision++ + test het hieu luc."""
    fp = _payload_fp("secret_purge", integration_id, {"v": expected_version, "k": key_name})

    async def _do():
        r = await _lock(conn, integration_id, expected_version)
        _, _, secret_keys, _ = _ALLOW[r["provider"]]
        if key_name not in secret_keys:
            raise SettingsError(f"key_name '{key_name}' khong hop le cho provider '{r['provider']}'")
        existing = await conn.fetchval(
            "SELECT 1 FROM integration_secrets WHERE integration_id=$1 AND key_name=$2", integration_id, key_name)
        if not existing:
            raise SettingsNotFound(f"secret '{key_name}' khong ton tai")
        await conn.execute("DELETE FROM integration_secrets WHERE integration_id=$1 AND key_name=$2",
                           integration_id, key_name)
        row = await conn.fetchrow(
            "UPDATE integrations SET enabled=false, version=version+1, config_revision=config_revision+1, "
            "last_test_status=NULL, last_test_at=NULL, last_test_config_version=NULL, last_test_secret_version=NULL, "
            "updated_at=now(), updated_by=$2 WHERE id=$1 AND version=$3 RETURNING version",
            integration_id, actor, expected_version)
        if row is None:
            raise SettingsConflict("version conflict (concurrent) — huy")
        await _audit(conn, "settings.integration.secret_purge", actor, integration_id, {"key_name": key_name})
        return {"key_name": key_name, "purged": True, "integration_version": row["version"]}

    return await _run_command(conn, command_key=command_key, action="secret_purge",
                              integration_id=integration_id, payload_fp=fp, fn=_do)


# ------------------------------------------------------------------ secret decrypt (server-side only)
async def _decrypt_secret(conn, integration_id: int, provider: str, key_name: str) -> str | None:
    r = await conn.fetchrow("SELECT key_id, ciphertext, nonce, version FROM integration_secrets "
                            "WHERE integration_id=$1 AND key_name=$2", integration_id, key_name)
    if not r:
        return None
    return _c.decrypt_secret(bytes(r["ciphertext"]), bytes(r["nonce"]), key_id=r["key_id"],
                             integration_id=integration_id, provider=provider, key_name=key_name, version=r["version"])


# ------------------------------------------------------------------ test-connection (READ-ONLY, HAI PHA — 307-04)
async def test_connection(conn, integration_id: int, *, actor: str, post=None) -> dict:
    """GHN staging: probe read-only (master-data province auth check). KHONG create/update/cancel shipment.
    HAI PHA (307-04): (1) txn ngan chup config_revision+secret_version+decrypt+validate; (2) probe NGOAI txn (khong
    giu row-lock); (3) txn ngan ghi last_test CHI khi revision van khop — nguoc lai bo ket qua stale.
    Ket qua REDACTED (ok/latency/error class), khong echo header/token."""
    # ---- PHA 1: snapshot (transaction ngan, KHONG giu qua network) ----
    async with conn.transaction():
        r = await conn.fetchrow("SELECT * FROM integrations WHERE id=$1", integration_id)
        if not r:
            raise SettingsNotFound("integration khong ton tai")
        if r["provider"] != "ghn":
            raise SettingsError("test-connection: chi ho tro GHN o GD1")
        cp = json.loads(r["config_public"]) if isinstance(r["config_public"], str) else (r["config_public"] or {})
        _require_ghn_complete(cp)   # 307-03: thieu pickup/quote -> khong test (khong probe)
        token = await _decrypt_secret(conn, integration_id, "ghn", "token")
        sec_ver = await conn.fetchval(
            "SELECT version FROM integration_secrets WHERE integration_id=$1 AND key_name='token'", integration_id)
        snap_cfg_rev = r["config_revision"]
    if not token:
        raise SettingsError("thieu secret token — nhap truoc khi test")

    # ---- PHA 2: probe NGOAI transaction (khong giu DB row-lock) ----
    from app.services.providers import ghn as _ghn
    cfg = {"base": (cp.get("base_url") or _GHN_STAGING_BASE).rstrip("/"), "token": token, "shop_id": str(cp["shop_id"]),
           "timeout": float(cp.get("timeout_seconds") or 8.0), "retries": int(cp.get("max_retries") or 1)}
    _post = post or _ghn._post
    st, js, err, dur = await _post(cfg, "/master-data/province", {}, retries=cfg["retries"])
    if err or st != 200 or not isinstance(js, dict) or js.get("code") != 200:
        ec = "timeout" if err == "timeout" else (f"http_{st}" if st else (err or "error"))
        result = {"ok": False, "error_class": ec, "latency_ms": dur}
    else:
        result = {"ok": True, "capability": "master-data:read", "province_count": len(js.get("data") or []),
                  "latency_ms": dur}

    # ---- PHA 3: ghi ket qua CHI khi revision van khop (bo stale) ----
    async with conn.transaction():
        cur = await conn.fetchrow("SELECT config_revision FROM integrations WHERE id=$1 FOR UPDATE", integration_id)
        if not cur:
            raise SettingsNotFound("integration khong ton tai")
        cur_sec = await conn.fetchval(
            "SELECT version FROM integration_secrets WHERE integration_id=$1 AND key_name='token'", integration_id)
        if cur["config_revision"] != snap_cfg_rev or cur_sec != sec_ver:
            result = {**result, "stale": True}
            await _audit(conn, "settings.integration.test", actor, integration_id,
                         {"ok": result["ok"], "stale": True})
            return result   # KHONG ghi last_test — config/secret da doi trong luc probe
        await conn.execute(
            "UPDATE integrations SET last_test_status=$2, last_test_at=now(), last_test_config_version=$3, "
            "last_test_secret_version=$4, last_test_detail=$5::jsonb, updated_at=now() WHERE id=$1",
            integration_id, "pass" if result["ok"] else "fail", snap_cfg_rev, sec_ver, json.dumps(result))
        await _audit(conn, "settings.integration.test", actor, integration_id,
                     {"ok": result["ok"], "error_class": result.get("error_class")})
    return result


# ------------------------------------------------------------------ enable / disable / archive
async def enable(conn, integration_id: int, *, expected_version: int, actor: str, command_key: str) -> dict:
    """Bat CHI khi latest test PASS va khop config_revision + secret version hien hanh (CA 305-06, 307-05)."""
    fp = _payload_fp("enable", integration_id, {"v": expected_version})

    async def _do():
        r = await _lock(conn, integration_id, expected_version)
        _, _, secret_keys, _ = _ALLOW[r["provider"]]
        for k in secret_keys:
            if not await conn.fetchval("SELECT 1 FROM integration_secrets WHERE integration_id=$1 AND key_name=$2",
                                       integration_id, k):
                raise SettingsError(f"thieu secret '{k}' — nhap truoc khi bat")
        if r["provider"] == "ghn":
            cp = json.loads(r["config_public"]) if isinstance(r["config_public"], str) else (r["config_public"] or {})
            _require_ghn_complete(cp)
        if r["last_test_status"] != "pass":
            raise SettingsError("chua co test-connection PASS — test truoc khi bat")
        if r["last_test_config_version"] != r["config_revision"]:
            raise SettingsError("config/secret da doi sau test — test lai truoc khi bat")
        sec_ver = await conn.fetchval("SELECT max(version) FROM integration_secrets WHERE integration_id=$1",
                                      integration_id)
        if r["last_test_secret_version"] != sec_ver:
            raise SettingsError("secret da doi sau test — test lai truoc khi bat")
        # enable bump LIFECYCLE version, KHONG dung config_revision -> test van current (307-05).
        row = await conn.fetchrow(
            "UPDATE integrations SET enabled=true, version=version+1, updated_at=now(), updated_by=$2 "
            "WHERE id=$1 AND version=$3 RETURNING *", integration_id, actor, expected_version)
        if row is None:
            raise SettingsConflict("version conflict (concurrent) — huy")
        await _audit(conn, "settings.integration.enable", actor, integration_id, {"version": row["version"]})
        return _row_public(row)

    return await _run_command(conn, command_key=command_key, action="enable",
                              integration_id=integration_id, payload_fp=fp, fn=_do)


async def disable(conn, integration_id: int, *, expected_version: int, actor: str, command_key: str) -> dict:
    fp = _payload_fp("disable", integration_id, {"v": expected_version})

    async def _do():
        await _lock(conn, integration_id, expected_version)
        # disable KHONG dung config_revision -> test binding giu nguyen (bat lai khong buoc retest neu config/secret khong doi).
        row = await conn.fetchrow(
            "UPDATE integrations SET enabled=false, version=version+1, updated_at=now(), updated_by=$2 "
            "WHERE id=$1 AND version=$3 RETURNING *", integration_id, actor, expected_version)
        if row is None:
            raise SettingsConflict("version conflict (concurrent) — huy")
        await _audit(conn, "settings.integration.disable", actor, integration_id, {"version": row["version"]})
        return _row_public(row)

    return await _run_command(conn, command_key=command_key, action="disable",
                              integration_id=integration_id, payload_fp=fp, fn=_do)


async def archive(conn, integration_id: int, *, expected_version: int, actor: str, command_key: str) -> dict:
    fp = _payload_fp("archive", integration_id, {"v": expected_version})

    async def _do():
        r = await _lock(conn, integration_id, expected_version)
        if r["archived_at"] is not None:
            raise SettingsNotFound("integration da archive")
        row = await conn.fetchrow(
            "UPDATE integrations SET enabled=false, archived_at=now(), version=version+1, updated_at=now(), "
            "updated_by=$2 WHERE id=$1 AND version=$3 AND archived_at IS NULL RETURNING version",
            integration_id, actor, expected_version)
        if row is None:
            raise SettingsConflict("version conflict (concurrent) — huy")
        await _audit(conn, "settings.integration.archive", actor, integration_id, {"version": row["version"]})
        return {"archived": True, "integration_version": row["version"]}

    return await _run_command(conn, command_key=command_key, action="archive",
                              integration_id=integration_id, payload_fp=fp, fn=_do)


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
