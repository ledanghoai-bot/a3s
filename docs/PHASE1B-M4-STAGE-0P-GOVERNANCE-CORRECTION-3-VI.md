---
id: A3S-PHASE1B-M4-STAGE-0P-GOVERNANCE-CORRECTION-3-001
title: Alpha3S Phase I-B M4 — Stage 0P Governance Correction #3
document_type: governance_correction
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-29 15:18+07:00
answers_review: PHASE1B-M4-STAGE-0P-GOVERNANCE-REVIEW-3-VI.md (CA, CHANGES_REQUIRED, reviewed_head ff1233a8)
corrected_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Governance Correction #3

Đáp lại `PHASE1B-M4-STAGE-0P-GOVERNANCE-REVIEW-3-VI.md`. Vẫn thuần **correction governance** —
không migration/role/production access/capture/flag/merge/deploy nào được tạo hay bật.

## Trạng thái giữ nguyên (không sửa)

- **F-M4-0P-04: CLOSED** — giữ nguyên qua cả 3 vòng review, không đụng.

## Mapping 4 mục CA yêu cầu (`01B/02B/03B/05A`) → sửa

| Mục | Yêu cầu CA | Đã sửa (gói v4.0.0) |
|---|---|---|
| **F-M4-0P-01B** control source chưa dynamic | Định nghĩa dynamic control source strongly-consistent hoặc cancel/restart có stop contract đo được; fail-to-read = OFF; chống stale cache; ghi rõ TTL/max latency thực không phải ước lượng | §9: control chuyển từ `settings` (static, nạp 1 lần lúc process start — lý do CA chỉ đúng: process đang chạy không thấy thay đổi) sang **1 row bảng `m4_stage0p_control`**, đọc tươi bằng `SELECT` trước mỗi INSERT (Postgres READ COMMITTED = strongly-consistent theo mỗi câu query mới); `statement_timeout='2s'` trên câu đọc + đọc lỗi/timeout coi là OFF; max stop latency = 2s (cơ chế thật, không phải "mili-giây" suông) + thời gian 1 INSERT dở; evidence methodology: UPDATE control từ session khác giữa lúc job chạy, chứng minh không row nào có `captured_at` sau boundary |
| **F-M4-0P-02B** interface đặc quyền chưa hoàn thiện + pending-DSR lookup hở | Khoá search_path, schema-qualify, owner non-superuser, revoke EXECUTE FROM PUBLIC, validate batch status/window/purpose, audit fail-closed; interface chỉ trả eligibility boolean không trao PSID; xử lý race check-vs-persist, DSR phải thắng | §5.2: đủ 5 mục hardening `SECURITY DEFINER` chuẩn Postgres (search_path khoá trong CREATE FUNCTION, object schema-qualify, owner=`alpha3s` non-superuser đã xác nhận qua 038, REVOKE EXECUTE FROM PUBLIC tường minh rồi GRANT riêng, validate `status='locked'`+window+purpose trước khi trả row, audit trong CÙNG statement fail-closed); §5.3 mới: `is_pending_deletion(customer_id) -> bool`, PSID chỉ tồn tại trong scope hàm, không log/trả/audit; re-check lại ngay trước mỗi persist (race); DSR §7 là thẩm quyền cuối vô điều kiện |
| **F-M4-0P-03B** cap byte sai (character≠byte) + eligibility hở | Đặt tên rõ character cap/byte cap, tính worst-case theo ciphertext thực; truncation UTF-8-safe trước persist + enforce lại ở DB boundary; eligibility buộc conversation trong cửa sổ + liên hệ order thật, không kéo hội thoại cũ/không liên quan; test multi-byte/oversized/old/unrelated | §4: tách rõ `MAX_CHARS=2000` (cắt bước 1) và `MAX_BYTES=8000` (constraint chính, cắt bước 2 trên bytes đã encode, UTF-8-safe cả 2 bước); Cap D thật = 260×20×8000 = **41.6MB** (gấp ~4 lần con số 10.4MB sai ở v3 — CA phát hiện đúng); DB `CHECK (octet_length(encrypted_message) <= 8045)` enforce lại ở tầng DB; eligibility thêm điều kiện `conversations.created_at` PHẢI trong cùng cửa sổ 14 ngày (không chỉ qua `orders`) — chặn kéo hội thoại cũ/không liên quan của cùng khách |
| **F-M4-0P-05A** count-only không đủ, cần giữ span | Ground truth + prediction giữ start/end trên canonical text cùng normalization/version; định nghĩa exact-span + overlap/IoU, gate dùng exact hoặc ngưỡng CA/PO duyệt, count-only chỉ phụ; test offset bounds/non-overlap/normalization/truncated; reviewer vẫn không thấy prediction trước; lưu detector version/normalization version/evaluation hash | §6: thêm `start/end` vào `labeled_slots`/`predicted_slots`, thêm `normalization_version`, `canonical_text_len`; §10 viết lại hoàn toàn: **exact-span là gate chính**, overlap/IoU là metric phụ (ngưỡng cần PO/CA duyệt riêng, Dev không tự chọn), count-only hạ xuống tham khảo; non-overlap policy, offset-bounds validation, normalization-version mapping, evaluation hash `(detector_version, normalization_version, evaluation_batch)`; §5.4 giữ nguyên thứ tự chống thiên lệch (không đổi) |

## Vì sao rút count-only — không phải chi tiết, là lỗi phương pháp thật

CA nêu ví dụ chính xác: tin nhắn có 2 số điện thoại, detector bắt trùng số #1 hai lần (bỏ sót số
#2) — count-only báo `2 khớp 2` = TP giả. Phương pháp S0 (`m4_pii_shadow_test.py`) đúng cho mục
đích của nó (smoke test synthetic, Dev kiểm soát cả corpus lẫn kỳ vọng, không có khái niệm "detector
bắt sai vị trí nhưng đúng số lượng" vì mỗi case chỉ thiết kế 1 giá trị/slot) — nhưng **không phải
acceptance methodology cho sample thật** nơi 1 message có thể có nhiều instance cùng slot_type ở
vị trí khác nhau. Đã sửa theo đúng hướng CA chỉ, không tranh luận lại.

## Vì sao offset an toàn để lưu (khác quyết định S0)

CA xác nhận "offset không phải plaintext PII". `PIISpan.as_safe_dict()` (S0) vẫn giữ nguyên
không đổi — nó phục vụ **log live-traffic phát liên tục ra stdout**, bối cảnh rủi ro khác hẳn
(tối giản triệt để là đúng ở đó). Cột `labeled_slots`/`predicted_slots` của Stage 0P là **jsonb
trong DB restricted-access, RBAC + audit chặt** (§5) — offset ở đây an toàn và **cần thiết** để
đo đúng theo đúng yêu cầu CA. Không sửa/không đụng code S0.

## Điều chưa làm (đúng phạm vi correction)

Chưa viết SQL/function/role/RBAC/job thật — toàn bộ vẫn `.md`. Evidence (boundary test cho kill
switch, negative-permission, multi-byte/oversized/old/unrelated conversation, offset-bounds/
non-overlap/normalization test) sẽ đi cùng submission kỹ thuật khi CA ra "Stage 0P Design
Accepted".

## Đề nghị

CA review lại §4, §5.2/§5.3 (mới), §6, §9, §10 của gói v4.0.0 và ra quyết định cho mục 1 §11.
