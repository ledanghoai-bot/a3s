---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-13-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #13
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-31
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-12-VI.md (CA, CHANGES_REQUIRED, reviewed_head 6078e79d27bdc9ca36026ff3967204b94a37c5a6)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #13

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-12-VI.md` — sửa `T12-01` (P1, peer-UID check REV12
chỉ so sánh với `os.getuid()` của CHÍNH signing service, nên "cùng UID với signer" luôn tự động
đúng — CA: "signer vẫn là oracle cho mọi process cùng UID") và `T12-02` (P1, request chưa ràng
buộc với authority/scope cụ thể — signer ký bất kỳ request nào qua được UID check). `T11-01` giữ
nguyên KHÔNG đổi (CA đã xác nhận **CLOSED**, exact delta round này không chạm). Toàn bộ hardening
filesystem/frame/timeout của T11-02 (private directory, symlink rejection, socket mode, frame/
concurrency limit) **giữ nguyên, không làm lại** — CA đã liệt kê rõ là "được chấp nhận, Correction
kế tiếp không cần làm lại". `T9-03` KHÔNG sửa bằng code — CA tiếp tục đóng khung đây là **activation
blocker**. Phạm vi KHÔNG đổi: dev/test trên branch M4 (worktree `D:\alpha3s-m4`, KHÔNG checkout M4
trong `D:\alpha3s`), dữ liệu synthetic/test, **KHÔNG** merge/deploy/production-data-access/
activation. Ngưỡng exclusion `10%/200` (T4-05) tiếp tục ở nguyên trạng CA đề xuất.

## 1. Mapping finding → sửa

| Finding | Xử lý | File |
|---|---|---|
| **T12-01** (P1) — `_allowed_uid()` REV12 mặc định `os.getuid()` của CHÍNH tiến trình signing service — vì collector và service REV12 chạy CÙNG uid trong mô hình dev/test 1 host, "peer uid khớp allowed_uid" luôn ĐÚNG cho BẤT KỲ tiến trình nào chạy cùng uid đó, không riêng collector. Test "wrong peer UID" REV12 chỉ đổi giá trị EXPECTED sai rồi kết nối từ CÙNG 1 principal — không chứng minh có 2 principal THẬT | `_allowed_uid()` KHÔNG còn mặc định — PHẢI cấu hình tường minh qua `STAGE0P_SIGNING_ALLOWED_UID`, thiếu thì `main()` từ chối khởi động (fail closed). Signer và collector giờ chạy dưới **2 UID hệ điều hành THẬT khác nhau** (`m4-signer`/`m4-collector`, tạo qua `useradd`, cùng 1 group chia sẻ `m4-signing-ipc`) — socket file mode 0600 owner-only (T11-02) sẽ chặn cả chính collector nếu giữ nguyên, nên thêm mô hình **group chia sẻ tùy chọn** (`shared_gid`): thư mục socket mode 0710 (owner rwx, group CHỈ `--x` để đi qua, không đọc/ghi được nội dung thư mục) + đúng gid nhóm chia sẻ, file socket mode 0660 (owner+group rw) — CA đã liệt kê rõ "socket mode 0600 hoặc group policy tối thiểu tương đương" là 2 lựa chọn hợp lệ. Evidence dùng **3 UID thật khác nhau** (signer/collector/other — `other` KHÔNG thuộc group chia sẻ) — collector thật thành công, other thật bị từ chối TRƯỚC khi đọc frame | `app/services/pii/stage0p_signing_service.py` (`_allowed_uid`, `_validate_socket_directory` +tham số `shared_gid`, `run_signing_service`, `main`); `scripts/_stage0p_signing_service_helper.py` (`ensure_service_accounts`, `start_signing_service` +`run_as_uid`/`shared_gid`, `request_signature_as_uid`); `scripts/_stage0p_signing_client_as_uid_helper.py` (mới) |
| **T12-02** (P1) — sau khi qua UID check, signer chấp nhận request chứa `batch_id`/message identity/`purpose_code`/`txid`/raw content do caller TỰ KHAI BÁO — không có one-time authorization/policy chứng minh request thuộc 1 capture capability hợp lệ. TTL/one-time consumption ở DB (T10-04) chỉ bảo vệ persistence CUỐI luồng, không ngăn signer tạo ciphertext/signature cho request NGOÀI capability | Chọn **Hướng 1** CA đề xuất: `m4_stage0p_fetch_message_content()` (CÙNG transaction với capability T4-01, đóng vai "trusted coordinator") TỰ KÝ 1 "signing authorization" HMAC-SHA256 TTL 30s buộc vào CHÍNH (`batch_id`, `conversation_id`, `message_id`, `sample_id`, `purpose_code`, `txid`) của request — collector CHỈ relay nguyên vẹn token này (opaque, `key_version\|issued_epoch\|expires_epoch\|signature_hex`) qua IPC, không tự tạo/sửa được (không giữ khóa verify). Signer tự xác minh chữ ký bằng khóa RIÊNG (`m4_signing_auth_verify_key_b64`, CHỈ tồn tại trong môi trường CHÍNH signing service — collector không bao giờ có) TRƯỚC khi đồng ý ký/mã hóa — bất kỳ trường nào trong request bị sửa đổi so với lúc DB ký đều làm HMAC không khớp. Chống replay: cache trong-bộ-nhớ (vòng đời = tiến trình) khóa bởi `(txid, sample_id)` — request THỨ HAI với CÙNG cặp này trong cửa sổ replay bị từ chối dù token còn hiệu lực TTL | `migrations/039_m4_stage0p.sql` (bảng mới `m4_stage0p_signing_auth_keys` §3b3, `m4_stage0p_fetch_message_content` +tham số `p_sample_id` +cột `signing_authorization`); `app/services/pii/stage0p_signing_service.py` (`_verify_signing_authorization`, `_prune_replay_cache`, `SigningAuthorizationError`); `app/services/pii/stage0p_signing_client.py` (+tham số `signing_authorization`); `app/services/pii/stage0p_sampling.py` (sample_id sinh TRƯỚC fetch, relay token); `app/config.py` (`m4_signing_auth_verify_key_b64`) |
| **T9-03** (P1 activation blocker) — không đổi từ Correction #12 | **KHÔNG sửa bằng code** — CA tiếp tục xác nhận đây là activation blocker. Khai báo lại known limitation, xem §6 | — (không có thay đổi code) |

## 2. Nguyên tắc sửa chung

T12-01 lộ ra 1 khoảng cách giữa "có cơ chế kiểm tra identity" và "cơ chế đó thực sự phân biệt được
2 identity khác nhau": `allowed_uid` mặc định `os.getuid()` KHÔNG SAI về mặt cú pháp — nó chỉ sai
vì trong mô hình dev/test 1 host trước đó, "uid của signer" và "uid của collector" LUÔN LÀ CÙNG 1
GIÁ TRỊ (chưa từng có 2 tiến trình OS thật tách biệt) — nên check này về bản chất luôn là "so sánh
1 giá trị với chính nó". Bài học nhất quán với T4-04/T5-01/T9-02 (không được để 1 tham số/mặc định
tự động trở thành authority) — ở đây áp dụng cho MẶC ĐỊNH của 1 tham số cấu hình, không chỉ tham số
do caller truyền: 1 default an toàn KHÔNG được là "tin chính bản thân mình", phải buộc operator
đưa ra 1 quyết định TƯỜNG MINH về danh tính đối tác được tin.

T12-02 tiếp tục nguyên tắc T6-02/T10-01 ("bất kỳ trường nào dùng để ra quyết định tin cậy đều phải
do bên xác minh tự tính hoặc tự xác minh, không phải do actor có động cơ gian lận tự khai") — áp
dụng sang TẦNG IPC (không chỉ tầng DB persist): trước round này, DB verify transcript SAU KHI đã
ký (đóng đúng "ciphertext/canonical đúng chưa"), nhưng KHÔNG có gì verify RẰNG signer chỉ nên đồng
ý ký cho request này ngay từ đầu. Token T12-02 lấp đúng khoảng trống đó — 1 lớp "authorization
TRƯỚC hành động" bổ sung cho lớp "verification SAU hành động" đã có.

## 3. Bug tự phát hiện trong lúc triển khai (khai báo minh bạch)

1. **`AmbiguousColumnError` (lớp bug tái diễn nhiều round trước) — `ORDER BY created_at DESC`
   không alias trong truy vấn lấy khóa signing_auth mới thêm vào `fetch_message_content()`** — hàm
   có `RETURNS TABLE(..., created_at TIMESTAMPTZ, ...)`, PL/pgSQL tự sinh 1 biến OUT tên
   `created_at` trùng với cột `m4_stage0p_signing_auth_keys.created_at` — `ORDER BY created_at
   DESC` không rõ ràng đang tham chiếu biến nào, xác nhận `AmbiguousColumnError` NGAY khi chạy
   `kill_test.py` lần đầu. Sửa: alias bảng tường minh (`sak.created_at`). Bài học lặp lại (đã ghi
   trong Correction #4): mọi tham chiếu cột bare-name trong hàm có `RETURNS TABLE` PHẢI alias
   nguồn — checklist hardening cần nhắc lại điều này mỗi khi thêm truy vấn MỚI vào 1 hàm ĐÃ CÓ
   `RETURNS TABLE`, không chỉ khi viết hàm mới.
2. **`subprocess`/`asyncio.create_subprocess_exec(..., user=<uid>)` CHỈ setuid, KHÔNG tự setgid
   theo primary group của user đó** — phát hiện khi debug kịch bản T12-01 [2]: cả collector THẬT
   (đúng UID, đúng group) LẪN other THẬT (sai UID, sai group) đều bị "Permission denied" — xác
   nhận bằng thực nghiệm độc lập: 1 tiến trình con spawn với `user=999` (m4-signer, primary
   gid=1000) tạo ra 1 file mà `os.stat().st_gid` vẫn là `0` (root, gid của tiến trình CHA) thay vì
   `1000` — chứng minh EGID của tiến trình con KHÔNG đổi theo `user=` nếu không truyền THÊM
   `group=` tường minh. Đây là hành vi CHUẨN của `subprocess`/`os.setuid()` (setuid không tự động
   setgid), không phải lỗi Docker/container — nhưng dễ bị hiểu nhầm khi thiết kế mô hình
   group-sharing. Sửa: mọi lời gọi `create_subprocess_exec(..., user=uid)` trong
   `_stage0p_signing_service_helper.py` giờ LUÔN kèm `group=pwd.getpwuid(uid).pw_gid` tường minh.
3. **Race điều kiện khởi động: `start_signing_service()` coi service "sẵn sàng" ngay khi file
   socket XUẤT HIỆN (`os.path.exists`), nhưng `asyncio.start_unix_server()` tạo file NGAY LÚC
   `bind()` — TRƯỚC KHI dòng code `os.chown`/`os.chmod` (chuyển về mode/group cuối cùng) của
   CHÍNH module kịp chạy** — 1 client kết nối đúng lúc file còn ở mode mặc định từ `bind()` (chưa
   qua chmod) có thể thành công/thất bại SAI lý do, che giấu bug thật hoặc tạo kết quả test không
   ổn định (flaky). Sửa: đợi THÊM `stat.S_IMODE(...)` của file khớp ĐÚNG mode cuối cùng mong đợi
   (0660 nếu dùng `shared_gid`, 0600 nếu không) trước khi coi là sẵn sàng, không chỉ đợi file tồn
   tại.

## 4. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`; DB reset từ `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` rồi `migrate.py up` lại từ đầu ngay trước loạt chạy cuối, kể cả sau khi sửa bug #1 §3)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` + `migrate.py up` (001..039 từ trạng thái sạch thật sự) | 0 | `OK 039_m4_stage0p`, postcondition PASS ngay lần đầu (bao gồm check MỚI cho `m4_stage0p_signing_auth_keys` — table tồn tại, `public`/`alpha3s_m4_sample_collector`/`alpha3s_app`/`alpha3s_vendor_path` không SELECT được, `alpha3s_m4_definer` CÓ SELECT) |
| 2 | `m4_stage0p_migration_test.py` | 0 | RESULT: PASS (fresh+idempotent+existing-apply+rollback atomic) — re-apply `migrate.py up` ngay sau |
| 3 | `m4_stage0p_pool_test.py` | 0 | RESULT: PASS — 16 nhóm kịch bản, không đổi so với Correction #12 (round này không chạm pool wrapper) |
| 4 | `m4_stage0p_signing_service_test.py` | 0 | RESULT: PASS — **14 kịch bản**: `[1]` happy path (peer hợp lệ + token hợp lệ), `[2]` **MỚI T12-01** 3 UID hệ điều hành THẬT (signer/collector/other) — collector thật thành công, other thật bị từ chối TRƯỚC khi đọc frame, `[3]`-`[8]` giữ nguyên T11-02/T11-03 (permissive dir/symlink/oversized frame/slow-loris/flood/no-content-leak), `[9]`-`[14]` **MỚI T12-02** signing_authorization adversarial (tampered field/hết hạn/TTL vượt/key_version sai/định dạng sai/replay) |
| 5 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — 9 kịch bản REV3 không đổi hành vi; xác nhận round-trip THẬT qua token DB-issued (không phải test riêng lẻ) |
| 6 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J) — cùng xác nhận round-trip qua token DB-issued thật |
| 7 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS — 19 call site `fetch_message_content` cập nhật chữ ký 4 tham số, ma trận EXECUTE + negative-permission mở rộng cho `m4_stage0p_signing_auth_keys` (3 role bị từ chối SELECT, đối xứng với `transcript_signing_keys`) |
| 8 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS — không đổi (không chạm collector/signing path) |
| 9 | `pytest -q` (full) | 0 | **241 passed** (không đổi — T12-01/T12-02 chỉ chạm signing-service access-control/pool wrapper cấu hình, không chạm logic thuần đã có unit test) |
| 10 | `ruff check app/services/pii/ app/config.py scripts/m4_stage0p_*.py scripts/_stage0p_signing_service_helper.py scripts/_stage0p_signing_client_as_uid_helper.py tests/test_m4_*.py` | 0 | All checks passed (sau khi sửa 1 import-sort ở file mới `_stage0p_signing_client_as_uid_helper.py`) |
| 11 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` tự xác nhận `capture_enabled=False` trước khi kết thúc |

Không có sự cố hạ tầng (Docker/DB) nào xảy ra trong round này.

## 5. Chưa/không cần sửa lại (theo đúng phạm vi CA giới hạn ở §4/Resubmission Review #12)

- `T11-01` (`except BaseException` resource guard) — CA xác nhận **CLOSED**, exact delta round này
  KHÔNG chạm logic đó.
- Toàn bộ filesystem/frame/timeout hardening của T11-02 (private directory owner/mode check,
  symlink rejection, socket mode, frame-size limit, concurrency semaphore, per-connection
  timeout) — CA liệt kê rõ "được giữ nguyên; Correction kế tiếp không cần làm lại". Round này CHỈ
  MỞ RỘNG `_validate_socket_directory()` để hỗ trợ THÊM 1 nhánh (`shared_gid`) khi cần — nhánh
  KHÔNG dùng `shared_gid` (mặc định) giữ NGUYÊN kiểm tra nghiêm ngặt cũ, không nới lỏng.

## 6. Known limitations (không đổi so với Correction #12 §6, cộng thêm)

30-34. Không đổi nội dung so với Correction #12 (T8-02 vẫn HMAC đối xứng, cần nâng KMS/HSM trước
    production; T9-01/T10-03 chỉ đóng đúng lớp truy cập qua `pinned_actor_session()`; T9-03 vẫn
    activation blocker theo khung CA; ngưỡng gate T4-05/T6-03 vẫn chờ PO decision record; signing
    service vẫn chạy như subprocess trên CÙNG HOST với collector trong mô hình dev/test).
35. Không đổi nội dung — `_peer_uid()` vẫn xác thực bằng UID cấp hệ điều hành (`SO_PEERCRED`),
    KHÔNG PHẢI 1 credential ứng dụng độc lập với quyền OS của host.
36. **MỚI — mô hình `shared_gid` (group chia sẻ giữa signer/collector) vẫn là 2 tài khoản HỆ ĐIỀU
    HÀNH THẬT nhưng CÙNG 1 HOST/container/namespace** (không phải service account/container tách
    biệt thật sự như production cần) — đóng đúng yêu cầu T12-01 "2 UID/service account/container
    identity khác nhau" ở MỨC UID, nhưng cả 2 vẫn chia sẻ TOÀN BỘ kernel/filesystem/network
    namespace của 1 host — 1 lỗ hổng leo thang đặc quyền cấp hệ điều hành (kernel exploit, shared
    /tmp, v.v.) trên host đó vẫn có thể xóa bỏ ranh giới này. Trước production: cần container/pod/
    VM tách biệt thật sự (network namespace riêng), không chỉ UID khác nhau trên cùng kernel.
37. **MỚI — cache chống replay của signing_authorization (T12-02) chỉ tồn tại TRONG BỘ NHỚ, vòng
    đời = tiến trình signing service hiện tại** — nếu service RESTART giữa lúc 1 token đang trong
    cửa sổ TTL, cache mất, token đó về lý thuyết dùng lại được 1 lần nữa (dù đã dùng trước restart)
    trước khi tự hết hạn TTL 30s. Rủi ro RẤT NHỎ (cửa sổ tối đa 30s, cần restart CHÍNH XÁC đúng lúc
    đó VÀ có 1 request replay sẵn sàng) nhưng là giới hạn kiến trúc cần ghi nhận — production cần
    state chống replay BỀN VỮNG hơn (vd Redis/DB) nếu signing service có thể restart thường xuyên
    trong khi vẫn còn token chưa hết hạn đang lưu hành.

## 7. Đề nghị

CA review Correction #13 đối chiếu `T12-01` (2 UID hệ điều hành THẬT signer/collector qua
`useradd`, group chia sẻ cho phép collector mở socket theo đúng "group policy" CA cho phép,
`_allowed_uid()` không còn mặc định tự tin chính mình, evidence dùng 3 principal thật) và `T12-02`
(DB tự ký signing authorization TTL 30s buộc vào toàn bộ identity/scope của request, signer verify
bằng khóa riêng collector không có, chống replay trong-bộ-nhớ, 6 kịch bản adversarial). `T9-03` giữ
nguyên trạng activation blocker theo đúng khung CA đã đặt — không xin đóng finding này round này.
Không xin quyền production-data-access/activation — gate đó vẫn tách riêng theo Design Acceptance
§6.
