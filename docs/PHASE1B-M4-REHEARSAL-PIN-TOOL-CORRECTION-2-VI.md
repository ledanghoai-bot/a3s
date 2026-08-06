---
document_id: PHASE1B-M4-REHEARSAL-PIN-TOOL-CORRECTION-2-VI
title: "Phase 1B M4 — Correction #2 (PIN Provisioning Tool) trả lời CA Review #2"
document_type: correction_note
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-08-06
answers: PHASE1B-M4-REHEARSAL-PIN-TOOL-REVIEW-2-VI.md (CA, CHANGES_REQUIRED_ACTIVATION_NOT_OPEN)
pr: https://github.com/ledanghoai-bot/a3s/pull/7 (vẫn DRAFT — CHƯA merge)
code_head: c653744e (đã push, CI xanh TRƯỚC khi note này được viết, không phải dự đoán)
ci_run: 31071892773
production_commit_unchanged: 3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585
language: vi-VN
---

# M4 — Correction #2 (PIN Provisioning Tool): trả lời CA Review #2

Đáp `PHASE1B-M4-REHEARSAL-PIN-TOOL-REVIEW-2-VI.md` (`CHANGES_REQUIRED_ACTIVATION_NOT_OPEN`), 3
finding F-M4-PIN-R2-01/02/03. Không có thay đổi nào tới `main` hay production — vẫn nằm trên
PR #7 (draft), production commit vẫn nguyên `3e87bf91e1c0f95ae84c45bbf2d2cd958d2f6585`.

## 1. F-M4-PIN-R2-01 (P1) — Issuer biết bearer token, có thể impersonate principal

**Vấn đề REV2:** `issue-token` tự sinh raw token RỒI in ra cho Dev/admin chuyển tiếp — Dev/admin
nhìn thấy bearer credential thật, có thể tự dùng nó trước người nhận thật.

**Sửa (REV3):** tách hẳn việc SINH token khỏi việc BIND token thành 2 vai trò khác nhau:

- Subcommand mới `generate-token`: **principal tự chạy trên chính session của họ, KHÔNG mở kết
  nối DB nào** (không cần `DATABASE_URL`) — sinh token cục bộ, in ra 2 giá trị TÁCH BIỆT rõ
  ràng: raw token (principal TỰ GIỮ, dùng 1 lần ở bước `provision-pin` sau này) và
  `sha256(token)` (giá trị DUY NHẤT principal đưa cho Dev/admin).
- `bind-token` (Dev/admin chạy) giờ **CHỈ nhận `--token-hash`** — không còn sinh hay nhìn thấy
  raw token dưới bất kỳ hình thức nào trong toàn bộ vòng đời của nó.

Test bắt buộc CA yêu cầu — đã viết và PASS (xem §4): `bind-token` không bao giờ in/nhận raw
token (kịch bản 3); token của A không bind được cho B (kịch bản 4); reuse/expired vẫn bị từ chối
(kịch bản 9/10).

## 2. F-M4-PIN-R2-02 (P1) — `issued_by` là caller-supplied, không phải authenticated identity

**Vấn đề REV2:** `--issued-by` chỉ kiểm tra account tồn tại/active — caller ghi ID bất kỳ.

**Sửa (REV3):** thêm bảng mới `m4_stage0p_pin_bind_approvals` (migration 041) — một ghi nhận
**RIÊNG BIỆT**, có `approval_ref`/`target_staff_id`/`recorded_by`/`valid_from`/`valid_until`/
`revoked_at`, phải TỒN TẠI VÀ CÒN HIỆU LỰC trước khi `bind-token` được phép chạy cho 1
`target_staff_id`. `bind-token` giờ **KHÔNG còn nhận `--issued-by` qua CLI nữa** — `issued_by`
được **server-side resolve TỪ chính approval record** đã được tham chiếu rõ ràng qua
`--approval-id`. 2 subcommand mới `record-bind-approval`/`revoke-bind-approval` cho ceremony
này vòng đời riêng, có thể thu hồi.

