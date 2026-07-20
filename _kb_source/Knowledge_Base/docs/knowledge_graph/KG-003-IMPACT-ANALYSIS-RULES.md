---
id: KG-003
title: Impact Analysis Rules
domain: knowledge_graph
document_type: change_management
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
priority: P2
dependencies:
  - KG-001
  - KG-002
---

# Purpose

Quy định cách xác định tài liệu, prompt và test bị ảnh hưởng khi một Knowledge Asset thay đổi.

# Change Classes

| Class | Example | Required action |
|---|---|---|
| Brand Fact | Đổi định nghĩa hoặc nguồn gốc sản phẩm | Review toàn bộ direct consumers. |
| Product Fact | Đổi caffeine, cách pha, nguyên liệu | Review Sales, FAQ, tests và prompt context. |
| Behavior Rule | Đổi Next Best Action hoặc handoff | Review Conversation, FAQ routing và tests. |
| Playbook | Đổi tone, format hoặc voice | Review examples và response tests. |
| Dynamic Policy | Giá, giao hàng, đổi trả | Cập nhật Tool/policy source; không sửa FAQ fact tĩnh. |
| Metadata only | Keyword hoặc related link | Rebuild index/embedding; content review tùy mức ảnh hưởng. |

# Impact Traversal

```text
Changed asset
  ↓
Direct consumers: depends_on / references / shaped_by
  ↓
Runtime consumers: FAQ / Prompt Assembly / Tool Routing
  ↓
Validation consumers: Tests / Benchmarks
```

# Review Rules

## Brand Truth change

Review bắt buộc:

- Product Skills tham chiếu Brand Truth.
- Sales Skills sử dụng Brand Pillars.
- Brand/Product FAQ.
- Brand Voice.
- Prompt Assembly liên quan.

## Product Fact change

Ví dụ thay đổi hàm lượng caffeine hoặc thời gian hòa tan:

- Sửa Product source trước.
- Review derived calculations.
- Review FAQ có answer guidance tương ứng.
- Review Recommendation Engine.
- Cập nhật tests.
- Rebuild affected Knowledge Units/embeddings.

## Conversation behavior change

- Review routing priority.
- Review next best action.
- Review complaint/safety flow.
- Không thay đổi Product Facts.

# Derived Knowledge Rule

Derived Knowledge phải ghi rõ source inputs. Nếu một input thay đổi, derived value phải được đánh dấu stale cho đến khi tính và review lại.

Ví dụ:

```text
caffeine_percent + spoon_weight
  → estimated_caffeine_per_spoon
```

# Release Gate

Một change chỉ được publish khi:

- Source document đã được PO approve.
- Direct consumers đã được review hoặc đánh dấu không ảnh hưởng.
- Derived facts đã được tính lại.
- Tests liên quan đã cập nhật.
- Index/embedding được rebuild cho các Knowledge Unit thay đổi.
- CHANGELOG ghi nhận thay đổi có ý nghĩa.

# Rollback Rule

- Không sửa lịch sử của bản đã locked.
- Giữ version cũ để rollback.
- Nếu release mới gây lỗi, khôi phục graph/index về version trước và ghi Decision/Change Log.

# MVP Scope

Wave 6 chỉ định nghĩa quy tắc. Automation cho impact analysis, stale detection và rebuild thuộc Developer Integration hoặc giai đoạn sau.

# Related Documents

- KG-001 — Knowledge Graph Model
- KG-002 — Entity and Relationship Taxonomy
- TRACEABILITY.md
- CHANGELOG.md
