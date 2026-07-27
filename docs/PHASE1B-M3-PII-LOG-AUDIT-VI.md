# PII-safe Logging — Baseline Audit (I-B M3-S0, đầu vào cho S4)

```yaml
owner: Dev
version: 1.0.0
audited_at: 2026-07-28 00:15+07:00
base: 9b49628a83ba1fe02b97913f20f33e4883560b5b
method: quét toàn bộ app/ (logger/print/exception path) — read-only
```

## 0. Phát hiện nền tảng

**Không có logging framework trong `app/`** — không `logging.getLogger`, không formatter/filter/level;
100% điểm log là `print()` ra stdout container. Chỉ có 1 hàm structured: `command/observability.py:20
log_event()` (JSON 1 dòng) nhưng nhận `**fields` tự do, không enforce redaction. Uvicorn access log
bật mặc định (ghi full path).

## 1. Gap ưu tiên (worklist S4)

| # | Điểm | Chi tiết | Mức |
|---|---|---|---|
| 1 | `app/workers/tasks.py:53` | DEAD-LETTER in nguyên webhook event: raw chat + PSID; cùng event lưu Redis dead-letter không TTL (`tasks.py:49-52`) | **HIGH** |
| 2 | Token rò qua `str(exception)` chứa URL | `messenger_profile.py:46` (Meta access_token + PSID); `telegram_listener.py:61,73,240,288,291`; `telegram_customer_listener.py:41,72,99,102`; `handoff.py:278,317` — URL Telegram `bot<TOKEN>/...` nằm trong HTTPStatusError | **HIGH (credential)** |
| 3 | `orchestrator.py:396-397, 409-413` | In 120/200 ký tự nội dung reply (ngữ cảnh xác nhận đơn → thường chứa tên/mã đơn/tổng tiền) | **HIGH** |
| 4 | Không framework/redaction/level | Nền tảng cho mọi gap còn lại | **HIGH** |
| 5 | `observability.py:23,25` | `log_event` không gọi `redact_generic()` dù đã có sẵn trong `command/redaction.py`; fallback in repr thô | MED |
| 6 | PSID trong URL path | `dashboard.py:109..248`, `admin.py:22` → uvicorn access log ghi PSID | MED |
| 7 | ~20 `print(f"...: {e}")` exception trần | asyncpg/httpx/pydantic exception có thể nhúng giá trị tham số (tools.py:283 order args; data_deletion.py:171 psid; nlu_hint.py; throttle.py:34 username+IP…) | MED |

## 2. Điểm đã làm đúng (giữ làm chuẩn)

- `command/redaction.py` (`mask_phone`, `redact_generic`) — đúng thiết kế, chưa nối vào log path.
- `audit_service.py:19-46,78-84` — `_SENSITIVE_KEYS` phủ credential+PII, redact đệ quy `before/after`
  trước khi INSERT. Chuẩn tốt nhất repo.
- `command/lifecycle.py`, `command/order_service.py` — log_event chỉ ID/error_code, không payload.
- `api/webhook.py` — không log gì tại điểm vào raw chat.
- `orchestrator.py:154-156` — không log/lưu sau khi xóa dữ liệu (tránh tái tạo khách vừa xóa).

## 2b. KẾT QUẢ S4 (2026-07-28 00:44+07:00) — đã sửa

| Gap | Xử lý |
|---|---|
| #1 dead-letter | KHÔNG print raw event (chỉ mid); Redis dead-letter TTL 7 ngày (RET-07) — payload giữ để replay trong Personal Data Zone |
| #2 token qua exception | `app/services/safe_log.py` — `safe_exc()` redact bot token/access_token/Bearer/SĐT/email (kể cả URL-encoded), áp vào TOÀN BỘ ~30 điểm `print(...{e})` trong app/ |
| #3 reply content | orchestrator chỉ log `reply_len`, không nội dung |
| #4 framework | chọn phương án nhẹ: `safe_exc` + `log_event` ENFORCE `redact_generic` (không tin call site) + fallback không in repr thô; framework đầy đủ = backlog |
| #5 log_event | enforced (observability.py) |
| #7 exception trần | toàn bộ qua `safe_exc`; throttle mask username/IP; data_deletion mask psid |
| Guard | `scripts/m3_pii_log_test.py`: unit redaction (raw/encoded/Unicode/httpx) + log_event enforce + **static guard** quét app/ chặn pattern tái xuất. ALL PASS EXIT=0 |

**Known limitation (khai báo cho CA):** #6 PSID trong URL path → uvicorn access log (hạ tầng): đổi
route là breaking API dashboard — đề xuất xử lý ở release (tắt/định dạng lại access log) hoặc
milestone sau; nêu trong Delivery Package như open release input.

## 3. Hướng xử lý S4 (dự kiến ban đầu — giữ làm lịch sử)

1. Đưa logging framework tối thiểu (structured, level, filter) hoặc chuẩn hóa qua `log_event` + bắt buộc
   `redact_generic` trong `log_event`.
2. Sanitize exception trước khi log (helper `safe_exc(e)`: cắt URL query/token, mask số).
3. Sửa từng điểm HIGH: dead-letter chỉ lưu/mở refs + TTL; bỏ in reply content (thay bằng
   flag/length/hash); wrap mọi call Telegram/Meta bằng error class không chứa URL.
4. Cân nhắc PSID→opaque id trong route path (hoặc tắt access log/uvicorn log format) — bàn với CA
   trong Delivery Package (đổi route là API-breaking cho dashboard).
5. Test guard: raw/encoded/Unicode PII case theo spec §10 (AC-M3-05).
