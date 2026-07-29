---
id: A3S-PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-001
title: Alpha3S Phase I-B M4 — Stage 0P Governance Package (Production Shadow Request)
document_type: governance_request_package
owner: Dev
status: CA REVIEW #1 CHANGES_REQUIRED (29/7 08:30) — 4 finding P1 đã sửa trong bản này (v2), chờ CA review lại
created_at: 2026-07-29 06:17+07:00
last_updated: 2026-07-29 09:10+07:00
version: 2.0.0 — Correction #1 theo PHASE1B-M4-STAGE-0P-GOVERNANCE-REVIEW-1-VI.md
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_directive: A3S-PHASE1B-M4-DEV-DIRECTIVE-001 v1.1.0 §6, §7
base_reference: CA Development Acceptance Closure (M4-S0..S3 ACCEPTED, evidence 5fee922, package cebbd68)
language: vi-VN
---

# Alpha3S Phase I-B M4 — Stage 0P Governance Package

## 0. Bản chất tài liệu này

Đây là **đề nghị (request), không phải quyết định tự cấp phép**. Dev soạn gói này theo đúng
danh mục Directive §6 để PO/CA có đủ thông tin phê duyệt hoặc từ chối. **Không có dòng code,
migration, flag hay hạ tầng nào bị thay đổi khi soạn tài liệu này.** Nếu được duyệt, bước triển
khai kỹ thuật (migration Slot Store cho sample zone, bật `m4_pii_shadow=true` trên tập con
traffic) là một submission riêng, có evidence riêng, sau khi có approval record bằng văn bản.

**Cập nhật 29/7 07:43 — PO đã ra quyết định cho 4/6 mục ở §10.**

**Cập nhật 29/7 08:30 — CA Review #1** (`PHASE1B-M4-STAGE-0P-GOVERNANCE-REVIEW-1-VI.md`):
**CHANGES_REQUIRED**. CA đã chốt được nhiều điểm:
- Purpose code `P12_PII_DETECTOR_EVAL`: **ACCEPTED** về tên/mục đích/data-class mapping (vẫn
  cần nộp addition kỹ thuật vào registry riêng, không tự ghi ngoài gate).
- Ranh giới vendor: **ACCEPTED có điều kiện** — Stage 0P thuần local không bị chặn bởi gap
  cross-border DeepSeek **nếu không có byte dữ liệu/sample/nhãn nào đi vào vendor path** (điều
  kiện này không tự mở rộng sang canary/enforcement).
- Reviewer + cơ sở pháp lý: CA **ghi nhận quyết định PO**, không tái quyết định thẩm quyền PO.
- Retention 45 ngày: **ACCEPTED về trần kỹ thuật** (nguyên tắc `eval completed OR 45 ngày,
  tuỳ điều kiện nào tới trước` — đúng như §6 đề xuất), nhưng **chỉ có hiệu lực sau khi** thiết
  kế DSR/purge/evidence fail-closed được nghiệm thu (tức phụ thuộc F-M4-0P-04 dưới đây).

CA yêu cầu sửa **4 finding P1** trước khi có thể ra "Stage 0P Design Accepted" — đã sửa trong
bản v2.0.0 này (§4, §5, §6, §7, §9 cập nhật), xem bảng mapping ở §11.

Directive §6 quy định 5 prerequisite phải PASS trước khi mở Stage 0P:

