# Data Subject Request (DSR) Runbook + Deletion Propagation Map — Alpha3S

```yaml
document: DSR-RUNBOOK
owner: PO (điều phối) / Dev (thực thi kỹ thuật)
version: 1.2.0
status: living-document
created: 2026-07-28 (I-B M3-S0)
updated: 2026-10-10 (CA Directive 405 + CA Review 415 — tombstone, kho vận hành M1-M7, hàm DSR quyền hẹp 077, ma trận §2b)
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
| 5 | `customers` | name/phone/address/current_address_resolution_id = NULL; **psid VÀ external_chat_id** → `deleted:<code>` (D405: cùng ChatID nhắn lại tạo customer mới, không vướng `uq_customers_channel_chat`); `SELECT … FOR UPDATE` → 2 yêu cầu đồng thời chỉ tombstone 1 lần | ✅ tự động |
| 6 | Redis `chat:`, `profile:`, `nlu_state:`, `del_pending:`, `addr_clarify:{psid}:*` | DELETE | ✅ tự động (D405 thêm 3 key cuối) |
| 7 | `data_deletion_requests` | ghi nhận request/status (received → completed / failed / `redis_pending`). Không chứa psid; `subject_hmac` (HMAC khoá server) CHỈ tồn tại khi `redis_pending`, về NULL khi hoàn tất | ✅ |
| 8 | Chống tái tạo sau xóa | orchestrator không log/lưu sau xóa (`orchestrator.py:154-156`) | ✅ |
| 9 | Redis **dead-letter** `dead_letter:messages` (webhook event thô) | LREM mọi event có sender/recipient = psid (D405) + TTL 7 ngày (M3-S4) | ✅ tự động |
| 10 | Container stdout logs | có thể còn PII đã in trước đó | ❌ GAP → S4 (chặn từ nguồn) + log-rotate hạ tầng |
| 11 | Backup pg_dump | bản backup cũ còn dữ liệu đã xóa | ⚠️ chấp nhận có kiểm soát: backup expiry (RET-06) + **cấm restore dữ liệu đã xóa về hệ active** (restore-non-resurrection test S6/S7 — AC-M3-07) |
| 12 | Vendor copy — DeepSeek | dữ liệu đã gửi vendor không có deletion API | ⚠️ ghi nhận trong VDR-001; mitigate dài hạn = M4 masked input; action PO: opt-out/verify retention |
| 13 | Vendor copy — Meta/Telegram | hội thoại tồn tại trên nền tảng kênh theo policy của họ (khách tự xóa phía app của họ) | ghi nhận trong notice |
| 14 | Vector/embedding | KB vectors = D0 product truth, KHÔNG có customer vector | ✅ n/a hiện tại (M4 slot store sẽ thêm mục mới) |
| 15 | `outbox_events` payload | Tin tới khách chưa gửi (pending/retry/dead_lettered) → `cancelled` (`data_deletion`); mọi tin tới khách: customer_ref → tombstone, bỏ text/params/tên/địa chỉ; thông báo staff gắn với khách (command/order/conversation/intent) bỏ customer_name/address/last_message. Worker: ref tombstone → hủy, KHÔNG gọi provider (`recipient_deleted`). `delivery_attempts` không chứa định danh | ✅ tự động (D405) |
| 16 | (S3 tương lai) `consent_records` | KHÔNG xóa evidence tuân thủ — khóa purpose "chứng minh tuân thủ" (§13.5) | thiết kế S3 |
| 17 | **M4 Stage 0P** `m4_shadow_review_samples` | `_delete_customer_data()` DELETE trực tiếp `WHERE customer_ref = customers.id` — KHÔNG join `conversations`/`messages` nên không phụ thuộc thứ tự (chạy trong CÙNG transaction, sau bước xóa conversations ở trên); vô điều kiện, không phụ thuộc pending-check của collector (F-M4-0P-02B/04). Guard `to_regclass` — môi trường chưa có migration 039 (production, tính tới CA Design Acceptance 29/7) bỏ qua bước này, không làm vỡ luồng xóa chính. | ✅ (F-M4-0P-04 CLOSED AT DESIGN LEVEL; evidence: `app/services/data_deletion.py`, smoke test DSR retry/idempotency PASS) |
| 18 | `command_executions` (M1) | conversation_id = NULL (gỡ FK — trước D405 FK này làm **rollback toàn bộ** lệnh xóa của khách từng đặt đơn qua chat); actor_id/causation_id/idempotency_scope chứa psid → tombstone; request_payload bỏ customer_name/phone_masked/psid | ✅ tự động (D405) |
| 19 | `order_intents` (M5) | conversation_id = NULL (gỡ FK); draft tên/SĐT/địa chỉ = NULL; intent đang mở → CANCELLED (`data_deletion`) | ✅ tự động (D405) |
| 20 | `fulfillment_conversations.customer_ref` (M7) | → tombstone (nhắc chuyển khoản/deadline không còn tới ChatID thật) | ✅ tự động (D405) |
| 21 | Container stdout (worker/listener Telegram) | log paused-path in `mask_ref` thay vì psid/ChatID thô | ✅ chặn từ nguồn (D405); log cũ → hạ tầng (#10) |

Kiểm tra footprint (chỉ đọc, output mask): `DSR_REF=<psid> python scripts/d405_dsr_footprint.py` quét MỌI bảng
public (`row::text`) + Redis (key, arq job, dead-letter); `--legacy` đếm customer tombstone psid nhưng còn ChatID thật.

### 2b. Ma trận DSR đầy đủ (CA Review 415 §3.1) — kho bất biến/append-only + bản sao ngoài DB active

**Đường xử lý kho bất biến:** hàm `dsr_anonymize_identity` (migration 077). Đặc điểm:
- `SECURITY DEFINER`, owner là role NOLOGIN `alpha3s_dsr`, chỉ có quyền UPDATE trên đúng các cột định danh.
- Trigger bất biến chỉ cho qua khi `current_user = alpha3s_dsr`. DELETE vẫn bị cấm, cột nghiệp vụ không có quyền sửa.
- Chỉ chạy được khi customer **đã tombstone trong cùng transaction**, nên không dùng được để sửa sổ của khách đang hoạt động.
- Tự ghi audit `dsr.anonymize`; nội dung là số dòng đã xử lý, không có định danh.
- Đầu vào là PSID/ChatID (thay bằng tombstone) và các giá trị tên/SĐT/địa chỉ cũ. Các giá trị này dùng để quét trường
  JSON và ghi chú tự do, thay bằng nhãn `[đã ẩn theo yêu cầu xóa dữ liệu]`.

**A. Kho active do Alpha3S kiểm soát — xử lý tự động trong transaction DSR.** Người chịu trách nhiệm: Dev (đường code).

| Kho | Định danh | Nguồn phát sinh | Giữ chứng từ? | Cách xử lý |
|---|---|---|---|---|
| `audit_log` | actor_ref/before/after: PSID, `customer:<psid>` (dữ liệu cũ), tên | đơn bot, GHN prepare, staff | Có (vết kiểm toán) | Thay ID bằng tombstone, PII bằng nhãn. Sau sửa nguồn chỉ ghi `customer:<id nội bộ>` |
| `order_events`, `inventory_movements` | actor_id/causation_id/idempotency_key: PSID | đơn bot (M2 ledger) | Có (sổ đơn/kho) | Thay bằng tombstone. Giữ nguyên số lượng/trạng thái/số dòng. Sau sửa nguồn ghi `customer:<id>` |
| `address_resolution` | street_text, raw_*, key `lv:<psid>:…` | live-verify, Dashboard | Giữ **mã hành chính** | Địa chỉ chi tiết và input thô → NULL; key → tombstone. Sau sửa nguồn key là `lv:c<id>:…` |
| `order_address_snapshot` | street_text | Gate E / Dashboard | Giữ mã + tên tỉnh/phường | street_text → NULL |
| `address_change_log` | customer_ref, giá trị cũ/mới | (dormant) | Không | Thay ref; giá trị → NULL |
| `address_confirmation_request/outbox` | bound_ref/payload | (dormant, staff CLI) | Không | Thay ID bằng tombstone |
| `ghn_shipment_create_operations` | snapshot: tên/SĐT/địa chỉ người nhận; note | bot/Dashboard tạo vận đơn | Giữ mã đơn GHN, khối lượng, phí, mã vùng | recipient → `{name:null, address_text:null, phone:"***xyz"}`; note → nhãn |
| `ghn_shipment_create_attempts` | actor `customer:<psid>` (cũ) | worker | Có | Thay bằng tombstone |
| `fulfillment_conversation_events` | reply_text (tin bot), command_key `msg:<psid>` (cũ), detail | M7 | Giữ bước/thời điểm | reply_text → NULL (như `messages`); ID → tombstone; PII → nhãn. Sau sửa nguồn: không fallback PSID |
| `payment_events`, `shipment_delivery_attempts` | command_key/recorded_by chứa PSID; note tự do | M6/M7, staff | Có (tiền/giao hàng) | ID → tombstone; note → nhãn. **Giữ** số tiền, `reference` (mã giao dịch ngân hàng) |
| `provider_events.raw` (SePay) | content/description (thường chứa tên người chuyển) | webhook SePay | Giữ số tiền, mã tham chiếu, thời gian | content/description → `[dsr]` |
| `staff_attention` | detail/resolution_note | M7/staff | Có | ID/PII trong detail → tombstone/nhãn; resolution_note → nhãn |
| `price_overrides.note` | ghi chú tự do | staff | Không | → nhãn |
| `pii_slots` | giá trị mã hoá | M4 (dormant) | Không | DELETE |
| Các mục §2 #1–#21 | (xem bảng trên) | | | Xử lý bằng code app trong cùng transaction |

**B. Giữ lại có căn cứ — sau DSR không còn định danh trực tiếp.** Người quyết định: PO/legal.

| Dữ liệu giữ | Căn cứ | Ghi chú |
|---|---|---|
| `orders` (số tiền, món, thời gian, trạng thái; `shipping_*` = NULL), `payments`, `payment_events` (số tiền, mã giao dịch NH), `shipments` (phí, mã vùng, mã vận đơn), GHN operation | Nghĩa vụ kế toán/thuế, đối soát với GHN và ngân hàng | Thời hạn lưu cụ thể **PO/legal chốt** (chưa cấu hình ở trung tâm) |
| SĐT dạng `***xyz` trong snapshot GHN | Đối soát vận đơn với GHN | **Quyết định PO/CA:** giữ 3 số cuối hay xoá hẳn |
| `consent_records` (evidence_ref mờ), `data_deletion_requests` (mã, trạng thái), audit `dsr.anonymize` | Chứng minh tuân thủ (P11) | Không chứa định danh |
| Dòng `customers` đã tombstone | Giữ khoá ngoại của đơn | Không có tên/SĐT/địa chỉ/PSID |

**C. Bản sao ngoài DB active — không hứa xoá nếu ngoài quyền kiểm soát của app.**

| Bản sao | Định danh | Kiểm soát | Xử lý |
|---|---|---|---|
| Redis | chat/profile/nlu_state/del_pending/addr_clarify, dead-letter | App | Xoá ngay; lỗi → `redis_pending` + worker 5 phút (§2 #6, #9). TTL tối đa 7 ngày |
| Backup `pg_dump` | toàn bộ DB tại thời điểm backup | App/hạ tầng (VPS) | Hết hạn theo vòng **14 bản/ngày**. **Cấm restore dữ liệu đã xoá về hệ active** (restore-non-resurrection) |
| Log container stdout | PSID/ChatID ở log cũ (trước khi mask) | Hạ tầng | Log mới đã mask. Log cũ mất khi container được tạo lại. **Chưa cấu hình xoay vòng log** (`json-file`, không có `max-size`) → đề xuất cấu hình, chờ PO |
| Meta (hộp thư Page), Telegram (chat khách + tin admin có PSID/tên/SĐT/tin gần nhất) | hội thoại | Nền tảng | Không xoá được từ app. Khách tự xoá phía nền tảng. Ghi trong chính sách quyền riêng tư |
| GHN (vận đơn), SePay/ngân hàng (sao kê), DeepSeek (input LLM) | người nhận, người chuyển, nội dung chat | Nhà cung cấp | Theo chính sách của họ (VDR-001). Không hứa xoá |

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
| 1 | ~~Dead-letter không nằm trong deletion propagation~~ | ✅ D405 |
| 2 | ~~Outbox payload cũ chứa PII~~ (phần gắn với khách đã xóa) | ✅ D405 |
| 2b | ~~Kho bất biến còn định danh~~ → hàm DSR quyền hẹp (077), ma trận §2b | ✅ CA 415 |
| 7 | Thời hạn lưu chứng từ kế toán + giữ SĐT `***xyz` trong snapshot GHN | PO/legal |
| 8 | Xoay vòng log container (`max-size`) | PO/hạ tầng |
| 3 | Restore-non-resurrection chưa có test | S6/S7 (AC-M3-07) |
| 4 | Rút consent per-purpose chưa chuẩn hóa | **S3** |
| 5 | SLA pháp lý chưa cấu hình central | PO/legal |
| 6 | Vendor copy DeepSeek | VDR-001 actions (PO) + M4 |
