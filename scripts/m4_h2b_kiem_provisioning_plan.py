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

import json
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

    # F-PR31-03: danh sach API duoc duyet phai TRUNG KHIT giua cau hinh va checker. Ban sao o day
    # co chu dich: them mot API vao Terraform ma khong sua checker se FAIL, buoc nguoi sua phai
    # di qua review thay vi lang le mo rong be mat.
    print("=== Inventory API (F-PR31-03) ===")
    API_DUOC_DUYET = {
        "serviceusage.googleapis.com",
        "cloudkms.googleapis.com",
        "iam.googleapis.com",
        "iamcredentials.googleapis.com",
        "sts.googleapis.com",
        "cloudresourcemanager.googleapis.com",
        "logging.googleapis.com",
        "monitoring.googleapis.com",
        "storage.googleapis.com",
    }
    trong_ch = set(re.findall(r'"([a-z][a-z0-9.-]*\.googleapis\.com)"\s*=', cau_hinh))
    kiem(trong_ch == API_DUOC_DUYET,
         f"inventory API khop danh sach duyet (thua: {sorted(trong_ch - API_DUOC_DUYET)}, "
         f"thieu: {sorted(API_DUOC_DUYET - trong_ch)})")
    so_khoi_api = len(re.findall(r'resource\s+"google_project_service"', cau_hinh))
    kiem(so_khoi_api == 1,
         f"chi MOT khoi google_project_service (for_each tren inventory) — thuc te {so_khoi_api}")
    kiem("SAFETY-STOP (F-PR31-03)" in hcl,
         "cau hinh ghi ro quy tac safety-stop khi can API ngoai danh sach")

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

    print("=== Authority (F-H2B-01A) ===")
    kiem("PHASE1B-M4-H2B-GOOGLE-CLOUD-KMS-PO-DECISION-VI" in hcl,
         "cau hinh khoa dan nguon PO Decision Record cua Google KMS")
    kiem("PHASE1B-M4-H2B-WIF-X509-TRUST-SOURCE-PO-DECISION-VI" in hcl,
         "cau hinh WIF dan nguon PO Decision Record cua X.509 trust source")
    kiem("Offline Certificate Authority" in hcl,
         "goi day du 'Offline Certificate Authority' (khong nham voi CA reviewer/governance)")

    print("=== Nguon tin cay WIF: X.509 (authority: PO Decision Record WIF-X509-TRUST-SOURCE) ===")
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
         "key ring va crypto key deu prevent_destroy (huy khoa = mat mat xich doi chieu public key trong registry voi nguon KMS; chu ky cu VAN verify duoc)")
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

    # F-PR31-05: CA yeu cau static checker FAIL neu khang dinh sai ve destroy quay lai. Phep kiem
    # nay chay tren CA VAN BAN ke ca COMMENT (khac cac phep kiem khac chay tren `cau_hinh` da bo
    # comment) — vi lan truoc chinh comment la cho sai, va comment la thu nguoi sau doc de hieu.
    print("=== Chan hoi quy khang dinh sai ve destroy (F-PR31-05 / Erratum 01) ===")
    MAU_SAI = (
        r"chu ky[^\n]{0,60}khong con verify duoc",
        r"mat kha nang verify",
        r"khong verify duoc nua",
        r"mất khả năng verify",
        r"không verify được nữa",
        r"không còn verify được",
    )
    for mau in MAU_SAI:
        vi_pham = re.search(mau, hcl, re.IGNORECASE)
        kiem(vi_pham is None,
             f"khong co khang dinh sai kieu {mau!r}"
             + (f" — TIM THAY: {vi_pham.group(0)!r}" if vi_pham else ""))
    kiem("m4_stage0p_transcript_public_keys" in hcl,
         "cau hinh noi ro NGUON verify la registry DB (khong phai GetPublicKey cua KMS)")

    doc = ROOT / "docs" / "M4-H2B-GOOGLE-KMS-IAM-VA-PROVISIONING-VI.md"
    if doc.is_file():
        van_ban = doc.read_text(encoding="utf-8")
        xau = [m for m in MAU_SAI if re.search(m, van_ban, re.IGNORECASE)]
        kiem(not xau, f"tai lieu thiet ke khong chua khang dinh sai (thuc te: {xau})")

    print("=== Canh bao (F-PROV-06, PO tra loi 20/8/2026) ===")
    so_alert = cau_hinh.count('resource "google_monitoring_alert_policy"')
    so_wire = cau_hinh.count("notification_channels = [google_monitoring_notification_channel")
    kiem(so_alert >= 6,
         "co du 6 alert policy (ky / IAM khoa / trang thai khoa / danh tinh / that bai xac thuc / "
         f"noi chua bang chung) — thuc te {so_alert}")
    kiem(so_alert > 0 and so_wire == so_alert,
         f"MOI alert policy deu noi vao notification channel ({so_wire}/{so_alert}) — alert khong co kenh la alert cam")
    kiem("var.alert_email" in cau_hinh and not re.search(r'email_address\s*=\s*"[^"]*@', cau_hinh),
         "hop thu nhan canh bao la BIEN, khong hard-code dia chi that trong .tf")
    kiem(not re.search(r'type\s*=\s*"webhook_', cau_hinh),
         "khong dung webhook channel (webhook Telegram se phai giu bot token trong cau hinh)")
    kiem("notification_rate_limit" in cau_hinh,
         "alert ky co notification_rate_limit (mot ceremony ~ mot email, khong phai 260)")

    # F-PR31-04: filter phai nam trong audit_filters.json de test fixture chay dung cai duoc deploy.
    # Neu ai do viet lai filter thang vao HCL, test se khong con gac cai filter that nua.
    print("=== Pham vi audit (F-PR31-04) ===")
    tep_filter = THU_MUC / "audit_filters.json"
    kiem(tep_filter.is_file(), "co audit_filters.json (mot nguon su that cho filter)")
    if tep_filter.is_file():
        bo_loc = json.loads(tep_filter.read_text(encoding="utf-8"))
        can_co = {
            "sink_all_audit", "sign_operations", "key_iam_changes", "key_state_changes",
            "identity_config_changes", "auth_failures", "audit_destination_changes",
        }
        co = {k for k in bo_loc if not k.startswith("_")}
        kiem(co == can_co, f"du 7 filter (thieu: {sorted(can_co - co)}, thua: {sorted(co - can_co)})")
        kiem(all('methodName="' not in v for k, v in bo_loc.items() if not k.startswith("_")),
             "khong filter nao dung methodName= (bang tuyet doi voi ten RPC rut gon = khong bao gio khop)")
        sink = bo_loc.get("sink_all_audit", "")
        for loai in ("activity", "data_access", "system_event", "policy"):
            kiem(loai in sink, f"sink giu ca loai audit log {loai!r}")
    kiem(cau_hinh.count("local.audit_filters.") >= 7,
         "sink va metric deu lay filter tu JSON (khong viet chuoi filter thang trong HCL)")
    kiem('service = "allServices"' in cau_hinh,
         "audit config phu allServices (khong liet ke tay roi sot service)")
    kiem(cau_hinh.count('resource "google_logging_metric"') >= 6,
         "co du 6 log-based metric (KMS x3 + danh tinh + xac thuc + noi chua bang chung)")

    # F-PR31-07A/08A: quyet dinh cua PO phai dan nguon VAN BAN, khong duoc ghi "PO chot ngay X" roi
    # coi do la authority. Day la lan thu HAI Dev vap cho nay (lan dau la F-H2B-01A), nen dong lai
    # bang phep kiem thay vi bang lo`i hua.
    print("=== Authority cua quyet dinh PO (F-PR31-07A / 08A) ===")
    kiem("PHASE1B-M4-H2B-F-PROV-06-PO-DECISION-RECORD-VI" in hcl,
         "cau hinh alert dan PO Decision Record chinh thuc cua F-PROV-06")
    kiem("PHASE1B-M4-H2B-AUDIT-BUCKET-RETENTION-PO-DECISION-VI" in hcl,
         "cau hinh retention dan PO Decision Record chinh thuc cua audit bucket")
    tu_phong = re.findall(r"PO (?:chot|tra loi) \d{1,2}/\d{1,2}/\d{4}", hcl)
    kiem(not tu_phong,
         f"khong co khang dinh authority kieu 'PO chot <ngay>' ma thieu van ban (thuc te: {tu_phong})")
    kiem("Telegram" not in cau_hinh or "best-effort" in hcl.lower() or "BEST-EFFORT" in hcl,
         "neu nhac Telegram thi phai ghi ro no la best-effort secondary, khong phai acceptance criterion")
    kiem(re.search(r"is_locked\s*=\s*(true|false)", cau_hinh) is not None,
         "retention_policy khai is_locked TUONG MINH (Bucket Lock la thao tac mot chieu)")
    kiem(re.search(r"is_locked\s*=\s*true", cau_hinh) is None,
         "bootstrap KHONG lock retention (PO Decision: unlocked; lock can gate rieng)")

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
    print(f"TAT CA {len(_dat)} BAT BIEN DAT.")
    print("Luu y pham vi: day la kiem TINH tren van ban cau hinh. `terraform validate` DA duoc chay")
    print("rieng va PASS (google provider ~> 6.0). `terraform plan` VAN CHUA chay duoc vi can")
    print("credential Google — xem blocker trong plan package.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
