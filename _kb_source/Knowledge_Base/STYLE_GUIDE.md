---
id: ALPHA3S-STYLE-GUIDE
title: Knowledge Style Guide
document_type: standard
owner: Alpha3S
version: 2.0.0
status: approved
approved_by: PO
last_review: 2026-07-20
review_after: 2027-01-20
last_updated: 2026-07-20
---

# Knowledge Style Guide

## Language Standard

> **Structure in English. Knowledge in Vietnamese.**

- Metadata, field names, enum và IDs: English.
- Business Knowledge, explanations và examples: Vietnamese.
- Thuật ngữ chuyên môn English có thể giữ nguyên, kèm giải thích khi cần.

## Document Rules

- Một document có một responsibility rõ ràng.
- Một Knowledge Unit tập trung một intent/fact/decision.
- Metadata bắt buộc: `id`, `title`, `domain`, `version`, `status`, `owner`.
- Production chỉ dùng `approved` assets.
- Heading có ý nghĩa, hỗ trợ chunking; không dùng heading trang trí.
- Không nhúng dữ liệu động vào Knowledge.

## Writing Rules

- Trả lời đúng và rõ trước khi giàu hình ảnh.
- Câu và đoạn ngắn.
- Dùng từ phổ thông; giải thích jargon.
- Không marketing quá mức.
- Không claim tuyệt đối khi trải nghiệm phụ thuộc khẩu vị.
- Phân biệt Fact, Observation và Recommendation.

## Product Knowledge Pattern

1. Definition — sản phẩm là gì.
2. Customer value — vì sao khách cần quan tâm.
3. Background — hoạt động thế nào, nếu cần.
4. Misconceptions — hiểu lầm thường gặp.
5. Things to Avoid.
6. Brand Alignment.
7. Sources/Related assets.

## FAQ Pattern

```text
FAQ ID + customer intent
  → Customer variants
  → Answer guidance
  → Next best action, if useful
  → Source / Tool / Escalation
```

FAQ là Delivery Layer, không phải canonical fact source.

## Units and Numbers

- Ưu tiên đơn vị khách dùng, kèm đơn vị chuẩn ở lần đầu.
- Ví dụ: `1 muỗng (khoảng 1 g)`.
- Giữ dấu thập phân và đơn vị nhất quán.
- Derived calculations phải ghi giả định và source inputs.

## Voice Constraints

- Tự nhiên, rõ, trung thực, hữu ích và tôn trọng.
- Không mở đầu mọi câu bằng “Dạ”.
- Không dùng “tốt nhất”, “số 1”, “thần thánh”.
- Không dùng emoji trong khiếu nại hoặc vấn đề sức khỏe.

## Prohibited Content

- Giá/tồn kho/khuyến mãi tĩnh.
- Chứng nhận hoặc chính sách chưa xác thực.
- Tỷ lệ phối trộn chưa công bố.
- Claim chữa bệnh, giảm cân, tăng testosterone.
- So sánh hạ thấp đối thủ.

## Review Checklist

- [ ] Responsibility rõ ràng.
- [ ] Metadata đầy đủ.
- [ ] Fact truy được về canonical source.
- [ ] Không có dynamic data.
- [ ] Không trùng hoặc mâu thuẫn asset khác.
- [ ] Có escalation khi cần.
- [ ] Có traceability/dependencies.
- [ ] Có test impact nếu thay đổi P1.
