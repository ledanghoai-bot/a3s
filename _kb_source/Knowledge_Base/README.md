---
id: ALPHA3S-README
title: Alpha3S Knowledge Base
document_type: repository_readme
owner: Alpha3S
version: 2.0.2
status: approved
approved_by: PO
last_review: 2026-07-20
review_after: 2027-01-20
last_updated: 2026-07-20
---

# Alpha3S Knowledge Base

Alpha3S Knowledge Base là hệ thống tri thức, kỹ năng, playbook và contract vận hành dành cho AI Agent CSKH và tư vấn bán hàng của 3S Coffee.

Mission:

> **CSKH và tư vấn như người thật — Không giờ nghỉ — Hoạt động siêu tốc.**

Business North Star trước mắt:

> **Hỗ trợ bán những đơn cà phê 3S Coffee đầu tiên.**

## Knowledge Is Source Code

Knowledge trong repository này được quản lý như source code:

- Có ID và version.
- Có trạng thái draft/approved/locked.
- Có nguồn chân lý và dependencies.
- Được PO review trước khi publish.
- Có thể kiểm thử, rollback và phân tích ảnh hưởng.

Knowledge Base không phải một system prompt khổng lồ và không phải nơi lưu dữ liệu thay đổi theo thời gian.

## Golden Rule

> **Nếu một thông tin có thể thay đổi theo thời gian hoặc theo từng khách hàng, nó không thuộc Knowledge Base. Hãy lấy từ Tool.**

Ví dụ dữ liệu phải lấy từ Tool:

- Giá hiện tại.
- Tồn kho.
- Khuyến mãi và voucher.
- Phí và thời gian giao hàng.
- Trạng thái đơn.
- Thông tin thanh toán hoặc khách hàng.

## Architecture at a Glance

```text
Brand Truth
  ↓
Product Knowledge
  ↓
Sales Knowledge
  ↓
Conversation Engine + Shared Playbooks
  ↓
FAQ Delivery Layer
  ↓
Knowledge Units + Tool Results
  ↓
Prompt Assembly + Runtime Guardrails
  ↓
Customer Response
  ↓
Evaluation + Continuous Learning
```

### Layer Responsibilities

| Layer | Responsibility |
|---|---|
| Brand Truth | Nguồn chân lý duy nhất cho thương hiệu. |
| Product Knowledge | Fact, đặc tính và trải nghiệm sản phẩm. |
| Customer Service | Tiếp nhận, khám phá nhu cầu và product matching. |
| Sales Knowledge | Logic tư vấn, đặt câu hỏi và recommendation. |
| Conversation Engine | Intent, state, source routing và Next Best Action. |
| Shared Playbooks | Brand voice, response standard và tone. |
| FAQ | Chuyển cách hỏi của khách thành source/route phù hợp. |
| Tool Layer | Dữ liệu động và hành động ngoài hệ thống. |
| Prompt/Runtime | Lắp context, tạo và kiểm tra phản hồi. |
| Evaluation | Smoke test, regression và feedback loop. |

## Canonical Source Priority

```text
Applicable runtime/safety policy
  > Current verified Tool result
  > Approved Brand/Product source
  > Approved behavior/playbook
  > Confirmed conversation state
  > Approved FAQ guidance
  > General model knowledge
```

Nếu hai nguồn authoritative cùng cấp mâu thuẫn, Alpha3S không được đoán; phải dùng fallback hoặc human handoff.

## Canonical Repository Paths

- Skill root: `skills/`
- FAQ Skills: `skills/faq/`
- Không sử dụng `skill/` hoặc `docs/faq/`.
- File nén/release phải bảo toàn chính xác cấu trúc này.

## Repository Structure

`depository-structure.md` là **canonical source duy nhất** cho cấu trúc thư mục và trạng thái từng tài liệu. README chỉ hiển thị top-level summary theo đúng cùng thứ tự; không được dùng phần này để tạo một cấu trúc thay thế.

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
│   ├── adr/
│   ├── governance/
│   ├── templates/
│   ├── knowledge_graph/
│   ├── prompt_assembly/
│   ├── runtime/
│   ├── evaluation/
│   └── integration/
│
├── skills/
│   ├── brand/
│   ├── customer_service/
│   ├── product/
│   ├── sales/
│   ├── conversation/
│   ├── faq/
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
├── playbooks/
│   ├── PBK-BRAND-VOICE.md
│   ├── PBK-RESPONSE-STANDARD.md
│   └── PBK-TONE-MATRIX.md
│
├── tests/
│   ├── brand/
│   ├── product/
│   ├── sales/
│   ├── conversation/
│   └── faq/
│
└── archive/
    └── superseded/
