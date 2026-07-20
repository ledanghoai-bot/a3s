---
id: DEV-API-CONTRACT
title: Integration API Contract
domain: integration
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
owner: Alpha3S
---

# Purpose

Định nghĩa các interface logic giữa Channel, Orchestrator, Retriever, Tool Layer và Response Runtime.

# Process Message

```json
{
  "request_id": "uuid",
  "conversation_id": "string",
  "channel": "web",
  "message": {"text": "...", "attachments": []},
  "customer_context": {},
  "timestamp": "ISO-8601"
}
```

Response:

```json
{
  "request_id": "uuid",
  "response": {"text": "...", "locale": "vi-VN"},
  "next_best_action": "answer_only",
  "tool_request": null,
  "handoff_request": null,
  "provenance": {"knowledge_unit_ids": [], "tool_result_ids": []},
  "validation": {"passed": true, "flags": []}
}
```

# Retrieve Knowledge

Input:

```json
{"query":"...","intent":"...","filters":{"status":"approved"},"top_k":5}
```

Output mỗi unit phải có `id`, `parent_id`, `source_version`, `heading`, `content`, `score` và relationships cần thiết.

# Execute Tool

```json
{
  "tool_id": "TOOL-PRICING",
  "request_id": "uuid",
  "arguments": {},
  "customer_context": {}
}
```

Result tuân RT-001: `status`, `observed_at`, `expires_at`, `data`, `customer_safe_summary`, `error_code`.

# Handoff

```json
{
  "conversation_id": "string",
  "reason_code": "COMPLAINT",
  "summary": "sanitized summary",
  "priority": "normal|urgent",
  "required_team": "support"
}
```

# Error Contract

| Code | Meaning |
|---|---|
| `INVALID_INPUT` | Missing/invalid request. |
| `NO_APPROVED_KNOWLEDGE` | No approved source. |
| `TOOL_UNAVAILABLE` | Required capability unavailable. |
| `SOURCE_CONFLICT` | Authoritative conflict. |
| `VALIDATION_FAILED` | Candidate response blocked. |
| `HANDOFF_REQUIRED` | Human route required. |

# Security

- AuthN/AuthZ tùy channel/tool.
- Không log full payment/PII.
- Verify order access before returning status.
- Idempotency key cho create-order/payment-like actions.

# Versioning

URI/header hoặc schema version phải hỗ trợ breaking change. Optional field mới là MINOR; breaking field là MAJOR.
