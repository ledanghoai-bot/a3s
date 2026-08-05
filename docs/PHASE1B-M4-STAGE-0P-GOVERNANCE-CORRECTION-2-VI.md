---
id: A3S-PHASE1B-M4-STAGE-0P-GOVERNANCE-CORRECTION-2-001
title: Alpha3S Phase I-B M4 — Stage 0P Governance Correction #2
document_type: governance_correction
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-29 11:40+07:00
answers_review: PHASE1B-M4-STAGE-0P-GOVERNANCE-REVIEW-2-VI.md (CA, CHANGES_REQUIRED, reviewed_head 0369403e)
corrected_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v3.0.0
language: vi-VN
---

# Stage 0P — Governance Correction #2

Đáp lại `PHASE1B-M4-STAGE-0P-GOVERNANCE-REVIEW-2-VI.md` (re-review Correction #1). Vẫn là
**correction của gói governance** — không migration/collector/production access/role/capture/
flag/merge/deploy nào được tạo hay bật, đúng giới hạn CA nhắc lại ở §4 review.

## Trạng thái finding sau Review #2 (không cần Dev làm gì thêm)

- **F-M4-0P-04: CLOSED AT DESIGN LEVEL** ✅ — CA xác nhận domain tag/AAD riêng + DSR direct-link
  đã đủ. Không sửa thêm phần crypto/DSR trong Correction #2; chỉ bổ sung cột không liên quan
  (prediction/truncated) vào cùng bảng.

## Mapping 4 mục CA yêu cầu (`01A/02A/03A/05`) → sửa

| Mục | Yêu cầu CA | Đã sửa (gói v3.0.0) |
|---|---|---|
| **F-M4-0P-01A** kill switch chưa dừng batch đang chạy | Re-check trước mỗi read/write unit hoặc micro-batch giới hạn rõ; OFF ngăn mọi write tiếp theo; định nghĩa max stop latency + đo; đổi prerequisite #5 thành DESIGN DEFINED/NOT VERIFIED cho capture path; PASS chỉ sau implementation test + rollback rehearsal | §9: re-check `m4_stage0p_capture_enabled` **trước MỖI INSERT một row** (không phải per-batch/per-run); max stop latency = thời gian 1 INSERT dở (mili-giây), không phụ thuộc số record còn lại; prerequisite tách 5a (PASS, detector shadow) / 5b (DESIGN DEFINED/NOT VERIFIED, capture — §11) |
| **F-M4-0P-02A** collector không có đường đọc nội dung được kiểm soát | Không SELECT rộng trên `messages`; audited purpose-bound interface chỉ trả customer-message thuộc batch đã khoá; chống arbitrary conversation-id query, loại assistant/tool/attachment; audit counts/IDs an toàn + negative-permission tests + revoke path; làm rõ loại trừ DSR-90-ngày không quét content | §5.1 bảng khoá `m4_selection_batches` (locked_conversation_ids, không grant SELECT trực tiếp); §5.2 hàm `SECURITY DEFINER` `m4_stage0p_fetch_batch_content(batch_id)` — chỉ nhận `batch_id` (không nhận `conversation_id` tự do), chỉ trả `role='customer'`, tự áp Cap B/C, collector chỉ có `EXECUTE`; audit mỗi lần gọi (count-only); negative-permission test liệt kê; §4 rút lại luật loại-trừ-90-ngày (không khả thi + không cần thiết — xem giải trình dưới) |
| **F-M4-0P-03A** hard cap chưa giới hạn raw footprint | Xác định sampling unit (conversation/message); cap đồng thời conversation + message + byte trước khi persist; deterministic truncation; không gãy UTF-8; test boundary + concurrent collector | §4: sampling unit = hội thoại (chọn) / tin nhắn (lưu) — tường minh cả hai; Cap A=260 hội thoại, Cap B=20 tin/hội thoại, Cap C=2000 ký tự/tin (string-level slice, UTF-8-safe theo thiết kế), Cap D=~10.4MB trần tuyệt đối; đơn-writer bằng advisory lock tái dùng pattern `scripts/migrate.py` (loại bỏ race thay vì cố enforce dưới concurrency); test boundary 21 tin/2001 ký tự/2 collector đồng thời |
| **F-M4-0P-05** evaluation dataset thiếu prediction/detector-version | Lưu prediction offset/type/confidence/reason không plaintext; lưu detector version/config hash + evaluation batch; evaluator chỉ đọc ground-truth + prediction + metadata D4; định nghĩa matching rule + aggregation + handling truncate/exclude; chống reviewer thấy prediction trước khi xong ground-truth | §6 thêm cột `predicted_slots, detector_version, evaluation_batch` (cùng format `labeled_slots`, không offset — xem lý do ở §10); §5.2 role `alpha3s_m4_prediction_writer` tách biệt reviewer-api/evaluator; §5.3 ràng buộc CẤU TRÚC (cột rỗng cho tới khi cả batch labeled xong, không phải quy ước API); §10 mới: matching rule = instance-count theo `(message, slot_type)` (nhất quán phương pháp S0, giải trình lý do không dùng offset-overlap), aggregation = micro, loại `truncated=true` khỏi mẫu số chính |

## Phát hiện tự rà soát trong lúc sửa (không phải CA yêu cầu, nhưng liên quan trực tiếp)

1. **Lỗi schema tự phát hiện:** bản v2 viết "`orders.conversation_id`" — cột này **không tồn
   tại** trong schema thật (`orders` chỉ có `customer_id`, không có `conversation_id`). Đã sửa
   câu truy vấn eligibility ở §4 sang đúng `orders.customer_id = conversations.customer_id`.
2. **Rút lại luật loại trừ "90 ngày":** đây chính là câu trả lời cho yêu cầu CA "làm rõ cách
   kiểm tra DSR exclusion 90 ngày mà không quét content". Sau khi đọc lại `data_deletion.py`,
   phát hiện: (a) `data_deletion_requests` (migration 013) **cố ý không lưu `psid`** — comment
   gốc trong migration: *"CO Y khong luu psid lau dai"* — nên không có nguồn 90-ngày nào để tra
   cứu structured; (b) **không cần luật này**: `_delete_customer_data()` xoá cứng toàn bộ
   `conversations` của khách ngay khi hoàn tất — khách đã xoá dữ liệu tự động biến mất khỏi tập
   `E` (eligible) ở Phase 1 vì không còn hội thoại nào để join. Giữ lại đúng 1 luật loại trừ có
   thật: Redis key `del_pending:{psid}` (đang chờ xác nhận, chưa xoá xong) — structured, O(1),
   không content scan.
3. **`customer_ref` đổi từ giả định "psid" sang `customers.id`:** psid bị chính
   `_delete_customer_data()` ghi đè thành `deleted:<code>` — nếu sample dùng psid làm khoá DSR,
   thứ tự thao tác sai có thể làm `WHERE customer_ref = $1` không khớp nữa. `customers.id` bất
   biến trong suốt vòng đời (kể cả sau khi ẩn danh), loại bỏ rủi ro thứ tự này hoàn toàn — không
   cần thêm ràng buộc "phải xoá sample TRƯỚC khi anonymize customer".

## Điều chưa làm (đúng phạm vi correction)

Chưa viết migration/hàm SQL/role DB/RBAC permission/collector job/prediction job thật — toàn bộ
vẫn là đặc tả `.md`. Sẽ có evidence riêng (test boundary, negative-permission, kill-latency,
concurrent-collector, matching-rule unit test) khi CA ra "Stage 0P Design Accepted".

## Đề nghị

CA review lại §4, §5 (đặc biệt §5.1/§5.2/§5.3 mới), §6, §9, §10 (mới) của gói v3.0.0 và ra quyết
định cho mục 1 §11.