**Giới hạn trung thực (nêu rõ theo đúng yêu cầu CA "không được trình bày issued_by như một
security assertion"):** môi trường CLI này KHÔNG có authenticated session/SSO cho thao tác vận
hành, và đây CHÍNH LÀ công cụ bootstrap PIN đầu tiên nên KHÔNG THỂ dùng `pin_actor()` để xác
thực ngược (chicken-and-egg — chưa ai có PIN để xác thực). Vì vậy `record-bind-approval` KHÔNG
THỂ được chứng minh bằng mật mã là do đúng người gõ — đây là 1 audit trail có thể thu hồi, dựa
trên kỷ luật quy trình (PO hoặc người PO ủy quyền TỰ chạy trên SSH session của họ), **CÙNG mô
hình CA đã chấp nhận trước đó** cho `record-approval`/`m4_stage0p_capture_approvals` và PO
Decision Record — không phải một khẳng định danh tính được mã hóa. Việc cải thiện thực sự so
với REV2: ceremony này giờ là 1 sự kiện tách biệt, có timestamp/tham chiếu/khả năng thu hồi
riêng, xảy ra TRƯỚC và ĐỘC LẬP với bước bind — không còn gộp chung vào 1 lệnh duy nhất vừa lộ
bearer secret vừa tự khai issuer.

## 3. F-M4-PIN-R2-03 (P2) — TTL chưa có trần trên

**Sửa:** `bind-token --ttl-minutes` bị chặn cứng **[1, 30] phút**, kiểm tra ở CẢ 2 lớp: CLI
(trước khi chạm DB — kịch bản 8) và DB CHECK constraint mới `m4_pin_bootstrap_ttl_bounded`
(migration 041, `expires_at` phải nằm trong khoảng `issued_at + [1, 30]` phút). Ngoài khoảng bị
từ chối rõ ràng.

## 4. Test bắt buộc + regression đầy đủ

Viết lại `m4_stage0p_provision_pin_test.py` thành **11 kịch bản** (tăng từ 5 ở Correction #1),
tất cả PASS trên sandbox mới hoàn toàn (`alpha3s-rehearsal-test-db`, xóa ngay sau khi chạy xong):

1. `provision-pin` vẫn không có `--staff-id` dưới bất kỳ hình thức nào.
2. `generate-token` chạy hoàn toàn cục bộ (không cần `DATABASE_URL`) — hash in ra khớp
   `sha256(raw token)` tính độc lập.
3. Round-trip đầy đủ thật: `generate-token` → `record-bind-approval` → `bind-token` (chỉ nhận
   hash) → `provision-pin` → row → `m4_stage0p_pin_actor()` THẬT chấp nhận; `issued_by` khớp
   đúng `recorded_by` của approval; không bước nào để lộ token/PIN/bcrypt hash thật.
4. Approval bind cho staff A không dùng được để bind-token cho staff B.
5. `bind-token` không có approval khớp (approval-id giả) → từ chối, không tạo token row.
6. Approval bị thu hồi → `bind-token` sau đó bị từ chối ngay.
7. Approval hết hạn (window đã qua) → `bind-token` bị từ chối.
8. `ttl-minutes` ngoài [1,30] và `token-hash` sai định dạng → từ chối trước khi chạm DB.
9. Token đã dùng (consumed) → lần 2 bị từ chối (giữ nguyên từ REV2).
10. Token hết hạn → bị từ chối, không tạo credential (giữ nguyên từ REV2, sửa cách giả lập hết
    hạn cho khớp CHECK TTL mới).
11. PIN mismatch/quá ngắn → từ chối NHƯNG token vẫn dùng lại được (giữ nguyên từ REV2).

- `pytest -q` trong `alpha3s-api-1`: **241 passed**.
- `ruff check scripts/m4_stage0p_provision_pin.py scripts/m4_stage0p_provision_pin_test.py`:
  **All checks passed!**
- Bundle bằng chứng thô đầy đủ (lệnh/timestamp/exit code/output, source snapshot + hash):
  `E:\Alpha3s\dev\rehearsal-support\evidence-pin-correction-2\MANIFEST.txt`.

## 5. Nội dung REV2 giữ nguyên không đổi

Migration 040 (`m4_stage0p_pin_bootstrap_tokens`), việc `provision-pin` không nhận `--staff-id`,
token+credential ghi cùng 1 transaction, PIN mismatch không tiêu thụ token — tất cả giữ nguyên
như CA đã ghi nhận đạt ở Review #2 §5.

## 6. Việc CHƯA làm

Chưa merge PR #7. Chưa chạy tool/migration untracked trên production. Chưa provision PIN/key
thật, chưa record approval_ref (nghiệp vụ Stage 0P — khác với approval-bind ceremony ở đây, vốn
chỉ dùng nội bộ cho việc bind token), chưa seed/start bất kỳ tiến trình rehearsal nào, chưa bật
capture. Chờ CA review exact head `c653744e`.
