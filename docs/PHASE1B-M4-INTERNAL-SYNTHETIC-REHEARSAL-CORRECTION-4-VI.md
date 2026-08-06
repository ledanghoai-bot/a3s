---
document_id: PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-CORRECTION-4-VI
title: "Phase 1B M4 — Dev Correction Note #4 (đáp CA Review #3)"
document_type: rehearsal_correction_note
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-08-05
answers: PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-REVIEW-3-VI.md (CA, CHANGES_REQUIRED_ACTIVATION_NOT_AUTHORIZED)
code_head: 62ae6f62a0b5604cc4138b68d02a8e720097084e
activation_performed: false
activation_gate: NOT_OPEN
language: vi-VN
---

# M4 — Rehearsal Readiness Correction Note #4

Đáp `PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-REVIEW-3-VI.md`. CA xác nhận
F-R2-02/03 đóng hẳn, F-R2-01/04/05 PARTIAL — note này đóng nốt phần PARTIAL bằng 5 finding mới
(F-M4-RH-R3-01..05).

## 0. Về F-M4-RH-R3-01 (exact-head chưa khoá) — cách note này tránh lặp lại lỗi

Nguyên nhân gốc F-R2-04/R3-01: Correction trước ghi "điền sau khi push" trong chính commit được
push — không thể biết SHA của 1 commit trước khi nó tồn tại, nên vòng trước để placeholder rồi
quên khoá lại bằng 1 bước riêng.

