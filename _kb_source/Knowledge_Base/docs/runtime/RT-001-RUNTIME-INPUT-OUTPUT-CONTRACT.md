---
id: RT-001
title: Runtime Input Output Contract
domain: runtime
document_type: api_contract
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
priority: P1
dependencies:
  - PA-001
  - PA-002
  - PA-003
  - SKL-CON-002
---

# Purpose

Định nghĩa dữ liệu tối thiểu mà Orchestrator cung cấp cho Prompt Assembly và dữ liệu runtime phải nhận lại sau khi model xử lý. Đây là contract logic, không phụ thuộc framework hoặc model.

# Runtime Input

```yaml
request_id: string
channel: messenger | zalo | web | api | other
timestamp: ISO-8601
customer_message:
  text: string
  attachments: []
conversation:
  conversation_id: string
  recent_turns: []
  state: {}
customer_context:
  verified_fields: {}
routing:
  primary_intent: string | unknown
  secondary_intents: []
  risk_flags: []
tool_results: []
retrieved_units: []
runtime_config:
  locale: vi-VN
  context_budget: integer
  response_mode: customer_chat
```

# Retrieved Unit Contract

```yaml
id: KU-PRD-004-003
parent_id: SKL-PRD-004
source_version: 1.0.0
status: approved
domain: product
heading: Cold Brewing
content: string
score: number
relationships: []
```

# Tool Result Contract

```yaml
tool_id: TOOL-PRICING
status: success | partial | error
observed_at: ISO-8601
expires_at: ISO-8601 | null
data: {}
customer_safe_summary: string | null
error_code: string | null
```

# Runtime Output

```yaml
request_id: string
response:
  text: string
  locale: vi-VN
decision:
  primary_intent: string
  next_best_action: answer_only | ask_clarifying_question | recommend | call_tool | start_order_flow | handoff | close_gracefully
  tool_request: null | {}
  handoff_request: null | {}
state_update:
  confirmed_fields: {}
  inferred_fields: {}
  unresolved_questions: []
provenance:
  knowledge_unit_ids: []
  tool_result_ids: []
  playbook_ids: []
validation:
  passed: boolean
  flags: []
```

# Contract Rules

- `response.text` không chứa metadata nội bộ.
- Inferred fields không được ghi đè confirmed fields nếu chưa có xác nhận.
- Tool result lỗi không được biến thành dữ liệu customer-facing giả định.
- Provenance phải lưu được nhưng không bắt buộc hiển thị cho khách.
- Một output chỉ có một `next_best_action` chính.
- `handoff` phải kèm reason code đủ cho người tiếp nhận.

# Error Handling

| Condition | Runtime action |
|---|---|
| Missing user text and unsupported attachment | Ask for supported input or handoff. |
| Retrieval empty | Use safe fallback; do not invent Product Fact. |
| Tool error | Explain temporary inability and offer handoff. |
| Validation failed | Regenerate once with flags or handoff/fallback. |
| Contract parsing failed | Do not send raw model output; use safe fallback. |

# Privacy Boundary

- Chỉ đưa vào prompt dữ liệu khách cần thiết cho nhiệm vụ.
- Log provenance và decisions; hạn chế log raw PII.
- Không trả nội dung state, risk flags hoặc internal scores cho khách.

# Versioning

Contract dùng Semantic Versioning:

- MAJOR: breaking schema change.
- MINOR: thêm optional field.
- PATCH: làm rõ mô tả không đổi schema.

# Related Documents

- PA-001 — Prompt Assembly Pipeline
- PA-002 — Context Selection and Budget
- PA-003 — Source Ordering and Conflict Resolution
- RT-002 — Runtime Guardrails and Fallbacks
