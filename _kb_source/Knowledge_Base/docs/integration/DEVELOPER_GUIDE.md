---
id: DEV-GUIDE
title: Alpha3S Developer Guide
domain: integration
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
owner: Alpha3S
---

# Purpose

Hướng dẫn dev tích hợp Alpha3S Knowledge Base đúng kiến trúc đã được PO phê duyệt, từ Markdown tới phản hồi khách hàng.

# System Boundary

```text
Channel Adapter
  → Orchestrator
  → Intent/Risk Router
  → Tool Layer + Knowledge Retriever
  → Prompt Assembly
  → LLM
  → Runtime Guardrails
  → Customer Response
```

# Source Responsibilities

| Source | Responsibility |
|---|---|
| Brand/Product Skills | Canonical static facts. |
| Sales/Conversation Skills | Decision and behavior. |
| Playbooks | Voice, format and tone. |
| FAQ | Maps customer wording to approved sources/routes. |
| Tool | Dynamic/customer-specific data. |
| Runtime policy | Safety and hard constraints. |

# Non-Negotiable Rules

- Production chỉ ingest asset `approved`.
- Không load toàn bộ repository vào mỗi prompt.
- Chunk/retrieve theo Knowledge Unit hoặc heading.
- Giá, tồn kho, khuyến mãi, giao hàng và đơn hàng phải qua Tool.
- Tool result thắng Knowledge tĩnh.
- Mọi response lưu provenance IDs.
- Complaint/safety flow tắt sales progression.

# Recommended Implementation Order

1. Markdown loader + front matter parser.
2. Asset validation và approved filter.
3. Heading-based Knowledge Unit builder.
4. Index/embedding pipeline.
5. Intent/risk routing.
6. Tool adapters.
7. Hybrid retrieval + reranking.
8. Prompt assembly theo PA-001.
9. Runtime contract RT-001.
10. Guardrails RT-002.
11. Smoke/regression tests EV-001..005.

# MVP Cut Line

Phải có trước khi chạy khách thật:

- Approved-only ingestion.
- Tool routing cho dữ liệu động.
- Product/FAQ retrieval.
- Conversation state tối thiểu.
- Provenance logging.
- Safety/complaint handoff.
- P1 smoke tests.

Có thể để sau:

- Graph database.
- Dashboard analytics.
- Automated Knowledge Doctor.
- Marketplace hoặc multi-agent orchestration.

# Configuration

```yaml
knowledge_root: ./skills
playbook_root: ./playbooks
approved_status: approved
locale: vi-VN
retrieval:
  mode: hybrid
  top_k: configurable
prompt:
  context_budget: configurable
runtime:
  provenance_logging: true
  block_draft_assets: true
```

# Definition of Done

- Dev ingest được asset và Knowledge Units.
- Câu hỏi P1 lấy đúng source/Tool.
- Runtime output đúng contract.
- Không có S0/S1 trong smoke suite.
- Có rollback index và Knowledge version.

# Companion Documents

- INGESTION_GUIDE.md
- RAG_PIPELINE.md
- API_CONTRACT.md
- TESTING_GUIDE.md
- DEPLOYMENT_GUIDE.md
- REFERENCE_IMPLEMENTATION.md
- BEST_PRACTICES.md
- ANTI_PATTERNS.md
