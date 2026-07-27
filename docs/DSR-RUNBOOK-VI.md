# Data Subject Request (DSR) Runbook + Deletion Propagation Map — Alpha3S

```yaml
document: DSR-RUNBOOK
owner: PO (điều phối) / Dev (thực thi kỹ thuật)
version: 1.0.0
status: living-document
created: 2026-07-28 (I-B M3-S0)
source_of_truth: Scalffold V2.0 §13.12–13.13; code thực data_deletion.py tại base 9b49628; luật 91/2025/QH15
scope_note: Gateway sẽ là DSR orchestrator dài hạn; giai đoạn này Alpha3S vận hành thủ công theo runbook
```

## 1. Quyền được hỗ trợ và cách tiếp nhận

| Quyền | Kênh tiếp nhận | Cách xử lý hiện hành |
|---|---|---|
| **Xóa dữ liệu** | Tự phục vụ qua chat: khách nhắn `XOA DU LIEU` → bot hỏi xác nhận → `XAC NHAN XOA` | **TỰ ĐỘNG** (`app/services/data_deletion.py`): xóa + ẩn danh trong 1 transaction, trả confirmation code + status URL. Deterministic, chạy TRƯỚC LLM, keyword match bỏ dấu cả 2 phía, mọi kênh |
| Xóa dữ liệu (Meta callback) | Meta Data Deletion Callback (signed_request) | Tự động, cùng `_delete_customer_data` |
| Biết/truy cập | Khách hỏi qua chat/PO nhận trực tiếp | THỦ CÔNG: PO/admin xuất từ dashboard/DB theo psid — checklist §3 |
| Chỉnh sửa | qua chat (khách cung cấp thông tin mới khi đặt đơn) hoặc thủ công | update customers/orders qua dashboard (audited) |
| Rút consent / phản đối / hạn chế | hiện = yêu cầu xóa hoặc yêu cầu thủ công | S3 consent ledger sẽ chuẩn hóa (withdraw per-purpose) |
| Khiếu nại | chat → escalation → admin | P04 + (S3) complaint suppression |

Quy trình chuẩn (mọi request thủ công): tiếp nhận → xác minh danh tính tương xứng (qua chính kênh
chat đã dùng) → phân loại → thực thi theo map §2 → xác nhận hoàn tất → trả lời khách (nêu rõ phần
giữ lại và căn cứ) → lưu audit tuân thủ (opaque reference).

## 2. Deletion Propagation Map (trạng thái thực — verified trên code)

| # | Data store | Hành động khi khách xóa | Trạng thái |
|---|---|---|---|
| 1 | `messages` (theo conversations của khách) | DELETE | ✅ tự động |
| 2 | `escalations` | DELETE | ✅ tự động |
| 3 | `conversations` | DELETE | ✅ tự động |
| 4 | `orders` | UPDATE shipping_name/phone/address = NULL (ẩn danh, giữ số liệu P11) | ✅ tự động |
| 5 | `customers` | name/phone/address = NULL; psid → `deleted:<code>` (cắt link định danh Meta) | ✅ tự động |
| 6 | Redis `chat:{psid}`, `profile:{psid}` | DELETE | ✅ tự động |
| 7 | `data_deletion_requests` | ghi nhận request/status (không chứa psid sau khi cắt) | ✅ |
| 8 | Chống tái tạo sau xóa | orchestrator không log/lưu sau xóa (`orchestrator.py:154-156`) | ✅ |
| 9 | Redis **dead-letter** (webhook event thô) | **KHÔNG được dọn** — có thể còn raw chat của khách đã xóa | ❌ **GAP → S4** (TTL + refs-only; thêm bước purge theo psid vào flow xóa) |
| 10 | Container stdout logs | có thể còn PII đã in trước đó | ❌ GAP → S4 (chặn từ nguồn) + log-rotate hạ tầng |
| 11 | Backup pg_dump | bản backup cũ còn dữ liệu đã xóa | ⚠️ chấp nhận có kiểm soát: backup expiry (RET-06) + **cấm restore dữ liệu đã xóa về hệ active** (restore-non-resurrection test S6/S7 — AC-M3-07) |
| 12 | Vendor copy — DeepSeek | dữ liệu đã gửi vendor không có deletion API | ⚠️ ghi nhận trong VDR-001; mitigate dài hạn = M4 masked input; action PO: opt-out/verify retention |
| 13 | Vendor copy — Meta/Telegram | hội thoại tồn tại trên nền tảng kênh theo policy của họ (khách tự xóa phía app của họ) | ghi nhận trong notice |
| 14 | Vector/embedding | KB vectors = D0 product truth, KHÔNG có customer vector | ✅ n/a hiện tại (M4 slot store sẽ thêm mục mới) |
| 15 | `outbox_events`/`delivery_attempts` payload | có thể chứa tên/SĐT trong alert cũ | ❌ GAP → S5 template minimization + S6 retention RET-05 |
| 16 | (S3 tương lai) `consent_records` | KHÔNG xóa evidence tuân thủ — khóa purpose "chứng minh tuân thủ" (§13.5) | thiết kế S3 |

## 3. Checklist thao tác thủ công (access/correction — tới khi tự động hóa)

1. Xác minh khách qua đúng kênh chat (không yêu cầu giấy tờ vượt mức).
2. Query theo psid/customer_id: customers, conversations→messages, orders(+items), escalations.
3. Xuất bản sao (access) hoặc sửa (correction) qua dashboard — mọi thay đổi đi qua audit_log.
4. Trả lời trong thời hạn theo 91/2025/QH15 (SLA cụ thể: central policy — PO/legal chốt, KHÔNG
   hard-code trong nhiều service).
5. Ghi audit tuân thủ bằng confirmation/opaque code.

## 4. Gap / Action tổng hợp

| # | Gap | Slice/Owner |
|---|---|---|
| 1 | Dead-letter không nằm trong deletion propagation | **S4** |
| 2 | Outbox payload cũ chứa PII | S5/S6 |
| 3 | Restore-non-resurrection chưa có test | S6/S7 (AC-M3-07) |
| 4 | Rút consent per-purpose chưa chuẩn hóa | **S3** |
| 5 | SLA pháp lý chưa cấu hình central | PO/legal |
| 6 | Vendor copy DeepSeek | VDR-001 actions (PO) + M4 |
