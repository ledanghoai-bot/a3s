# Data Classification Catalog — Alpha3S

```yaml
document: DATA-CLASSIFICATION-CATALOG
owner: Dev (catalog) / PO (policy)
version: 1.0.0
status: living-document
created: 2026-07-28 (I-B M3-S0)
source_of_truth: Scalffold V2.0 §13.3 (classes) + §13.4 (purposes); schema thực = migrations 001–028 tại base 9b49628
enforcement_note: catalog + SQL comment là documentation; enforcement nằm ở application/policy boundary (spec M3 §6.1). data_class/purpose_code BẮT BUỘC khai báo cho schema/event mới từ migration 029.
```

## 1. Classes (định nghĩa chuẩn — Scalffold §13.3)

| Class | Định nghĩa | Quy tắc |
|---|---|---|
| `D0_PUBLIC` | Không phải dữ liệu cá nhân, được phép công khai | Integrity/version control |
| `D1_PERSONAL_BASIC` | Xác định hoặc giúp xác định cá nhân | Purpose, access, retention, deletion |
| `D2_PERSONAL_SENSITIVE` | Gắn quyền riêng tư, xâm phạm gây ảnh hưởng trực tiếp (sức khỏe, thai kỳ, tài chính, vị trí…) | Default deny, restricted access, enhanced audit |
| `D3_PERSONAL_DERIVED` | Hệ thống suy luận nhưng còn gắn với khách | Bảo vệ như dữ liệu nguồn; health inference = nhạy cảm |
| `D4_DEIDENTIFIED` | Khử nhận dạng thực sự | Chỉ thoát phạm vi personal data sau re-identification review |

Nhắc: pseudonymized/encrypted vẫn là dữ liệu cá nhân; giữ customer/conversation ID hoặc lineage nối
ngược vẫn là dữ liệu cá nhân.

## 2. Catalog áp cho schema hiện có (Postgres, migrations 001–028)

| Bảng | Class | Purpose | Ghi chú |
|---|---|---|---|
| `customers` (name, phone, address, psid) | **D1** | P01/P02 | psid = định danh Meta; sau self-service deletion → ẩn danh (`deleted:<code>`) |
| `conversations` | **D1** (linkage) | P01 | khóa nối khách↔chat |
| `messages` (content thô) | **D1, có thể chứa D2 tự khai** | P01 | free-text khách có thể chứa bệnh lý/thai kỳ… → xử lý như D1 với cờ D2-possible; cấm vào log (S4), cấm vào Content Generator |
| `orders` (shipping_name/phone/address) | **D1** | P02/P03/P11 | ẩn danh PII khi khách xóa, giữ số liệu cho kế toán (P11) |
| `order_items` | D1 (qua order_id) | P02 | |
| `order_events` (M2, 022) | **D1 refs** | P02 | payload không raw PII — giữ nguyên tắc này cho event mới |
| `escalations` | **D1, D2-possible** | P04 | trích message khách |
| `products`, `price_tiers`, `price_overrides`, `faq_entries` | **D0** | P02/P01 | |
| `knowledge_chunks`, `kb_assets/units/ingestion_reports/config` | **D0** | P01 | product truth; embeddings từ D0 → D0 |
| `staff_users`, `staff_sessions` | D1 (nội bộ nhân sự) | vận hành | không thuộc customer scope nhưng vẫn bảo vệ |
| `roles`, `permissions`, `role_permissions` | D0 (nội bộ) | vận hành | |
| `audit_log` (015) | D1 refs (before/after ĐÃ redact tại `audit_service`) | P11/audit | chuẩn redact tốt nhất repo — giữ |
| `command_executions` (019) | D1 refs + payload redacted (`command/redaction.py`) | P02/P03 | |
| `outbox_events`, `delivery_attempts` (019) | **D1** (payload notify có thể chứa tên/SĐT cho admin alert) | P03 | S5 template minimization |
| `inventory_locations/balances/reservations/movements` (021) | D0 vận hành (refs đơn → D1 gián tiếp) | P02 | |
| `inventory_adjustment_requests`, `inventory_unit_members` (023) | D1 nội bộ (actor) | P02 | |
| `data_deletion_requests` (013) | D1 (confirmation code ↔ psid đã cắt) | P11/DSR | |

## 3. Ngoài Postgres

| Store | Nội dung | Class | Retention hiện hành |
|---|---|---|---|
| Redis `chat:{psid}` | history hội thoại gửi LLM | **D1 (D2-possible)** | TTL ~24h (đã khai trong privacy notice) |
| Redis `profile:{psid}` | tên profile Meta | D1 | TTL 7 ngày |
| Redis dead-letter (`tasks.py:49-52`) | **nguyên webhook event (raw chat + PSID)** | **D1/D2-possible** | **KHÔNG TTL — GAP** (xem §5) |
| Stdout/container log | print() các loại | phải là **D0** | hiện có PII lọt — GAP → S4 |
| Backup pg_dump (VPS, cron ngày) | toàn bộ DB | theo bảng nguồn | expiry backup chưa policy hóa → Retention Schedule |

## 4. Data zoning (áp dụng từ M3)

- **Personal Data Zone**: customers, messages, conversations, orders, escalations, Redis chat/profile,
  slot store (M4 tương lai). Encryption at rest (managed volume), least privilege (DB role 024),
  access audit (audit_log), retention + deletion theo Schedule/DSR.
- **Insight Zone** (Orbit đọc, chưa mở trong M3): chỉ nhận qua Privacy Transformation Boundary,
  aggregate + minimum group size; KHÔNG direct identifier/raw health/quote nhận diện được.
- Content/Insight consumer **không đọc trực tiếp** Personal Data Zone (Directive §8).

## 5. Gap / Action

| # | Gap | Action | Slice |
|---|---|---|---|
| 1 | PII/credential lọt stdout log (chi tiết: `docs/PHASE1B-M3-PII-LOG-AUDIT-VI.md` — 4 HIGH) | Sửa toàn bộ + guard test | **S4** |
| 2 | Redis dead-letter lưu raw event không TTL | TTL + chỉ refs | **S4** |
| 3 | Chưa có cột/comment `data_class`/`purpose_code` trên schema cũ | KHÔNG retro-fit ồ ạt trong M3; áp cho schema mới từ 029; catalog này là mapping cho schema cũ | quy ước |
| 4 | `messages` D2-possible chưa có detection | M4 (sensitive detection) — ngoài scope M3 | M4 |
| 5 | Backup expiry chưa policy | Retention Schedule + S6 dry-run | S6 |
