"""M4 — Preflight checks THAT cho production signing activation (Roadmap Buoc 1).

Thay 4 stub cu (`return True`) bang check LAM VIEC THAT + fail-closed. Nguyen tac:
  - Moi check tra (passed: bool, detail: str). KHONG raise ra ngoai — moi ngoai le -> fail-closed
    (passed=False, detail=ma ly do). "Xanh vi khong co gi de kiem" bi cam: thieu backend/config/
    khong doc duoc -> FAIL, khong pass.
  - Dependency injected (backend_factory / token_provider / redis_ping) => unit test bang fake,
    production wire tu settings/env. Truoc khi KMS/WIF provision (Buoc 2/3) cac check ngoai se
    fail-closed dung nhu thiet ke — khong the preflight-pass khi dormant.

Cac check:
  kms_wif_health      — backend.public_key_raw() (doc, KHONG ky) + doi chieu registry public key.
  cert_chain          — WIF token doi duoc (STS) = cert chain hop le & tin cay. (localdev: N/A co nhan.)
  clock_nonce_replay  — clock skew app-vs-DB trong nguong + nonce store (Redis) reachable.
  no_conflicting_incident — m4_signing_control.signing_frozen=false + khong activation APPROVED/ACTIVE khac.
"""
from __future__ import annotations

import datetime as _dt

# Nguong lech dong ho app-vs-DB toi da (giay). Vuot => fail-closed.
CLOCK_SKEW_MAX_SECONDS = 5.0


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


async def check_kms_wif_health(conn, *, backend_factory) -> tuple[bool, str]:
    """Reachability KMS/WIF: lay public key (KHONG ky) + khop registry. Fail-closed moi loi backend."""
    try:
        backend = backend_factory()  # co the raise SigningBackendError
        pub = backend.public_key_raw()
        if not isinstance(pub, (bytes, bytearray)) or len(pub) != 32:
            return False, "kms_pubkey_bad_length"
        key_id = backend.key_id()
        key_ver = backend.key_version()
    except Exception as e:  # noqa: BLE001 — fail-closed, khong leak chi tiet provider
        ma = getattr(e, "MA", None)
        return False, f"kms_backend_error:{ma or type(e).__name__}"
    row = await conn.fetchrow(
        "SELECT public_key FROM m4_stage0p_transcript_public_keys "
        "WHERE key_id=$1 AND key_version=$2 AND retired_at IS NULL", key_id, key_ver)
    if row is None:
        return False, f"kms_no_live_registry_key:{key_id}:{key_ver}"
    if bytes(row["public_key"]) != bytes(pub):
        return False, "kms_pubkey_registry_mismatch"
    return True, f"kms reachable, pubkey khop registry {key_id}:{key_ver}"


async def check_cert_chain(*, token_provider, localdev_ok: bool) -> tuple[bool, str]:
    """WIF X.509: lay duoc token = cert chain hop le & trust. localdev (sandbox): N/A co nhan ro."""
    if token_provider is None:
        if localdev_ok:
            return True, "localdev — khong co WIF cert (sandbox only, da guard)"
        return False, "wif_credential_not_configured"
    try:
        tok = token_provider()  # co the raise SigningBackendError (Unavailable/Denied/Misconfigured)
        if not (isinstance(tok, str) and tok):
            return False, "wif_token_empty"
    except Exception as e:  # noqa: BLE001 — fail-closed
        ma = getattr(e, "MA", None)
        return False, f"wif_cert_error:{ma or type(e).__name__}"
    return True, "WIF token doi duoc (cert chain hop le)"


async def check_clock_nonce_replay(conn, *, redis_ping) -> tuple[bool, str]:
    """Clock skew app-vs-DB trong nguong + nonce store (Redis) reachable. Fail-closed neu Redis chet."""
    try:
        db_now = await conn.fetchval("SELECT now()")
        skew = abs((_now() - db_now).total_seconds())
    except Exception as e:  # noqa: BLE001
        return False, f"clock_read_error:{type(e).__name__}"
    if skew > CLOCK_SKEW_MAX_SECONDS:
        return False, f"clock_skew_qua_lon:{skew:.2f}s"
    try:
        ok = await redis_ping()
    except Exception as e:  # noqa: BLE001 — Redis chet => fail-closed (nonce/replay khong bao ve duoc)
        return False, f"nonce_store_unreachable:{type(e).__name__}"
    if not ok:
        return False, "nonce_store_ping_false"
    return True, f"clock skew {skew:.2f}s ok, nonce store reachable"


async def check_no_conflicting_incident(conn, activation_id) -> tuple[bool, str]:
    """signing_frozen=false (doc tuoi) + khong activation APPROVED/ACTIVE khac. Fail-closed neu thieu control."""
    try:
        ctl = await conn.fetchrow(
            "SELECT signing_frozen, incident_ref FROM m4_signing_control WHERE id=1")
    except Exception as e:  # noqa: BLE001 — bang thieu/khong doc duoc => fail-closed
        return False, f"signing_control_unreadable:{type(e).__name__}"
    if ctl is None:
        return False, "signing_control_missing"
    if ctl["signing_frozen"]:
        return False, f"signing_frozen:{ctl['incident_ref'] or 'no-ref'}"
    other = await conn.fetchval(
        "SELECT count(*) FROM m4_signing_activation "
        "WHERE state IN ('APPROVED','ACTIVE') AND activation_id <> $1", activation_id)
    if other and other > 0:
        return False, f"conflicting_active_activation:{other}"
    return True, "khong dong bang, khong activation dang mo khac"


async def run_all(conn, *, activation_id, backend_factory, token_provider, redis_ping,
                  localdev_ok: bool) -> list[dict]:
    """Chay 4 check that, tra list {name,passed,detail}. Moi check tu fail-closed (khong raise ra)."""
    results = []

    async def run(name, coro):
        try:
            passed, detail = await coro
        except Exception as e:  # noqa: BLE001 — lop bao ve cuoi: bat ke loi gi -> fail-closed
            passed, detail = False, f"check_exception:{type(e).__name__}"
        results.append({"name": name, "passed": passed, "detail": detail})

    await run("kms_wif_health", check_kms_wif_health(conn, backend_factory=backend_factory))
    await run("cert_chain", check_cert_chain(token_provider=token_provider, localdev_ok=localdev_ok))
    await run("clock_nonce_replay", check_clock_nonce_replay(conn, redis_ping=redis_ping))
    await run("no_conflicting_incident", check_no_conflicting_incident(conn, activation_id))
    return results
