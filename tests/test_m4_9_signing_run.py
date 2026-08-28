"""M4-9 — Unit test THUAN (khong DB) cho signing-run control surface.

Kiem cac bat bien logic khong can DB:
- TRANSITIONS la allowlist dong nhat; moi state khong-terminal deu co 'abort'.
- _assert_no_secret bat cac chuoi giong secret o payload JSON.
- cli_adapter._classify fail-closed (chi PASS khi thay dung marker) + bat CLEANUP_FAILED.
- redact() che secret.
- Parity: nut UI (ACTIONS trong dashboard) khop transition backend (kiem thu cong qua danh sach).

Integration co DB (create_run/transition/ledger/quota/SoD/preflight/rehearsal) nam o
scripts/m4_9_signing_run_test.py (evidence, chay voi DATABASE_URL that).
"""
import pytest

from app.services.m4_signing import cli_adapter, run_store
from app.services.m4_signing.run_store import SecretLeakBlocked

# --- TRANSITIONS -------------------------------------------------------------
NON_TERMINAL = set(run_store.TRANSITIONS) - run_store.TERMINAL_STATES


def test_terminal_states_have_no_transitions():
    for s in run_store.TERMINAL_STATES:
        assert run_store.TRANSITIONS[s] == {}, f"{s} terminal nhung con transition"


def test_every_active_state_can_abort():
    for s in NON_TERMINAL:
        assert "abort" in run_store.TRANSITIONS[s], f"{s} khong the abort"
        assert run_store.TRANSITIONS[s]["abort"] == "ABORTED"


def test_transitions_point_to_known_states():
    all_states = set(run_store.TRANSITIONS)
    for s, evmap in run_store.TRANSITIONS.items():
        for ev, to in evmap.items():
            assert to in all_states, f"{s}--{ev}-->{to} khong phai state hop le"


def test_happy_path_reaches_closed():
    # CREATED -> ... -> CLOSED bang chuoi event mong doi
    chain = [("confirm", "CONFIRMED"), ("preflight_pass", "PREFLIGHT_PASSED"),
             ("ceremony_record", "CEREMONY_RECORDED"), ("canary_request", "CANARY_PENDING"),
             ("canary_approve", "CANARY_APPROVED"), ("execute_start", "EXECUTING"),
             ("execute_success", "CLOSED")]
    state = "CREATED"
    for ev, expected in chain:
        state = run_store.TRANSITIONS[state][ev]
        assert state == expected


def test_invalid_transition_not_in_allowlist():
    # Khong the execute thang tu CREATED
    assert "execute_start" not in run_store.TRANSITIONS["CREATED"]
    # Khong the canary_approve khi chua CANARY_PENDING
    assert "canary_approve" not in run_store.TRANSITIONS["CONFIRMED"]


# --- no-secret ---------------------------------------------------------------
@pytest.mark.parametrize("payload", [
    {"pin_secret": "x"},
    {"note": "-----BEGIN PRIVATE KEY-----"},
    {"a": {"token": "abc"}},
    {"pw": "my password here"},
    "ya29.abcdef",
])
def test_assert_no_secret_blocks(payload):
    with pytest.raises(SecretLeakBlocked):
        run_store._assert_no_secret(payload, "test")


@pytest.mark.parametrize("payload", [
    {"batch": "synthetic-v1"},
    {"cert_fingerprint": "7D:67:ED:50"},
    {"scope": "pii-eval", "count": 200},
    None,
])
def test_assert_no_secret_allows_clean(payload):
    run_store._assert_no_secret(payload, "test")  # khong raise


# --- cli_adapter._classify (fail-closed) -------------------------------------
def test_classify_dry_run_pass():
    ok, sig, danger = cli_adapter._classify(0, "...\ndry_run_ready\n...", "dry_run")
    assert ok and sig == "dry_run_ready" and not danger


def test_classify_requires_marker_even_on_exit0():
    ok, sig, danger = cli_adapter._classify(0, "no marker here", "dry_run")
    assert not ok and sig == "fail"


def test_classify_nonzero_exit_fails():
    ok, sig, danger = cli_adapter._classify(1, "dry_run_ready", "dry_run")
    assert not ok


def test_classify_cleanup_failed_is_danger():
    ok, sig, danger = cli_adapter._classify(0, "rehearsal_execute_succeeded\nCLEANUP_FAILED", "execute")
    assert not ok and danger and sig == "cleanup_failed"


def test_classify_execute_pass():
    ok, sig, danger = cli_adapter._classify(0, "rehearsal_execute_succeeded", "execute")
    assert ok and sig == "execute_ok" and not danger


# --- redact ------------------------------------------------------------------
def test_redact_hides_secrets():
    s = cli_adapter.redact("pin_secret=abc token=xyz ya29.SECRETTOKEN password=p")
    assert "abc" not in s or "[REDACTED]" in s
    assert "ya29.SECRETTOKEN" not in s
    assert "[REDACTED]" in s


# --- Tiered model: _evaluate_escalation (Review 64) --------------------------
def test_escalation_tier_a_clean_stays():
    kind, flags = run_store._evaluate_escalation(
        "evidence_batch", scope={"batch_size": 100}, data_boundary={}, quota_sts=3, quota_sign=3)
    assert kind == "evidence_batch" and flags == []


def test_escalation_non_repudiation_forces_production():
    kind, flags = run_store._evaluate_escalation(
        "evidence_batch", scope={}, data_boundary={"non_repudiation": True},
        quota_sts=3, quota_sign=3)
    assert kind == "production" and "non_repudiation_or_external" in flags


def test_escalation_unmasked_pii_forces_production():
    kind, flags = run_store._evaluate_escalation(
        "evidence_batch", scope={}, data_boundary={"unmasked_pii": True},
        quota_sts=3, quota_sign=3)
    assert kind == "production" and "pii_outside_scope" in flags


def test_escalation_batch_over_cap():
    kind, flags = run_store._evaluate_escalation(
        "evidence_batch", scope={"batch_size": 261}, data_boundary={}, quota_sts=3, quota_sign=3)
    assert kind == "production" and any("batch_over_cap" in f for f in flags)


def test_escalation_quota_over_routine():
    kind, flags = run_store._evaluate_escalation(
        "evidence_batch", scope={}, data_boundary={}, quota_sts=6, quota_sign=3)
    assert kind == "production" and any("quota_over_routine" in f for f in flags)


def test_escalation_production_never_downgraded():
    kind, flags = run_store._evaluate_escalation(
        "production", scope={"batch_size": 10}, data_boundary={}, quota_sts=3, quota_sign=3)
    assert kind == "production" and flags == []


def test_batch_cap_and_quota_cap_values():
    # Cap CA chot (Review 64): batch 260, quota routine 5.
    assert run_store.ROUTINE_BATCH_CAP == 260
    assert run_store.ROUTINE_QUOTA_CAP == 5


def test_worker_env_rejects_secret_keys():
    with pytest.raises(ValueError):
        cli_adapter._worker_env({"STAGE0P_REHEARSAL_OPERATOR_PIN": "x"})
    # key khong nhay cam thi cho phep
    env = cli_adapter._worker_env({"M4_STAGE0P_SIGNING_SOCKET": "/run/x.sock"})
    assert env["M4_STAGE0P_SIGNING_SOCKET"] == "/run/x.sock"
