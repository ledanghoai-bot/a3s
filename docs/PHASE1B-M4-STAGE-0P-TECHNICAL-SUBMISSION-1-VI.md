---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-SUBMISSION-1-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Implementation Submission #1
document_type: technical_implementation_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-29 17:00+07:00
answers: PHASE1B-M4-STAGE-0P-DESIGN-ACCEPTANCE-VI.md (CA, DESIGN_ACCEPTED, accepted_head d2a63c5)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Implementation Submission #1

Đáp lại `PHASE1B-M4-STAGE-0P-DESIGN-ACCEPTANCE-VI.md` §4/§5 — triển khai đúng phạm vi được cấp:
**migration, role, function, collector, reviewer API, evaluator, purge trên branch M4, dữ liệu
synthetic/test**. **KHÔNG** đọc/copy production data, **KHÔNG** cấp role/credential production,
**KHÔNG** đặt control row ON ngoài rehearsal, **KHÔNG** bật `m4_pii_shadow`/capture trên
production, **KHÔNG** merge/deploy/vendor call/canary.

## 1. Thành phần đã giao

| Thành phần | File | Vai trò |
|---|---|---|
| Migration | `migrations/039_m4_stage0p.sql` | 3 bảng (`m4_shadow_review_samples`, `m4_selection_batches`, `m4_stage0p_control`) + 7 role least-privilege + hàm `SECURITY DEFINER` hardened + postcondition fail-closed |
| Crypto sample zone | `app/services/pii/crypto.py` (mở rộng) | `encrypt_sample_value`/`decrypt_sample_value`, domain tag `a3s-m4-shadow-sample-aad-v1`, khóa riêng `m4_sample_key_b64` |
| Control-plane (F-01B) | `app/services/pii/stage0p_control.py` | Đọc tươi trước mỗi đơn vị ghi (asyncpg `timeout=2s`, không dùng `SET LOCAL` — bug tự phát hiện), ghi qua role riêng + audit bắt buộc |
| Pending-deletion (F-02B) | `app/services/pii/stage0p_eligibility.py` | `is_pending_deletion(customer_id)` — PSID không rời scope hàm |
| Sampling 2 pha (F-03B) | `app/services/pii/stage0p_sampling.py` | Eligibility (cửa sổ đúng cho cả conversation+order), seed cố định, khóa batch, collector 1-checkpoint/row, `purge_expired` |
| Evaluation (F-05A) | `app/services/pii/stage0p_evaluation.py` | exact-span (gate), overlap/IoU (phụ), offset-bounds, non-overlap, aggregate micro, evaluation hash |
| Prediction writer | `app/services/pii/stage0p_prediction.py` | Chấm điểm sau-labeling, từ chối cấu trúc nếu còn row unlabeled |
| DSR propagation #17 | `app/services/data_deletion.py` (sửa) | DELETE vô điều kiện theo `customer_ref`, cùng transaction, guard `to_regclass` (production chưa có migration 039) |
| Registry/runbook | `docs/{DSR-RUNBOOK,PROCESSING-PURPOSE-REGISTRY,RETENTION-SCHEDULE,AI-USE-CASE-REGISTER}-VI.md` | Mục #17, `P12_PII_DETECTOR_EVAL`, `RET-11b`, `UC-004` |
| Unit test | `tests/test_m4_stage0p_crypto.py`, `tests/test_m4_stage0p_evaluation.py` | 28 test thuần logic |
| Evidence script (DB) | `scripts/m4_stage0p_{migration,permissions,kill,sampling,evaluation}_test.py` | 5 script, tổng ~85 assertion trên DB thật |

## 2. Mapping 14 tiêu chí CA (§5 Design Acceptance) → evidence

