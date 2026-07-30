---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-8-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #8
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-30
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-7-VI.md (CA, CHANGES_REQUIRED, reviewed_head d05d9fba7a8a5411e15a7620c363e1e20632c2c6)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #8

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-7-VI.md` — sửa `T7-01` (P1) và `T7-03` (P2) bằng
code + evidence; `T7-03` yêu cầu code CHÍNH nó cũng đã đóng. `T7-02` (P1) **KHÔNG sửa bằng code**
round này — CA chỉ rõ "không được tuyên bố finding closed nếu kiến trúc hiện tại không thể kiểm
chứng ciphertext... khi đó cần trình CA/PO một architecture decision thay vì thêm heuristic" (§F-
M4-0P-T7-02, yêu cầu cuối). §5 dưới đây trình bày architecture decision request theo đúng yêu cầu
đó, xin CA/PO quyết định trước khi Dev tiếp tục. `T6-03` KHÔNG động tới (exact delta round này
không chạm phần đã CLOSED AT CODE-DESIGN LEVEL). Phạm vi KHÔNG đổi: dev/test trên branch M4
(worktree `D:\alpha3s-m4`, KHÔNG checkout M4 trong `D:\alpha3s`), dữ liệu synthetic/test, **KHÔNG**
merge/deploy/production-data-access/activation. Ngưỡng exclusion `10%/200` (T4-05) tiếp tục ở
nguyên trạng CA đề xuất, CHƯA có PO decision record chính thức.

## 1. Mapping finding → sửa (hoặc architecture decision)

| Finding | Xử lý | File |
|---|---|---|
| **T7-01** (P1) — `session_nonce`+TTL (Correction #7) chặn được PID-tái-sử-dụng-sau-khi-chết, nhưng CA chỉ rõ CHƯA chặn được 1 connection **pool** tái sử dụng **chính connection còn sống** cho request/actor khác — row/backend_pid/GUC đều còn nguyên, request sau "kế thừa" pin của request trước trong tối đa 15 phút | `m4_stage0p_require_pinned_actor` TIÊU THỤ (`DELETE`) row pin ngay khi validate THÀNH CÔNG — **consume-on-use**: 1 pin dùng được cho ĐÚNG 1 hành động nghiệp vụ. Vì PL/pgSQL không có autonomous transaction (Correction #7 §3), `DELETE` này CHỈ thực sự COMMIT nếu cả hàm nghiệp vụ bao quanh (set_capture/record_approval/revoke_approval/seal_labels/complete_evaluation/set_current_normalization_version) THÀNH CÔNG tới cùng — 1 hành động THẤT BẠI vì lý do KHÁC (không phải vì actor) KHÔNG tiêu thụ pin, giữ đúng ngữ nghĩa "retry hợp lệ với CÙNG pin". Giới hạn còn lại (khai báo minh bạch, xem §4): pin đã tạo nhưng CHƯA TỪNG dùng thành công (bị ngắt quãng trước khi gọi hàm nghiệp vụ đầu tiên, hoặc trước khi gọi `unpin_actor()`) vẫn còn hiệu lực cho tới khi TTL hết hạn hoặc connection đóng thật sự — cần tích hợp tầng connection-pool thật (pool checkin hook gọi `unpin_actor()`) ở giai đoạn production-activation | `migrations/039_m4_stage0p.sql` §5d (`require_pinned_actor`) |
| **T7-02** (P1) — digest canonical plaintext (Correction #7) được bind đúng, nhưng `record_sample()` vẫn nhận `p_encrypted_message` từ caller mà KHÔNG xác minh ciphertext đó THẬT SỰ giải mã ra plaintext mang đúng digest — 1 caller đã qua fetch hợp lệ (biết đúng canonical text + đủ AAD fields) vẫn có thể gửi 1 ciphertext hợp lệ NHƯNG KHÁC (vd tự encrypt lại với nonce AEAD khác) mà DB không phát hiện được | **KHÔNG sửa bằng code round này** — xem §5 Architecture Decision Request. DB không giữ khóa giải mã (có chủ ý, phục vụ key-rotation/DSR crypto-shredding — xem Known Limitations mọi round trước), nên không có cách nào tại tầng DB thuần túy xác minh ciphertext↔plaintext mà không hoặc (a) đổi kiến trúc để DB tham gia encrypt, hoặc (b) chấp nhận giới hạn kiến trúc và trình CA/PO quyết định | — (không có thay đổi code) |
| **T7-03** (P2) — `write_predictions()` (Correction #7) đọc row `is_current=true` (registry TOÀN CỤC) làm authority cho `normalization_version` — SAI nếu registry đổi SAU khi batch lock/capture nhưng TRƯỚC prediction (batch hợp lệ theo version ĐÃ KHÓA có thể bị loại hàng loạt sai lệch) | `write_predictions` đọc `v_batch.normalization_version` (đã khóa từ lúc `lock_batch`, FK đảm bảo luôn tồn tại trong registry) thay vì đọc lại "current" toàn cục — "current" giờ CHỈ quyết định version cho batch MỚI. `run_prediction_writer()` (Python) sửa tương tự — bỏ gọi `get_current_normalization_version()`, đọc `normalization_version` từ chính batch row đã fetch. Thêm `pg_advisory_xact_lock` serialize `set_current_normalization_version` (chống race 2 giao dịch đổi version đồng thời) | `migrations/039_m4_stage0p.sql` §5i (`write_predictions`)/§5d2 (`set_current_normalization_version`); `app/services/pii/stage0p_prediction.py:run_prediction_writer` |

## 2. Nguyên tắc sửa chung (không đổi so với Correction #1-7)

T7-01/T7-03 tiếp tục nguyên tắc xuyên suốt: **thứ dùng làm bằng chứng phải là thứ DB tự cấp phát/
tự tính, gắn đúng phạm vi (scope) mà nó THẬT SỰ đại diện, không mở rộng ngầm sang phạm vi khác**.
T7-01: một pin đại diện cho "quyền thực hiện 1 hành động", không phải "quyền của cả phiên kết nối
trong 15 phút" — consume-on-use thu hẹp đúng phạm vi đó. T7-03: `normalization_version` của 1
batch đại diện cho "phiên bản đã khóa lúc batch được tạo", không phải "phiên bản hiện hành toàn hệ
thống tại bất kỳ thời điểm nào sau đó" — đọc `v_batch.normalization_version` thay vì registry
`is_current` sửa đúng chỗ nhầm phạm vi này.

## 3. Bug tự phát hiện trong lúc triển khai (khai báo minh bạch)

1. **`alpha3s_m4_prediction_writer` chưa có `GRANT SELECT` trên cột `normalization_version` của
   `m4_selection_batches`** — vì T7-03 đổi `run_prediction_writer()` sang đọc trực tiếp cột này
   từ batch row (trước đó chỉ đọc `labels_sealed_hash`), lộ ra ngay lần chạy evidence đầu tiên
   (`InsufficientPrivilegeError`). Sửa: thêm cột vào GRANT hiện có (không cấp thêm quyền nào khác
   ngoài cột cần).
2. **Test `set_current_normalization_version` (T6-04, đã pass ở Correction #7) vỡ do consume-
   on-use (T7-01)** — kịch bản gọi hàm này 2 LẦN liên tiếp trên CÙNG 1 pin (lần 2 để kiểm tra
   "version trùng bị từ chối") không còn hợp lệ sau khi pin trở thành 1-lần-dùng. Không phải bug
   sản phẩm — xác nhận đúng bằng agent rà soát TOÀN BỘ 6 file liên quan (2 module Python + 4
   evidence script) tìm mọi chỗ "1 pin, 2+ lời gọi nghiệp vụ" TRƯỚC khi sửa migration, xác nhận
   đây là ĐIỂM DUY NHẤT bị ảnh hưởng trong toàn bộ codebase. Sửa: thêm 1 lần pin lại giữa 2 lời
   gọi trong test.
3. **Race test kịch bản [G] (`m4_stage0p_sampling_test.py`, Pending-DSR race) "flaky" giả —
   nguyên nhân THẬT là Redis KHÔNG được reset giữa các lần Dev tự chạy lại evidence thủ công
   trong phiên làm việc này** (chỉ Postgres được `DROP SCHEMA` mỗi lần, Redis là container riêng,
   sống xuyên suốt). Khóa `del_pending:cap-g` (TTL 15 phút) từ 1 lần chạy TRƯỚC đó vẫn còn hiệu
   lực khi Dev chạy lại NHIỀU LẦN liên tiếp trong vài phút để debug — khiến pending-check báo
   `true` NGAY TỪ CANDIDATE ĐẦU TIÊN thay vì đúng lúc watcher chủ động đặt cờ giữa chừng, làm
   0 sample commit trước khi `close_collection` chạy (đúng luật T6-03 "corpus rỗng bị từ chối" —
   bản thân luật này hoạt động ĐÚNG, chỉ là tiền đề race bị phá bởi state cũ). Xác nhận bằng
   thực nghiệm: viết lại CHÍNH XÁC logic kịch bản [G] trong 1 script debug độc lập với 1 DB sạch
   + psid RIÊNG (không đụng key Redis cũ) — chạy ĐÚNG như thiết kế (1 sample commit trong ~200ms,
   watcher đặt cờ đúng lúc); sau đó `redis-cli FLUSHALL` + chạy lại file gốc — PASS ngay, không
   sửa gì thêm về logic. Đây KHÔNG phải bug code (T7 hay các round trước) — là gap trong quy
   trình dọn dẹp môi trường test THỦ CÔNG của Dev (chỉ reset Postgres, quên Redis) khi lặp lại
   nhiều lần trong 1 phiên debug. Vẫn nâng cấp phụ (không bắt buộc để sửa bug): mở rộng cửa sổ
   polling của watcher từ 500ms lên 10s (thay `for _ in range(500): sleep(0.001)` bằng
   `for _ in range(5000): sleep(0.002)` + `else: raise AssertionError(...)` rõ ràng nếu THẬT SỰ
   timeout) — biên độ an toàn hơn cho môi trường container có thể chậm hơn máy phát triển, và bây
   giờ báo lỗi RÕ RÀNG thay vì im lặng dựa may rủi timing nếu tình huống này tái diễn.

## 4. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`; DB reset từ `DROP SCHEMA public CASCADE` + **`redis-cli FLUSHALL`** rồi `migrate.py up` lại từ đầu ngay trước loạt chạy cuối — cả 2 tầng state đều sạch, không chỉ Postgres)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` + `migrate.py up` (001..039 từ trạng thái sạch thật sự) | 0 | `OK 039_m4_stage0p`, postcondition PASS ngay lần đầu |
| 2 | `m4_stage0p_migration_test.py` | 0 | RESULT: PASS (fresh+idempotent+existing-apply+rollback) — re-apply `migrate.py up` ngay sau (kịch bản rollback dọn sạch schema M4, đúng ý đồ thiết kế) |
| 3 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS, 0 FAIL. Thêm mảng adversarial MỚI: (a) T7-01 — actor A pin + 1 hành động THÀNH CÔNG, actor B "mượn" CHÍNH connection đó (KHÔNG pin lại) → bị từ chối ngay ("chua pin actor"); (b) T7-01 — 1 hành động THẤT BẠI vì lý do KHÁC actor (approval không tồn tại) KHÔNG tiêu thụ pin, retry với CÙNG pin vẫn thành công (chứng minh consume-on-SUCCESS, không phải consume-on-attempt); (c) T7-03 — đổi "current" toàn cục giữa lock→seal→prediction của 1 batch 200-conversation thật, batch cũ VẪN xử lý đúng 200/200 theo version đã khóa (không bị loại nhầm), batch MỚI (`lock_batch()` Python thật) dùng đúng version mới. Toàn bộ ma trận T1-T6 cũ không đổi hành vi |
| 4 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — 9 kịch bản REV3 không đổi hành vi |
| 5 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J, bao gồm kịch bản [G] race sau khi loại bỏ nhiễu Redis — xem §3 mục 3) |
| 6 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS — file này không gọi `set_capture`/`record_approval`/`revoke_approval`/`set_current_normalization_version` 2 lần trên cùng 1 pin, nên T7-01 không chạm tới theo cách cần sửa gì thêm; không gọi `write_predictions` với registry đổi giữa chừng, nên T7-03 không chạm tới |
| 7 | `pytest -q` (full) | 0 | **241 passed** (không đổi — thay đổi REV8 chỉ ở DB boundary/Python wrapper mỏng, không chạm logic thuần) |
| 8 | `ruff check app/services/pii/ scripts/m4_stage0p_*.py tests/test_m4_*.py` | 0 | All checks passed |
| 9 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` tự xác nhận `capture_enabled=False` trước khi kết thúc |

