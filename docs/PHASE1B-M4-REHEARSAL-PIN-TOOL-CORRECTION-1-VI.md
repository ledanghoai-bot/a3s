---
document_id: PHASE1B-M4-REHEARSAL-PIN-TOOL-CORRECTION-1-VI
title: "Phase 1B M4 — Correction #1 (PIN Provisioning Tool) trả lời CA Review #1"
document_type: correction_note
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-08-06
answers: PHASE1B-M4-REHEARSAL-READINESS-SNAPSHOT-REVIEW-1-VI.md (CA, CHANGES_REQUIRED_ACTIVATION_NOT_OPEN)
pr: https://github.com/ledanghoai-bot/a3s/pull/7 (vẫn DRAFT — CHƯA merge)
code_head: 740e5e42 (đã push, CI xanh TRƯỚC khi note này được viết, không phải dự đoán)
ci_run: 31069326260
production_commit_unchanged: 3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585
language: vi-VN
---

# M4 — Correction #1 (PIN Provisioning Tool): trả lời CA Review #1

Đáp `PHASE1B-M4-REHEARSAL-READINESS-SNAPSHOT-REVIEW-1-VI.md`
(`CHANGES_REQUIRED_ACTIVATION_NOT_OPEN`), 3 finding F-M4-PIN-R1-01/02/03. Không có thay đổi nào
tới `main` hay production trong lần sửa này — toàn bộ vẫn nằm trên PR #7 (draft), production
commit vẫn nguyên `3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585` như PO Decision Record đã khóa.

## 1. F-M4-PIN-R1-01 (P1) — Tool không bind người chạy với staff_id

**Thiết kế cũ (REV1, bị CA từ chối):** `provision-pin --staff-id N` nhận `staff_id` trực tiếp từ
caller — bất kỳ ai chạy được `docker exec` đều có thể tự chọn 3/4/5.

**Thiết kế mới (REV2, hướng 2 CA đề xuất — single-use bootstrap token):**

- Migration mới `040_m4_pin_bootstrap.sql`: bảng `m4_stage0p_pin_bootstrap_tokens` (`token_hash`
  PK — CHỈ lưu sha256, KHÔNG BAO GIỜ lưu token gốc; `staff_id` FK; `issued_by` FK; `issued_at`/
  `expires_at` có CHECK `expires_at > issued_at`; `consumed_at`). Không GRANT cho `alpha3s_app`
  hay `PUBLIC` — cùng mô hình "ngoài luồng qua superuser" đã dùng cho
  `m4_stage0p_actor_credentials`/các bảng key.
- Subcommand mới `issue-token --staff-id N --issued-by M --ttl-minutes T`: Dev/admin phát 1 token
  ngẫu nhiên (32 byte) **BUỘC SẴN với 1 staff_id cụ thể ngay lúc tạo**, in ra token gốc DUY NHẤT 1
  LẦN, chỉ lưu hash.
- Subcommand `provision-pin`: **KHÔNG CÒN nhận `--staff-id` (hay bất kỳ biến thể nào) dưới bất kỳ
  hình thức nào** — chỉ hỏi token qua `getpass` (không echo), `staff_id` được **server-side
  resolve từ chính token đó**. Token bị tiêu thụ trong CÙNG transaction với việc ghi PIN — xác
  nhận PIN thất bại (mismatch/quá ngắn) KHÔNG tiêu thụ token, cho phép thử lại với CÙNG token; chỉ
  thành công thật sự mới tiêu thụ.

Kết quả: về mặt cấu trúc, không còn cách nào để caller chọn staff_id của người khác — họ chỉ có
thể provision đúng staff_id đã được bind sẵn vào token họ đang cầm.

**Test bắt buộc (đã viết, đã PASS — xem §3):** token của A không dùng được cho B (đảm bảo cấu
trúc, không phải test riêng lẻ vì không còn input surface để thử "B"); token reuse bị từ chối;
token expired bị từ chối; không log PIN/token/hash thật ở bất kỳ output nào.

## 2. F-M4-PIN-R1-02 (P1) — Tool chưa nằm trong authorized deployed commit