**Cách làm đúng lần này:** `code_head` ở đầu file (`62ae6f62a0b5604cc4138b68d02a8e720097084e`)
là SHA của commit sửa lỗi code (đã push, đã CI xanh — CI run `31014966828` — **TRƯỚC KHI** note
này được viết) — không phải SHA dự đoán. Note này (Correction #4) tự nó nằm trong 1 commit
**sau đó, docs-only, không đổi bất kỳ file code nào** — SHA của chính commit đó chỉ được biết
SAU khi push, và không cần thiết phải tự nhắc tới trong nội dung của mình (nó không mô tả code
gì cả). CA review CODE tại `62ae6f62a0b5604cc4138b68d02a8e720097084e` (đã tồn tại, đã CI xanh,
không đổi từ lúc note này được viết tới lúc CA đọc) — PR head hiện tại (bao gồm cả commit
docs-only này) chỉ cần khớp lịch sử git bình thường, không phải "SHA dự đoán".

## 1. F-M4-RH-R3-02 — Capture-OFF còn phụ thuộc cờ nhớ cục bộ

**Sửa:** tách toàn bộ logic cleanup ra khỏi `_run_execute()` thành 2 hàm độc lập gọi được trực
tiếp — `_do_cleanup()` và `_do_cleanup_and_verify()`. Bước capture-off trong `_do_cleanup()` giờ
gọi `read_capture_enabled(admin_conn)` **đọc trạng thái THẬT từ DB** trước khi quyết định có thử
tắt hay không — hoàn toàn không còn dùng `state.capture_turned_on` cho quyết định này (biến đó
chỉ còn dùng để log/telemetry). Nếu DB báo đang `true`, LUÔN thử tắt, bất kể cờ nhớ nói gì.

**Evidence:** kịch bản `[8]` — bật capture qua đúng đường thật (`set_capture_enabled`), rồi CỐ Ý
tạo 1 `RehearsalState` với `capture_turned_on=False` (mô phỏng crash giữa lúc DB ghi xong và
lúc gán cờ), gọi TRỰC TIẾP `runner._do_cleanup()` (hàm thật) — xác nhận `capture_enabled` THẬT
SỰ chuyển về `false` dù cờ nói ngược lại.

## 2. F-M4-RH-R3-03 — Redis postcheck thất bại vẫn có thể trả thành công

**Sửa:** `_do_cleanup_and_verify()` giờ coi `cleanup_step_ok["redis_postcheck"] == False` là 1
ĐIỀU KIỆN ÉP `postcondition_ok = False` — không còn chỉ là 1 dòng log. Không cần xoá nonce (vẫn
giữ nguyên TTL tự hết hạn + bounded `SCAN`) — chỉ là: nếu KHÔNG XÁC NHẬN ĐƯỢC chính sách nonce
đã duyệt (do lỗi kết nối/scan), runner không còn được phép coi đó là "không sao, bỏ qua".

**Evidence:** kịch bản `[9]` — gọi TRỰC TIẾP `runner._do_cleanup_and_verify()` với `REDIS_URL`
bị phá (`redis://127.0.0.1:1/0`, cổng không tồn tại) trong khi MỌI thứ khác (DB) đều sạch (state
rỗng) — xác nhận `postcondition_ok=False` chỉ vì lý do Redis, đúng yêu cầu.

## 3. F-M4-RH-R3-04 — Postcondition verifier chưa fail có kiểm soát

**Sửa:** lệnh gọi `_verify_cleanup_postconditions()` bên trong `_do_cleanup_and_verify()` giờ
nằm trong `try/except` riêng — nếu BẢN THÂN verifier raise (vd mất kết nối DB giữa lúc đang truy
vấn), được coi là "KHÔNG THỂ XÁC MINH được trạng thái an toàn" = fail-closed, sinh ra đúng 1
`CLEANUP_FAILED` chuẩn hoá thay vì để traceback thoát thẳng. `admin_conn`/`pool` được đóng qua
`finally` ở tầng `_run_execute()` bao ngoài `_do_cleanup_and_verify()`, vô điều kiện.

**Evidence:** kịch bản `[10]` — gọi TRỰC TIẾP `_do_cleanup_and_verify()` với 1 connection ĐÃ
ĐÓNG sẵn cho tham số verifier dùng — xác nhận KHÔNG có exception thoát ra ngoài hàm, trả về
`postcondition_ok=False` với message rõ ràng bắt đầu "BAN THAN postcondition verifier loi...".

## 4. F-M4-RH-R3-05 — Thiếu raw DB black-box evidence tại exact head

**Sửa:** nộp kèm **evidence bundle** (`E:\Alpha3s\dev\rehearsal-support\evidence-correction-4\`)
gồm:

| File | sha256 |
|---|---|
| `runner_test_raw_output.log` (raw output đầy đủ 10 kịch bản, có command/timestamp/exit code) | `340117684eca3f3d617886d3781b555f8c910814674583791ea25d719ac1f7df` |
| `production_offstate_snapshot.log` (SSH read-only, có timestamp/target, không có secret) | `3454907bccc429879b8f7932ece2dba545d3c7fd599a2ae9c259d883527c5eb9` |
| `MANIFEST.txt` (mô tả command đầy đủ, sandbox identity chứng minh không phải production, code_head/CI run) | — |

`runner_test_raw_output.log` chứa NGUYÊN VĂN output CLI thật (không tóm tắt) của cả 10 kịch bản
(1,2,3,4,5a,5b,6,7,8,9,10), sinh RA SAU KHI `code_head` đã tồn tại và CI đã xanh — không phải
chạy trước rồi suy diễn khớp head. Sandbox identity (`alpha3s-rehearsal-test-db`/
`-redis`, throwaway, network `alpha3s_default`, KHÔNG phải `alpha3s-db-1`/`-redis-1`) ghi rõ
trong `MANIFEST.txt` để CA phân biệt với production.

## 5. Full regression

`241 pytest PASS`, `ruff check app` clean, `ruff check` 3 file scripts/ mới clean, evidence
suite M4 hiện có PASS không đổi baseline, `m4_stage0p_rehearsal_runner_test.py` (nay 10 kịch
bản) — **RESULT: PASS** (raw output trong evidence bundle §4).

## 6. Đề nghị

CA review code tại `code_head` = `62ae6f62a0b5604cc4138b68d02a8e720097084e` (CI run
`31014966828`, đã xanh trước khi note này viết), đối chiếu §1-4 (4 finding) + evidence bundle
§4 (F-R3-05) + §0 (F-R3-01). Sau khi CA chấp nhận readiness code, PO vẫn cần cấp
`approval_ref`/scope/window hữu hạn riêng trước khi CA mở Internal Synthetic Activation Gate —
note này không suy diễn quyền activation.
