---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-9-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #9
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-30
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-8-VI.md (CA, CHANGES_REQUIRED, reviewed_head 12a4ac368ad3350ece8e4f193d4a1da590a8a591)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #9

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-8-VI.md` — sửa `T8-01` (P1) và `T8-03` (P2) bằng
code + evidence. `T8-02` (P1) **KHÔNG sửa bằng code** round này — CA chỉ rõ "nếu hạ tầng hiện tại
chưa có KMS/signing boundary, Dev phải trình một design amendment cụ thể cho trusted capture
service trước khi code tiếp; không thêm digest/length heuristic mới" (§F-M4-0P-T8-02). §5 dưới đây
trình bày design amendment cho Phương án C (signed capture transcript) CA yêu cầu, với 3 hướng
triển khai cụ thể cho CA/PO chọn. Phạm vi KHÔNG đổi: dev/test trên branch M4 (worktree
`D:\alpha3s-m4`, KHÔNG checkout M4 trong `D:\alpha3s`), dữ liệu synthetic/test, **KHÔNG**
merge/deploy/production-data-access/activation. Ngưỡng exclusion `10%/200` (T4-05) tiếp tục ở
nguyên trạng CA đề xuất, CHƯA có PO decision record chính thức.

## 1. Mapping finding → sửa (hoặc design amendment)

| Finding | Xử lý | File |
|---|---|---|
| **T8-01** (P1) — consume-on-use (Correction #8) chỉ đóng trường hợp actor A dùng pin XONG rồi actor B mượn lại connection; nếu actor A pin THÀNH CÔNG rồi request bị hủy/lỗi TRƯỚC khi làm hành động nghiệp vụ nào, row pin vẫn còn — 1 connection pool THẬT trả lại CHÍNH connection đó cho actor B có thể để B kế thừa pin của A trong tối đa 15 phút (TTL) | Module mới `app/services/pii/stage0p_pool.py` — `pinned_actor_session()` là async context manager DUY NHẤT để làm việc với 1 pool `asyncpg` thật: (1) checkout LUÔN chủ động gọi `m4_stage0p_unpin_actor()` NGAY trước khi pin (lưới an toàn — không phụ thuộc cleanup của lần checkout trước có chạy đúng hay không); (2) pin + `SET ROLE` sang business role, yield connection — connection KHÔNG BAO GIỜ thoát khỏi `async with` trong lúc pin còn hiệu lực; (3) cleanup (unpin, boọc `asyncio.shield`) LUÔN chạy trong `finally`, kể cả khi exception hoặc `task.cancel()` xảy ra giữa chừng, TRƯỚC khi `pool.release()`. Evidence mới `scripts/m4_stage0p_pool_test.py` dùng pool `min_size=1,max_size=1` (ép buộc tái sử dụng CHÍNH 1 connection vật lý) — 6 nhóm kịch bản: happy path, abandoned pin (không exception, không hành động), exception trước hành động, `task.cancel()` giữa chừng, 5 vòng checkin/checkout xen kẽ A/B, và 2 đối chứng bypass wrapper (xem §3 mục 3 — phát hiện phụ thú vị về hành vi `asyncpg.Pool.release()`) | `app/services/pii/stage0p_pool.py` (mới); `scripts/m4_stage0p_pool_test.py` (mới) |
| **T8-02** (P1) — `record_sample()` không xác minh ciphertext THẬT SỰ giải mã ra plaintext mang đúng digest; CA không chấp nhận Phương án B (Correction #8) làm closure, yêu cầu design amendment cho Phương án C (signed capture transcript) trước khi code | **KHÔNG sửa bằng code round này** — xem §5 Design Amendment. Chưa có KMS/HSM/signing-boundary trong hạ tầng hiện tại (xác nhận bằng cách rà soát `docker-compose.yml`/`docker-compose.prod.yml` — DB image `pgvector/pgvector:pg16` không có `pgsodium`/`pg_net`; VPS production `160.30.157.235` không có dịch vụ KMS nào) | — (không có thay đổi code) |
| **T8-03** (P2) — `set_current_normalization_version()` chỉ kiểm `approval_ref` không rỗng, không xác minh đó là 1 approval record THẬT | Bảng mới `m4_stage0p_normalization_approvals`/`_revocations` (immutable-record + revocation-event-riêng, cùng mẫu `m4_stage0p_capture_approvals` T3-05 nhưng HOÀN TOÀN TÁCH BIỆT — không tái diễn giải approval capture-ON) + hàm mới `m4_stage0p_record_normalization_approval()`/`m4_stage0p_revoke_normalization_approval()`. `set_current_normalization_version()` giờ đòi hỏi `approval_ref` trỏ tới 1 record tồn tại, đúng `requested_version`, còn hiệu lực (`now() BETWEEN valid_from AND valid_until`), và chưa bị thu hồi — registry row lưu đúng `approval_ref` đã xác minh (không còn chuỗi tùy ý). Evidence mới trong `m4_stage0p_permissions_test.py`: forged/expired/revoked/wrong-version approval_ref đều RAISE đúng thông điệp T8-03 | `migrations/039_m4_stage0p.sql` §2c2 (bảng mới)/§5g0 (hàm mới)/§5d2 (`set_current_normalization_version`); `scripts/m4_stage0p_permissions_test.py` |

## 2. Nguyên tắc sửa chung (không đổi so với Correction #1-8)

T8-01/T8-03 tiếp tục nguyên tắc xuyên suốt: **thứ dùng làm bằng chứng phải là thứ DB tự cấp phát/
tự tính, gắn đúng phạm vi mà nó THẬT SỰ đại diện**. T8-01 thu hẹp phạm vi thêm 1 bậc so với T7-01:
pin không chỉ "tiêu thụ khi dùng thành công" mà còn "không bao giờ sống sót qua ranh giới
checkout/checkin của pool" — ranh giới đó giờ là 1 lớp Python tường minh (`pinned_actor_session`),
không phải giả định ngầm rằng mọi connection đều là 1-lần-dùng như các evidence script khác. T8-03:
`approval_ref` của normalization change đại diện cho "1 quyết định phê duyệt THẬT, đúng version,
còn hiệu lực" — không phải "1 chuỗi bất kỳ do actor có quyền tự khai", cùng nguyên tắc đã áp dụng
cho `m4_stage0p_capture_approvals` từ T3-05.

## 3. Bug/phát hiện tự phát hiện trong lúc triển khai (khai báo minh bạch)

1. **`m4_stage0p_pool_test.py` kịch bản [6a] (đối chứng bypass wrapper): quên `pool.release()` cho
   `raw_conn2`** — gây deadlock THẬT (pool `max_size=1`, lần `pool.acquire()` kế tiếp trong kịch
   bản [6b] treo vô hạn chờ 1 connection không bao giờ được trả lại). Phát hiện bằng thực nghiệm:
   script treo quá 120s, kiểm tra `pg_stat_activity` xác nhận CẢ 2 connection đều `idle`/
   `ClientRead` (không phải deadlock phía DB) → suy ra deadlock phía Python đúng khi rà soát lại
   toàn bộ cặp `acquire()`/`release()` trong file, tìm ra 1 `acquire()` thiếu `release()` tương
   ứng. Sửa: thêm `await pool.release(raw_conn2)`. Không phải bug ở `stage0p_pool.py` (module sản
   phẩm) — chỉ ở chính evidence script.
2. **Phát hiện phụ (không phải bug — bằng chứng bổ sung có giá trị)**: kịch bản đối chứng đầu tiên
   ([6a], dùng `pool.acquire()`/`pin_actor()`/`pool.release()` thô, KHÔNG unpin trước release) đã
   KHÔNG tái hiện được lỗ hổng như dự tính — actor "B" bị từ chối với lỗi "session STALE
   (session_nonce khong khop)" dù ROW pin của A vẫn còn nguyên. Xác nhận bằng thực nghiệm độc lập
   (script tối giản: `set_config` 1 GUC tùy ý → `pool.release()` → `pool.acquire()` lại CHÍNH
   connection đó qua `pg_backend_pid()` → đọc lại GUC → rỗng): **`asyncpg.Pool.release()` tự thực
   hiện 1 dạng reset session-scoped state (tương đương `DISCARD`/`RESET ALL`) trên connection vật
   lý trước khi đưa nó trở lại pool cho lần acquire tiếp theo**, dù backend process/PID được tái sử
   dụng nguyên vẹn. Kết hợp với `session_nonce` (T6-01), điều này tình cờ đóng góp 1 lớp phòng thủ
   THÊM cho chính kịch bản T8-01 lo ngại — nhưng đây là hành vi ĐẶC THÙ của `asyncpg`, KHÔNG phải
   cam kết giao thức Postgres hay đảm bảo của Stage 0P, và KHÔNG được dựa vào như cơ chế đóng
   chính thức (1 pooler khác — vd PgBouncer session-pooling, hoặc 1 driver tự viết không gọi
   `Connection.reset()` — có thể KHÔNG có hành vi này). Viết lại kịch bản đối chứng thành [6a]
   (giữ nguyên, đổi thành ghi nhận phát hiện này) + [6b] MỚI (mô phỏng 1 pooler KHÔNG tự reset
   bằng cách ghi đè thủ công GUC `session_nonce` về giá trị cũ sau reacquire) — [6b] tái hiện ĐÚNG
   lỗ hổng CA mô tả (actor B chưa từng pin vẫn thực hiện được hành động nghiệp vụ bằng danh tính
   bỏ dở của A), xác nhận `pinned_actor_session()` (xóa hẳn ROW, không chỉ dựa vào GUC) là lớp đóng
   THẬT SỰ, không phụ thuộc hành vi ngoài ý muốn của 1 driver/pooler cụ thể.
3. **`m4_stage0p_pool_test.py` cleanup cuối script thiếu `DELETE FROM audit_log`** — các lệnh
   `set_capture_enabled()` trong kịch bản đều ghi `audit_log` với `actor_staff_id` trỏ tới
   staff test; `DELETE FROM staff_users` cuối script vỡ FK `audit_log_actor_staff_id_fkey`. Sửa:
   thêm `DELETE FROM audit_log WHERE actor_staff_id IN (...)` trước khi xóa `staff_users`, đúng
   thứ tự các evidence script khác đã dùng.
4. **Ruff**: 1 import block chưa sort đúng trong `m4_stage0p_pool_test.py` (nhiều tên trên 1 dòng
   `from ... import a, b`) — sửa theo gợi ý `ruff` (tách thành block nhiều dòng).

## 4. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`; DB reset từ `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` rồi `migrate.py up` lại từ đầu ngay trước loạt chạy cuối)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` + `migrate.py up` (001..039 từ trạng thái sạch thật sự) | 0 | `OK 039_m4_stage0p`, postcondition PASS ngay lần đầu (bao gồm toàn bộ check MỚI cho `m4_stage0p_normalization_approvals`/`_revocations` — table tồn tại, `public`/`alpha3s_vendor_path` không EXECUTE được 2 hàm mới, `alpha3s_m4_approval_recorder` CÓ EXECUTE) |
| 2 | `m4_stage0p_migration_test.py` | 0 | RESULT: PASS (fresh+idempotent+existing-apply+rollback) — re-apply `migrate.py up` ngay sau (kịch bản rollback dọn sạch schema M4, đúng ý đồ thiết kế) |
| 3 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS, 0 FAIL. Ma trận EXECUTE mở rộng lên **19 hàm SECURITY DEFINER** (thêm `m4_stage0p_record_normalization_approval`/`revoke_normalization_approval`). Mảng adversarial T8-03 MỚI: approval_ref giả mạo/hết hạn/đã bị thu hồi/đúng approval nhưng SAI version đều RAISE đúng thông điệp; approval hợp lệ → `set_current_normalization_version` thành công VÀ registry row lưu đúng `approval_ref` đã xác minh (không phải chuỗi bất kỳ) |
| 4 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — 9 kịch bản REV3 không đổi hành vi |
| 5 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J) |
| 6 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS |
| 7 | `m4_stage0p_pool_test.py` (**mới**, T8-01) | 0 | RESULT: PASS — 6 nhóm kịch bản (xem §1 bảng finding + §3 mục 2 cho phát hiện phụ về `asyncpg.Pool.release()`) |
| 8 | `pytest -q` (full) | 0 | **241 passed** (không đổi — T8-01/T8-03 chỉ thêm module/evidence script mới + DB boundary mới, không chạm logic thuần đã có unit test) |
| 9 | `ruff check app/services/pii/ scripts/m4_stage0p_*.py tests/test_m4_*.py` | 0 | All checks passed (sau khi sửa 1 import-sort ở `m4_stage0p_pool_test.py`, xem §3 mục 4) |
| 10 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` tự xác nhận `capture_enabled=False` trước khi kết thúc |