| # | Prerequisite | Trạng thái |
|---|---|---|
| 1 | M3 PII-safe logging control accepted | ✅ **PASS** — S4 áp `safe_log`/`safe_exc` toàn app, guard `scripts/m3_pii_log_test.py` ALL PASS (4 gap HIGH đã đóng; 1 known-limitation PSID-trong-URL-log còn mở, không phải HIGH) |
| 2 | Vendor/AI Use Case review accepted | 🟡 **PASS CÓ ĐIỀU KIỆN** — xem §1 (Stage 0P không gọi vendor nên gap cross-border DeepSeek không block trực tiếp; cần UC mới, đề xuất ở §2) |
| 3 | Production-data access approved PO/CA | ⏳ **ĐANG XIN** — chính là mục đích gói này |
| 4 | Retention/labeling environment verified | ⏳ **THIẾT KẾ TRONG GÓI NÀY** — xem §5, §6 (RET-11 trong Retention Schedule hiện chỉ là khung rỗng "thiết kế tại M4") |
| 5 | Rollback/kill switch tested | ✅ **PASS** — `m4_pii_shadow` flag OFF = 0 code path chạy (evidence S0/S3: 214 pytest bao gồm flag-OFF regression, static check orchestrator không tham chiếu `m4_trusted_pii_path`) |

## 1. Vendor/AI Use Case — làm rõ ranh giới (prerequisite #2)

- **Stage 0P (shadow mode) không gọi vendor DeepSeek.** Detector `app/services/pii/detector.py`
  là regex/rule thuần, chạy 100% cục bộ trong container API/worker — không có network call ra
  ngoài. Do đó **gap cross-border DeepSeek theo 91/2025/QH15** (Vendor Register, gap #1: "trước
  khi M4 canary") áp dụng cho giai đoạn **canary/enforcement** (khi `m4_trusted_pii_path` bật và
  masked input thật sự đi tới model), **không áp dụng cho Stage 0P**. Đề nghị PO/CA xác nhận
  cách đọc này bằng văn bản để tránh mơ hồ khi review submission sau.
- **AI Use Case Register cần bổ sung UC-004** (file đã tự ghi chú "record mới khi M4 mở" ở
  UC-003 nhưng chưa tồn tại). Đề xuất nội dung UC-004 (Dev soạn, PO/CA duyệt rồi mới ghi chính
  thức vào `AI-USE-CASE-REGISTER.md`):

  | Trường | Giá trị đề xuất |
  |---|---|
  | id | UC-004 |
  | name | PII Detector Shadow Evaluation (M4-S0, Stage 0P) |
  | model_provider | Local (rule/regex, không model học máy, không vendor) |
  | purpose | P12_PII_DETECTOR_EVAL (đề xuất mới, xem §2) |
  | input_data_class | D1_PERSONAL_BASIC + D2_PERSONAL_SENSITIVE (tin nhắn khách trong cửa sổ sample) |
  | output_data_class | D4_DEIDENTIFIED (metric counts/enum) cho vận hành thường trực; labeled sample thô là D1/D2 nhưng **restricted zone riêng**, không phải output vận hành |
  | risk_class | MEDIUM — không gửi vendor, không tác động response khách, nhưng CÓ truy cập nội dung tin nhắn thật để gán nhãn |
  | cross_border | KHÔNG |
  | retention_mode | theo RET-11 (đề xuất cụ thể hoá ở §5) |

## 2. Purpose code + data class (Directive §6 mục 1)

Registry hiện có 11 mã (P01–P11), không mã nào khớp: P07_ANALYTICS định nghĩa rõ là *không*
chạm personal data; P10_AI_PROCESSING dành cho luồng gửi vendor. **Đề xuất thêm mã mới:**

```text
P12_PII_DETECTOR_EVAL
  Mô tả: Lấy mẫu có kiểm soát từ hội thoại thật để gán nhãn thủ công, đo recall/precision
         của PII detector nội bộ (không gửi vendor, không ảnh hưởng response khách).
  Data class: D1_PERSONAL_BASIC, D2_PERSONAL_SENSITIVE (nội dung tin nhắn thô trong sample)
  Cơ sở pháp lý: legitimate interest (cải thiện kiểm soát bảo vệ dữ liệu) — PO ĐÃ DUYỆT
                 (29/7 07:43, mục 6 §10).
  Trạng thái: PO ĐỒNG Ý — chờ CA xác nhận format/tính nhất quán với registry (mục 2 §10)
```

