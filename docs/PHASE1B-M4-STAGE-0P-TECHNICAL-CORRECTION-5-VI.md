---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-5-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #5
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-30
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-5-VI.md (CA, CHANGES_REQUIRED, reviewed_head c7fdbaf2ee17c40b4ba4166552235a6e207c36c0)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #5

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-5-VI.md` — sửa đúng 4 finding `T5-01..T5-04`
(T5-01/02/03 = P1, T5-04 = P2). Phạm vi KHÔNG đổi: dev/test trên branch M4 (worktree
`D:\alpha3s-m4`, KHÔNG checkout trong `D:\alpha3s`), dữ liệu synthetic/test, **KHÔNG**
merge/deploy/production-data-access/activation. Ngưỡng exclusion `10%/200` (T4-05, `gate_version
= ca-review-4-proposed-v1`) tiếp tục ở nguyên trạng CA đề xuất, CHƯA có PO decision record chính
thức — round này không tự ý coi đó là đã duyệt (đúng §4 review #5).

## 1. Mapping 4 finding → sửa

| Finding | Sửa | File |
|---|---|---|
| **T5-01** `require_pinned_actor()` đọc custom GUC (`current_setting`) — bất kỳ session nào cũng tự `set_config('alpha3s.m4_actor_staff_id', '<victim-id>', false)` rồi gọi hàm nghiệp vụ đúng role, mạo danh victim; `pin_actor(staff_id)` đường chính thức cũng chỉ xác nhận ID caller đưa vào tồn tại/active, không xác minh caller THẬT SỰ là staff đó | Bỏ HẲN GUC. Bảng mới `m4_stage0p_actor_credentials` (`staff_id` PK, `pin_secret`, **KHÔNG GRANT cho bất kỳ role nào** — chỉ chạm được qua provisioning ngoài luồng, mô phỏng bước cấp phát vận hành) và `m4_stage0p_actor_session` (`backend_pid` PK — `pg_backend_pid()`, hệ thống tự cấp theo tiến trình backend thật, caller KHÔNG chọn được, khác về bản chất so với GUC mà caller ghi trực tiếp). `pin_actor(staff_id, pin_secret)` đối chiếu `pin_secret` với bảng credentials TRƯỚC khi ghi `(pg_backend_pid(), staff_id)` vào bảng session; `require_pinned_actor` đọc actor theo `backend_pid` của CHÍNH connection đang gọi. Không biết `pin_secret` đúng của staff X → không pin được thành X | `migrations/039_m4_stage0p.sql` §1/§3 (2 bảng mới)/§5d; `app/services/pii/stage0p_control.py:pin_actor` |
| **T5-02** `record_sample()` nhận `p_encrypted_message`/`p_canonical_text_len`/`p_truncated` hoàn toàn từ caller, không đối chiếu với nội dung DB vừa fetch — sau 1 fetch hợp lệ, holder collector vẫn ghi ciphertext tùy ý hoặc canonical length sai dưới message ID hợp lệ | `m4_stage0p_fetch_capability` thêm cột server-derived `fetched_char_len`/`fetched_char_truncated` (tính tại thời điểm `fetch_message_content`, không phải caller khai). `record_sample` bổ sung 3 kiểm tra trước INSERT: (a) `canonical_text_len` phải nằm trong `(0, fetched_char_len]`; (b) nếu DB biết nội dung gốc đã bị cắt thì `p_truncated` bắt buộc `true`; (c) `octet_length(encrypted_message)` phải nằm trong khoảng hợp lý so với `canonical_text_len` (cận AES-GCM-with-versioned-header overhead cố định 30 byte + hệ số UTF-8 1-4 byte/ký tự) — bắt gross mismatch độ dài ciphertext. Giới hạn còn lại khai báo minh bạch ở §5 dưới đây (nội dung ciphertext CHÍNH XÁC vẫn không verify được ở tầng DB) | `migrations/039_m4_stage0p.sql` §3b/§5b/§5c |
| **T5-03** Sau 3 lần fence timeout, candidate thành `permanent_failed` (terminal) nhưng `close_collection()` chỉ chặn `pending`/`retryable_failed` — batch có thể đóng dù có permanent failure, các row này biến mất khỏi corpus/coverage/exclusion numerator/result hash mà không qua gate nào | `close_collection` tái dùng CHÍNH bảng `m4_stage0p_exclusion_gate` (đã có từ T4-05, không mở thêm ngưỡng ngầm định thứ 2) — đếm `permanent_failed`/`excluded` tại capture-time, đối chiếu tỷ lệ `permanent_failed` với `max_exclusion_rate` CÙNG gate, RAISE INSUFFICIENT_DATA nếu vượt. Lưu `capture_excluded_count`/`capture_permanent_failed_count` lên batch row (đưa vào closure evidence). `mark_candidate_outcome` thêm DB-side allowlist cho `p_reason` (4 chuỗi Python thực sự phát ra: `asyncio_wait_for_timeout`/`customer_in_pending_cache`/`pending_check_before_fence`/`pending_recheck_inside_fence`) — không còn nhận reason tùy ý | `migrations/039_m4_stage0p.sql` §5a3 (`mark_candidate_outcome`)/§5c2 (`close_collection`) |
| **T5-04** Bỏ tham số caller đóng được đường giả version, nhưng DB hardcode `'nfc-v1'` còn app giữ `NORMALIZATION_VERSION` riêng — 2 nơi độc lập, đòi hỏi con người "bump cả 2" | Bảng mới `m4_stage0p_normalization_registry` (singleton, seed `nfc-v1`) — nguồn THẬT DUY NHẤT. `write_predictions` đọc `current_version` từ bảng này (thay vì hằng số PL/pgSQL). Python: xoá hẳn `NORMALIZATION_VERSION` module constant, thêm `get_current_normalization_version(conn)` đọc CÙNG bảng — cả DB lẫn Python callers (`lock_batch`/`run_prediction_writer`) đều đọc từ 1 nguồn, đổi version chỉ cần 1 UPDATE (qua migration khi cần), không còn "bump 2 nơi" | `migrations/039_m4_stage0p.sql` §3 (bảng mới)/§5i; `app/services/pii/stage0p_sampling.py`; `app/services/pii/stage0p_prediction.py` |

## 2. Nguyên tắc sửa chung (không đổi so với Correction #1-4, áp dụng đúng khoảng cách CA chỉ ra)

CA chỉ rõ round #4 (T4-01/T4-04) *trông giống* đã đóng nhưng còn khoảng cách cụ thể: T4-01 đổi từ
GUC sang bảng nhưng KHÔNG bind nội dung payload; T4-04 đổi từ tham số caller sang GUC session
nhưng GUC vẫn là thứ caller tự ghi được, không phải "bằng chứng DB tự sở hữu". Round này đóng
đúng 2 khoảng cách đó bằng 1 nguyên tắc chung: **thứ dùng làm bằng chứng phải là thứ DB tự cấp
phát và caller không thể tự tạo ra bằng thao tác thông thường** — `pg_backend_pid()` (hệ điều
hành/Postgres tự gán theo tiến trình kết nối thật) thay cho GUC (session variable bất kỳ ai
`SET`/`set_config` được); `fetched_char_len`/`fetched_char_truncated` do DB tự tính tại thời điểm
fetch (không phải caller khai lại) thay cho việc tin `p_canonical_text_len`/`p_truncated` nguyên
văn. T5-03/T5-04 áp dụng nguyên tắc phụ đã dùng ở các round trước: tái dùng ngưỡng governance đã
có thay vì mở ngưỡng ngầm định mới (T5-03), và gộp 2 nguồn hardcode độc lập thành 1 bảng DB đọc
runtime bởi cả 2 phía (T5-04).

## 3. Bug tự phát hiện trong lúc triển khai (khai báo minh bạch)

1. **`GRANT USAGE ON SCHEMA public` chưa từng được cấp cho bất kỳ role nào trong 10 role M4**
   (kể cả `alpha3s_m4_definer`, owner của mọi hàm SECURITY DEFINER) — migration `024_runtime_db_
   role.sql` (M2, trước M4) revoke toàn bộ quyền mặc định của `PUBLIC` trên schema `public` và chỉ
   cấp lại `USAGE` cho `alpha3s_app`; migration `039_m4_stage0p.sql` (M4, mọi round trước) tạo 10
   role mới nhưng KHÔNG bao giờ cấp `USAGE ON SCHEMA public` cho bất kỳ role nào trong số đó. Trên
   1 DB THỰC SỰ SẠCH (`DROP SCHEMA public CASCADE` rồi `migrate.py up` lại từ đầu — bước reset lần
   này làm KỸ hơn các round trước, vốn chỉ xoá dữ liệu chứ không drop schema), lỗi lộ ra ngay ở lời
   gọi `pin_actor()` đầu tiên: `function m4_stage0p_pin_actor(bigint, text) does not exist` —
   KHÔNG phải lỗi "permission denied" (EXECUTE grant vẫn đúng), mà là lỗi resolve tên đối tượng:
   thiếu `USAGE` trên schema khiến Postgres không tìm thấy hàm/bảng để mà kiểm tra EXECUTE/SELECT.
   Bug này ĐÃ TỒN TẠI từ khi migration 039 được viết lần đầu (không phải do T5-01..04), chỉ chưa
   từng lộ ra vì chưa vòng nào trước đó reset DB thật sự từ `DROP SCHEMA` — luôn chạy tiếp trên 1
   DB đã có `USAGE` được cấp thủ công ngoài migration lúc thiết lập môi trường ban đầu. Sửa: thêm
   `GRANT USAGE ON SCHEMA public TO alpha3s_m4_definer` (ngay sau `CREATE ROLE alpha3s_m4_definer`)
   và 1 câu `GRANT USAGE ON SCHEMA public TO <9 role còn lại>` (ngay sau khối `CREATE ROLE` của
   chúng) vào `039_m4_stage0p.sql` — không đổi mô hình least-privilege (schema USAGE chỉ cho phép
   RESOLVE tên, không thay thế bất kỳ GRANT bảng/hàm/cột nào đã có).
2. **Test harness `_try()` (`permissions_test.py`) chỉ bắt `asyncpg.InsufficientPrivilegeError`,
   không bắt `UndefinedTableError`/`UndefinedFunctionError`** — sau khi sửa mục 1, ma trận
   negative-permission cho `alpha3s_vendor_path` (role bị khoá gần như tuyệt đối, có chủ đích
   KHÔNG có `USAGE` trên `public`) crash thay vì báo DENY, vì thiếu `USAGE` khiến Postgres trả lỗi
   "relation does not exist" thay vì "permission denied" cho role không thấy được object. Không
   phải lỗi sản phẩm — đây CHÍNH LÀ hành vi DENY đúng, thậm chí chặt hơn (object hoàn toàn vô hình
   với role đó); chỉ là helper test chưa tính tới lớp lỗi này. Sửa: `_try()` bắt thêm 2 exception
   class đó, coi là DENY tương đương.
3. **Quên truyền `-e REDIS_URL=redis://alpha3s-m4-redis:6379/0` ở 1 lần chạy `kill_test.py`**
   (đã ghi rõ trong header comment của chính script, do lần chạy trước theo thói quen chỉ truyền
   `DATABASE_URL`) khiến `settings.redis_url` rơi về default không route được tới container Redis
   thật trên network `m4net` → mọi pending-check fail-closed hàng loạt, làm sai lệch 4 assertion về
   "insert giữa chừng"/"aborted_control_off". Không phải lỗi code — xác nhận lại bằng cách chạy
   đúng lệnh trong header comment, PASS sạch 0 FAIL ngay.

