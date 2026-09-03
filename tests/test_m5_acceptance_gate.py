"""M5 Phase 1 — Acceptance gate unit tests (logic thuan, khong cham DB). CA Directive 104.

Test CA CAP co-dau/khong-dau cho address (bai hoc tieng Viet) + tung failure mode cua 8 kiem tra.
"""
from app.services.address import acceptance_gate as g


def _good_dataset():
    units = [
        {"level": "province", "code": "P01", "name": "Cà Mau", "parent_code": None},
        {"level": "district", "code": "D01", "name": "Đầm Dơi", "parent_code": "P01"},
        {"level": "ward", "code": "W01", "name": "Tân Duyệt", "parent_code": "D01"},
    ]
    aliases = [
        {"unit_code": "P01", "alias_name": "Ca Mau", "alias_kind": "accentless"},
        {"unit_code": "D01", "alias_name": "Dam Doi", "alias_kind": "accentless"},
    ]
    prov = {"source_url": "https://danhmuchanhchinh.nso.gov.vn/x", "source_kind": "authoritative",
            "downloaded_at": "2025-07-01", "license": "OGL", "first_version": True,
            "expected_counts": {"province": 1, "district": 1, "ward": 1}}
    sha = g.canonical_checksum(units, aliases)
    return units, aliases, prov, sha


def test_normalize_accent_and_d():
    assert g.normalize("Cà Mau") == g.normalize("Ca Mau") == "ca mau"
    assert g.normalize("Đầm Dơi") == "dam doi"


def test_good_dataset_passes_all_8():
    units, aliases, prov, sha = _good_dataset()
    rep = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                declared_sha256=sha)
    assert rep["passed"], [c for c in rep["checks"] if not c["ok"]]
    assert len(rep["checks"]) == 8
    assert rep["topology"] == "3-tier"  # regression: 3-tier van pass + ghi topology


def _two_tier():
    """CA Review 122: dataset 2 cap (Tinh->Xa), khong district; ward parent = province."""
    units = [
        {"level": "province", "code": "01", "name": "Thành phố Hà Nội", "parent_code": None},
        {"level": "ward", "code": "00004", "name": "Phường Ba Đình", "parent_code": "01"},
        {"level": "ward", "code": "00008", "name": "Phường Hoàn Kiếm", "parent_code": "01"},
    ]
    aliases = [{"unit_code": "00004", "alias_name": "Phường Trúc Bạch", "alias_kind": "legacy"}]
    prov = {"source_url": "https://danhmuchanhchinh.nso.gov.vn/", "source_kind": "authoritative",
            "downloaded_at": "2025-07-01", "license": "OGL", "first_version": True,
            "expected_counts": {"province": 1, "ward": 2}}
    return units, aliases, prov, g.canonical_checksum(units, aliases)


def test_two_tier_passes_topology_recorded():
    units, aliases, prov, sha = _two_tier()
    rep = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                declared_sha256=sha)
    assert rep["passed"], [c for c in rep["checks"] if not c["ok"]]
    assert rep["topology"] == "2-tier"


def test_mixed_topology_fails():
    # co district nhung 1 ward tro thang province -> hybrid -> fail-closed (khong "uu tien")
    units = [
        {"level": "province", "code": "P01", "name": "Cà Mau", "parent_code": None},
        {"level": "district", "code": "D01", "name": "Đầm Dơi", "parent_code": "P01"},
        {"level": "ward", "code": "W01", "name": "Tân Duyệt", "parent_code": "D01"},
        {"level": "ward", "code": "W02", "name": "Phường X", "parent_code": "P01"},  # bo qua district
    ]
    aliases = []
    prov = {"source_url": "x", "source_kind": "authoritative", "downloaded_at": "2025-07-01",
            "license": "OGL", "first_version": True,
            "expected_counts": {"province": 1, "district": 1, "ward": 2}}
    rep = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                declared_sha256=g.canonical_checksum(units, aliases))
    assert not _check(rep, "parent_child")["ok"]
    assert rep["topology"] == "mixed"


def test_two_tier_orphan_ward_fails():
    units, aliases, prov, _ = _two_tier()
    units[1]["parent_code"] = "99"  # ward tro province khong ton tai
    sha = g.canonical_checksum(units, aliases)
    rep = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                declared_sha256=sha)
    assert not _check(rep, "parent_child")["ok"]
    assert rep["topology"] == "2-tier"


def test_bad_version_format_fails_schema():
    units, aliases, prov, sha = _good_dataset()
    rep = g.run(version="2025-07", units=units, aliases=aliases, provenance=prov, declared_sha256=sha)
    assert not rep["passed"]
    assert not _check(rep, "schema")["ok"]


