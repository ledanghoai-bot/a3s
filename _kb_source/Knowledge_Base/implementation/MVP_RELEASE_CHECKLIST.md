---
id: IMPL-RELEASE-001
title: MVP Release Checklist
document_type: release_checklist
owner: Alpha3S
version: 0.1.0
status: draft
last_updated: 2026-07-20
---

# Alpha3S MVP Release Checklist

## Release Identity

- [ ] Release, Knowledge commit, index, model, prompt/runtime và test report versions được ghi nhận.

## Knowledge

- [ ] Chỉ approved assets.
- [ ] Brand Truth hiện hành; không có claim 100% Robusta cũ.
- [ ] Không dynamic data trong static Knowledge.
- [ ] Product Facts có provenance.

## Critical Journeys

- [ ] Greeting/consultation, product, taste và brewing.
- [ ] Price/inventory/shipping Tools.
- [ ] Purchase-ready flow.
- [ ] Complaint/handoff và health/safety fallback.

## Safety and Privacy

- [ ] Không S0/S1.
- [ ] Không diagnosis/medical claims.
- [ ] PII tối thiểu và protected.
- [ ] Order lookup verifies access.
- [ ] Không lộ raw Tool error/internal metadata.

## Reliability and Performance

- [ ] Tool/no-retrieval/source-conflict fallbacks tested.
- [ ] Retry bounded và rollback tested.
- [ ] Context budget enforced; latency baseline recorded.

## Go-Live Operations

- [ ] Human monitor/handoff destination active.
- [ ] Traffic/channel ban đầu được giới hạn.
- [ ] Daily issue review và emergency rollback owner.

## Final Decision

```text
GO     → P1 pass; no S0/S1; support and rollback ready.
NO-GO  → Critical Tool, safety, privacy, provenance or handoff failure.
```