Đây là format khớp các mục hiện có trong `PROCESSING-PURPOSE-REGISTRY.md`. Cơ sở pháp lý đã có
quyết định PO (xem trên); mã purpose và nội dung đăng ký cụ thể vẫn chờ CA xác nhận trước khi
Dev nộp addition chính thức vào registry chung (KHÔNG tự ý sửa file M3 trong lúc soạn gói này).

## 3. Data minimization (Directive §6 mục 2)

- Sample **CHỈ** lấy từ hội thoại **đặt hàng** (order-eligible conversations) — đúng phạm vi
  "200 hội thoại đặt hàng đủ điều kiện" của spec §6/directive §7, không mở rộng sang toàn bộ
  traffic tư vấn.
- **Không** lưu response/tool-call output, chỉ lưu **tin nhắn khách** (input phía cần đo detector).
- **Không** lưu kèm ảnh/attachment nếu có (ngoài phạm vi text detector).
- Loại trừ trước khi vào sample: hội thoại đã có yêu cầu xóa dữ liệu đang chờ xử lý
  (`del_pending:{sender_id}` còn tồn tại) hoặc khách đã từng gửi `XOA DU LIEU` trong 90 ngày gần
  nhất — tránh mâu thuẫn với quyền được quên.
- Sample lưu **tách rời khỏi `messages`/`conversations` chính** (không mở rộng quyền truy cập
  vào bảng vận hành) — xem storage zone §6.

## 4. Sampling method (Directive §6 mục 3) + quy mô đại diện — **sửa theo F-M4-0P-03**

- **Cửa sổ:** 14 ngày liên tục kể từ ngày kích hoạt (đúng ngưỡng khởi điểm spec §6/directive §7).
- **Hard cap tuyệt đối: 260 hội thoại** (200 mục tiêu + 30% buffer cho loại trừ ở bước lọc
  metadata — xem dưới). Sample zone **không bao giờ** chứa quá 260 row bất kể traffic thật cao
  đến đâu.
- **Thuật toán chọn — 2 pha tách bạch, KHÔNG đọc nội dung tin nhắn ở pha 1:**
  1. **Pha chọn (metadata-only):** truy vấn `conversation_id` đủ điều kiện thuần từ **metadata**
     (`orders.created_at` trong cửa sổ + `orders.conversation_id`; loại trừ theo §3 — không đọc
     `messages.content`). Sắp xếp deterministic theo `conversation_id ASC`. Gọi tập này là `E`.
  2. Nếu `|E| ≤ 260`: chọn toàn bộ `E`.
     Nếu `|E| > 260`: chọn 260 phần tử bằng **permutation có seed cố định, công khai, tái lập
     được** — seed = số nguyên suy từ `SHA256("m4-stage0p-v1")` (hằng số ghi trong code khi
     triển khai), KHÔNG dùng `random()` không seed. Cùng `E` + cùng seed ⇒ luôn ra cùng tập chọn
     — kiểm chứng lại được độc lập.
  3. **Chỉ sau khi có tập `conversation_id` cuối cùng (≤260), pha thu thập mới đọc nội dung tin
     nhắn** của đúng các hội thoại đó để mã hoá và ghi vào sample zone. Hội thoại không được
     chọn **không bao giờ** bị đọc nội dung ở bất kỳ bước nào.
  4. Mỗi row lưu `selection_batch = "m4-stage0p-v1"` để truy vết đúng lô/thuật toán đã tạo ra nó.
- **Dưới ngưỡng:** nếu `|E| < 200` khi hết cửa sổ 14 ngày → **dừng, báo cáo, chờ quyết định**
  (không tự gia hạn cửa sổ) — giữ nguyên như bản trước.
- **Metric loại trừ:** chỉ log **counts** (`eligible=N excluded_pending_deletion=K
  selected=M`), không có định danh hội thoại/khách trong log.
- **Tính đại diện dự kiến:** không giữ nguyên bước "chuyển sang stratify theo khung giờ" của bản
  trước (mơ hồ, không tái lập được) — thay bằng permutation seed cố định ở trên, đã tự nhiên bảo
  toàn tỷ lệ kênh (Messenger/Telegram) vì chọn ngẫu nhiên có seed trên toàn bộ `E`, không lọc
  theo kênh trước.

