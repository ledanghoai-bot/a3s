"""I-B M4 H2-B — test cho ke hoach bootstrap IAM (F-PR31-06).

Ke hoach nay sinh ra cac lenh se duoc chay bang quyen cao nhat trong project production signing.
Sai o day khong hong build — no de lai mot binding song lau hon du dinh ma khong ai nhan ra, vi
mot nguoi dang kiem ca bon vai. Nen cac rang buoc cua PO Decision Record duoc test truc tiep.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "m4_h2b_bootstrap_iam_plan", ROOT / "scripts" / "m4_h2b_bootstrap_iam_plan.py"
)
assert _spec and _spec.loader
ke_hoach = importlib.util.module_from_spec(_spec)
sys.modules["m4_h2b_bootstrap_iam_plan"] = ke_hoach
_spec.loader.exec_module(ke_hoach)


def _moc(gio: str) -> datetime:
    return datetime.fromisoformat(gio).replace(tzinfo=timezone.utc)


def test_expiry_bang_cuoi_cua_so_cong_mot_gio():
    bat_dau = _moc("2026-08-21T02:00:00")
    ket_thuc = _moc("2026-08-21T06:00:00")
    assert ke_hoach.tinh_expiry(bat_dau, ket_thuc) == ket_thuc + timedelta(hours=1)


def test_chan_tong_vong_doi_vuot_48_gio():
    """PO Decision Record muc 5: tong lifetime khong vuot 48 gio, khong co ngoai le."""
    bat_dau = _moc("2026-08-21T02:00:00")
    ket_thuc = bat_dau + timedelta(hours=47, minutes=30)  # +1h cleanup => 48h30
    with pytest.raises(SystemExit) as loi:
        ke_hoach.tinh_expiry(bat_dau, ket_thuc)
    assert "48 gio" in str(loi.value)


def test_chap_nhan_dung_muc_48_gio():
    bat_dau = _moc("2026-08-21T02:00:00")
    ket_thuc = bat_dau + timedelta(hours=47)
    assert ke_hoach.tinh_expiry(bat_dau, ket_thuc) == bat_dau + timedelta(hours=48)


def test_chan_cua_so_nguoc():
    bat_dau = _moc("2026-08-21T06:00:00")
    with pytest.raises(SystemExit):
        ke_hoach.tinh_expiry(bat_dau, _moc("2026-08-21T02:00:00"))


def test_dieu_kien_la_timestamp_tuyet_doi_khong_phai_dien_giai():
    """CA doi exact RFC 3339, cam dien dat xap xi kieu 'khoang 48 gio'."""
    dk = ke_hoach.dieu_kien(_moc("2026-08-21T07:00:00"))
    assert 'request.time < timestamp("2026-08-21T07:00:00Z")' in dk
    assert f"title={ke_hoach.TIEU_DE_DIEU_KIEN}" in dk


def test_khong_co_owner_hay_editor_trong_danh_sach_bootstrap():
    roles = {r for r, _ in ke_hoach.ROLE_BOOTSTRAP}
    assert roles.isdisjoint(set(ke_hoach.ROLE_CAM))


def test_moi_role_deu_co_ly_do_bang_resource_cu_the():
    """F-PROV-04: role nao khong bien minh duoc bang resource trong plan thi phai bo."""
    for role, ly_do in ke_hoach.ROLE_BOOTSTRAP:
        assert ly_do.strip(), f"{role} khong co ly do"
        assert len(ly_do) > 15, f"ly do cua {role} qua so sai: {ly_do!r}"


def test_ke_hoach_in_du_bon_phan(capsys):
    ke_hoach.in_ke_hoach(
        "alpha3s-production-signing",
        "user:3scoffee.cs@gmail.com",
        _moc("2026-08-21T02:00:00"),
        _moc("2026-08-21T06:00:00"),
    )
    ra = capsys.readouterr().out
    assert "1. IAM TRUOC KHI GRANT" in ra
    assert "2. GRANT" in ra
    assert "3. REVOKE" in ra
    assert "4. POSTCONDITION" in ra
    # Grant va revoke phai doi xung: cung so lenh, cung condition.
    assert ra.count("add-iam-policy-binding") == len(ke_hoach.ROLE_BOOTSTRAP)
    assert ra.count("remove-iam-policy-binding") == len(ke_hoach.ROLE_BOOTSTRAP)
    assert "PHAI in ra 0" in ra
    # Khong duoc lo mot role nao khong co expiry.
    assert ra.count("--condition=") == 2 * len(ke_hoach.ROLE_BOOTSTRAP)
    # Phai nhac ro expiry khong thay the revoke tay.
    assert "revoke tay" in ra.lower()


def test_canh_bao_owner_editor_nam_trong_ban_in(capsys):
    """CA phai duoc nhac kiem effective IAM truoc gate, ke ca quyen ke thua."""
    ke_hoach.in_ke_hoach(
        "alpha3s-production-signing",
        "user:3scoffee.cs@gmail.com",
        _moc("2026-08-21T02:00:00"),
        _moc("2026-08-21T06:00:00"),
    )
    ra = capsys.readouterr().out
    assert "roles/owner" in ra and "roles/editor" in ra
    assert "least privilege" in ra.lower()
