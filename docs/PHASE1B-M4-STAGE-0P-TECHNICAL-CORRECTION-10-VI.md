---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-10-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #10
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-30
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-9-VI.md (CA, CHANGES_REQUIRED, reviewed_head 7ceb9c129ddecf4d14d5f9dde87fa2450468a83a)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #10

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-9-VI.md` — sửa `T9-01` (P1, race giữa cleanup và
release trong pool wrapper) và `T9-02` (P1, `business_role` không allowlist) bằng code; triển
khai `T8-02` theo quyết định kiến trúc CA đã chốt ở Review #9 §4 — **Hướng 3 (HMAC interim) cho
dev/test**, với đầy đủ 7 điều kiện CA liệt kê. `T9-03` (identity/KMS production) KHÔNG sửa bằng
code — CA đã đóng khung đây là **activation blocker**, không phải finding chờ code fix; giữ
nguyên trạng thái known limitation, khai báo lại rõ ràng ở §6. Phạm vi KHÔNG đổi: dev/test trên
branch M4 (worktree `D:\alpha3s-m4`, KHÔNG checkout M4 trong `D:\alpha3s`), dữ liệu synthetic/
test, **KHÔNG** merge/deploy/production-data-access/activation. Ngưỡng exclusion `10%/200`
(T4-05) tiếp tục ở nguyên trạng CA đề xuất, CHƯA có PO decision record chính thức.

## 1. Mapping finding → sửa

| Finding | Xử lý | File |
|---|---|---|
| **T9-01** (P1) — `_PinnedSession.__aexit__()` REV9 bọc cleanup bằng `asyncio.shield()` MỚI mỗi lần chạy; nếu outer task nhận cancellation THÊM trong lúc đang `await shield(...)`, chính await đó ném `CancelledError` (đúng ngữ nghĩa `shield` — chỉ bảo vệ inner task, không bảo vệ outer await khỏi bị hủy) trong khi cleanup task vẫn chạy nền — nhánh `except CancelledError: pass` đi thẳng tới `finally: pool.release(conn)`, trả connection về pool TRƯỚC KHI cleanup thật sự xong | `__aexit__` tạo 1 `asyncio.Task` cleanup TƯỜNG MINH (`_cleanup_connection`, không phải coroutine bọc lại mỗi lần shield); LẶP LẠI `await asyncio.wait_for(asyncio.shield(cleanup_task), timeout=remaining)` cho tới khi `cleanup_task.done()` là THẬT — 1 lần cancel THÊM chỉ làm vòng lặp thử lại (cleanup_task KHÔNG bị hủy, KHÔNG bị tạo lại), không bao giờ cho phép tiến tới `release()` sớm. Deadline backstop `_CLEANUP_MAX_WAIT_SECONDS=10.0`: nếu vượt quá, gọi `conn.terminate()` (đóng VẬT LÝ ngay lập tức) rồi discard thay vì release bình thường. Nếu `cleanup_task` tự bị lỗi (SQL/network fail giữa chừng), cũng terminate+discard — không bao giờ trả 1 connection có thể ở trạng thái session/role không xác định về pool | `app/services/pii/stage0p_pool.py` (`_PinnedSession.__aexit__`, `_cleanup_connection`, `_release_or_discard`, mới) |
| **T9-02** (P1) — `business_role: str` REV9 nội suy trực tiếp vào `SET ROLE {business_role}` — không allowlist, không quote identifier, "gọi wrapper" trở thành role-selection authority | `business_role` giờ PHẢI là 1 thành viên enum `Stage0PBusinessRole` — CHỈ liệt kê ĐÚNG 4 role thật sự gọi `m4_stage0p_require_pinned_actor()` bên trong (rà soát trực tiếp 8 lời gọi trong migration 039: `alpha3s_m4_control_plane`/`alpha3s_m4_approval_recorder`/`alpha3s_m4_sample_reviewer_api`/`alpha3s_m4_sample_evaluator` — `alpha3s_m4_sample_collector` KHÔNG nằm trong danh sách vì `record_sample`/`fetch_message_content` không đòi hỏi pinned actor, chỉ đòi capability one-time nonce T4-01). Truyền giá trị khác `TypeError` NGAY tại `pinned_actor_session()`, TRƯỚC `pool.acquire()`/bất kỳ SQL nào. Giá trị enum còn được quote identifier an toàn (double-quote + escape) trước khi vào `SET ROLE` — phòng thủ thêm dù enum đã loại trừ injection từ nguồn | `app/services/pii/stage0p_pool.py` (`Stage0PBusinessRole`, `_quote_role_ident`) |
| **T8-02** (P1) — CA chốt Hướng 3 (HMAC interim) cho dev/test, với 7 điều kiện cụ thể (§4 Review #9); production phải nâng lên KMS/HSM asymmetric | Triển khai ĐẦY ĐỦ — xem §2 nguyên tắc + §3 ánh xạ 7 điều kiện. Boundary ký DUY NHẤT `crypto.py:sign_capture()` (tự encrypt + xây + ký transcript — collector KHÔNG còn gọi `encrypt_sample_value()` riêng lẻ); bảng mới `m4_stage0p_transcript_signing_keys` (SELECT CHỈ cho `alpha3s_m4_definer`); `m4_stage0p_record_sample()` verify HMAC + đối chiếu TOÀN BỘ trường transcript (identity/txid/digest/AEAD algorithm+key_version/AAD digest/purpose/thời hạn) TRƯỚC khi tiêu thụ capability | `app/services/pii/crypto.py` (`sign_capture`, mới); `app/services/pii/stage0p_sampling.py` (`_run_fenced_unit`); `migrations/039_m4_stage0p.sql` §3b2 (bảng mới)/§5c (`record_sample`) |
| **T9-03** (P1 activation blocker) — `staff_id`/`pin_secret` vẫn do caller truyền, chưa có HTTP/JWT identity binding | **KHÔNG sửa bằng code** — CA xác nhận đây là activation blocker (chỉ được giữ trong synthetic dev/test), không phải finding chờ code fix round này. Khai báo lại known limitation, xem §6 | — (không có thay đổi code) |

## 2. Nguyên tắc sửa chung

T9-01 tiếp tục nguyên tắc "cleanup phải thật sự bảo vệ được resource nó đang dọn, không chỉ tuyên
bố bảo vệ" — 1 `asyncio.shield()` mới mỗi lần thử lại KHÔNG đủ, vì nó chỉ bảo vệ inner task khỏi
CHÍNH lần shield đó bị hủy, không bảo vệ được "outer đã bị hủy ĐÚNG lúc đang chờ shield". Chỉ 1
Task cleanup TƯỜNG MINH, sống xuyên suốt toàn bộ vòng lặp chờ, mới đảm bảo được "release() không
bao giờ chạy trước khi cleanup task báo done()".

T9-02 tiếp tục nguyên tắc "1 tham số nhận giá trị từ caller không được trở thành authority chọn
hành vi đặc quyền" (cùng nguyên tắc T4-04/T5-01 áp dụng cho actor identity) — áp dụng sang lựa
chọn ROLE: allowlist bằng kiểu dữ liệu (enum) mạnh hơn allowlist bằng runtime check (dễ quên/dễ
bypass), vì Python từ chối truyền giá trị sai NGAY tại lúc gọi, không cần logic kiểm tra riêng có
thể có lỗ hổng.

T8-02 tiếp tục nguyên tắc T6-02 (digest binding) nhưng nâng 1 bậc: T6-02 bind PLAINTEXT identity
(canonical digest) — không ngăn được actor thay CIPHERTEXT bằng 1 bản mã hợp lệ khác cùng plaintext
digest bề ngoài (vì actor tự tính digest, tự khai báo). T8-02 bind CIPHERTEXT thật sự bằng 1 chữ
ký mà actor giữ role `alpha3s_m4_sample_collector` KHÔNG có khả năng tự tạo (không đọc được khoá
HMAC) — ciphertext-substitution giờ làm `ciphertext_digest` trong transcript không khớp
`digest(p_encrypted_message)`, bị từ chối dù chữ ký của transcript GỐC vẫn hợp lệ.

## 3. T8-02 — ánh xạ 7 điều kiện CA (Review #9 §4) → triển khai thực tế

| # | Điều kiện CA | Triển khai |
|---|---|---|
| 1 | Signer tách khỏi code path có thể truyền arbitrary ciphertext | `sign_capture()` (`crypto.py`) là boundary DUY NHẤT — tự gọi `encrypt_sample_value()` NGAY BÊN TRONG, không nhận ciphertext làm tham số từ caller. Collector (`stage0p_sampling.py:_run_fenced_unit`) không còn gọi `encrypt_sample_value()` trực tiếp — chỉ còn đường `sign_capture()` |
| 2 | Signer tự thực hiện/kiểm soát canonicalize + encrypt rồi mới ký | `sign_capture()` nhận `plaintext_canonical` (đã qua `_truncate(nfc(...))` ở caller — cùng thuật toán T6-02 đã kiểm chứng), tự gọi encrypt, tự tính `ciphertext_digest` từ CHÍNH ciphertext nó vừa tạo, rồi mới ký transcript chứa digest đó |
| 3 | HMAC key không cấp cho collector DB role/app worker thường/log/fixture committed/client | Khoá (`m4_transcript_hmac_key_b64`) là secret app-level (cùng mô hình `m4_sample_key_b64`) — KHÔNG bao giờ vào DB dưới dạng caller-accessible; bản sao trong `m4_stage0p_transcript_signing_keys` SELECT CHỈ cho `alpha3s_m4_definer` (xác nhận bằng postcondition + evidence: `alpha3s_m4_sample_collector`/`alpha3s_app`/`public`/`alpha3s_vendor_path` đều KHÔNG SELECT được) |
| 4 | DB verifier đọc key qua restricted definer boundary; key_version trong transcript | `record_sample()` (SECURITY DEFINER, owner `alpha3s_m4_definer`) đọc `hmac_key` qua `SELECT ... WHERE key_version = p_key_version AND retired_at IS NULL` — chạy với quyền OWNER bất kể role gọi là gì. `key_version` là trường bắt buộc trong transcript, đối chiếu với tham số `p_key_version` |
| 5 | Canonical JSON/binary encoding deterministic | `json.dumps(fields, sort_keys=True, separators=(",",":"), ensure_ascii=True)` — cùng dict luôn ra cùng chuỗi byte; DB verify HMAC trên CHÍNH `p_transcript` (bytea) nhận được, không tái tạo lại chuỗi |
| 6 | Transcript bind đầy đủ field CA liệt kê + issued-at/expiry + one-time nonce | Transcript gồm: `batch_id`/`conversation_id`/`message_id`/`sample_id` (identity); `txid` (one-time capability nonce/transaction identity — dùng lại `txid_current()` của CHÍNH transaction Python đang mở, record_sample đối chiếu lại `txid_current()` lúc verify); `canonical_digest`/`canonical_len`/`truncated`; `ciphertext_digest`; `aead_algorithm`+`key_version`; `aad_digest` (DB tự tái tạo AAD từ `customer_id`/`conversation_id`/`sample_id` THẬT rồi so sánh digest, không nhận AAD gốc); `purpose_code`; `issued_at`/`expires_at` (TTL 60s, dung sai clock-skew 5s — xem §4 bug tự phát hiện) |
| 7 | Consume capability + persist sample atomic sau verification | Toàn bộ block verify transcript (chữ ký/JSON/thời hạn/txid/identity/digest/algorithm) nằm NGAY ĐẦU `record_sample()`, TRƯỚC `DELETE FROM m4_stage0p_fetch_capability` — transcript sai thì capability KHÔNG bị tiêu thụ (giữ được cho retry hợp lệ); transcript đúng thì consume capability + INSERT sample + audit đều trong CÙNG 1 lời gọi hàm SECURITY DEFINER, atomic theo transaction Postgres |

**Adversarial test bắt buộc theo CA (Review #9 §4)** — cả 8 kịch bản đều có trong
`m4_stage0p_permissions_test.py` (mục `== T8-02: ... ==`): thiếu chữ ký/transcript; chữ ký sai (1
byte); ciphertext-substitution (digest plaintext thật + ciphertext giả cùng AEAD-length-hợp-lệ);
replay (dùng lại transcript+signature cũ cho message khác — bắt bởi txid không khớp); transcript
hết hạn; key_version không tồn tại; cross-message; cross-batch; cross-sample; AAD bị sửa (aad_digest
của customer_ref khác) — tất cả đều RAISE đúng, xác nhận bằng exact-match trên message lỗi.

## 4. Bug tự phát hiện trong lúc triển khai (khai báo minh bạch)

1. **Clock skew giữa container `alpha3s-m4-test` (ký transcript) và `alpha3s-m4-db` (verify)** —
   kiểm tra ban đầu `issued_at > now()` KHÔNG dung sai làm nhiều test RAISE sai lý do ("issued_at
   trong tương lai" thay vì lý do đang test), phát hiện qua traceback thực tế khi chạy evidence.
   Đây là hiện tượng THẬT (2 container riêng, dù cùng host vẫn có thể lệch vài chục ms) — KHÔNG
   phải chỉ vấn đề test, production cũng cần dung sai này nếu signer/verifier chạy trên host/
   container khác nhau. Sửa: thêm dung sai 5 giây (`now() + interval '5 seconds'`).
2. **`m4_stage0p_pool_test.py` kịch bản [7] (T9-01): 2 lần assertion sai do hiểu sai ngữ nghĩa
   cancellation** — (a) mong đợi `task7` ném `CancelledError` khi bị `cancel()` lặp lại, nhưng
   toàn bộ các lần cancel đó rơi vào `__aexit__` (thân `async with` đã kết thúc BÌNH THƯỜNG trước
   đó — đúng ý đồ T9-01 là bảo vệ cleanup, không phải bảo vệ thân block), nên task hoàn tất bình
   thường (không lỗi) — sửa expectation, không sửa code sản phẩm (hành vi implementation là ĐÚNG
   theo yêu cầu CA "không được release sớm dù bị cancel bao nhiêu lần"); (b) đọc `owner` của actor
   B SAU KHI task B đã thoát `async with` của chính nó — tại thời điểm đó B đã tự unpin, luôn đọc
   ra `None` — sửa: đọc owner NGAY TRONG block, trước khi wrapper tự cleanup.
3. **2 kịch bản adversarial T8-02 ([b] chữ ký sai, [c] ciphertext-substitution) tự sinh 2 UUID
   độc lập cho `sample_id`** (1 lần khi ký transcript, 1 lần khi gọi `record_sample` — do gọi
   `str(uuid.uuid4())` 2 lần riêng biệt thay vì 1 biến dùng chung) — [c] thất bại rõ ràng (RAISE
   sai lý do — "khong khop identity" thay vì "ciphertext_digest"); [b] tình cờ vẫn PASS vì chữ ký
   sai bị bắt trước khi tới bước đối chiếu identity, nhưng lý luận test không đúng ý đồ. Sửa: dùng
   1 biến `sample_id` chung cho cả transcript lẫn tham số gọi hàm ở cả 2 kịch bản.
4. Ruff: 2 import-block chưa sort đúng (`kill_test.py`, `sampling_test.py`) sau khi thêm import
   `TRANSCRIPT_KEY_VERSION` — sửa theo gợi ý `ruff`.

## 5. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`; Docker Desktop restart giữa phiên làm việc — containers `docker start` lại, không mất dữ liệu do reset lại từ đầu ngay sau; DB reset từ `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` rồi `migrate.py up` lại từ đầu ngay trước loạt chạy cuối)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` + `migrate.py up` (001..039 từ trạng thái sạch thật sự) | 0 | `OK 039_m4_stage0p`, postcondition PASS ngay lần đầu (bao gồm check MỚI cho `m4_stage0p_transcript_signing_keys` — table tồn tại, `public`/`alpha3s_m4_sample_collector`/`alpha3s_app`/`alpha3s_vendor_path` không SELECT được, `alpha3s_m4_definer` CÓ SELECT) |
| 2 | `m4_stage0p_migration_test.py` | 0 | RESULT: PASS (fresh+idempotent+existing-apply+rollback) — re-apply `migrate.py up` ngay sau |
| 3 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS, **512 PASS/0 FAIL**. Thêm: ma trận EXECUTE 11-tham-số `record_sample`; adversarial T9-... không áp dụng ở đây (T9 thuộc pool_test.py); mảng T8-02 đầy đủ 10 kịch bản (§3) |
| 4 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — 9 kịch bản REV3 không đổi hành vi (collector thật dùng `sign_capture()` qua toàn bộ pipeline, xác nhận không phá vỡ luồng kill-switch) |
| 5 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J — collector thật ghi sample qua `sign_capture()` thành công trong kịch bản race [G] và các kịch bản khác) |
| 6 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS — không đổi (không gọi `record_sample`, seed trực tiếp bằng SQL) |
| 7 | `m4_stage0p_pool_test.py` | 0 | RESULT: PASS — 9 nhóm kịch bản (giữ nguyên [1]-[6] Correction #9 + MỚI [7] T9-01 cleanup bị block thật + cancel lặp lại, [8] T9-01 cleanup thất bại → discard, [9] T9-02 business_role allowlist) |
| 8 | `pytest -q` (full) | 0 | **241 passed** (không đổi — T9-01/T9-02/T8-02 chỉ chạm DB boundary/pool wrapper/crypto signing, không chạm logic thuần đã có unit test) |
| 9 | `ruff check app/services/pii/ app/config.py scripts/m4_stage0p_*.py tests/test_m4_*.py` | 0 | All checks passed (sau khi sửa 2 import-sort, xem §4 mục 4) |
| 10 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` tự xác nhận `capture_enabled=False` trước khi kết thúc |

