---
document_id: PHASE1B-M4-REHEARSAL-PIN-TOOL-CORRECTION-3-VI
title: "Phase 1B M4 — Correction #3 (PIN Provisioning Tool) trả lời CA Review #3"
document_type: correction_note
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-08-06
answers: PHASE1B-M4-REHEARSAL-PIN-TOOL-REVIEW-3-VI.md (CA, CHANGES_REQUIRED_ACTIVATION_NOT_OPEN)
pr: https://github.com/ledanghoai-bot/a3s/pull/7 (vẫn DRAFT — CHƯA merge)
code_head: 71af6eb3 (đã push, CI xanh TRƯỚC khi note này được viết, không phải dự đoán)
ci_run: 31073263482
production_commit_unchanged: 3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585
language: vi-VN
---

# M4 — Correction #3 (PIN Provisioning Tool): trả lời CA Review #3

Đáp `PHASE1B-M4-REHEARSAL-PIN-TOOL-REVIEW-3-VI.md` (`CHANGES_REQUIRED_ACTIVATION_NOT_OPEN`),
finding F-M4-PIN-R3-01 (code) + F-M4-PIN-R3-02 (chính sách vận hành). Không có thay đổi nào tới
`main` hay production — vẫn nằm trên PR #7 (draft), production commit vẫn nguyên
`3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585`.

## 1. F-M4-PIN-R3-01 (P1) — Revoked/expired approval sau bind không vô hiệu hóa token

**Vấn đề REV3:** `bind-token` chỉ kiểm approval TẠI THỜI ĐIỂM tạo token row — row
`m4_stage0p_pin_bootstrap_tokens` không lưu `approval_id`, nên `provision-pin` (bước consume)
chỉ còn kiểm được chính token (`consumed_at`/`expires_at`), không join lại được approval. Hệ
quả: approval bị revoke hoặc hết hạn SAU khi bind vẫn không ngăn được token đã bind provision
PIN thành công.

**Sửa (REV4)**, đúng 4 yêu cầu CA nêu trong §4:

1. **Token row phải tham chiếu approval_id**: migration mới `042_m4_pin_token_approval_link.sql`
   thêm cột `approval_id BIGINT NOT NULL REFERENCES m4_stage0p_pin_bind_approvals(id)` vào
   `m4_stage0p_pin_bootstrap_tokens`.
2. **Token expires_at = min(now + TTL yêu cầu, approval.valid_until)**: `bind-token` giờ tính
   `expires_at` bằng `MIN` của 2 giá trị — token không thể sống lâu hơn chính approval cho phép
   nó tồn tại. Nếu approval còn lại dưới 1 phút, `bind-token` từ chối hoàn toàn (không tạo token
   row) — không còn đủ thời gian tối thiểu.
3. **Tại consume, transaction phải JOIN/lock cả token và approval**: `provision-pin` bước tiêu
   thụ (trong `async with conn.transaction()`) giờ chạy 1 câu `SELECT ... FROM
   m4_stage0p_pin_bootstrap_tokens t JOIN m4_stage0p_pin_bind_approvals a ON a.id = t.approval_id
   WHERE ... AND a.revoked_at IS NULL AND now() < a.valid_until FOR UPDATE OF t, a` — yêu cầu
   approval CHƯA revoke VÀ còn trong validity window **TẠI THỜI ĐIỂM CONSUME**, không chỉ tại
   thời điểm bind.
4. **Revoke phải làm token liên quan không dùng được NGAY**: vì bước consume join lại approval
   mỗi lần, một approval bị revoke sau bind sẽ khiến điều kiện `a.revoked_at IS NULL` không còn
   đúng ngay lập tức — không cần đợi hết `valid_until`.
5. **Race giữa revoke và consume fail-closed theo row locking**: `FOR UPDATE OF t, a` khóa CẢ
   HAI row trong transaction consume — nếu `revoke-bind-approval` chạy đồng thời trên CÙNG
   approval, nó bị CHẶN bởi chính Postgres (row-level lock thật, không phải giả lập bằng code)
   cho tới khi transaction consume commit/rollback. Không còn trạng thái "vừa revoked vừa
   provisioned".

## 2. Test bắt buộc (§4 review) — cả 4 đã viết và PASS

Thêm 4 kịch bản mới (12-15) vào `m4_stage0p_provision_pin_test.py` (tổng 15, từ 11):

- **[12]** bind thành công → SAU ĐÓ revoke approval → `provision-pin` bị từ chối, không
  credential nào được tạo, và xác nhận riêng token bản thân KHÔNG bị đánh dấu consumed (bị chặn
  bởi approval, không phải bởi chính nó).