| # | Tiêu chí CA | Evidence |
|---|---|---|
| 1 | Migration fresh/existing/idempotent + rollback | `m4_stage0p_migration_test.py` §1-4: fresh apply 001→039 EXIT=0; idempotent re-run; existing-apply (DB có sẵn 001-038+dữ liệu → chỉ 039 áp, dữ liệu cũ nguyên vẹn); rollback (gia lập postcondition FAIL → xác nhận KHÔNG bảng nào của 039 tồn tại sau đó — atomic thật, không chỉ "báo lỗi") |
| 2 | Negative-permission matrix mọi role + PUBLIC + runtime + vendor | `m4_stage0p_permissions_test.py` — 34 dòng ma trận: 7 role M4 + `alpha3s_app` + `alpha3s_vendor_path` + `public`, đủ SELECT/INSERT/UPDATE/DELETE per-column trên 3 bảng |
| 3 | SECURITY DEFINER hardening đủ 6 mục | `m4_stage0p_permissions_test.py` phần riêng: `prosecdef=true`; owner = `alpha3s_m4_definer` (role MỚI non-superuser, KHÔNG dùng migration-owner — sửa từ thiết kế v4.0.0 sau khi phát hiện `alpha3s` là superuser trong môi trường); `search_path` khóa; `REVOKE EXECUTE FROM PUBLIC`; validate `status`/`window`/`purpose_code` trước khi trả row (2 test riêng: batch không tồn tại, batch `status='closed'`); audit fail-closed (revoke `INSERT` trên `audit_log` của definer → hàm từ chối trả dữ liệu) |
| 4 | Control-plane role riêng, không dùng `updated_by` tự khai | Migration 039 §6f: role `alpha3s_m4_control_plane` tách biệt, chỉ role này UPDATE được `capture_enabled`; tham quyền thật = `audit_log` (`actor_staff_id` FK `staff_users` + `reason=approval_ref` bắt buộc non-empty, `stage0p_control.py:set_capture_enabled` raise nếu thiếu); cột `updated_by_note` chỉ tham khảo (COMMENT ghi rõ) |
| 5 | Kill rehearsal DB commit boundary, không app timestamp | `m4_stage0p_kill_test.py` — dùng **transaction ID (`xmin`/`txid_current()`)**, không `now()`/app clock; kill thật giữa lúc collector chạy (2 asyncio task interleave qua await point thật, không sleep cố định trước khi bắt đầu); xác nhận `aborted_control_off=True` + `0<inserted<tổng`; toàn bộ row insert có `xmin` ràng buộc chặt với `off_txid` (tối đa 1 row "đua" — cửa sổ đua có thật trong hệ thống đồng thời thật, đã chứng minh nó luôn là row CUỐI CÙNG, không có row nào sau nó) |
| 6 | Fail-to-read/timeout=OFF, timeout đo được cho cả control read và write unit | `m4_stage0p_kill_test.py` [4]: đóng connection giữa chừng → `read_capture_enabled` trả `False`; `stage0p_control.py` dùng asyncpg `timeout=2.0` (CONTROL_READ_TIMEOUT_MS=2000) — cận trên tường minh, không suy đoán |
| 7 | Cap test: multi-byte UTF-8, ciphertext thật, total batch cap, concurrent collector, DB constraint | `m4_stage0p_sampling_test.py` [A][B][C][D]: text đa-byte vượt MAX_CHARS/MAX_BYTES cắt đúng UTF-8-safe cả 2 bước; DB `CHECK octet_length<=8045` từ chối ciphertext cố tình oversized (bypass Python); cap 260 deterministic (2 lần chọn cùng input → cùng kết quả); 2 collector cùng xin advisory lock → đúng 1 thành công |
| 8 | Eligibility loại conversation ngoài cửa sổ + không thuộc order-eligible definition (không suy từ customer_id) | `m4_stage0p_sampling_test.py` [E][F]: khách có 2 hội thoại (1 cũ ngoài cửa sổ + 1 mới trong cửa sổ, cả 2 cùng customer_id có 1 order trong cửa sổ) — CHỈ hội thoại mới được chọn, hội thoại cũ bị loại tường minh dù cùng khách |
| 9 | Pending-DSR race, DSR retry/idempotency, source-conversation missing, cross-customer deletion | `m4_stage0p_sampling_test.py` [G][H][I][J]: pending xuất hiện GIỮA lúc collector chạy (asyncio interleave thật) → phần còn lại bị bỏ qua; `process_deletion()` gọi 2 lần → lần 2 no-op sạch; xóa `conversations` TRƯỚC khi gọi DSR (không qua chính DSR) → sample vẫn xóa đúng (chứng minh không orphan/không join); xóa khách A không đụng khách B |
| 10 | Crypto AAD/domain/key separation, tamper, cross-context | `tests/test_m4_stage0p_crypto.py` (10 unit test) + `m4_stage0p_evaluation_test.py` [1][2][3] trên row DB thật: sample blob không giải mã được bằng hàm slot store; tamper 1 byte → `SlotBindingError`; đổi `customer_ref` của context → fail |
| 11 | Label-before-prediction; reviewer không đọc prediction | `m4_stage0p_evaluation_test.py` [7] (batch mới hoàn toàn unlabeled → `PredictionNotAllowedError`); migration 039 postcondition `reviewer_can_see_prediction` (role reviewer-api không có SELECT `predicted_slots`); ràng buộc CẤU TRÚC ở `stage0p_prediction.py` (cột rỗng cho tới khi cả batch labeled) |
| 12 | Offset bounds/non-overlap/normalization-version; exact-span precision/recall; 3 hash | `tests/test_m4_stage0p_evaluation.py` (18 unit test, gồm đúng case CA nêu: detector bắt trùng 1 vị trí 2 lần → exact-span báo FN+FP đúng, không TP giả như count-only) + `m4_stage0p_evaluation_test.py` [4][5][6][8]: `validate_spans` trên output detector THẬT; normalization_version cũ bị loại khỏi gate; `evaluation_hash` deterministic + nhạy tham số |
| 13 | Retention `eval completed OR 45 days`, purge fail-closed, counts-only logs | `stage0p_sampling.py:purge_expired()` — `DELETE WHERE expires_at<=now() OR (label_status='labeled' AND predicted_slots IS NOT NULL)`, log `[m4-stage0p-sampling] m4_purge_done count=N` (không sample_id/customer_ref); RET-11b ghi rõ nguyên tắc trong Retention Schedule |
| 14 | Full regression, CI success, xác nhận mọi flag/control production vẫn OFF | pytest **242 passed** (214 baseline + 28 unit mới); ruff clean; `Settings(_env_file=None)` xác nhận `m4_pii_shadow`/`m4_trusted_pii_path`/`m4_stage0p_capture_enabled` đều `False`; DB control row `capture_enabled=False` sau mọi lần rehearsal; CI GitHub Actions — xem §4 |

