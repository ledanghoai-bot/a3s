---
document_id: PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-PACKAGE-2-VI
title: "Phase 1B M4 — Dev Internal Synthetic Rehearsal Readiness Package #2"
document_type: rehearsal_readiness_package
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-08-05
answers: PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-REVIEW-1-VI.md (CA, CHANGES_REQUIRED_ACTIVATION_NOT_AUTHORIZED)
supersedes: PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-PACKAGE-VI.md (v1)
production_baseline: e96a32079bffedc8f6dbdeb3bc2006f2cf5ef77a
activation_performed: false
activation_gate: NOT_OPEN
language: vi-VN
---

# M4 — Internal Synthetic Rehearsal Readiness Package #2

Đáp lại `PHASE1B-M4-INTERNAL-SYNTHETIC-REHEARSAL-READINESS-REVIEW-1-VI.md`
(`CHANGES_REQUIRED_ACTIVATION_NOT_AUTHORIZED`). Gói #1 xác nhận nền tảng tốt nhưng có 7 finding
P1 cần sửa trước khi mở gate. Gói #2 này trả lời TỪNG finding bằng code thật + evidence chạy
thật (không chỉ thiết kế trên giấy) — khác gói #1 vốn chỉ có hồ sơ + generator, gói #2 có thêm
**runner hoàn chỉnh đã chạy thành công full lifecycle thật trên sandbox cô lập**, bao gồm 1
signing service thật, 220 conversation thật, và evaluation_completed thật.

## 0. Xác nhận phạm vi — vẫn CHƯA activation

Đúng theo Directive §3 và Review #1 §5: **CHƯA** seed production, **CHƯA** provision key/
credential trên production, **CHƯA** khởi chạy signer/collector trên production, **CHƯA** bật
`m4_stage0p_control.capture_enabled` trên production. Toàn bộ evidence trong gói này chạy trên
**2 container Postgres/Redis cô lập, tạo mới hoàn toàn cho lần kiểm thử này**
(`alpha3s-rehearsal-test-db`/`alpha3s-rehearsal-test-redis`, cùng docker network với stack chính
nhưng KHÔNG phải `alpha3s-db-1`/`alpha3s-redis-1` — tránh đụng dữ liệu dev cục bộ khác), migrate
từ đầu bằng `scripts/migrate.py up` (39 migration, đúng schema production).

## 1. Tóm tắt thay đổi so với gói #1

| Artifact | Gói #1 | Gói #2 |
|---|---|---|
| Manifest generator | v1, 22 conversation, chỉ đếm `expect` | **v2**, 225 conversation (220 gate-eligible + 5 known-limitation), mỗi message có `labeled_slots` — offset THẬT tính qua `app.services.pii.canonicalize.canonicalize()` + `str.find()`, xác minh lại bằng `validate_spans()`/regex detector thật (0 lỗi trên 221 span) |
| Runner (`scripts/m4_stage0p_rehearsal_runner.py`) | Chưa viết | **778 dòng, hoàn chỉnh** — subcommand `record-approval`/`provision-keys`/`retire-keys`/`run --dry-run`/`run` |
| Test/evidence (`scripts/m4_stage0p_rehearsal_runner_test.py`) | Chưa có | **536 dòng, 6 kịch bản**, bao gồm 1 lần chạy **FULL LIFECYCLE THẬT** (signing service thật, 225 conversation, evaluation_completed thật) |
| Phạm vi lifecycle | Đề xuất dừng ở seal (A1-only) | **Full lifecycle** (capture→seal→predict→evaluate) — theo đúng khuyến nghị CA, không dùng bypass ngưỡng 10%/200 |

## 2. Trả lời từng finding

### F-M4-RH-R1-01 — Hard fence

`_seed_synthetic()` insert customers/conversations/messages TỪ MANIFEST, ghi lại CHÍNH XÁC ID
Postgres cấp ra vào `RehearsalState`. `lock_batch` (viết lại trực tiếp trong runner, KHÔNG gọi
`select_eligible_conversations`) nhận `locked_conversation_ids` CHỈ TỪ danh sách ID đã tracked
— về cấu trúc, một conversation không nằm trong danh sách này KHÔNG THỂ vào được batch, không
phụ thuộc cửa sổ thời gian. `_assert_batch_isolated()` join lại `locked_conversation_ids` →
`customers.psid`, abort (`SystemExit`) nếu count sai hoặc bất kỳ psid nào không đúng tiền tố —
chạy TRƯỚC khi gọi `set_capture_enabled`.

