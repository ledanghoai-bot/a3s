# I-B M4 H2-B — Google Cloud KMS cho chu ky transcript.
#
# TRANG THAI: CHUA THUC THI. Directive H2-B cam tao resource. File nay de CA review va de chay
# `terraform plan` SAU KHI PO mo Provisioning Gate. Khong chay `apply` o buoc chuan bi nay.
#
# Moi gia tri dinh danh (project, region, ten key ring/key, service account, WIF pool) deu la
# BIEN, vi PO Decision Record `CA-Docs/PHASE1B-M4-H2B-GOOGLE-CLOUD-KMS-PO-DECISION-VI.md` ghi ro chung "chua duoc quyet
# dinh". Gia tri de xuat nam o docs/M4-H2B-GOOGLE-KMS-IAM-VA-PROVISIONING-VI.md va can
# mot PO decision rieng truoc khi plan.

# ---------------------------------------------------------------------------
# HOP DONG BOOTSTRAP (F-H2B-05) — DOC TRUOC KHI PLAN
#
# Module nay KHONG tao project va KHONG gan billing. Do la thao tac o cap to chuc, thuoc quyen chu
# billing account, va co he qua tai chinh — khong nen nam chung voi module bao mat nay.
#
# Dieu kien tien quyet (nguoi thuc hien: PO/chu billing account, TRUOC khi chay `terraform plan`):
#   1. project `var.project_id` da ton tai — PO bao cao da tao `alpha3s-production-signing`
#      (project number 452818585523, parent NONE / No organization);
#   2. billing account da gan vao project do (tham chieu governance: A3S-GCP-BILLING-01;
#      KHONG ghi full Billing Account ID vao repo/evidence);
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
      source = "hashicorp/google"
      # DO DUOC (khong phai doan): provider 5.x KHONG co block `x509` —
      # `terraform validate` bao "Blocks of type x509 are not expected here".
      # v6.50.0 validate PASS. Vi vay ~> 6.0 la BAT BUOC cho WIF X.509.
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.location
}

# --- API bat buoc (F-PR31-03: INVENTORY tuong minh, khong doan) --------------
#
# CA Review 1 bac ban truoc vi module chi khai 4 API trong khi luong WIF X.509 + service-account
# impersonation con phu thuoc IAM, Resource Manager va Service Account Credentials. Danh sach
# duoi day la INVENTORY DUY NHAT: moi API duoc enable deu phai co ten o day kem LY DO.
#
# SAFETY-STOP (F-PR31-03): neu `terraform plan` doi enable mot API KHONG co trong danh sach nay,
# hoac discovery cho thay resource nao do can them API khac, thi DUNG va xin gate rieng — KHONG
# tu them vao day o Plan Gate. `scripts/m4_h2b_kiem_provisioning_plan.py` gac bang cach doi chieu
# danh sach nay voi ban sao trong checker; them API ma quen sua checker se FAIL.
#
# CHUA XAC MINH BANG DISCOVERY THAT: chua co credential nen chua goi duoc `gcloud services list`.
# Danh sach nay suy tu tai lieu + tu chinh cac resource trong module, va phai doi chieu lai o
# buoc discovery read-only cua PO.
locals {
  required_services = {
    "serviceusage.googleapis.com"         = "chinh API dung de enable 7 API con lai — module tu liet ke minh, khong gia dinh no da bat"
    "cloudkms.googleapis.com"             = "key ring, crypto key, AsymmetricSign, GetPublicKey"
    "iam.googleapis.com"                  = "service account cua signer + Workload Identity Pool/Provider"
    "iamcredentials.googleapis.com"       = "impersonate signer SA sau khi doi token (generateAccessToken)"
    "sts.googleapis.com"                  = "doi X.509 client certificate lay token STS — buoc dau cua WIF"
    "cloudresourcemanager.googleapis.com" = "doc/ghi IAM policy cap project va audit config"
    "logging.googleapis.com"              = "log sink + log-based metric"
    "monitoring.googleapis.com"           = "notification channel + alert policy"
    "storage.googleapis.com"              = "bucket dich cua audit sink"
  }
}