Cả 4 evidence script chạy TUẦN TỰ trên CÙNG một DB (sau khi re-apply migration do
`migration_test.py` kịch bản rollback dọn sạch), xác nhận không rò rỉ state giữa các lần chạy —
kể cả hành vi consume-on-use MỚI của actor pin (mọi call site "1 pin → nhiều hành động" đã được rà
soát và sửa đủ, xem §3 mục 2).

## 5. Architecture Decision Request — T7-02 (ciphertext binding)

CA chỉ rõ: nếu kiến trúc hiện tại không thể kiểm chứng ciphertext, không được tuyên bố finding
closed bằng thêm heuristic — phải trình CA/PO quyết định. Dev trình bày 2 phương án cụ thể, không
tự chọn thay CA/PO:

**Bối cảnh kỹ thuật**: `m4_stage0p_record_sample()` (chạy dưới role `alpha3s_m4_definer`,
SECURITY DEFINER) không bao giờ nắm khóa giải mã AES-256-GCM của sample zone — quyết định kiến
trúc CÓ CHỦ Ý từ Submission #1 (T4 mục Known Limitations mọi round), phục vụ 2 mục tiêu: (a) key
rotation không cần touch DB, (b) DSR crypto-shredding (xóa khóa = coi như đã xóa dữ liệu, không
cần DELETE từng row) vẫn đúng ngay cả khi DB có toàn quyền trên bảng. Vì không có khóa, DB không
thể tự giải mã `p_encrypted_message` để đối chiếu với `fetched_canonical_digest` — mọi kiểm tra DB
làm được (digest canonical plaintext, AAD qua context, độ dài/truncation, capability nonce
one-shot) đều là ràng buộc GIÁN TIẾP, không phải bằng chứng ciphertext↔plaintext trực tiếp.

