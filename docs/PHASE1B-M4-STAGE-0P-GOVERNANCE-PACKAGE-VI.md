---
id: A3S-PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-001
title: Alpha3S Phase I-B M4 — Stage 0P Governance Package (Production Shadow Request)
document_type: governance_request_package
owner: Dev
status: CA REVIEW #3 CHANGES_REQUIRED (29/7 13:41) — F-04 CLOSED; 01A/02A/03A OPEN→01B/02B/03B, F-05 OPEN→05A, đã sửa trong bản này (v4), chờ CA review lại
created_at: 2026-07-29 06:17+07:00
last_updated: 2026-07-29 15:18+07:00
version: 4.0.0 — Correction #3 theo PHASE1B-M4-STAGE-0P-GOVERNANCE-REVIEW-3-VI.md
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
`01A/02A/03A/05` trong bản v3.0.0 (commit `ff1233a`) — mapping đầy đủ ở §12.

**Cập nhật 29/7 13:41 — CA Review #3** (`PHASE1B-M4-STAGE-0P-GOVERNANCE-REVIEW-3-VI.md`), review
Correction #2: **CHANGES_REQUIRED**, nhưng **F-M4-0P-04 vẫn CLOSED** (giữ nguyên). Kết quả:
F-M4-0P-01A **OPEN** (checkpoint per-row đúng hướng nhưng nguồn control đọc từ `settings` nạp 1
lần lúc process start — không quan sát được thay đổi giữa lúc job đang chạy); F-M4-0P-02A
**CONDITIONALLY CLOSED AT DESIGN LEVEL** (hàm `SECURITY DEFINER` đúng hướng, cần hardening cụ
thể + xử lý pending-DSR lookup không trao PSID cho collector); F-M4-0P-03A **OPEN** (cap tôi gọi
là "byte" thực chất là character — cap byte thật có thể gấp ~4 lần; eligibility có thể kéo nhầm
hội thoại cũ/không liên quan của cùng khách); F-M4-0P-05 **OPEN** (count-only theo slot_type có
thể chấm đúng số nhưng sai vị trí/thực thể — false acceptance, không đủ để đo precision/recall
thật trên sample thật, dù S0 dùng được cho corpus synthetic smoke test). 4 mục con mới
`01B/02B/03B/05A` đã sửa trong bản v4.0.0 này — mapping đầy đủ ở §12.

Directive §6 quy định 5 prerequisite phải PASS trước khi mở Stage 0P:

| # | Prerequisite | Trạng thái |
|---|---|---|
| 1 | M3 PII-safe logging control accepted | ✅ **PASS** — S4 áp `safe_log`/`safe_exc` toàn app, guard `scripts/m3_pii_log_test.py` ALL PASS (4 gap HIGH đã đóng; 1 known-limitation PSID-trong-URL-log còn mở, không phải HIGH) |
| 2 | Vendor/AI Use Case review accepted | 🟡 **PASS CÓ ĐIỀU KIỆN** — xem §1 (Stage 0P không gọi vendor nên gap cross-border DeepSeek không block trực tiếp; cần UC mới, đề xuất ở §2) |
| 3 | Production-data access approved PO/CA | ⏳ **ĐANG XIN** — chính là mục đích gói này |
| 4 | Retention/labeling environment verified | ⏳ **THIẾT KẾ TRONG GÓI NÀY** — xem §5, §6 (RET-11 trong Retention Schedule hiện chỉ là khung rỗng "thiết kế tại M4") |
| 5a | Rollback/kill switch — detector shadow (`m4_pii_shadow`) | ✅ **PASS** — flag OFF = 0 code path chạy (evidence S0/S3: 214 pytest bao gồm flag-OFF regression, static check orchestrator không tham chiếu `m4_trusted_pii_path`) |
| 5b | Rollback/kill switch — raw sample capture | 🔧 **DESIGN DEFINED / NOT VERIFIED** (F-M4-0P-01B) — control source giờ là **row DB động** (không phải `settings` nạp 1 lần), ngữ nghĩa ở §9; PASS chỉ sau implementation test (OFF từ session khác giữa lúc job chạy, chứng minh không commit nào sau boundary) + rollback rehearsal thật |

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

## 4. Sampling method (Directive §6 mục 3) + quy mô đại diện — **sửa theo F-M4-0P-03B**

**Sửa lỗi schema (tự phát hiện khi thiết kế lại):** bản trước viết "`orders.conversation_id`" —
cột này **không tồn tại**. Schema thật: `orders.customer_id → customers.id`,
`conversations.customer_id → customers.id` (không có liên kết trực tiếp order↔conversation).
Đã sửa câu truy vấn eligibility bên dưới cho khớp schema thật.

**Sampling UNIT tường minh:** đơn vị **chọn** là **hội thoại**; đơn vị **lưu trữ** là **tin
nhắn** (1 row = 1 `encrypted_message`, §6). Cả hai đều có cap riêng, không suy diễn cap này ra
cap kia.

**Sửa cap byte (F-M4-0P-03B — CA chỉ đúng: `text[:2000]` là 2000 CODE POINT, không phải byte;
1 ký tự tiếng Việt có dấu có thể chiếm 2-3 byte UTF-8, worst case 4 byte/ký tự):**

