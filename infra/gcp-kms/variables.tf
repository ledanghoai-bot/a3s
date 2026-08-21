# Moi gia tri o day CHUA duoc quyet dinh (CA-Docs/PHASE1B-M4-H2B-GOOGLE-CLOUD-KMS-PO-DECISION-VI.md, muc "Chua duoc quyet dinh").
# Khong dat gia tri mac dinh cho cac dinh danh that: mot mac dinh am tham o day co the tao resource
# nham project — dung lop loi ma H2 da phai sua nhieu lan o cho khac.

variable "project_id" {
  type        = string
  description = "Project ID rieng cho production signing (PO chot)"
}

variable "location" {
  type        = string
  description = "Location cua key ring, vd asia-southeast1 (PO chot)"
}

variable "key_ring_name" {
  type = string
}

variable "key_name" {
  type = string
}

variable "signer_sa_id" {
  type        = string
  description = "account_id cua service account signer (khong phai email day du)"
}

variable "wif_pool_id" {
  type = string
}

variable "wif_provider_id" {
  type = string
}

variable "wif_ca_trust_anchor_pem" {
  type        = string
  description = "Chung chi cua Offline Certificate Authority (PEM) lam trust anchor. Day la PUBLIC material — khong phai bi mat."
}

variable "wif_allowed_subject" {
  type        = string
  description = "CN trong subject cua chung chi signer — DUY NHAT gia tri duoc phep doi token"
}

variable "log_sink_name" {
  type = string
}

variable "log_sink_bucket" {
  type        = string
  description = "Bucket luu Cloud Audit Logs cua KMS"
}

variable "log_bucket_location" {
  type        = string
  description = "Location cua bucket luu audit log"
}

variable "log_retention_days" {
  type        = number
  description = "So ngay giu audit log (retention policy cua bucket)"
}

variable "audit_reader_member" {
  type        = string
  description = "Principal duoc DOC audit log; phai KHAC signer va KHAC nguoi ghi"
}

# Hop thu nhan canh bao Cloud Monitoring.
# Authority: CA-Docs/PHASE1B-M4-H2B-F-PROV-06-PO-DECISION-RECORD-VI.md muc 2 — day la
# AUTHORITATIVE channel cua Cloud Monitoring. Telegram la best-effort secondary, nam ngoai GCP,
# co runbook/secret custody rieng, va KHONG phai acceptance criterion cua Apply Gate.
variable "alert_email" {
  type        = string
  description = "Dia chi email nhan canh bao KMS (khong dat mac dinh: khong doan hop thu that)"
}
