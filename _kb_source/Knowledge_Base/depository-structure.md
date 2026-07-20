---
id: ALPHA3S-DEPOSITORY-STRUCTURE
title: Alpha3S Knowledge Base Depository Structure
document_type: repository_map
owner: Alpha3S
version: 3.3.1
status: approved
approved_by: PO
last_review: 2026-07-20
review_after: 2027-01-20
last_updated: 2026-07-20
---

# Alpha3S Knowledge Base — Depository Structure

## Canonical Path Contract

- Thư mục Skill chính thức là `skills/` (số nhiều).
- Tất cả FAQ Skill nằm tại `skills/faq/`.
- `skill/` và `docs/faq/` không phải đường dẫn hợp lệ.
- Gói release phải giữ nguyên cây thư mục canonical; không được đổi tên hoặc di chuyển asset khi nén.
- Ingestion phải fail validation nếu phát hiện Skill nằm ngoài `skills/`.

## Purpose

Đây là bản đồ chính thức để Product Owner theo dõi cấu trúc, trạng thái và vị trí của toàn bộ tài sản Knowledge thuộc Alpha3S.

Mission:

> **CSKH và tư vấn như người thật — Không giờ nghỉ — Hoạt động siêu tốc.**

Business North Star trước mắt:

> **Hỗ trợ bán những đơn cà phê 3S Coffee đầu tiên.**

## Working Agreement

```text
CA xác định phạm vi
  ↓
CA biên soạn tài liệu
  ↓
CA xuất thành file .md độc lập
  ↓
PO review
  ├─ Approve → CA compile thành approved v1.0.0 và khóa Wave
  └─ Amend   → CA chỉnh sửa, tái xuất file và gửi review lại
```

### Delivery Rules

- Không preview toàn bộ tài liệu trong chat nếu PO không yêu cầu.
- Mỗi deliverable được xuất thành một file `.md` độc lập.
- Metadata, field names và enum dùng English.
- Nội dung nghiệp vụ và ví dụ hội thoại dùng Vietnamese.
- Structure in English; Knowledge in Vietnamese.
- Không tự tạo Brand Fact, Product Fact, giá, chính sách, chứng nhận hoặc công thức.
- Dữ liệu thay đổi theo thời gian hoặc theo khách hàng phải lấy từ Tool.
- PO phê duyệt nội dung; CA chịu trách nhiệm kiến trúc, tính nhất quán và publication.

## Status Convention

| Status | Meaning |
|---|---|
| `approved` | PO đã duyệt nội dung. |
| `locked` | Baseline chính thức; thay đổi cần PO phê duyệt. |
| `draft` | CA đã xuất file và đang chờ PO review. |
| `amend` | PO yêu cầu chỉnh sửa. |
| `planned` | Đã nằm trong roadmap nhưng chưa biên soạn. |
| `backlog` | Chưa cần cho mục tiêu vận hành hiện tại. |
| `unverified` | Được duyệt trong lịch sử nhưng file chưa có trong workspace hiện tại. |

## Canonical Repository Layout

