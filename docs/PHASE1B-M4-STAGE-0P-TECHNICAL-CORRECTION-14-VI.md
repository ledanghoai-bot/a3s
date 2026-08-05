---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-14-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #14
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-31
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-13-VI.md (CA, CHANGES_REQUIRED, reviewed_head c0609546658faebe0a9fd921213196239726d67a)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #14

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-13-VI.md` — sửa `T13-01` (P1, authorization REV13
chưa buộc canonical digest của nội dung THẬT hoặc các trường ảnh hưởng output như customer_ref/
conversation_ref/truncation — "một authorized collector process có thể... thay raw_content hoặc
AAD-related fields và vẫn yêu cầu signer tạo ciphertext/signature") và `T13-02` (P1, `_replay_seen`
REV13 chỉ là dictionary trong bộ nhớ 1 tiến trình — mất qua restart, không dùng chung giữa nhiều
signer instance) và `T13-03` (P2, semaphore chỉ giới hạn concurrency, không giới hạn tốc độ
request). `T12-01` giữ nguyên KHÔNG đổi (CA đã xác nhận **CLOSED AT DEV/TEST CODE-DESIGN LEVEL**,
exact delta round này không chạm distinct-UID/socket group policy). `T11-01`/pool cancellation
guard cũng KHÔNG đổi. `T9-03` KHÔNG sửa bằng code — CA tiếp tục đóng khung đây là **activation
blocker**. Phạm vi KHÔNG đổi: dev/test trên branch M4 (worktree `D:\alpha3s-m4`, KHÔNG checkout M4
trong `D:\alpha3s`), dữ liệu synthetic/test, **KHÔNG** merge/deploy/production-data-access/
activation.

## 1. Mapping finding → sửa

| Finding | Xử lý | File |
|---|---|---|
| **T13-01** (P1) — payload REV13 chỉ gồm `batch_id\|conversation_id\|message_id\|sample_id\|purpose_code\|txid\|issued\|expires` — CHƯA buộc canonical digest của nội dung THẬT, CHƯA buộc `customer_ref`/`conversation_ref` (dùng trong AAD/transcript), CHƯA có domain/operation tag, nối bằng dấu `\|` KHÔNG unambiguous | `m4_stage0p_fetch_message_content()` TỰ DERIVE `customer_id` từ `m4_stage0p_capture_progress` (KHÔNG còn nhận từ caller — đóng thêm 1 điểm caller-tự-khai, cùng nguyên tắc T4-04/T5-01/T9-02), TỰ TÍNH `canonical_digest_hex` từ CHÍNH canonical text nó vừa tính cho `fetched_canonical_digest` (T4-01/T6-02) — CÙNG 1 giá trị. Payload giờ là 14 trường (domain tag cố định `m4-stage0p-sign-capture-v1` + identity + `customer_ref`/`conversation_ref` + `purpose_code` + `txid` + `canonical_digest_hex` + `char_truncated` + `nonce` + `issued`/`expires`), nối bằng LENGTH-PREFIX (`<số-byte>:<giá-trị>` nối tiếp, không dùng dấu phân cách) — loại bỏ khả năng 1 trường chứa ký tự đặc biệt làm lệch ranh giới. Signer tự canonicalize `raw_content` TRƯỚC, tự tính digest, RỒI MỚI đối chiếu chữ ký — bất kỳ sai lệch nội dung/`customer_ref`/`db_char_truncated` đều làm HMAC không khớp, từ chối TRƯỚC khi mã hóa/ký. `conversation_ref` dùng trong mã hóa/AAD KHÔNG còn đọc từ `req["conversation_ref"]` (trường caller tự khai) — signer TỰ DERIVE `str(conversation_id)` (đã được bind qua chữ ký) | `migrations/039_m4_stage0p.sql` (`m4_stage0p_fetch_message_content`); `app/services/pii/stage0p_signing_service.py` (`_lenpfx_join`, `_verify_signing_authorization`, `_handle_request`) |
| **T13-02** (P1) — `_replay_seen` REV13 là dictionary TRONG BỘ NHỚ của 1 tiến trình — restart signer xóa toàn bộ state, 2 signer instance có 2 cache độc lập — KHÔNG phải one-time semantics THẬT SỰ | Token giờ mang 1 `nonce` ngẫu nhiên (`gen_random_uuid()`, 128-bit) — buộc VÀO payload (chống giả mạo) VÀ đưa RIÊNG vào token (ngoài payload). Thay `_replay_seen` bằng Redis `SET NX PX` (`_consume_nonce_once()`) — TTL Redis = thời gian còn lại của token + biên an toàn, dùng CHUNG `settings.redis_url` (hạ tầng dùng chung, không phải secret) — state chống replay giờ BỀN VỮNG qua restart signer VÀ dùng CHUNG giữa NHIỀU signer instance. Redis lỗi/timeout → FAIL CLOSED. Thứ tự bắt buộc: verify chữ ký+digest → tiêu thụ nonce qua Redis (atomic) → ký/mã hóa SAU CÙNG | `app/services/pii/stage0p_signing_service.py` (`_consume_nonce_once`, `_handle_request`, `main` +đọc `REDIS_URL`) |
| **T13-03** (P2) — `asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)` REV13 CHỈ giới hạn số request ĐỒNG THỜI, không giới hạn TỐC ĐỘ request tuần tự | `_check_rate_limit()` — fixed-window (10s, tối đa 40 request/cửa sổ) ÁP DỤNG SAU peer-UID check (chỉ tính traffic của peer đã xác thực), TRƯỚC khi đọc bất kỳ frame nào — vượt hạn bị từ chối ngay (không có response), tự phục hồi khi cửa sổ tiếp theo bắt đầu | `app/services/pii/stage0p_signing_service.py` (`_check_rate_limit`, `_handle_conn`) |
| **T9-03** (P1 activation blocker) — không đổi từ Correction #13 | **KHÔNG sửa bằng code** — CA tiếp tục xác nhận đây là activation blocker. Khai báo lại known limitation, xem §6 | — (không có thay đổi code) |

## 2. Nguyên tắc sửa chung

T13-01 mở rộng nguyên tắc T10-01/T12-02 ("bên xác minh phải tự tính hoặc tự xác minh mọi trường
dùng để ra quyết định tin cậy, không dựa vào actor tự khai") sang TOÀN BỘ tập hợp trường ảnh hưởng
đến ciphertext/transcript cuối cùng, không chỉ digest plaintext đơn thuần: T12-02 đã bind identity
(batch/conversation/message/sample/purpose/txid), nhưng CA chỉ ra đúng — content digest và các
trường AAD-affecting (`customer_ref`, truncation claim) vẫn là khoảng trống. Bài học: khi thiết kế
1 lớp "authorization trước hành động", phải liệt kê ĐẦY ĐỦ tập hợp input ảnh hưởng đến OUTPUT của
hành động đó (ở đây: ciphertext + AAD + transcript), không chỉ các trường "định danh" bề mặt.

T13-02 tiếp tục nguyên tắc "cleanup/state bảo vệ phải thật sự bảo vệ được, không chỉ tuyên bố bảo
vệ" (T9-01/T10-03) — áp dụng cho state CHỐNG REPLAY: 1 cache chỉ tồn tại trong phạm vi 1 tiến trình
không đáp ứng được ngữ nghĩa "one-time" khi hệ thống có thể có NHIỀU tiến trình signer (khả năng
mở rộng ngang) hoặc tiến trình có thể RESTART (khả năng phục hồi sau sự cố) — 2 thuộc tính vận
hành cơ bản mà bất kỳ dịch vụ dev/test nghiêm túc nào cũng cần. Chuyển sang Redis (hạ tầng CHIA SẺ,
BỀN VỮNG) đóng đúng khoảng cách này mà không cần thay đổi kiến trúc signer.

## 3. Bug tự phát hiện trong lúc triển khai (khai báo minh bạch)

1. **`m4_stage0p_capture_progress` chưa được seed cho các message test tự tạo trực tiếp (bỏ qua
   `run_collector`/`seed_capture_progress`)** — sau khi `fetch_message_content()` đổi sang TỰ
   DERIVE `customer_id` từ `capture_progress` (T13-01), MỌI lời gọi hàm này giờ đòi hỏi 1 row
   `capture_progress` tồn tại sẵn cho đúng `(batch_id, conversation_id, message_id)`. Cả
   `m4_stage0p_kill_test.py` (kịch bản `[8]` DB write hang — gọi `_run_fenced_unit` TRỰC TIẾP, bỏ
   qua `run_collector`) lẫn `m4_stage0p_permissions_test.py` (4 vị trí tự tạo message/batch riêng
   cho kịch bản adversarial cô lập) đều gặp `RaiseError: khong tim thay capture_progress` ngay lần
   chạy đầu — SAU KHI đã seed đúng 1 row tối thiểu `(batch_id, conversation_id, message_id,
   customer_id)` qua `admin` (superuser) TRƯỚC mỗi lời gọi fetch trực tiếp, cả 2 script chạy đúng
   trở lại. Đây LÀ hành vi ĐÚNG Ý ĐỒ (phản ánh đúng bất biến thật của hệ thống — sản xuất luôn seed
   trước khi fetch), không phải bug logic — chỉ là điểm cần đồng bộ ở CÁC vị trí test bỏ qua luồng
   đầy đủ để cô lập 1 kịch bản cụ thể.
2. **`_raw_request()` (evidence script) chưa xử lý `ConnectionResetError` xảy ra NGAY TRONG lúc
   GHI request** — kịch bản T13-03 mới (`[20]`, burst 60 request đồng thời vượt ngân sách rate-
   limit 40/10s) làm lộ: khi server đóng kết nối do rate-limit NGAY SAU accept (trước khi client
   kịp ghi xong request), `writer.drain()` phía client ném `ConnectionResetError` — trước đó
   `_raw_request()` chỉ bọc try/except quanh bước ĐỌC response (mô phỏng đúng theo các kịch bản
   REV13 cũ, vốn luôn ghi xong request trước khi bị từ chối). Sửa: bọc thêm bước GHI, coi
   `ConnectionResetError`/`BrokenPipeError`/`OSError` lúc ghi là "không có response" (cùng ý nghĩa
   với bị từ chối sớm), không phải lỗi test.

## 4. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`; DB reset từ `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` rồi `migrate.py up` lại từ đầu ngay trước loạt chạy cuối)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` + `migrate.py up` (001..039 từ trạng thái sạch thật sự) | 0 | `OK 039_m4_stage0p`, postcondition PASS ngay lần đầu — round này không thêm bảng/hàm mới, chỉ sửa thân `fetch_message_content` |
| 2 | `m4_stage0p_migration_test.py` | 0 | RESULT: PASS (fresh+idempotent+existing-apply+rollback atomic) — re-apply `migrate.py up` ngay sau |
| 3 | `m4_stage0p_pool_test.py` | 0 | RESULT: PASS — 16 nhóm kịch bản, không đổi (round này không chạm pool wrapper) |
| 4 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — 9 kịch bản REV3 không đổi hành vi; kịch bản `[8]` seed thêm 1 row `capture_progress` (xem §3 bug 1); round-trip THẬT qua token DB-issued 14-trường + Redis nonce consume |
| 5 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J) — cùng round-trip qua token/Redis THẬT |
| 6 | `m4_stage0p_signing_service_test.py` | 0 | RESULT: PASS — **20 kịch bản** (giữ nguyên `[1]`-`[9]` T11-02/T12-01/T12-02 + MỚI `[10]`-`[12]` T13-01 tampered raw_content/customer_ref/db_char_truncated + `[13]`-`[17]` T12-02 renumbered + MỚI `[18]` T13-02 replay SAU signer restart (Redis THẬT giữ state qua process mới) + MỚI `[19]` T13-02 2 signer instance khác nhau nhận CÙNG token đồng thời → ĐÚNG 1 thành công + MỚI `[20]` T13-03 burst 60 request vượt ngân sách 40/10s → 1 phần bị từ chối, tự phục hồi sau cửa sổ) |
| 7 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS — 520 assertion; 4 vị trí seed thêm `capture_progress` (xem §3 bug 1) |
| 8 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS — không đổi (không chạm collector/signing path) |
| 9 | `pytest -q` (full) | 0 | **241 passed** (không đổi — T13-01/T13-02/T13-03 chỉ chạm signing-service/DB function, không chạm logic thuần đã có unit test) |
| 10 | `ruff check app/services/pii/ app/config.py scripts/m4_stage0p_*.py scripts/_stage0p_signing_service_helper.py scripts/_stage0p_signing_client_as_uid_helper.py tests/test_m4_*.py` | 0 | All checks passed ngay lần đầu, không cần `--fix` |
| 11 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` tự xác nhận `capture_enabled=False` trước khi kết thúc |

