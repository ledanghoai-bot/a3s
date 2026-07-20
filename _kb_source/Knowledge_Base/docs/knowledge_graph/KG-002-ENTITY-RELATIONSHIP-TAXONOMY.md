---
id: KG-002
title: Entity and Relationship Taxonomy
domain: knowledge_graph
document_type: taxonomy
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
priority: P2
dependencies:
  - KG-001
---

# Purpose

Chuẩn hóa tên entity và relationship để CA, Dev và QA dùng cùng một ngôn ngữ khi liên kết Knowledge Assets.

# Entity Rules

- Mỗi entity có một ID duy nhất và ổn định.
- Tên file có thể thay đổi; ID không đổi trừ khi entity bị thay thế hoàn toàn.
- Entity `approved` chỉ liên kết tới nguồn đã được PO phê duyệt.
- File draft không được trở thành nguồn production mặc định.

# Relationship Types

| Relationship | Direction | Meaning |
|---|---|---|
| `depends_on` | child → source | Asset cần source để hoạt động đúng. |
| `references` | consumer → source | Asset trích dẫn hoặc sử dụng nội dung source. |
| `governed_by` | asset → ADR/policy | Asset tuân theo quyết định/chuẩn. |
| `supports` | source → consumer | Source cung cấp cơ sở cho asset khác. |
| `routes_to` | FAQ/conversation → Tool/Human | Chuyển xử lý sang capability khác. |
| `shaped_by` | response/skill → Playbook | Cách diễn đạt chịu điều chỉnh bởi playbook. |
| `validated_by` | asset → Test | Asset có test tương ứng. |
| `supersedes` | new → old | Tài liệu mới thay thế tài liệu cũ. |
| `related_to` | asset ↔ asset | Liên quan tham khảo, không tạo dependency bắt buộc. |

# Relationship Constraints

## Brand Truth

- Có thể `support` Product, Sales và FAQ.
- Không `depend_on` FAQ.
- Thay đổi Brand Truth phải kích hoạt review các consumer trực tiếp.

## Product Knowledge

- `depends_on` Brand Truth khi có nội dung thương hiệu.
- Có thể `support` Sales và FAQ.
- Không lấy FAQ làm nguồn fact.

## FAQ

- Phải `reference` ít nhất một nguồn Knowledge hoặc `route_to` Tool/Human.
- Không được trở thành nguồn ngược cho Product Fact.

## Conversation Skill

- Có thể `route_to` Knowledge, Tool hoặc Human.
- Có thể `shaped_by` Playbooks.
- Không sở hữu Product Fact.

## Tool

- Là source cho dữ liệu động.
- Không bị Knowledge tĩnh ghi đè.

# Edge Schema

```yaml
from: SKL-FAQ-003
relationship: references
to: SKL-PRD-004
required: true
reason: Brewing answers use verified brewing facts.
```

# Example Graph

```text
ADR-PRD-003
  └─ governs → SKL-PRD-003

SKL-BRAND-001
  └─ supports → SKL-PRD-001

SKL-PRD-004
  ├─ supports → SKL-SAL-004
  └─ supports → SKL-FAQ-003

SKL-CON-001
  ├─ routes_to → TOOL-PRICING
  └─ shaped_by → PBK-RESPONSE-STANDARD
```

# Naming Conventions

```text
Knowledge Unit: KU-{DOMAIN}-{PARENT_NUMBER}-{UNIT_NUMBER}
Test Case:      TST-{DOMAIN}-{NUMBER}
Tool:           TOOL-{CAPABILITY}
Human route:    HUMAN-{TEAM_OR_FUNCTION}
```

# Things to Avoid

- Không dùng `related_to` thay cho dependency bắt buộc.
- Không tạo hai ID cho cùng một entity.
- Không liên kết draft vào production graph nếu chưa có cờ rõ ràng.
- Không dùng quan hệ graph để hợp thức hóa suy luận chưa được phê duyệt.

# Related Documents

- KG-001 — Knowledge Graph Model
- KG-003 — Impact Analysis Rules
- TRACEABILITY.md