```text
alpha3s-knowledge-base/
│
├── README.md
├── FOUNDATION.md
├── STYLE_GUIDE.md
├── CONTRIBUTING.md
├── CHANGELOG.md
├── ARCHITECTURE.md
├── taxonomy.yaml
│
├── docs/
│   ├── adr/)
│   │   ├── ADR-INDEX.md
│   │   ├── ADR-TEMPLATE.md
│   │   ├── ADR-PRD-001.md
│   │   ├── ADR-PRD-002.md
│   │   └── ADR-PRD-003.md
│   │
│   ├── governance/
│   │   └── ROADMAP.md
│   │
│   ├── templates/
│   │   ├── SKL-TEMPLATE.md
│   │   └── FAQ-TEMPLATE.md
│   │
│   ├── knowledge_graph/               # Wave 6
│   │   ├── KG-001-KNOWLEDGE-GRAPH-MODEL.md
│   │   ├── KG-002-ENTITY-RELATIONSHIP-TAXONOMY.md
│   │   ├── KG-003-IMPACT-ANALYSIS-RULES.md
│   │   └── TRACEABILITY.md
│   │
│   ├── prompt_assembly/               # Wave 7
│   │   ├── PA-001-PROMPT-ASSEMBLY-PIPELINE.md
│   │   ├── PA-002-CONTEXT-SELECTION-AND-BUDGET.md
│   │   └── PA-003-SOURCE-ORDERING-AND-CONFLICT-RESOLUTION.md
│   │
│   ├── runtime/                       # Wave 7
│   │   ├── RT-001-RUNTIME-INPUT-OUTPUT-CONTRACT.md
│   │   └── RT-002-RUNTIME-GUARDRAILS-AND-FALLBACKS.md
│   │
│   ├── evaluation/                    # Wave 8
│   │   ├── EV-001-EVALUATION-FRAMEWORK.md
│   │   ├── EV-002-TEST-CASE-SCHEMA.md
│   │   ├── EV-003-RETRIEVAL-AND-ROUTING-EVALUATION.md
│   │   ├── EV-004-RESPONSE-QUALITY-AND-SAFETY-EVALUATION.md
│   │   └── EV-005-CONTINUOUS-LEARNING-LOOP.md
│   │
│   └── integration/                    # Final deliverables for Dev
│       ├── DEVELOPER_GUIDE.md
│       ├── INGESTION_GUIDE.md
│       ├── RAG_PIPELINE.md
│       ├── API_CONTRACT.md
│       ├── TESTING_GUIDE.md
│       ├── DEPLOYMENT_GUIDE.md
│       ├── REFERENCE_IMPLEMENTATION.md
│       ├── BEST_PRACTICES.md
│       └── ANTI_PATTERNS.md
│
├── implementation/                    # Post-Knowledge Base V1
│   ├── IMPLEMENTATION_PLAN.md
│   ├── DEV_HANDOFF_CHECKLIST.md
│   └── MVP_RELEASE_CHECKLIST.md
│
├── skills/
│   ├── brand/
│   │   └── SKL-BRAND-001.md
│   │
│   ├── customer_service/
│   │   ├── SKL-CS-001.md
│   │   ├── SKL-CS-002.md
│   │   └── SKL-CS-003.md
│   │
│   ├── product/
│   │   ├── SKL-PRD-001.md
│   │   ├── SKL-PRD-002.md
│   │   ├── SKL-PRD-003.md
│   │   └── SKL-PRD-004.md
│   │
│   ├── sales/
│   │   ├── SKL-SAL-001.md
│   │   ├── SKL-SAL-002.md
│   │   ├── SKL-SAL-003.md
│   │   ├── SKL-SAL-004.md
│   │   └── SKL-SAL-005.md
│   │
│   ├── conversation/                  # Wave 4 — Conversation Engine
│   │   ├── SKL-CON-001.md
│   │   ├── SKL-CON-002.md
│   │   └── SKL-CON-003.md
│   │
│   ├── faq/                           # Wave 5 — Delivery Layer
│   │   ├── SKL-FAQ-001.md
│   │   ├── SKL-FAQ-002.md
│   │   ├── SKL-FAQ-003.md
│   │   ├── SKL-FAQ-004.md
│   │   └── SKL-FAQ-005.md
│   │
│   ├── ordering/
│   ├── after_sales/
│   ├── health/
│   ├── caffeine/
│   ├── storage/
│   ├── sports/
│   ├── comparisons/
│   ├── objections/
│   └── b2b/
│
├── playbooks/                         # Wave 4 — Shared Playbooks
│   ├── PBK-BRAND-VOICE.md
│   ├── PBK-RESPONSE-STANDARD.md
│   └── PBK-TONE-MATRIX.md
│
├── tests/
│   ├── README.md
│   ├── UAT-001-ALPHA3S-TEST-PACK.md
│   ├── brand/
│   ├── product/
│   ├── sales/
│   ├── conversation/
│   └── faq/
│
└── archive/
    └── superseded/
```

## Document Register

### Foundation and Governance

| Document | Purpose | Project status | Workspace status |
|---|---|---:|---:|
| `README.md` | Entry point và top-level summary; cấu trúc canonical nằm trong file này | approved v2.0.1 | available |
| `FOUNDATION.md` | Vai trò và triết lý vận hành Alpha3S | draft v2.0.0 | available |
| `STYLE_GUIDE.md` | Chuẩn biên soạn Knowledge | draft v2.0.0 | available |
| `CONTRIBUTING.md` | Quy trình đóng góp và review | draft v2.0.0 | available |
| `CHANGELOG.md` | Lịch sử publication | approved | available |
| `ARCHITECTURE.md` | Kiến trúc Knowledge và runtime | draft v2.0.0 | available |
| `taxonomy.yaml` | Taxonomy domain/topic/intent/route | draft v2.0.0 | available |
| `ADR-INDEX.md` | Danh mục ADR | approved | available |
| `ADR-TEMPLATE.md` | Mẫu ADR | approved | unverified |
| `ADR-PRD-001.md` | Brand Truth as Single Source of Truth | locked | unverified |
| `ADR-PRD-002.md` | Product Skills Reference Brand Truth | locked | unverified |
| `ADR-PRD-003.md` | Product Knowledge to Customer Experience | locked | unverified |

