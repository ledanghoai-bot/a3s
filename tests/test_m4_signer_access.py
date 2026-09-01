"""M4 — Unit test THUAN (khong DB) cho signer_access state machine + constants (Directive 91)."""

from app.services.m4_signing import signer_access as SA

NON_TERMINAL = set(SA.TRANSITIONS) - SA.TERMINAL


def test_role_key_allowlist():
    assert SA.ROLE_KEY == "m4_signing_operator"


def test_terminal_states_no_transition():
    for s in SA.TERMINAL:
        assert SA.TRANSITIONS[s] == {}


def test_every_active_state_can_revoke():
    for s in NON_TERMINAL:
        assert SA.TRANSITIONS[s].get("revoke") == "REVOKED"


def test_transitions_point_to_known_states():
    alls = set(SA.TRANSITIONS)
    for _s, m in SA.TRANSITIONS.items():
        for _ev, to in m.items():
            assert to in alls


def test_happy_path_submit_to_closed():
    st = "SUBMITTED"
    for ev, exp in [("preflight_pass", "PREFLIGHT_PASSED"), ("approve", "ACTIVE"), ("close", "CLOSED")]:
        st = SA.TRANSITIONS[st][ev]
        assert st == exp


def test_cannot_approve_before_preflight():
    assert "approve" not in SA.TRANSITIONS["SUBMITTED"]


def test_active_can_expire():
    assert SA.TRANSITIONS["ACTIVE"].get("expire") == "EXPIRED"


def test_preflight_fresh_constant():
    assert SA.PREFLIGHT_FRESH_SECONDS == 15 * 60
