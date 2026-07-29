---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-1-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #1
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-29 (giờ chính xác xem §5)
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-1-VI.md (CA, CHANGES_REQUIRED, reviewed_head e10af661247cd1f3e9af1da83bc1eb50f32097fe)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #1

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-1-VI.md` — sửa đúng 6 finding P1 `T1-01..T1-06`
tại head mới, mapping từng finding sang code/migration/evidence. Phạm vi KHÔNG đổi so với
Technical Submission #1: dev/test trên branch M4, dữ liệu synthetic/test, **KHÔNG** merge/deploy/
production-data-access/activation.

## 1. Nguyên tắc sửa chung

Cả 6 finding của CA đều quy về một chủ đề: **kiểm tra và thao tác đặc quyền không được DB
enforce nguyên tử — sequencing ở tầng Python có thể bị bypass/race**. Cách sửa nhất quán cho cả
6 finding: chuyển toàn bộ "check + write" vào **1 hàm `SECURITY DEFINER` DUY NHẤT** chạy trong
đúng 1 transaction, và **thu hồi mọi quyền UPDATE trực tiếp** trên các bảng liên quan — role chỉ
còn `EXECUTE` hàm, không còn đường nào khác để ghi.

Cơ chế fencing mới cho kill switch: **`pg_advisory_xact_lock(4013003)`** — một lock key MỚI
(khác `4013001` của `scripts/migrate.py` và `4013002` của collector single-writer lock cũ),
dùng CHUNG giữa `m4_stage0p_fetch_next_message` (đọc nội dung) và `m4_stage0p_set_capture` (đổi
kill switch). Vì đây là **transaction-scoped** advisory lock (tự nhả khi COMMIT/ROLLBACK), và
Postgres cấp phát transaction ID (`xid`) tăng dần toàn cục tại lần ghi ĐẦU TIÊN của mỗi
transaction, bên nào giữ được lock trước THÌ BẮT BUỘC phải COMMIT/ROLLBACK (nhả lock) trước khi
bên kia được tiếp tục — nên **không có ngoại lệ nào** cho phép 1 sample commit SAU KHI 1 lệnh
`set_capture(OFF)` đã commit. Đây là khác biệt cốt lõi so với thiết kế cũ (đọc control rồi ghi
riêng rẽ, không có cơ chế khóa nào ràng buộc 2 bên).

## 2. Mapping 6 finding → sửa

| Finding | Sửa | File |
|---|---|---|
| **T1-01** Kill switch không chặn raw read, không fence write | Hàm mới `m4_stage0p_fetch_next_message(batch_id, after_conversation_id, after_message_id)` — phân trang **1 message/lần gọi**, `PERFORM pg_advisory_xact_lock(4013003)` là câu lệnh ĐẦU TIÊN, đọc `capture_enabled` SAU KHI đã giữ lock (luôn là giá trị mới nhất đã commit), trả `status='control_off'` (content=NULL) nếu OFF — KHÔNG đọc `messages` nào. `run_collector()` viết lại: **1 message = 1 transaction** (fetch → pending-check → encrypt → insert, tất cả trong CÙNG transaction Python mở qua `collector_conn.transaction()`), giữ lock xuyên suốt đơn vị | `migrations/039_m4_stage0p.sql` §5a; `app/services/pii/stage0p_sampling.py:run_collector` |
| **T1-02** Cap chưa enforce tại privileged fetch boundary; CHECK constraint sai byte | `m4_stage0p_fetch_next_message` áp `left(content, 2000)` (MAX_CHARS) NGAY TRONG SQL trước khi content rời DB, trả thêm `char_truncated`; cột mới `m4_selection_batches.captured_count` (đếm BỀN VỮNG tại DB, tăng ATOMIC cùng transaction với INSERT, chặn trần `selected_count*20`) — không còn chỉ dựa vào counter Python/advisory lock. `_SAMPLE_VERSION=b"v1"` là 2 byte (không phải 1) → overhead thật = 2+12+16=30 byte → sửa `CHECK (octet_length(encrypted_message) <= 8030)` (không phải 8045). Khóa bằng unit test exact-boundary | `migrations/039_m4_stage0p.sql` §3/§4/§5a; `tests/test_m4_stage0p_crypto.py::test_exact_ciphertext_boundary_8030_bytes` |
| **T1-03** Label-before-prediction là TOCTOU Python; prediction-writer có UPDATE trực tiếp | Cột mới `m4_selection_batches.labels_sealed_at/by/hash`. Hàm mới `m4_stage0p_seal_labels(batch_id, actor_staff_id, labels_hash)` — kiểm tra ATOMIC (trong transaction của chính hàm) toàn bộ sample `label_status='labeled'` trước khi seal. Trigger `m4_stage0p_label_immutable_after_seal` (`BEFORE UPDATE`, **SECURITY DEFINER** — xem bug tự phát hiện ở §3.1) chặn sửa `labeled_slots`/`label_status` sau seal, **bất kể role nào** thực hiện UPDATE. Hàm mới `m4_stage0p_write_predictions(batch_id, predictions_jsonb, detector_version, evaluation_batch)` — kiểm tra `labels_sealed_at IS NOT NULL` trước khi ghi, ghi TẤT CẢ prediction trong 1 lệnh gọi. `REVOKE UPDATE` trên `predicted_slots`/`detector_version`/`evaluation_batch` từ `alpha3s_m4_prediction_writer` — role chỉ còn `EXECUTE` | `migrations/039_m4_stage0p.sql` §4/§5c/§5d; `app/services/pii/stage0p_evaluation.py:seal_labels`; `app/services/pii/stage0p_prediction.py:run_prediction_writer` |
| **T1-04** `evaluation_hash()` chỉ hash 3 chuỗi rời, không bind corpus | Xóa hẳn `evaluation_hash()`. 3 hàm mới: `corpus_manifest_hash()` (bind `batch_id` + `sample_ids` sắp xếp + hash riêng từng sample [`sample_id`+`labeled_slots`+`truncated`] + `normalization_version`), `result_hash()` (bind `corpus_hash` + `detector_version` + prediction theo thứ tự `sample_id`), `report_hash()` (bind `MATCHING_RULE_VERSION`="exact-span-v1" + `AGGREGATION_VERSION`="micro-v1" + `corpus_hash` + `result_hash` + metrics canonical JSON) | `app/services/pii/stage0p_evaluation.py` |
| **T1-05** `set_capture_enabled()` atomicity dựa vào caller convention | Hàm mới `m4_stage0p_set_capture(enabled, actor_staff_id, approval_ref)` — validate `actor_staff_id` tồn tại+`is_active`, `approval_ref` non-empty, UPDATE + INSERT audit_log TRONG CÙNG 1 lệnh gọi hàm (1 transaction thật, không phụ thuộc caller mở transaction đúng cách). `REVOKE UPDATE` trên `m4_stage0p_control` từ `alpha3s_m4_control_plane` — role chỉ còn `EXECUTE`. `stage0p_control.py:set_capture_enabled()` viết lại thành wrapper 1 lệnh gọi | `migrations/039_m4_stage0p.sql` §5b; `app/services/pii/stage0p_control.py` |
| **T1-06** "Eval completed" đồng nhất với "prediction written" | Cột mới `m4_selection_batches.evaluation_completed_at/by/report_hash`. Hàm mới `m4_stage0p_complete_evaluation(batch_id, actor_staff_id, report_hash)` — kiểm tra ATOMIC batch đã sealed + TẤT CẢ sample đã có `predicted_slots` trước khi set. `purge_expired()` viết lại: `DELETE ... USING m4_selection_batches b WHERE s.selection_batch=b.batch_id AND (s.expires_at<=now() OR b.evaluation_completed_at IS NOT NULL)` — JOIN sang trạng thái batch, không còn suy từ `label_status`/`predicted_slots` cấp-row | `migrations/039_m4_stage0p.sql` §3/§5e; `app/services/pii/stage0p_sampling.py:purge_expired` |

## 3. Bug tự phát hiện trong lúc triển khai (khai báo minh bạch)

1. **Trigger bất biến label KHÔNG phải `SECURITY DEFINER` → chặn NHẦM mọi UPDATE, không chỉ
   sau-seal.** Bản đầu tiên của `m4_stage0p_block_label_after_seal()` không khai báo `SECURITY
   DEFINER`, nên trigger chạy bằng quyền của role đang UPDATE (invoker) — role `alpha3s_m4_
   sample_reviewer_api` không có `SELECT` trên `m4_selection_batches` (không cần cho công việc
   bình thường của nó), nên câu `SELECT labels_sealed_at ...` bên trong trigger tự nó fail vì
   thiếu quyền, khiến **TẤT CẢ** `UPDATE labeled_slots` bị chặn (kể cả trước khi seal) — không
   phải chỉ trường hợp sau-seal như thiết kế. Phát hiện qua `m4_stage0p_permissions_test.py`
   (dòng `reviewer_api / samples UPDATE labeled_slots -> ALLOW` báo FAIL thực tế "denied"), không
   phải suy luận lý thuyết. Sửa: thêm `SECURITY DEFINER SET search_path = ...`, owner
   `alpha3s_m4_definer` (đã có `SELECT` trên `m4_selection_batches`), `REVOKE EXECUTE FROM
   PUBLIC`.
2. **`AmbiguousColumnError` trong `m4_stage0p_fetch_next_message`:** `RETURNS TABLE(status
   TEXT, ...)` tự động tạo 1 biến PL/pgSQL tên `status`, trùng tên với cột `m4_selection_batches.
   status` dùng trong câu `UPDATE ... SET status = CASE WHEN status = 'locked' ...`. Phát hiện
   ngay lần chạy evidence đầu tiên (`m4_stage0p_kill_test.py` §[2]) — Postgres từ chối chạy hàm
   với lỗi cột mơ hồ. Sửa: alias bảng (`m4_selection_batches AS b`), qualify toàn bộ tham chiếu
   cột bằng `b.status`.
3. **Kill rehearsal evidence ban đầu vẫn dùng `<=1 row đua`** (thói quen từ script cũ) — sau khi
   viết lại fencing bằng advisory lock, đã SIẾT lại thành khẳng định `== 0` (0 tuyệt đối, không
   còn khoan nhượng) và **evidence thực tế xác nhận đạt được `0 row đua`** — chứng minh cơ chế
   fencing mới mạnh hơn thật sự, không chỉ đổi lời văn.
4. **DB test chung (`alpha3s-m4-db`) đã có migration 039 BẢN CŨ áp từ vòng Technical Submission
   #1** — vì `CREATE TABLE IF NOT EXISTS` không thêm cột mới vào bảng đã tồn tại và
   `schema_migrations` đánh dấu 039 "đã áp", lần chạy evidence đầu tiên của vòng Correction #1
   dùng nhầm state CŨ (thiếu cột `captured_count`/`labels_sealed_*`/..., hàm `fetch_next_message`
   chưa tồn tại, grant cũ còn nguyên). Không phải lỗi migration (idempotency/rollback vẫn đúng
   trên DB SẠCH — xem `m4_stage0p_migration_test.py` PASS), mà là quy trình vận hành DB test dùng
   lại giữa 2 vòng review — đã xử lý bằng drop sạch object M4 + xóa dòng `schema_migrations` +
   `migrate.py up` lại từ đầu trước khi chạy evidence.

## 4. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`, DB đã drop-sạch + migrate lại từ đầu ngay trước loạt chạy cuối)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `migrate.py up` (DB đã drop sạch object M4) | 0 | `OK 039_m4_stage0p`, postcondition PASS |
| 2 | `m4_stage0p_migration_test.py` | 0 | RESULT: PASS (fresh+idempotent+existing-apply+rollback) |
| 3 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS — ma trận bảng (39) + ma trận EXECUTE 5 hàm×10 role (50) + hardening (16) + 8 kịch bản T1-01/T1-03/T1-06 mới, tất cả PASS |
| 4 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — bao gồm `[1] OFF từ đầu → 0 raw fetch (audit_log 0 row `m4_message_fetch`) + 0 insert`, `[3] 0 row đua` (nghiêm ngặt, không còn "tối đa 1"), `[4] captured_count DB khớp đúng` |
| 5 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J, cập nhật signature `run_collector`) |
| 6 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS — `seal_labels`/`write_predictions`/`complete_evaluation`/`corpus_manifest_hash`/`result_hash`/`report_hash` trên DB thật, cộng `purge_expired()` tôn trọng `evaluation_completed_at` (batch đã eval-completed bị purge, batch chưa thì không) |
| 7 | `pytest -q` (full) | 0 | **251 passed** (242 baseline Submission #1 + 9 test mới: 1 crypto boundary + 8 hash) |
| 8 | `ruff check app/services/pii/ scripts/m4_stage0p_*.py tests/test_m4_*.py` | 0 | All checks passed |
| 9 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` đều tự xác nhận `capture_enabled=False` trước khi kết thúc (assertion tường minh, không chỉ dọn dẹp im lặng) |

Tất cả 5 evidence script chạy TUẦN TỰ trên CÙNG một DB (không reset giữa các script, trừ phần tự
dọn dữ liệu riêng), xác nhận không rò rỉ state giữa các lần chạy — kể cả state `capture_enabled`
(mỗi script tự bật/tắt và luôn để lại OFF).

## 5. Known limitations (không đổi so với Submission #1, cộng thêm)

Toàn bộ 5 mục ở `PHASE1B-M4-STAGE-0P-TECHNICAL-SUBMISSION-1-VI.md` §5 vẫn giữ nguyên hiệu lực.
Bổ sung:

6. **`corpus_manifest_hash`/`result_hash`/`report_hash` là hàm Python thuần** (không phải hàm DB)
   — đủ để tái lập/audit lại độc lập (test sensitivity đã xác nhận), nhưng KHÔNG có ràng buộc DB
   nào chặn việc gọi sai thứ tự tham số. Nếu cần siết chặt hơn ở giai đoạn sau (production
   activation), có thể cân nhắc bind `report_hash` vào chính `m4_stage0p_complete_evaluation` như
   1 tham số bắt buộc tính lại phía Python trước khi gọi — hiện tại đã đủ cho scope Stage 0P.
7. **`m4_stage0p_write_predictions` nhận `predictions_jsonb` là mảng JSONB do Python dựng** —
   không kiểm tra lược đồ (schema) từng phần tử `predicted_slots` bên trong DB (dựa vào
   `validate_spans()` Python-side đã test kỹ ở unit test); nếu tương lai có nguồn ghi prediction
   khác ngoài `run_prediction_writer()`, nên bổ sung kiểm tra JSONB schema trong hàm.

## 6. Đề nghị

CA review Correction #1 đối chiếu 6 finding `T1-01..T1-06`. Không xin quyền production-data-
access/activation — gate đó vẫn tách riêng theo Design Acceptance §6, xin sau khi Correction #1
được nghiệm thu.