**Sự cố hạ tầng giữa phiên làm việc**: Docker Desktop mất kết nối daemon giữa lúc chạy evidence
(`failed to connect to the docker API ...`) — TẤT CẢ container (kể cả ngoài phạm vi M4) bị dừng
khi daemon phục hồi. Xác nhận qua `docker ps -a` (mọi container ở trạng thái `Exited`), khởi động
lại bằng `docker start alpha3s-m4-db alpha3s-m4-redis alpha3s-m4-test`, reset DB/Redis THẬT SỰ
SẠCH rồi chạy lại TOÀN BỘ evidence từ đầu (không tin vào kết quả PASS trước sự cố). Đây là hiện
tượng CLAUDE.md mục 6 đã ghi nhận (Docker Desktop trên máy dev có thể bất ổn) — không phải lỗi
logic code, tự phục hồi sau restart.

## 6. Known limitations (không đổi so với Correction #9 §6, cộng thêm)

30. **T8-02 đóng ở mức Hướng 3 (HMAC interim) — KHÔNG đủ cho production**, đúng quyết định CA
    Review #9 §4. Khoá đối xứng — bất kỳ ai đọc được `m4_transcript_hmac_key_b64`/bản sao trong
    `m4_stage0p_transcript_signing_keys` đều giả mạo được transcript; không có non-repudiation.
    TRƯỚC production-data-access/activation PHẢI chuyển sang chữ ký bất đối xứng (Ed25519/tương
    đương) với private key trong KMS/HSM/Vault Transit — CA đã nêu rõ việc đổi DB image để dùng
    `pgsodium` CHƯA được duyệt trong Review #9, cần trình migration/rollback plan riêng nếu chọn
    hướng đó.