## 5. Labeling roles / access matrix (Directive §6 mục 4) + reviewer audit (mục 7) — **sửa theo F-M4-0P-02**

CA chỉ ra đúng: bản trước vừa cấp `SELECT` trực tiếp cho reviewer vừa nói "phải qua view/API" —
2 điều này mâu thuẫn (SELECT trực tiếp luôn đi vòng được qua bất kỳ view/API nào). Thiết kế lại
với **4 role DB tách biệt**, không role nào (kể cả Dev) có SELECT trực tiếp trên cột dữ liệu thô:

| Role DB | Quyền trên `m4_shadow_review_samples` | Dùng bởi |
|---|---|---|
| `alpha3s_m4_sample_collector` | INSERT-only (không SELECT/UPDATE/DELETE) trên bảng sample; SELECT trên metadata `orders`/`conversations` cần cho pha chọn §4 (không phải `messages.content`) | Job thu thập (batch, không phải request-path) — **là principal DUY NHẤT ghi vào sample zone** |
| `alpha3s_m4_sample_reviewer_api` | SELECT toàn bộ cột (kể cả `encrypted_message`) | **CHỈ credential của tiến trình API nội bộ** (ops endpoint, tái dùng xác thực `staff_users`/`staff_sessions` đã có — `app/services/auth_service.py`). Con người **không bao giờ** cầm credential DB này trực tiếp; PO (reviewer, §10 mục 5) đăng nhập qua session staff như dashboard hiện tại, endpoint dùng role này thay mặt, giải mã, **ghi 1 dòng audit TRƯỚC KHI trả dữ liệu** (fail closed nếu ghi audit lỗi — không trả gì) |
| `alpha3s_m4_sample_evaluator` | SELECT **chỉ cột** `sample_id, label_status, labeled_slots, selection_batch` (column-level GRANT, Postgres hỗ trợ trực tiếp) — **KHÔNG** `encrypted_message`, **KHÔNG** `customer_ref`/`conversation_ref` | Eval script (Dev) đo recall/precision trên nhãn — không cần và không được đọc nội dung thô |
| `alpha3s_m4_sample_purge` | DELETE + SELECT **chỉ** `customer_ref, expires_at, sample_id` (Postgres yêu cầu SELECT trên cột dùng trong `WHERE` của `DELETE`) | Purge job (retention §6 + DSR §7) |
| `alpha3s_app` (runtime) | **KHÔNG có quyền nào** | Sample zone hoàn toàn ngoài request-path production |
| `alpha3s_vendor_path` | **KHÔNG có quyền nào** (REVOKE ALL tường minh, đúng nguyên tắc đã áp cho `pii_slots` 038) | — |

`REVOKE ALL ON m4_shadow_review_samples FROM PUBLIC` là bước đầu tiên của migration khi triển
khai — mọi quyền trên đều là GRANT tường minh, không có quyền ngầm định.

**Cấp/thu hồi quyền con người (không phải quyền DB):** PO (reviewer) được cấp một **permission
RBAC mới** (ví dụ `m4.sample.read`) qua đúng cơ chế `staff_users`/`role_permissions` đã có từ M0
(`app/services/permission_service.py`) — **không tạo cơ chế phân quyền song song**. Permission
này có giới hạn thời gian = đúng cửa sổ Stage 0P (14 ngày thu thập + tối đa 45 ngày retention,
§6) — hết hạn thì permission bị rà soát/thu hồi, không tự động gia hạn. **Break-glass:** nếu cần
truy cập ngoài kế hoạch (vd điều tra sự cố), phải có xác nhận bằng văn bản của PO + đi qua đúng
API audit — không có đường "tắt" bỏ qua audit trong bất kỳ tình huống nào.

