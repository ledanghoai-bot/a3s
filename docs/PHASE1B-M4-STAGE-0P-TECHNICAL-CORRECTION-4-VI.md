---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-4-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #4
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-30
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-4-VI.md (CA, CHANGES_REQUIRED, reviewed_head 6c5f0f1d1cba67ce491846c267932ce4021edccb)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #4

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-4-VI.md` — sửa đúng 5 finding P1 `T4-01..T4-05`.
CA xác nhận T3-04/T3-06 **CLOSED AT CODE-DESIGN LEVEL** (không viết lại phần DB-computed metrics
và hash-chain vì exact delta của round này không chạm vào chúng); T3-01/T3-02/T3-05 chuyển từ
CLOSED (Correction #3) xuống **OPEN/PARTIALLY CLOSED** — round này vá đúng phần còn hở mà CA chỉ
ra, không mở rộng scope. Phạm vi KHÔNG đổi: dev/test trên branch M4 (worktree `D:\alpha3s-m4`,
KHÔNG checkout trong `D:\alpha3s`), dữ liệu synthetic/test, **KHÔNG** merge/deploy/production-
data-access/activation.

## 1. Mapping 5 finding → sửa

| Finding | Sửa | File |
|---|---|---|
| **T4-01** Capability "token" Correction #3 là custom GUC (`set_config`/`current_setting`) — CA chỉ rõ đây KHÔNG phải secret/privileged storage, caller có thể tự `set_config` rồi gọi `record_sample` độc lập, bỏ qua hoàn toàn `fetch_message_content` | Bảng mới `m4_stage0p_fetch_capability` (`batch_id,conversation_id,message_id,txid` PK, **KHÔNG GRANT cho bất kỳ role M4 nào** — chỉ owner `alpha3s_m4_definer` INSERT/DELETE được, chạy bên trong hàm). `fetch_message_content` khi thành công INSERT 1 row với `txid_current()` (giá trị Postgres tự cấp theo transaction thật, caller KHÔNG thể tự chọn). `record_sample` DELETE...RETURNING đúng row đó trong CÙNG transaction (`txid = txid_current()`) — DELETE 0 row = RAISE. Vì bảng không có GRANT nào cho caller, đây là bằng chứng DB-owned thật sự, không thể giả mạo bằng cách tự set 1 GUC | `migrations/039_m4_stage0p.sql` §3b/§5b/§5c |
| **T4-02** `p_current_normalization_version` Correction #3 vẫn là tham số caller tự khai — caller có thể truyền giá trị giả để ép mọi row thành "mismatch" | XÓA HẲN tham số này khỏi `write_predictions` — DB tự so sánh với hằng số HARDCODE `v_current_normalization_version` trong thân hàm (cùng quy ước với `MATCHING_RULE_VERSION`/`AGGREGATION_VERSION` đã hardcode trong `complete_evaluation` — phải khớp `app/services/pii/stage0p_sampling.py:NORMALIZATION_VERSION`, bump cả 2 nơi khi thuật toán normalize đổi, qua 1 migration mới) | `migrations/039_m4_stage0p.sql` §5i; `app/services/pii/stage0p_prediction.py` |
| **T4-03** Collector bỏ qua candidate khi fence timeout (`continue`) — candidate đó KHÔNG BAO GIỜ đạt trạng thái terminal nào, nhưng batch vẫn có thể đóng (`close_collection`) khi vòng lặp hết danh sách tự nhiên | Bảng mới `m4_stage0p_capture_progress` (1 row/candidate, state machine 5 giá trị: `pending→committed｜excluded｜retryable_failed→permanent_failed`, `attempt_count`). Hàm mới `m4_stage0p_seed_capture_progress` — vét TOÀN BỘ candidate hợp lệ 1 LẦN (idempotent, `ON CONFLICT DO NOTHING`) TRƯỚC vòng lặp collector. `peek_next_candidate` đổi chữ ký còn `(batch_id)` — đọc từ bảng progress thay vì cursor Python. Hàm mới `m4_stage0p_mark_candidate_outcome` — collector gọi khi KHÔNG đạt `'ok'`: `fence_timeout` (tăng `attempt_count`, ≥3 lần → `permanent_failed`, còn lại → `retryable_failed`, VẪN nằm trong tập `peek` chọn lại) hoặc `pending_deletion` (→ `excluded` ngay, KHÔNG retry — DSR là thẩm quyền cuối). `close_collection` THÊM điều kiện bắt buộc: KHÔNG còn row `pending`/`retryable_failed` nào — đối chiếu 3 chiều (`captured_count` cột đếm == số row sample thật == số row `committed` trong progress) | `migrations/039_m4_stage0p.sql` §3c/§5a/§5a2/§5a3/§5c2; `app/services/pii/stage0p_sampling.py:run_collector` |
| **T4-04** `p_actor_staff_id` là tham số caller tự khai trên MỌI hàm (`set_capture`/`record_approval`/`revoke_approval`/`seal_labels`/`complete_evaluation`) — 1 người giữ chung 1 role DB có thể mạo danh BẤT KỲ staff active nào | Bỏ HẲN tham số actor khỏi cả 5 hàm. Hàm mới `m4_stage0p_pin_actor(staff_id)` — "pin" actor vào SESSION (`set_config(...,false)` — session-scoped, KHÔNG phải LOCAL, sinh tồn qua mọi lần `SET ROLE` tiếp theo trên CÙNG connection cho tới khi đóng). EXECUTE **CHỈ** cấp cho role MỚI `alpha3s_m4_actor_binder` — tách biệt HOÀN TOÀN mọi role nghiệp vụ khác (1 holder của `alpha3s_m4_approval_recorder` KHÔNG có quyền tự pin actor). Hàm nội bộ `m4_stage0p_require_pinned_actor(permission)` — đọc actor đã pin từ session, kiểm active, VÀ kiểm **QUYỀN CỤ THỂ** trong bảng mới `m4_stage0p_staff_permissions` (`m4.stage0p.approve`/`operate`/`review`/`evaluate` — đúng 4 permission CA nêu, tách theo từng hành động). Audit dùng actor đã derive từ session (KHÔNG dùng ID caller tự khai) | `migrations/039_m4_stage0p.sql` §2d/§5d; `app/services/pii/stage0p_control.py:pin_actor`; `app/services/pii/stage0p_evaluation.py` |
| **T4-05** Ngưỡng exclusion `>50%` (Correction #3) là Dev tự chọn, chưa được duyệt, không tách khỏi hardcode | Bảng mới `m4_stage0p_exclusion_gate` (singleton, có thể đổi qua migration/quyết định mới — KHÔNG hardcode trong thân hàm). Seed **ĐÚNG** đề xuất CA Review #4: `max_exclusion_rate=10%`, `min_non_excluded_conversations=200`, `gate_version='ca-review-4-proposed-v1'` (đánh dấu rõ "CA đề xuất, CHƯA có PO decision record chính thức"). `write_predictions` đọc CẢ 2 điều kiện từ bảng này (không hardcode); trả thêm `non_excluded_conversation_count`/`gate_version` trong kết quả — batch report có đủ numerator/denominator/threshold-version | `migrations/039_m4_stage0p.sql` §2e/§3 (`exclusion_gate_version` cột mới)/§5i |

## 2. Nguyên tắc sửa chung (không đổi so với Correction #1-3, áp dụng sâu hơn)

Toàn bộ 5 finding tiếp tục quy về: **kiểm tra và ghi đặc quyền phải được DB enforce nguyên tử,
không tin dữ liệu/khẳng định do Python truyền vào**. REV5 đóng nốt 2 lỗ hổng còn lại trong đúng
nguyên tắc này mà 3 vòng trước chưa chạm tới triệt để: (a) **"đã làm bước A trước" phải là bằng
chứng DB TỰ SỞ HỮU, không phải quy ước lập trình mà caller có thể tự mô phỏng** — GUC REV4
(T4-01) *trông giống* một capability nhưng thực chất là session state bất kỳ ai cũng set được;
bảng riêng không GRANT là ranh giới thật; (b) **"actor là ai" phải đến từ một kênh caller không
tự khai được, không chỉ "actor có active hay không"** — REV4 vẫn hỏi "actor X có active không"
nhưng KHÔNG hỏi "caller có đúng là actor X không", đây là 2 câu hỏi khác nhau và T4-04 đóng đúng
khoảng cách đó bằng session-pinning + role tách biệt.

## 3. Bug tự phát hiện trong lúc triển khai (khai báo minh bạch)

Round này phát hiện **nhiều hơn hẳn** 3 round trước — chủ yếu 1 lớp lỗi lặp lại nhiều lần và vài
lỗi thiết lập test, tất cả đều bắt được bằng evidence thực tế trước khi nộp:

1. **`AmbiguousColumnError` lặp lại 3 lần trong round này** (cùng lớp lỗi đã gặp ở Correction #1
   REV2 — PostgreSQL PL/pgSQL tự sinh 1 biến cho MỖI cột trong `RETURNS TABLE(...)`, va chạm với
   cột bảng CÙNG TÊN nếu tham chiếu không alias):
   - `m4_stage0p_mark_candidate_outcome` — `RETURNS TABLE(new_status, attempt_count)`; câu
     `UPDATE ... SET attempt_count = attempt_count + 1` mơ hồ giữa biến OUT và cột bảng. Sửa:
     alias bảng (`AS cp`, `cp.attempt_count`).
   - `m4_stage0p_peek_next_candidate` VÀ `m4_stage0p_close_collection` — cả 2 đều
     `RETURNS TABLE(status, ...)`; các câu `WHERE status IN (...)`/`FILTER (WHERE status = ...)`
     đọc từ `m4_stage0p_capture_progress` mơ hồ với biến OUT `status`. Sửa alias tương tự.
   - `m4_stage0p_write_predictions` — `RETURNS TABLE(..., gate_version)`; câu
     `SELECT max_exclusion_rate, min_non_excluded_conversations, gate_version INTO v_gate FROM
     m4_stage0p_exclusion_gate` mơ hồ với biến OUT `gate_version`. Sửa alias (`AS eg`).
   Cả 4 lỗi đều bắt được NGAY LẦN CHẠY EVIDENCE ĐẦU TIÊN (không lọt qua `migrate.py up` vì
   postcondition không thực thi các nhánh runtime này) — bài học: **hardening checklist cần thêm
   mục "mọi tham chiếu cột bare-name bên trong hàm có `RETURNS TABLE` PHẢI alias bảng nguồn"**,
   không chỉ né tên cột trùng ở tầng thiết kế schema như trước.
2. **Test setup bug — `_make_large_batch()` (permissions_test.py) hardcode `canonical_text_len=1`
   cho toàn bộ 200 sample "đệm"** trong khi kịch bản "THANH CONG" cần dự đoán 1 span `0-5` trên
   sample đầu — vi phạm CHÍNH bounds-check mà `write_predictions` đang kiểm tra đúng. Không phải
   bug sản phẩm; sửa test tăng `canonical_text_len` lên 20.
3. **`migration_test.py` kịch bản [4] (Rollback) DROP TOÀN BỘ bảng/hàm/role M4** như một phần
   chứng minh atomicity — phát hiện lại (không phải lần đầu, nhưng gây nhầm lẫn debug đáng kể
   round này) rằng chạy script này XONG để lại DB **KHÔNG CÒN schema M4**, cần `migrate.py up`
   lại trước khi chạy bất kỳ evidence script nào khác. Không phải bug — đúng ý đồ thiết kế (chứng
   minh rollback sạch) — nhưng ghi nhận rõ ràng ở đây vì nó từng gây debug sai hướng (tưởng nhầm
   là cột mới `exclusion_gate_version` "biến mất" do lỗi migration, thực ra do chạy
   `migration_test.py` xen giữa mà quên re-apply).
4. **`psql -c "stmt1; stmt2; ...; stmtN"` (nhiều câu lệnh phân tách bằng `;` trong 1 lời gọi) bị
   Postgres simple-query protocol coi là 1 TRANSACTION NGẦM DUY NHẤT** — 1 câu lỗi ở GIỮA chuỗi
   khiến TOÀN BỘ chuỗi (kể cả các câu "đã chạy thành công" hiển thị trước đó trong output) bị
   ROLLBACK, không chỉ câu bị lỗi. Gây nhầm lẫn thao tác dọn dẹp DB test thủ công giữa các vòng
   sửa lỗi trong phiên làm việc này — không ảnh hưởng evidence/code cuối cùng, nhưng ghi nhận vì
   đây là thói quen thao tác DB thủ công cần tránh (tách mỗi câu lệnh DDL/DML rời thành 1 lời gọi
   `psql -c` riêng khi cần đảm bảo cô lập lỗi).
5. **Thứ tự xóa dọn dẹp cuối script vi phạm FK MỚI `m4_stage0p_capture_progress.batch_id →
   m4_selection_batches.batch_id`** ở cả 3 evidence script (`permissions_test.py`,
   `kill_test.py`, `sampling_test.py`) — bảng progress là bảng MỚI round này, code dọn dẹp cũ xóa
   `m4_selection_batches` TRƯỚC `m4_stage0p_capture_progress`. Sửa thứ tự (progress trước batches)
   ở cả 3 file.

## 4. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`, DB drop-sạch + migrate lại từ đầu ngay trước loạt chạy cuối)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `migrate.py up` (DB drop sạch object M4) | 0 | `OK 039_m4_stage0p`, postcondition PASS ngay lần đầu |
| 2 | `m4_stage0p_migration_test.py` | 0 | RESULT: PASS (fresh+idempotent+existing-apply+rollback) — re-apply `migrate.py up` ngay sau (xem §3 mục 3) trước khi chạy evidence tiếp theo |
| 3 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS — ma trận 9 bảng (thêm `m4_stage0p_fetch_capability`/`capture_progress`/`staff_permissions`/`exclusion_gate`) × 12 role, ma trận EXECUTE 15 hàm×12 role (kể cả `m4_stage0p_require_pinned_actor` — KHÔNG role nào được EXECUTE, chỉ gọi nội bộ), hardening 15 hàm+trigger; T4-01: record_sample gọi độc lập/2-transaction-khác-nhau đều bị từ chối (capability row txid không khớp), caller không INSERT/SELECT/DELETE trực tiếp được bảng capability; T4-02: false-claim mismatch bị từ chối bằng hằng số hardcode (không còn tham số caller); T4-03: mark_candidate_outcome tăng dần retryable→permanent (đúng 3 lần), close_collection từ chối khi còn pending/retryable và thành công khi mọi candidate terminal, đối chiếu 3 chiều phát hiện lệch; T4-04: gọi hàm nghiệp vụ khi CHƯA pin bị từ chối, actor đã pin nhưng thiếu quyền cụ thể bị từ chối, pin sinh tồn qua SET ROLE; T4-05: batch dưới 200 conversation và batch vượt 10% exclusion đều bị từ chối INSUFFICIENT_DATA, batch hợp lệ trả đúng gate_version/non_excluded_conversation_count |
| 4 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — toàn bộ 9 kịch bản REV3 (Redis hang/DB write hang/process death/kill giữa chừng/DB-native boundary/…) không đổi hành vi sau khi thêm pin_actor vào mọi lời gọi set_capture — xác nhận REV5 không phá vỡ timeout/fencing đã đóng ở Correction #2 |
| 5 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J; kịch bản [G] pending-race giờ log `collection_closed=true` xác nhận seed+peek+mark_candidate_outcome hoạt động đúng qua 1 lần chạy collector thật) |
| 6 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS — thêm helper `_add_padding_samples()` (199 sample/batch không PII, bulk insert qua `executemany`) để 2 batch test đạt ngưỡng tối thiểu 200 conversation của T4-05 mà không ảnh hưởng assertion metrics (ground-truth/predicted đều rỗng cho sample đệm); tất cả `seal_labels`/`complete_evaluation` qua `pin_actor()` trước |
| 7 | `pytest -q` (full) | 0 | **241 passed** (không đổi so với Correction #3 — thay đổi REV5 chỉ ở DB boundary/Python wrapper mỏng, không chạm logic thuần) |
| 8 | `ruff check app/services/pii/ scripts/m4_stage0p_*.py tests/test_m4_*.py` | 0 | All checks passed |
| 9 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` tự xác nhận `capture_enabled=False` trước khi kết thúc |

Tất cả 5 evidence script chạy TUẦN TỰ trên CÙNG một DB (sau khi re-apply migration do
`migration_test.py` kịch bản rollback dọn sạch), xác nhận không rò rỉ state giữa các lần chạy —
kể cả 4 bảng mới và 9 role (8 role M4 cũ + `alpha3s_m4_actor_binder` mới).

## 5. Known limitations (không đổi so với Correction #3 §5, cộng thêm)

13. **`m4_stage0p_staff_permissions` chưa có quy trình vận hành thật để cấp/thu hồi quyền**
    (T4-04) — kỹ thuật đã sẵn sàng (bảng + `require_pinned_actor` enforce đúng), nhưng "ai được
    cấp `m4.stage0p.approve`, dựa trên văn bản quyết định nào, có cần 2-người-duyệt không" là
    quyết định vận hành thuộc giai đoạn production-activation, ngoài phạm vi Stage 0P dev/test.
14. **`m4_stage0p_pin_actor` hiện chỉ xác minh `staff_id` tồn tại + active — KHÔNG xác minh
    caller thực sự LÀ staff đó** (vd qua password/JWT/session token đã xác thực ở tầng ứng dụng).
    Đây là giới hạn CÓ CHỦ Ý của Stage 0P (dev/test synthetic harness gọi hàm DB trực tiếp, chưa
    có tầng HTTP API/auth thật nào tồn tại cho M4) — role `alpha3s_m4_actor_binder` là ranh giới
    kỹ thuật DUY NHẤT hiện có (chỉ ai giữ credential role này mới pin được actor), tương đương
    "tin cậy lớp gọi vào, không tin cậy tham số". Khi Stage 0P được wire vào API thật, tầng auth
    HTTP (JWT/session đã xác thực) PHẢI là nơi DUY NHẤT gọi `pin_actor` — không được để code
    nghiệp vụ khác tự chọn staff_id để pin. Đây là quyết định kiến trúc cần CA/PO xác nhận trước
    activation, không phải thứ Dev có thể tự đóng ở tầng Stage 0P.
15. **Ngưỡng gate T4-05 (10%/200) là đề xuất CA Review #4, chưa có PO decision record chính
    thức** — bảng `m4_stage0p_exclusion_gate` đã sẵn sàng kỹ thuật để đổi qua migration mới khi
    PO/CA ra quyết định chính thức khác, nhưng hiện tại KHÔNG có cơ chế thay đổi giá trị này
    NGOÀI một migration — nếu cần một quy trình vận hành (function có audit) để PO tự cập nhật
    ngưỡng mà không cần Dev triển khai migration mỗi lần, đây là việc bổ sung cho giai đoạn sau.

## 6. Đề nghị

CA review Correction #4 đối chiếu 5 finding `T4-01..T4-05`. Không xin quyền production-data-
access/activation — gate đó vẫn tách riêng theo Design Acceptance §6, xin sau khi Correction #4
được nghiệm thu.