def test_orphan_ward_fails_parent_child():
    units, aliases, prov, _ = _good_dataset()
    units[2]["parent_code"] = "D99"  # ward tro district khong ton tai
    sha = g.canonical_checksum(units, aliases)
    prov = {**prov, "expected_counts": {"province": 1, "district": 1, "ward": 1}}
    rep = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                declared_sha256=sha)
    assert not _check(rep, "parent_child")["ok"]


def test_coverage_mismatch_fails():
    units, aliases, prov, sha = _good_dataset()
    prov = {**prov, "expected_counts": {"province": 5, "district": 1, "ward": 1}}
    rep = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                declared_sha256=sha)
    assert not _check(rep, "coverage")["ok"]


def test_legacy_canonical_collision_recorded_not_failed():
    # CA Review 126: alias legacy trung canonical unit khac = AMBIGUITY hop le -> KHONG fail, ghi vao report.
    units, aliases, prov, _ = _good_dataset()
    aliases.append({"unit_code": "D01", "alias_name": "Cà Mau", "alias_kind": "legacy"})  # trung canonical P01
    sha = g.canonical_checksum(units, aliases)
    rep = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                declared_sha256=sha)
    assert _check(rep, "duplicate")["ok"]  # khong fail
    assert rep["legacy_name_collisions"]["count"] >= 1
    assert len(rep["legacy_name_collisions"]["digest"]) == 64
    assert rep["legacy_name_collisions"]["version"] == "VN-ADMIN-2025-07-v1"


def test_missing_alias_target_fails_duplicate():
    # alias tro toi unit_code khong ton tai trong dataset -> HARD FAIL (Review 126)
    units, aliases, prov, _ = _good_dataset()
    aliases.append({"unit_code": "NOPE", "alias_name": "Xã Cũ", "alias_kind": "legacy"})
    sha = g.canonical_checksum(units, aliases)
    rep = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                declared_sha256=sha)
    assert not _check(rep, "duplicate")["ok"]


def test_duplicate_code_still_hard_fails():
    # Review 126: trung administrative code van HARD-FAIL gate (qua code_range overlap hoac duplicate).
    units, aliases, prov, _ = _good_dataset()
    units.append({"level": "ward", "code": "W01", "name": "Trùng Mã", "parent_code": "D01"})  # W01 da ton tai
    sha = g.canonical_checksum(units, aliases)
    rep = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                declared_sha256=sha)
    assert not rep["passed"]
    assert not _check(rep, "code_range")["ok"]


def test_checksum_mismatch_fails():
    units, aliases, prov, _ = _good_dataset()
    rep = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                declared_sha256="0" * 64)
    assert not _check(rep, "checksum")["ok"]


def test_missing_provenance_fails():
    units, aliases, _, sha = _good_dataset()
    prov = {"source_kind": "authoritative", "expected_counts": {"province": 1, "district": 1, "ward": 1},
            "first_version": True}  # thieu source_url/downloaded_at/license
    rep = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                declared_sha256=sha)
    assert not _check(rep, "provenance")["ok"]


def test_no_rollback_target_non_first_fails():
    units, aliases, prov, sha = _good_dataset()
    prov = {**prov, "first_version": False}
    rep = g.run(version="VN-ADMIN-2025-08-v2", units=units, aliases=aliases, provenance=prov,
                declared_sha256=sha, has_rollback_target=False)
    assert not _check(rep, "provenance")["ok"]
    rep2 = g.run(version="VN-ADMIN-2025-08-v2", units=units, aliases=aliases, provenance=prov,
                 declared_sha256=sha, has_rollback_target=True)
    assert _check(rep2, "provenance")["ok"]


def test_mapping_regression_accentless_and_legacy():
    units, aliases, prov, sha = _good_dataset()
    reg = [{"legacy": "Ca Mau", "expected_code": "P01"},   # khong dau -> P01
           {"legacy": "Đầm Dơi", "expected_code": "D01"}]  # co dau -> D01
    rep = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                declared_sha256=sha, regression=reg)
    assert _check(rep, "mapping_regress")["ok"], _check(rep, "mapping_regress")["detail"]
    # regression sai -> fail
    rep_bad = g.run(version="VN-ADMIN-2025-07-v1", units=units, aliases=aliases, provenance=prov,
                    declared_sha256=sha, regression=[{"legacy": "Ca Mau", "expected_code": "D01"}])
    assert not _check(rep_bad, "mapping_regress")["ok"]


def _check(rep, name):
    return next(c for c in rep["checks"] if c["check"] == name)