## 3. Phát hiện/sửa trong lúc triển khai (khai báo minh bạch)

1. **Owner hàm `SECURITY DEFINER`:** thiết kế v4.0.0 giả định dùng "migration-owner" làm owner
   với lý luận "non-superuser" — kiểm tra thực tế thấy `alpha3s` (user kết nối/migration-owner
   trong image Docker dev) **LÀ superuser** (`POSTGRES_USER` mặc định của Postgres image). Đã
   sửa đúng: tạo role **RIÊNG** `alpha3s_m4_definer` (NOLOGIN, non-superuser tường minh), owner
   hàm trỏ vào role này, cấp quyền nội bộ tối thiểu (SELECT `messages`/`m4_selection_batches`,
   INSERT/UPDATE/SELECT(id) `audit_log`). Đây là thiết kế ĐÚNG bất kể migration-owner có
   superuser hay không trong bất kỳ môi trường nào — không phải workaround riêng cho dev.
2. **`SET LOCAL statement_timeout`không có tác dụng như kỳ vọng:** thiết kế ban đầu của
   `read_capture_enabled` dùng `SET LOCAL` trước câu `SELECT` — nhưng 2 lệnh gọi rời (không bọc
   trong `conn.transaction()`) chạy thành 2 implicit-transaction riêng trên asyncpg, nên
   `SET LOCAL` không mang tác dụng sang câu SELECT kế tiếp. Sửa dùng tham số `timeout=` gốc của
   asyncpg (client-side deadline áp trực tiếp cho câu SELECT) — đơn giản hơn và đúng.
3. **3 chỗ thiếu `GRANT SELECT` cho cột dùng trong `WHERE`/`RETURNING`:** Postgres yêu cầu
   SELECT trên cột xuất hiện ở `WHERE`/`RETURNING`, không chỉ quyền hành động chính (INSERT/
   UPDATE/DELETE). Phát hiện qua smoke test thực tế (không phải suy luận): thiếu `SELECT(id)`
   trên `audit_log` cho hàm `RETURNING id`; thiếu `SELECT(selection_batch)` cho reviewer-api;
   thiếu `SELECT(predicted_slots)` cho prediction-writer (dùng trong `WHERE predicted_slots IS
   NULL`). Cả 3 đã sửa trong migration 039 (không phải patch rời).