**Evidence:** kịch bản `[2]` trong test script — seed 1 conversation "khách thật" (psid
`1234567890123_real_facebook_psid`, KHÔNG mang marker) trong cùng thời điểm; xác nhận (a) nó
không nằm trong `state.conversation_ids` (chứng minh cấu trúc), và (b) khi CỐ TÌNH chèn nó vào
1 state giả để mô phỏng bug tương lai, `_assert_batch_isolated()` abort ngay — PASS.

### F-M4-RH-R1-02 — Key provisioning đúng version

Đọc TRỰC TIẾP 3 hằng số đã hardcode trong code đã merge (không tự đặt tên mới):
`ENCRYPTION_KEY_VERSION = "sample-aead-v1"` (`crypto.py`, không cần provisioning DB — chỉ là
nhãn trong transcript), `TRANSCRIPT_KEY_VERSION = "sample-transcript-hmac-v1"` (`crypto.py`,
bảng `m4_stage0p_transcript_signing_keys`), `_SIGNING_AUTH_KEY_VERSION = "m4-signing-auth-v1"`
(`stage0p_signing_service.py`, bảng `m4_stage0p_signing_auth_keys`). Subcommand `provision-keys`/
`retire-keys` kết nối bằng chính `DATABASE_URL` (superuser/admin — đúng mô hình 2 bảng này đã
document "provisioning ngoài luồng qua superuser, không qua role/hàm được GRANT"), precheck từ
chối ghi đè nếu key đang active (không overwrite âm thầm), evidence/log chỉ ghi key_version,
không bao giờ ghi giá trị khoá.

**Evidence:** kịch bản `[1]`/`[5]`/`[6]` — `provision-keys` thành công, `retire-keys` idempotent,
precheck từ chối ghi đè (chứng minh gián tiếp qua kịch bản `[5]` cần retire trước khi `[6]`
provision lại — nếu precheck không hoạt động thì bước đó sẽ không cần thiết).

### F-M4-RH-R1-03 — Labeling workflow + reviewer principal riêng

`_label_samples()` chạy dưới `pinned_actor_session(..., business_role=SAMPLE_REVIEWER_API)` —
principal RIÊNG (`--reviewer-staff-id`, permission `m4.stage0p.review`), tách khỏi operator.
Đọc lại sample đã capture qua `customer_ref`/`conversation_ref` (DB tự derive = `str(id)`), map
ngược về `conversation_key` qua `RehearsalState`, UPDATE `labeled_slots`/`label_status='labeled'`
bằng **ground truth từ manifest** (KHÔNG chạy `detect()` — tránh detector tự chấm điểm chính
nó). Assert cứng: mỗi conversation trong manifest CHỈ có đúng 1 message (self-discovered — xem
§4.1), nên mapping sample↔ground-truth luôn 1-1, không cần đoán qua thứ tự `captured_at`.

**Evidence:** kịch bản `[6]` — `labeling_done: labeled_count=225`, `labels_sealed` thành công
(seal chỉ thành công khi 0 sample unlabeled — đúng `m4_stage0p_seal_labels` DB-side).

### F-M4-RH-R1-04 — Runner hoàn chỉnh

`scripts/m4_stage0p_rehearsal_runner.py` (778 dòng). State machine đầy đủ: preflight (`--dry-run`,
0 ghi DB) → seed → fence → capture ON → lock batch → collect (có retry, xem §4.1) → label →
seal → predict → evaluate → **`finally` VÔ ĐIỀU KIỆN**: capture OFF → key retire → purge (theo
ID tracked) → Redis nonce postcheck. Không sửa bất kỳ file production nào (`stage0p_sampling.py`/
`stage0p_signing_service.py`/migration 039 nguyên vẹn) — chỉ gọi lại các hàm nội bộ đã CA nghiệm
thu, đúng F-04 yêu cầu.

