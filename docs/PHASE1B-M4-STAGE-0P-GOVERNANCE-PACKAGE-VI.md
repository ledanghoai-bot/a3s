---
id: A3S-PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-001
title: Alpha3S Phase I-B M4 — Stage 0P Governance Package (Production Shadow Request)
document_type: governance_request_package
owner: Dev
status: CA REVIEW #2 CHANGES_REQUIRED (29/7 11:05) — F-04 CLOSED AT DESIGN LEVEL; F-01/02/03 PARTIALLY CLOSED + F-05 mới, đã sửa trong bản này (v3), chờ CA review lại
created_at: 2026-07-29 06:17+07:00
last_updated: 2026-07-29 11:40+07:00
version: 3.0.0 — Correction #2 theo PHASE1B-M4-STAGE-0P-GOVERNANCE-REVIEW-2-VI.md
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

**Cập nhật 29/7 07:43 — PO đã ra quyết định cho 4/6 mục** (nay là bảng §11).

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
bản v2.0.0 này (§4, §5, §6, §7, §9 cập nhật), xem bảng mapping ở §12.

**Cập nhật 29/7 11:05 — CA Review #2** (`PHASE1B-M4-STAGE-0P-GOVERNANCE-REVIEW-2-VI.md`), review
Correction #1: **CHANGES_REQUIRED**. Kết quả từng finding cũ: F-M4-0P-01 **PARTIALLY CLOSED**
(đã tách công tắc nhưng ngữ nghĩa dừng job/latency chưa đủ chặt); F-M4-0P-02 **PARTIALLY CLOSED**
(đã tách role nhưng collector chưa có đường đọc `messages.content` được kiểm soát); F-M4-0P-03
**OPEN** (mới giới hạn số hội thoại, chưa giới hạn số tin nhắn/byte thực lưu); **F-M4-0P-04
CLOSED AT DESIGN LEVEL** ✅ (domain tag/AAD riêng + DSR direct-link đã đủ, chuyển sang chờ
implementation evidence — không cần sửa thêm ở tầng thiết kế). Thêm **F-M4-0P-05 mới** (P1):
evaluation dataset thiếu prediction/detector-version bên cạnh ground truth. Đã sửa cả 4 mục
`01A/02A/03A/05` trong bản v3.0.0 này — mapping đầy đủ ở §12.

Directive §6 quy định 5 prerequisite phải PASS trước khi mở Stage 0P:

