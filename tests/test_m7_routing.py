"""M7 routing — unit (logic thuan, Directive 272 §3.2). allowlist -> SELF; hop le ngoai list -> GHN; thieu/mo ho -> MANUAL."""
from app.services.fulfillment import routing as r

ALLOW = {("66", "24121"), ("66", "24133"), ("66", "24154"), ("66", "24163"), ("66", "24169")}


def test_allowlist_wards_self_delivery():
    for pc, wc in sorted(ALLOW):
        out = r.resolve(pc, wc, allow=ALLOW, version=1)
        assert (out.source, out.reason, out.version) == (r.SELF_DELIVERY, "ward_in_allowlist", 1)


def test_valid_ward_outside_allowlist_is_ghn():
    for pc, wc in (("66", "24305"), ("66", "24340"), ("66", "24316"), ("01", "00004"), ("79", "26734")):
        out = r.resolve(pc, wc, allow=ALLOW, version=1)
        assert out.source == r.GHN and out.reason == "ward_outside_allowlist"


def test_missing_or_ambiguous_codes_manual_review():
    assert r.resolve(None, None, allow=ALLOW, version=1).source == r.MANUAL_REVIEW
    assert r.resolve("66", None, allow=ALLOW, version=1).reason == "address_missing_codes"
    assert r.resolve("", "24121", allow=ALLOW, version=1).source == r.MANUAL_REVIEW
    assert r.resolve("  ", "  ", allow=ALLOW, version=1).source == r.MANUAL_REVIEW


def test_no_active_version_fail_closed_manual():
    out = r.resolve("66", "24121", allow=set(), version=None)
    assert out.source == r.MANUAL_REVIEW and out.reason == "no_active_routing_version"


def test_ward_code_exact_match_no_prefix_or_province_guess():
    # ma phuong dung nhung tinh khac -> KHONG tu suy la noi thanh
    assert r.resolve("79", "24121", allow=ALLOW, version=1).source == r.GHN
    # ma gan giong -> khong khop
    assert r.resolve("66", "2412", allow=ALLOW, version=1).source == r.GHN


def test_version_change_does_not_alter_previous_result():
    v1 = r.resolve("66", "24305", allow=ALLOW, version=1)
    v2 = r.resolve("66", "24305", allow=ALLOW | {("66", "24305")}, version=2)
    assert v1.source == r.GHN and v2.source == r.SELF_DELIVERY and v1.version == 1 and v2.version == 2
