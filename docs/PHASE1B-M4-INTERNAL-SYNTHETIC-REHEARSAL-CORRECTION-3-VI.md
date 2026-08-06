---
document_id: PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-CORRECTION-3-VI
title: "Phase 1B M4 — Dev Correction Note #3 (đáp CA Review #2)"
document_type: rehearsal_correction_note
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-08-05
answers: PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-REVIEW-2-VI.md (CA, CHANGES_REQUIRED_ACTIVATION_NOT_AUTHORIZED)
activation_performed: false
activation_gate: NOT_OPEN
language: vi-VN
---

# M4 — Rehearsal Readiness Correction Note #3

Đáp `PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-REVIEW-2-VI.md`. CA xác nhận phần lớn
thiết kế Package #2 đạt (F-R1-01/02/03/05/06), nhưng 5 finding mới (F-M4-RH-R2-01..05) cần sửa
trước khi review tiếp. Note này trả lời từng finding bằng code + evidence chạy thật.

## 0. Xác nhận phạm vi

Đúng như Submission #3 mục 5 yêu cầu: **production snapshot chỉ-đọc** thực hiện qua SSH, không
provision/seed/start/capture bất kỳ gì. Kết quả (xem §6): `capture_enabled=false`, 0 residual
synthetic, 0 active key, 0 biến môi trường `M4_*`, HEAD VPS vẫn `e96a3207` (không đổi kể từ
dormant deploy). Toàn bộ evidence sửa lỗi trong note này chạy trên sandbox cô lập tạo mới
(`alpha3s-rehearsal-test-db`/`-redis`), không đụng production.

## 1. F-M4-RH-R2-01 — Cleanup có thể thất bại nhưng runner vẫn trả thành công

**Sửa:** `_run_execute()` viết lại hoàn toàn phần cuối. Lifecycle chính giờ nằm trong
`try/except BaseException as e: main_exc = e` (không còn `return 0` sớm bên trong try). Sau đó,
**vô điều kiện**, 4 bước cleanup chạy (capture-off, retire key, purge, Redis postcheck), MỖI
bước tự ghi outcome vào `cleanup_step_ok` — nhưng quyết định exit KHÔNG dựa vào các outcome tự
báo này. Hàm mới `_verify_cleanup_postconditions()` chạy truy vấn **độc lập** ngay sau cleanup:
`capture_enabled` phải `false`, 0 customer/conversation còn lại theo đúng ID đã tracked, 0 sample
còn lại cho batch, cả 2 key phải `retired_at IS NOT NULL`. Nếu bất kỳ điều nào sai,
`_run_execute()` raise `SystemExit` với message bắt đầu `CLEANUP_FAILED (F-M4-RH-R2-01)` — **kể
cả khi lifecycle chính đã thành công** (main_exc là None) — đây chính là tình huống nguy hiểm
nhất CA chỉ ra, giờ không còn cách nào để runner âm thầm trả `0`.

**Evidence:** kịch bản `[5a]`/`[5b]` (xem §5 — fault-injection thật, không phải bản sao logic).

## 2. F-M4-RH-R2-02 — Chưa chứng minh 3 principal tách biệt trong lần chạy thật

**Sửa:** hàm mới `_check_approval_active()` đọc `recorded_by` TRỰC TIẾP từ
`m4_stage0p_capture_approvals` (không tin CLI argument nào khác). Cả `_run_dry_run()` và
`_run_execute()` giờ gọi `_assert_distinct_principals(recorded_by, operator_staff_id,
reviewer_staff_id)` — 3 giá trị đều đọc từ nguồn có thẩm quyền (DB cho recorder, CLI cho
operator/reviewer — 2 giá trị này CHÍNH LÀ credential thật sẽ dùng để pin_actor ngay sau đó,
nên so sánh chúng có thẩm quyền tương đương). Nếu `recorded_by` trùng operator hoặc reviewer,
`execute()` từ chối NGAY trước khi bật capture.

**Evidence:** toàn bộ kịch bản `[1]`/`[5a]`/`[5b]`/`[6]`/`[7]` dùng approval_ref record bởi 1
staff_id THẬT riêng biệt, khác operator/reviewer — nếu binding không hoạt động đúng,
`_assert_distinct_principals` sẽ không có cơ hội raise vì luôn nhận đúng 3 giá trị khác nhau
(đã verify bằng cách tạm thời cho operator_staff_id trùng approval_staff_id trong 1 lần chạy thử
cục bộ trong quá trình sửa — xác nhận execute() từ chối đúng trước khi hoàn tất sửa lỗi cuối).

## 3. F-M4-RH-R2-03 — Preflight không kiểm tra approval window đang có hiệu lực

