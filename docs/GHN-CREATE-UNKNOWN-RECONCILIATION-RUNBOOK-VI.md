# Runbook — Tạo vận đơn GHN: `unknown_reconciliation_required` và `not_found_unsettled`

CA Directive 393 (lifecycle), D421 B1 / CA 424 §2. Áp dụng khi gate `GHN_SHIPMENT_CREATE_BOT_ENABLED` / `GHN_SHIPMENT_CREATE_DASHBOARD_ENABLED` được bật. Hiện tại cả hai **OFF**.

## 1. Khi nào operation vào `unknown_reconciliation_required`

Hệ thống **không biết chắc** GHN đã tạo vận đơn hay chưa. Vì vậy không tự gửi lại, vì gửi lại có thể tạo **vận đơn trùng**. Các nguyên nhân (`last_error_class`):

| error_class | Ý nghĩa |
|---|---|
| `timeout_read`, `protocol` | Request đã gửi đi nhưng mất kết nối hoặc hết giờ chờ phản hồi |
| `http_408_maybe_created`, `http_5xx_maybe_created` | GHN trả lỗi máy chủ. Đơn **có thể đã được tạo** (D421 B1: trước đây coi là retry được, nay chuyển sang staff đối soát vì chưa chứng minh `client_order_code` idempotent) |
| `ok_without_order_code` | HTTP 200 nhưng thiếu mã vận đơn |
| `create_exception`, `lease_expired` | Worker lỗi hoặc chết giữa chừng |
| `reconcile_unknown`, `lookup_http_*` | Tra cứu GHN không cho kết quả chắc chắn (lỗi quyền/shop `..._CLIENT_NOT_OWNER_OF_SHOP`, 401 `..._UNAUTHORIZED`, 5xx, ...) |

Mỗi lần vào trạng thái này, hệ thống mở 1 `staff_attention` với reason `shipment_create`, ghi `why` và mã `client_order_code` đã mask.

## 2. Staff xử lý

1. Mở Dashboard **Giao hàng** → đơn → khung **Vận đơn GHN** → operation. Thông báo sau khi bấm cho biết kết quả `lookup` bên dưới.
2. Bấm **Đối soát với GHN**, tức `POST /dashboard/fulfillment/ghn-create/operations/{op_id}/reconcile`. Thao tác này chỉ đọc: tra `detail-by-client-code` bằng GET.

| Kết quả `lookup` | Hệ thống làm | Staff làm |
|---|---|---|
| `found` | Ghi mã vận đơn → `succeeded`, cập nhật shipment, báo khách, đóng attention | Không cần làm gì |
| `not_found` | → `failed_retryable`. Worker sẽ đối soát **một lần nữa** rồi mới tạo | Theo dõi kết quả |
| **`not_found_unsettled`** | **Giữ nguyên `unknown`**, attention vẫn mở. Attempt ghi `error_class=not_found_unsettled`, API trả `retry_after_s=60` | **Chờ ít nhất 60 giây** rồi bấm **Đối soát với GHN** lại (§3) |
| `unknown` | Giữ nguyên | Xem `error_class`. Lỗi quyền/shop/token → kiểm tra cấu hình GHN (Cài đặt → Tích hợp). Lỗi tạm → đối soát lại sau |

3. **Kiểm tra chéo trên cổng GHN** (khách hàng GHN → Quản lý đơn) theo `client_order_code` `A3S-<order>-<op>` **trước khi** chấp nhận tạo lại. Nếu cổng có đơn mà API vẫn báo không có: **không** tạo lại. Ghi mã vận đơn vào shipment theo quy trình thủ công và báo Dev.
4. **Dừng hẳn** khi đã chắc chắn GHN không có đơn và không muốn tạo nữa: bấm **Dừng yêu cầu**, tức `POST .../abandon`, kèm ghi chú bắt buộc → `failed_terminal`.

## 3. `not_found_unsettled` — vì sao phải chờ

GHN có thể chưa index kịp đơn vừa tạo, nên `detail-by-client-code` vẫn trả "Đơn hàng không tồn tại" trong vài giây đầu. Vì vậy, nếu kết quả "không tồn tại" về trong vòng **60 giây** (`LOOKUP_SETTLE_S`) kể từ lần create gần nhất, kết quả đó **không được dùng** để mở lại create.

**60 giây không phải là bảo đảm** GHN đã nhất quán, chỉ là ngưỡng tối thiểu. Nếu nghi ngờ (ví dụ lỗi trước đó là 5xx/timeout), luôn kiểm tra chéo trên cổng GHN (§2 bước 3) trước khi để hệ thống tạo lại.

## 4. Đường retry tự động còn lại (worker)

| Kết quả create | Worker |
|---|---|
| 429 / 425 (GHN từ chối trước khi xử lý), lỗi kết nối **chưa gửi** | `failed_retryable`, backoff 60/300/900 giây (hoặc theo `Retry-After`). Lần sau **luôn lookup trước**: `found` → succeeded; `not_found` → create; khác → `unknown` |
| 408 / 5xx / timeout / mất kết nối | **`unknown`, không tự retry** (§1) |
| 4xx khác, hoặc 200 + code ≠ 200 | `failed_terminal` (`rejected_http_<st>_code_<code>_<CODE_MESSAGE>`), attention `provider_rejected` |

Backoff đầu tiên (60 giây) ≥ `LOOKUP_SETTLE_S`; test khoá bất biến này.

## 5. Sau khi tạo thành công

Nếu `total_fee` GHN trả khi tạo khác phí đã báo khách (`quote.fee_vnd` trong snapshot): mở attention `provider_fee_mismatch` và audit `shipment.ghn_create.fee_mismatch`. Vận đơn vẫn giữ. Staff quyết định bù hoặc báo khách; hệ thống không tự huỷ.

## 6. Kill switch

Đặt `GHN_SHIPMENT_CREATE_BOT_ENABLED=false` / `GHN_SHIPMENT_CREATE_DASHBOARD_ENABLED=false` rồi `docker compose up -d api worker`. Worker sẽ không gọi GHN nữa (`gate_blocked`, 0 HTTP). Các operation đang `unknown` vẫn ở nguyên để đối soát khi bật lại.
