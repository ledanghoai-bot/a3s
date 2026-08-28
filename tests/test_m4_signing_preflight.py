"""M4 — Unit test preflight_checks THUAN (fake deps, KHONG DB/Redis/KMS). Roadmap Buoc 1.

Kiem tung check LAM VIEC THAT + fail-closed. Trong tam: "xanh vi khong co gi de kiem" bi cam —
thieu backend/config/khong doc duoc PHAI ra passed=False.
"""
import asyncio
import datetime as _dt

from app.services.m4_signing import preflight_checks as P

PUB32 = b"\x11" * 32


def run(coro):
    return asyncio.run(coro)


class FakeConn:
    """conn gia: dispatch theo chuoi SQL. Cac gia tri tra do test dat."""

    def __init__(self, *, registry_pub=PUB32, control=("frozen0", False, None),
                 db_now=None, other_active=0):
        self._registry_pub = registry_pub          # bytes | None
        self._control = control                     # (marker, frozen, incident) | None
        self._db_now = db_now or _dt.datetime.now(_dt.timezone.utc)
        self._other_active = other_active

    async def fetchrow(self, sql, *args):
        if "m4_stage0p_transcript_public_keys" in sql:
            return None if self._registry_pub is None else {"public_key": self._registry_pub}
        if "m4_signing_control" in sql:
            if self._control is None:
                return None
            _, frozen, incident = self._control
            return {"signing_frozen": frozen, "incident_ref": incident}
        raise AssertionError(f"fetchrow bat ngo: {sql}")

    async def fetchval(self, sql, *args):
        if "SELECT now()" in sql:
            return self._db_now
        if "count(*) FROM m4_signing_activation" in sql:
            return self._other_active
        raise AssertionError(f"fetchval bat ngo: {sql}")


class FakeBackend:
    def __init__(self, pub=PUB32, key_id="m4-transcript-ed25519-localdev", key_version="localdev:v1"):
        self._pub, self._kid, self._kv = pub, key_id, key_version

    def public_key_raw(self, key_version=None):
        return self._pub

    def key_id(self):
        return self._kid

    def key_version(self):
        return self._kv


class BackendErr(Exception):
    MA = "backend_unavailable"


# ---------- kms_wif_health ----------
def test_kms_pass_when_pubkey_matches_registry():
    ok, detail = run(P.check_kms_wif_health(FakeConn(registry_pub=PUB32),
                                            backend_factory=lambda: FakeBackend(pub=PUB32)))
    assert ok, detail


def test_kms_fail_closed_when_backend_raises():
    def boom():
        raise BackendErr("khong reachable")
    ok, detail = run(P.check_kms_wif_health(FakeConn(), backend_factory=boom))
    assert not ok and "backend_unavailable" in detail


def test_kms_fail_when_no_live_registry_key():
    ok, detail = run(P.check_kms_wif_health(FakeConn(registry_pub=None),
                                            backend_factory=lambda: FakeBackend()))
    assert not ok and "no_live_registry_key" in detail


def test_kms_fail_when_pubkey_mismatch_registry():
    ok, detail = run(P.check_kms_wif_health(FakeConn(registry_pub=b"\x22" * 32),
                                            backend_factory=lambda: FakeBackend(pub=PUB32)))
    assert not ok and "mismatch" in detail


def test_kms_fail_when_pubkey_bad_length():
    ok, detail = run(P.check_kms_wif_health(FakeConn(),
                                            backend_factory=lambda: FakeBackend(pub=b"\x11" * 10)))
    assert not ok and "bad_length" in detail


# ---------- cert_chain ----------
def test_cert_pass_when_token_obtained():
    ok, detail = run(P.check_cert_chain(token_provider=lambda: "ya29.fake", localdev_ok=False))
    assert ok, detail


def test_cert_fail_closed_when_no_config_and_not_localdev():
    ok, detail = run(P.check_cert_chain(token_provider=None, localdev_ok=False))
    assert not ok and "not_configured" in detail


def test_cert_localdev_labeled_pass_only_when_localdev_ok():
    ok, detail = run(P.check_cert_chain(token_provider=None, localdev_ok=True))
    assert ok and "localdev" in detail


def test_cert_fail_closed_when_token_raises():
    def boom():
        raise BackendErr("STS chet")
    ok, detail = run(P.check_cert_chain(token_provider=boom, localdev_ok=False))
    assert not ok and "backend_unavailable" in detail


def test_cert_fail_when_token_empty():
    ok, detail = run(P.check_cert_chain(token_provider=lambda: "", localdev_ok=False))
    assert not ok and "empty" in detail


# ---------- clock_nonce_replay ----------
def test_clock_nonce_pass():
    async def ping():
        return True
    ok, detail = run(P.check_clock_nonce_replay(FakeConn(), redis_ping=ping))
    assert ok, detail


def test_clock_fail_when_skew_too_large():
    old = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=30)

    async def ping():
        return True
    ok, detail = run(P.check_clock_nonce_replay(FakeConn(db_now=old), redis_ping=ping))
    assert not ok and "clock_skew" in detail


def test_clock_nonce_fail_closed_when_redis_raises():
    async def ping():
        raise RuntimeError("redis down")
    ok, detail = run(P.check_clock_nonce_replay(FakeConn(), redis_ping=ping))
    assert not ok and "nonce_store_unreachable" in detail


def test_clock_nonce_fail_when_ping_false():
    async def ping():
        return False
    ok, detail = run(P.check_clock_nonce_replay(FakeConn(), redis_ping=ping))
    assert not ok and "ping_false" in detail


# ---------- no_conflicting_incident ----------
def test_incident_pass_when_not_frozen_no_conflict():
    ok, detail = run(P.check_no_conflicting_incident(FakeConn(control=("m", False, None),
                                                              other_active=0), "AID"))
    assert ok, detail


def test_incident_fail_when_frozen():
    ok, detail = run(P.check_no_conflicting_incident(
        FakeConn(control=("m", True, "INC-9")), "AID"))
    assert not ok and "signing_frozen" in detail and "INC-9" in detail


def test_incident_fail_closed_when_control_missing():
    ok, detail = run(P.check_no_conflicting_incident(FakeConn(control=None), "AID"))
    assert not ok and "control_missing" in detail


def test_incident_fail_when_conflicting_active():
    ok, detail = run(P.check_no_conflicting_incident(
        FakeConn(control=("m", False, None), other_active=1), "AID"))
    assert not ok and "conflicting_active_activation" in detail


# ---------- run_all aggregate + fail-closed on unexpected ----------
def test_run_all_all_pass_localdev():
    async def ping():
        return True
    res = run(P.run_all(FakeConn(), activation_id="AID",
                        backend_factory=lambda: FakeBackend(pub=PUB32),
                        token_provider=None, redis_ping=ping, localdev_ok=True))
    names = {c["name"] for c in res}
    assert names == {"kms_wif_health", "cert_chain", "clock_nonce_replay", "no_conflicting_incident"}
    assert all(c["passed"] for c in res), res


def test_run_all_fail_closed_on_unexpected_exception():
    # backend_factory nem loi la (khong .MA); check phai fail-closed, run_all khong vo.
    def boom():
        raise ValueError("bat ngo")

    async def ping():
        return True
    res = run(P.run_all(FakeConn(), activation_id="AID", backend_factory=boom,
                        token_provider=lambda: "t", redis_ping=ping, localdev_ok=False))
    kms = next(c for c in res if c["name"] == "kms_wif_health")
    assert not kms["passed"] and "ValueError" in kms["detail"]