**Sửa:** `_check_approval_active()` kiểm tra timezone-aware `valid_from <= now < valid_until`,
`requested_enabled=true`, đúng `purpose_code`, chưa revoke — TRẢ VỀ danh sách `problems` cụ thể.
`_run_dry_run()` giờ đưa các problems này vào danh sách chặn `return 1` (trước đây chỉ log thông
tin). **Quan trọng hơn:** `_run_execute()` gọi LẠI đúng hàm này NGAY TRƯỚC khi gọi
`set_capture_enabled(enabled=True, ...)` — không chỉ dựa vào 1 lần dry-run trước đó có thể đã cũ
(approval có thể hết hạn giữa lúc dry-run và lúc execute thật).

**Evidence:** kịch bản `[7]` — 4 case CLI `run --dry-run` thật: hợp lệ (rc=0), chưa bắt đầu
(rc=1), đã hết hạn (rc=1), đã thu hồi (rc=1) — đúng yêu cầu Submission #3 mục 4.

## 4. F-M4-RH-R2-04 — Exact-head/CI evidence bị lệch

**Nguyên nhân:** Package #2 khóa commit `da1d0a53...` (commit đầu), nhưng 1 commit sau đó
(`dea351ec...`, chỉ thêm PR reference vào tài liệu) làm head thực tế lệch khỏi commit đã khóa
trong package.

**Sửa:** Correction #3 này CHỈ push **1 lần duy nhất** sau khi hoàn tất toàn bộ sửa lỗi — không
push thêm sau khi ghi exact head vào §6. Head/commit/CI run cuối cùng được ghi NGAY SAU khi push
xong, không dự đoán trước (xem §6 bảng exact-head).

## 5. F-M4-RH-R2-05 — Test failure-path chưa chạy cleanup thật của runner

**Sửa:** viết lại hoàn toàn kịch bản `[5]` cũ (đã tự mô phỏng logic `finally` bằng tay) thành 2
kịch bản BLACK-BOX mới, gọi **subprocess thật** của `scripts/m4_stage0p_rehearsal_runner.py run`
(không import/gọi hàm nội bộ để giả lập):

- **`[5a]` capture-off thất bại thật:** poll DB tới khi `capture_enabled=true` (subprocess đang
  chạy), rồi **sabotage credential operator thật** (UPDATE `pin_secret_hash` sai) — lần
  `pin_actor()` kế tiếp trong cleanup của CHÍNH subprocess đó thất bại thật. Xác nhận: exit code
  ≠ 0, stdout chứa `"CLEANUP_FAILED"` + lý do đúng (`capture_enabled VAN la true sau cleanup`),
  và truy vấn DB độc lập xác nhận `capture_enabled` THẬT SỰ vẫn `true`.
- **`[5b]` purge thất bại thật:** poll DB tới khi customer synthetic xuất hiện, chèn 1 row
  `orders` tham chiếu tới 1 customer đó (FK mà `_purge_synthetic()` không biết) — `DELETE FROM
  customers` trong cleanup của subprocess thất bại thật vì `ForeignKeyViolationError`. Xác nhận:
  exit code ≠ 0, `CLEANUP_FAILED`, và DB độc lập xác nhận residual customer > 0 THẬT SỰ (đồng
  thời xác nhận capture-off vẫn thành công độc lập — 2 bước cleanup thất bại riêng biệt, không
  liên luỵ nhau).

Cả 2 kịch bản test tự dọn dẹp (khôi phục credential/xoá order/purge tay) sau khi xác nhận xong,
để sandbox sạch cho kịch bản kế tiếp.

## 6. Exact-head evidence

| Mục | Giá trị |
|---|---|
| PR | [ledanghoai-bot/a3s#6](https://github.com/ledanghoai-bot/a3s/pull/6) (`draft`) |
| Reviewed base (Review #2) | `e96a32079bffedc8f6dbdeb3bc2006f2cf5ef77a` |
| Reviewed head (Review #2) | `dea351ec29c75d073d6c47575d569c72a974983a` |
| **Head Correction #3 (mới, exact)** | *(điền sau khi push — xem cam kết §4: chỉ push 1 lần)* |
| CI run gắn đúng head trên | *(điền cùng lúc)* |

## 7. Full regression

`241 pytest PASS`, `ruff check app` clean, `ruff check` 3 file scripts/ mới clean, full evidence
suite M4 hiện có (`migration_test`/`sampling_test`/`kill_test`/`permissions_test`/
`evaluation_test`/`pool_test`) PASS không đổi baseline, `m4_stage0p_rehearsal_runner_test.py`
(nay 7 kịch bản, bao gồm 5a/5b black-box mới + 7 dry-run 4-case) — **RESULT: PASS**.

## 8. Đề nghị

CA review code tại exact head §6, đối chiếu §1-5 (5 finding) + §6 (evidence). Sau khi CA chấp
nhận readiness code, PO vẫn cần cấp `approval_ref`/scope/window hữu hạn riêng trước khi CA mở
Internal Synthetic Activation Gate — note này không suy diễn quyền activation.