`unverified` chỉ có nghĩa file chưa hiện diện trong workspace hiện tại; không phủ nhận việc PO đã duyệt trong giai đoạn trước.

### Brand Foundation

| ID | Title | Project status | Workspace status |
|---|---|---:|---:|
| `SKL-BRAND-001` | 3S Coffee Brand Truth | approved v1.0.0 | available |

Brand Pillars:

- Convenience — Tính tiện lợi khi sử dụng.
- Consistency — Sự ổn định về chất lượng, hương vị và nguồn cung.
- Transparency — Minh bạch và trung thực với khách hàng.

### Customer Service Foundation

| ID | Title | Project status | Workspace status |
|---|---|---:|---:|
| `SKL-CS-001` | Customer Reception | approved v1.0.0 | available |
| `SKL-CS-002` | Need Discovery | approved v1.0.0 | available |
| `SKL-CS-003` | Product Matching | approved v1.0.0 | available |

### Product Foundation — Wave 2

| ID | Title | Project status | Workspace status |
|---|---|---:|---:|
| `SKL-PRD-001` | Freeze-Dried Coffee | approved v1.0.0 | available |
| `SKL-PRD-002` | Raw Materials | approved v1.0.0 | available |
| `SKL-PRD-003` | Taste Experience | approved v1.0.0 | available |
| `SKL-PRD-004` | Brewing Guide / Personalization Foundation | approved v1.0.0 | available |

### Sales Knowledge — Wave 3

| ID | Title | Status | Current workspace file |
|---|---|---:|---|
| `SKL-SAL-001` | Consultative Selling Principles | approved / v1.0.0 | `outputs/SKL-SAL-001.md` |
| `SKL-SAL-002` | Customer Intent Recognition | approved / v1.0.0 | `outputs/SKL-SAL-002.md` |
| `SKL-SAL-003` | Questioning Framework | approved / v1.0.0 | `outputs/SKL-SAL-003.md` |
| `SKL-SAL-004` | Recommendation Engine | approved / v1.0.0 | `outputs/SKL-SAL-004.md` |
| `SKL-SAL-005` | Sales Conversation Patterns | approved / v1.0.0 | `outputs/SKL-SAL-005.md` |

### Conversation Engine — Wave 4

| ID | Title | Status | Current workspace file |
|---|---|---:|---|
| `SKL-CON-001` | Conversation Orchestration | approved / v1.0.0 | `outputs/SKL-CON-001.md` |
| `SKL-CON-002` | Conversation State Management | approved / v1.0.0 | `outputs/SKL-CON-002.md` |
| `SKL-CON-003` | Next Best Action | approved / v1.0.0 | `outputs/SKL-CON-003.md` |

Conversation Engine điều phối nguồn dữ liệu, duy trì state và chọn một Next Best Action. Nó không tự tạo Brand Fact hoặc Product Fact.

### Shared Playbooks — Wave 4

| ID | Title | Status | Current workspace file |
|---|---|---:|---|
| `PBK-BRAND-VOICE` | 3S Coffee Brand Voice | approved / v1.0.0 | `outputs/PBK-BRAND-VOICE.md` |
| `PBK-RESPONSE-STANDARD` | Response Standard | approved / v1.0.0 | `outputs/PBK-RESPONSE-STANDARD.md` |
| `PBK-TONE-MATRIX` | Tone Matrix | approved / v1.0.0 | `outputs/PBK-TONE-MATRIX.md` |

Shared Playbooks kiểm soát cách diễn đạt, độ sâu phản hồi và tone. Chúng không phải nguồn Product Fact.

### FAQ Domain / Knowledge Delivery Layer — Wave 5

