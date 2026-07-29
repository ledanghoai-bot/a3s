---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-3-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #3
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-30
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-3-VI.md (CA, CHANGES_REQUIRED, reviewed_head 4f76d2ead93a8cd46d0aec453cf596859fe9ca7b)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #3

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-3-VI.md` — sửa đúng 6 finding P1 `T3-01..T3-06`.
CA ghi chú tên hồ sơ Dev trước đó (`...CORRECTION-2-VI.md`) thực chất là vòng correction thứ ba
trong chuỗi — hồ sơ này đặt tên **Correction #3** theo đúng số thứ tự nộp thật (Submission #1 →
Correction #1 → Correction #2 → **Correction #3**), khớp với cách CA gọi trong §4 Resubmission
của Review #3. Phạm vi KHÔNG đổi: dev/test trên branch M4 (worktree `D:\alpha3s-m4`, KHÔNG
checkout trong `D:\alpha3s`), dữ liệu synthetic/test, **KHÔNG** merge/deploy/production-data-
access/activation. Không mở rộng scope ngoài việc cụ thể hóa state machine/security boundaries
theo đúng yêu cầu CA.

## 1. Mapping 6 finding → sửa

| Finding | Sửa | File |
|---|---|---|
| **T3-01** `record_sample` bypass toàn bộ control/pending/fetch authorization — role collector `EXECUTE` được hàm này ĐỘC LẬP với dữ liệu (customer_ref/conversation_ref/retention/normalization) do caller tự khai, không chứng minh đã qua `fetch_message_content` | Viết lại `m4_stage0p_record_sample` — chữ ký còn đúng 7 tham số (`batch_id,conversation_id,message_id,sample_id,encrypted_message,canonical_text_len,truncated`), KHÔNG còn nhận refs/retention/normalization từ caller — hàm TỰ derive `customer_ref` (JOIN `conversations`), TỰ đọc `retention_days`/`normalization_version` từ chính batch row. Cơ chế capability token transaction-scoped: `m4_stage0p_fetch_message_content` khi thành công gọi `PERFORM set_config('alpha3s.m4_fetch_token', batch_id\|\|':'\|\|conversation_id\|\|':'\|\|message_id, true)` (`true`=LOCAL, tự mất khi transaction kết thúc); `record_sample` đối chiếu `current_setting(...) = v_expected_token`, RAISE nếu không khớp — buộc 2 lệnh gọi phải nằm CÙNG 1 transaction Python (`async with collector_conn.transaction():`), không thể tái dùng token cũ hay gọi độc lập với dữ liệu bịa. Batch status/pending vẫn được re-check bên trong (kế thừa REV3) | `migrations/039_m4_stage0p.sql` §5b/§5c; `app/services/pii/stage0p_sampling.py:_run_fenced_unit` |
| **T3-02** Seal không đóng collection — collector functions chỉ chặn `status='closed'` (giá trị không có đường vận hành nào đạt tới), `record_sample` không kiểm `labels_sealed_at`, prediction có thể đọc/ghi trong lúc collector còn thêm row | State machine 6 giá trị tường minh trên `m4_selection_batches.status` (`locked→collecting→collection_closed→labels_sealed→predictions_written→evaluation_completed`), CHECK constraint ép đúng tập giá trị. Hàm mới `m4_stage0p_close_collection(batch_id)` — row-lock `FOR UPDATE`, đối chiếu `captured_count` với `COUNT(*)` thực tế trên bảng sample (RAISE nếu lệch — dấu hiệu bug cần điều tra thay vì âm thầm đóng batch không nhất quán), chuyển `collection_closed`. MỌI hàm downstream (`peek_next_candidate`, `fetch_message_content`, `record_sample`, `seal_labels`, `write_predictions`, `complete_evaluation`) đọc `v_batch` qua `FOR UPDATE` và kiểm đúng giá trị status tiền điều kiện — bất biến 1-chiều-không-lùi. `run_collector()` khi `peek` báo `exhausted` THẬT SỰ (không phải do control OFF/fence timeout) tự gọi `close_collection` | `migrations/039_m4_stage0p.sql` §4 (CHECK constraint)/§5a-§5h; `app/services/pii/stage0p_sampling.py:run_collector` |
| **T3-03** Exclusion chỉ cần `reason` không rỗng — có thể loại toàn bộ corpus, đạt coverage giả, complete evaluation với gate rỗng | `write_predictions` thêm tham số `p_current_normalization_version`; mỗi exclusion phải có `reason` nằm trong allowlist DB-side (hiện chỉ `normalization_version_mismatch`) — RAISE nếu ngoài allowlist; với lý do đó, DB TỰ ĐỐI CHIẾU `normalization_version` thật của row với giá trị hiện hành, RAISE nếu claim SAI (chống caller khai khống). Gate cứng mới: `excluded_count * 2 > total_count` → RAISE `INSUFFICIENT_DATA`, từ chối ghi (không chỉ đánh dấu) — chặn kịch bản loại ≥50% corpus | `migrations/039_m4_stage0p.sql` §5g; `app/services/pii/stage0p_prediction.py` |
| **T3-04** Report hash hash `p_metrics` tùy ý do evaluator truyền — DB không recompute, "metrics hoàn hảo" giả có thể được chứng thực | XÓA HẲN tham số `p_metrics` khỏi `m4_stage0p_complete_evaluation` — chữ ký còn `(batch_id, actor_staff_id, expected_result_hash)`. DB TỰ TÍNH exact-span TP/FN/FP trực tiếp từ `labeled_slots`/`predicted_slots` JSONB bằng SQL (multiset intersection theo `(sample_id,slot_type,start,end)` — khóa `sample_id` trong điều kiện JOIN để không khớp chéo giữa các sample, tương đương ngữ nghĩa 1-1 exact-match của `exact_span_match()` Python), rồi tự tính `recall`/`precision`/`evaluation_report_hash` từ chính metrics đó. Hàm Python `compute_batch_metrics()` (REV3) bị xóa — không còn load-bearing | `migrations/039_m4_stage0p.sql` §5h; `app/services/pii/stage0p_evaluation.py` |
| **T3-05** Approval bảng dùng `approval_ref` PK, recorder chỉ INSERT+SELECT, không có đường revoke khả dụng (`status='revoked'` cùng ref sẽ conflict PK) | Bảng `m4_stage0p_capture_approvals` bỏ hẳn cột `status` — bất biến từ lúc ghi. Bảng mới `m4_stage0p_capture_approval_revocations` (`approval_ref` PK+FK, `revoked_by`, `revoked_at`, `reason`) — append-only, thu hồi là 1 SỰ KIỆN riêng thay vì sửa row cũ. 2 hàm SECURITY DEFINER mới: `m4_stage0p_record_approval(...)` và `m4_stage0p_revoke_approval(approval_ref, actor_staff_id, reason)` — cả hai validate actor active + audit trong thân hàm. Role `alpha3s_m4_approval_recorder` mất HẲN `INSERT`/`SELECT` trực tiếp trên cả 2 bảng — chỉ còn `EXECUTE` 2 hàm này. `m4_stage0p_set_capture(ON)` thêm điều kiện `NOT EXISTS (SELECT 1 FROM ...revocations WHERE approval_ref=a.approval_ref)` | `migrations/039_m4_stage0p.sql` §2b/§5d/§5d2; `app/services/pii/stage0p_control.py:record_capture_approval,revoke_capture_approval` |
| **T3-06** `labels_sealed_hash` chỉ hash `sample_id+labeled_slots` — không bind normalization/truncation/canonical-length/batch membership; `result_hash` không bind evaluation batch đầy đủ | Domain tag hash bump: `'m4-stage0p-label-hash-v1'→v2` (canonical string thêm `batch_id\|\|normalization_version\|\|truncated\|\|canonical_text_len`), `'m4-stage0p-result-hash-v1'→v2` (thêm `evaluation_batch` vào chuỗi hash). Bump domain tag (không chỉ mở rộng nội dung hash cùng tag cũ) để tránh va chạm ngầm giữa hash cũ/mới nếu có dữ liệu residual | `migrations/039_m4_stage0p.sql` §5e/§5g |

## 2. Nguyên tắc sửa chung (không đổi so với Correction #1/#2, áp dụng sâu hơn)

Toàn bộ 6 finding tiếp tục quy về: **kiểm tra và ghi đặc quyền phải được DB enforce nguyên tử,
không tin dữ liệu/khẳng định do Python truyền vào**. REV4 mở rộng nguyên tắc này sang 2 chiều mới:
(a) **"đã làm bước A trước" không còn là quy ước lập trình mà là một capability token do DB tự
cấp/tự tiêu thụ trong cùng transaction** (T3-01) — không tin call sequence phía Python, chỉ tin
bằng chứng DB có thể tự xác minh; (b) **giá trị "tính toán được" (metrics, exclusion-reason) phải
do DB tự tính/tự xác minh từ dữ liệu gốc, không tin JSON caller khẳng định là đúng** (T3-03/T3-04)
— cùng tinh thần "không tin caller" của T2-04 (hash) nhưng áp cho cả nội dung phán đoán, không chỉ
định danh.

## 3. Bug tự phát hiện trong lúc triển khai (khai báo minh bạch)

1. **Lỗi chính tả trong message `RAISE EXCEPTION` của gate exclusion-ratio** — viết nhầm
   `(%/%đ)` (ký tự `đ` tiếng Việt chen vào giữa placeholder `%` thứ hai) thay vì `(%/%)`. PL/pgSQL
   thay thế `%` theo vị trí bất kể ký tự theo sau, nên lỗi này thuần túy thẩm mỹ (không phải lỗi
   cú pháp SQL) — chuỗi sẽ hiện `(3/5đ)` thay vì `(3/5)`. Tự phát hiện khi đọc lại migration trước
   khi test, sửa bằng 1 `Edit` trực tiếp trước lần chạy evidence đầu tiên.
2. **`m4_stage0p_evaluation_test.py` §[8] (T2-02 cũ) va chạm với gate mới T3-03** — kịch bản gốc
   tạo batch 1 sample duy nhất, cố tình loại (exclude) sample đó để kiểm tra "lý do exclusion được
   ghi rõ ràng". Với gate `INSUFFICIENT_DATA` mới (T3-03), 1/1 loại = 100% vượt ngưỡng 50%, script
   gốc sẽ RAISE thay vì đi tới assertion dự kiến. Không phải bug sản phẩm — batch 1-sample-100%-
   loại đúng là kịch bản T3-03 CHỦ ĐÍCH chặn. Sửa test: thêm 1 sample thứ hai khớp
   `normalization_version` hiện hành (dự đoán bình thường), giữ tỉ lệ loại đúng 50% (không vượt
   ngưỡng `>50%`) để bài test vẫn kiểm đúng mục tiêu gốc (exclusion có lý do rõ ràng) mà không va
   gate mới; cập nhật lại assertion `remaining2` ở bước purge cuối cho khớp 2 sample thay vì 1.
3. **`m4_stage0p_permissions_test.py` — `fetch_message_content` kiểm `control_off` TRƯỚC status
   batch** — thứ tự kiểm tra bên trong hàm (kill switch trước, batch status sau — cố ý, ưu tiên
   dừng sớm nhất có thể khi control tắt) khiến 1 test mới viết cho T3-02 ("fetch trên batch đã
   `collection_closed` phải RAISE") thất bại khi chạy với `capture_enabled=false` từ bước trước đó
   — hàm trả `status='control_off'` (không RAISE) thay vì chạm tới nhánh kiểm status. Không phải
   bug sản phẩm (thứ tự đó đúng theo thiết kế F-M4-0P-01B: ưu tiên kill switch). Sửa test: bật
   control ON tạm thời ngay trước lệnh gọi đó để thực sự chạm nhánh kiểm tra status, tắt lại ngay
   sau.

## 4. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`, DB drop-sạch + migrate lại từ đầu ngay trước loạt chạy cuối)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `migrate.py up` (DB drop sạch object M4) | 0 | `OK 039_m4_stage0p`, postcondition PASS ngay lần đầu (không có bug SQL tự phát hiện vòng này, khác Correction #1/#2) |
| 2 | `m4_stage0p_migration_test.py` | 0 | RESULT: PASS (fresh+idempotent+existing-apply+rollback) |
| 3 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS — ma trận 5 bảng (thêm `m4_stage0p_capture_approval_revocations`), ma trận EXECUTE 11 hàm×11 role (3 hàm mới: `close_collection`/`record_approval`/`revoke_approval`), hardening 11 hàm+trigger; T3-01: `record_sample` gọi độc lập bị từ chối, gọi ở 2 transaction khác nhau (token LOCAL đã mất) bị từ chối, gọi cùng transaction với fetch thành công; T3-02: `close_collection` đối chiếu counter đúng/sai, chặn record_sample/peek/fetch/seal sau khi đóng, chặn đóng lặp; T3-03: reason ngoài allowlist bị từ chối, false-claim mismatch bị DB tự phát hiện và từ chối, tỉ lệ loại 2/3 (>50%) bị từ chối INSUFFICIENT_DATA; T3-04: metrics DB tự tính đúng cả trường hợp FP thuần và TP khớp chính xác (so khớp bằng tay); T3-05: approval hết hạn/không tồn tại/đã bị thu hồi đều bị từ chối cho ON, OFF luôn thành công, thu hồi lặp và thu hồi approval không tồn tại đều bị từ chối, `approval_recorder` không còn INSERT/SELECT trực tiếp trên 2 bảng |
| 4 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — chỉ 1 sửa chữ ký gọi (`record_capture_approval` bỏ `status=`), toàn bộ 9 kịch bản REV3 (Redis hang/DB write hang/process death/kill giữa chừng/DB-native boundary/…) không đổi hành vi, xác nhận REV4 không phá vỡ timeout/fencing đã đóng ở Correction #2 |
| 5 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J, chỉ sửa 1 chữ ký gọi approval giống kill_test; kịch bản [G] pending-race giờ có thêm log `collection_closed=true` xác nhận `run_collector` tự đóng collection khi hết ứng viên thật) |
| 6 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS — bỏ `compute_batch_metrics()` (đã xóa), `complete_evaluation()` không còn truyền `metrics`; 2 batch test chuyển sang tạo sẵn ở `status='collection_closed'` (điều kiện tiên quyết mới của seal — T3-02); batch trạng thái cuối đổi từ `'closed'`→`'evaluation_completed'` (state machine 6 giá trị); §[8] thêm 1 sample giữ tỉ lệ loại đúng 50% (xem §3.2) |
| 7 | `pytest -q` (full) | 0 | **241 passed** (không đổi so với Correction #2 — thay đổi REV4 chỉ ở DB boundary/Python wrapper mỏng, không chạm logic thuần `stage0p_evaluation.py` các hàm `exact_span_match`/`overlap_match`/`aggregate_micro`/… mà `tests/test_m4_stage0p_evaluation.py` kiểm) |
| 8 | `ruff check app/services/pii/ scripts/m4_stage0p_*.py tests/test_m4_*.py` | 0 | All checks passed |
| 9 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` tự xác nhận `capture_enabled=False` trước khi kết thúc |

Tất cả 5 evidence script chạy TUẦN TỰ trên CÙNG một DB, xác nhận không rò rỉ state giữa các lần
chạy — kể cả bảng `m4_stage0p_capture_approval_revocations` mới và state machine 6 giá trị.

## 5. Known limitations (không đổi so với Correction #2 §5, cộng thêm)

10. **Allowlist exclusion-reason DB-side hiện chỉ có 1 giá trị (`normalization_version_mismatch`)**
    — đúng nhu cầu hiện tại của prediction writer (chỉ có 1 lý do loại tự động), nhưng nếu tương
    lai cần thêm lý do loại khác (vd content quá ngắn, detector timeout riêng lẻ), phải thêm cả
    entry allowlist DB-side LẪN cơ chế DB-tự-xác-minh điều kiện tương ứng — không chỉ thêm string
    vào Python.
11. **Ngưỡng `>50%` của gate `INSUFFICIENT_DATA` (T3-03) là giá trị chọn hợp lý cho dev/test,
    chưa qua PO/CA duyệt như một tham số vận hành chính thức** — tương tự tinh thần khuyến cáo ở
    `overlap_match()` (F-M4-0P-05A, ngưỡng IoU phải do PO/CA duyệt): nên rà soát lại ngưỡng này
    trước activation dựa trên đặc điểm dữ liệu production thật (vd tỉ lệ tin nhắn không đủ điều
    kiện chấm điểm là bao nhiêu trong thực tế).
12. **`m4_stage0p_capture_approval_revocations` chưa có quy trình vận hành thật** (T3-05) — tương
    tự limitation #8 đã ghi ở Correction #2 cho bảng approval gốc: kỹ thuật đã sẵn sàng
    (`revoke_capture_approval()`), nhưng "ai được thu hồi, dựa trên văn bản quyết định nào" là
    quyết định vận hành thuộc giai đoạn production-activation.

## 6. Đề nghị

CA review Correction #3 đối chiếu 6 finding `T3-01..T3-06`. Không xin quyền production-data-
access/activation — gate đó vẫn tách riêng theo Design Acceptance §6, xin sau khi Correction #3
được nghiệm thu.
