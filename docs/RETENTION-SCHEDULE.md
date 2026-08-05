# Retention Schedule — Alpha3S

```yaml
document: RETENTION-SCHEDULE
owner: PO (approve thời hạn) / Dev (executor)
version: 1.0.0
status: living-document — thời hạn đánh dấu [PROPOSED] cần PO approve trước khi executor S6 chạy thật
created: 2026-07-28 (I-B M3-S0)
source_of_truth: Scalffold V2.0 §13.11 (retention_rule schema); hiện trạng code tại base 9b49628; privacy notice đã công bố (app/api/legal.py)
rules: không retain_forever; raw ngắn hơn aggregate; backup có expiry; restore không tái sinh dữ liệu đã xóa; legal-hold override có audit
```

| rule_id | data_category | purpose | start_event | retention_period | deletion_method | Trạng thái enforcement |
|---|---|---|---|---|---|---|
| RET-01 | Redis `chat:{psid}` (history LLM) | P01 | message cuối | **~24h** (đã công bố trong notice) | Redis TTL | **ENFORCED (TTL)** |
| RET-02 | Redis `profile:{psid}` (tên Meta) | P01 | fetch | **7 ngày** (đã công bố) | Redis TTL | **ENFORCED (TTL)** |
| RET-03 | `orders` + `order_items` + `order_events` | P02/P03/P11 | order completed/cancelled | PII: đến khi khách yêu cầu xóa (ẩn danh ngay); số liệu ẩn danh: **[PROPOSED] 10 năm** (chứng từ kế toán) | anonymize (đã có trong DSR flow) | partial (on-request); theo lịch → **S6** |
| RET-04 | `messages` + `conversations` + `escalations` (raw chat DB) | P01/P04 | message tạo | **[PROPOSED] 24 tháng** kể từ tương tác cuối (CSKH/tranh chấp), sau đó xóa | delete (S6 executor, dry-run trước) | **CHƯA — hiện vô thời hạn (GAP chính)** |
| RET-05 | `audit_log`, `command_executions`, `delivery_attempts` | P11/audit | ghi | **[PROPOSED] 5 năm** (audit), payload đã redact | archive/delete | CHƯA — S6 |
| RET-06 | Backup pg_dump (VPS cron ngày) | P11 | dump | **[PROPOSED] 30 ngày rolling** | xóa file backup hết hạn | CHƯA — S6 + ops; restore-non-resurrection test bắt buộc (AC-M3-07) |
| RET-07 | Redis dead-letter (webhook event thô) | vận hành | enqueue | **[PROPOSED] 7 ngày TTL + chỉ refs** | TTL | CHƯA — sửa cùng **S4** (hiện không TTL, chứa raw chat) |
| RET-08 | Container stdout logs | vận hành | ghi | theo log-rotate hạ tầng | rotate | ngoài app — ghi nhận; PII phải sạch từ S4 |
| RET-09 | `data_deletion_requests` (confirmation code) | P11/DSR | request | **[PROPOSED] 2 năm** (chứng minh tuân thủ) | delete | CHƯA — S6 |
| RET-10 | KB assets/chunks/vectors (D0) | P01 | version | theo vòng đời nội dung (không phải personal data) | version control | n/a |
| RET-11 | `pii_slots` (M4 Trusted Slot Store, migration 038) | P10 | capture | ngắn — theo `m4_slot_ttl_hours` (mặc định 24h, spec §8) | `purge_expired()` DELETE, counts-only log | **dev/test scope** — flag `m4_trusted_pii_path` OFF, chưa canary |
| RET-11b | `m4_shadow_review_samples` (M4 Stage 0P, migration 039, CA Design Acceptance `d2a63c5`) | P12 | captured_at | `eval completed (predicted_slots IS NOT NULL AND label_status='labeled') OR 45 ngày, tuỳ điều kiện nào tới trước` — CA ACCEPTED trần kỹ thuật có điều kiện (§6 gói governance v4.0.0) | purge job DELETE `expires_at<=now() OR eval-completed`, counts-only; DSR #17 xoá vô điều kiện độc lập | **dev/test scope** — chưa capture production (control row `m4_stage0p_control.capture_enabled` mặc định FALSE) |

## Legal hold

Mọi rule có `legal_hold_override`: khi có tranh chấp/yêu cầu pháp lý, đánh dấu hold (audit bằng opaque
reference), executor bỏ qua bản ghi hold; dữ liệu hold bị khóa purpose (không marketing).

## Gap / Action

| # | Gap | Action | Slice |
|---|---|---|---|
| 1 | Raw chat DB (RET-04) vô thời hạn — mâu thuẫn nguyên tắc "raw ngắn hơn aggregate" | PO approve thời hạn → S6 executor dry-run → chạy theo lịch | **S6 + PO gate** |
| 2 | Backup không expiry (RET-06) | ops policy + non-resurrection test | S6/S7 |
| 3 | Dead-letter không TTL (RET-07) | TTL + refs-only | **S4** |
| 4 | Mọi giá trị [PROPOSED] chưa được PO approve | đưa vào Delivery Package như open release input; executor S6 chỉ dry-run cho tới khi approve | S7 |
