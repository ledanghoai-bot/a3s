---
id: IMPL-PLAN-001
title: Alpha3S Implementation Plan
document_type: implementation_plan
owner: Alpha3S
version: 0.1.0
status: draft
phase: implementation_go_live_mvp
last_updated: 2026-07-20
---

# Alpha3S Implementation Plan

## Objective

Đưa Knowledge Base V1 vào Alpha3S để CSKH, tư vấn và hỗ trợ những đơn cà phê đầu tiên trong phạm vi MVP an toàn.

## MVP Scope

### Must Have

- Ingest approved Markdown và tạo heading-based Knowledge Units.
- Approved/status/version filters.
- Hybrid retrieval và reranking cơ bản.
- Conversation state tối thiểu.
- Tool routing cho giá, tồn kho, vận chuyển và đơn hàng.
- Prompt Assembly theo PA-001..003.
- Runtime contract/guardrails RT-001..002.
- Human handoff cho complaint/safety.
- Provenance logging và P1 smoke suite.

### Out of Scope

- Graph database, analytics dashboard, auto-learning/auto-publish.
- Multi-agent marketplace và recommendation ML riêng.

## Milestones

### M1 — Repository and Ingestion

Tạo canonical folders, parser front matter, validation, Knowledge Unit builder và rejected-asset report.

**Exit:** approved assets ingest được; draft/superseded bị chặn.

### M2 — Retrieval

Xây lexical + vector index, metadata filters, reranking, deduplication và provenance.

**Exit:** Product/FAQ smoke queries lấy đúng canonical source.

### M3 — Tools and Routing

Kết nối pricing, inventory, shipping, order status, risk router, Tool fallback và human handoff.

**Exit:** dynamic queries không dùng Knowledge tĩnh.

### M4 — Prompt and Runtime

Triển khai block assembly, context budget, source conflict handling, response validation và fallback.

**Exit:** output đúng RT-001; safety smoke pass.

### M5 — Evaluation and Staging

Tạo P1 fixtures, retrieval/routing/state tests, staging deployment và internal canary.

**Exit:** không S0/S1; PO/QA sign-off.

### M6 — Supervised Go-Live

Giới hạn channel/traffic, bật monitoring/handoff và review issue hằng ngày.

**Exit:** Agent vận hành ổn định và hỗ trợ giao dịch thật.

## Work Order

```text
Ingestion → Retrieval → Tool Gate → Runtime → Evaluation → Staging → Supervised Production
```

## Ownership

| Workstream | Owner |
|---|---|
| Knowledge/source approval | PO + CA |
| Ingestion/retrieval/runtime | Dev |
| Tool contracts | Dev + business owner |
| Tests/review | QA + CA + PO |
| Handoff operation | Support/Operations |

## Stop/Go Rules

GO khi P1 smoke pass, Tool routes và handoff hoạt động, rollback đã thử.

STOP khi có S0/S1, dynamic-data leakage, safety/complaint routing lỗi hoặc không có provenance.

## Immediate Dev Task

Bắt đầu tại `DEVELOPER_GUIDE.md`, sau đó triển khai M1 theo `INGESTION_GUIDE.md` và `REFERENCE_IMPLEMENTATION.md`.