**Audit record (tái dùng `audit_service.record()`, KHÔNG tạo bảng audit riêng):** mỗi lần API
trả dữ liệu, ghi 1 dòng `audit_log` với `actor_staff_id` (người), `action='m4_sample_read'`,
`entity_type='m4_shadow_sample'`, `entity_id=sample_id`, `reason=purpose_code`, `after={"outcome":
"success"}` — **payload không bao giờ chứa `encrypted_message`/nội dung** (không cần dựa vào cơ
chế redact theo tên cột như `_SENSITIVE_KEYS`, vì trường đó đơn giản không được đưa vào lời gọi
`record()`). Truy cập bị từ chối (permission thiếu/hết hạn) cũng ghi audit với `outcome=denied`.

## 6. Storage zone + retention/expiry (Directive §6 mục 5, 6) — **sửa theo F-M4-0P-04**

**Thiết kế đề xuất** (triển khai bằng migration RIÊNG, sau khi có approval — không nằm trong gói
này):

- Bảng mới `m4_shadow_review_samples`, **TÁCH HOÀN TOÀN** khỏi `pii_slots` (Trusted Slot Store là
  cho luồng vận hành masked orchestration tương lai, không phải kho lưu để gán nhãn thủ công —
  gộp chung 2 mục đích sẽ làm access matrix rối và khó audit).
- **Crypto: KHÔNG tái dùng nguyên trạng `_aad()` của `pii_slots`.** CA chỉ ra đúng: hàm hiện tại
  bind theo `(customer_ref, conversation_ref, slot_type)` — "slot_type" không có ý nghĩa với một
  tin nhắn thô (không phải giá trị 1 slot). Thiết kế: hàm mã hoá **mới, domain tách biệt**
  `encrypt_sample_value()`/`decrypt_sample_value()` (thêm vào `app/services/pii/crypto.py`, dùng
  lại `AESGCM` + `_validate_ref` + kỹ thuật length-prefix canonical đã có — chỉ khác domain tag
  và bộ field bind):
  ```text
  domain tag: "a3s-m4-shadow-sample-aad-v1"   (khác "a3s-m4-slot-aad-v2" của pii_slots)
  AAD fields: (customer_ref, conversation_ref, sample_id)   — sample_id (UUID) thay slot_type,
              làm MỖI ROW có AAD DUY NHẤT (mạnh hơn slot_type vốn lặp lại giữa nhiều row)
  ```
  Khoá riêng (`m4_sample_key_b64`, không dùng chung `m4_slot_key_b64`) — tách biệt hoàn toàn với
  Slot Store kể cả khi rotate khoá.
- Cột tối thiểu: `sample_id` (UUID PK, sinh trước khi mã hoá vì là 1 field của AAD),
  `customer_ref`, `conversation_ref` (**plaintext, indexed** — lý do giữ plaintext ở dưới),
  `encrypted_message` (blob `encrypt_sample_value` output), `captured_at`,
  `expires_at` (NOT NULL), `purpose_code='P12_PII_DETECTOR_EVAL'`, `label_status`
  (unlabeled/labeled), `labeled_slots` (jsonb — nhãn reviewer gán, KHÔNG phải output tự động của
  detector để tránh vòng lặp "detector tự chấm điểm chính nó"; chỉ offset+slot_type kiểu
  `PIISpan.as_safe_dict()`, không lưu giá trị plaintext trong nhãn), `selection_batch` (§4).
- **Vì sao `customer_ref`/`conversation_ref` vẫn giữ plaintext (không tokenize):** CA gợi ý cân
  nhắc "không lưu thêm plaintext identifier nếu không cần". Đã cân nhắc phương án token hoá
  (HMAC(customer_ref)) nhưng **không khả thi**: nếu không giữ plaintext, không ai (kể cả reviewer
  qua API) tính lại được AAD để giải mã — tự khoá luôn dữ liệu. Giữ plaintext 2 cột này là tiền
  lệ đã được CA chấp nhận cho `pii_slots` (migration 038) với cùng lý do (cần cho isolation
  query + DSR). Bảo vệ bù lại: (a) 2 cột này **không phải PII nhạy cảm nhất** (khác nội dung tin
  nhắn thật), (b) truy cập bị giới hạn đúng theo access matrix §5 (chỉ role reviewer-api/purge
  đọc được, không role nào con người cầm trực tiếp), (c) xoá cùng lúc với nội dung khi DSR/hết
  hạn — không tồn tại độc lập lâu hơn `encrypted_message`.