- **Cửa sổ:** 14 ngày liên tục kể từ ngày kích hoạt.
- **Cap A — hội thoại:** hard cap **260**.
- **Cap B — tin nhắn khách/hội thoại:** hard cap **20** — chỉ lấy **20 tin đầu tiên** theo
  `created_at ASC, id ASC` (deterministic); phần dư không thu thập, log metric đếm.
- **Cap C — BYTE thật/tin nhắn (tách riêng khỏi cap ký tự, đặt tên rõ ràng theo yêu cầu CA):**
  - `MAX_CHARS = 2000` (character cap — vẫn giữ, dùng cho bước cắt ban đầu để giới hạn khối
    lượng xử lý).
  - `MAX_BYTES = 8000` (**byte cap thật**, = 2000 × 4 byte — worst case UTF-8 cho 1 code point).
    Đây là **constraint chính**, không suy ra từ cap ký tự.
  - **Thuật toán cắt 2 bước, UTF-8-safe cả hai bước:**
    1. Cắt theo ký tự trước: `s = text[:MAX_CHARS]` (string-level, an toàn code-point).
    2. Mã hoá UTF-8, nếu `len(s.encode('utf-8')) > MAX_BYTES`: cắt tiếp trên **bytes đã encode**
       tại `MAX_BYTES`, sau đó `decode('utf-8', errors='ignore')` — `errors='ignore'` ở đây CHỈ
       loại bỏ đúng phần chuỗi byte KHÔNG HOÀN CHỈNH bị cắt dở ở cuối (1 ký tự đa-byte bị chẻ
       đôi), không làm hỏng bất kỳ ký tự nào đứng trước nó — kết quả luôn là UTF-8 hợp lệ.
  - Row bị cắt ở BẤT KỲ bước nào → `truncated=true` — loại khỏi mẫu số recall/precision chính
    (nguyên tắc `gate=false` như S0), báo cáo riêng.
- **Cap D — trần byte tuyệt đối (con số THẬT, không phải ước lượng sai trước đây):**
  260 × 20 × **8000 byte** (MAX_BYTES, không phải MAX_CHARS) = **41.6 MB** plaintext-equivalent
  tối đa toàn sample zone — **gấp ~4 lần con số 10.4MB đã khai báo sai ở bản v3** (CA phát hiện
  đúng). Ciphertext lớn hơn không đáng kể (overhead nonce+tag cố định 12+16+1 byte/row).
- **Enforce lại ở DB boundary, không chỉ counter trong process (CA yêu cầu tường minh):** thêm
  `CHECK (octet_length(encrypted_message) <= 8045)` (8000 + 29 byte overhead cố định của
  `encrypt_sample_value`: version 1 + nonce 12 + tag 16 = 29 — dư biên nhỏ) trên chính cột —
  Postgres từ chối INSERT nếu logic cắt ở tầng ứng dụng có bug, không phụ thuộc 100% vào code
  Python đúng.
- **Thực thi đơn-writer (chống race — test concurrent collector):** advisory lock **tái dùng
  đúng pattern** `scripts/migrate.py` (`pg_try_advisory_lock` fail-fast, `LOCK_KEY` riêng M4).
  Chỉ 1 tiến trình collector chạy tại một thời điểm ⇒ cap giữ bởi bộ đếm trong tiến trình đó
  (check tại đúng 1 checkpoint trước mỗi INSERT — cùng điểm với kill switch §9 và pending-
  deletion re-check §5.3).
- **Thuật toán chọn — 2 pha tách bạch, KHÔNG đọc nội dung tin nhắn ở pha 1:**
  1. **Pha chọn (metadata-only, sửa đúng schema VÀ sửa phạm vi eligibility — F-M4-0P-03B):**
     `E` = tập `conversations.id` sao cho **(a)** tồn tại ≥1 `orders` với
     `orders.customer_id = conversations.customer_id` và `orders.created_at` trong cửa sổ 14
     ngày, **VÀ (b) `conversations.created_at` CŨNG nằm trong đúng cửa sổ 14 ngày đó** (KHÔNG
     chỉ ràng buộc qua `orders`). Điều kiện (b) là bổ sung mới — thiếu nó, join theo
     `customer_id` một mình có thể kéo theo **mọi hội thoại cũ, không liên quan** của một khách
     hàng chỉ vì họ có 1 đơn hàng mới trong cửa sổ (đúng lỗ hổng CA chỉ ra). Không đọc
     `messages.content`. Sắp xếp deterministic theo `conversations.id ASC`.
  2. `|E| ≤ 260` → chọn toàn bộ `E`. `|E| > 260` → chọn 260 bằng permutation seed cố định công
     khai `SHA256("m4-stage0p-v1")` — tái lập được độc lập.
  3. Tập chọn được **KHOÁ LẠI** thành 1 row trong bảng `m4_selection_batches` (§5.1) — chỉ sau
     khi khoá xong, pha thu thập mới đọc nội dung, chỉ đọc đúng batch đã khoá (§5.2).
  4. Mỗi row lưu `selection_batch` = id batch đã khoá.
