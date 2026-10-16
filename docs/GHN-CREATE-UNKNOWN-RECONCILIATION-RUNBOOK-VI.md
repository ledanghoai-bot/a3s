# Runbook — Tạo vận đơn GHN: `unknown_reconciliation_required`, `not_found_unverified`, `not_found_unsettled`

CA Directive 393 (lifecycle), D421 B1 / CA 424 §2 / CA 425 §2. Áp dụng khi gate `GHN_SHIPMENT_CREATE_BOT_ENABLED` / `GHN_SHIPMENT_CREATE_DASHBOARD_ENABLED` được bật. Hiện tại cả hai **OFF**.

## 0. Hai sự thật từ GHN staging (D421 B1, 16/10/2026)

1. **Gửi lại cùng `client_order_code` trả lại đúng vận đơn cũ** (HTTP 200, không tạo đơn thứ hai).
2. **Vận đơn đã huỷ cũng trả "Đơn hàng không tồn tại"** khi tra `detail-by-client-code`.

Hệ quả: một kết quả tra cứu "không tồn tại" **không phân biệt** được "chưa từng tạo" với "đã tạo rồi bị huỷ". Vì vậy, sau một lần gửi **có thể đã tới GHN**, hệ thống **không bao giờ tự tạo lại**.

## 1. Khi nào operation vào `unknown_reconciliation_required`

Hệ thống **không biết chắc** GHN đã tạo vận đơn hay chưa. Các nguyên nhân (`last_error_class`):

| error_class | Ý nghĩa |
|---|---|
| `timeout_read`, `protocol` | Request đã gửi đi nhưng mất kết nối hoặc hết giờ chờ phản hồi |
| `http_408_maybe_created`, `http_5xx_maybe_created` | GHN trả lỗi máy chủ; đơn **có thể đã được tạo** |
| `ok_without_order_code` | HTTP 200 nhưng thiếu mã vận đơn |
| `create_exception`, `lease_expired` | Worker lỗi hoặc chết giữa chừng |
| `reconcile_unknown`, `lookup_http_*` | Tra cứu GHN không cho kết quả chắc chắn (lỗi quyền/shop `..._CLIENT_NOT_OWNER_OF_SHOP`, 401 `..._UNAUTHORIZED`, 5xx, ...) |
| `not_found_unverified` | Worker tra cứu ra "không tồn tại" sau một lần gửi có thể đã tới GHN → không tạo lại |

Mỗi lần vào trạng thái này, hệ thống mở 1 `staff_attention` với reason `shipment_create`, ghi `why`, `operation_id` và mã `client_order_code` đã mask.

## 2. Staff xử lý

1. Mở Dashboard **Giao hàng** → đơn → khung **Vận đơn GHN** → operation. Thông báo sau khi bấm cho biết kết quả `lookup`.
2. Bấm **Đối soát với GHN** (`POST /dashboard/fulfillment/ghn-create/operations/{op_id}/reconcile`). Thao tác này chỉ đọc: tra `detail-by-client-code` bằng GET.

| Kết quả `lookup` | Hệ thống làm | Staff làm |
|---|---|---|
| `found` | Ghi mã vận đơn → `succeeded`, cập nhật shipment, báo khách, đóng attention | Không cần làm gì |
| **`not_found_unsettled`** (trong 60 giây sau lần gửi gần nhất) / **`not_found_unverified`** (sau 60 giây) | **Giữ nguyên `unknown`**, attention vẫn mở, **không tạo lại**. Ghi attempt `error_class` tương ứng và audit `reconciled_not_found_unverified` | Làm bước 3 |
| `not_found` | Chỉ xảy ra khi **mọi** lần gửi trước **chắc chắn chưa tới GHN** (op `failed_retryable` do 429/425 hoặc lỗi kết nối chưa gửi) → `failed_retryable`; worker tra lại rồi mới tạo | Theo dõi |
| `unknown` | Giữ nguyên | Xem `error_class`. Lỗi quyền/shop/token → kiểm tra cấu hình GHN (Cài đặt → Tích hợp). Lỗi tạm → đối soát lại sau |

3. **Xác minh trên cổng GHN** (khách hàng GHN → Quản lý đơn, **gồm cả đơn đã huỷ**) theo `client_order_code` `A3S-<order>-<op>`:
   - **Có vận đơn đang hiệu lực:** **không** tạo mới. Ghi mã vận đơn vào shipment theo quy trình thủ công và báo Dev.
   - **Có vận đơn nhưng đã huỷ, hoặc không có gì:** bấm **Dừng yêu cầu** (`POST .../abandon`), ghi chú **bằng chứng** (ví dụ: "Cổng GHN 16/10 10:05: A3S-12-3 đã huỷ / không có"). Operation → `failed_terminal`, attention **của operation đó** được đóng.
4. Nếu đơn còn cần giao: tạo **yêu cầu mới** theo luồng bình thường (Xem trước → Xác nhận). Yêu cầu mới có `client_order_code` **mới**, nên GHN không trả lại vận đơn đã huỷ của mã cũ.

Không có nút "tạo lại" cho operation cũ. Nếu sau này cần, phải thiết kế nút xác nhận tường minh và review riêng (CA 425 §2).

## 3. Mốc 60 giây (`LOOKUP_SETTLE_S`)

GHN có thể chưa index kịp đơn vừa tạo. "Không tồn tại" trong 60 giây đầu được báo riêng là `not_found_unsettled`, để staff biết nên chờ rồi đối soát lại: kết quả có thể chuyển sang `found`. **Sau 60 giây, kết quả vẫn không đủ để tạo lại** (§0). Hành động duy nhất là xác minh cổng GHN rồi Dừng yêu cầu (§2).

## 4. Đường retry tự động còn lại (worker)

| Kết quả create | Worker |
|---|---|
| 429 / 425 (GHN từ chối trước khi xử lý), lỗi kết nối **chưa gửi** | `failed_retryable`, backoff 60/300/900 giây (hoặc theo `Retry-After`). Lần sau **luôn tra cứu trước**: `found` → succeeded; `not_found` → create **chỉ khi không có lần gửi nào có thể đã tới GHN**, ngược lại → `unknown` (`not_found_unverified`); kết quả khác → `unknown` |
| 408 / 5xx / timeout / mất kết nối | **`unknown`, không tự retry** (§1) |
| 4xx khác, hoặc 200 + code ≠ 200 | `failed_terminal` (`rejected_http_<st>_code_<code>_<CODE_MESSAGE>`), attention `provider_rejected` |

## 5. Sau khi tạo thành công

Nếu `total_fee` GHN trả khi tạo khác phí đã báo khách (`quote.fee_vnd` trong snapshot): mở attention `provider_fee_mismatch` và audit `shipment.ghn_create.fee_mismatch`. Vận đơn vẫn giữ. Staff quyết định bù hoặc báo khách; hệ thống không tự huỷ.

## 6. Kill switch

Đặt `GHN_SHIPMENT_CREATE_BOT_ENABLED=false` / `GHN_SHIPMENT_CREATE_DASHBOARD_ENABLED=false` rồi `docker compose up -d api worker`. Worker sẽ không gọi GHN nữa (`gate_blocked`, 0 HTTP). Các operation đang `unknown` vẫn ở nguyên để đối soát khi bật lại.