Cả 6 evidence script (bao gồm `m4_stage0p_pool_test.py` mới) chạy TUẦN TỰ trên CÙNG một DB (sau khi
re-apply migration do `migration_test.py` kịch bản rollback dọn sạch), xác nhận không rò rỉ state
giữa các lần chạy.

## 5. Design Amendment — T8-02 (Phương án C: Signed capture transcript)

CA yêu cầu cụ thể: "nếu hạ tầng hiện tại chưa có KMS/signing boundary, Dev phải trình một design
amendment cụ thể cho trusted capture service trước khi code tiếp; không thêm digest/length
heuristic mới." Dev xác nhận **hạ tầng hiện tại KHÔNG có KMS/HSM/signing boundary** (xem §1 bảng
finding — DB image `pgvector/pgvector:pg16` không có `pgsodium`/`pg_net`; VPS production
`160.30.157.235`, xem `docs/DEPLOYMENT-VI.md`, không chạy dịch vụ KMS nào). Dưới đây là 3 hướng
triển khai cụ thể cho CA/PO chọn — Dev KHÔNG tự chọn thay.

**Bối cảnh không đổi so với Correction #8 §5**: `record_sample()` (role `alpha3s_m4_definer`)
không giữ khóa giải mã AES-256-GCM (có chủ ý — key rotation + DSR crypto-shredding), nên DB không
thể tự giải mã ciphertext để đối chiếu digest. Transcript ký (theo đúng danh sách CA yêu cầu) phải
gồm: batch/conversation/message/sample identity; capability nonce một lần (đã có, bảng
`m4_stage0p_fetch_capability`); canonical plaintext digest + length + truncation (đã có, cột
`fetched_canonical_digest`); ciphertext digest; thuật toán AEAD/key-version + AAD digest; control
generation/purpose.