- **[13]** bind thành công (approval còn hiệu lực dài) → SAU ĐÓ đẩy `valid_until` của approval
  về quá khứ trực tiếp trong DB → `provision-pin` vẫn bị từ chối, MẶC DÙ `token.expires_at` của
  riêng nó (đã ghi cố định lúc bind, xác nhận độc lập vẫn còn ở tương lai lúc test chạy) — chứng
  minh việc từ chối đến từ join lại approval, không phải trùng hợp.
- **[14]** approval còn hiệu lực ngắn hơn TTL yêu cầu → `token.expires_at` THẬT SỰ bị cap theo
  `approval.valid_until` (sai số <2 giây), không theo TTL yêu cầu; approval sắp hết hạn dưới 1
  phút → `bind-token` từ chối hoàn toàn, không tạo token row.
- **[15]** race THẬT qua 2 kết nối Postgres đồng thời, dùng CHÍNH XÁC câu lệnh JOIN+FOR UPDATE
  mà `provision_pin()` dùng (không hand-copy sai lệch) — xác nhận revoke từ 1 connection khác
  THẬT SỰ bị Postgres row-level lock chặn (đo bằng timeout thật, không phải giả định), rồi sau
  khi lock được nhả, revoke hoàn tất và `provision-pin` sau đó bị từ chối đúng.

- `pytest -q` trong `alpha3s-api-1`: **241 passed**.
- `ruff check scripts/m4_stage0p_provision_pin.py scripts/m4_stage0p_provision_pin_test.py`:
  **All checks passed!**
- Bundle bằng chứng thô đầy đủ: `E:\Alpha3s\dev\rehearsal-support\evidence-pin-correction-3\
  MANIFEST.txt`.

## 3. F-M4-PIN-R3-02 (P2) — Ceremony phải khóa approval recorder PO đã chỉ định

CA chấp nhận **procedural bootstrap exception CHỈ cho lần synthetic-only run này**, với điều
kiện rõ ràng. Đây KHÔNG phải thay đổi code (không có "authenticated recorder" nào code có thể
cưỡng chế ở bước bootstrap này — đã nêu rõ giới hạn này ở Correction #2 §2) — đây là 1 cam kết
quy trình mà Dev ghi nhận và sẽ tuân thủ đúng khi thực thi rehearsal thật:

- `staff_id=3` (`m4-approval-recorder`, người PO chỉ định) sẽ là `recorded_by` cho **CẢ BA**
  `record-bind-approval` (targets 3/4/5) — KHÔNG dùng ID nào khác (ví dụ trong docstring của
  REV3 từng dùng `--recorded-by 5` chỉ là minh họa cú pháp, KHÔNG phải giá trị dự định dùng thật
  — đã sửa lại ví dụ trong docstring của tool để tránh gây hiểu nhầm).
- Mỗi target (3/4/5) dùng 1 `approval_ref` riêng, không trùng lặp/không nhập nhằng (ví dụ:
  `m4-pin-bind-<staff_id>-20260806-01`).
- Raw token CHỈ do từng principal tự giữ (đúng thiết kế `generate-token` từ REV3) — Dev/admin
  không bao giờ thấy raw token, chỉ thấy hash khi bind.
- Evidence của lần chạy thật sẽ KHÔNG chứa token/PIN/hash bí mật nào — đúng pattern đã kiểm
  chứng xuyên suốt REV2-REV4.
- Không mô tả `recorded_by` (kể cả khi = 3 đúng chính sách) như một xác nhận danh tính được mã
  hóa — nó vẫn là 1 audit trail dựa trên kỷ luật quy trình, như đã nêu rõ ở Correction #2.

## 4. Nội dung Review #3 ghi nhận đạt (giữ nguyên không đổi)

principal tự sinh raw token cục bộ; bind-token không nhận raw token; provision-pin không nhận
staff_id; format/TTL token bị chặn trước DB + DB có hard cap; target mismatch, missing/revoked/
expired approval TẠI BIND bị từ chối; token reuse/race, expired token, PIN validation có
evidence; PR vẫn draft, chưa có production mutation.

## 5. Việc CHƯA làm

Chưa merge PR #7. Chưa chạy tool/migration untracked trên production. Chưa provision PIN/key
thật, chưa record approval_ref nghiệp vụ Stage 0P, chưa seed/start bất kỳ tiến trình rehearsal
nào, chưa bật capture. Chờ CA review exact head `71af6eb3`.