- **Test bổ sung khi triển khai (F-M4-0P-03B, đúng 4 case CA yêu cầu):** multi-byte (tin nhắn
  toàn ký tự có dấu, kiểm MAX_BYTES là constraint chốt chặn thật, không phải MAX_CHARS);
  oversized ciphertext (cố tình vượt `octet_length` CHECK → INSERT bị DB từ chối); old
  conversation (hội thoại `created_at` NGOÀI cửa sổ dù khách có order trong cửa sổ → loại khỏi
  `E`); unrelated conversation (hội thoại khác của cùng khách, không liên quan đơn hàng, ngoài
  cửa sổ → loại).
- **Loại trừ khi chọn (không quét nội dung — chi tiết interface hẹp ở §5.3 theo F-M4-0P-02B):**
  - Đang chờ xác nhận xoá: kiểm tra qua **interface hẹp riêng** (§5.3) trả về boolean, KHÔNG trao
    PSID cho collector (sửa từ bản v3: trước đây viết tắt "Redis key `del_pending:{psid}`" như
    thể collector tự tra — nay tách hẳn thành 1 dịch vụ nội bộ, xem §5.3). Re-check lại lần nữa
    ngay trước persist mỗi tin nhắn (chống race — §5.3).
  - **Đã hoàn tất xoá dữ liệu: TỰ ĐỘNG loại** — `_delete_customer_data()` xoá cứng toàn bộ
    `conversations`, khách không còn xuất hiện trong `E`. Luật "90 ngày" giữ nguyên rút lại như
    bản v3 (lý do đầy đủ ở Correction #2) — không lặp lại ở đây.
- **Dưới ngưỡng:** nếu `|E| < 200` khi hết cửa sổ 14 ngày → dừng, báo cáo, chờ quyết định (không
  tự gia hạn) — giữ nguyên.
- **Metric:** chỉ log counts (`eligible=N excluded_old_conversation=X excluded_pending=K
  selected=M truncated_conversations=T truncated_messages=U`), không định danh hội thoại/khách.
- **Test boundary khi triển khai kỹ thuật:** hội thoại đúng 21 tin nhắn khách → chỉ 20 được lưu;
  tin nhắn toàn ký tự đa-byte đúng 2001 code point → cắt theo MAX_CHARS rồi MAX_BYTES, kiểm tra
  byte cap là constraint chốt (không phải char cap); cố tình đẩy `octet_length` vượt 8045 →
  DB CHECK từ chối INSERT; 2 collector cùng khởi động → fail-fast; hội thoại cũ ngoài cửa sổ của
  khách có order mới → loại khỏi `E`; hội thoại khác không liên quan cùng khách → loại.

## 5. Labeling roles / access matrix (Directive §6 mục 4) + reviewer audit (mục 7) — **sửa theo F-M4-0P-02, F-M4-0P-02A, F-M4-0P-02B, F-M4-0P-05**

CA chỉ ra đúng qua 3 vòng: (Review #1) bản v1 vừa cấp `SELECT` trực tiếp cho reviewer vừa nói
"phải qua view/API" — mâu thuẫn. (Review #2) bản v2 không nói ai/bằng cách nào đọc được
`messages.content` thật. (Review #3) hướng hàm `SECURITY DEFINER` đúng nhưng **thiếu hardening
cụ thể** (search_path, owner, revoke-from-public, validate trạng thái batch) **và** thiết kế
kiểm tra pending-deletion ngầm giả định collector có PSID mà không nói rõ đường lấy — cần 1
interface hẹp riêng. Thiết kế đầy đủ:

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

### 5.2. Đường đọc nội dung duy nhất — hàm `SECURITY DEFINER`, không SELECT trực tiếp trên `messages` — **hardening theo F-M4-0P-02B**

`m4_stage0p_fetch_batch_content(batch_id UUID) RETURNS TABLE(conversation_id, message_id,
content, created_at)`. Ràng buộc cứng trong thân hàm (logic bắt buộc, không phải quy ước):

- **Chỉ trả `role = 'customer'`** (loại trừ tuyệt đối `bot`/`agent`).
- **Chỉ trả tin nhắn thuộc `conversation_id` nằm trong `locked_conversation_ids` của ĐÚNG
  `batch_id` truyền vào** — hàm tự tra `m4_selection_batches`, không nhận `conversation_id` làm
  tham số ⇒ loại bỏ "arbitrary conversation-id query".
- **Validate trạng thái batch TRƯỚC khi trả bất kỳ row nào** (mới, F-M4-0P-02B): `status =
  'locked'` (từ chối nếu `'closed'` hoặc không tìm thấy — chặn tái sử dụng batch cũ);
  `now() BETWEEN window_start AND window_end + khoảng đệm hợp lý` (chặn replay batch_id ngoài
  cửa sổ hợp lệ); `purpose_code` khớp `P12_PII_DETECTOR_EVAL`.
- **Không có cột/loại attachment trong schema `messages` hiện tại** — ghi rõ ràng buộc để nếu
  sau này thêm cột đính kèm, hàm phải cập nhật tường minh, không "tự động an toàn".
- Áp Cap B/MAX_CHARS/MAX_BYTES của §4 **ngay trong hàm** trước khi trả.
- **Hardening `SECURITY DEFINER` chuẩn Postgres (mới, F-M4-0P-02B — không phải tuỳ chọn):**
  - `SET search_path = pg_catalog, public` khai báo ngay trong `CREATE FUNCTION` (chặn
    search-path injection).
  - Mọi object tham chiếu trong thân hàm **schema-qualify tường minh** (`public.messages`,
    `public.m4_selection_batches`) — phòng thủ kép dù đã khoá search_path.
  - **Owner = `alpha3s`** (role migration-owner sẵn có, đã xác nhận non-superuser qua
    postcondition 038) — KHÔNG tạo role đặc quyền mới cho việc này.
  - `REVOKE EXECUTE ON FUNCTION m4_stage0p_fetch_batch_content(uuid) FROM PUBLIC;` tường minh,
    sau đó `GRANT EXECUTE ... TO alpha3s_m4_sample_collector` — không dựa vào default PUBLIC
    EXECUTE mà Postgres cấp ngầm cho function mới tạo.
- **Audit fail-closed TRONG CÙNG STATEMENT** (mới, F-M4-0P-02B — không phải audit-rồi-mới-đọc
  như §5.1 review trước mô tả chung chung): hàm ghi dòng audit (`action='m4_batch_fetch',
  entity_type='m4_selection_batch', entity_id=batch_id, after={"row_count": N}`) là một phần của
  CÙNG câu lệnh trả dữ liệu (vd CTE ghi audit rồi SELECT nội dung trong 1 statement) — nếu ghi
  audit lỗi, toàn bộ statement rollback, không có content nào được trả. Thu hồi `EXECUTE` là
  lever kill riêng, độc lập với §9.

| Role DB | Quyền trên `m4_shadow_review_samples` | Quyền khác | Dùng bởi |
|---|---|---|---|
| `alpha3s_m4_sample_collector` | INSERT-only | `EXECUTE m4_stage0p_fetch_batch_content` (§5.2); SELECT metadata `orders.customer_id, orders.created_at, conversations.id, conversations.customer_id` cho pha chọn §4 (KHÔNG `messages`) | Job thu thập, serialize bằng advisory lock (§4) — **principal DUY NHẤT ghi vào sample zone và DUY NHẤT đọc `messages.content`, qua hàm, không qua SELECT** |
| `alpha3s_m4_sample_reviewer_api` | SELECT `sample_id, encrypted_message, canonical_text_len, normalization_version, customer_ref, conversation_ref, captured_at, label_status` — **KHÔNG** `predicted_slots`/`detector_version` (chống thiên lệch xác nhận, F-M4-0P-05) | UPDATE `labeled_slots, label_status` (ghi nhãn kèm offset) | **CHỈ credential tiến trình API nội bộ** (ops endpoint, tái dùng xác thực `staff_users`/`staff_sessions` — `app/services/auth_service.py`). Con người không bao giờ cầm credential DB này; PO đăng nhập qua session staff, endpoint giải mã + **ghi audit TRƯỚC KHI trả dữ liệu** (fail closed nếu audit lỗi) |
| `alpha3s_m4_sample_evaluator` | SELECT **chỉ** `sample_id, label_status, labeled_slots, predicted_slots, canonical_text_len, normalization_version, detector_version, evaluation_batch, selection_batch, truncated` — **KHÔNG** `encrypted_message`, **KHÔNG** `customer_ref`/`conversation_ref` | — | Eval script (Dev) đo recall/precision qua offset (§10) — không đọc được nội dung thô, chỉ nhãn + dự đoán + metadata cần để validate bounds |
| `alpha3s_m4_prediction_writer` (mới) | UPDATE **chỉ** `predicted_slots, detector_version, evaluation_batch` | `EXECUTE` hàm chạy detector nội bộ (đọc `encrypted_message` **của chính hàm này**, giải mã tạm trong bộ nhớ, KHÔNG trả plaintext ra ngoài, chỉ ghi lại kết quả `as_safe_dict`-shape) | Job chấm điểm sau-labeling (§5.4) — tách khỏi reviewer-api và evaluator |
| `alpha3s_m4_sample_purge` | DELETE + SELECT **chỉ** `customer_ref, expires_at, sample_id` | — | Purge job (retention §6 + DSR §7) |
| `alpha3s_app` (runtime) | KHÔNG có quyền nào | — | Sample zone hoàn toàn ngoài request-path production |
| `alpha3s_vendor_path` | KHÔNG có quyền nào (REVOKE ALL, đúng nguyên tắc `pii_slots` 038) | — | — |

`REVOKE ALL ON m4_shadow_review_samples, m4_selection_batches FROM PUBLIC` là bước đầu tiên của
migration khi triển khai — mọi quyền trên đều là GRANT tường minh, không có quyền ngầm định.

### 5.3. Interface hẹp kiểm tra pending-deletion — KHÔNG trao PSID cho collector (mới, F-M4-0P-02B)

CA chỉ đúng: §4 nói kiểm tra `del_pending:{psid}` nhưng collector chỉ có `customer_id` (từ
metadata §4), không có `psid` — thiết kế trước bỏ ngỏ ai/bằng cách nào lấy `psid` để tra Redis,
và tra ngầm như vậy sẽ vô tình "trao PSID" cho collector.

- **Hàm/module riêng** (Python, KHÔNG phải SQL — Postgres không gọi Redis trực tiếp được):
  `is_pending_deletion(customer_id: int) -> bool`. Bên trong: tra `customers.psid` bằng
  `customer_id` (đọc có kiểm soát, không phải SELECT rộng), gọi Redis `EXISTS del_pending:
  {psid}`, trả **boolean**. Biến `psid` **chỉ tồn tại trong scope của hàm này** — không được
  trả ra, không log, không đưa vào audit metadata, không gán vào state của collector.
- **Audit riêng cho lần gọi này:** `action='m4_pending_check', entity_type='customer',
  entity_id=customer_id` (KHÔNG phải psid), `after={"pending": true/false}` — chỉ boolean.
- **Race giữa eligibility check (Phase 1) và persist (Phase 2) — CA yêu cầu xử lý tường minh:**
  gọi lại `is_pending_deletion()` **lần nữa ngay trước mỗi lệnh INSERT** (cùng checkpoint với
  kill switch §9 và cap §4 — 1 điểm kiểm tra duy nhất trước mỗi ghi, gộp cả 3 điều kiện: flag
  ON? cap chưa vượt? khách không pending-deletion?). Nếu pending xuất hiện giữa 2 lần check →
  bỏ qua (không ghi) các tin nhắn còn lại của khách đó trong lượt chạy, log metric đếm.
  **Ngay cả khi race vẫn lọt** (vd deletion hoàn tất đúng lúc): **DSR §7 là thẩm quyền cuối
  cùng, không điều kiện** — `DELETE ... WHERE customer_ref = $1` chạy vô điều kiện khi có yêu
  cầu xoá, xoá sạch bất kỳ row nào đã lỡ lọt qua re-check. Re-check ở đây là phòng thủ giảm cửa
  sổ rủi ro, KHÔNG phải lớp bảo vệ duy nhất.

### 5.4. Chống thiên lệch xác nhận (F-M4-0P-05) — thứ tự bắt buộc, không chỉ là quy ước API

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

## 6. Storage zone + retention/expiry (Directive §6 mục 5, 6) — **F-M4-0P-04 CLOSED; cột cho F-M4-0P-03B/05A**

CA xác nhận phần domain tag/AAD riêng + DSR direct-link (§6/§7 bản v2.0.0) **đã đủ ở tầng thiết
kế qua cả 3 vòng review** — giữ nguyên, không sửa lại phần crypto/DSR. Phần dưới đây cập nhật cột
cho F-M4-0P-03B (byte cap thật) và **F-M4-0P-05A (offset — thay đổi quan trọng nhất ở v4):
ground truth và prediction giờ PHẢI giữ vị trí span, không còn instance-count-only**.

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
  `customer_ref` (= `customers.id`, KHÔNG dùng `psid` — lý do: `psid` bị ghi đè thành
  `deleted:<code>` khi xoá, còn `customers.id` bất biến suốt vòng đời, tra cứu DSR §7 ổn định
  hơn), `conversation_ref` (**plaintext, indexed** — lý do giữ plaintext ở dưới),
  `encrypted_message` (blob `encrypt_sample_value` output, đã cắt theo MAX_CHARS/MAX_BYTES §4
  TRƯỚC khi mã hoá — CHECK `octet_length` §4), `canonical_text_len` (int — độ dài chuỗi canonical
  ĐÃ CẮT, dùng để validate offset bounds khi chấm điểm, KHÔNG phải nội dung), `truncated` (bool —
  loại khỏi mẫu số recall/precision chính khi True), `captured_at`, `expires_at` (NOT NULL),
  `purpose_code='P12_PII_DETECTOR_EVAL'`, `label_status` (unlabeled/labeled),
  `normalization_version` (text, vd `"nfc-v1"` — khớp `app/services/pii/normalize.py:nfc()`,
  **bắt buộc** vì offset chỉ có nghĩa khi biết chuỗi canonical nào sinh ra nó — F-M4-0P-05A),
  `labeled_slots` (jsonb — **ground truth**, reviewer gán tay, format
  `[{slot_type, start, end, confidence, reason}]` — **CÓ offset** (sửa từ v3: CA Review #3 xác
  nhận "offset không phải plaintext PII", nên khác với `PIISpan.as_safe_dict()` dùng cho log
  live-traffic ở S0 — xem giải trình vì sao 2 format khác nhau ở §10), `predicted_slots` (jsonb
  — **output detector**, CÙNG FORMAT `{slot_type, start, end, confidence, reason}`; NULL cho tới
  khi cả batch labeled xong — §5.4), `detector_version` (text, vd `m4d-0.1.0` — tái dùng hằng số
  `DETECTOR_VERSION` ở `taxonomy.py`), `evaluation_batch` (text — phân biệt lần chấm điểm nếu
  detector re-run version mới trên cùng ground truth; cùng với `detector_version` +
  `normalization_version` tạo thành **evaluation hash** truy vết được — §10), `selection_batch`
  (§4).
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
  - `labeled_slots`/`predicted_slots` (nhãn — không phải raw): có thể giữ lâu hơn nếu PO muốn
    dùng làm regression corpus cho detector version sau — nhưng **chỉ khi đã tách khỏi
    `encrypted_message`**. Offset (start/end) tự nó **không phải plaintext PII** (2 số nguyên,
    không suy ngược được nội dung nếu không còn `encrypted_message`/`canonical_text_len` đi
    kèm) — CA Review #3 xác nhận rõ điều này; khác với quyết định S0 (`PIISpan.as_safe_dict()`
    loại offset) vốn áp cho **log live-traffic phát ra liên tục** (bối cảnh khác — xem §10).
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

## 9. Incident path (Directive §6 mục 10) — **kill switch sửa theo F-M4-0P-01, F-M4-0P-01A, F-M4-0P-01B**

CA chỉ ra qua 3 vòng: (#1) `m4_pii_shadow` không liên quan raw sample capture — cần công tắc
riêng. (#2) "no-op ở lượt chạy tiếp theo" không đủ chặt cho 1 batch đang ghi dở — cần re-check ở
đơn vị nhỏ nhất. (#3) — **đúng và quan trọng nhất**: dù đã re-check trước mỗi INSERT, nếu nguồn
đọc là `settings.m4_stage0p_capture_enabled` (pydantic-settings, nạp **một lần** lúc process
khởi động — đúng cách toàn bộ `app/config.py` hoạt động, xem `settings = Settings()` module-level
singleton) thì **process đang chạy không bao giờ thấy được thay đổi env/config bên ngoài** — re-
check trước mỗi INSERT chỉ đọc lại đúng 1 giá trị Python tĩnh trong bộ nhớ, không phải trạng thái
động. Đây là lỗi thiết kế thật, không phải chi tiết.

**Sửa: nguồn control chuyển từ static settings sang 1 ROW DB động, đọc tươi mỗi lần (F-M4-0P-01B):**

```text
CREATE TABLE m4_stage0p_control (
  id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- singleton, dung idiom Postgres chuan
  capture_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by TEXT
)
```

| Công tắc | Nguồn | Phạm vi | Default | Khi TẮT |
|---|---|---|---|---|
| `m4_pii_shadow` (đã có từ S0) | `settings` (static — đúng, vì đây chỉ là flag đọc 1 lần lúc orchestrator xử lý 1 request, không phải long-running job) | Detector trong orchestrator | OFF | 0 code path — không đổi |
| capture control | **row `m4_stage0p_control`** (động — SỬA theo F-01B, không dùng `settings` cho control của 1 long-running job) | Job thu thập (§4) | `capture_enabled=FALSE` mặc định; **thiếu row = coi như FALSE** (fail closed, giữ đúng nguyên tắc "missing config = OFF" dù nguồn đã đổi từ settings sang DB) | Xem ngữ nghĩa dưới |

**Ngữ nghĩa "kill" — đọc tươi từ DB trước MỖI INSERT, có giới hạn thời gian đọc tường minh:**

1. Trước mỗi INSERT 1 row, collector chạy `SELECT capture_enabled FROM m4_stage0p_control WHERE
   id=1` trên **connection/transaction hiện tại** — Postgres READ COMMITTED đảm bảo mỗi câu SELECT
   mới thấy giá trị **đã commit gần nhất** từ bất kỳ session nào khác, giải quyết đúng vấn đề CA
   nêu (không còn đọc lại 1 biến Python tĩnh). Cùng checkpoint dùng cho cap §4 và pending-deletion
   §5.3 — 1 điểm kiểm tra duy nhất trước mỗi ghi.
2. **Đọc lỗi/timeout = OFF (fail closed, tường minh — CA yêu cầu):** câu SELECT control chạy với
   `SET LOCAL statement_timeout = '2s'` — nếu không trả về trong 2 giây (DB quá tải, mất kết nối,
   …) → coi như đọc thất bại → xử lý như FALSE → dừng ghi. Không có nhánh "đọc lỗi thì cứ tiếp tục
   giả định vẫn ON".
3. **Maximum stop latency định nghĩa lại — có cơ chế thật đứng sau, không phải ước lượng:**
   ≤ 2 giây (statement_timeout ở trên) + thời gian hoàn tất 1 INSERT một row đang thực thi dở
   (thực tế mili-giây, nhưng KHÔNG còn là con số duy nhất tự đứng — có timeout 2s làm cận trên
   cứng khi đường đọc control gặp sự cố).
4. Tắt (`UPDATE m4_stage0p_control SET capture_enabled=false ...` từ session khác) → dừng ghi MỚI
   theo ngữ nghĩa trên; KHÔNG xoá row đã có sẵn (chỉ qua retention §6/DSR §7).
5. Thu hồi quyền reviewer vẫn là hành động ĐỘC LẬP với control này (không đổi từ v3).
6. **Evidence bắt buộc trước khi prerequisite 5b được PASS (methodology CA yêu cầu, thực hiện ở
   submission kỹ thuật):** từ 1 session KHÁC, `UPDATE` control row thành FALSE **giữa lúc** job
   collector đang chạy dở (không dừng job trước); sau đó xác nhận: (a) không có row nào trong
   `m4_shadow_review_samples` có `captured_at` SAU thời điểm commit của UPDATE đó (chứng minh
   ranh giới, không chỉ "job dừng lại"); (b) đọc-lỗi-giả-lập (ngắt kết nối control table) cũng
   dừng ghi tương đương. Đây là việc của submission kỹ thuật, không phải gói governance này.

**Escalation** (không đổi): theo đúng kênh hiện dùng cho các gate M1–M3 — Telegram ping tới anh
Hoài khi phát hiện sự cố privacy/security (đúng thoả thuận đã ghi ở [[telegram-approve-pings]]),
đi "incident route ngay, không chờ Delivery Package" (Directive §16/spec stop conditions).

**Trigger cụ thể cho Stage 0P:** raw PII xuất hiện ngoài sample zone (log/trace/dead-letter);
cross-customer row trong sample zone (binding fail — evidence bắt buộc theo §7); reviewer truy
cập ngoài audit (audit ghi `outcome=denied` bất thường hoặc API bị bypass); sample vượt cửa sổ
14 ngày/hard cap 260 mà chưa có quyết định gia hạn (§4); DSR không xoá được sample trong 1
transaction (§7).

## 10. Evaluation methodology — matching rule + aggregation — **sửa theo F-M4-0P-05A**

**Rút lại instance-count-only.** CA Review #3 chỉ đúng: count theo `(message, slot_type)` có thể
báo TP dù detector khoanh SAI vị trí/thực thể miễn số lượng và loại khớp — ví dụ tin nhắn có 2 số
điện thoại, detector bắt trúng số #1 hai lần (bỏ sót số #2), count-only vẫn báo `2 khớp 2` = TP=2,
sai hoàn toàn. Phương pháp S0 (đúng cho smoke test synthetic, nơi Dev tự kiểm soát cả corpus lẫn
kỳ vọng) **không tự động mở rộng thành acceptance methodology cho sample thật** — CA nói rõ điều
này, và đúng.

**Matching rule mới — exact-span là chính, count-only chỉ là metric phụ:**

- Cả `labeled_slots` và `predicted_slots` giữ `start`/`end` (offset ký tự trên **canonical text
  đã normalize + đã cắt theo cap §4** — chuỗi này không lưu trực tiếp nhưng xác định qua
  `encrypted_message` giải mã + `normalization_version` + `canonical_text_len` §6). Offset **không
  phải plaintext PII** (CA xác nhận) — khác quyết định S0 (`PIISpan.as_safe_dict()` loại offset)
  vì bối cảnh khác hẳn: S0 là **log live-traffic phát liên tục ra stdout** (bối cảnh rủi ro cao
  hơn, tối giản triệt để); Stage 0P sample là **jsonb trong DB restricted-access có RBAC + audit
  chặt (§5)**, offset ở đây an toàn và cần thiết để đo đúng. **Không sửa `as_safe_dict()`/S0** —
  giữ nguyên, 2 format phục vụ 2 mục đích khác nhau.
- **Gate chính: exact-span match** — `slot_type` khớp VÀ `(start, end)` khớp chính xác giữa 1 cặp
  ground-truth/prediction (không ghép chéo — 1 prediction chỉ khớp tối đa 1 ground-truth và
  ngược lại, ưu tiên khớp theo thứ tự offset tăng dần khi có nhiều ứng viên).
- **Metric phụ: overlap/IoU** — `IoU = |giao (start,end)| / |hợp (start,end)|`, ngưỡng khớp
  **cần PO/CA phê duyệt cụ thể** trước khi dùng cho bất kỳ quyết định gate nào (Dev không tự chọn
  ngưỡng) — báo cáo song song với exact-span để CA thấy độ nhạy của kết quả với định nghĩa "khớp".
- **Count-only (§10 bản v3)** hạ xuống **metric tham khảo bổ sung**, không còn là gate.
- **Non-overlap policy:** trong CÙNG một tập nhãn (ground-truth hoặc prediction) của 1 message,
  các span không được chồng lấn nhau — nếu detector/reviewer tạo span chồng lấn, coi là lỗi dữ
  liệu, loại row khỏi batch tính gate (không âm thầm gộp/chọn 1 trong 2).
- **Offset bounds:** `0 ≤ start < end ≤ canonical_text_len` — vi phạm bounds là lỗi dữ liệu, loại
  khỏi gate, log riêng (không phải "gate=false" như truncated — đây là bug cần điều tra).
- **Normalization mapping:** ground-truth VÀ prediction của CÙNG 1 message phải cùng
  `normalization_version` — khác version thì không so khớp trực tiếp được (offset không còn cùng
  ý nghĩa), loại khỏi gate cho tới khi ground-truth được relabel với version khớp.
- **Truncated row:** giữ nguyên loại khỏi mẫu số gate chính (§4/§6), báo cáo riêng — không đổi.
- **Aggregation: micro** (gộp TP/FN/FP toàn batch trước khi tính recall/precision) — giữ như v3,
  vẫn đúng dù đổi matching rule.
- **Evaluation hash:** `(detector_version, normalization_version, evaluation_batch)` cùng nhau
  xác định duy nhất 1 lần chấm điểm — ghi trong report để tái lập/audit lại được.
- **Thứ tự bắt buộc — chống thiên lệch xác nhận (không đổi):** ground-truth labeling phải hoàn
  tất toàn bộ batch trước khi `predicted_slots` được ghi (§5.4, ràng buộc cấu trúc).
- **Test khi triển khai kỹ thuật:** offset ngoài bounds → loại + log; 2 span chồng lấn trong cùng
  message → loại + log; ground-truth/prediction khác `normalization_version` → loại khỏi gate;
  detector đúng số nhưng sai vị trí (case tái tạo ví dụ CA nêu: 2 phone, detector bắt trùng 1 vị
  trí 2 lần) → exact-span phải báo FN=1 (số #2 bị bỏ sót) + FP=1 (bắt trùng số #1), KHÔNG còn là
  TP=2 giả như count-only.

## 11. Điều kiện Dev đề nghị PO/CA quyết định

| # | Nội dung | Trạng thái sau CA Review #3 |
|---|---|---|
| 1 | Duyệt/không duyệt mở Stage 0P với thiết kế §2–§10 | ⏳ CHỜ CA review lại — 4 mục con (01B/02B/03B/05A) đã sửa, mapping ở §12, chờ "Stage 0P Design Accepted" |
| 2 | Purpose code mới `P12_PII_DETECTOR_EVAL` | ✅ CA ACCEPTED (Review #1) — không đổi |
| 3 | Retention 45 ngày | 🟡 CA ACCEPTED trần kỹ thuật, có điều kiện (Review #1) — không đổi |
| 4 | Ranh giới vendor gap | ✅ CA ACCEPTED có điều kiện (Review #1) — không đổi |
| 5 | Reviewer cụ thể | ✅ PO ĐÃ DUYỆT (29/7 07:43); CA ghi nhận — không đổi |
| 5b | Kill switch capture path | 🔧 DESIGN DEFINED / NOT VERIFIED (F-01B) — nguồn control đổi sang DB row động; PASS chỉ sau implementation test (OFF giữa batch từ session khác + chứng minh boundary) + rollback rehearsal |
| 6 | Cơ sở pháp lý xử lý | ✅ PO ĐÃ DUYỆT (29/7 07:43); CA ghi nhận — không đổi |

**Vẫn chưa có bước triển khai kỹ thuật nào được thực hiện** — đúng ranh giới CA nhắc lại cuối cả
3 lần review. Sau khi CA ra "Stage 0P Design Accepted", Dev mở submission kỹ thuật riêng:
migration `m4_shadow_review_samples` + `m4_selection_batches` + `m4_stage0p_control` + hàm
`m4_stage0p_fetch_batch_content` (hardened) + hàm `is_pending_deletion` + 6 role DB (§5) + control
động với re-check trước mỗi INSERT (§9), cập nhật Deletion Propagation Map (mục #17, §7), bổ
sung UC-004 chính thức, sample job 2 pha cap 4 lớp + eligibility window đúng (§4), job chấm điểm
sau-labeling dùng exact-span (§5.4, §10), rồi mới bật capture control trên tập traffic đã duyệt —
mỗi bước có evidence riêng theo đúng khuôn mẫu S0–S3.

## 12. Mapping finding → sửa ở đâu (cộng dồn 3 vòng review, bản v4.0.0)

| Finding | Vòng phát sinh | Vòng đóng | Sửa tại |
|---|---|---|---|
| F-M4-0P-01 | #1 | base | §9 |
| F-M4-0P-01A | #2 | v3 (nhưng #3 phát hiện chưa đủ → 01B) | §9 |
| **F-M4-0P-01B** | **#3** | **Sửa ở v4** | §9 — control nguồn từ **row DB động** `m4_stage0p_control` (không phải `settings` static), đọc tươi trước mỗi INSERT, `statement_timeout=2s` + đọc-lỗi=OFF, evidence methodology boundary rõ |
| F-M4-0P-02 | #1 | base | §5 |
| F-M4-0P-02A | #2 | v3 (nhưng #3 yêu cầu hardening → 02B) | §5.1, §5.2 |
| **F-M4-0P-02B** | **#3** | **Sửa ở v4** | §5.2 — hardening `SECURITY DEFINER` (search_path/schema-qualify/owner non-superuser/revoke-from-public/validate batch status+window+purpose/audit cùng statement); §5.3 mới — interface hẹp `is_pending_deletion(customer_id)` không trao PSID, re-check race trước persist, DSR §7 là thẩm quyền cuối |
| F-M4-0P-03 | #1 | base | §4 |
| F-M4-0P-03A | #2 | v3 (nhưng #3 phát hiện char≠byte + eligibility hở → 03B) | §4, §6 |
| **F-M4-0P-03B** | **#3** | **Sửa ở v4** | §4 — tách MAX_CHARS (2000)/MAX_BYTES (8000, cắt 2-bước UTF-8-safe), Cap D thật = 41.6MB (không phải 10.4MB sai trước); DB CHECK `octet_length` enforce lại; eligibility thêm ràng buộc `conversations.created_at` trong cửa sổ (chặn kéo hội thoại cũ/không liên quan) |
| F-M4-0P-04 | #1 | #2 | ✅ **CLOSED**, giữ nguyên qua cả Review #3 |
| F-M4-0P-05 | #2 (mới) | v3 (nhưng #3 bác methodology → 05A) | §5.2, §5.4, §6, §10 |
| **F-M4-0P-05A** | **#3** | **Sửa ở v4** | §6 — thêm `start/end` offset + `normalization_version` + `canonical_text_len` vào `labeled_slots`/`predicted_slots`; §10 — viết lại hoàn toàn: exact-span là gate chính, overlap/IoU là metric phụ cần ngưỡng CA/PO duyệt, count-only hạ xuống tham khảo, non-overlap policy, offset bounds, normalization mapping, evaluation hash |
