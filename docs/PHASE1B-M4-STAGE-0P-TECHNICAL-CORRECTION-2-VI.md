---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-2-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #2
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-29 (giờ chính xác xem §5)
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-2-VI.md (CA, CHANGES_REQUIRED, reviewed_head 470d985c00ef8c573c4f099984b76763e968601e)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #2

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-2-VI.md` — sửa đúng 6 finding P1 `T2-01..T2-06`.
CA kết luận vòng Correction #1 (head `470d985`): T1-02/T1-06 CLOSED AT CODE-DESIGN LEVEL,
T1-01/T1-03/T1-04/T1-05 chỉ PARTIALLY CLOSED — vẫn cùng chủ đề gốc "check + write đặc quyền
chưa được DB enforce đủ nguyên tử/đủ bind". Phạm vi KHÔNG đổi: dev/test trên branch M4, dữ liệu
synthetic/test, **KHÔNG** merge/deploy/production-data-access/activation.

## 1. Mapping 6 finding → sửa

| Finding | Sửa | File |
|---|---|---|
| **T2-01** Fenced work unit (khóa 4013003) có thể bị giữ vô thời hạn nếu 1 bước bên trong treo (pending-check/Redis/INSERT không timeout) | Tách `m4_stage0p_fetch_next_message` cũ thành 2 hàm: `m4_stage0p_peek_next_candidate` (KHÔNG lock, KHÔNG kiểm tra control, KHÔNG trả PII — an toàn gọi tự do TRƯỚC khi giữ fence) + `m4_stage0p_fetch_message_content` (fenced, nhận đúng 1 `(conversation_id, message_id)` đã biết — không còn tự quét cursor bên trong). Pending-check chuyển ra NGOÀI fence trước (timeout `PENDING_CHECK_TIMEOUT_SECONDS=1.5s`), rồi recheck NGẮN bên trong fence (`PENDING_RECHECK_TIMEOUT_SECONDS=0.5s`). Toàn bộ đơn vị fenced (`_run_fenced_unit`) bọc trong `asyncio.wait_for(FENCE_UNIT_DEADLINE_SECONDS=5.0)` — asyncpg hủy (cancel) query đang chờ trên server khi task Python bị hủy, đảm bảo transaction abort và lock 4013003 được nhả trong thời gian bounded bất kể bước nào bên trong treo. `is_pending_deletion()` thêm timeout tường minh cho cả câu DB (`customers.psid`) lẫn Redis (`socket_timeout`+`asyncio.wait_for`) | `migrations/039_m4_stage0p.sql` §5a/§5b; `app/services/pii/stage0p_sampling.py`; `app/services/pii/stage0p_eligibility.py` |
| **T2-02** Prediction path SELECT+decrypt toàn bộ corpus TRƯỚC khi biết batch sealed — DB chỉ từ chối ở bước ghi cuối | Hàm mới `m4_stage0p_fetch_sealed_message(batch_id, after_sample_id)` — kiểm `labels_sealed_at IS NOT NULL` TRƯỚC KHI trả bất kỳ `encrypted_message` nào (batch chưa sealed → RAISE, 0 row rời hàm), phân trang 1-sample/lần, audit từng lần đọc. `REVOKE` toàn bộ `SELECT` trực tiếp trên cột nội dung của `alpha3s_m4_prediction_writer` — role chỉ còn `EXECUTE` 2 hàm | `migrations/039_m4_stage0p.sql` §5f; `app/services/pii/stage0p_prediction.py` |
| **T2-03** `write_predictions` nhận JSONB tùy ý không validate schema/bounds/coverage/immutability | Viết lại hoàn toàn `m4_stage0p_write_predictions` — validate: JSON array, exact allowed keys (`predicted_slots`,`sample_id` / `confidence`,`end`,`reason`,`slot_type`,`start`), `slot_type` ∈ enum taxonomy, `confidence` ∈ (`high`,`medium`,`low`), bounds `0≤start<end≤canonical_text_len`, non-overlap trong 1 sample, `sample_id` thuộc đúng batch, không trùng lặp. Tham số mới `p_exclusions` (sample_id+reason có ý nghĩa rõ ràng, vd `normalization_version_mismatch`) — bắt buộc `predictions ∪ exclusions` PHỦ ĐÚNG toàn bộ sample trong batch (không thiếu/thừa/lạ). Cột mới `predictions_written_at` — hàm từ chối nếu đã set (bất biến 1-lần-ghi, rerun phải tạo batch mới) | `migrations/039_m4_stage0p.sql` §4/§5g; `app/services/pii/stage0p_prediction.py` |
| **T2-04** Hash do Python tính rồi "truyền vào" cho DB, DB chỉ kiểm "không rỗng", không xác minh khớp dữ liệu thật | Bật `pgcrypto`. `m4_stage0p_seal_labels` TỰ TÍNH `labels_sealed_hash` bằng `digest()` trên chính `(sample_id, labeled_slots)` trong bảng — không còn nhận tham số hash từ Python. `m4_stage0p_write_predictions` nhận `p_expected_labels_sealed_hash`, đối chiếu với giá trị đã lưu, từ chối nếu không khớp (chống stale/forged) — rồi TỰ TÍNH `result_hash` (bind `labels_sealed_hash`+`detector_version`+predictions/exclusions thật đã ghi). `m4_stage0p_complete_evaluation` nhận `p_expected_result_hash`, đối chiếu, rồi TỰ TÍNH `evaluation_report_hash` (bind matching/aggregation version + `result_hash` + metrics). Xóa hẳn `corpus_manifest_hash`/`result_hash`/`report_hash`/`label_set_hash` (hàm Python thuần REV2 — không còn load-bearing, giữ lại sẽ là dead code gây hiểu nhầm "đây là nguồn hash thật") | `migrations/039_m4_stage0p.sql` §5e/§5g/§5h; `app/services/pii/stage0p_evaluation.py` |
| **T2-05** `approval_ref` chỉ cần là chuỗi không rỗng — không xác thực với bản ghi quyết định nào | Bảng mới `m4_stage0p_capture_approvals` (`approval_ref` PK, `purpose_code`, `requested_enabled`, `status` ∈ (`approved`,`revoked`), `valid_from`/`valid_until`, `recorded_by`/`recorded_at`). Role mới `alpha3s_m4_approval_recorder` (chỉ `INSERT`+`SELECT` bảng này) — TÁCH BIỆT `alpha3s_m4_control_plane` (chỉ `EXECUTE set_capture`, không đọc/ghi bảng approvals trực tiếp) để không role nào tự duyệt cho chính mình. `m4_stage0p_set_capture(ON)` bắt buộc tồn tại 1 row `approved`, đúng `purpose_code`, `requested_enabled=true`, còn hiệu lực (`now() BETWEEN valid_from AND valid_until`) — else RAISE. `OFF` KHÔNG kiểm approval (chỉ cần actor active) — đúng yêu cầu CA "OFF không được bị chặn vì approval hết hạn" | `migrations/039_m4_stage0p.sql` §2b/§5d; `app/services/pii/stage0p_control.py:record_capture_approval` |
| **T2-06** `captured_count` tăng cùng lúc FETCH (trước cả pending-check) — row bị skip vẫn tính vào cap, số liệu không phản ánh sample thật sự lưu | Hàm mới `m4_stage0p_record_sample` — gộp `INSERT` sample + tăng `captured_count` ATOMIC trong 1 lệnh gọi, CHỈ được gọi khi sample THẬT SỰ được lưu (sau khi đã qua pending-recheck). `m4_stage0p_fetch_message_content` KHÔNG còn đụng `captured_count`. `alpha3s_m4_sample_collector` mất `INSERT` trực tiếp trên bảng sample — chỉ còn `EXECUTE record_sample`, không còn đường nào khác để tăng counter mà không kèm ghi sample thật | `migrations/039_m4_stage0p.sql` §5c; `app/services/pii/stage0p_sampling.py` |

## 2. Nguyên tắc sửa chung (không đổi so với Correction #1, áp dụng sâu hơn)

Toàn bộ 6 finding tiếp tục quy về: **kiểm tra và ghi đặc quyền phải được DB enforce nguyên tử,
không tin dữ liệu/khẳng định do Python truyền vào**. REV3 mở rộng nguyên tắc này sang 2 chiều
mới mà Correction #1 chưa chạm tới: (a) **thời lượng giữ khóa phải có trần đo được**, không chỉ
"nguyên tử" (T2-01); (b) **DB phải tự tính/tự xác minh hash, không tin giá trị Python khẳng
định** (T2-04) — cùng tinh thần "không tin caller" nhưng áp cho dữ liệu định danh (hash), không
chỉ cho hành động (write).

## 3. Bug tự phát hiện trong lúc triển khai (khai báo minh bạch)

1. **`AmbiguousColumnError` tương tự REV2 KHÔNG lặp lại** — lần này rút kinh nghiệm, alias
   bảng tường minh (`m4_selection_batches AS b`) ngay từ đầu cho `m4_stage0p_record_sample`
   (cùng pattern lỗi cũ ở `m4_stage0p_fetch_next_message`).
2. **`compute_batch_metrics()` giả định sai kiểu dữ liệu asyncpg trả về** — asyncpg trả cột
   `jsonb` là TEXT thô (không có codec đăng ký trong dự án này), không phải Python object đã
   parse sẵn. Code ban đầu gọi thẳng `match_by_slot_type(r["labeled_slots"], ...)` coi đó là
   list — vỡ với `TypeError: string indices must be integers`. Phát hiện ngay lần chạy evidence
   đầu tiên (`m4_stage0p_evaluation_test.py` §[10]), sửa bằng `json.loads()` tường minh trước khi
   xử lý. Đây là bug thật (không phải giả định lý thuyết) — các đoạn code cũ (REV2's
   `corpus_manifest_hash` v.v.) có cùng lỗi tiềm ẩn nhưng chưa từng lộ ra vì chưa có chỗ nào thật
   sự lặp/index vào nội dung `labeled_slots`/`predicted_slots` sau khi đọc — chỉ serialize lại
   nguyên trạng.
3. **Thứ tự xóa FK giữa `staff_users` và `m4_stage0p_capture_approvals`** trong dọn dẹp evidence
   script — `m4_stage0p_capture_approvals.recorded_by` tham chiếu `staff_users(id)`, xóa
   `staff_users` trước khi xóa approval record gây `ForeignKeyViolationError`. Sửa thứ tự dọn dẹp
   trong `m4_stage0p_sampling_test.py`.

## 4. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`, DB drop-sạch + migrate lại từ đầu ngay trước loạt chạy cuối)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `migrate.py up` (DB drop sạch object M4) | 0 | `OK 039_m4_stage0p`, postcondition PASS ngay lần đầu |
| 2 | `m4_stage0p_migration_test.py` | 0 | RESULT: PASS (fresh+idempotent+existing-apply+rollback) |
| 3 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS — ma trận bảng 4 bảng (bao gồm `m4_stage0p_capture_approvals` mới), ma trận EXECUTE 8 hàm×11 role, hardening 8 hàm+trigger, T2-05 approval khiếm khuyết (không tồn tại/hết hạn/thu hồi) bị từ chối cho ON còn OFF luôn thành công, T2-06 counter tách biệt fetch/insert, T2-02 fetch_sealed_message 0-raw-fetch khi chưa sealed, T2-03 10 kịch bản adversarial JSON, T2-04 hash forged/stale bị từ chối cho cả write_predictions và complete_evaluation, T2-03 bất biến rerun bị từ chối |
| 4 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — bao gồm 3 kịch bản MỚI T2-01: Redis không routable (fail-closed bounded ~1s), DB write hang (row `FOR UPDATE` từ session khác → fenced unit timeout ~2s do inner statement timeout, transaction rollback 0 sample, `set_capture(OFF)` thành công ngay sau ~0.01s), process death (connection giữ lock 4013003 bị đóng đột ngột → lock tự nhả, `set_capture(OFF)` thành công ~0.09s) |
| 5 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J, cập nhật approval record cho kịch bản [G]) |
| 6 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS — `seal_labels` DB-computed hash, `run_prediction_writer` qua `fetch_sealed_message` (có audit), exclusion có lý do rõ ràng, bất biến rerun bị từ chối qua Python wrapper, `compute_batch_metrics`+`complete_evaluation` bind đúng `result_hash`, `purge_expired` tôn trọng `evaluation_completed_at` |
| 7 | `pytest -q` (full) | 0 | **241 passed** (251 Correction #1 − 10 test hash Python thuần đã xóa vì hàm superseded) |
| 8 | `ruff check app/services/pii/ scripts/m4_stage0p_*.py tests/test_m4_*.py` | 0 | All checks passed |
| 9 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` tự xác nhận `capture_enabled=False` trước khi kết thúc |

Tất cả 5 evidence script chạy TUẦN TỰ trên CÙNG một DB, xác nhận không rò rỉ state giữa các lần
chạy — kể cả state `capture_enabled` và bảng `m4_stage0p_capture_approvals` mới.

## 5. Known limitations (không đổi so với Correction #1 §5, cộng thêm)

8. **Bảng `m4_stage0p_capture_approvals` chưa có quy trình vận hành thật để PO/CA ghi approval
   record** (T2-05) — role `alpha3s_m4_approval_recorder` và hàm `record_capture_approval()` đã
   sẵn sàng về mặt kỹ thuật, nhưng AI/quy trình cụ thể "ai được cấp credential role này, ghi
   record khi nào, dựa trên văn bản quyết định nào" là quyết định vận hành thuộc giai đoạn
   production-activation (ngoài phạm vi Stage 0P dev/test).
9. **`FENCE_UNIT_DEADLINE_SECONDS=5.0`/`PENDING_CHECK_TIMEOUT_SECONDS=1.5`/
   `PENDING_RECHECK_TIMEOUT_SECONDS=0.5` là hằng số chọn hợp lý cho dev/test** — chưa có tuning
   dựa trên latency thật của production DB/Redis; nên rà soát lại trước activation nếu môi
   trường production có latency khác biệt đáng kể.

## 6. Đề nghị

CA review Correction #2 đối chiếu 6 finding `T2-01..T2-06`. Không xin quyền production-data-
access/activation — gate đó vẫn tách riêng theo Design Acceptance §6, xin sau khi Correction #2
được nghiệm thu.