**Phương án A — DB tham gia encrypt trong 1 trusted boundary** (đóng T7-02 hoàn toàn): chuyển
bước encrypt vào NGAY TRONG `record_sample()` (hoặc 1 hàm SECURITY DEFINER mới gộp fetch+
normalize+truncate+encrypt+persist) — DB tự tạo ciphertext từ canonical plaintext nó ĐÃ CÓ (từ
`fetch_message_content`), Python KHÔNG còn tự encrypt/tự truyền `p_encrypted_message` nữa. Đánh
đổi: **DB phải giữ khóa AES-256-GCM** (hoặc pgcrypto tương đương) — phá vỡ 2 mục tiêu kiến trúc
CÓ CHỦ Ý ở trên (key rotation cần đổi cả DB; DSR crypto-shredding không còn tin cậy tuyệt đối nếu
DB cũng có bản sao khóa/khả năng giải mã lại). Đây là thay đổi kiến trúc LỚN, vượt phạm vi 1
correction round, cần CA/PO xác nhận trước khi triển khai.

**Phương án B — Chấp nhận giới hạn kiến trúc, ghi nhận chính thức** (KHÔNG đóng T7-02, giữ nguyên
hiện trạng có kiểm soát): giữ kiến trúc "DB không giữ khóa" như hiện tại; T7-02 tiếp tục là known
limitation CHÍNH THỨC được PO/CA xác nhận bằng văn bản (không phải Dev tự diễn giải), với các
ràng buộc bù đắp đã có (digest canonical plaintext + AAD domain-tag theo customer_ref/
conversation_ref/sample_id + capability nonce one-shot txid-based) được công nhận là "đủ tốt cho
mức độ tin cậy Stage 0P dev/test", và đưa vào điều kiện RÕ RÀNG trước khi activation: hoặc triển
khai Phương án A trước activation, hoặc bổ sung kiểm soát ngoài DB (vd code review + giám sát vận
hành cho role `alpha3s_m4_sample_collector`) như biện pháp bù trừ.