- **Retention cụ thể hoá RET-11** (CA: ACCEPTED về trần kỹ thuật, có điều kiện — xem §11):
  - `encrypted_message`: xoá **cứng (DELETE, không anonymize)** sau khi hoàn tất eval +
    tối đa **45 ngày** kể từ `captured_at`, tuỳ điều kiện nào tới trước. 45 ngày = 14 ngày thu
    thập + buffer gán nhãn/review + margin an toàn — con số này Dev đề xuất, PO/CA có thể điều
    chỉnh.
  - `labeled_slots` (nhãn, không phải raw): có thể giữ lâu hơn nếu PO muốn dùng làm regression
    corpus cho detector version sau — nhưng **chỉ khi đã tách khỏi `encrypted_message`** và bản
    thân nhãn không tái tạo lại được nội dung gốc (offset + slot_type, giống
    `PIISpan.as_safe_dict()` đã dùng trong S0, không lưu giá trị plaintext trong nhãn).
  - Purge job tái dùng pattern `purge_expired` đã có ở `app/services/pii/slot_store.py` (DELETE
    theo `expires_at`, log counts-only).
- **Storage zone vật lý:** cùng Postgres instance production (không tách DB riêng — đơn giản hoá
  vận hành cho quy mô nhỏ 200 hội thoại), nhưng **schema/quyền tách biệt** như trên. Nếu PO muốn
  tách hẳn instance/VPC riêng, Dev điều chỉnh thiết kế theo quyết định đó.

## 7. Cơ chế xóa liên kết DSR (Directive §6 — cần bổ sung Deletion Propagation Map) — **sửa theo F-M4-0P-04**

**Gap xác nhận:** `DSR-RUNBOOK-VI.md` (16 mục propagation) hiện **không có mục nào** cho kho mới
này — đúng như class dead-letter/outbox từng bị bỏ sót trước khi S4 vá.

**Thiết kế chống orphan (CA: "sample row phải không phụ thuộc conversation còn tồn tại"):**

- Thêm mục #17 vào Deletion Propagation Map: `m4_shadow_review_samples` —
  `DELETE FROM m4_shadow_review_samples WHERE customer_ref = $1` **lọc trực tiếp trên cột
  `customer_ref` lưu tại chính bảng sample — KHÔNG JOIN sang `conversations`/`messages`.**
  Vì vậy dù `conversations`/`messages` của khách đã bị xoá/ẩn danh **trước đó** (ở bước khác của
  cùng `process_deletion()`, hoặc do purge/retention khác chạy trước), lệnh xoá sample **vẫn
  chạy đúng** — không có khái niệm "orphan" vì không có foreign-key/join nào để mất theo.
- **Thứ tự/transaction:** bước xoá `m4_shadow_review_samples` chạy **trong cùng transaction**
  với phần còn lại của `process_deletion()` (atomic — hoặc xoá hết hoặc không xoá gì, không có
  trạng thái nửa vời).
- **Idempotency/retry:** `DELETE ... WHERE customer_ref = $1` khớp 0 row là no-op hợp lệ (không
  raise) — gọi lại nhiều lần (retry DSR) an toàn tự nhiên, không cần cờ trạng thái riêng.
