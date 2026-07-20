---
id: IMPL-HANDOFF-001
title: Developer Handoff Checklist
document_type: checklist
owner: Alpha3S
version: 0.1.0
status: draft
last_updated: 2026-07-20
---

# Developer Handoff Checklist

## Repository and Ingestion

- [ ] Canonical folders theo `depository-structure.md`.
- [ ] Approved files đặt đúng folder; draft/superseded bị chặn.
- [ ] UTF-8, front matter parser và metadata validation.
- [ ] Duplicate IDs bị block.
- [ ] Heading-based Knowledge Units có stable IDs/hash/version.
- [ ] Rejected asset report được tạo.

## Retrieval

- [ ] Approved filter bắt buộc.
- [ ] Hybrid lexical/vector retrieval.
- [ ] Reranking/deduplication và canonical-source priority.
- [ ] Provenance IDs trong runtime output/log.

## Tools

- [ ] Pricing, inventory, shipping và order status.
- [ ] Tool TTL/error contract.
- [ ] Không fallback sang giá/tồn kho tĩnh.

## Conversation Runtime

- [ ] Intent/risk routing.
- [ ] Confirmed vs inferred state.
- [ ] One Next Best Action.
- [ ] Complaint/safety override sales.
- [ ] Human handoff có reason/summary.

## Prompt and Guardrails

- [ ] Block-based assembly và context budget.
- [ ] Source conflict resolution.
- [ ] Response validation và bounded retry/fallback.

## Testing and Deployment

- [ ] P1 retrieval, Tool routing, Brand Truth, safety và multi-turn tests.
- [ ] Versioned index/release manifest.
- [ ] Staging, atomic switch và rollback.
- [ ] Secrets không nằm trong repository.
- [ ] Monitoring tối thiểu.

## Sign-Off

- [ ] Dev confirms implementation.
- [ ] QA confirms P1 tests.
- [ ] PO confirms business behavior.
- [ ] Support confirms handoff readiness.
