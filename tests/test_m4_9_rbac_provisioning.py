"""M4-9 — Unit test THUAN (khong DB) cho RBAC provisioning hardening (Directive 70 + 70A)."""
import pytest

from app.services.m4_signing import rbac_provisioning as rp


def test_operator_role_and_perms_allowlist():
    assert rp.OPERATOR_ROLE == "m4_signing_operator"
    assert set(rp.OPERATOR_PERMS) == {
        "m4.signing.run.view", "m4.signing.run.start", "m4.signing.run.operate",
        "m4.signing.run.approve", "m4.signing.run.abort"}
    assert len(rp.OPERATOR_PERMS) == 5  # least privilege — dung 5, khong hon


@pytest.mark.parametrize("actor,reason,ticket", [
    ("", "r", "t"), ("a", "", "t"), ("a", "r", ""), (None, "r", "t"),
    ("a", None, "t"), ("a", "r", None), ("  ", "r", "t"),
])
def test_require_auth_fail_closed(actor, reason, ticket):
    with pytest.raises(rp.ProvisioningError):
        rp._require_auth(actor, reason, ticket)


def test_require_auth_ok():
    rp._require_auth("hoai", "cap operator", "M4-9-OPS-1")  # khong raise