31. **T9-01 đóng đúng lớp truy cập đi qua `pinned_actor_session()`** — nếu code tương lai bypass
    wrapper (tự `pool.acquire()`/`pool.release()` trực tiếp, như kịch bản đối chứng [6a]/[6b] ở
    Correction #9), lỗ hổng quay lại. Không đổi so với giới hạn #27 Correction #9.
32. **T9-03 (P1 activation blocker) — CHƯA đóng, đúng theo khung CA đặt ở Review #9**: `staff_id`/
    `pin_secret` vẫn do caller truyền trực tiếp, KHÔNG derive từ authenticated principal/JWT/
    session. CA cho phép giữ cơ chế này CHỈ trong synthetic dev/test để hoàn thành Stage 0P
    implementation — KHÔNG được coi là production-closed. Trước production activation: (a) staff
    identity phải derive từ principal đã xác thực, (b) request/caller không được tự chọn staff ID,
    (c) pool wrapper phải nhận verified principal context thay vì raw pin secret, (d) credential
    provisioning/rotation/revocation/audit cần operational design riêng. Đây là khoảng cách kiến
    trúc CHUNG với T8-02's Hướng 1 (đều cần lớp identity/KMS thật trước activation) — nên được
    thiết kế CÙNG LÚC khi Stage 0P nối vào 1 service HTTP thật.
33. Ngưỡng gate T4-05/T6-03 (10%/200, `gate_version=ca-review-4-proposed-v1`) — không đổi so với
    Correction #9 giới hạn #29: vẫn là đề xuất CA, CHƯA có PO decision record chính thức.

## 7. Đề nghị

CA review Correction #10 đối chiếu `T9-01`/`T9-02` (sửa bằng code, cleanup/cancellation race +
role allowlist) và `T8-02` (triển khai đầy đủ Hướng 3 theo quyết định CA Review #9 §4, 7/7 điều
kiện + 8/8 adversarial test). `T9-03` giữ nguyên trạng activation blocker theo đúng khung CA đã
đặt — không xin đóng finding này round này. Không xin quyền production-data-access/activation —
gate đó vẫn tách riêng theo Design Acceptance §6.
