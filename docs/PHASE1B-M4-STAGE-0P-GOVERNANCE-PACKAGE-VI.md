---
id: A3S-PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-001
title: Alpha3S Phase I-B M4 — Stage 0P Governance Package (Production Shadow Request)
document_type: governance_request_package
owner: Dev
status: PROPOSED — chờ PO/CA phê duyệt
created_at: 2026-07-29 06:17+07:00
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
  Cơ sở pháp lý: legitimate interest (cải thiện kiểm soát bảo vệ dữ liệu) — CẦN PO/legal xác
                 nhận cơ sở cụ thể theo quy định hiện hành trước khi kích hoạt.
  Trạng thái: PROPOSED
```

Đây là format khớp các mục hiện có trong `PROCESSING-PURPOSE-REGISTRY.md`; nếu PO/CA duyệt,
Dev sẽ nộp addition này như một correction nhỏ vào registry chung (KHÔNG tự ý sửa file M3
trong lúc soạn gói đề nghị này).

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

## 4. Sampling method (Directive §6 mục 3) + quy mô đại diện (mục "số lượng/tính đại diện")

- **Cửa sổ:** 14 ngày liên tục kể từ ngày kích hoạt (đúng ngưỡng khởi điểm spec §6/directive §7).
- **Ngưỡng:** tối thiểu 200 hội thoại đặt hàng đủ điều kiện trong cửa sổ; nếu traffic không đủ,
  Dev báo cáo và **không tự rút ngắn** — PO/CA duyệt sample plan thay thế (đúng yêu cầu spec).
- **Phương pháp:** lấy **toàn bộ** hội thoại đặt hàng hợp lệ trong cửa sổ (không random-subsample
  thêm một lớp nữa) — tối đa hoá tính đại diện với quy mô nhỏ này; nếu vượt xa 200 (traffic cao),
  chuyển sang random sampling có stratify theo khung giờ để tránh thiên lệch ca trực.
- **Tính đại diện dự kiến:** đơn hàng qua Messenger là kênh chính (~majority theo ISSUES-VI.md),
  Telegram là dự phòng — sample tự nhiên phản ánh tỷ lệ kênh thật vì lấy toàn bộ, không lọc theo
  kênh.

## 5. Labeling roles / access matrix (Directive §6 mục 4) + reviewer audit (mục 7)

| Vai trò | Quyền | Ghi chú |
|---|---|---|
| Reviewer (gán nhãn) | SELECT trên sample zone (đọc tin nhắn thô để gán nhãn slot) | Danh sách người cụ thể do PO chỉ định bằng tên — **không phải role chung chung**; tối thiểu hoá số người |
| Dev (vận hành/đo eval) | SELECT trên nhãn + metric đã gán (KHÔNG cần đọc lại tin nhắn thô sau khi label xong) | Tách quyền: eval script chạy trên nhãn, không cần quyền đọc raw liên tục |
| Runtime app (`alpha3s_app`) | KHÔNG có quyền trên sample zone | Sample zone tách biệt hoàn toàn khỏi runtime path — detector production (nếu shadow bật) chỉ ghi *metric*, không ghi raw message vào sample zone tự động (xem §6) |
| Vendor-path role | KHÔNG có quyền (đúng nguyên tắc `alpha3s_vendor_path` DENY ALL đã áp cho `pii_slots`) | Áp dụng cùng nguyên tắc cho sample zone khi migration |

**Reviewer audit:** mọi truy vấn SELECT trên sample zone phải đi qua một view/API ghi
audit log (ai, lúc nào, hội thoại nào) — tái dùng pattern `audit_log`/`log_event` đã có từ M1-M3
(`app/services/audit_service.py`, `app/services/command/observability.py`), KHÔNG tạo cơ chế
audit riêng. Access matrix thực tế (role DB nào map sang người nào) là quyết định vận hành của
PO khi phê duyệt — Dev không tự gán quyền DB cho người cụ thể.

## 6. Storage zone + retention/expiry (Directive §6 mục 5, 6)

**Thiết kế đề xuất** (triển khai bằng migration RIÊNG, sau khi có approval — không nằm trong gói
này):

- Bảng mới `m4_shadow_review_samples`, **TÁCH HOÀN TOÀN** khỏi `pii_slots` (Trusted Slot Store là
  cho luồng vận hành masked orchestration tương lai, không phải kho lưu để gán nhãn thủ công —
  gộp chung 2 mục đích sẽ làm access matrix rối và khó audit).
- Cột tối thiểu: `sample_id`, `conversation_ref`, `raw_message` (ENCRYPTED cùng cơ chế AES-GCM
  v2 đã có trong `app/services/pii/crypto.py` — tái dùng, không thiết kế crypto mới),
  `captured_at`, `expires_at` (NOT NULL, bắt buộc), `purpose_code='P12_PII_DETECTOR_EVAL'`,
  `label_status` (unlabeled/labeled), `labeled_slots` (jsonb, nhãn reviewer gán — KHÔNG phải
  output tự động của detector, để tránh vòng lặp "detector tự chấm điểm chính nó" nếu lẫn dữ liệu).
- **Retention cụ thể hoá RET-11** (đề xuất, cần PO duyệt số ngày):
  - `raw_message` (encrypted): xoá **cứng (DELETE, không anonymize)** sau khi hoàn tất eval +
    tối đa **45 ngày** kể từ `captured_at`, tuỳ điều kiện nào tới trước. 45 ngày = 14 ngày thu
    thập + buffer gán nhãn/review + margin an toàn — con số này Dev đề xuất, PO/CA có thể điều
    chỉnh.
  - `labeled_slots` (nhãn, không phải raw): có thể giữ lâu hơn nếu PO muốn dùng làm regression
    corpus cho detector version sau — nhưng **chỉ khi đã tách khỏi `raw_message`** và bản thân
    nhãn không tái tạo lại được nội dung gốc (offset + slot_type, giống `PIISpan.as_safe_dict()`
    đã dùng trong S0, không lưu giá trị plaintext trong nhãn).
  - Purge job tái dùng pattern `purge_expired` đã có ở `app/services/pii/slot_store.py` (DELETE
    theo `expires_at`, log counts-only).
- **Storage zone vật lý:** cùng Postgres instance production (không tách DB riêng — đơn giản hoá
  vận hành cho quy mô nhỏ 200 hội thoại), nhưng **schema/quyền tách biệt** như trên. Nếu PO muốn
  tách hẳn instance/VPC riêng, Dev điều chỉnh thiết kế theo quyết định đó.

## 7. Cơ chế xóa liên kết DSR (Directive §6 — cần bổ sung Deletion Propagation Map)

**Gap xác nhận:** `DSR-RUNBOOK-VI.md` (16 mục propagation) hiện **không có mục nào** cho kho mới
này — đúng như class dead-letter/outbox từng bị bỏ sót trước khi S4 vá. Đề xuất:

- Thêm mục #17 vào Deletion Propagation Map: `m4_shadow_review_samples` — khi khách gửi
  `XOA DU LIEU` xác nhận, `process_deletion()` (`app/services/data_deletion.py`) **PHẢI** DELETE
  mọi row có `conversation_ref` thuộc customer đó, bất kể `expires_at` còn hạn hay không.
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

## 9. Incident path (Directive §6 mục 10)

Tái dùng cơ chế đã có, không tạo quy trình riêng cho M4:

- **Kill switch:** `m4_pii_shadow=false` — đã rehearsal (0 code path khi OFF, evidence S0/S3).
- **Escalation:** theo đúng kênh hiện dùng cho các gate M1–M3 — Telegram ping tới anh Hoài khi
  phát hiện sự cố privacy/security (đúng thoả thuận đã ghi ở [[telegram-approve-pings]]), đi
  "incident route ngay, không chờ Delivery Package" (Directive §16/spec stop conditions).
- **Trigger cụ thể cho Stage 0P:** raw PII xuất hiện ngoài sample zone (log/trace/dead-letter);
  cross-customer row trong sample zone (binding fail); reviewer truy cập ngoài audit; sample
  vượt cửa sổ 14 ngày mà chưa có quyết định gia hạn.

## 10. Điều kiện Dev đề nghị PO/CA quyết định

1. Duyệt/không duyệt mở Stage 0P với thiết kế §2–§9.
2. Duyệt purpose code mới `P12_PII_DETECTOR_EVAL` (§2) hoặc chỉ định mã khác.
3. Duyệt con số retention 45 ngày (§6) hoặc chỉ định số khác.
4. Xác nhận cách đọc ranh giới vendor gap (§1: Stage 0P không cần chờ gap cross-border DeepSeek).
5. Chỉ định danh sách reviewer cụ thể (tên, không phải role chung).
6. Xác nhận cơ sở pháp lý xử lý (§2) — cần legal/PO, không phải quyết định kỹ thuật của Dev.

**Không có bước nào ở trên được Dev tự thực hiện.** Sau khi có quyết định bằng văn bản, Dev sẽ
mở submission kỹ thuật riêng: migration `m4_shadow_review_samples`, cập nhật Deletion Propagation
Map (mục #17), bổ sung UC-004 chính thức, sample job, rồi mới bật `m4_pii_shadow=true` trên tập
traffic đã duyệt — mỗi bước có evidence riêng theo đúng khuôn mẫu S0–S3.
