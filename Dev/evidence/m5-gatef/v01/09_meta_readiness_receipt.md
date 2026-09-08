# Meta Readiness Receipt (SANITIZED — no secrets/tokens) — CA Directive 243 §2.3

- **App mode / permission:** Meta app **LIVE / approved for external users** (PO-attested, 2026-09-08 — app đã ra khỏi dev mode; nhắn được người dùng ngoài test roles). `pages_messaging` khả dụng public.
- **Webhook signature verification (external-user path):** verified ở lớp `app/api/webhook.py::_valid_signature` (HMAC-SHA256 app_secret, `hmac.compare_digest`).
  - Test tổng hợp (synthetic secret, KHÔNG dùng secret thật): **valid signature ACCEPTED = True**, **tampered signature REJECTED = True** (xem `06_readback_and_signature.txt`).
  - Provider-event dedupe (inbound-event effective-once) bắt buộc — xem `02_gatef_dod_harness.txt` AC-4 (Messenger replay → no mutation).
- **Credential rotation status (BẮT BUỘC trước Messenger full-scope ON):**
  - **Phát hiện exposure (detection-only, không in giá trị):** `.env` từng được commit (≥1 commit chạm `.env`); chuỗi gán `PAGE_ACCESS_TOKEN=` xuất hiện trong **3 commit** lịch sử git. ⇒ `META_APP_SECRET` / `PAGE_ACCESS_TOKEN` bị coi là **exposed trong git history → PHẢI rotate**.
  - **Trạng thái rotate:** ❌ **CHƯA thực hiện.** Đây là hành động ops/PO (Dev không nhập credential). Messenger full-scope **KHÔNG được bật** cho tới khi rotate xong.
  - **Receipt template (PO/ops điền sau khi rotate — chỉ redacted, KHÔNG secret):**
    ```
    rotated_at_utc:        <ISO8601>
    secret_kind:           META_APP_SECRET | PAGE_ACCESS_TOKEN
    new_version_fingerprint: <sha256 12 ký tự đầu của secret mới, một chiều>   # KHÔNG phải secret
    old_invalidated:       true|false
    webhook_signature_after_rotate: pass|fail   # test lại _valid_signature với secret mới
    owner:                 <người thực hiện>
    ```
- **Kết luận:** Telegram không phụ thuộc Meta → sẵn sàng full-scope. Messenger: Meta app đã LIVE (hết chặn platform), CÒN LẠI 1 tiền đề bắt buộc = **rotate credential** trước khi bật `gate_e_fullscope_messenger`/`address_resolver_fullscope_messenger`. Nếu vì lý do nào Meta external chưa nhận traffic tại thời điểm bật, báo `BLOCKED_BY_META_PLATFORM` (Directive 243 §2.3), không tuyên bố live giả.