- **Test bổ sung khi triển khai kỹ thuật** (đúng 4 case CA yêu cầu): (a) cross-customer/
  cross-conversation — decrypt bằng sai `customer_ref`/`conversation_ref`/`sample_id` phải fail
  (cùng pattern `TestAADCanonical` đã làm cho `pii_slots`); (b) tamper — sửa 1 byte
  `encrypted_message` phải fail; (c) DSR retry/idempotency — gọi `process_deletion()` 2 lần liên
  tiếp, lần 2 không lỗi, không xoá thêm; (d) xoá khi `conversations` nguồn **đã mất trước** —
  DELETE trực tiếp row `conversations` bằng SQL (mô phỏng dữ liệu đã trôi qua retention khác),
  sau đó gọi `process_deletion()`, xác nhận sample vẫn bị xoá đúng (chứng minh không orphan).
- Đây là thay đổi code cần làm **trước khi** Stage 0P thật sự bật flag — không nằm trong gói đề
  nghị này (gói này là governance request, không phải implementation). Dev sẽ đưa vào submission
  triển khai kỹ thuật sau khi PO/CA duyệt hướng đi.

## 8. Metric redaction (Directive §6 mục 9)

Đã có sẵn, không cần thiết kế thêm: `shadow_scan()` (`app/services/pii/shadow.py`) chỉ emit
`[m4-shadow]` JSON gồm counts/enum/latency/độ dài — **không có cơ chế nào trong code hiện tại có
thể đưa plaintext vào log**, đã được evidence hoá ở S0 (`m4_pii_shadow_test.py` bước [5]: quét
output không chứa giá trị PII đã gieo) và tái xác nhận qua `scripts/m3_pii_log_test.py` static
guard (ALL PASS trên toàn bộ code M4 hiện tại). Khi chạy Stage 0P thật, đề nghị chạy lại đúng 2
evidence này trên traffic thật (không chỉ synthetic) trước khi coi là đủ bằng chứng.

## 9. Incident path (Directive §6 mục 10) — **kill switch sửa theo F-M4-0P-01**

CA chỉ ra đúng: `m4_pii_shadow` chỉ tắt detector trong orchestrator — **không** liên quan gì tới
việc thu thập raw sample (đó là một job riêng, chạy độc lập). Cần 2 công tắc **tách biệt**:

| Công tắc | Phạm vi | Default | Khi TẮT |
|---|---|---|---|
| `m4_pii_shadow` (đã có từ S0) | Detector chạy trong orchestrator (đo metric, không liên quan sample) | OFF | 0 code path chạy — không đổi so với thiết kế S0 |
| `m4_stage0p_capture_enabled` (**mới**, đề xuất tên) | Job thu thập raw sample (§4) | OFF, **missing config = OFF** (đúng nguyên tắc mọi flag M4) | Job **no-op ngay ở lượt chạy tiếp theo** — không quét/đọc/ghi gì mới |

**Ngữ nghĩa "kill" tường minh (đúng yêu cầu CA):**
1. Tắt `m4_stage0p_capture_enabled` → dừng thu thập MỚI ngay lập tức, **không** xoá row đã có
   sẵn trong sample zone (xoá chỉ qua retention §6 hoặc DSR §7 — tránh việc một "báo động giả"
   dẫn tới mất bằng chứng/dữ liệu đang chờ review một cách ngoài ý muốn).
2. **Thu hồi quyền reviewer là hành động ĐỘC LẬP** với công tắc capture — ops có thể cắt quyền
   đọc của reviewer (revoke permission `m4.sample.read`, §5) mà không cần đụng tới
   `m4_stage0p_capture_enabled`, và ngược lại có thể dừng thu thập mà vẫn giữ nguyên quyền
   reviewer đọc dữ liệu đã thu thập trước đó để hoàn tất review đang dở.
3. **Test/rehearsal cho cả 2 công tắc** (flag-OFF, rollback, partial-failure) sẽ nằm trong
   submission kỹ thuật — theo đúng khuôn mẫu evidence đã dùng cho `m4_pii_shadow`/
   `m4_trusted_pii_path` ở S0–S3 (pytest flag-OFF regression + static check).

**Escalation** (không đổi): theo đúng kênh hiện dùng cho các gate M1–M3 — Telegram ping tới anh
Hoài khi phát hiện sự cố privacy/security (đúng thoả thuận đã ghi ở [[telegram-approve-pings]]),
đi "incident route ngay, không chờ Delivery Package" (Directive §16/spec stop conditions).

