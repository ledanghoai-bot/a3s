---
id: DEV-RAG
title: RAG Pipeline
domain: integration
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
owner: Alpha3S
---

# Purpose

Mô tả retrieval pipeline cho tiếng Việt và các ID/tên sản phẩm, độc lập vector store cụ thể.

# Query Pipeline

```text
User query + conversation state
  → Normalize
  → Intent/risk classification
  → Tool-required gate
  → Metadata filter
  → Vector search + lexical search
  → Merge/deduplicate
  → Rerank
  → Source-priority validation
  → Context selection/budget
  → Prompt Assembly
```

# Tool Gate

Trước retrieval, route Tool nếu intent là giá, tồn kho, khuyến mãi, vận chuyển hoặc đơn hàng. FAQ routing có thể hỗ trợ quyết định nhưng không cung cấp dữ liệu động.

# Hybrid Retrieval

Vector search phù hợp paraphrase; lexical/BM25 phù hợp ID, SKU, tên riêng và thuật ngữ. Merge theo rank fusion hoặc chiến lược có thể cấu hình.

# Filters

```yaml
status: approved
language: vi
domain: inferred_or_allowed_domains
source_version: active
```

# Retrieval Expansion

- Start với exact intent units.
- Có thể mở rộng dependencies/related assets một bước.
- Canonical source được ưu tiên hơn consumer FAQ khi cần fact.
- Không mở rộng graph không giới hạn.

# Reranking

Reranker xem xét:

- Intent match.
- Canonical-source priority.
- Heading/query match.
- Conversation-state relevance.
- Approved status/version.

# Context Builder

- Loại fact trùng.
- Giữ Tool result riêng khỏi Knowledge.
- Giữ provenance IDs.
- Tuân PA-002 context budget.

# Failure Modes

| Failure | Action |
|---|---|
| No result | Honest uncertainty/clarification/handoff. |
| Conflicting sources | PA-003 resolution; do not guess. |
| Only draft result | Treat as no approved result. |
| Tool-required query | Stop static retrieval response. |
| Too many duplicates | Deduplicate and inspect chunking. |

# Observability

Log query, sanitized state, candidate IDs/scores, selected IDs, filters, latency và route. Hạn chế raw PII.

# Baseline Tests

- Brand definition.
- Freeze-dried definition.
- Hot/cold brewing.
- Caffeine calculation source.
- 100% Robusta correction.
- Price → Tool.
- Complaint → Human.