**Hướng 1 — KMS/HSM thật + `pgsodium` (đúng ưu tiên CA nêu, đóng T8-02 hoàn toàn)**: 1 "trusted
capture service" là 1 tiến trình Python RIÊNG (không chạy chung process/container với app
worker hiện tại — chỉ tiến trình này có network access tới KMS), giữ private key Ed25519 trong
KMS thật (vd HashiCorp Vault Transit tự host, hoặc chuyển 1 phần hạ tầng sang nhà cung cấp có
KMS quản lý nếu PO chấp nhận). Service này ký transcript TRƯỚC khi app gọi `record_sample()`.
PostgreSQL verify chữ ký bằng `pgsodium.crypto_sign_verify_detached()` (hoặc tương đương) ngay
trong `record_sample()` — nhưng image DB hiện tại (`pgvector/pgvector:pg16`) KHÔNG có
`pgsodium` cài sẵn, cần build custom image (compile từ source hoặc đổi sang base image khác đã
có, vd `supabase/postgres`). Đây là **thay đổi hạ tầng lớn, đổi cả DB image đang chạy production
thật tại VPS** — vượt phạm vi 1 correction round, cần CA/PO duyệt kế hoạch migrate riêng (bao gồm
rủi ro tương thích `pgvector` + extension mới trên cùng 1 image, downtime cutover, rollback plan).

