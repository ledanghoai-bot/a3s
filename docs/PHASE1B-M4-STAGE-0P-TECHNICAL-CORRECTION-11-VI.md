---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-11-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #11
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-31
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-10-VI.md (CA, CHANGES_REQUIRED, reviewed_head b25f67c8b146d4155a7ed2ff479619c8f94ac1dd)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #11

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-10-VI.md` — sửa `T10-01`/`T10-02` (P1, cả hai đóng
lại `T8-02`: signer phải tự derive canonical metadata từ CHÍNH plaintext nó ký, và phải là 1
boundary tách biệt THẬT, không phải "logic riêng cùng process") bằng code; sửa `T10-03` (P1, mọi
lỗi trong `__aenter__()` sau `pool.acquire()` phải đi qua cùng 1 cleanup/discard primitive với
`__aexit__()`); sửa `T10-04` (P2, DB phải giới hạn chặt transcript lifetime/schema/key-version).
`T9-03` KHÔNG sửa bằng code — CA tiếp tục đóng khung đây là **activation blocker**, không phải
finding chờ code fix; giữ nguyên known limitation, khai báo lại rõ ràng ở §6. Phạm vi KHÔNG đổi:
dev/test trên branch M4 (worktree `D:\alpha3s-m4`, KHÔNG checkout M4 trong `D:\alpha3s`), dữ liệu
synthetic/test, **KHÔNG** merge/deploy/production-data-access/activation. Ngưỡng exclusion
`10%/200` (T4-05) tiếp tục ở nguyên trạng CA đề xuất, CHƯA có PO decision record chính thức.

## 1. Mapping finding → sửa

| Finding | Xử lý | File |
|---|---|---|
| **T10-01** (P1) — `sign_capture()` REV10 nhận `canonical_digest`/`canonical_len`/`truncated` như tham số TRUSTED từ caller, không tự derive/đối chiếu với `plaintext_canonical` nó thực sự encrypt — cho phép "digest thật của A + ciphertext của B" | `sign_capture()` KHÔNG còn nhận `canonical_digest` làm tham số — tự tính `canonical_digest = sha256(plaintext_canonical)` NGAY TỪ chính chuỗi nó sắp encrypt, trước khi build transcript. `canonical_len` còn giữ làm tham số nhưng bị đối chiếu `len(plaintext_canonical)` ngay đầu hàm — lệch thì `SlotCryptoError` (bug nội bộ, không phải security boundary — chỉ bẫy lỗi gọi sai). `truncated` không tự derive được CHỈ từ chuỗi đã cắt (1 chuỗi 2000 ký tự không tự nói lên được bản gốc có dài hơn không) — SIGNING SERVICE (không phải collector) tự chạy `canonicalize()` (module mới, dùng chung) trên RAW content để xác định, rồi OR với `db_char_truncated` (cờ DB tự tính ở `fetch_message_content`, đáng tin vì server-computed) — nguyên tắc "signer tự derive TOÀN BỘ trường" giữ nguyên | `app/services/pii/crypto.py` (`sign_capture`); `app/services/pii/canonicalize.py` (mới, `canonicalize`/`truncate_canonical`); `app/services/pii/stage0p_signing_service.py` (`_handle_request`) |
| **T10-02** (P1) — `sign_capture()` REV10 là 1 function trong `crypto.py`, chạy CÙNG process với collector; collector process tự đọc được `settings.m4_transcript_hmac_key_b64` — "logic riêng cùng process" không phải security boundary theo CA | Tách signer thành 1 **process hệ điều hành riêng thật sự** — `python -m app.services.pii.stage0p_signing_service`, giao tiếp qua **Unix domain socket** (frame JSON tiền tố 4-byte big-endian length, 1 request/response mỗi kết nối). Service đọc `M4_SAMPLE_KEY_B64`/`M4_TRANSCRIPT_HMAC_KEY_B64` CHỈ từ **environment của chính nó** (`os.environ.get(...)` trong `main()`) — collector process KHÔNG BAO GIỜ set 2 setting này (xác nhận: đã bỏ toàn bộ dòng gán `settings.m4_sample_key_b64`/`m4_transcript_hmac_key_b64` khỏi mọi đường code liên quan tới collector trong evidence scripts, chỉ còn giữ 1 chỗ trong `sampling_test.py` cho test crypto round-trip ĐỘC LẬP, không mô phỏng collector). Collector gọi service qua `stage0p_signing_client.request_signature()` — không nhận ciphertext/digest/canonical metadata do collector tự khai, chỉ gửi `raw_content` + identity/context, service tự validate → canonicalize → encrypt → sign | `app/services/pii/stage0p_signing_service.py` (mới); `app/services/pii/stage0p_signing_client.py` (mới); `app/services/pii/stage0p_sampling.py` (`_run_fenced_unit`, fail-closed nếu `m4_stage0p_signing_socket` chưa cấu hình — không fallback ký trong-process); `app/config.py` (`m4_stage0p_signing_socket`); `scripts/_stage0p_signing_service_helper.py` (mới, helper spawn/stop subprocess cho evidence scripts) |
| **T10-03** (P1) — `__aenter__()` REV10 chỉ bọc `try/except` quanh `pin_actor()`; lỗi tại `SET ROLE alpha3s_m4_actor_binder` ban đầu, safety-unpin, `RESET ROLE`, hoặc `SET ROLE <business_role>` không đi qua cùng cleanup/discard primitive với `__aexit__()`; safety-unpin `except Exception: ... continue` coi lỗi unpin thật như no-op | Toàn bộ acquire/setup (`SET ROLE actor_binder` → safety-unpin → `pin_actor()` → `RESET ROLE` → `SET ROLE business_role`) nằm trong 1 `try` DUY NHẤT bên trong `__aenter__()`; `except Exception:` gọi CÙNG `_wait_cleanup_and_release(pool, conn)` mà `__aexit__()` dùng (tách hàm dùng chung, không phải logic lặp lại 2 nơi), rồi re-raise. Safety-unpin không còn `except Exception: continue` nuốt lỗi — `m4_stage0p_unpin_actor()` bình thường không RAISE cho trường hợp "chưa pin gì" (chỉ là `DELETE ... WHERE backend_pid=...` vô hại), nên bất kỳ `PostgresError` nào nó THẬT SỰ ném ra giờ propagate vào cleanup path (fail-closed) thay vì bị coi là no-op | `app/services/pii/stage0p_pool.py` (`__aenter__`, `__aexit__`, `_wait_cleanup_and_release` — tách từ logic `__aexit__` cũ) |
| **T10-04** (P2) — DB chỉ kiểm `expires_at >= now()`/`issued_at <= now()+5s`, không kiểm `expires_at > issued_at`, TTL tối đa, schema/field allowlist đầy đủ, hay tách `signing_key_version` khỏi `encryption_key_version` | `m4_stage0p_record_sample()` thêm: (1) strict schema validation — transcript phải là JSON object, ĐÚNG 17 field trong allowlist cố định, version `v=1` bắt buộc; (2) `encryption_key_version` field MỚI, tách biệt khỏi `key_version` (signing key) hiện có, đối chiếu hardcode `'sample-aead-v1'`; (3) `expires_at > issued_at` VÀ TTL `expires_at - issued_at <= 60s`, kiểm TRƯỚC (không phải sau) 2 check temporal `now()`-relative đã có — thứ tự này quan trọng (xem §4 bug tự phát hiện) | `migrations/039_m4_stage0p.sql` (`m4_stage0p_record_sample`); `app/services/pii/crypto.py` (`ENCRYPTION_KEY_VERSION` constant, field mới trong transcript) |
| **T9-03** (P1 activation blocker) — không đổi từ Correction #10 | **KHÔNG sửa bằng code** — CA tiếp tục xác nhận đây là activation blocker. Khai báo lại known limitation, xem §6 | — (không có thay đổi code) |

## 2. Nguyên tắc sửa chung

T10-01 đóng đúng khoảng cách CA chỉ ra ở Review #10: T8-02/Correction #10 đã bind CIPHERTEXT bằng
chữ ký (đóng đúng lỗ hổng T6-02 để lại), nhưng vẫn để CANONICAL METADATA (digest/length/truncated)
là dữ liệu caller tự khai và signer tin tưởng — signer "ký cái gì nó KHÔNG tự kiểm tra" thì chữ ký
chỉ chứng minh "signer đã ký", không chứng minh "nội dung được ký đúng là nội dung được encrypt".
Nguyên tắc xuyên suốt cả 8 correction trước (T4-02 normalization version, T5-02 content bounds,
T6-02 digest binding) là: **bất kỳ trường nào signer/DB dùng để RA QUYẾT ĐỊNH tin cậy đều phải do
chính signer/DB tự tính, không phải do actor có động cơ gian lận tự khai** — T10-01 áp dụng triệt
để nguyên tắc này cho chính hàm ký, không chỉ cho DB verifier.

T10-02 đóng đúng nhận định CA: "một function/module 'logic riêng' trong cùng process không được
coi là security boundary" — ranh giới bảo mật thật đòi hỏi ranh giới CÔ LẬP THẬT (process/quyền hệ
điều hành khác nhau), không phải ranh giới tổ chức code (module/hàm riêng vẫn chia sẻ toàn bộ
address space, import path, và biến `settings` toàn cục với code gọi nó). Unix domain socket +
process con là ranh giới TỐI THIỂU đúng nghĩa cho dev/test — key vật lý không tồn tại trong bất kỳ
biến Python nào mà collector process có thể đọc.

T10-03 tiếp tục nguyên tắc T9-01 ("cleanup phải thật sự bảo vệ được resource, không chỉ tuyên bố
bảo vệ") nhưng mở rộng phạm vi: T9-01 chỉ đóng đường `__aexit__()` (thân `async with` chạy xong),
T10-03 đóng luôn đường THIẾT LẬP thất bại giữa chừng (`__aenter__()` tự ném lỗi trước khi thân
block kịp chạy) — 1 resource guard chỉ đúng nếu nó bảo vệ ĐỦ mọi điểm ra khỏi vòng đời, không chỉ
điểm ra "bình thường".

## 3. T10-01/T10-02 — chuỗi tin cậy mới cho `sign_capture()`

| Bước | Ai làm | Vì sao đáng tin |
|---|---|---|
| 1. Collector fetch `raw_content` qua capability one-time (T4-01) đã xác thực trong transaction DB của nó | Collector | Không đổi — vẫn là cơ chế capability hiện có, KHÔNG phải chỗ T10-01/02 sửa |
| 2. Collector gửi `raw_content` (KHÔNG canonicalize/truncate/hash trước) + identity/context qua socket tới signing service | Collector → service (IPC) | Service không tin bất kỳ trường "đã qua xử lý" nào của collector — chỉ tin `raw_content` thô, service tự làm hết phần còn lại |
| 3. Service tự `canonicalize(raw_content)` (NFC + truncate 2000 ký tự/8000 byte, cùng thuật toán `_truncate` cũ, nay ở module dùng chung `canonicalize.py`) | Service | Service, không phải collector, quyết định canonical text cuối cùng là gì |
| 4. Service tự `sha256(canonical_text)` → `canonical_digest`; tự `len(canonical_text)` → `canonical_len`; OR cờ truncate của chính nó với `db_char_truncated` (server-computed, đáng tin) | Service | Không còn tham số `canonical_digest` nhận từ ngoài trong `sign_capture()` — về mặt kiểu dữ liệu Python, exploit "digest A + ciphertext B" không còn CÓ THỂ diễn đạt được qua boundary này |
| 5. Service `encrypt_sample_value(canonical_text, ...)` rồi `sha256(ciphertext)` → `ciphertext_digest` — TỪ CHÍNH ciphertext nó vừa tạo (không đổi từ Correction #10) | Service | Giữ nguyên tính chất đã được CA chấp nhận ở Review #9/#10 |
| 6. Service build transcript 17 field + HMAC ký bằng key CHỈ nó đọc được | Service | Key không tồn tại trong bất kỳ process nào khác |
| 7. DB (`record_sample`) verify chữ ký + đối chiếu TOÀN BỘ field (không đổi cơ chế verify, chỉ thêm T10-04) | DB (definer) | Lớp phòng thủ thứ 2 độc lập với service |

Kết quả: 3 lớp độc lập (kiểu dữ liệu Python tại `sign_capture()`, cô lập process/IPC tại service
boundary, verify HMAC+field tại DB) cùng phải bị phá mới tái tạo được exploit CA mô tả — không còn
1 điểm caller-supplied duy nhất nào quyết định "signer tin plaintext nào".

**Adversarial test mới theo yêu cầu CA (Review #10 §F-M4-0P-T10-01/02)**: gọi `sign_capture()` với
`plaintext_canonical` = B nhưng cố truyền `canonical_digest` của A — KHÔNG CÒN gọi được (TypeError,
tham số không tồn tại) — xác nhận bằng kiểm tra chữ ký hàm trong `crypto_test`/`sign_capture` docstring
và bằng việc toàn bộ 512 test cũ trong `permissions_test.py` (dùng `_sign_test_transcript()` helper,
tự build transcript giả để test DB verify) tiếp tục PASS vì helper đó build transcript độc lập với
`sign_capture()` thật — hai đường kiểm tra bổ sung nhau (Python-level exploit bị chặn ở
`sign_capture()`; DB-level forgery vẫn bị chặn ở `record_sample()` như trước). Test collector
process không đọc được key: xác nhận bằng review code (không còn dòng nào set
`settings.m4_transcript_hmac_key_b64`/`m4_sample_key_b64` trong đường chạy collector của
`kill_test.py`/`sampling_test.py`) — chỉ service subprocess (spawn qua
`_stage0p_signing_service_helper.py`, nhận key qua env riêng) mới có key.

## 4. Bug tự phát hiện trong lúc triển khai (khai báo minh bạch)

1. **Postgres superuser bypass `SET ROLE` qua `REVOKE` — phát hiện khi thiết kế test T10-03 [10]**
   (business_role `SET ROLE` thất bại sau pin thành công). Thiết kế ban đầu dùng
   `REVOKE alpha3s_m4_control_plane FROM alpha3s` (role login của `DATABASE_URL`) kỳ vọng
   `SET ROLE` sau đó thất bại — nhưng xác nhận bằng thực nghiệm `psql` trực tiếp: superuser BỎ QUA
   hoàn toàn kiểm tra role-membership cho `SET ROLE` (REVOKE thành công, `SET ROLE` vẫn thành công,
   chỉ có WARNING, không có lỗi) — vì `alpha3s` là superuser (`rolsuper=t`, xác nhận qua
   `pg_roles`). Sửa: đổi sang `ALTER ROLE ... RENAME TO ...` (đổi tên tạm role mục tiêu) — đây là
   lỗi resolve TÊN, không phải kiểm tra quyền, nên superuser KHÔNG bypass được. Ngược lại, test
   T10-03 [11] (thu hồi `EXECUTE` trên `m4_stage0p_unpin_actor()` từ `alpha3s_m4_actor_binder`)
   hoạt động đúng NGAY LẦN ĐẦU vì `alpha3s_m4_actor_binder` là role KHÔNG superuser thật
   (`rolsuper=f`) — sau khi 1 connection chạy `SET ROLE alpha3s_m4_actor_binder`, các kiểm tra
   quyền TIẾP THEO (như `EXECUTE`) được đánh giá theo quyền của role ĐÓ, không phải superuser gốc
   — REVOKE có hiệu lực thật. Đây là hiện tượng THẬT của Postgres (không phải bug code), ghi nhận
   lại để tránh lặp lại nhầm lẫn khi thiết kế test failure-injection tương lai dùng `alpha3s`
   (superuser) làm connection admin.
2. **T10-04 thứ tự kiểm tra sai (structural trước temporal)** — thiết kế ban đầu đặt 2 check MỚI
   (`expires_at > issued_at`, TTL ≤ 60s) SAU 2 check temporal cũ (`expires_at < now()`,
   `issued_at > now()+5s`) — khiến kịch bản test "`expires_at` trước `issued_at`" (dựng bằng cách
   đặt `expires_at` lùi 30 giây so với `issued_at`, đồng thời cả hai đều ở QUÁ KHỨ so với `now()`)
   trúng nhầm check "transcript đã hết hạn" trước, sai với thông điệp lỗi kỳ vọng. Phát hiện ngay
   khi chạy evidence lần đầu (message lỗi không khớp `_t8_expect_raise`). Sửa: đảo thứ tự trong
   migration — check structural/malformed (`expires_at > issued_at`, TTL) chạy TRƯỚC 2 check
   temporal `now()`-relative. Xác nhận đúng cho cả 5 kịch bản mới `[k]`-`[o]` sau khi sửa.
3. **Docker Desktop crash toàn bộ (Secrets Engine, sự cố hạ tầng mới, khác với sự cố daemon-drop
   Correction #10)** — `docker ps` báo lỗi kết nối; xác nhận `Get-Process -Name "*docker*"` KHÔNG
   có tiến trình nào (crash hoàn toàn, không phải daemon giật). Thử khởi động lại Docker Desktop
   lộ ra nguyên nhân gốc: file socket Unix `C:\Users\Admin\AppData\Local\docker-secrets-engine\
   engine.sock` (đối tượng đặc biệt do WSL2 quản lý) bị hỏng/mồ côi phía NTFS Windows — không thể
   xoá bằng CẢ 3 cách (`Remove-Item -Force`, `cmd /c rmdir /s /q`, `rm -fv` qua Git Bash) đều thất
   bại vì cùng 1 nguyên nhân (metadata filesystem hỏng, `ls -la` cho toàn bộ trường `-?????????`).
   Không phải lỗi logic code — cần can thiệp cấp Windows (restart, `wsl --shutdown`, hoặc factory
   reset Docker Desktop). PO khởi động lại máy, sự cố tự phục hồi; containers M4 khởi động lại
   bằng `docker start`, DB/Redis reset THẬT SỰ SẠCH rồi chạy lại TOÀN BỘ evidence từ đầu (không tin
   kết quả PASS trước sự cố). Đúng hiện tượng CLAUDE.md mục 6 đã ghi nhận (Docker Desktop trên máy
   dev có thể bất ổn), nay thêm 1 biến thể cụ thể (Secrets Engine/socket mồ côi) vào kinh nghiệm đã
   biết.
4. Ruff: 3 import-block chưa sort đúng (`app/services/pii/stage0p_sampling.py`,
   `scripts/m4_stage0p_kill_test.py`, `scripts/m4_stage0p_sampling_test.py`) sau khi thêm import
   `stage0p_signing_client`/`_stage0p_signing_service_helper` — sửa bằng `ruff check --fix`, xác
   nhận lại evidence script liên quan (`kill_test.py`, `sampling_test.py`) vẫn PASS sau khi sửa.

## 5. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`; Docker Desktop crash toàn bộ giữa phiên làm việc — restart cấp Windows do PO thực hiện, containers khởi động lại bằng `docker start`, không mất dữ liệu do reset lại từ đầu ngay sau; DB reset từ `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` rồi `migrate.py up` lại từ đầu ngay trước loạt chạy cuối, kể cả sau khi `ruff --fix` sửa import)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` + `migrate.py up` (001..039 từ trạng thái sạch thật sự) | 0 | `OK 039_m4_stage0p`, postcondition PASS ngay lần đầu (schema/TTL/encryption_key_version check mới không phá vỡ postcondition có sẵn) |
| 2 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS — 8 kịch bản T8-02 gốc `[a]`-`[j]` + 5 kịch bản T10-04 mới `[k]`-`[o]` (malformed timestamp, excessive TTL, unknown field, missing field, encryption_key_version confusion) đều đúng message lỗi kỳ vọng |
| 3 | `m4_stage0p_pool_test.py` | 0 | RESULT: PASS — 11 nhóm kịch bản (giữ nguyên `[1]`-`[9]` + MỚI `[10]` T10-03 business_role `SET ROLE` thất bại sau pin thành công (qua `ALTER ROLE RENAME`, xem §4 mục 1) + `[11]` T10-03 safety-unpin failure fail-closed (qua `REVOKE EXECUTE`)); cả 2 xác nhận actor B nhận connection sạch ngay sau |
| 4 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — 9 kịch bản REV3 không đổi hành vi; LẦN ĐẦU thật sự đi qua kiến trúc T10-02 (spawn signing service subprocess thật, IPC Unix socket thật, 2 sample ký thành công qua round-trip) |
| 5 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J, bao gồm kịch bản race nhạy thời gian `[G]`) — round-trip qua signing service subprocess thật |
| 6 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS — không đổi (không gọi `record_sample`/`sign_capture`, seed trực tiếp bằng SQL, xác nhận qua rà soát code không đụng đường T10) |
| 7 | `pytest -q` (full, lần 1 — trước `ruff --fix`) | 0 | **241 passed** |
| 8 | `ruff check app/services/pii/ app/config.py scripts/m4_stage0p_*.py scripts/_stage0p_signing_service_helper.py tests/test_m4_*.py` (lần 1) | 1 | 3 lỗi import-sort (xem §4 mục 4) |
| 9 | `ruff check --fix` (cùng phạm vi) | 0 | 3/3 fixed |
| 10 | `ruff check` (lần 2, xác nhận) | 0 | All checks passed |
| 11 | Reset DB/Redis sạch lại + `migrate.py up` + `m4_stage0p_kill_test.py` + `m4_stage0p_sampling_test.py` (rerun sau `ruff --fix`, xác nhận đổi import không phá hành vi) | 0 | RESULT: PASS cả 2 (không lặp lại toàn bộ 6 script — chỉ 2 script chứa file bị `ruff --fix` sửa) |
| 12 | `pytest -q` (full, lần 2 — sau `ruff --fix`, xác nhận cuối) | 0 | **241 passed** (không đổi — T10-01/02/03/04 chỉ chạm crypto signing/IPC boundary/pool wrapper/DB function, không chạm logic thuần đã có unit test) |
| 13 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` tự xác nhận `capture_enabled=False` trước khi kết thúc |

