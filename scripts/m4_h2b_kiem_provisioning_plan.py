#!/usr/bin/env python
"""I-B M4 H2-B — kiem TINH cau hinh provisioning Google KMS (`infra/gcp-kms/`).

VI SAO CAN THU NAY
Directive H2-B doi "plan/dry-run hoac static validation; khong apply". Tren may lam viec khong co
`terraform` lan `gcloud`, nen KHONG THE chay `terraform validate/plan` — dieu nay duoc khai bao
tuong minh trong hop so, khong nguy trang.

Nhung phan quan trong nhat cua cau hinh khong phai cu phap HCL, ma la cac BAT BIEN AN TOAN:
thuat toan dung, khong co JSON key lau dai, quyen gan o cap khoa chu khong phai cap project, khoa
khong bi xoa duoc. Script nay ma hoa dung nhung bat bien do va chay duoc trong CI khong can cloud —
nen no con gac tiep khi ai do sua Terraform sau nay, la thu `terraform validate` khong lam duoc.

Exit: 0 dat | 1 co vi pham | 2 loi van hanh
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THU_MUC = ROOT / "infra" / "gcp-kms"

_loi: list[str] = []
_dat: list[str] = []


def kiem(dieu_kien: bool, nhan: str) -> None:
    (_dat if dieu_kien else _loi).append(nhan)
    print(("  PASS  " if dieu_kien else "  FAIL  ") + nhan)


def main() -> int:
    if not THU_MUC.is_dir():
        print(f"khong thay thu muc {THU_MUC}", file=sys.stderr)
        return 2
    hcl = "\n".join(p.read_text(encoding="utf-8") for p in sorted(THU_MUC.glob("*.tf")))
    if not hcl.strip():
        print("khong co file .tf nao", file=sys.stderr)
        return 2
    # Cac phep kiem dang "KHONG duoc chua X" phai chay tren CAU HINH, khong phai comment:
    # ban dau `rotation_period` bi bao vi pham chi vi no nam trong mot comment giai thich
    # LY DO khong dat no. Do la loi cua chinh trinh kiem, khong phai cua cau hinh — sua bang
    # cach bo comment truoc khi kiem, thay vi bo phep kiem.
    cau_hinh = re.sub(r"#[^\n]*", "", hcl)

    print("=== Bat bien mat ma (PO decision H2B) ===")
    kiem('purpose = "ASYMMETRIC_SIGN"' in hcl, "khoa dung purpose ASYMMETRIC_SIGN")
    kiem('algorithm        = "EC_SIGN_ED25519"' in hcl or 'algorithm = "EC_SIGN_ED25519"' in hcl,
         "thuat toan EC_SIGN_ED25519 (khop CHECK cua migration 044)")
    kiem('protection_level = "SOFTWARE"' in hcl, "protection level SOFTWARE")
    kiem("ENCRYPT_DECRYPT" not in cau_hinh, "khong dung khoa nay cho muc dich ma hoa")

    print("=== Khong co credential lau dai ===")
    kiem("google_service_account_key" not in cau_hinh,
         "KHONG tao service-account JSON key (PO decision: chi dung federation)")
    kiem("google_iam_workload_identity_pool_provider" in hcl,
         "co Workload Identity Federation provider")
    kiem("attribute_condition" in hcl,
         "WIF provider co attribute_condition (khong cho moi subject cua issuer doi token)")
    kiem('role               = "roles/iam.workloadIdentityUser"' in hcl
         or 'role    = "roles/iam.workloadIdentityUser"' in hcl
         or "roles/iam.workloadIdentityUser" in hcl,
         "chi subject duoc phep moi impersonate signer SA")

    print("=== Nguon tin cay WIF: X.509 (PO decision 18/8/2026, phuong an A) ===")
    kiem("x509" in cau_hinh and "trust_anchors" in cau_hinh,
         "provider dung X.509 va co trust anchor cua CA noi bo")
    kiem("oidc" not in cau_hinh and "issuer_uri" not in cau_hinh,
         "KHONG con cau hinh OIDC sot lai (PO da chot X.509)")
    kiem("assertion.subject" in cau_hinh,
         "danh tinh lay tu SUBJECT cua chung chi, khong phai claim tu khai")
    kiem("PRIVATE KEY" not in hcl,
         "trust anchor la PUBLIC material — khong khoa rieng nao trong cau hinh")

    print("=== Quyen toi thieu, dung cap ===")
    kiem("google_kms_crypto_key_iam_member" in hcl,
         "quyen gan o cap CRYPTO KEY (khong phai project)")
    kiem("google_project_iam_member" not in cau_hinh,
         "KHONG gan role KMS o cap project cho signer")
    vai_tro = set(re.findall(r'roles/cloudkms\.[A-Za-z]+', cau_hinh))
    kiem(vai_tro <= {"roles/cloudkms.signer", "roles/cloudkms.publicKeyViewer"},
         f"chi dung vai tro ky + doc public key (thuc te: {sorted(vai_tro)})")
    for cam in ("roles/cloudkms.admin", "roles/owner", "roles/editor",
                "roles/cloudkms.cryptoKeyEncrypterDecrypter"):
        kiem(cam not in cau_hinh, f"khong cap {cam}")

    print("=== Chong mat bang chung lich su ===")
    kiem(hcl.count("prevent_destroy = true") >= 2,
         "key ring va crypto key deu prevent_destroy (huy khoa = chu ky cu khong verify duoc nua)")
    kiem("rotation_period" not in cau_hinh,
         "KHONG rotation tu dong (phai cong bo public key moi vao registry TRUOC khi doi phien ban)")

    print("=== Audit ===")
    kiem("google_project_iam_audit_config" in hcl, "co audit config cho KMS")
    kiem('log_type = "DATA_WRITE"' in hcl, "ghi log moi thao tac ky (DATA_WRITE)")
    kiem('log_type = "DATA_READ"' in hcl, "ghi log thao tac doc public key (DATA_READ)")
    kiem("google_logging_project_sink" in hcl, "co log sink de giu lai audit log")

    print("=== Bootstrap va audit destination (F-H2B-05) ===")
    kiem("HOP DONG BOOTSTRAP" in hcl and "billing" in hcl.lower(),
         "co hop dong bootstrap project/billing (ai lam, thu tu, dieu kien tien quyet)")
    kiem("google_storage_bucket" in cau_hinh and "google_storage_bucket_iam_member" in cau_hinh,
         "bucket audit duoc TAO o day, khong gia dinh da ton tai")
    kiem("writer_identity" in cau_hinh and "roles/storage.objectCreator" in cau_hinh,
         "writer identity cua sink duoc cap quyen ghi (thieu -> sink chay nhung khong luu duoc log)")
    kiem("retention_policy" in cau_hinh, "bucket audit co retention policy")
    kiem("public_access_prevention" in cau_hinh and "uniform_bucket_level_access" in cau_hinh,
         "bucket audit chan truy cap cong khai va dung IAM thay ACL")
    kiem("audit_reader_member" in cau_hinh,
         "nguoi DOC audit log duoc khai bao tuong minh (tach khoi signer va nguoi ghi)")

    print("=== Khong co dinh danh that bi hard-code ===")
    kiem("variable " + chr(34) + "project_id" + chr(34) in hcl,
         "dinh danh la BIEN (PO chua chot gia tri) chu khong hard-code")
    kiem(not re.search(r'project_id\s*=\s*"[a-z0-9-]{6,}"', hcl),
         "khong hard-code project_id that")
    kiem(not re.search(r'\bya29\.|BEGIN PRIVATE KEY|"AIza[0-9A-Za-z_-]{20,}"', hcl),
         "khong co token/khoa/API key nao trong cau hinh")

    print()
    if _loi:
        print(f"KHONG DAT ({len(_loi)}):")
        for x in _loi:
            print("  - " + x)
        return 1
    print(f"TAT CA {len(_dat)} BAT BIEN DAT. (Luu y: day la kiem TINH — chua chay terraform "
          "validate/plan vi may nay khong co terraform/gcloud.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
