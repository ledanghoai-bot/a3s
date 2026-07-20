---
id: EV-005
title: Continuous Learning Loop
domain: evaluation
document_type: operating_process
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
priority: P2
dependencies:
  - EV-001
  - EV-002
  - KG-003
  - CHANGELOG
---

# Purpose

Định nghĩa quy trình biến câu hỏi và lỗi thực tế thành Knowledge/Test cải tiến mà không cho model tự sửa production Knowledge.

# Learning Loop

```text
Real conversation
  ↓
Detect failure or missing coverage
  ↓
Sanitize PII
  ↓
Classify root cause
  ↓
Create test case first
  ↓
Propose source/behavior/tool change
  ↓
CA review
  ↓
PO approve
  ↓
Rebuild affected assets
  ↓
Run smoke + regression
  ↓
Release and monitor
```

# Feedback Sources

- Khách hỏi nhưng không có answer source.
- Human handoff lặp lại cùng một vấn đề.
- Tool routing sai.
- Retrieval lấy source không liên quan.
- Câu trả lời đúng nhưng khách không hiểu.
- Complaint/safety issue.
- PO, CSKH hoặc Sales staff phản hồi.

# Root Cause Classes

| Code | Root cause | Primary owner |
|---|---|---|
| `KB_MISSING` | Thiếu fact/Knowledge | Knowledge team / PO |
| `KB_WRONG` | Fact sai hoặc stale | PO + source owner |
| `RETRIEVAL_MISS` | Source có nhưng không lấy được | Dev/RAG |
| `ROUTING_ERROR` | Sai Tool/Knowledge/Human route | Orchestrator |
| `ASSEMBLY_ERROR` | Đúng source nhưng context sai | Prompt runtime |
| `GENERATION_ERROR` | Model không tuân context | Prompt/guardrail/model |
| `TOOL_ERROR` | Capability lỗi/thiếu dữ liệu | Tool owner |
| `UX_ERROR` | Dài, máy móc, khó hiểu | Conversation/Playbook |

# Promotion Rules

Một conversation chỉ được đưa thành Knowledge/Test khi:

- Đã loại hoặc ẩn PII.
- Xác định được intent và expected behavior.
- Fact mới có source xác thực.
- Không sao chép nguyên nội dung khách nếu không cần.
- Có owner và priority.

# Approval Boundary

AI có thể:

- Phát hiện pattern.
- Đề xuất FAQ/test draft.
- Gợi ý root cause.

AI không được:

- Tự approve Brand/Product Fact.
- Tự sửa production Knowledge.
- Tự publish regression expectation.
- Tự hạ severity để release pass.

# Review Cadence

MVP:

- Sau mỗi lỗi S0/S1: review ngay.
- Hàng tuần trong giai đoạn 10 đơn đầu tiên: xem missing questions và handoffs.
- Trước mỗi release: chạy smoke/regression.
- Hàng tháng khi hệ thống ổn định: review stale facts và coverage.

# Prioritization

Ưu tiên theo:

1. Safety và quyền riêng tư.
2. Câu hỏi cản trở đặt hàng/hỗ trợ đơn.
3. Câu hỏi xuất hiện nhiều.
4. Lỗi làm mất niềm tin hoặc tạo handoff không cần thiết.
5. Nice-to-have content.

# Minimal Feedback Record

```yaml
id: FB-2026-0001
observed_at: ISO-8601
sanitized_query: string
root_cause: RETRIEVAL_MISS
severity: S2
affected_assets: []
proposed_test_id: TST-...
owner: string
status: open | reviewed | fixed | verified
```

# Success Criteria

- Mỗi lỗi nghiêm trọng có regression test.
- Knowledge thay đổi có source và approval.
- Số handoff do thiếu Knowledge P1 giảm theo thời gian.
- Continuous learning không biến thành auto-training không kiểm soát.

# Things to Avoid

- Không ingest toàn bộ chat thô vào Knowledge Base.
- Không tối ưu cho một câu hỏi hiếm làm hỏng behavior phổ biến.
- Không sửa prompt khi root cause là Tool hoặc source fact.
- Không đo thành công chỉ bằng số FAQ mới.

# Related Documents

- EV-001 — Evaluation Framework
- EV-002 — Test Case Schema
- KG-003 — Impact Analysis Rules
- CHANGELOG.md
