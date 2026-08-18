# I-B M4 H2-B — Google Cloud KMS cho chu ky transcript.
#
# TRANG THAI: CHUA THUC THI. Directive H2-B cam tao resource. File nay de CA review va de chay
# `terraform plan` SAU KHI PO mo Provisioning Gate. Khong chay `apply` o buoc chuan bi nay.
#
# Moi gia tri dinh danh (project, region, ten key ring/key, service account, WIF pool) deu la
# BIEN, vi PO decision H2B ghi ro chung "chua duoc quyet dinh". Gia tri de xuat nam o
# docs/M4-H2B-GOOGLE-KMS-IAM-VA-PROVISIONING-VI.md va can PO chot truoc khi plan.

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

resource "google_iam_workload_identity_pool_provider" "vps" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.vps.workload_identity_pool_id
  workload_identity_pool_provider_id = var.wif_provider_id
  project                            = var.project_id

  attribute_mapping = {
    "google.subject" = "assertion.sub"
  }

  # Chi DUNG mot subject duoc phep doi token. Thieu dieu kien nay thi bat ky identity nao cua
  # issuer cung mao danh duoc signer.
  attribute_condition = "assertion.sub == \"${var.wif_allowed_subject}\""

  oidc {
    issuer_uri = var.wif_issuer_uri
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

resource "google_logging_project_sink" "kms_audit" {
  name        = var.log_sink_name
  project     = var.project_id
  destination = "storage.googleapis.com/${var.log_sink_bucket}"
  filter      = "protoPayload.serviceName=\"cloudkms.googleapis.com\""

  unique_writer_identity = true
}