4. **`customers` không có cột `customer_id`** (chỉ có `id`) — sai sót nhỏ trong 1 câu GRANT lúc
   viết migration, phát hiện ngay ở lần chạy migration đầu tiên, sửa trước khi có evidence nào
   dựa trên nó.

## 4. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` fresh + `alpha3s-m4-redis`, tất cả trên network `m4net`)

| # | Lệnh | Giờ (29/7) | Exit | Kết quả |
|---|---|---|---|---|
| 1 | `migrate.py up` (DB fresh) | 16:47 | 0 | 39 migrations, validations M0+M3 PASS |
| 2 | `m4_stage0p_migration_test.py` | 16:48 | 0 | RESULT: PASS (fresh+idempotent+existing-apply+rollback) |
| 3 | `m4_stage0p_permissions_test.py` | 16:49 | 0 | RESULT: PASS (40 assertion) |
| 4 | `m4_stage0p_kill_test.py` | 16:50 | 0 | RESULT: PASS (9 assertion) |
| 5 | `m4_stage0p_sampling_test.py` | 16:51 | 0 | RESULT: PASS (~30 assertion) |
| 6 | `m4_stage0p_evaluation_test.py` | 16:52 | 0 | RESULT: PASS (12 assertion) |
| 7 | `pytest -q` (full) | 16:55 | 0 | **242 passed** (214 baseline + 28 mới) |
| 8 | `ruff check app/services/pii scripts/m4_stage0p_*.py tests app/services/data_deletion.py app/config.py` | 16:58 | 0 | All checks passed |
| 9 | Xác nhận flag/control OFF | 17:00 | — | `Settings(_env_file=None)`: `m4_pii_shadow=False`, `m4_trusted_pii_path=False`, `m4_stage0p_capture_enabled=False`; DB `m4_stage0p_control.capture_enabled=False` |

Tất cả 5 evidence script được chạy **liên tiếp trên CÙNG một DB** (không reset giữa các script,
trừ script tự dọn dữ liệu của chính nó) để xác nhận không có state rò rỉ giữa các lần chạy.

## 5. Known limitations (khai báo, không giấu)

1. **`existing-apply` cho migration 039 chỉ test với DB đã có 001-038** — chưa test kịch bản
   "039 áp trên DB production thật có `pii_slots` đang dùng" vì Stage 0P chưa có authority chạm
   production; đây là hành vi đã biết trước (CA Design Acceptance §4 giới hạn dev/test scope).
2. **Rollback evidence's role-persistence note:** `alpha3s_m4_definer` role còn tồn tại sau kịch
   bản rollback trong test — do role đó đã được tạo THÀNH CÔNG ở lần apply TRƯỚC (không phải
   trong transaction lỗi đang test); bản thân TABLE/FUNCTION rollback đúng (đã verify) — ghi chú
   để không gây hiểu nhầm đây là bằng chứng "role tạo có transactional", chỉ là quan sát phụ.
3. **Purge job (`purge_expired`) chưa có evidence script riêng schedule/cron** — hàm đã viết và
   đúng theo RET-11b, nhưng chưa test tích hợp với 1 job scheduler thật (ngoài phạm vi Stage 0P
   — thuộc vận hành production sau này).
4. **Collector job chưa đóng gói thành CLI/entrypoint chạy độc lập** — các hàm (`select_eligible_
   conversations`, `select_sample`, `lock_batch`, `run_collector`) đã đủ để 1 script điều phối
   gọi, nhưng chưa có `scripts/m4_stage0p_collector_run.py` thực thi production-ready (không cần
   cho Technical Submission — không có authority chạy trên traffic thật).
5. **Race window trong kill rehearsal** (tối đa 1 row) là thuộc tính hệ thống đồng thời thật,
   không phải lỗi — đã giải trình đầy đủ ở §2 mục 5 và trong chính script.

## 6. Đề nghị

CA review implementation này đối chiếu 14 tiêu chí §5 Design Acceptance. Chưa xin quyền production-
data access/activation — đó là gate riêng theo đúng §6 Design Acceptance, sẽ xin sau khi
implementation này được nghiệm thu.