**Đề xuất của Dev** (không phải quyết định — CA/PO quyết): Phương án B cho giai đoạn Stage 0P
dev/test hiện tại (rủi ro thực tế thấp — vector tấn công đòi hỏi ĐÃ có quyền thực thi vai trò
`alpha3s_m4_sample_collector`, tức đã vượt qua nhiều lớp kiểm soát khác), kèm điều kiện: quyết
định về Phương án A (hoặc phương án khác) phải được chốt TRƯỚC khi Stage 0P được cấp quyền
production-data-access/activation — không được để mặc định trôi qua giai đoạn đó.

## 6. Known limitations (không đổi so với Correction #7 §5, cộng thêm)

24. **T7-01 vẫn còn khoảng cách "pin chưa từng được dùng thành công"** (xem §1 bảng finding) — consume-on-use đóng đúng kịch bản CA nêu cụ thể (actor A dùng xong, actor B mượn connection), nhưng KHÔNG đóng được trường hợp pin bị bỏ dở (không có hành động nghiệp vụ nào chạy) trước khi connection được tái sử dụng — vẫn phụ thuộc TTL (15 phút) hoặc `unpin_actor()` được gọi đúng cách. Đóng triệt để đòi hỏi tích hợp tầng connection-pool THẬT (pool checkin/reset hook gọi `unpin_actor()`), việc mà Stage 0P dev/test hiện chưa có (mỗi evidence script mở connection MỚI cho mỗi thao tác, không dùng pool thật) — quyết định kiến trúc này (cùng T6-01 giới hạn #20 Correction #7 về authenticated application principal) cần CA/PO xác nhận cùng lúc khi thiết kế tầng HTTP API thật cho Stage 0P.
25. **T7-02 KHÔNG đóng — xem §5 Architecture Decision Request.** Đây là known limitation CHỦ ĐỘNG khai báo lại (không phải bug mới), chờ CA/PO quyết định giữa Phương án A/B trước activation.
26. Ngưỡng gate T4-05/T6-03 (10%/200, `gate_version=ca-review-4-proposed-v1`) — không đổi so với Correction #7 giới hạn #23: vẫn là đề xuất CA, CHƯA có PO decision record chính thức.

## 7. Đề nghị

CA review Correction #8 đối chiếu `T7-01`/`T7-03` (sửa bằng code) và §5 Architecture Decision
Request cho `T7-02` (chờ CA/PO quyết định giữa Phương án A/B, không phải code fix). Không xin
quyền production-data-access/activation — gate đó vẫn tách riêng theo Design Acceptance §6.
