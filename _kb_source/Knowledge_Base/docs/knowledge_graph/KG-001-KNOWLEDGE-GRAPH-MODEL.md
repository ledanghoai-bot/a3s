---
id: KG-001
title: Knowledge Graph Model
domain: knowledge_graph
document_type: model
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
priority: P2
---

# Purpose

Định nghĩa mô hình liên kết tối thiểu giữa Brand Truth, Knowledge, Skills, Playbooks, FAQ, Tools và Test Cases. Mục tiêu là traceability và impact analysis; chưa yêu cầu triển khai graph database.

# Design Principle

> Markdown là đơn vị quản trị; Knowledge Unit là đơn vị retrieval; relationship là đơn vị traceability.

# Node Types

| Node type | Prefix | Responsibility |
|---|---|---|
| Brand Truth | `SKL-BRAND` | Nguồn fact thương hiệu được phê duyệt. |
| Product Skill | `SKL-PRD` | Fact và trải nghiệm sản phẩm. |
| Customer Service Skill | `SKL-CS` | Hành vi tiếp nhận và khám phá nhu cầu. |
| Sales Skill | `SKL-SAL` | Logic tư vấn và recommendation. |
| Conversation Skill | `SKL-CON` | Orchestration, state và next action. |
| Playbook | `PBK` | Voice, response format và tone. |
| FAQ Skill | `SKL-FAQ` | Delivery mapping từ câu hỏi tới nguồn. |
| Tool | `TOOL` | Dữ liệu động và hành động bên ngoài. |
| ADR | `ADR` | Quyết định kiến trúc. |
| Test Case | `TST` | Kiểm tra retrieval và behavior. |
| Knowledge Unit | `KU` | Section/chunk được ingest và retrieve. |

# Canonical Flow

```text
ADR
  └─ governs → Brand / Product / Sales / Conversation / FAQ

Brand Truth
  └─ supports → Product Knowledge

Product Knowledge
  └─ supports → Sales Recommendation

Sales Knowledge
  └─ supports → Conversation Decision

Conversation + Playbook
  └─ shapes → FAQ Delivery / Runtime Response

FAQ
  ├─ references → Knowledge
  └─ routes_to → Tool / Human

Tests
  └─ validates → Knowledge Unit / Skill / Routing
```

# Minimal Node Schema

```yaml
id: SKL-PRD-003
type: product_skill
title: Taste Experience
version: 1.0.0
status: approved
domain: product
owner: Alpha3S
source_file: skills/product/SKL-PRD-003.md
dependencies:
  - SKL-BRAND-001
governed_by:
  - ADR-PRD-003
```

# Knowledge Unit Schema

```yaml
id: KU-PRD-004-003
parent_id: SKL-PRD-004
heading: Cold Brewing
domain: product
intent:
  - cold_brewing
keywords:
  - pha lạnh
  - nước nguội
  - hòa tan
source_version: 1.0.0
status: approved
```

# Runtime Boundary

Knowledge Graph hỗ trợ:

- Tìm dependencies.
- Xác định nguồn fact.
- Phân tích ảnh hưởng khi file thay đổi.
- Mở rộng retrieval bằng related assets.
- Liên kết test với Knowledge Unit.

Knowledge Graph không được:

- Tự tạo fact mới.
- Thay thế Tool cho dữ liệu động.
- Tự suy ra approval.
- Tự quyết định nội dung customer-facing khi chưa qua Conversation/Playbook.

# MVP Implementation

Trong giai đoạn hiện tại, graph có thể được biểu diễn bằng:

- Front matter trong Markdown.
- `TRACEABILITY.md` cho quan hệ quan trọng.
- Script build index ở giai đoạn Dev integration.

Không cần Neo4j, graph database hoặc dịch vụ mới để đạt mục tiêu Wave 6.

# Success Criteria

- Mỗi tài liệu có ID duy nhất.
- Có thể truy từ FAQ về nguồn fact.
- Có thể xác định file bị ảnh hưởng khi Brand/Product Fact thay đổi.
- Quan hệ không mâu thuẫn với Source Priority.

# Related Documents

- KG-002 — Entity and Relationship Taxonomy
- KG-003 — Impact Analysis Rules
- TRACEABILITY.md