# --- Filter audit: MOT nguon su that (F-PR31-04) -----------------------------
# CA Review 1 doi "chung minh filters bang fixture hoac provider-supported validation". Filter vi
# vay khong viet rai rac trong HCL nua ma nam trong `audit_filters.json`; Terraform va
# `tests/test_m4_h2b_audit_filters.py` doc CUNG mot file, nen test chay dung cai se duoc deploy.
#
# Fixture da bat mot loi that o ban truoc: filter cu dung `methodName="AsymmetricSign"` (bang
# tuyet doi), trong khi audit log ghi ten RPC day du
# `google.cloud.kms.v1.KeyManagementService.AsymmetricSign` — filter do se KHONG BAO GIO khop, tuc
# metric luon bang 0 va alert "co thao tac ky" im lang vinh vien. Nay doi sang toan tu chua `:`.
locals {
  _audit_filters_raw = jsondecode(file("${path.module}/audit_filters.json"))

  audit_filters = {
    for ten, mau in local._audit_filters_raw :
    ten => replace(
      replace(mau, "__CRYPTO_KEY_ID__", google_kms_crypto_key.transcript.id),
      "__KEY_RING_ID__", google_kms_key_ring.m4.id
    )
    if !startswith(ten, "_")
  }
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project = var.project_id
  service = each.key

  # Khong disable khi destroy: tat API o day co the lam hong workload KHAC trong cung project.
  disable_on_destroy = false
}