**Trigger cụ thể cho Stage 0P:** raw PII xuất hiện ngoài sample zone (log/trace/dead-letter);
cross-customer row trong sample zone (binding fail — evidence bắt buộc theo §7); reviewer truy
cập ngoài audit (audit ghi `outcome=denied` bất thường hoặc API bị bypass); sample vượt cửa sổ
14 ngày/hard cap 260 mà chưa có quyết định gia hạn (§4); DSR không xoá được sample trong 1
transaction (§7).

## 10. Điều kiện Dev đề nghị PO/CA quyết định

| # | Nội dung | Trạng thái sau CA Review #1 |
|---|---|---|
| 1 | Duyệt/không duyệt mở Stage 0P với thiết kế §2–§9 | ⏳ CHỜ CA review lại — 4 finding đã sửa ở §11, chờ "Stage 0P Design Accepted" |
| 2 | Purpose code mới `P12_PII_DETECTOR_EVAL` | ✅ **CA ACCEPTED** (tên/mục đích/data-class) — còn bước nộp addition kỹ thuật vào registry, không tự ghi ngoài gate |
| 3 | Retention 45 ngày | 🟡 **CA ACCEPTED trần kỹ thuật, có điều kiện** — chỉ hiệu lực sau khi F-M4-0P-04 (DSR/purge/evidence, §7) được nghiệm thu |
| 4 | Ranh giới vendor gap | ✅ **CA ACCEPTED có điều kiện** — đúng miễn là Stage 0P không có byte nào đi vendor path; không tự mở rộng sang canary |
| 5 | Reviewer cụ thể | ✅ PO ĐÃ DUYỆT (29/7 07:43); CA ghi nhận, không tái quyết định |
| 6 | Cơ sở pháp lý xử lý | ✅ PO ĐÃ DUYỆT (29/7 07:43); CA ghi nhận, không tái quyết định |

**Vẫn chưa có bước triển khai kỹ thuật nào được thực hiện** (không migration, không sample
collector, không cấp quyền production, không bật flag) — đúng ranh giới CA nhắc lại ở cuối Review
#1. Sau khi CA ra "Stage 0P Design Accepted" cho mục 1, Dev sẽ mở submission kỹ thuật riêng:
migration `m4_shadow_review_samples` + 4 role DB (§5) + 2 công tắc (§9), cập nhật Deletion
Propagation Map (mục #17, §7), bổ sung UC-004 chính thức, sample job 2 pha (§4), rồi mới bật
`m4_stage0p_capture_enabled=true` trên tập traffic đã duyệt — mỗi bước có evidence riêng theo
đúng khuôn mẫu S0–S3.

## 11. Mapping finding CA Review #1 → sửa ở đâu trong bản v2.0.0 này

| Finding | Mức | Sửa tại | Tóm tắt |
|---|---|---|---|
| F-M4-0P-01 | P1 | §9 | Tách `m4_stage0p_capture_enabled` khỏi `m4_pii_shadow`; định nghĩa ngữ nghĩa kill (dừng ghi mới, không xoá dữ liệu cũ, thu hồi reviewer độc lập) |
| F-M4-0P-02 | P1 | §5 | 4 role DB tách biệt (collector/reviewer-api/evaluator/purge), column-level grant, reviewer con người không bao giờ cầm credential DB, audit bắt buộc trước khi trả dữ liệu, break-glass có văn bản |
| F-M4-0P-03 | P1 | §4 | Hard cap 260, chọn 2 pha (metadata trước, nội dung sau), seed cố định công khai tái lập được thay cho "stratify" mơ hồ |
| F-M4-0P-04 | P1 | §6, §7 | Domain tag/AAD riêng cho sample (không tái dùng nguyên trạng slot AAD), giữ plaintext ref có lý do rõ + bù đắp, DSR filter trực tiếp trên `customer_ref` (không join, không orphan), 4 test bổ sung |
