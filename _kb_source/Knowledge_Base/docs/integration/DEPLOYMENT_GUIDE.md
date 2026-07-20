---
id: DEV-DEPLOYMENT
title: Deployment Guide
domain: integration
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
owner: Alpha3S
---

# Purpose

Triển khai Knowledge và runtime an toàn, versioned và rollback được.

# Release Flow

```text
Merge approved assets
  → Validate/lint
  → Build versioned Knowledge Units
  → Build new index
  → Run smoke/regression
  → Deploy runtime config/prompt version
  → Canary
  → Promote
  → Monitor
```

# Release Manifest

```yaml
release_id: alpha3s-2026-07-19.1
knowledge_commit: sha
index_version: string
embedding_model: string
prompt_assembly_version: 1.0.0
runtime_contract_version: 1.0.0
model: configured-model
test_report_id: string
```

# Environments

- `dev`: local/test data.
- `staging`: production-like, no live customer mutation.
- `production`: approved releases only.

# Deployment Rules

- Không build index trực tiếp đè production.
- Atomic switch index/version.
- Tool credentials qua secret manager/environment, không trong Markdown.
- Canary một phần traffic hoặc internal channel trước.
- Không auto-push production chỉ vì file Markdown đổi.

# Rollback

Rollback đồng bộ:

- Runtime/prompt version.
- Knowledge index version.
- Tool adapter/config nếu có.

Không rollback chỉ một phần khiến provenance/source mismatch.

# Smoke After Deploy

- Product fact.
- Tool price route.
- Complaint handoff.
- State multi-turn.
- Provenance log.
- No draft assets.

# Monitoring

Theo dõi latency, Tool errors, no-knowledge fallbacks, handoff rate, S0/S1 guardrail events và failed response validation.

# Stop Condition

Nếu S0/S1 hoặc Tool trả dữ liệu sai: halt promotion, rollback, tạo regression test trước release lại.