| # | Prerequisite | Trạng thái |
|---|---|---|
| 1 | M3 PII-safe logging control accepted | ✅ **PASS** — S4 áp `safe_log`/`safe_exc` toàn app, guard `scripts/m3_pii_log_test.py` ALL PASS (4 gap HIGH đã đóng; 1 known-limitation PSID-trong-URL-log còn mở, không phải HIGH) |
| 2 | Vendor/AI Use Case review accepted | 🟡 **PASS CÓ ĐIỀU KIỆN** — xem §1 (Stage 0P không gọi vendor nên gap cross-border DeepSeek không block trực tiếp; cần UC mới, đề xuất ở §2) |
| 3 | Production-data access approved PO/CA | ⏳ **ĐANG XIN** — chính là mục đích gói này |
| 4 | Retention/labeling environment verified | ⏳ **THIẾT KẾ TRONG GÓI NÀY** — xem §5, §6 (RET-11 trong Retention Schedule hiện chỉ là khung rỗng "thiết kế tại M4") |
| 5a | Rollback/kill switch — detector shadow (`m4_pii_shadow`) | ✅ **PASS** — flag OFF = 0 code path chạy (evidence S0/S3: 214 pytest bao gồm flag-OFF regression, static check orchestrator không tham chiếu `m4_trusted_pii_path`) |
| 5b | Rollback/kill switch — raw sample capture (`m4_stage0p_capture_enabled`) | 🔧 **DESIGN DEFINED / NOT VERIFIED** (F-M4-0P-01A) — ngữ nghĩa thiết kế ở §9; chỉ chuyển PASS sau implementation test (chứng minh 0 write sau khi OFF giữa batch) + rollback rehearsal thật, KHÔNG suy diễn từ evidence của 5a |

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
                 (29/7 07:43, mục 6 §11) — CA đã ghi nhận (Review #1).
  Trạng thái: CA ACCEPTED tên/mục đích/data-class (Review #1, mục 2 §11) — còn nộp addition
              kỹ thuật vào registry chính thức
```

Đây là format khớp các mục hiện có trong `PROCESSING-PURPOSE-REGISTRY.md`. Cơ sở pháp lý đã có
quyết định PO, tên/mục đích/data-class đã CA ACCEPTED (Review #1) — còn bước nộp addition chính
thức vào registry chung sau khi có "Stage 0P Design Accepted" (KHÔNG tự ý sửa file M3 ngoài gate).

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

## 4. Sampling method (Directive §6 mục 3) + quy mô đại diện — **sửa theo F-M4-0P-03 và F-M4-0P-03A**

**Sửa lỗi schema (tự phát hiện khi thiết kế lại):** bản trước viết "`orders.conversation_id`" —
cột này **không tồn tại**. Schema thật: `orders.customer_id → customers.id`,
`conversations.customer_id → customers.id` (không có liên kết trực tiếp order↔conversation).
Đã sửa câu truy vấn eligibility bên dưới cho khớp schema thật.

**Sampling UNIT tường minh (F-M4-0P-03A yêu cầu):** đơn vị **chọn** là **hội thoại**; đơn vị
**lưu trữ** là **tin nhắn** (đúng như schema §6 mô tả — 1 row = 1 `encrypted_message`). Cả hai
đều phải có cap riêng, không suy diễn cap này ra cap kia:

- **Cửa sổ:** 14 ngày liên tục kể từ ngày kích hoạt.
- **Cap A — hội thoại:** hard cap **260** (200 mục tiêu + buffer).
- **Cap B — tin nhắn khách/hội thoại:** hard cap **20** — nếu hội thoại có >20 tin nhắn khách,
  chỉ lấy **20 tin đầu tiên** theo `created_at ASC, id ASC` (deterministic); phần dư **không**
  được thu thập (không phải "thu rồi ẩn"), log 1 metric đếm (`truncated_conversations=K`).
- **Cap C — byte/tin nhắn:** hard cap **2000 ký tự** (tái dùng đúng hằng số
  `_MAX_CANDIDATE_LEN` đã dùng ở `semantic_schema.py`, nhất quán trong toàn bộ code M4). Cắt
  bằng **string-level slicing trên chuỗi đã decode** (`text[:2000]`, KHÔNG cắt theo byte thô —
  luôn an toàn UTF-8 vì Python string index theo code point, không bao giờ chẻ đôi 1 ký tự đa
  byte). Row bị cắt đánh dấu `truncated=true` — **loại khỏi mẫu số recall/precision chính**
  (cùng nguyên tắc `gate=false` đã dùng cho corpus known-limitation ở S0), chỉ báo cáo riêng.
- **Cap D — trần byte tuyệt đối (để CA thấy worst-case thật):** 260 × 20 × 2000 ký tự ≈ **10.4 MB**
  plaintext-equivalent tối đa toàn bộ sample zone (ciphertext lớn hơn không đáng kể do overhead
  nonce+tag cố định 12+16 byte/row).
- **Thực thi đơn-writer (chống race điều kiện đồng thời — F-M4-0P-03A yêu cầu test concurrent
  collector):** job thu thập dùng **đúng pattern advisory lock đã có** trong
  `scripts/migrate.py` (`pg_try_advisory_lock` fail-fast, `LOCK_KEY` riêng cho M4 — không phát
  minh cơ chế khoá mới). Chỉ 1 tiến trình collector chạy tại một thời điểm ⇒ mọi cap ở trên được
  giữ bởi một bộ đếm trong tiến trình đó (check trước mỗi INSERT — cùng checkpoint với kill
  switch §9), loại bỏ hoàn toàn race điều kiện thay vì cố enforce cap dưới concurrency thật.
- **Thuật toán chọn — 2 pha tách bạch, KHÔNG đọc nội dung tin nhắn ở pha 1:**
  1. **Pha chọn (metadata-only, sửa đúng schema):** `E` = tập `conversations.id` sao cho tồn tại
     ≥1 `orders` với `orders.customer_id = conversations.customer_id` và
     `orders.created_at` trong cửa sổ 14 ngày — **không đọc `messages.content`**. Sắp xếp
     deterministic theo `conversations.id ASC`.
  2. `|E| ≤ 260` → chọn toàn bộ `E`. `|E| > 260` → chọn 260 bằng permutation seed cố định công
     khai `SHA256("m4-stage0p-v1")` (không dùng `random()` không seed) — tái lập được độc lập.
  3. Tập chọn được **KHOÁ LẠI** thành 1 row trong bảng `m4_selection_batches` (thiết kế mới, xem
     §5) — **chỉ sau khi khoá xong**, pha thu thập mới được phép đọc nội dung, và chỉ đọc đúng
     batch đã khoá (xem §5 — collector không tự do truy vấn `conversation_id` bất kỳ).
  4. Mỗi row lưu `selection_batch` = id của batch đã khoá, để truy vết đúng lô/thuật toán.
- **Loại trừ khi chọn (sửa theo F-M4-0P-02A — không quét nội dung, xem thêm §5):**
  - Đang chờ xác nhận xoá: Redis key `del_pending:{psid}` còn tồn tại → loại (kiểm tra key,
    KHÔNG phải content scan).
  - **Đã hoàn tất xoá dữ liệu: TỰ ĐỘNG loại, không cần luật riêng** — `_delete_customer_data()`
    xoá cứng (`DELETE`) toàn bộ `conversations` của khách đó, nên họ **không còn hội thoại nào**
    để xuất hiện trong tập `E` ở bước 1. Bản trước đề xuất luật "loại nếu đã gửi XOA DU LIEU
    trong 90 ngày" — **rút lại**: luật đó vừa cần quét `messages.content` (đúng điều CA cấm),
    vừa **không khả thi** vì `data_deletion_requests` (013) **cố ý không lưu psid** ("CO Y khong
    luu psid lau dai" — comment gốc trong migration) để không giữ lại định danh của người đã bị
    xoá — không có nguồn dữ liệu 90-ngày nào để tra cứu. Loại bỏ luật này không giảm an toàn vì
    trường hợp nó nhắm tới (khách đã xoá) đã được loại tự động qua cơ chế trên.
- **Dưới ngưỡng:** nếu `|E| < 200` khi hết cửa sổ 14 ngày → dừng, báo cáo, chờ quyết định (không
  tự gia hạn) — giữ nguyên.
- **Metric:** chỉ log counts (`eligible=N excluded_pending=K selected=M
  truncated_conversations=T truncated_messages=U`), không định danh hội thoại/khách trong log.
- **Test boundary khi triển khai kỹ thuật:** hội thoại đúng 21 tin nhắn khách → chỉ 20 được lưu +
  metric truncation; tin nhắn đúng 2001 ký tự → cắt còn 2000 tại ranh giới ký tự, `truncated=true`;
  2 tiến trình collector cùng khởi động → tiến trình thứ 2 fail-fast (không giữ được advisory
  lock), không có ghi trùng/vượt cap.

## 5. Labeling roles / access matrix (Directive §6 mục 4) + reviewer audit (mục 7) — **sửa theo F-M4-0P-02, F-M4-0P-02A, F-M4-0P-05**

CA chỉ ra đúng (Review #1): bản v1 vừa cấp `SELECT` trực tiếp cho reviewer vừa nói "phải qua
view/API" — mâu thuẫn. CA chỉ ra tiếp (Review #2): bản v2 định nghĩa collector chỉ SELECT
metadata, nhưng **không nói ai/bằng cách nào đọc được `messages.content`** thật — đó là lỗ hổng
thiết kế, không phải chi tiết bỏ sót. Thiết kế lại đầy đủ:

### 5.1. Bảng khoá lựa chọn `m4_selection_batches` (mới, hỗ trợ §4 bước 3 + chặn collector tự do)

```text
batch_id       UUID PK
window_start, window_end   TIMESTAMPTZ
eligible_count, selected_count   INT   -- counts-only, khong danh sach id public
algorithm_seed TEXT   -- "m4-stage0p-v1", truy vet
locked_conversation_ids   BIGINT[]   -- chi migration-owner/function noi bo doc; KHONG grant SELECT truc tiep cho collector
locked_at      TIMESTAMPTZ
status         TEXT   -- 'locked' | 'collecting' | 'closed'
```

Collector **không** tự chọn/truyền `conversation_id`; nó chỉ biết `batch_id` và gọi hàm §5.2.

### 5.2. Đường đọc nội dung duy nhất — hàm `SECURITY DEFINER`, không SELECT trực tiếp trên `messages`

`m4_stage0p_fetch_batch_content(batch_id UUID) RETURNS TABLE(conversation_id, message_id,
content, created_at)` — sở hữu bởi migration-owner (đọc `messages` bằng quyền của **hàm**, không
phải quyền của caller — chuẩn Postgres `SECURITY DEFINER`). Ràng buộc cứng trong thân hàm (không
phải quy ước, mà là logic bắt buộc):

- **Chỉ trả `role = 'customer'`** (loại trừ tuyệt đối `bot`/`agent` — output máy/nhân viên).
- **Chỉ trả tin nhắn thuộc `conversation_id` nằm trong `locked_conversation_ids` của ĐÚNG
  `batch_id` truyền vào** — hàm tự tra `m4_selection_batches`, **không nhận `conversation_id`
  làm tham số** ⇒ collector không thể truy vấn tuỳ ý một `conversation_id` ngoài batch đã khoá
  (loại bỏ chính xác nguy cơ CA nêu "arbitrary conversation-id query").
- **Không có cột/loại attachment trong schema `messages` hiện tại** (chỉ có `content TEXT`) —
  ghi rõ ràng buộc này để nếu sau này thêm cột đính kèm, hàm phải cập nhật tường minh loại trừ,
  không "tự động an toàn".
- Áp **Cap B/C của §4** (20 tin/hội thoại, cắt 2000 ký tự) **ngay trong hàm** trước khi trả — cắt
  càng sớm càng ít bề mặt rủi ro giữ nguyên nội dung dư thừa dù chỉ tạm thời trong bộ nhớ caller.
- `alpha3s_m4_sample_collector` chỉ có `EXECUTE` trên hàm này — **KHÔNG có SELECT nào trên bảng
  `messages`** (đúng yêu cầu CA "không cấp SELECT rộng"). Thu hồi `EXECUTE` là một lever kill
  riêng, độc lập với §9.
- **Audit mỗi lần gọi:** `actor_type='system', action='m4_batch_fetch', entity_type=
  'm4_selection_batch', entity_id=batch_id, after={"row_count": N}` — đếm, không nội dung/ID
  tin nhắn cụ thể trong audit (đúng "audit counts/IDs an toàn" — chỉ đếm, ID chỉ là batch_id).

| Role DB | Quyền trên `m4_shadow_review_samples` | Quyền khác | Dùng bởi |
|---|---|---|---|
| `alpha3s_m4_sample_collector` | INSERT-only | `EXECUTE m4_stage0p_fetch_batch_content` (§5.2); SELECT metadata `orders.customer_id, orders.created_at, conversations.id, conversations.customer_id` cho pha chọn §4 (KHÔNG `messages`) | Job thu thập, serialize bằng advisory lock (§4) — **principal DUY NHẤT ghi vào sample zone và DUY NHẤT đọc `messages.content`, qua hàm, không qua SELECT** |
| `alpha3s_m4_sample_reviewer_api` | SELECT `sample_id, encrypted_message, customer_ref, conversation_ref, captured_at, label_status` — **KHÔNG** `predicted_slots`/`detector_version` (chống thiên lệch xác nhận, F-M4-0P-05) | UPDATE `labeled_slots, label_status` (ghi nhãn) | **CHỈ credential tiến trình API nội bộ** (ops endpoint, tái dùng xác thực `staff_users`/`staff_sessions` — `app/services/auth_service.py`). Con người không bao giờ cầm credential DB này; PO đăng nhập qua session staff, endpoint giải mã + **ghi audit TRƯỚC KHI trả dữ liệu** (fail closed nếu audit lỗi) |
| `alpha3s_m4_sample_evaluator` | SELECT **chỉ** `sample_id, label_status, labeled_slots, predicted_slots, detector_version, evaluation_batch, selection_batch` — **KHÔNG** `encrypted_message`, **KHÔNG** `customer_ref`/`conversation_ref` | — | Eval script (Dev) đo recall/precision — không đọc được nội dung thô, chỉ nhãn + dự đoán (§5.3) |
| `alpha3s_m4_prediction_writer` (mới) | UPDATE **chỉ** `predicted_slots, detector_version, evaluation_batch` | `EXECUTE` hàm chạy detector nội bộ (đọc `encrypted_message` **của chính hàm này**, giải mã tạm trong bộ nhớ, KHÔNG trả plaintext ra ngoài, chỉ ghi lại kết quả `as_safe_dict`-shape) | Job chấm điểm sau-labeling (§5.3) — tách khỏi reviewer-api và evaluator |
| `alpha3s_m4_sample_purge` | DELETE + SELECT **chỉ** `customer_ref, expires_at, sample_id` | — | Purge job (retention §6 + DSR §7) |
| `alpha3s_app` (runtime) | KHÔNG có quyền nào | — | Sample zone hoàn toàn ngoài request-path production |
| `alpha3s_vendor_path` | KHÔNG có quyền nào (REVOKE ALL, đúng nguyên tắc `pii_slots` 038) | — | — |

`REVOKE ALL ON m4_shadow_review_samples, m4_selection_batches FROM PUBLIC` là bước đầu tiên của
migration khi triển khai — mọi quyền trên đều là GRANT tường minh, không có quyền ngầm định.

### 5.3. Chống thiên lệch xác nhận (F-M4-0P-05) — thứ tự bắt buộc, không chỉ là quy ước API

`predicted_slots` **KHÔNG được ghi cho tới khi TOÀN BỘ row trong batch có `label_status=
'labeled'`** — job chấm điểm (`alpha3s_m4_prediction_writer`) tự kiểm tra điều kiện này trước
khi chạy, **từ chối chạy nếu còn row unlabeled trong batch**. Đây là ràng buộc **cấu trúc** (cột
rỗng cho tới lúc đó), không phải lời hứa ở tầng API — nên dù có bug ở endpoint, reviewer vẫn
không thể thấy `predicted_slots` sớm vì nó **chưa tồn tại**.

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

**Negative-permission test khi triển khai kỹ thuật (F-M4-0P-02A):** `alpha3s_m4_sample_collector`
thử `SELECT * FROM messages` trực tiếp → phải bị `InsufficientPrivilegeError` (chỉ `EXECUTE`
hàm §5.2 mới hợp lệ); gọi hàm §5.2 với `batch_id` giả/chưa khoá → trả 0 row; `alpha3s_m4_sample_
evaluator` thử `SELECT encrypted_message` → bị từ chối (cùng pattern test đã dùng cho
`alpha3s_vendor_path`/`alpha3s_app` ở migration 038, `m4_slot_store_test.py` [9]).

## 6. Storage zone + retention/expiry (Directive §6 mục 5, 6) — **F-M4-0P-04 CLOSED AT DESIGN LEVEL (CA Review #2); bổ sung cột cho F-M4-0P-03A/05**

CA Review #2 xác nhận phần domain tag/AAD riêng + DSR direct-link (nội dung §6/§7 bản v2.0.0)
**đã đủ ở tầng thiết kế** — giữ nguyên, không sửa lại phần crypto/DSR. Phần dưới đây bổ sung cột
còn thiếu để đáp ứng F-M4-0P-03A (truncation) và F-M4-0P-05 (prediction/detector version).

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
  `customer_ref` (đề xuất = `customers.id`, KHÔNG dùng `psid` — lý do: `psid` bị ghi đè thành
  `deleted:<code>` khi xoá, còn `customers.id` bất biến suốt vòng đời, tra cứu DSR §7 ổn định
  hơn), `conversation_ref` (**plaintext, indexed** — lý do giữ plaintext ở dưới),
  `encrypted_message` (blob `encrypt_sample_value` output, đã cắt theo Cap C §4 TRƯỚC khi mã
  hoá), `truncated` (bool, đúng Cap B/C §4 — loại khỏi mẫu số recall/precision chính khi True),
  `captured_at`, `expires_at` (NOT NULL), `purpose_code='P12_PII_DETECTOR_EVAL'`, `label_status`
  (unlabeled/labeled), `labeled_slots` (jsonb — **ground truth**, reviewer gán tay, format
  `[{slot_type, confidence, reason}]` theo dạng `PIISpan.as_safe_dict()` nhưng KHÔNG offset —
  xem lý do chọn instance-count matching thay vì offset-overlap ở §10), `predicted_slots`
  (jsonb — **output detector**, CÙNG FORMAT với `labeled_slots` để so sánh trực tiếp; NULL cho
  tới khi cả batch labeled xong — §5.3), `detector_version` (text, vd `m4d-0.1.0` — tái dùng
  hằng số `DETECTOR_VERSION` đã có ở `taxonomy.py`), `evaluation_batch` (text — phân biệt lần
  chấm điểm nếu detector re-run version mới trên cùng ground truth), `selection_batch` (§4).
- **Vì sao `customer_ref`/`conversation_ref` vẫn giữ plaintext (không tokenize):** CA gợi ý cân
  nhắc "không lưu thêm plaintext identifier nếu không cần". Đã cân nhắc phương án token hoá
  (HMAC(customer_ref)) nhưng **không khả thi**: nếu không giữ plaintext, không ai (kể cả reviewer
  qua API) tính lại được AAD để giải mã — tự khoá luôn dữ liệu. Giữ plaintext 2 cột này là tiền
  lệ đã được CA chấp nhận cho `pii_slots` (migration 038) với cùng lý do (cần cho isolation
  query + DSR). Bảo vệ bù lại: (a) 2 cột này **không phải PII nhạy cảm nhất** (khác nội dung tin
  nhắn thật), (b) truy cập bị giới hạn đúng theo access matrix §5 (chỉ role reviewer-api/purge
  đọc được, không role nào con người cầm trực tiếp), (c) xoá cùng lúc với nội dung khi DSR/hết
  hạn — không tồn tại độc lập lâu hơn `encrypted_message`.
- **Retention cụ thể hoá RET-11** (CA: ACCEPTED về trần kỹ thuật, có điều kiện — xem §11 mục 3):
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
  `DELETE FROM m4_shadow_review_samples WHERE customer_ref = $1` (tham số = `customers.id`,
  lấy từ chính `cust["id"]` mà `_delete_customer_data()` đã truy vấn ở dòng đầu hàm — không cần
  query thêm) **lọc trực tiếp trên cột `customer_ref` lưu tại chính bảng sample — KHÔNG JOIN
  sang `conversations`/`messages`.** Dùng `customers.id` (bất biến) thay vì `psid` (bị ghi đè
  thành `deleted:<code>` trong CHÍNH hàm này) — nếu lỡ dùng `psid` sẽ có nguy cơ thứ tự sai (xoá
  sample sau khi `psid` đã bị đổi thì WHERE không khớp được nữa); dùng `id` loại bỏ rủi ro thứ
  tự này. Vì vậy dù `conversations`/`messages` của khách đã bị xoá/ẩn danh **trước đó** (ở bước
  khác của cùng `process_deletion()`, hoặc do purge/retention khác chạy trước), lệnh xoá sample
  **vẫn chạy đúng** — không có khái niệm "orphan" vì không có foreign-key/join nào để mất theo.
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

## 9. Incident path (Directive §6 mục 10) — **kill switch sửa theo F-M4-0P-01 và F-M4-0P-01A**

CA chỉ ra đúng (Review #1): `m4_pii_shadow` chỉ tắt detector trong orchestrator — không liên
quan raw sample capture. CA chỉ ra tiếp (Review #2): nói job "no-op ở lượt chạy tiếp theo" là
**chưa đủ chặt** — nếu 1 lượt chạy (batch) đang đọc/ghi hàng loạt record thì tắt cờ giữa chừng
vẫn không ngăn được các ghi còn lại của batch đó. Cần 2 công tắc **tách biệt** + **ngữ nghĩa
dừng ở cấp đơn vị ghi nhỏ nhất**, không phải cấp lượt chạy:

| Công tắc | Phạm vi | Default | Khi TẮT |
|---|---|---|---|
| `m4_pii_shadow` (đã có từ S0) | Detector chạy trong orchestrator (đo metric, không liên quan sample) | OFF | 0 code path chạy — không đổi so với thiết kế S0 |
| `m4_stage0p_capture_enabled` (**mới**, đề xuất tên) | Job thu thập raw sample (§4) | OFF, **missing config = OFF** | Xem ngữ nghĩa dừng dưới đây |

**Ngữ nghĩa "kill" — dừng ở cấp TỪNG TIN NHẮN, không phải cấp job/batch (F-M4-0P-01A):**

1. Collector **re-check `m4_stage0p_capture_enabled` ngay trước MỖI lệnh INSERT một row** (đơn
   vị nhỏ nhất — 1 tin nhắn), **không** re-check ở cấp hội thoại hay cấp lượt chạy. Đây là cùng
   checkpoint dùng để giữ cap §4 (Cap A/B) — 1 điểm kiểm tra duy nhất trước mỗi ghi, kiểm tra cả
   "flag còn ON?" lẫn "cap chưa vượt?".
2. **Maximum stop latency định nghĩa tường minh:** thời gian hoàn tất **1 lệnh INSERT một row
   đang thực thi dở** tại thời điểm cờ chuyển OFF (thực tế: single-row INSERT trên Postgres,
   quy mô mili-giây) — **không phụ thuộc** số hội thoại/tin nhắn còn lại trong lượt chạy. Đây là
   cận trên xấu nhất có thể chứng minh được, không phải ước lượng "lượt chạy tiếp theo".
3. Tắt cờ → dừng ghi MỚI theo ngữ nghĩa trên; **không** xoá row đã có sẵn (xoá chỉ qua retention
   §6/DSR §7 — tránh "báo động giả" gây mất dữ liệu đang chờ review ngoài ý muốn).
4. **Thu hồi quyền reviewer là hành động ĐỘC LẬP** với công tắc capture (§5: revoke permission
   `m4.sample.read` hoặc revoke `EXECUTE` trên hàm §5.2 — không cần đụng `m4_stage0p_capture_
   enabled`, và ngược lại).
5. **Evidence bắt buộc trước khi prerequisite 5b (§0) được coi là PASS:** test khẳng định 0 write
   xảy ra sau khi cờ chuyển OFF giữa batch (harness: bắt đầu capture N tin nhắn, chuyển OFF sau
   khi M<N đã ghi, assert đúng M row tồn tại — không hơn); rollback rehearsal thật (không chỉ
   suy luận trên giấy). Đây là việc của submission kỹ thuật, không phải gói governance này.

**Escalation** (không đổi): theo đúng kênh hiện dùng cho các gate M1–M3 — Telegram ping tới anh
Hoài khi phát hiện sự cố privacy/security (đúng thoả thuận đã ghi ở [[telegram-approve-pings]]),
đi "incident route ngay, không chờ Delivery Package" (Directive §16/spec stop conditions).

**Trigger cụ thể cho Stage 0P:** raw PII xuất hiện ngoài sample zone (log/trace/dead-letter);
cross-customer row trong sample zone (binding fail — evidence bắt buộc theo §7); reviewer truy
cập ngoài audit (audit ghi `outcome=denied` bất thường hoặc API bị bypass); sample vượt cửa sổ
14 ngày/hard cap 260 mà chưa có quyết định gia hạn (§4); DSR không xoá được sample trong 1
transaction (§7).

## 10. Evaluation methodology — matching rule + aggregation (mới, F-M4-0P-05)

**Matching rule đã chọn: instance-count matching theo `(message, slot_type)` — KHÔNG offset-
overlap.** Lý do: (1) đây **chính là phương pháp đã dùng ở S0** cho corpus synthetic
(`m4_pii_shadow_test.py`: `got = đếm span theo slot_type; want = đếm kỳ vọng`, `TP = min(got,
want)`) — CA đã review S0/S3 không phản đối phương pháp này; giữ nhất quán tránh 2 chuẩn đo song
song. (2) Offset-overlap đòi hỏi lưu vị trí bắt đầu/kết thúc trong cả `labeled_slots` lẫn
`predicted_slots` — dù bản thân con số vị trí không phải PII, đây là bề mặt dữ liệu KHÔNG cần
thiết cho mục tiêu đo recall/precision tổng thể; bỏ offset là lựa chọn tối giản hoá dữ liệu
nhất quán với `PIISpan.as_safe_dict()` (S0) vốn đã cố ý không có offset.

- **Đơn vị so khớp:** với mỗi `(sample_id, slot_type)`: `TP = min(đếm trong labeled_slots, đếm
  trong predicted_slots)`, `FN = max(0, đếm labeled - đếm predicted)`, `FP = max(0, đếm predicted
  - đếm labeled)`.
- **Aggregation: micro** (gộp TP/FN/FP toàn bộ batch trước khi tính recall/precision — đúng cách
  S0 đã làm), không dùng macro (trung bình theo từng row) để tránh hội thoại ít tin nhắn có
  trọng số bất thường so với hội thoại nhiều tin nhắn.
- **Loại trừ khỏi mẫu số:** row `truncated=true` (§4/§6) — không tính vào recall/precision
  chính, báo cáo riêng số lượng (đúng nguyên tắc `gate=false` đã dùng cho corpus S0).
- **Thứ tự bắt buộc — chống thiên lệch xác nhận:** ground-truth labeling **phải hoàn tất toàn bộ
  batch** trước khi `predicted_slots` được ghi (§5.3, ràng buộc cấu trúc — cột rỗng cho tới lúc
  đó, không phải quy ước quy trình).

## 11. Điều kiện Dev đề nghị PO/CA quyết định

| # | Nội dung | Trạng thái sau CA Review #2 |
|---|---|---|
| 1 | Duyệt/không duyệt mở Stage 0P với thiết kế §2–§10 | ⏳ CHỜ CA review lại — 4 finding (01A/02A/03A/05) đã sửa, mapping ở §12, chờ "Stage 0P Design Accepted" |
| 2 | Purpose code mới `P12_PII_DETECTOR_EVAL` | ✅ **CA ACCEPTED** (tên/mục đích/data-class) — còn bước nộp addition kỹ thuật vào registry |
| 3 | Retention 45 ngày | 🟡 **CA ACCEPTED trần kỹ thuật, có điều kiện** — hiệu lực sau khi DSR/purge/evidence (§7, F-04 đã CLOSED AT DESIGN LEVEL) được nghiệm thu ở tầng implementation |
| 4 | Ranh giới vendor gap | ✅ **CA ACCEPTED có điều kiện** — miễn Stage 0P không có byte nào đi vendor path |
| 5 | Reviewer cụ thể | ✅ PO ĐÃ DUYỆT (29/7 07:43); CA ghi nhận |
| 5b | Kill switch capture path | 🔧 DESIGN DEFINED / NOT VERIFIED (F-01A) — PASS chỉ sau implementation test + rollback rehearsal |
| 6 | Cơ sở pháp lý xử lý | ✅ PO ĐÃ DUYỆT (29/7 07:43); CA ghi nhận |

**Vẫn chưa có bước triển khai kỹ thuật nào được thực hiện** (không migration, không sample
collector, không cấp quyền production, không bật flag) — đúng ranh giới CA nhắc lại cuối cả 2
lần review. Sau khi CA ra "Stage 0P Design Accepted", Dev mở submission kỹ thuật riêng: migration
`m4_shadow_review_samples` + `m4_selection_batches` + hàm `m4_stage0p_fetch_batch_content` + 6
role DB (§5) + 2 công tắc với re-check per-message (§9), cập nhật Deletion Propagation Map (mục
#17, §7), bổ sung UC-004 chính thức, sample job 2 pha có cap 4 lớp (§4), job chấm điểm sau-
labeling (§5.3), rồi mới bật `m4_stage0p_capture_enabled=true` trên tập traffic đã duyệt — mỗi
bước có evidence riêng theo đúng khuôn mẫu S0–S3.

## 12. Mapping finding → sửa ở đâu (cộng dồn Review #1 + #2, bản v3.0.0)

| Finding | Vòng | Mức | Trạng thái | Sửa tại |
|---|---|---|---|---|
| F-M4-0P-01 | #1 | P1 | Base đã tách 2 công tắc | §9 |
| F-M4-0P-01A | #2 | P1 | **Sửa ở v3** | §9 — re-check per-message (không phải per-batch), max stop latency = 1 INSERT dở, prerequisite 5b tách trạng thái |
| F-M4-0P-02 | #1 | P1 | Base đã tách role/audit | §5 |
| F-M4-0P-02A | #2 | P1 | **Sửa ở v3** | §5.1, §5.2 — bảng khoá `m4_selection_batches`, hàm `SECURITY DEFINER` duy nhất đọc `messages`, loại bỏ luật loại-trừ-90-ngày cần content-scan (thay bằng loại trừ tự nhiên từ metadata + Redis key) |
| F-M4-0P-03 | #1 | P1 | Base đã cap hội thoại | §4 |
| F-M4-0P-03A | #2 | P1 | **Sửa ở v3** | §4, §6 — thêm Cap B (tin/hội thoại), Cap C (byte/tin), Cap D (trần byte tuyệt đối), cắt UTF-8-safe, đơn-writer bằng advisory lock |
| F-M4-0P-04 | #1→#2 | P1 | ✅ **CLOSED AT DESIGN LEVEL** | §6, §7 — không sửa thêm, chỉ bổ sung cột không liên quan crypto/DSR |
| F-M4-0P-05 | #2 (mới) | P1 | **Sửa ở v3** | §5.2 (`predicted_slots`/`detector_version` role tách), §5.3 (chống thiên lệch — cấu trúc, không phải quy ước), §6 (cột mới), §10 (matching rule + aggregation) |
