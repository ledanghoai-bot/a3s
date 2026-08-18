# I-B M4 H2-B — Google Cloud KMS cho chu ky transcript.
#
# TRANG THAI: CHUA THUC THI. Directive H2-B cam tao resource. File nay de CA review va de chay
# `terraform plan` SAU KHI PO mo Provisioning Gate. Khong chay `apply` o buoc chuan bi nay.
#
# Moi gia tri dinh danh (project, region, ten key ring/key, service account, WIF pool) deu la
# BIEN, vi PO decision H2B ghi ro chung "chua duoc quyet dinh". Gia tri de xuat nam o
# docs/M4-H2B-GOOGLE-KMS-IAM-VA-PROVISIONING-VI.md va can PO chot truoc khi plan.

# ---------------------------------------------------------------------------
# HOP DONG BOOTSTRAP (F-H2B-05) — DOC TRUOC KHI PLAN
#
# Module nay KHONG tao project va KHONG gan billing. Do la thao tac o cap to chuc, thuoc quyen chu
# billing account, va co he qua tai chinh — khong nen nam chung voi module bao mat nay.
#
# Dieu kien tien quyet (nguoi thuc hien: PO/chu billing account, TRUOC khi chay `terraform plan`):
#   1. project `var.project_id` da ton tai, tao rieng cho production signing (khong dung chung);
#   2. billing account da gan vao project do;
#   3. nguoi/SA chay Terraform co quyen tren project: `roles/cloudkms.admin`,
#      `roles/iam.serviceAccountAdmin`, `roles/iam.workloadIdentityPoolAdmin`,
#      `roles/logging.configWriter`, `roles/storage.admin`;
#   4. thu tu tao: project + billing -> (module nay) API -> key ring -> khoa -> SA -> IAM -> WIF ->
#      audit + bucket + sink.
#
# Module nay TU tao: API, key ring, khoa, signer SA, IAM cap khoa, WIF pool/provider, audit config,
# bucket audit va sink. Khong thu nao trong so do gia dinh la "da co san".
# ---------------------------------------------------------------------------

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.location
}

# --- API bat buoc -----------------------------------------------------------
resource "google_project_service" "kms" {
  project            = var.project_id
  service            = "cloudkms.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iamcredentials" {
  project            = var.project_id
  service            = "iamcredentials.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "sts" {
  project            = var.project_id
  service            = "sts.googleapis.com"
  disable_on_destroy = false
}

# --- Key ring + khoa --------------------------------------------------------
resource "google_kms_key_ring" "m4" {
  name     = var.key_ring_name
  location = var.location
  project  = var.project_id

  depends_on = [google_project_service.kms]

  # Key ring khong xoa duoc o Google Cloud; prevent_destroy chan luon ca y dinh xoa khoi state.
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key" "transcript" {
  name     = var.key_name
  key_ring = google_kms_key_ring.m4.id

  # PO decision H2B: ASYMMETRIC_SIGN + EC_SIGN_ED25519 + SOFTWARE.
  purpose = "ASYMMETRIC_SIGN"

  version_template {
    algorithm        = "EC_SIGN_ED25519"
    protection_level = "SOFTWARE"
  }

  # KHONG dat rotation_period: rotation cua M4 la thao tac CO CHU DICH, phai di kem buoc cong bo
  # public key moi vao registry (migration 044) TRUOC khi signer doi phien ban. Rotation tu dong se
  # tao ra phien ban ma registry chua biet, va moi chu ky sau do bi tu choi ghi.
  #
  # Huy khoa lam moi chu ky lich su khong con verify duoc -> chan o ca hai lop.
  lifecycle {
    prevent_destroy = true
  }
}

# --- Danh tinh signer -------------------------------------------------------
resource "google_service_account" "signer" {
  account_id   = var.signer_sa_id
  display_name = "M4 transcript signer (chi duoc ky, khong quan tri)"
  project      = var.project_id
}

# Quyen TOI THIEU, gan o cap CRYPTO KEY chu khong phai cap project.
resource "google_kms_crypto_key_iam_member" "signer_sign" {
  crypto_key_id = google_kms_crypto_key.transcript.id
  role          = "roles/cloudkms.signer"
  member        = "serviceAccount:${google_service_account.signer.email}"
}

resource "google_kms_crypto_key_iam_member" "signer_read_public_key" {
  crypto_key_id = google_kms_crypto_key.transcript.id
  role          = "roles/cloudkms.publicKeyViewer"
  member        = "serviceAccount:${google_service_account.signer.email}"
}

# --- Workload Identity Federation (khong co JSON key lau dai) ----------------
resource "google_iam_workload_identity_pool" "vps" {
  workload_identity_pool_id = var.wif_pool_id
  display_name              = "Alpha3S VPS"
  project                   = var.project_id
  depends_on                = [google_project_service.sts]
}

# PO decision 18/8/2026: phuong an A — WIF + X.509. Danh tinh cua signer la mot CHUNG CHI CLIENT
# do CA noi bo cap; VPS giu khoa rieng cua chung chi do.
#
# !! CAN DOI CHIEU KHI CHAY PLAN !!
# Ten khoi/truong cua provider X.509 (`x509`, `trust_store`, `trust_anchors`, `pem_certificate`)
# duoc viet theo tai lieu, CHUA doi chieu voi provider Terraform that vi may lam viec khong co
# terraform/gcloud. Provisioning Gate PHAI chay `terraform validate` + `plan` va sua lai neu lech —
# xem docs/M4-H2B-GOOGLE-KMS-IAM-VA-PROVISIONING-VI.md muc 1. KHONG duoc coi doan nay la da xac minh.
resource "google_iam_workload_identity_pool_provider" "vps" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.vps.workload_identity_pool_id
  workload_identity_pool_provider_id = var.wif_provider_id
  project                            = var.project_id

  # Danh tinh lay tu SUBJECT cua chung chi, khong phai tu mot claim tu khai.
  attribute_mapping = {
    "google.subject" = "assertion.subject.dn.cn"
  }

  # Chi DUNG mot subject duoc phep doi token. Thieu dieu kien nay thi BAT KY chung chi nao do cung
  # CA do cap cung mao danh duoc signer — ke ca chung chi cap cho muc dich khac.
  attribute_condition = "assertion.subject.dn.cn == \"${var.wif_allowed_subject}\""

  x509 {
    trust_store {
      trust_anchors {
        pem_certificate = var.wif_ca_trust_anchor_pem
      }
    }
  }
}

