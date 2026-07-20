---
id: PA-003
title: Source Ordering and Conflict Resolution
domain: prompt_assembly
document_type: source_policy
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
priority: P1
dependencies:
  - PA-001
  - TRACEABILITY
  - KG-003
---

# Purpose

Quy định nguồn nào được ưu tiên và cách runtime xử lý khi Tool, Knowledge, state hoặc model knowledge không nhất quán.

# Source Priority

```text
Applicable runtime/safety policy
  > Current verified Tool result
  > Approved canonical Brand/Product source
  > Approved behavior/playbook
  > Confirmed conversation state
  > Approved FAQ delivery guidance
  > General model knowledge
```

Human handoff không phải “nguồn fact” nhưng là route ưu tiên khi vượt quyền hoặc rủi ro.

# Conflict Types

## Tool vs Knowledge

Ví dụ giá/tồn kho khác tài liệu tĩnh: Tool thắng. Không trộn hai giá trị.

## Canonical source vs consumer

Brand/Product source thắng FAQ hoặc Sales consumer. Consumer phải được đánh dấu cần review.

## Approved vs draft

Approved thắng. Draft không được vào production context.

## Current state vs older state

Thông tin khách vừa xác nhận thắng summary cũ.

## Knowledge vs model knowledge

Knowledge đã approved thắng. Model không được “sửa” Brand/Product Fact bằng kiến thức chung.

# Conflict Resolution Algorithm

```text
1. Classify each source by type, status, version and timestamp.
2. Remove draft, superseded and expired sources.
3. Apply source priority.
4. If one authoritative value remains → use it.
5. If authoritative sources at same level conflict → do not guess.
6. Return safe uncertainty + trigger human/content review.
7. Log source IDs and conflict reason.
```

# Staleness Rules

- Tool result dùng TTL do capability định nghĩa.
- Conversation state hết hiệu lực khi khách sửa hoặc ngữ cảnh thay đổi.
- Approved Knowledge dùng version/status, không dùng thời gian như dữ liệu động.
- Derived fact stale khi input source thay đổi.

# Customer-Facing Behavior

Không nói:

> “Hai nguồn dữ liệu của hệ thống đang conflict.”

Nói:

> “Hiện em chưa xác nhận được thông tin này. Em sẽ chuyển người phụ trách kiểm tra giúp anh/chị.”

Nếu Tool tạm lỗi, nói rõ chưa kiểm tra được hiện tại; không dùng dữ liệu cũ để đoán.

# Logging Requirements

```yaml
source_resolution:
  selected_source_ids: []
  rejected_source_ids: []
  conflict_detected: false
  conflict_type: null
  fallback_action: null
```

# Things to Avoid

- Không lấy majority vote giữa nhiều nguồn lặp.
- Không coi FAQ là canonical Product source.
- Không âm thầm dùng dữ liệu stale.
- Không để model tự chọn nguồn chỉ dựa trên cách viết tự tin hơn.
- Không tiết lộ raw internal conflict cho khách.

# Success Criteria

- Mọi fact customer-facing truy được về source đã chọn.
- Không có dữ liệu động được trả từ Knowledge tĩnh khi Tool bắt buộc.
- Conflict ngang cấp tạo review/handoff thay vì hallucination.

# Related Documents

- PA-001 — Prompt Assembly Pipeline
- PA-002 — Context Selection and Budget
- KG-003 — Impact Analysis Rules
- TRACEABILITY.md
