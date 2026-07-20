---
id: PA-002
title: Context Selection and Budget
domain: prompt_assembly
document_type: context_policy
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
priority: P1
dependencies:
  - PA-001
  - KG-001
---

# Purpose

Quy định cách lựa chọn, giới hạn và cắt giảm context để giữ tốc độ, chi phí và độ tập trung của model khi Knowledge Base tăng trưởng.

# Core Principle

> **Tài liệu có thể dài; runtime context phải nhỏ và đúng.**

# Budget Model

Không khóa số token tuyệt đối trong Knowledge Architecture vì model và giới hạn runtime có thể thay đổi. Dev cấu hình theo tỷ lệ:

```yaml
context_budget:
  runtime_policy: 0.15
  state_and_history: 0.20
  tool_results: 0.15
  knowledge_units: 0.30
  behavior_and_style: 0.10
  output_reserve: 0.10
```

Tỷ lệ là baseline, không phải công thức cứng. Tool result hoặc safety context có thể chiếm ưu tiên khi cần.

# Selection Order

1. Runtime policy và safety constraints bắt buộc.
2. User message hiện tại.
3. Tool result cần thiết.
4. Conversation state đã xác nhận.
5. Knowledge Unit trực tiếp trả lời intent.
6. Behavior Unit cho next action.
7. Voice/tone instructions tối thiểu.
8. Examples và related context nếu còn ngân sách.

# Retrieval Rules

- Retrieve theo Knowledge Unit/heading, không theo toàn file.
- Ưu tiên exact intent và verified fact.
- Dùng metadata filter: `status=approved`, domain, version, language.
- Loại chunk trùng hoặc diễn đạt lại cùng fact.
- Related Skill chỉ được mở rộng tối đa một bước trong MVP.
- Dừng retrieval khi top units đã trả lời đủ câu hỏi.

# History Compression

Giữ nguyên văn:

- Tin nhắn hiện tại.
- Các lượt gần nhất cần giải quyết tham chiếu.
- Tool result còn hiệu lực.

Tóm tắt có cấu trúc:

- Nhu cầu đã xác nhận.
- Sở thích vị/cách pha.
- Recommendation trước đó và lý do.
- Câu hỏi chưa giải quyết.

Không tóm tắt thành fact:

- Giả định chưa được khách xác nhận.
- Dữ liệu Tool đã stale.
- Nội dung nhạy cảm không cần thiết.

# Truncation Policy

Khi vượt ngân sách, cắt theo thứ tự:

1. Examples không bắt buộc.
2. Related Knowledge không trực tiếp trả lời.
3. History cũ đã được tóm tắt.
4. Style elaboration trùng lặp.
5. Secondary intent không cấp thiết.

Không được cắt:

- Safety rule liên quan.
- Tool result trực tiếp.
- Fact cần để trả lời.
- User request hiện tại.
- Output contract bắt buộc.

# Latency Guidelines

- Không rerank tập lớn khi exact routing đã đủ.
- Tool calls độc lập có thể chạy song song nếu runtime cho phép và không có dependency.
- Cache embedding/index; không cache dữ liệu động như tồn kho/giá ngoài TTL của Tool.
- Log số Knowledge Units và kích thước prompt để tối ưu sau vận hành thật.

# Things to Avoid

- Không dùng “file ngắn” như lý do để load tất cả.
- Không chèn cả FAQ và Product source khi hai phần lặp nguyên văn.
- Không giữ toàn bộ lịch sử hội thoại vô thời hạn.
- Không cắt Tool result nhưng giữ example.

# Success Criteria

- P95 context size nằm trong budget cấu hình.
- Chất lượng không giảm khi repository tăng số file.
- Có thể giải thích unit nào được chọn/bị loại.
- Phản hồi nhanh cho câu hỏi đơn giản mà không gọi pipeline quá mức.

# Related Documents

- PA-001 — Prompt Assembly Pipeline
- PA-003 — Source Ordering and Conflict Resolution
- RT-001 — Runtime Input Output Contract