# --- Key ring + khoa --------------------------------------------------------
resource "google_kms_key_ring" "m4" {
  name     = var.key_ring_name
  location = var.location
  project  = var.project_id

  depends_on = [google_project_service.required["cloudkms.googleapis.com"]]

  # Key ring khong xoa duoc o Google Cloud; prevent_destroy chan luon ca y dinh xoa khoi state.
  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key" "transcript" {
  name     = var.key_name
  key_ring = google_kms_key_ring.m4.id

  # Authority: CA-Docs/PHASE1B-M4-H2B-GOOGLE-CLOUD-KMS-PO-DECISION-VI.md
  # (ASYMMETRIC_SIGN + EC_SIGN_ED25519 + protection level SOFTWARE).
  purpose = "ASYMMETRIC_SIGN"

  version_template {
    algorithm        = "EC_SIGN_ED25519"
    protection_level = "SOFTWARE"
  }

  # KHONG dat rotation_period: rotation cua M4 la thao tac CO CHU DICH, phai di kem buoc cong bo
  # public key moi vao registry (migration 044) TRUOC khi signer doi phien ban. Rotation tu dong se
  # tao ra phien ban ma registry chua biet, va moi chu ky sau do bi tu choi ghi.
  #
  # F-PR31-05 (Erratum 01): huy phien ban khoa KHONG lam chu ky lich su het verify duoc — verifier
  # doc public key tu registry DB (m4_stage0p_transcript_public_keys), khong goi Google. Cai that su
  # mat la (a) kha nang KY TIEP va (b) mat xich doi chieu public key trong registry nguoc ve nguon
  # KMS. Theo PO Decision Record F-PROV-06 muc 4, phien ban da DISABLE cung khong duoc gia dinh la
  # con goi duoc GetPublicKey. Vi vay chan o ca hai lop: khong rotation tu dong + prevent_destroy.
  lifecycle {
    prevent_destroy = true

    # Thuat toan de LITERAL chu khong qua bien: mot bien co the bi ghi de tu tfvars/CLI, con literal
    # thi khong. Doi thuat toan = thay khoa: chu ky cu VAN verify duoc bang public key da luu o
    # registry, nhung tu do tro di la mot khoa KHAC — phai cong bo public key moi vao registry TRUOC
    # khi signer doi phien ban, neu khong moi capture se bi tu choi ghi.
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
  depends_on = [
    google_project_service.required["sts.googleapis.com"],
    google_project_service.required["iam.googleapis.com"],
  ]
}

# Authority: CA-Docs/PHASE1B-M4-H2B-WIF-X509-TRUST-SOURCE-PO-DECISION-VI.md — WIF voi X.509 client certificate.
# Danh tinh cua signer la mot CHUNG CHI CLIENT do OFFLINE CERTIFICATE AUTHORITY cap.
# (Luu y thuat ngu: "CA" trong du an nay la vai REVIEWER/GOVERNANCE; ben cap chung chi
#  luon phai goi day du la Offline Certificate Authority.)
# Khoa rieng client SINH TRONG TMPFS TREN VPS va khong roi VPS; chi CSR di ra, chi
# certificate/chain di vao. Chi PUBLIC trust anchor xuat hien o day.
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
        pem_certificate = var.wif_ca_trust_anchor_pem # PUBLIC material
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

# F-PR31-04: audit config rieng cho KMS o tren la de noi RO Y DINH. Nhung neu chi co no thi moi
# service khac (IAM, STS, IAM Credentials, Storage, Logging) chi con Admin Activity mac dinh, va
# khong co gi bat duoc thao tac DOC. Project nay chi chua signing platform nen luu luong rat thap;
# bat allServices la cach duy nhat chung minh KHONG SOT service, thay vi liet ke tay roi quen.
resource "google_project_iam_audit_config" "all_services" {
  project = var.project_id
  service = "allServices"

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

  depends_on = [google_project_service.required["storage.googleapis.com"]]

  # Khong cho ACL cu/truy cap theo object -> quyen chi den tu IAM, de kiem soat va kiem tra.
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # F-PR31-08A. Authority: CA-Docs/PHASE1B-M4-H2B-AUDIT-BUCKET-RETENTION-PO-DECISION-VI.md
  # (APPROVED 20/8/2026): retention DUNG 400 ngay, bootstrap lock state = UNLOCKED.
  #
  # `is_locked` de TUONG MINH bang false chu khong bo trong: Bucket Lock la thao tac MOT CHIEU,
  # khoa roi thi khong go, khong rut ngan, khong xoa bucket truoc han — vinh vien. De trong o day
  # se khien nguoi doc phai doan y dinh; ghi ro false thi moi thay do la LUA CHON co van ban.
  #
  # Doi lai cua trang thai unlocked: nguoi co quyen VAN sua/go duoc retention. Bu lai bang
  # `google_monitoring_alert_policy.audit_destination_changes` (bao ngay khi sink/bucket bi doi) +
  # postcondition o apply evidence. Lock chi duoc xem xet o mot gate RIENG sau khi Infrastructure
  # Apply va Synthetic KMS Integration deu duoc CA dong (Decision Record muc 3).
  retention_policy {
    retention_period = var.log_retention_days * 24 * 60 * 60
    is_locked        = false
  }

  # CA acceptance §5.6: retention toi thieu 400 ngay. Precondition lam rang buoc nay hong o PLAN,
  # truoc khi ai do kip apply mot gia tri thap hon.
  versioning {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true

    # CA acceptance §5.6: retention toi thieu 400 ngay. Precondition lam rang buoc nay hong ngay o
    # PLAN, truoc khi ai do kip apply mot gia tri thap hon.
    precondition {
      condition     = var.log_retention_days >= 400
      error_message = "Audit retention phai >= 400 ngay (CA acceptance criteria)."
    }
  }
}

resource "google_logging_project_sink" "kms_audit" {
  name        = var.log_sink_name
  project     = var.project_id
  destination = "storage.googleapis.com/${google_storage_bucket.kms_audit.name}"
  # F-PR31-04: sink cu CHI giu log cua Cloud KMS, tuc moi thay doi IAM/WIF/provider/service
  # account, moi su kien xac thuc STS/IAM Credentials va moi thay doi CHINH CAI SINK/BUCKET nay
  # deu roi ra ngoai. Bang chung ma khong giu duoc thao tac SUA BANG CHUNG thi khong con la bang
  # chung. Nay giu toan bo bon loai Cloud Audit Log cua project.
  #
  # Doi lai la dung luong: project nay chi chua signing platform, luu luong audit rat thap, nen
  # chon PHU RONG thay vi loc hep roi phat hien thieu sau su co.
  filter = local.audit_filters.sink_all_audit

  unique_writer_identity = true

  depends_on = [google_project_service.required["logging.googleapis.com"]]
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


# --- Bang chung co the LOC THEO WORKLOAD (CA acceptance muc 6) -----------------
# Audit log tho thi kho doi chieu. Metric nay dem rieng cac lan KY bang DUNG khoa cua M4, de:
#   * doi chieu cheo voi so hang chu ky sinh ra trong DB cung cua so thoi gian — lech la dau hieu
#     phai dieu tra;
#   * lam co so cho alert "co thao tac ky NGOAI cua so ceremony".
#
# Alert policy tuong ung: `google_monitoring_alert_policy.sign_activity` o duoi (PO da chot kenh
# email tai CA-Docs/PHASE1B-M4-H2B-F-PROV-06-PO-DECISION-RECORD-VI.md).
resource "google_logging_metric" "m4_sign_operations" {
  name    = "m4-transcript-sign-operations"
  project = var.project_id

  filter = local.audit_filters.sign_operations

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# --- Canh bao (F-PROV-06) ----------------------------------------------------
# Authority: CA-Docs/PHASE1B-M4-H2B-F-PROV-06-PO-DECISION-RECORD-VI.md (APPROVED 20/8/2026).
# Record do THAY THE tu cach authority cua ban Dev ghi lai
# (Dev/PHASE1B-M4-H2B-PROVISIONING-F-PROV-06-PO-ANSWERS-VI.md) — ban Dev chi con gia tri lich su.
#
# Theo Decision Record muc 2:
#   * `3scoffee.cs@gmail.com` la AUTHORITATIVE Cloud Monitoring channel;
#   * Telegram la BEST-EFFORT SECONDARY, nam NGOAI GCP, KHONG phai acceptance criterion va KHONG
#     chan Infrastructure Apply Gate;
#   * cam dat Telegram bot token trong Terraform, repository, evidence hoac VPS signer.
# Vi vay Terraform/GCP scope chi gom email notification channel + cac alert policy duoc review.
#
# Hai ly do ky thuat khien Telegram khong the lam bang webhook channel o day:
#   1. Cloud Monitoring khong co kenh Telegram; webhook channel POST mot payload rieng cua Google
#      ma Bot API khong hieu, nen phai co mot bo chuyen doi o giua (Cloud Function/Run) — them
#      resource, them IAM, them chi phi trong dung project toi thieu nay;
#   2. bo chuyen doi do phai giu BOT TOKEN. Dat token vao cau hinh module nay pha bat bien "khong
#      token/khoa trong cau hinh" ma static checker dang gac.
# Duong Telegram vi vay lam NGOAI Google Cloud (forward tu hop thu nhan alert), khong tao phu thuoc
# VPS o duong bao dong, va can runbook + secret custody RIENG ngoai module nay (Decision Record
# muc 2). Khong duoc suy dien authority cho viec do tu cau hinh nay.
resource "google_monitoring_notification_channel" "alert_email" {
  project      = var.project_id
  display_name = "M4 transcript signing alerts"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.required["monitoring.googleapis.com"]]
}

# Metric 2/3: THAY DOI IAM tren key ring hoac khoa. Doi quyen la buoc bat buoc cua bat ky duong
# lam dung nao — no phai phat ra tieng, ke ca khi nguoi doi la chinh chu.
resource "google_logging_metric" "m4_key_iam_changes" {
  name    = "m4-transcript-key-iam-changes"
  project = var.project_id

  filter = local.audit_filters.key_iam_changes

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# Metric 3/3: doi TRANG THAI khoa/phien ban (tao, disable, destroy, restore, doi primary).
# Lien quan truc tiep toi mat xich doi chieu registry <-> KMS: mot phien ban bi destroy lam mat
# kha nang chung minh public key trong registry dung la cua khoa Google da ky (chu ky cu VAN verify
# duoc — verifier doc public key tu DB). Vi vay day la su kien phai bao, khong phai su kien im lang.
resource "google_logging_metric" "m4_key_state_changes" {
  name    = "m4-transcript-key-state-changes"
  project = var.project_id

  filter = local.audit_filters.key_state_changes

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# Alert 1/3 — CO THAO TAC KY.
# Production o trang thai dormant: ngoai cua so ceremony thi so lan ky dung phai la 0. Nguong > 0
# tren cua so 300s + notification_rate_limit 300s cho ra "mot ceremony ~ mot email", khong phai 260
# email. Doi lai: mot ceremony hop le cung sinh email — dung y do, vi email do la doi chung cua
# nguoi van hanh voi so hang chu ky trong DB.
resource "google_monitoring_alert_policy" "sign_activity" {
  project      = var.project_id
  display_name = "M4: co thao tac ky transcript"
  combiner     = "OR"

  conditions {
    display_name = "AsymmetricSign tren khoa M4 > 0"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.m4_sign_operations.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
  }

  notification_channels = [google_monitoring_notification_channel.alert_email.id]
  depends_on            = [google_project_service.required["monitoring.googleapis.com"]]
}

# Alert 2/3 — DOI IAM tren key ring/khoa.
resource "google_monitoring_alert_policy" "key_iam_changes" {
  project      = var.project_id
  display_name = "M4: IAM tren key ring/khoa bi thay doi"
  combiner     = "OR"

  conditions {
    display_name = "SetIamPolicy tren key ring hoac khoa M4"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.m4_key_iam_changes.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.alert_email.id]
  depends_on            = [google_project_service.required["monitoring.googleapis.com"]]
}

# Alert 3/3 — doi trang thai khoa/phien ban.
resource "google_monitoring_alert_policy" "key_state_changes" {
  project      = var.project_id
  display_name = "M4: trang thai khoa/phien ban thay doi"
  combiner     = "OR"

  conditions {
    display_name = "Tao/disable/destroy/restore phien ban khoa M4"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.m4_key_state_changes.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.alert_email.id]
  depends_on            = [google_project_service.required["monitoring.googleapis.com"]]
}


# --- F-PR31-04: ba duong con lai ma ban truoc bo sot ------------------------
#
# CA Review 1: sink + alert cu chi phu Cloud KMS. Ba metric duoi day phu not ba mat con lai ma mot
# ke tan cong PHAI di qua, hoac mot su co PHAI de lai dau vet:
#   1. doi danh tinh/quyen  — them binding, sua WIF provider, tao service account khac;
#   2. that bai xac thuc     — chung chi sai/het han, subject khong khop, token bi tu choi;
#   3. doi noi chua bang chung — sua/xoa sink, sua bucket audit hoac retention cua no.
# Rieng (3) la duong ma ke muon xoa dau vet buoc phai di, nen no phai bao dong RIENG.

resource "google_logging_metric" "m4_identity_config_changes" {
  name    = "m4-identity-config-changes"
  project = var.project_id
  filter  = local.audit_filters.identity_config_changes

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_logging_metric" "m4_auth_failures" {
  name    = "m4-auth-failures"
  project = var.project_id
  filter  = local.audit_filters.auth_failures

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_logging_metric" "m4_audit_destination_changes" {
  name    = "m4-audit-destination-changes"
  project = var.project_id
  filter  = local.audit_filters.audit_destination_changes

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# Alert 4/6 — doi danh tinh/quyen (WIF pool/provider, service account, IAM binding cap project).
resource "google_monitoring_alert_policy" "identity_config_changes" {
  project      = var.project_id
  display_name = "M4: cau hinh danh tinh/quyen bi thay doi"
  combiner     = "OR"

  conditions {
    display_name = "Thay doi IAM/WIF/service account trong project"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.m4_identity_config_changes.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.alert_email.id]
  depends_on            = [google_project_service.required["monitoring.googleapis.com"]]
}

# Alert 5/6 — THAT BAI xac thuc o STS/IAM Credentials.
# Production dormant: khong ai duoc phep doi token. Mot chuoi that bai la dau hieu chung chi bi
# dung sai cho, het han, hoac co ke dang thu.
resource "google_monitoring_alert_policy" "auth_failures" {
  project      = var.project_id
  display_name = "M4: that bai xac thuc STS/IAM Credentials"
  combiner     = "OR"

  conditions {
    display_name = "Loi xac thuc > 0"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.m4_auth_failures.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.alert_email.id]
  depends_on            = [google_project_service.required["monitoring.googleapis.com"]]
}

# Alert 6/6 — doi NOI CHUA BANG CHUNG (sink, bucket audit, retention, quyen tren bucket).
# Retention policy hien KHONG lock (PO Decision Record AUDIT-BUCKET-RETENTION), nghia la no VAN SUA DUOC boi nguoi co
# quyen. Alert nay la lop bu cho khoang chua lock: sua duoc, nhung khong sua len duoc.
resource "google_monitoring_alert_policy" "audit_destination_changes" {
  project      = var.project_id
  display_name = "M4: noi chua audit log bi thay doi"
  combiner     = "OR"

  conditions {
    display_name = "Thay doi sink hoac bucket audit"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.m4_audit_destination_changes.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.alert_email.id]
  depends_on            = [google_project_service.required["monitoring.googleapis.com"]]
}
