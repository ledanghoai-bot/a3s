---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-7-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #7
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-30
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-6-VI.md (CA, CHANGES_REQUIRED, reviewed_head 62b47b7f3bd16b4d9afa4eae490646d021de1915)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #7

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-6-VI.md` — sửa đúng 4 finding `T6-01..T6-04`
(T6-01/02/03 = P1, T6-04 = P2). **Thống nhất số hiệu submission theo đúng yêu cầu CA §1**: tài
liệu commit trước (sửa T5-01..04) do Dev tự đặt tên `...CORRECTION-5-VI.md`, trong khi CA/PO đếm
đó là **Correction #6**; nộp lần này Dev đặt tên **Correction #7**, khớp đúng số thứ tự submission
thật (tính từ PO/CA, không tính riêng theo tên file nội bộ) — từ nay về sau đặt tên theo đúng dãy
số này. Phạm vi KHÔNG đổi: dev/test trên branch M4 (worktree `D:\alpha3s-m4`, KHÔNG checkout M4
trong `D:\alpha3s`), dữ liệu synthetic/test, **KHÔNG** merge/deploy/production-data-access/
activation. Ngưỡng exclusion `10%/200` (T4-05, `gate_version = ca-review-4-proposed-v1`) tiếp tục
ở nguyên trạng CA đề xuất, CHƯA có PO decision record chính thức.

## 1. Mapping 4 finding → sửa

| Finding | Sửa | File |
|---|---|---|
| **T6-01** `m4_stage0p_actor_session` REV6 chỉ khóa bởi `backend_pid` ĐƠN — PID có thể bị OS tái sử dụng cho 1 kết nối HOÀN TOÀN MỚI sau khi backend cũ chết (session mới vô tình "kế thừa" pin cũ); không có expiry/TTL; `pin_secret` lưu PLAINTEXT, không rotation/revocation/rate-limit | Thêm cột `session_nonce` (UUID ngẫu nhiên `pin_actor` sinh, đặt ĐỒNG THỜI vào row VÀ vào 1 GUC session-scoped của CHÍNH connection gọi — GUC này KHÔNG sinh tồn qua 1 backend process MỚI dù PID trùng, và KHÔNG BAO GIỜ trả về cho caller/SELECT được từ bảng nên không đoán/đọc lại được) — `require_pinned_actor` đối chiếu GUC hiện tại với `session_nonce` đã lưu mỗi lần gọi, phát hiện chính xác PID-tái-sử-dụng MÀ KHÔNG cần đọc `pg_stat_activity` (xem §3 bug tự phát hiện — cột `backend_start` bị Postgres NULL hóa cho role không đặc quyền). Thêm `expires_at` bắt buộc (TTL 15 phút, không còn "pin vĩnh viễn"). `pin_secret` chuyển sang `pin_secret_hash` (pgcrypto `crypt()`/`gen_salt('bf')`, KHÔNG còn plaintext — cùng quy ước `staff_users.password_hash`). Thêm rate-limit (`failed_attempts`/`locked_until`, khóa 15 phút sau 5 lần sai). Hàm mới `m4_stage0p_unpin_actor()` — "logout" tường minh (tự xóa pin của CHÍNH session gọi, không đòi permission). Giới hạn còn lại (khai báo minh bạch): Stage 0P CHƯA có tầng HTTP auth/identity-provider thật — `pin_secret` vẫn là 1 bespoke shared credential, không phải binding từ authenticated application principal thật sự; đây là quyết định kiến trúc cần CA/PO xác nhận trước activation, không phải thứ Dev tự đóng được ở tầng DB | `migrations/039_m4_stage0p.sql` §2f/§5d/§5d2; `app/services/pii/stage0p_control.py:pin_actor/unpin_actor` |
| **T6-02** `record_sample()` REV6 chỉ kiểm độ dài/truncation HEURISTIC (khoảng hợp lý) — ciphertext KHÁC nhưng CÙNG độ dài vẫn qua được, không chứng minh payload thật sự bắt nguồn từ nội dung đã fetch | `fetch_message_content` TỰ TÍNH digest SHA-256 trên đúng văn bản canonical (NFC-normalize + truncate 2 bước GIỐNG HỆT logic Python `_truncate(nfc(...))`, tái tạo chính xác trong PL/pgSQL kể cả trường hợp UTF-8-byte-truncation giữa ký tự đa byte) lúc fetch, lưu vào `fetch_capability.fetched_canonical_digest`; `record_sample` đòi hỏi `p_canonical_text_digest` (Python tính NGAY TRƯỚC lúc encrypt, trên chính văn bản đã encrypt) khớp CHÍNH XÁC — sai là RAISE ngay, không còn "trong khoảng hợp lý". Do digest đã chứng minh đúng nội dung, `canonical_text_len`/`truncated` giờ bắt buộc khớp CHÍNH XÁC (không còn chỉ là biên trên). Giới hạn còn lại: DB vẫn KHÔNG có khóa giải mã nên không xác minh được ciphertext GIẢI MÃ RA đúng plaintext đó — digest chỉ chứng minh caller SỞ HỮU đúng canonical text gốc; kết hợp AAD (đã có từ trước) là ràng buộc gần nhất có thể đạt được mà không đổi kiến trúc "plaintext không bao giờ rời Python process" | `migrations/039_m4_stage0p.sql` §3b/§5b/§5c |
| **T6-03** `close_collection()` REV6 dùng NGƯỠNG TỶ LỆ (`exclusion_gate`, vẫn là đề xuất CA Review #4, CHƯA có PO decision record) để CHO PHÉP batch có `permanent_failed` đi tiếp — CA chỉ rõ không được dùng đề xuất chưa duyệt theo hướng "cho phép"; gate cũng chỉ tính `permanent_failed/total_candidates`, không đưa `excluded` vào numerator, batch 19 excluded + 1 permanent_failed + 0 committed vẫn đóng được | Bỏ HẲN dùng tỷ lệ cho `permanent_failed` — batch có BẤT KỲ `permanent_failed` nào (>0) đều RAISE `INSUFFICIENT_DATA` VÔ ĐIỀU KIỆN cho tới khi có PO decision record thật sự (chính sách đánh dấu rõ `capture_gate_policy = 'zero_tolerance_pending_po_decision_v1'`, lưu trên batch row + đưa vào hash chain). Thêm: từ chối đóng corpus RỖNG (0 candidate committed) — sanity cơ bản, không phải ngưỡng governance. `capture_gate_policy` đưa vào `labels_sealed_hash` v3 (cùng `capture_excluded_count`/`capture_permanent_failed_count`, trước đây REV6 lưu trên batch nhưng CHƯA từng nằm trong hash chain) — đáp ứng yêu cầu CA "bind counts, gate version và quyết định closure vào tamper-evident evidence/hash" | `migrations/039_m4_stage0p.sql` §5c2 (`close_collection`)/§5h (`seal_labels` hash v3) |
| **T6-04** (P2) Registry REV6 là singleton MUTABLE (1 row, UPDATE tại chỗ) — vẫn là 1 nguồn "mềm" không có lịch sử/immutable; `m4_selection_batches.normalization_version` còn `DEFAULT 'nfc-v1'` (nguồn hardcode thứ 2 tiềm ẩn nếu 1 INSERT quên chỉ định cột) | Registry đổi thành APPEND-ONLY (PK=`version`, cột `is_current` là DUY NHẤT được phép UPDATE qua trigger guard, không bao giờ DELETE — cả 2 đều RAISE nếu vi phạm). Hàm mới `m4_stage0p_set_current_normalization_version(version, approval_ref)` — đòi hỏi pinned actor + quyền `m4.stage0p.approve`, ghi audit, version MỚI HOÀN TOÀN (không tái tạo version đã dùng — lịch sử bất biến). Bỏ `DEFAULT` trên `m4_selection_batches.normalization_version` + thêm FK tới `registry(version)` (không còn insert được version không tồn tại/không biết) | `migrations/039_m4_stage0p.sql` §2g (bảng + trigger guard)/§5d2 (hàm mới)/§3 (bỏ DEFAULT + FK) |

## 2. Nguyên tắc sửa chung (không đổi so với Correction #1-6, áp dụng đúng khoảng cách CA chỉ ra)

CA chỉ rõ round trước (T5-01/T5-02) *trông giống* đã đóng nhưng còn khoảng cách cụ thể: T5-01 đổi
từ GUC-mang-danh-tính sang bảng khóa bởi `backend_pid` nhưng KHÔNG chống được PID-tái-sử-dụng/
connection-pool-reuse; T5-02 đổi từ tin caller sang kiểm "trong khoảng hợp lý" nhưng KHÔNG chứng
minh được NỘI DUNG. Round này đóng đúng 2 khoảng cách đó bằng 1 nguyên tắc chung, nhất quán với
mọi round trước: **thứ dùng làm bằng chứng phải là thứ DB tự cấp phát/tự tính VÀ caller không thể
tự tạo ra hay đoán được** — `session_nonce` ngẫu nhiên (không phải PID hệ thống caller có thể suy
luận, không phải GUC caller tự ghi được) thay cho `backend_pid` đơn; digest SHA-256 của nội dung
THẬT (DB tự tính từ chính dữ liệu nó fetch) thay cho việc tin độ dài caller khai báo. T6-03/T6-04
áp dụng nguyên tắc phụ đã dùng ở các round trước: không dùng ngưỡng CHƯA được duyệt theo hướng "nới
lỏng" (T6-03), và gộp nguồn hardcode kép thành 1 bảng DB có lịch sử bất biến (T6-04).

## 3. Bug tự phát hiện trong lúc triển khai (khai báo minh bạch)

1. **`pg_stat_activity.backend_start` bị Postgres NULL hóa cho role KHÔNG đặc quyền** — thiết kế
   ban đầu của T6-01 dùng `backend_start` (đọc từ `pg_stat_activity`) kết hợp `backend_pid` để
   chống PID-tái-sử-dụng, dựa trên giả định "1 backend luôn thấy được đầy đủ thông tin hoạt động
   của chính nó". Xác nhận bằng thử nghiệm thực tế: dưới role `alpha3s_m4_definer` (không phải
   superuser, không phải thành viên `pg_read_all_stats`), cột `backend_start` trong hàng
   `pg_stat_activity` của CHÍNH backend đang gọi bị trả về NULL — hàng vẫn hiển thị (PID/state
   thấy được) nhưng cột này bị ẩn cho vai trò không đặc quyền, khác giả định ban đầu. Sửa: thiết
   kế lại HOÀN TOÀN sang `session_nonce` (UUID ngẫu nhiên đặt vào GUC session-scoped của chính
   connection) — không phụ thuộc `pg_stat_activity` nữa, và về logic còn chặt hơn thiết kế cũ (một
   backend MỚI luôn có GUC tùy chỉnh RỖNG, bất kể có đọc được stats hay không).
2. **PL/pgSQL KHÔNG có autonomous transaction — `UPDATE` rồi `RAISE EXCEPTION` trong CÙNG lời gọi
   hàm khiến UPDATE bị ROLLBACK theo, không bao giờ thực sự ghi xuống** — đây là lớp bug MỚI, xác
   nhận bằng thử nghiệm trực tiếp (hàm PL/pgSQL tối giản: `UPDATE` 1 bảng rồi `RAISE EXCEPTION`;
   sau khi gọi, giá trị KHÔNG đổi). Bug này làm hỏng thiết kế rate-limit ban đầu của T6-01
   (`pin_actor` định tăng `failed_attempts` RỒI `RAISE` khi sai `pin_secret` — counter không bao
   giờ thực sự tăng) VÀ thiết kế dọn dẹp ban đầu của T6-01 cho session STALE/hết hạn
   (`require_pinned_actor` định `DELETE` row rồi `RAISE` — row không bao giờ thực sự bị xóa). Sửa
   2 nơi khác nhau theo đúng bản chất từng trường hợp: (a) `pin_actor` — bỏ `RAISE` cho nhánh
   `pin_secret` sai/đang khóa, thay bằng `RETURN QUERY` 1 hàng `pinned_staff_id=NULL` (để `UPDATE`
   counter được COMMIT bình thường như 1 lời gọi THÀNH CÔNG), Python wrapper (`pin_actor()`) tự
   `RAISE ActorNotPinnedError` dựa trên giá trị trả về thay vì dựa vào lỗi DB; (b) `require_pinned_
   actor` — bỏ hẳn `DELETE` trước `RAISE` (không cần thiết về bảo mật: kiểm tra luôn đánh giá LẠI
   TỪ ĐẦU mỗi lần gọi dựa trên dữ liệu hiện tại của row, dù row cũ có còn tồn tại hay không kết quả
   vẫn đúng; dọn dẹp tự nhiên xảy ra khi pin lại — `ON CONFLICT DO UPDATE` ghi đè row cũ).
3. **`AmbiguousColumnError` lặp lại đúng 1 lần** (cùng lớp lỗi đã gặp nhiều round trước —
   PL/pgSQL tự sinh 1 biến cho MỖI cột trong `RETURNS TABLE(...)`) — hàm mới
   `m4_stage0p_set_current_normalization_version` có `RETURNS TABLE(version TEXT, ...)`; câu
   `SELECT 1 FROM m4_stage0p_normalization_registry WHERE version = p_version` mơ hồ giữa biến OUT
   `version` và cột bảng cùng tên. Sửa alias bảng (`AS nr`, `nr.version`) — bắt được NGAY LẦN CHẠY
   EVIDENCE ĐẦU TIÊN.
4. **`FOREIGN KEY approved_by → staff_users(id)` (registry, T6-04) chặn dọn dẹp `staff_users`
   cuối evidence script** — do registry là APPEND-ONLY, row lịch sử test (`nfc-v2-test`) không thể
   xóa được kể cả sau khi đổi `is_current=false`, khiến `DELETE FROM staff_users` cuối
   `permissions_test.py` vỡ FK. Đây là mâu thuẫn thiết kế thật giữa "audit trail" (ai duyệt) và
   "immutable history" (row không bao giờ mất) — không phải lỗi test fixture đơn thuần. Sửa đúng
   gốc: đổi `approved_by` sang `ON DELETE SET NULL` (mất tham chiếu người duyệt khi staff bị xóa
   là chấp nhận được cho 1 cột audit-trail, KHÔNG nên chặn việc xóa entity được tham chiếu); đồng
   thời nới trigger guard cho phép `approved_by` chuyển **về NULL** (qua đúng đường `ON DELETE SET
   NULL`) trong khi vẫn chặn MỌI thay đổi khác trên cột này (vd đổi sang 1 staff_id khác).
5. **2 chuỗi test "cùng độ dài" ban đầu tính sai** (`permissions_test.py`, kịch bản T6-02
   ciphertext-substitution) — "noi dung goc that su" (20 ký tự) so với chuỗi giả mạo ban đầu "noi
   dung gia mao vay!" (21 ký tự, đếm tay sai) khiến kịch bản thất bại ở bước setup thay vì đúng
   bước đang test. Sửa: đếm lại bằng `len()` thực tế, đổi chuỗi giả mạo thành "noi dung gia mao
   roi" (khớp đúng 20 ký tự).

## 4. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`; DB reset từ `DROP SCHEMA public CASCADE` rồi `migrate.py up` lại từ đầu ngay trước loạt chạy cuối)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `DROP SCHEMA public CASCADE` + `CREATE SCHEMA public` + `migrate.py up` (001..039 từ DB rỗng thật sự) | 0 | `OK 039_m4_stage0p`, postcondition PASS ngay lần đầu |
| 2 | `m4_stage0p_migration_test.py` | 0 | RESULT: PASS (fresh+idempotent+existing-apply+rollback) — re-apply `migrate.py up` ngay sau (kịch bản rollback dọn sạch schema M4, đúng ý đồ thiết kế) trước khi chạy evidence tiếp theo |
| 3 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS, 0 FAIL. Bao gồm mảng adversarial MỚI cho T6-01..04: rate-limit (5 lần sai liên tiếp → khóa 15 phút, secret ĐÚNG sau đó vẫn bị từ chối trong lúc khóa); pin hết hạn (`expires_at` quá khứ → từ chối, pin lại ghi đè đúng); `session_nonce` không khớp (mô phỏng PID tái sử dụng sau khi backend chết → từ chối, pin lại ghi đè đúng); `unpin_actor()` — "logout" tường minh có hiệu lực ngay; digest ciphertext-substitution (nội dung KHÁC, CÙNG độ dài khai báo đúng → từ chối); registry append-only (UPDATE/DELETE trực tiếp bị trigger chặn); `set_current_normalization_version` (chưa pin → từ chối; thành công → `is_current` chuyển đúng, version cũ vẫn còn với `is_current=false`; version trùng → từ chối). Toàn bộ ma trận T1-T5 cũ (record_sample digest-exact-match, close_collection zero-tolerance thay rate-based, corpus rỗng bị từ chối) đều PASS |
| 4 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — 9 kịch bản REV3 không đổi hành vi sau khi `pin_actor` chuyển hẳn sang `session_nonce` |
| 5 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J không đổi hành vi) |
| 6 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS — file này insert trực tiếp qua admin/superuser (không qua `record_sample`), nên T6-02 không chạm tới; không gọi `mark_candidate_outcome`/`close_collection`, nên T6-03 không chạm tới |
| 7 | `pytest -q` (full) | 0 | **241 passed** (không đổi so với Correction #6 — thay đổi REV7 chỉ ở DB boundary/Python wrapper mỏng, không chạm logic thuần) |
| 8 | `ruff check app/services/pii/ scripts/m4_stage0p_*.py tests/test_m4_*.py` | 0 | All checks passed |
| 9 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` tự xác nhận `capture_enabled=False` trước khi kết thúc |

Cả 4 evidence script chạy TUẦN TỰ trên CÙNG một DB (sau khi re-apply migration do
`migration_test.py` kịch bản rollback dọn sạch), xác nhận không rò rỉ state giữa các lần chạy —
kể cả cột mới (`session_nonce`/`expires_at`/`pin_secret_hash`/`failed_attempts`/`locked_until` trên
actor_session/actor_credentials, `fetched_canonical_digest` trên fetch_capability,
`capture_gate_policy` trên batch) và bảng registry đổi cấu trúc hoàn toàn (singleton → append-only
versioned).

## 5. Known limitations (không đổi so với Correction #6 §5, cộng thêm)

20. **T6-01 vẫn KHÔNG kết nối với 1 tầng authentication HTTP thật** (giống giới hạn #18 Correction
    #6, CHƯA đóng được — CA Review #6 chỉ rõ đây vẫn là khoảng cách gốc) — `session_nonce` đóng
    đúng 2 vấn đề CỤ THỂ CA nêu (PID-reuse-sau-khi-chết, và tăng cường TTL/rate-limit/hash cho
    credential), nhưng KHÔNG tự nó tạo ra "authenticated application principal" — `pin_secret` vẫn
    là 1 shared credential do "ai đó giữ role `alpha3s_m4_actor_binder`" biết và dùng để pin, chứ
    KHÔNG chứng minh caller-hiện-tại chính là staff đó qua 1 phiên đăng nhập đã xác thực độc lập
    (JWT/session HTTP). Khi Stage 0P wire vào API thật, tầng auth HTTP PHẢI là nơi DUY NHẤT gọi
    `pin_actor` — quyết định kiến trúc này tiếp tục cần CA/PO xác nhận trước activation, KHÔNG phải
    thứ Dev có thể tự đóng ở tầng DB/Stage 0P một mình.
21. **T6-02 KHÔNG đóng hoàn toàn — chỉ bind digest của canonical PLAINTEXT, KHÔNG bind
    ciphertext.** DB vẫn không giữ khóa giải mã (có chủ ý, hỗ trợ key-rotation/DSR
    crypto-shredding), nên không thể xác minh `encrypted_message` GIẢI MÃ RA đúng digest đó. Về lý
    thuyết, 1 caller đã qua được `fetch_message_content` (biết đúng canonical text, có đúng
    `sample_id`/`customer_ref`/`conversation_ref` để tạo AAD hợp lệ) vẫn có thể tự encrypt LẠI cùng
    nội dung bằng 1 nonce khác — DB coi đây là hợp lệ (đúng là cùng nội dung, chỉ khác nonce ngẫu
    nhiên trong AEAD, không phải tấn công thật). Đóng triệt để hơn đòi hỏi thay đổi kiến trúc lớn
    hơn phạm vi 1 correction round (xem giới hạn #16 Correction #6, không đổi).
22. **`pin_secret_hash` dùng pgcrypto `crypt()`/`gen_salt('bf')` (bcrypt) — chưa có chính sách
    rotation định kỳ hay revocation tức thời ngoài rate-limit-khóa-tạm-thời.** Nếu 1 `pin_secret`
    bị lộ, cách duy nhất vô hiệu hóa hiện tại là admin/superuser tự UPDATE lại hash (out-of-band,
    giống provisioning ban đầu) — chưa có hàm SECURITY DEFINER riêng cho "revoke pin_secret ngay
    lập tức" (khác với T3-05 đã có cho approval). Đây là quyết định vận hành thuộc giai đoạn
    production-activation, chưa cấp thiết cho Stage 0P dev/test.
23. Ngưỡng gate T4-05/T5-03/T6-03 (10%/200, `gate_version=ca-review-4-proposed-v1`) — không đổi so
    với Correction #6 giới hạn #19: vẫn là đề xuất CA, CHƯA có PO decision record chính thức; T6-03
    giờ áp dụng chính sách **zero-tolerance** (không dùng tỷ lệ) riêng cho `permanent_failed`
    capture-time, tách biệt hoàn toàn khỏi ngưỡng 10%/200 vẫn áp dụng cho exclusion prediction-time
    (T4-05, không đổi) — 2 cơ chế độc lập, quyết định PO (nếu có) cho 1 cái không tự động áp dụng
    cho cái kia trừ khi PO quyết định rõ.

## 6. Đề nghị

CA review Correction #7 đối chiếu 4 finding `T6-01..T6-04`. Không xin quyền production-data-
access/activation — gate đó vẫn tách riêng theo Design Acceptance §6, xin sau khi Correction #7
được nghiệm thu.
