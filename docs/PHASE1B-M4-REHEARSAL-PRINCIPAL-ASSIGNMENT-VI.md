---
document_id: PHASE1B-M4-REHEARSAL-PRINCIPAL-ASSIGNMENT-VI
title: "Phase 1B M4 — PO Principal Assignment for Internal Synthetic Rehearsal"
document_type: po_principal_assignment
owner: PO
recorded_by: Dev
status: SUBMITTED — chờ CA khoá phân công + mở activation gate
created_at: 2026-08-06
language: vi-VN
---

# M4 — PO Principal Assignment (3 staff_id, không kèm secret)

Đáp `PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-REVIEW-4-VI.md` §5 và chỉ dẫn phân công
3 principal của CA. PO xác nhận phân công như sau và cung cấp 3 `staff_id` — **không có PIN/
secret nào trong hồ sơ này**.

## Phân công

| Vai trò | staff_id | username | Người đảm nhận | Quyền `m4_stage0p_staff_permissions` |
|---|---|---|---|---|
| Approval recorder | **3** | `m4-approval-recorder` | Người PO uỷ quyền (tài khoản riêng, khác PO Reviewer) | `m4.stage0p.approve` |
| Control operator | **4** | `m4-control-operator` | Dev lead — trực tiếp chạy rehearsal | `m4.stage0p.operate` |
| Reviewer / evaluator | **5** | `m4-reviewer-evaluator` | PO | `m4.stage0p.review`, `m4.stage0p.evaluate` |

Xác nhận đúng yêu cầu CA:

- 3 `staff_id` hoàn toàn khác nhau (3 ≠ 4 ≠ 5).
- Reviewer/evaluator (staff_id=5) là chính PO — Dev chỉ hỗ trợ thao tác kỹ thuật (hướng dẫn màn
  hình/câu lệnh/ý nghĩa kết quả), **không dùng credential của PO**, không thao tác dưới danh
  nghĩa PO.
- Approval recorder (staff_id=3) là tài khoản RIÊNG, khác tài khoản Reviewer của PO.
- Cả 3 tài khoản mới tạo, chỉ có đúng quyền `m4.stage0p.*` tương ứng vai trò — không gán
  `role_key`/quyền dashboard nghiệp vụ nào khác (least privilege).
- **PIN nghiệp vụ M4** (`m4_stage0p_actor_credentials.pin_secret_hash`, dùng cho `pin_actor()`
  lúc chạy rehearsal) — **CHƯA đặt cho bất kỳ ai**. Sẽ được chính người đảm nhận từng vai trò tự
  đặt riêng (Dev không biết, không thao tác hộ) ngay trước cửa sổ thực thi đã duyệt — không nằm
  trong phạm vi hồ sơ này.
- Mật khẩu đăng nhập dashboard (khác hoàn toàn PIN M4 ở trên) đã đặt mặc định, PO tự đổi qua màn
  hình đổi mật khẩu — không liên quan tới hồ sơ này, không phải secret cần gửi CA.

## Đề nghị

CA khoá phân công theo bảng trên, kiểm quyền (`m4_stage0p_staff_permissions` đã đúng như liệt
kê) và phát hành Internal Synthetic Activation Gate cho cửa sổ hữu hạn theo đúng trình tự đã nêu
ở Review #4 §5 bước 3-5. Approval_ref/scope/window cụ thể do PO cấp riêng ở bước kế tiếp, không
nằm trong hồ sơ phân công này.