Không có sự cố hạ tầng (Docker/DB) nào xảy ra trong round này.

## 5. Chưa/không cần sửa lại (theo đúng phạm vi CA giới hạn ở §6/Resubmission Review #13)

- `T12-01` (2 UID hệ điều hành thật, socket group policy) — CA xác nhận **CLOSED AT DEV/TEST
  CODE-DESIGN LEVEL**, exact delta round này KHÔNG chạm logic đó (`ensure_service_accounts()`,
  `_validate_socket_directory()` với `shared_gid` giữ nguyên).
- `T11-01` (pool cancellation guard, `except BaseException`) — không đổi.

## 6. Known limitations (không đổi so với Correction #13 §6, cộng thêm)

30-37. Không đổi nội dung so với Correction #13 (T8-02 vẫn HMAC đối xứng cần nâng KMS/HSM; T9-01/
    T10-03 chỉ đóng đúng lớp truy cập qua `pinned_actor_session()`; T9-03 vẫn activation blocker;
    ngưỡng gate T4-05/T6-03 vẫn chờ PO decision record; signing service vẫn 2 UID CÙNG host/kernel/
    namespace, không phải container/VM tách biệt thật; nonce-consumption cache trong-bộ-nhớ REV13
    — MỤC NÀY NAY ĐÃ ĐÓNG bởi T13-02 round này, không còn là giới hạn).