**Sự cố hạ tầng giữa phiên làm việc**: Docker Desktop crash TOÀN BỘ (không phải daemon-drop như
Correction #10) — nguyên nhân gốc là file socket `docker-secrets-engine\engine.sock` mồ côi/hỏng
phía Windows, không xoá được bằng bất kỳ công cụ Windows/Git Bash nào sẵn có (xem §4 mục 3 chi
tiết). Cần can thiệp cấp Windows — PO khởi động lại máy, xác nhận `docker ps` hoạt động lại, 3
container M4 khởi động bằng `docker start alpha3s-m4-db alpha3s-m4-redis alpha3s-m4-test`, reset
DB/Redis THẬT SỰ SẠCH rồi chạy lại TOÀN BỘ evidence từ đầu (không tin kết quả PASS trước sự cố).
Ghi nhận thêm vào kinh nghiệm CLAUDE.md mục 6 (Docker Desktop trên máy dev có thể bất ổn) — không
phải lỗi logic code.

## 6. Known limitations (không đổi so với Correction #10 §6, cộng thêm)

30. **T8-02 giờ đóng ở mức: bind CIPHERTEXT (từ Correction #10, không đổi) + signer tự derive
    TOÀN BỘ canonical metadata + boundary process/IPC tách biệt thật (T10-01/T10-02, round này)**
    — nhưng vẫn dùng khoá ĐỐI XỨNG (HMAC), đúng Hướng 3 CA đã chốt cho dev/test, **KHÔNG đủ cho
    production**. Bất kỳ ai đọc được `M4_TRANSCRIPT_HMAC_KEY_B64` từ environment của TIẾN TRÌNH
    SIGNING SERVICE (không còn là collector process, nhưng vẫn là 1 process trên cùng host trong
    mô hình dev/test hiện tại) đều giả mạo được transcript; không có non-repudiation. TRƯỚC
    production-data-access/activation PHẢI chuyển sang chữ ký bất đối xứng (Ed25519/tương đương)
    với private key trong KMS/HSM/Vault Transit thật, VÀ signing service phải chạy trên
    host/container/quyền hệ điều hành KHÁC với mọi worker khác — không chỉ process khác trên cùng
    máy dev. Không đổi so với giới hạn #30 Correction #10 về việc `pgsodium` CHƯA được duyệt.
31. **T9-01/T10-03 đóng đúng lớp truy cập đi qua `pinned_actor_session()`** — nếu code tương lai
    bypass wrapper (tự `pool.acquire()`/`pool.release()` trực tiếp), lỗ hổng quay lại. Không đổi
    so với giới hạn #31 Correction #10.
32. **T9-03 (P1 activation blocker) — CHƯA đóng, đúng theo khung CA đặt ở Review #9/#10**:
    `staff_id`/`pin_secret` vẫn do caller truyền trực tiếp, KHÔNG derive từ authenticated
    principal/JWT/session. Không đổi nội dung so với giới hạn #32 Correction #10 — CA cho phép giữ
    cơ chế này CHỈ trong synthetic dev/test.
33. Ngưỡng gate T4-05/T6-03 (10%/200, `gate_version=ca-review-4-proposed-v1`) — không đổi, vẫn là
    đề xuất CA, CHƯA có PO decision record chính thức.
34. **MỚI — signing service hiện chạy như subprocess trên CÙNG HOST với collector trong mô hình
    dev/test** (spawn bằng `python -m app.services.pii.stage0p_signing_service`, giao tiếp qua
    Unix domain socket cục bộ) — đây là ranh giới process/quyền hệ điều hành THẬT (đóng đúng yêu
    cầu T10-02 cho dev/test), nhưng KHÔNG phải ranh giới mạng/host thật như 1 dịch vụ ký production
    cần có (network policy, service credential riêng, audit truy cập độc lập hạ tầng). Trước
    production: service phải chạy trên host/container tách biệt với network policy giới hạn CHỈ
    collector gọi được đúng operation, không dùng Unix socket cục bộ dev/test này.

## 7. Đề nghị

CA review Correction #11 đối chiếu `T10-01` (signer tự derive canonical_digest/len/truncated từ
plaintext, không còn tin caller), `T10-02` (signing service tách process thật qua Unix socket
IPC, key chỉ tồn tại trong environment của service, collector không đọc được), `T10-03` (mọi lỗi
sau `pool.acquire()` trong `__aenter__()` đi qua cùng cleanup/discard primitive với `__aexit__()`,
safety-unpin fail-closed) và `T10-04` (DB enforce `expires_at > issued_at` + TTL 60s + strict
schema allowlist 17 field + `encryption_key_version` tách biệt `key_version`). `T9-03` giữ nguyên
trạng activation blocker theo đúng khung CA đã đặt — không xin đóng finding này round này. Không
xin quyền production-data-access/activation — gate đó vẫn tách riêng theo Design Acceptance §6.