**Hướng 2 — External verifier qua network call-out (`pg_net`/FDW)**: PostgreSQL gọi ra 1 service
verifier bên ngoài (giữ public key hoặc tự có quyền gọi KMS) để verify chữ ký thay vì verify tại
chỗ. Cũng cần extension (`pg_net`) không có sẵn trong image hiện tại; QUAN TRỌNG HƠN, đưa vào 1
network dependency ĐỒNG BỘ bên trong transaction của `record_sample()` — nếu verifier service
down/chậm, toàn bộ capture pipeline bị chặn hoặc timeout theo cách khó dự đoán hơn 1 lệnh SQL
thuần. Dev KHÔNG thấy lợi thế rõ ràng của hướng này so với Hướng 1 (cùng cần hạ tầng mới) hay
Hướng 3 (không cần), nên không đề xuất trừ khi CA có lý do cụ thể ưu tiên nó.

**Hướng 3 — Interim: HMAC-based transcript signing bằng `pgcrypto` hiện có (KHÔNG cần KMS/HSM,
triển khai được NGAY trong 1 correction round tiếp theo)**: "Trusted capture service" vẫn là 1
ranh giới logic riêng (vd 1 hàm/module Python chỉ nó biết 1 secret HMAC — secret này KHÔNG nằm
trong bất kỳ credential nào role `alpha3s_m4_sample_collector` đọc được, vd biến môi trường riêng
của service đó hoặc 1 bảng Postgres cực kỳ hạn chế GRANT, không role m4 nào SELECT được). Service
tính `hmac(transcript::text::bytea, secret, 'sha256')` (hàm `hmac()` đã có sẵn trong `pgcrypto`,
extension ĐANG được dùng trong migration 039 — không cần cài thêm gì). `record_sample()` nhận
thêm transcript (`jsonb`) + chữ ký (`bytea`), verify bằng CHÍNH `hmac()` đó với secret đọc từ nơi
role `alpha3s_m4_sample_collector` KHÔNG có quyền SELECT. **Đánh đổi rõ ràng so với Hướng 1**: đây
là lược đồ ĐỐI XỨNG (không phải chữ ký số thật) — bất kỳ ai đọc được secret (kể cả superuser vận
hành DB, hoặc chính role `alpha3s_m4_definer` nếu secret vô tình đặt sai chỗ) đều giả mạo được
transcript; KHÔNG có non-repudiation. Nhưng đóng ĐÚNG lỗ hổng T8-02 hiện tại ở mức: 1 actor chỉ có
role `alpha3s_m4_sample_collector` (mức truy cập THẤP NHẤT hiện dùng để gọi `record_sample`)
KHÔNG còn tự tạo được ciphertext-thay-thế hợp lệ nữa — phải có quyền đọc secret HMAC (phạm vi hoàn
toàn khác, không cấp cho role nghiệp vụ nào).