```

Xem tên file, version, trạng thái và vị trí chi tiết tại `depository-structure.md`. Khi hai tài liệu không nhất quán, `depository-structure.md` thắng và README phải được sửa theo.

## Asset Types

| Prefix | Asset type | Example |
|---|---|---|
| `SKL-BRAND` | Brand Truth | `SKL-BRAND-001` |
| `SKL-PRD` | Product Skill | `SKL-PRD-003` |
| `SKL-CS` | Customer Service Skill | `SKL-CS-002` |
| `SKL-SAL` | Sales Skill | `SKL-SAL-004` |
| `SKL-CON` | Conversation Skill | `SKL-CON-001` |
| `SKL-FAQ` | FAQ Delivery Skill | `SKL-FAQ-003` |
| `PBK` | Shared Playbook | `PBK-TONE-MATRIX` |
| `KG` | Knowledge Graph contract | `KG-001` |
| `PA` | Prompt Assembly | `PA-001` |
| `RT` | Runtime contract/policy | `RT-001` |
| `EV` | Evaluation standard | `EV-001` |
| `ADR` | Architecture decision | `ADR-PRD-003` |

## Current Baseline

| Wave | Scope | Status |
|---|---|---:|
| W1 | Foundation and governance | completed |
| W2 | Brand and Product Foundation | completed |
| W3 | Sales Knowledge | completed / locked |
| W4 | Conversation Engine and Shared Playbooks | completed / locked |
| W5 | FAQ Delivery Layer | completed / locked |
| W6 | Knowledge Graph and Traceability | completed / locked |
| W7 | Prompt Assembly and Runtime | completed / locked |
| W8 | Evaluation and Continuous Learning | completed / locked |
| W9 | Developer Integration and Handoff | completed / locked |

Kiến trúc đã đạt điểm dừng. Bước tiếp theo là implementation, smoke testing và vận hành có giám sát với khách thật.

## How to Read This Repository

### Product Owner / Knowledge Author

Đọc theo thứ tự:

1. `FOUNDATION.md`
2. `SKL-BRAND-001`
3. `STYLE_GUIDE.md`
4. Product, Sales và FAQ Skills liên quan.
5. `depository-structure.md` và `CHANGELOG.md`.

### Developer

Bắt đầu tại:

1. `DEVELOPER_GUIDE.md`
2. `INGESTION_GUIDE.md`
3. `RAG_PIPELINE.md`
4. `API_CONTRACT.md`
5. `REFERENCE_IMPLEMENTATION.md`
6. `TESTING_GUIDE.md`
7. `DEPLOYMENT_GUIDE.md`
8. `BEST_PRACTICES.md` và `ANTI_PATTERNS.md`

### QA

Bắt đầu tại:

1. `EV-001-EVALUATION-FRAMEWORK.md`
2. `EV-002-TEST-CASE-SCHEMA.md`
3. `EV-003-RETRIEVAL-AND-ROUTING-EVALUATION.md`
4. `EV-004-RESPONSE-QUALITY-AND-SAFETY-EVALUATION.md`
5. `TESTING_GUIDE.md`

## Runtime Usage

Không coi file Markdown là đơn vị runtime. Khi ingest:

```text
Approved Markdown
  → Parse metadata
  → Split by semantic heading
  → Create stable Knowledge Units
  → Index/embed
  → Retrieve only relevant units
  → Assemble bounded context
```

Production phải loại bỏ:

- Draft và superseded assets.
- Governance/CHANGELOG khỏi customer retrieval.
- Knowledge Unit không có provenance.
- Dữ liệu động được viết cứng trong Markdown.

## Working Agreement

```text
CA defines scope
  → CA authors and exports .md
  → PO reviews
  ├─ Approve → compile approved version and lock
  └─ Amend   → revise and review again
```

Quy ước ngôn ngữ:

- Structure, metadata, field names và enum: English.
- Business Knowledge và ví dụ hội thoại: Vietnamese.

## Change Workflow

1. Xác định canonical source cần sửa.
2. Phân tích consumers bằng `TRACEABILITY.md` và `KG-003`.
3. Tạo hoặc cập nhật test trước khi publish.
4. PO review và approve.
5. Rebuild affected Knowledge Units/index.
6. Chạy smoke và regression.
7. Cập nhật `CHANGELOG.md`.
8. Deploy versioned release và giữ rollback.

## Release Gate

Không release khi:

- Có lỗi S0/S1.
- Draft/superseded asset lọt vào production index.
- Câu hỏi Tool-required được trả bằng Knowledge tĩnh.
- Brand Truth regression.
- Safety hoặc complaint routing không đạt smoke tests.

## Point of Stop

Repository đã có đủ baseline để dev implement. Không tiếp tục mở rộng kiến trúc chỉ vì có thể.

Ưu tiên tiếp theo:

1. Ingest approved assets.
2. Kết nối Tool bắt buộc.
3. Chạy P1 smoke tests.
4. Vận hành có giám sát.
5. Cập nhật Knowledge từ câu hỏi thật ảnh hưởng CSKH và đơn hàng.

> **Architecture serves Business. Business serves Customers. Customers create Revenue.**
