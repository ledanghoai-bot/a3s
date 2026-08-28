"""M4 — Unit test THUAN (khong DB) cho activation state machine + constants (Design 71/72)."""

from app.services.m4_signing import activation as A

NON_TERMINAL = set(A.TRANSITIONS) - A.TERMINAL


def test_capability_separate():
    assert A.ACTIVATE_CAP == "m4.signing.activate.production"


def test_terminal_states_no_transition():
    for s in A.TERMINAL:
        assert A.TRANSITIONS[s] == {}


def test_every_active_state_can_revoke():
    for s in NON_TERMINAL:
        assert A.TRANSITIONS[s].get("revoke") == "REVOKED"


def test_transitions_point_to_known_states():
    alls = set(A.TRANSITIONS)
    for s, m in A.TRANSITIONS.items():
        for ev, to in m.items():
            assert to in alls


def test_happy_path_reaches_active_then_closed():
    st = "REQUESTED"
    for ev, exp in [("preflight_pass", "PREFLIGHT_PASSED"), ("approve", "APPROVED"),
                    ("activate", "ACTIVE"), ("close", "CLOSED")]:
        st = A.TRANSITIONS[st][ev]
        assert st == exp


def test_cannot_activate_before_approved():
    assert "activate" not in A.TRANSITIONS["REQUESTED"]
    assert "activate" not in A.TRANSITIONS["PREFLIGHT_PASSED"]


def test_approved_and_active_can_expire():
    assert A.TRANSITIONS["APPROVED"].get("expire") == "EXPIRED"
    assert A.TRANSITIONS["ACTIVE"].get("expire") == "EXPIRED"


def test_ttl_and_freshness_constants():
    assert A.PREFLIGHT_FRESH_SECONDS == 15 * 60