Xác nhận: PR #7 **VẪN Ở TRẠNG THÁI DRAFT**, chưa merge. Code head hiện tại `740e5e42` (đã push,
CI run `31069326260` xanh) — nhưng **KHÔNG được chạy trên production** cho tới khi:

1. CA review + accept exact head này (hoặc head sửa tiếp nếu còn finding);
2. PO mở một merge/deploy-dormant gate **riêng** cho PR #7 (theo đúng tiền lệ PR #6 — PO xác nhận
   rõ ràng "tiến hành merge + dormant deploy", Dev không tự merge);
3. Dev merge + deploy dormant + nộp OFF-state evidence;
4. PO re-baseline `deployed_commit` trong PO Decision Record (nếu window 24h vẫn còn hiệu lực,
   không cần approval_ref mới; nếu window đã hết, cần PO quyết định lại).

Note này KHÔNG yêu cầu hay giả định merge — chỉ báo cáo code đã sẵn sàng để CA review tiếp.

## 3. F-M4-PIN-R1-03 (P2 Evidence) — Thiếu raw test artifact

Bundle bằng chứng thô đã được tạo, KHÔNG chỉ source+hash: `pin_provision_test_raw_output.log`
(lệnh, sandbox identity, timestamp start/end, exit code, toàn bộ stdout/stderr của cả 5 kịch bản
— PASS/PASS/PASS/PASS/PASS, `RESULT: PASS`), cộng source snapshot + hash của 3 file thay đổi
(`040_m4_pin_bootstrap.sql`, `m4_stage0p_provision_pin.py`, `m4_stage0p_provision_pin_test.py`),
gắn đúng `code_head=740e5e42`. Chi tiết đầy đủ trong
`E:\Alpha3s\dev\rehearsal-support\evidence-pin-correction-1\MANIFEST.txt`.

Sandbox: container `alpha3s-rehearsal-test-db` (pgvector/pgvector:pg16) tạo mới hoàn toàn cho lần
chạy này, trên network `alpha3s_default`, KHÔNG phải `alpha3s-db-1` (dev stack chung) và KHÔNG
phải production — đã xoá ngay sau khi chạy xong (test PIN + regression đầy đủ).

## 4. Regression đầy đủ

- `pytest -q` trong `alpha3s-api-1`: **241 passed**.
- `ruff check scripts/m4_stage0p_provision_pin.py scripts/m4_stage0p_provision_pin_test.py`: **All
  checks passed!**
- Migration `040_m4_pin_bootstrap.sql` áp dụng sạch qua `scripts/migrate.py up` (cùng 39 migration
  trước + migration mới, tổng schema hiện tại của nhánh này = 40).

## 5. Bug tự phát hiện trong lần sửa này (không liên quan trực tiếp tới finding, ghi nhận minh
   bạch)

- Postcondition ban đầu của migration 040 dùng
  `has_table_privilege('PUBLIC', 'public...', 'SELECT')` — cú pháp không hợp lệ trong Postgres
  (không có role literal tên `'PUBLIC'` mà hàm này chấp nhận dưới dạng chuỗi), gây
  `UndefinedObjectError`. Đã sửa bằng cách bỏ dòng check đó, khớp tiền lệ migration 038 (không
  bao giờ check `has_table_privilege` với chuỗi `'PUBLIC'`/`'public'` trực tiếp).
- Kịch bản test 4 (giả lập token hết hạn) ban đầu chỉ lùi `expires_at` về quá khứ, vi phạm CHECK
  `expires_at > issued_at` của chính bảng (vì `issued_at` vẫn ở "vừa nãy"). Đã sửa bằng cách lùi
  CẢ HAI cột về quá khứ, giữ đúng thứ tự `issued_at < expires_at`, đồng thời `expires_at` vẫn nhỏ
  hơn `now()` để kích hoạt đúng nhánh "hết hạn" thật sự trong `provision_pin()`.

## 6. Việc CHƯA làm (đúng như giới hạn đã nêu trong review)

Chưa record approval_ref, chưa provision PIN/key thật trên production, chưa seed/start bất kỳ
tiến trình rehearsal nào, chưa bật capture. PR #7 chưa merge — chờ CA review exact head
`740e5e42`.
