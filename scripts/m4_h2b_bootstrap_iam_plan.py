#!/usr/bin/env python
"""I-B M4 H2-B — sinh KE HOACH bootstrap IAM cho Infrastructure Apply Gate (F-PR31-06).

VI SAO CAN THU NAY
CA Review 1 (F-PR31-06) bac cach lam cu: package chi noi "quyen bootstrap co expiry khoang 48 gio"
ma khong co exact condition expression, khong co timestamp, khong noi ai grant ai revoke, va khong
co postcondition chung minh da thu hoi.

Timestamp go tay la cho de sai nhat: sai mui gio, sai dinh dang, hoac go 2026-09 thay vi 2026-08 la
ra mot binding song rat lau ma khong ai nhan ra — trong khi o day MOT NGUOI kiem ca bon vai, khong
co nguoi thu hai de doi chieu. Vi vay ke hoach duoc SINH RA tu cua so gate, khong go tay.

Script nay KHONG goi Google, KHONG can credential, KHONG sua gi. No chi in ra:
  1. lenh kiem IAM TRUOC khi grant (gom ca kiem Owner/Editor ke thua);
  2. lenh grant voi exact IAM Condition co expiry;
  3. lenh revoke;
  4. lenh kiem IAM SAU khi revoke va khang dinh so binding con lai = 0.

Nguoi chay cac lenh do la PO/operator bang danh tinh cua chinh minh. DEV khong nhan credential.

Dung:
  python scripts/m4_h2b_bootstrap_iam_plan.py --bat-dau 2026-08-21T02:00:00Z --ket-thuc 2026-08-21T06:00:00Z

Exit: 0 sinh duoc ke hoach | 2 tham so vi pham rang buoc cua PO Decision Record
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

# Authority: CA-Docs/PHASE1B-M4-H2B-F-PROV-06-PO-DECISION-RECORD-VI.md muc 5.
DEM_CLEANUP = timedelta(hours=1)  # expiry = het cua so gate + toi da 1 gio don dep
TONG_TOI_DA = timedelta(hours=48)  # tong vong doi khong duoc vuot 48 gio

TIEU_DE_DIEU_KIEN = "m4-h2b-bootstrap"

# Moi role phai duoc bien minh bang resource CU THE trong plan. Role nao khong co resource tuong
# ung thi bo — day la yeu cau cua F-PROV-04, khong phai goi y.
ROLE_BOOTSTRAP: tuple[tuple[str, str], ...] = (
    ("roles/serviceusage.serviceUsageAdmin", "enable 8 API trong local.required_services"),
    ("roles/cloudkms.admin", "tao key ring, crypto key va 2 IAM binding cap CryptoKey"),
    ("roles/iam.serviceAccountAdmin", "tao service account signer + binding workloadIdentityUser tren chinh SA do"),
    ("roles/iam.workloadIdentityPoolAdmin", "tao Workload Identity Pool va Provider X.509"),
    ("roles/resourcemanager.projectIamAdmin", "dat google_project_iam_audit_config (IAM policy cap project)"),
    ("roles/logging.configWriter", "tao log sink + 6 log-based metric"),
    ("roles/storage.admin", "tao bucket audit + 2 binding tren bucket"),
    ("roles/monitoring.editor", "tao notification channel + 6 alert policy"),
)

# Cam tuyet doi: khong dung quyen tong lam duong tat cho bootstrap.
ROLE_CAM = ("roles/owner", "roles/editor")


def _doc_thoi_gian(gia_tri: str) -> datetime:
    try:
        moc = datetime.fromisoformat(gia_tri.replace("Z", "+00:00"))
    except ValueError as loi:
        raise SystemExit(f"[2] thoi gian khong dung RFC 3339: {gia_tri!r} ({loi})")
    if moc.tzinfo is None:
        raise SystemExit(f"[2] thoi gian phai co mui gio (dung hau to Z): {gia_tri!r}")
    return moc.astimezone(timezone.utc)


def _rfc3339(moc: datetime) -> str:
    return moc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tinh_expiry(bat_dau: datetime, ket_thuc: datetime) -> datetime:
    """Expiry = het cua so gate + 1 gio cleanup, va tong vong doi khong qua 48 gio."""
    if ket_thuc <= bat_dau:
        raise SystemExit("[2] ket-thuc phai sau bat-dau")
    expiry = ket_thuc + DEM_CLEANUP
    if expiry - bat_dau > TONG_TOI_DA:
        raise SystemExit(
            f"[2] tong vong doi {expiry - bat_dau} vuot 48 gio — PO Decision Record muc 5 cam. "
            "Thu hep cua so gate thay vi keo dai binding."
        )
    return expiry


def dieu_kien(expiry: datetime) -> str:
    """Exact IAM Condition expression. Mot dong, khong dien giai xap xi."""
    return (
        f'expression=request.time < timestamp("{_rfc3339(expiry)}"),'
        f"title={TIEU_DE_DIEU_KIEN},"
        f"description=Bootstrap tam thoi cho M4 H2-B Infrastructure Apply Gate; "
        f"het han {_rfc3339(expiry)}; van PHAI revoke tay ngay sau apply"
    )


def in_ke_hoach(du_an: str, principal: str, bat_dau: datetime, ket_thuc: datetime) -> None:
    expiry = tinh_expiry(bat_dau, ket_thuc)
    dk = dieu_kien(expiry)

    print("# ===================================================================")
    print("# KE HOACH BOOTSTRAP IAM — M4 H2-B Infrastructure Apply Gate")
    print(f"# Project      : {du_an}")
    print(f"# Principal    : {principal}")
    print(f"# Cua so gate  : {_rfc3339(bat_dau)} -> {_rfc3339(ket_thuc)}")
    print(f"# Expiry binding: {_rfc3339(expiry)}  (= het cua so + 1 gio cleanup)")
    print(f"# Tong vong doi : {expiry - bat_dau}  (tran cung: {TONG_TOI_DA})")
    print("# Expiry chi la LUOI AN TOAN. Revoke tay sau apply VAN LA BAT BUOC.")
    print("# ===================================================================")
    print()

    print("# --- 1. IAM TRUOC KHI GRANT (luu lai lam evidence) ------------------")
    print(f"gcloud projects get-iam-policy {du_an} --format=json > iam_before.json")
    print("# Khang dinh phai kiem bang mat, khong doc luot:")
    print(f"gcloud projects get-iam-policy {du_an} \\")
    print("  --flatten='bindings[].members' \\")
    print(f"  --filter='bindings.members:{principal}' \\")
    print("  --format='table(bindings.role, bindings.condition.expression)'")
    print("# Neu principal DA co roles/owner hoac roles/editor (truc tiep hay ke thua) thi conditional")
    print("# Storage Admin KHONG con y nghia gioi han. Khi do: bao CA de ghi nhan bootstrap-owner")
    print("# exception hoac chan gate. KHONG duoc tuyen bo least privilege khi chua chung minh.")
    print()

    print("# --- 2. GRANT (moi role deu co expiry, khong role nao vinh vien) ----")
    for role, ly_do in ROLE_BOOTSTRAP:
        print(f"# {ly_do}")
        print(f"gcloud projects add-iam-policy-binding {du_an} \\")
        print(f"  --member='{principal}' \\")
        print(f"  --role='{role}' \\")
        print(f"  --condition='{dk}'")
        print()

    print("# --- 3. REVOKE (chay NGAY sau khi apply + thu evidence xong) --------")
    print("# Phai truyen dung condition da grant, neu khong gcloud se khong tim thay binding.")
    for role, _ in ROLE_BOOTSTRAP:
        print(f"gcloud projects remove-iam-policy-binding {du_an} \\")
        print(f"  --member='{principal}' \\")
        print(f"  --role='{role}' \\")
        print(f"  --condition='{dk}'")
    print()

    print("# --- 4. POSTCONDITION: so binding con lai PHAI = 0 ------------------")
    print(f"gcloud projects get-iam-policy {du_an} --format=json > iam_after.json")
    print(f"gcloud projects get-iam-policy {du_an} \\")
    print("  --flatten='bindings[].members' \\")
    print(f"  --filter='bindings.members:{principal} AND bindings.condition.title={TIEU_DE_DIEU_KIEN}' \\")
    print("  --format='value(bindings.role)' | wc -l   # PHAI in ra 0")
    print()
    print("# Evidence bat buoc nop kem: iam_before.json, cac lenh grant da chay + gio UTC,")
    print("# gio UTC revoke, iam_after.json, va ket qua dem = 0 o tren.")


def main() -> int:
    bo_doc = argparse.ArgumentParser(description="Sinh ke hoach bootstrap IAM (khong goi Google)")
    bo_doc.add_argument("--du-an", default="alpha3s-production-signing")
    bo_doc.add_argument("--principal", default="user:3scoffee.cs@gmail.com")
    bo_doc.add_argument("--bat-dau", required=True, help="dau cua so Apply Gate, RFC 3339 UTC")
    bo_doc.add_argument("--ket-thuc", required=True, help="cuoi cua so Apply Gate, RFC 3339 UTC")
    doi_so = bo_doc.parse_args()

    for role, _ in ROLE_BOOTSTRAP:
        if role in ROLE_CAM:
            print(f"[2] role bi cam trong danh sach bootstrap: {role}", file=sys.stderr)
            return 2

    in_ke_hoach(
        doi_so.du_an,
        doi_so.principal,
        _doc_thoi_gian(doi_so.bat_dau),
        _doc_thoi_gian(doi_so.ket_thuc),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