**Evidence:** kịch bản `[5]` — ép collector thất bại THẬT giữa chừng (thiếu signing socket, sau
khi capture đã ON và đã seed 3 conversation) — xác nhận `finally` vẫn đưa `capture_enabled` về
`false`, 0 residual, cả 2 key retired. Kịch bản `[6]` — full run thành công, `finally` cũng chạy
sạch ở nhánh THÀNH CÔNG (không chỉ nhánh lỗi).

### F-M4-RH-R1-05 — Full lifecycle, không dùng bypass ngưỡng

Theo đúng khuyến nghị CA §4 ("Hướng ưu tiên... tăng synthetic dataset đủ >=200 và chạy full
lifecycle"): manifest v2 có **220 conversation gate-eligible** (>200, có headroom so mức tối
thiểu; CA khuyến nghị 220, manifest đạt đúng 220), runner mặc định chạy XUYÊN SUỐT tới
`run_prediction_writer`/`complete_evaluation` — KHÔNG dừng ở seal, KHÔNG sửa/nới singleton
`m4_stage0p_exclusion_gate`, KHÔNG thêm bất kỳ logic phân biệt "tier" nào trong code production.

**Evidence:** kịch bản `[6]` — chạy THẬT với 1 signing service thật (không mock), 225 conversation
(220 gate + 5 known-limitation) đi hết qua `write_predictions` (vượt ngưỡng 10%/200 hiện có mà
KHÔNG cần thay đổi gì) và `complete_evaluation` — batch cuối cùng có
`evaluation_completed_at`/`evaluation_report_hash` THẬT (không phải giả định), xác nhận bằng
SELECT độc lập sau khi CLI thoát.

### F-M4-RH-R1-06 — Redis: SCAN, không KEYS

`_postcheck_redis_nonces()` dùng `redis.scan(cursor=..., match="m4-signing-nonce:*", count=100)`
(cursor-based, non-blocking), CHỈ để xác minh/log (đếm + lấy mẫu TTL), KHÔNG bao giờ gọi `DEL` —
nonce tự hết hạn qua TTL sẵn có (`_NONCE_TTL_BUFFER_SECONDS`, tối đa ~90s). Có backstop cứng
(dừng nếu quét quá 100k key) tránh quét vô hạn.

**Evidence:** log `redis_nonce_postcheck` trong kịch bản `[6]` — `remaining_count` + mẫu TTL
(giây) của từng key, xác nhận toàn bộ có TTL dương (đang đếm ngược tự nhiên, không phải residual
vĩnh viễn).

### F-M4-RH-R1-07 — 3 principal tách biệt, credential riêng

`_assert_distinct_principals()` (gọi ngay đầu `run`) từ chối (`SystemExit`) nếu bất kỳ 2
staff_id nào trùng nhau. 3 pin_secret đọc từ 3 biến môi trường RIÊNG
(`STAGE0P_REHEARSAL_APPROVAL_PIN`/`_OPERATOR_PIN`/`_REVIEWER_PIN`) — không bao giờ qua CLI
argument (tránh lộ process list/shell history), không bao giờ log. `record-approval` là
subcommand TÁCH RIÊNG khỏi `run` — runner không tự record approval bằng credential operator
(đúng yêu cầu CA "runner không được tự record approval bằng credential của control operator");
approval recorder phải tự chạy subcommand này với credential của chính họ, độc lập với người
vận hành `run`.

**Evidence:** kịch bản `[3]` — `_assert_distinct_principals(101, 101)` raise; 3 giá trị phân
biệt không raise. Kịch bản `[1]`/`[6]` — toàn bộ chạy với 3 staff_id/pin_secret thật sự khác
nhau (tạo qua `staff_users`/`m4_stage0p_staff_permissions`/`m4_stage0p_actor_credentials` riêng
biệt).

## 3. Trả lời 2 hướng dẫn CA (§4 Review #1)

**Ngưỡng 10%/200:** đã áp dụng đúng hướng CA ưu tiên — KHÔNG sửa singleton gate, KHÔNG thêm
bypass. Manifest mở rộng lên 220 gate-eligible (đúng khuyến nghị) và runner chạy full lifecycle
thật, xác nhận vượt ngưỡng tự nhiên (§2, F-05 ở trên).