38. **MỚI — Redis dùng cho tiêu thụ nonce (T13-02) là 1 INSTANCE DÙNG CHUNG, KHÔNG CÓ AUTHENTICATION/
    TLS trong mô hình dev/test hiện tại** (cùng instance mọi service khác trong `docker-compose`
    dùng, kết nối plaintext nội bộ network Docker) — phù hợp phạm vi dev/test 1 host, nhưng trước
    production cần: Redis AUTH/ACL riêng cho signing service (không dùng chung credential với các
    dịch vụ khác), TLS nếu Redis không cùng host vật lý/network namespace tin cậy, và xem xét
    Redis Cluster/Sentinel nếu cần khả năng chịu lỗi (hiện là single point of failure cho nonce
    consumption — Redis down đồng nghĩa signing service fail-closed hoàn toàn, đúng thiết kế
    nhưng là 1 đánh đổi availability cần ghi nhận).
39. **MỚI — rate-limit budget T13-03 là GLOBAL cho 1 signer instance (không phân biệt theo request
    identity/scope cụ thể ngoài peer-UID)** — trong mô hình dev/test hiện tại chỉ có 1 collector
    hợp lệ nên "global" và "per-peer" là tương đương, nhưng nếu tương lai có NHIỀU collector hợp
    lệ dùng chung 1 signer (vd nhiều worker), ngân sách 40/10s sẽ bị CHIA SẺ giữa tất cả — cần
    ngân sách per-identity thật sự (vd theo `customer_ref`/batch) nếu mô hình đa-collector được
    triển khai.

## 7. Đề nghị

CA review Correction #14 đối chiếu `T13-01` (payload 14 trường length-prefix, buộc canonical
digest + customer_ref/conversation_ref + domain tag, signer tự derive conversation_ref thay vì tin
request, 4 kịch bản tampered-field mới `[10]`-`[12]` + `[9]`), `T13-02` (nonce ngẫu nhiên + Redis
`SET NX PX` dùng chung/bền vững qua restart, 2 kịch bản mới `[18]` replay-sau-restart và `[19]`
2-instance-đồng-thời), và `T13-03` (fixed-window 40/10s, kịch bản `[20]` burst-vượt-ngân-sách +
tự-phục-hồi). `T12-01`/`T11-01` giữ nguyên theo đúng xác nhận CLOSED của CA. `T9-03` giữ nguyên
trạng activation blocker theo đúng khung CA đã đặt — không xin đóng finding này round này. Không
xin quyền production-data-access/activation — gate đó vẫn tách riêng theo Design Acceptance §6.