**Đề xuất của Dev** (không phải quyết định — CA/PO quyết): Hướng 3 cho giai đoạn Stage 0P dev/test
hiện tại — khả thi triển khai ngay, không đổi hạ tầng/image production đang chạy thật, và nâng rào
cản đúng theo tinh thần CA yêu cầu (chữ ký thật, không phải heuristic digest/length thêm nữa). Điều
kiện RÕ RÀNG kèm theo (giống tinh thần Phương án B/Correction #8 nhưng chặt hơn — lần này có cơ chế
xác minh thật, không chỉ ghi nhận limitation): **trước khi Stage 0P được cấp production-data-access/
activation, phải nâng cấp lên Hướng 1 (KMS/HSM thật)** — Hướng 3 KHÔNG được coi là đủ cho
production, chỉ là bước tăng cường tạm thời cho giai đoạn dev/test. Hướng 2 Dev không đề xuất (xem
lý do trên).

**Adversarial test bắt buộc khi CA/PO chọn xong hướng và Dev triển khai** (nhắc lại đúng yêu cầu CA
Review #8): digest plaintext thật + ciphertext giả cùng length + chữ ký thiếu/sai/replay/
cross-message/cross-batch đều phải RAISE.

## 6. Known limitations (không đổi so với Correction #8 §6, cộng thêm)

27. **T8-01 đóng khoảng cách "pool checkin/checkout" cho ĐÚNG lớp truy cập đi qua
    `pinned_actor_session()`** — nếu code nghiệp vu tương lai bypass wrapper này (tự gọi
    `pool.acquire()`/`pool.release()` trực tiếp như kịch bản đối chứng §3 mục 2 minh họa), lỗ hổng
    quay lại. `pin_secret` VẪN là 1 credential tự tạo (bespoke), không phải identity authority
    production thật — Stage 0P hiện chưa có lớp HTTP/JWT auth thật để derive staff identity từ 1
    authenticated application principal (CA đã nêu lại ở Correction #6/#7/Review #8) — đây vẫn là
    khoảng cách kiến trúc RIÊNG, T8-01 không giải quyết, cần quyết định cùng lúc khi thiết kế tầng
    HTTP API thật cho Stage 0P.
28. **T8-02 KHÔNG đóng — xem §5 Design Amendment.** Known limitation CHỦ ĐỘNG khai báo lại, chờ
    CA/PO chọn 1 trong 3 hướng trước khi Dev triển khai code.
29. Ngưỡng gate T4-05/T6-03 (10%/200, `gate_version=ca-review-4-proposed-v1`) — không đổi so với
    Correction #8 giới hạn #26: vẫn là đề xuất CA, CHƯA có PO decision record chính thức.

## 7. Đề nghị

CA review Correction #9 đối chiếu `T8-01`/`T8-03` (sửa bằng code) và §5 Design Amendment cho
`T8-02` (chờ CA/PO chọn Hướng 1/2/3, không phải code fix). Không xin quyền
production-data-access/activation — gate đó vẫn tách riêng theo Design Acceptance §6.