**Signer/collector isolation:** giữ nguyên mô hình OS-UID/group (T12-01) cho rehearsal synthetic
— CA đã xác nhận chấp nhận được cho phạm vi này ("Distinct Unix UID/group trên cùng VPS được
chấp nhận cho synthetic-only rehearsal với approval hữu hạn"). Evidence `[6]` chạy signing
service ở chế độ đơn-UID đơn giản (không cần dual-UID đầy đủ cho kiểm thử chức năng runner —
dual-UID đã evidence riêng ở Correction #13); khi thực thi THẬT trên VPS, runner sẽ dùng đúng
`ensure_service_accounts()`/`start_signing_service(..., run_as_uid=..., shared_gid=...)` đã có
sẵn trong `scripts/_stage0p_signing_service_helper.py` (không cần code mới).

## 4. Self-discovered trong lúc chạy evidence thật (KHÔNG có trong gói #1, chỉ lộ ra khi chạy)

### 4.1. `seed_capture_progress()` capture TỐI ĐA 20 message/conversation, không phải 1

`m4_stage0p_seed_capture_progress()` seed MỌI message `role='customer'` trong 1 conversation
(tối đa 20, `ROW_NUMBER() OVER (PARTITION BY conversation_id...)`), không giới hạn 1. Manifest
v1 có conversation combo 2-message (1 message "đặt hàng" + 1 message chứa PII) — nếu chạy thật,
CẢ HAI sẽ được capture thành 2 sample riêng, nhưng `m4_shadow_review_samples` KHÔNG có cột
`message_id` để phân biệt sample nào khớp message nào (chỉ có `customer_ref`/`conversation_ref`)
— labeling sẽ map sai. Sửa ở generator v2: MỌI conversation chỉ có ĐÚNG 1 message — loại bỏ
nguồn gốc vấn đề thay vì đoán qua thứ tự `captured_at`/`canonical_text_len`. `_label_samples()`
assert cứng số message/sample = 1 mỗi conversation, để lộ lỗi ngay nếu manifest tương lai vi
phạm bất biến này thay vì âm thầm gán sai nhãn.

### 4.2. Rate limit T13-03 (40 request/10s) crash `run_collector()` khi xử lý batch lớn tuần tự

`run_collector()` (gốc, không sửa) xử lý TUẦN TỰ, nhanh hơn tốc độ sustained mà admission budget
cho phép — 1 request bị rate-limit reject giữa chừng gây `ConnectionResetError` không được
`asyncio.wait_for` bắt (chỉ bắt `asyncio.TimeoutError`), crash thẳng ra ngoài. Với manifest
>=220 message xử lý tuần tự, lần chạy đầu GẦN NHƯ CHẮC CHẮN chạm giới hạn trước khi xong.
**Sửa ở TẦNG RUNNER** (code mới, không đụng `stage0p_sampling.py`): `_run_collector_with_retry()`
gọi lại `run_collector()` nhiều lần, mỗi lần tiếp tục từ `m4_stage0p_capture_progress` còn lại
(idempotent — sample đã `committed` không bao giờ bị xử lý lại), nghỉ 11s (> cửa sổ rate-limit)
giữa các lần, dừng nếu 2 lần liên tiếp không giảm được số pending (dấu hiệu lỗi thật, không phải
rate-limit tạm thời). Evidence `[6]`: chạy thành công, 225/225 conversation capture xong.

### 4.3. Prediction writer cần `M4_SAMPLE_KEY_B64` trong CHÍNH môi trường runner, không chỉ signing service

`run_prediction_writer()` gọi `decrypt_sample_value()` TRỰC TIẾP trong tiến trình runner (không
qua signing service — đúng thiết kế, decrypt để evaluate là vai trò khác với encrypt lúc capture)
— cần `settings.m4_sample_key_b64` đọc từ MÔI TRƯỜNG CỦA RUNNER, không phải chỉ môi trường
signing service subprocess. Đã bổ sung vào hướng dẫn vận hành §C dưới đây — người vận hành `run`
(execute) cần set `M4_SAMPLE_KEY_B64` trong shell của họ (khớp key đã provision), không chỉ khi
gọi `provision-keys`.

## 5. Evidence log tóm tắt

| Hạng mục | Kết quả |
|---|---|
| Full pytest suite (`tests/`) | **241 passed** (sandbox riêng, unrelated tới thay đổi — xác nhận không hồi quy) |
| `ruff check app` | All checks passed (không đụng `app/`) |
| `ruff check scripts/m4_stage0p_{gen_rehearsal_manifest,rehearsal_runner,rehearsal_runner_test}.py` | All checks passed |
| Evidence M4 hiện có (`migration_test`/`sampling_test`/`kill_test`/`permissions_test`/`evaluation_test`/`pool_test`) | RESULT: PASS (cả 6 script, baseline không đổi) |
| `m4_stage0p_rehearsal_runner_test.py` (MỚI) | **RESULT: PASS**, 6/6 kịch bản (§2 ở trên) |
| Manifest v2 sha256 | `5f0f92dbd311d0a4c7d309c01c86b958c81f32126ee531694f4b43a23c54bce5` (225 conversation, 245→225 message sau sửa §4.1, 221 labeled span, 0 lỗi `validate_spans`/regex đối chiếu) |
| `scripts/m4_stage0p_rehearsal_runner.py` sha256 | `016379f734c218504c2575947db9370e9948287632907dcb9b8328140f17a59e` (778 dòng) |
| `scripts/m4_stage0p_gen_rehearsal_manifest.py` sha256 | `75ad5858f72c8ac1096e45cd3ad8fd758bff078314ed232c42525fb5649e2714` (390 dòng) |
| `scripts/m4_stage0p_rehearsal_runner_test.py` sha256 | `343e5099ca15f9fb41300c29e99e8ccb7244d8a93ee2e2c83ff88073c0434602` (536 dòng) |
| Sandbox dùng cho evidence | `alpha3s-rehearsal-test-db`/`alpha3s-rehearsal-test-redis` (container cô lập, tạo mới, KHÔNG phải `alpha3s-db-1`/`alpha3s-redis-1` cục bộ) |

## 6. PR / head để CA review code

Đúng F-04 §5 mục 2 ("PR/head của reviewed runner + generator + immutable manifest"): 3 file
(`scripts/m4_stage0p_gen_rehearsal_manifest.py`, `scripts/m4_stage0p_rehearsal_runner.py`,
`scripts/m4_stage0p_rehearsal_runner_test.py`) + manifest (`datasets/pii/
m4_stage0p_rehearsal_manifest_v2.jsonl`) + gói hồ sơ này được đóng gói trong **1 PR draft riêng**:

| Mục | Giá trị |
|---|---|
| PR | [ledanghoai-bot/a3s#6](https://github.com/ledanghoai-bot/a3s/pull/6) (`draft`) |
| Branch | `feat/m4-rehearsal-operational-tooling` |
| Base | `main`@`e96a32079bffedc8f6dbdeb3bc2006f2cf5ef77a` |
| Commit | `da1d0a53a12550e6dbc4f59557225f1a80cba979` |
| CI run | `31006802965` — `lint-test`: **success**; `deploy`: **skipped** (đúng CR-07, PR không trigger deploy) |

**KHÔNG merge** cho tới khi CA review code xong (đúng văn hoá của toàn bộ dự án M4: mọi thay đổi
qua PR/CI/CA review trước khi vào `main`, kể cả code KHÔNG đụng gì tới production path).

## 7. Đề nghị

CA review code tại PR/head sẽ cung cấp, đối chiếu với §2 (7 finding) + §3 (2 hướng dẫn) + §4 (3
self-discovered) ở trên. Sau khi CA chấp nhận, PO ra quyết định `approval_ref`/window/scope
chính thức (qua `record-approval` subcommand, thực hiện bởi chính PO hoặc staff PO chỉ định —
KHÔNG phải Dev) trước khi CA mở Internal Synthetic Activation Gate. Dev **không** suy diễn quyền
activation từ việc nộp gói này — toàn bộ evidence trong gói chạy trên sandbox cô lập, chưa chạm
production dưới bất kỳ hình thức nào.