| ID | Title | Status | Current workspace file |
|---|---|---:|---|
| `SKL-FAQ-001` | Brand and Product FAQ | approved / v1.0.0 | `outputs/SKL-FAQ-001.md` |
| `SKL-FAQ-002` | Taste and Comparison FAQ | approved / v1.0.0 | `outputs/SKL-FAQ-002.md` |
| `SKL-FAQ-003` | Brewing and Personalization FAQ | approved / v1.0.0 | `outputs/SKL-FAQ-003.md` |
| `SKL-FAQ-004` | Caffeine, Nutrition and Safety FAQ | approved / v1.0.0 | `outputs/SKL-FAQ-004.md` |
| `SKL-FAQ-005` | Ordering Support and Tool Routing FAQ | approved / v1.0.0 | `outputs/SKL-FAQ-005.md` |

FAQ là Delivery Layer: tham chiếu Brand Truth, Product/Sales Skills hoặc Tool; không tạo fact mới.

### Knowledge Graph and Traceability — Wave 6

| ID | Title | Status | Current workspace file |
|---|---|---:|---|
| `KG-001` | Knowledge Graph Model | approved / v1.0.0 | `outputs/KG-001-KNOWLEDGE-GRAPH-MODEL.md` |
| `KG-002` | Entity and Relationship Taxonomy | approved / v1.0.0 | `outputs/KG-002-ENTITY-RELATIONSHIP-TAXONOMY.md` |
| `KG-003` | Impact Analysis Rules | approved / v1.0.0 | `outputs/KG-003-IMPACT-ANALYSIS-RULES.md` |
| `TRACEABILITY` | Alpha3S Knowledge Traceability Matrix | approved / v1.0.0 | `outputs/TRACEABILITY.md` |

Wave 6 hiện là schema và documentation contract. Việc hoàn thành Wave 6 không đồng nghĩa bắt buộc triển khai graph database.

### Prompt Assembly — Wave 7

| ID | Title | Status | Current workspace file |
|---|---|---:|---|
| `PA-001` | Prompt Assembly Pipeline | approved / v1.0.0 | `outputs/PA-001-PROMPT-ASSEMBLY-PIPELINE.md` |
| `PA-002` | Context Selection and Budget | approved / v1.0.0 | `outputs/PA-002-CONTEXT-SELECTION-AND-BUDGET.md` |
| `PA-003` | Source Ordering and Conflict Resolution | approved / v1.0.0 | `outputs/PA-003-SOURCE-ORDERING-AND-CONFLICT-RESOLUTION.md` |

### Runtime Integration — Wave 7

| ID | Title | Status | Current workspace file |
|---|---|---:|---|
| `RT-001` | Runtime Input Output Contract | approved / v1.0.0 | `outputs/RT-001-RUNTIME-INPUT-OUTPUT-CONTRACT.md` |
| `RT-002` | Runtime Guardrails and Fallbacks | approved / v1.0.0 | `outputs/RT-002-RUNTIME-GUARDRAILS-AND-FALLBACKS.md` |

Các file Wave 7 đã được PO phê duyệt và compile thành bản chính thức `v1.0.0` ngày 2026-07-19.

## Knowledge Architecture

```text
Brand Truth
  ↓
Product Knowledge
  ↓
Taste and Usage Experience
  ↓
Sales Knowledge
  ↓
Conversation Engine + Shared Playbooks
  ↓
FAQ Delivery Layer
  ↓
Prompt Assembly and Runtime
```

### Layer Responsibilities

| Layer | Core question |
|---|---|
| Brand Truth | Thương hiệu là ai và điều gì đã được xác nhận? |
| Product Knowledge | Điều gì đúng về sản phẩm? |
| Sales Knowledge | Nên tư vấn và ra quyết định thế nào? |
| Conversation Engine | Nguồn nào cần dùng, state hiện tại là gì và bước tiếp theo là gì? |
| Shared Playbooks | Nên diễn đạt với voice, độ dài và tone nào? |
| FAQ Layer | Khách hỏi theo cách này thì lấy Knowledge nào để trả lời? |
| Tool Layer | Dữ liệu động hoặc theo từng khách hàng là gì? |

## Roadmap Tracker

| Wave | Scope | Status |
|---|---|---:|
| W1 | Foundation, governance, architecture and standards | completed |
| W2 | Brand Truth and Product Foundation | completed |
| W3 | Sales Knowledge Foundation | completed / locked |
| W4 | Conversation Engine and Shared Playbooks | completed / locked |
| W5 | FAQ Domain / Knowledge Delivery Layer | completed / locked |
| W6 | Knowledge Graph and traceability | completed / locked |
| W7 | Prompt Assembly and runtime integration | completed / locked |
| W8 | Evaluation and continuous learning | completed / locked |
| W9 | Developer Integration and Handoff | completed / locked |