resource "google_service_account_iam_member" "wif_impersonate" {
  service_account_id = google_service_account.signer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${google_iam_workload_identity_pool.vps.name}/subject/${var.wif_allowed_subject}"
}

# --- Audit ------------------------------------------------------------------
resource "google_project_iam_audit_config" "kms" {
  project = var.project_id
  service = "cloudkms.googleapis.com"

  # DATA_READ ghi lai ca thao tac doc public key; DATA_WRITE ghi lai moi lan ky.
  audit_log_config { log_type = "ADMIN_READ" }
  audit_log_config { log_type = "DATA_READ" }
  audit_log_config { log_type = "DATA_WRITE" }
}

# F-H2B-05: bucket dich phai duoc TAO O DAY (khong gia dinh no da ton tai), va phai co retention
# + chan truy cap rong. Mot sink tro toi bucket khong ton tai/khong co quyen se tao THANH CONG
# nhung khong luu duoc log — audit trong rong ma khong ai biet.
resource "google_storage_bucket" "kms_audit" {
  name     = var.log_sink_bucket
  project  = var.project_id
  location = var.log_bucket_location

  # Khong cho ACL cu/truy cap theo object -> quyen chi den tu IAM, de kiem soat va kiem tra.
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  retention_policy {
    retention_period = var.log_retention_days * 24 * 60 * 60
  }

  versioning {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_logging_project_sink" "kms_audit" {
  name        = var.log_sink_name
  project     = var.project_id
  destination = "storage.googleapis.com/${google_storage_bucket.kms_audit.name}"
  filter      = "protoPayload.serviceName=\"cloudkms.googleapis.com\""

  unique_writer_identity = true
}

# F-H2B-05: khong cap quyen cho writer identity thi sink chay nhung KHONG ghi duoc.
# Quyen toi thieu: chi tao object, khong doc, khong xoa.
resource "google_storage_bucket_iam_member" "sink_writer" {
  bucket = google_storage_bucket.kms_audit.name
  role   = "roles/storage.objectCreator"
  member = google_logging_project_sink.kms_audit.writer_identity
}

# Nguoi DOC audit log tach khoi nguoi ghi va khoi signer.
resource "google_storage_bucket_iam_member" "audit_reader" {
  bucket = google_storage_bucket.kms_audit.name
  role   = "roles/storage.objectViewer"
  member = var.audit_reader_member
}
