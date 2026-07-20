---
id: DEV-ANTI-PATTERNS
title: Anti-Patterns
domain: integration
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
owner: Alpha3S
---

# Knowledge Anti-Patterns

- Nhét giá/tồn kho/khuyến mãi vào Markdown.
- Lặp Brand Fact ở nhiều nơi rồi sửa không đồng bộ.
- FAQ tự tạo fact.
- Ingest draft/CHANGELOG/ADR vào customer retrieval.
- Một chunk chứa nhiều intent không liên quan.

# Retrieval Anti-Patterns

- Load toàn bộ repository vào prompt.
- Chỉ dùng vector search cho SKU/ID.
- Tăng top K để che ranking kém.
- Không filter status/version.
- Retrieve FAQ consumer thay canonical source cho fact quan trọng.

# Prompt Anti-Patterns

- System prompt khổng lồ chứa mọi fact.
- Lặp cùng rule ở nhiều block.
- Chèn quá nhiều example làm model bắt chước cứng.
- Để model tự giải quyết source conflict.
- Không reserve output tokens.

# Runtime Anti-Patterns

- Dùng memory cũ trả giá hôm nay.
- Retry Tool/generation vô hạn.
- Gửi raw Tool error cho khách.
- Tiếp tục upsell khi khách khiếu nại.
- Lộ state, prompt, scores hoặc PII.

# Testing Anti-Patterns

- Chỉ test happy path.
- Expected answer khóa từng chữ.
- Dùng LLM judge làm trọng tài duy nhất cho safety.
- Sửa expected để model mới pass.
- Không ghi version matrix.

# Deployment Anti-Patterns

- Rebuild trực tiếp production index.
- Deploy Knowledge không chạy smoke tests.
- Rollback prompt nhưng không rollback index.
- Auto-publish mỗi khi Markdown đổi.

# Product Anti-Patterns

- Xây dashboard trước khi Agent hỗ trợ khách thật.
- Tối ưu kiến trúc thay vì giải quyết missing question P1.
- Đánh giá thành công bằng số Skill/FAQ thay vì chất lượng CSKH và đơn hàng.