## Current Workspace Inventory

### Available and approved

- `ADR-INDEX.md`
- `CHANGELOG.md`
- `SKL-SAL-001.md` đến `SKL-SAL-005.md`
- `SKL-CON-001.md` đến `SKL-CON-003.md`
- `PBK-BRAND-VOICE.md`
- `PBK-RESPONSE-STANDARD.md`
- `PBK-TONE-MATRIX.md`

### Available and approved

- `SKL-FAQ-001.md` đến `SKL-FAQ-005.md`

### Available and approved — Wave 6

- `KG-001-KNOWLEDGE-GRAPH-MODEL.md`
- `KG-002-ENTITY-RELATIONSHIP-TAXONOMY.md`
- `KG-003-IMPACT-ANALYSIS-RULES.md`
- `TRACEABILITY.md`

### Available and approved — Wave 7

- `PA-001-PROMPT-ASSEMBLY-PIPELINE.md`
- `PA-002-CONTEXT-SELECTION-AND-BUDGET.md`
- `PA-003-SOURCE-ORDERING-AND-CONFLICT-RESOLUTION.md`
- `RT-001-RUNTIME-INPUT-OUTPUT-CONTRACT.md`
- `RT-002-RUNTIME-GUARDRAILS-AND-FALLBACKS.md`

### Available and approved — Wave 8

- `EV-001-EVALUATION-FRAMEWORK.md`
- `EV-002-TEST-CASE-SCHEMA.md`
- `EV-003-RETRIEVAL-AND-ROUTING-EVALUATION.md`
- `EV-004-RESPONSE-QUALITY-AND-SAFETY-EVALUATION.md`
- `EV-005-CONTINUOUS-LEARNING-LOOP.md`

### Available and approved — Wave 9

- `DEVELOPER_GUIDE.md`
- `INGESTION_GUIDE.md`
- `RAG_PIPELINE.md`
- `API_CONTRACT.md`

### Available and approved — Release Readiness

- `UAT-001-ALPHA3S-TEST-PACK.md` — approved v1.0.0, 100 test cases.
- `TESTING_GUIDE.md`
- `DEPLOYMENT_GUIDE.md`
- `REFERENCE_IMPLEMENTATION.md`
- `BEST_PRACTICES.md`
- `ANTI_PATTERNS.md`

### Implementation and Go-Live MVP — Next Phase

| Document | Status | Current workspace file |
|---|---:|---|
| `IMPLEMENTATION_PLAN.md` | draft v0.1.0 | `outputs/IMPLEMENTATION_PLAN.md` |
| `DEV_HANDOFF_CHECKLIST.md` | draft v0.1.0 | `outputs/DEV_HANDOFF_CHECKLIST.md` |
| `MVP_RELEASE_CHECKLIST.md` | draft v0.1.0 | `outputs/MVP_RELEASE_CHECKLIST.md` |

### Approved historically but not present in current workspace

- W1 Foundation documents.
- `SKL-BRAND-001`.
- `SKL-CS-001` đến `SKL-CS-003`.
- `SKL-PRD-001` đến `SKL-PRD-004`.
- `ADR-PRD-001` đến `ADR-PRD-003` và `ADR-TEMPLATE.md`.

## Recommended Next Actions

1. PO/dev review Implementation Plan và hai checklist.
2. Dev triển khai ingestion, retrieval, Tool routing, prompt assembly và runtime contract.
3. Chạy P1 smoke/regression tests trước khi mở cho khách thật.
4. Vận hành có giám sát để hướng tới những đơn cà phê đầu tiên.
5. Chỉ bổ sung Knowledge/Tool khi dữ liệu thực tế cho thấy khoảng trống ảnh hưởng CSKH hoặc bán hàng.

## Maintenance Rule

Cập nhật tài liệu này khi:

- PO approve hoặc amend một file.
- CA xuất bản phiên bản mới.
- Thêm hoặc đổi tên domain/folder.
- Một Wave được mở, khóa hoặc thay đổi phạm vi.
- File bị superseded, archived hoặc không còn trong workspace.

## Golden Rule

> **Nếu một thông tin có thể thay đổi theo thời gian hoặc theo từng khách hàng, nó không thuộc Knowledge Base. Hãy lấy từ Tool.**
