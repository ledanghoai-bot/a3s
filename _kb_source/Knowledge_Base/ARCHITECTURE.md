---
id: ALPHA3S-ARCHITECTURE
title: Alpha3S Knowledge and Runtime Architecture
document_type: architecture
owner: Alpha3S
version: 2.0.0
status: approved
approved_by: PO
last_review: 2026-07-20
review_after: 2027-01-20
last_updated: 2026-07-20
---

# Alpha3S Architecture

## Scope

Tài liệu mô tả kiến trúc từ customer message đến response. Cấu trúc thư mục canonical nằm tại `depository-structure.md`; implementation details nằm trong bộ W9 Developer Handoff.

## High-Level Runtime

```text
Customer / Channel
  → Channel Adapter
  → Orchestrator
  → Risk + Intent Router
  → Conversation State
  → Tool Gate
  → Hybrid Retriever
  → Reranker + Source Resolver
  → Context Builder
  → Prompt Assembly
  → LLM
  → Response Validator / Guardrails
  → Customer Response or Human Handoff
```

## Knowledge Layers

```text
Brand Truth
  → Product Knowledge
  → Sales Knowledge
  → Conversation Engine + Playbooks
  → FAQ Delivery
  → Runtime Knowledge Units
```

## Source Priority

```text
Runtime/safety policy
  > Current verified Tool result
  > Approved canonical Brand/Product source
  > Approved behavior/playbook
  > Confirmed conversation state
  > Approved FAQ guidance
  > General model knowledge
```

## Static vs Dynamic Boundary

| Static Knowledge | Dynamic Tool data |
|---|---|
| Brand Truth | Giá/tồn kho/khuyến mãi |
| Product facts | Phí/thời gian giao |
| Brewing facts | Trạng thái đơn |
| Sales behavior | Customer-specific data |
| FAQ routing | Payment/order mutations |

## Ingestion

```text
Approved Markdown
  → Front matter validation
  → Semantic heading split
  → Stable Knowledge Unit IDs
  → Metadata enrichment
  → Deduplicate
  → Embed + lexical index
  → Versioned publication
```

Không ingest mặc định README, CHANGELOG, ADR, governance, draft hoặc archived assets vào customer retrieval.

## Retrieval

- Hybrid vector + lexical/BM25.
- Approved/version filters.
- Reranking theo intent và canonical source priority.
- Related expansion tối đa một bước trong MVP.
- Context budget theo PA-002.

## Conversation

- State phân biệt confirmed và inferred.
- Một Next Best Action chính mỗi lượt.
- Purchase-ready chuyển sang order flow.
- Complaint/safety tắt sales progression.

## Prompt Assembly

```text
Policy
  + Mission
  + Source Priority
  + State
  + Tool Results
  + Knowledge Units
  + Behavior
  + Voice/Tone
  + Output Contract
```

Block trống bị bỏ; không load toàn bộ repository.

## Runtime Contract

Input/output và provenance tuân `RT-001`; guardrails/fallback tuân `RT-002`. Mọi response customer-facing phải truy được về Knowledge Unit/Tool result hoặc được đánh dấu là general safe response.

## Evaluation

- P1 smoke tests.
- Retrieval/routing tests.
- Response/safety tests.
- Regression từ lỗi thực tế.
- S0/S1 block release.

## Deployment

- Versioned index/config/prompt/model manifest.
- Build beside production, atomic switch.
- Canary, monitor và rollback đồng bộ.

## Explicit Non-Goals for MVP

- Không bắt buộc graph database.
- Không tự động học từ chat thô.
- Không multi-agent marketplace.
- Không dashboard phức tạp trước vận hành thật.

## Architecture Baseline

W1–W9 đã khóa baseline. Mọi mở rộng kiến trúc mới phải chứng minh tác động trực tiếp tới CSKH, độ an toàn hoặc bán hàng.
