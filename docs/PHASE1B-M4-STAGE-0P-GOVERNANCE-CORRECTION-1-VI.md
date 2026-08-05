---
id: A3S-PHASE1B-M4-STAGE-0P-GOVERNANCE-CORRECTION-1-001
title: Alpha3S Phase I-B M4 — Stage 0P Governance Correction #1
document_type: governance_correction
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-29 09:10+07:00
answers_review: PHASE1B-M4-STAGE-0P-GOVERNANCE-REVIEW-1-VI.md (CA, CHANGES_REQUIRED, reviewed_head 241fa957)
corrected_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v2.0.0
language: vi-VN
---

# Stage 0P — Governance Correction #1

Đáp lại `PHASE1B-M4-STAGE-0P-GOVERNANCE-REVIEW-1-VI.md`. Đây là **correction của gói governance**
(đúng như CA ghi ở §4 review: "không tiêu thụ thêm submission triển khai M4 S0–S3"). **Không có
migration/sample collector/production access/flag nào được tạo hay bật** — toàn bộ vẫn là thiết
kế trên giấy, cập nhật trực tiếp vào `PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md` (nâng version
1.0.0 → 2.0.0).

## Xác nhận các mục CA đã chốt (§2 Review #1) — không cần sửa gì thêm

- Purpose code `P12_PII_DETECTOR_EVAL`: ACCEPTED tên/mục đích/data-class — giữ nguyên §2 gói.
- Ranh giới vendor: ACCEPTED có điều kiện — giữ nguyên §1 gói, đã nhấn mạnh lại điều kiện "không
  byte nào đi vendor path" ở §10.
- Reviewer + cơ sở pháp lý: CA ghi nhận quyết định PO, không đổi.
- Retention 45 ngày: ACCEPTED trần kỹ thuật có điều kiện — đã ghi rõ phụ thuộc F-M4-0P-04 ở §10/§6.

## Mapping 4 finding → sửa

| Finding | Yêu cầu CA | Đã sửa (gói v2.0.0) |
|---|---|---|
| **F-M4-0P-01** kill switch chưa bao phủ raw sample capture | Tách detector-shadow và raw-sample-capture; flag/control riêng cho capture, default OFF, missing=OFF; ngữ nghĩa kill rõ ràng; reviewer access revoke độc lập | §9: thêm `m4_stage0p_capture_enabled` (tách khỏi `m4_pii_shadow`), bảng ngữ nghĩa 2 công tắc, 3 điểm ngữ nghĩa kill tường minh (dừng-mới/không-xoá-cũ/thu-hồi-độc-lập) |
| **F-M4-0P-02** access matrix/audit chưa enforceable | Định danh role riêng (collector/reviewer-API/evaluator/purge); base table revoke direct access; reviewer chỉ qua audited interface enforceable; audit record tối thiểu; cấp/thu hồi credential, break-glass | §5: viết lại hoàn toàn — 4 role DB + column-level grant, REVOKE ALL FROM PUBLIC là bước đầu migration, con người không cầm credential DB (chỉ qua staff session + ops API), audit ghi TRƯỚC KHI trả dữ liệu (fail closed), RBAC permission có thời hạn + break-glass có văn bản |
| **F-M4-0P-03** sampling không có giới hạn trên xác định | Hard cap; ngưỡng + thuật toán chọn xác định trước, tái lập được; selection trước khi persist raw; dưới 200 vẫn dừng như cũ; counts loại trừ không PII | §4: hard cap 260, 2 pha tách bạch (metadata-only → chọn → mới đọc nội dung), seed cố định công khai `SHA256("m4-stage0p-v1")` thay cho "stratify" mơ hồ trước đó |
| **F-M4-0P-04** liên kết crypto/DSR chưa hoàn chỉnh | Domain tag/AAD riêng cho sample, không giả định tái dùng nguyên trạng slot crypto; binding metadata tối thiểu hoặc token; thứ tự/transaction DSR không orphan; 4 loại test | §6: `encrypt_sample_value`/`decrypt_sample_value` domain tag riêng `a3s-m4-shadow-sample-aad-v1`, AAD=(customer_ref, conversation_ref, **sample_id** thay slot_type — mỗi row AAD duy nhất), khoá riêng `m4_sample_key_b64`; giải trình vì sao giữ plaintext ref (không tokenize được vì cần để tính lại AAD) + bù đắp truy cập hạn chế. §7: DSR filter trực tiếp `customer_ref` không JOIN → không orphan, cùng transaction, idempotent tự nhiên, liệt kê đủ 4 test CA yêu cầu (cross-context, tamper, retry, xoá-khi-nguồn-đã-mất) |

## Điều chưa làm (đúng phạm vi correction, không lấn sang implementation)

- Chưa viết migration SQL thật, chưa viết `encrypt_sample_value`/role DB/RBAC permission/collector
  job — tất cả vẫn là đặc tả trong `.md`. Sẽ có evidence riêng (fresh/existing/idempotent, pytest
  adversarial, CI) khi CA ra "Stage 0P Design Accepted" và Dev mở submission kỹ thuật.
- Chưa động tới `PROCESSING-PURPOSE-REGISTRY.md`/`AI-USE-CASE-REGISTER.md`/`DSR-RUNBOOK-VI.md`
  thật (chỉ đề xuất nội dung trong gói) — đúng nguyên tắc không tự sửa tài sản chung ngoài gate.

## Đề nghị

CA review lại thiết kế đã sửa (§4, §5, §6, §7, §9 của gói v2.0.0, mapping đầy đủ ở §11 gói) và ra
quyết định cho mục 1 §10 ("Stage 0P Design Accepted" hoặc yêu cầu sửa thêm).