## 4. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`; **DB reset từ `DROP SCHEMA public CASCADE` — sạch hơn các round trước, vốn chỉ xoá dữ liệu** — rồi `migrate.py up` lại từ đầu ngay trước loạt chạy cuối)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `DROP SCHEMA public CASCADE` + `CREATE SCHEMA public` + `migrate.py up` (001..039 từ DB rỗng thật sự) | 0 | `OK 039_m4_stage0p`, postcondition PASS ngay lần đầu (sau khi thêm `GRANT USAGE ON SCHEMA public` — xem §3 mục 1) |
| 2 | `m4_stage0p_migration_test.py` | 0 | RESULT: PASS (fresh+idempotent+existing-apply+rollback) — re-apply `migrate.py up` ngay sau (kịch bản rollback dọn sạch schema M4, đúng ý đồ thiết kế) trước khi chạy evidence tiếp theo |
| 3 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS — 393 assertion, 0 FAIL. Ma trận 12 bảng × 12 role, ma trận EXECUTE 15 hàm × 12 role, hardening 15 hàm+trigger; T5-01: `set_config()` trực tiếp với staff có quyền vẫn KHÔNG pin được (không còn đọc GUC); pin sinh tồn đúng qua `SET ROLE` (khoá bởi `pg_backend_pid()` của session, không phải GUC); `actor_credentials`/`actor_session` không role nào SELECT/INSERT trực tiếp được; T5-02: `canonical_text_len` vượt `fetched_char_len` → RAISE; `p_truncated=false` che giấu truncation đã biết → RAISE; ciphertext quá ngắn/quá dài so với canonical length → RAISE; T5-03: `permanent_failed` 100% (1/1) → RAISE INSUFFICIENT_DATA; 5% (1/20) → THÀNH CÔNG, `capture_excluded_count`/`capture_permanent_failed_count` lưu đúng; reason ngoài allowlist → RAISE; T5-04: registry seed đúng `nfc-v1`, `normalization_registry` không role nghiệp vụ nào UPDATE được |
| 4 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — toàn bộ 9 kịch bản REV3 không đổi hành vi sau khi `_pin()` chuyển sang 2 tham số `(staff_id, pin_secret)` — xác nhận T5-01 không phá vỡ timeout/fencing đã đóng ở Correction #2 |
| 5 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J không đổi hành vi sau khi thêm provisioning `pin_secret`) |
| 6 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS — file này insert trực tiếp qua admin/superuser (không qua `record_sample`), nên T5-02 không chạm tới; không gọi `mark_candidate_outcome`/`close_collection`, nên T5-03 không chạm tới; chỉ cần thêm provisioning `pin_secret` cho `_pin()` |
| 7 | `pytest -q` (full) | 0 | **241 passed** (không đổi so với Correction #4 — thay đổi REV6 chỉ ở DB boundary/Python wrapper mỏng, không chạm logic thuần) |
| 8 | `ruff check app/services/pii/ scripts/m4_stage0p_*.py tests/test_m4_*.py` | 0 | All checks passed |
| 9 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` tự xác nhận `capture_enabled=False` trước khi kết thúc |

Cả 4 evidence script chạy TUẦN TỰ trên CÙNG một DB (sau khi re-apply migration do
`migration_test.py` kịch bản rollback dọn sạch), xác nhận không rò rỉ state giữa các lần chạy —
kể cả 3 bảng mới (`actor_credentials`/`actor_session`/`normalization_registry`) và các cột mới
trên `fetch_capability`/`m4_selection_batches`.

## 5. Known limitations (không đổi so với Correction #4 §5, cộng thêm)

16. **T5-02 KHÔNG đóng hoàn toàn — chỉ bind độ dài/truncation, KHÔNG bind nội dung ciphertext
    CHÍNH XÁC.** DB không bao giờ nắm khoá giải mã AES-GCM (có chủ ý — để hỗ trợ key rotation và
    DSR crypto-shredding không cần DB biết plaintext), nên không thể so `encrypted_message` với
    nội dung gốc byte-cho-byte; chỉ có thể kiểm cận độ dài hợp lý (overhead AEAD cố định + hệ số
    UTF-8) và cờ truncation. Một caller vẫn có thể, về lý thuyết, ghi 1 ciphertext HỢP LỆ VỀ ĐỘ DÀI
    nhưng KHÁC nội dung message đã fetch (miễn ciphertext đó đúng AAD/domain của đúng
    customer_ref/conversation_ref/sample_id — collector role không có quyền đọc `encrypted_message`
    khác nên đây không phải lỗ hổng dễ khai thác trong mô hình quyền hiện tại, nhưng về mặt lý
    thuyết không phải "chứng minh payload có nguồn gốc từ message đã fetch" như CA yêu cầu đầy đủ).
    Đóng triệt để đòi hỏi hoặc (a) DB tự thực hiện encrypt trong 1 trusted boundary duy nhất (đổi
    kiến trúc — DB cần biết plaintext, mâu thuẫn với thiết kế "plaintext không bao giờ rời Python
    process" hiện tại), hoặc (b) 1 content digest không cần khoá (vd HMAC nội dung gốc với khoá
    riêng DB giữ) được server tính tại fetch-time và verify tại record-time — đây là thay đổi kiến
    trúc lớn hơn phạm vi 1 correction round, cần CA/PO xác nhận trước khi triển khai.
17. **`m4_stage0p_actor_credentials.pin_secret` lưu dạng TEXT thuần, chưa hash** — mô phỏng bước
    provisioning ngoài luồng (bảng không GRANT cho role nào, chỉ admin/superuser chạm được), nhưng
    nếu Stage 0P wire vào production, `pin_secret` PHẢI được hash (vd bcrypt/argon2) trước khi lưu,
    giống mọi credential khác trong hệ thống (`staff_users.password_hash`) — hiện tại đây vẫn là
    dev/test harness mô phỏng, chưa phải quy trình cấp phát thật.
18. **T5-01 vẫn KHÔNG kết nối với 1 tầng authentication HTTP thật** (giống giới hạn #14 Correction
    #4) — `pin_secret` là 1 shared credential do "ai đó" (admin/actor_binder holder) biết và dùng
    để pin actor, KHÔNG phải chứng minh caller-hiện-tại chính là staff đó qua phiên đăng nhập đã
    xác thực. Khi Stage 0P wire vào API thật, tầng auth HTTP (JWT/session đã xác thực) PHẢI là nơi
    DUY NHẤT gọi `pin_actor` với `pin_secret` tương ứng — quyết định kiến trúc này vẫn cần CA/PO
    xác nhận trước activation, không đổi so với giới hạn đã ghi ở Correction #4.
19. Ngưỡng gate T4-05/T5-03 dùng chung (10%/200, `gate_version=ca-review-4-proposed-v1`) — không
    đổi so với Correction #4 giới hạn #15: vẫn là đề xuất CA, CHƯA có PO decision record chính
    thức; T5-03 giờ áp dụng CÙNG ngưỡng cho `permanent_failed` capture-time, nên quyết định PO
    (nếu thay đổi) sẽ ảnh hưởng CẢ 2 cổng chặn cùng lúc.

## 6. Đề nghị

CA review Correction #5 đối chiếu 4 finding `T5-01..T5-04`. Không xin quyền production-data-
access/activation — gate đó vẫn tách riêng theo Design Acceptance §6, xin sau khi Correction #5
được nghiệm thu.
