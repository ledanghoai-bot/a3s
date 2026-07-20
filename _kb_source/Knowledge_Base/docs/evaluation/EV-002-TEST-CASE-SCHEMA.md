---
id: EV-002
title: Test Case Schema
domain: evaluation
document_type: test_contract
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
priority: P1
dependencies:
  - EV-001
  - RT-001
---

# Purpose

Chuẩn hóa cấu trúc test để Dev và QA có thể kiểm tra retrieval, routing, response và state bằng cùng một contract.

# Single-Turn Test Schema

```yaml
id: TST-PRD-001
title: Explain freeze-dried coffee
suite:
  - smoke
  - retrieval
priority: P1
input:
  message: "Cà phê sấy lạnh là gì?"
  conversation_state: {}
expected:
  primary_intent: product_understanding
  route: knowledge
  source_ids:
    must_include:
      - SKL-PRD-001
    must_not_include: []
  response:
    must_convey:
      - là cà phê hòa tan
      - sản xuất bằng công nghệ sấy lạnh
    must_not_claim:
      - 100% Robusta
      - ngon nhất
  next_best_action:
    allowed:
      - answer_only
      - ask_clarifying_question
severity_if_failed: S1
```

# Tool-Routing Test Schema

```yaml
id: TST-ORD-001
title: Current price requires Tool
suite:
  - smoke
  - routing
priority: P1
input:
  message: "Hôm nay một hũ giá bao nhiêu?"
expected:
  route: tool
  tool_id: TOOL-PRICING
  static_answer_allowed: false
  next_best_action: call_tool
severity_if_failed: S1
```

# Multi-Turn Test Schema

```yaml
id: TST-CON-001
title: Preserve taste preference across turns
suite:
  - conversation
priority: P1
turns:
  - user: "Mình thích vị êm và thường uống lạnh."
    expected_state:
      taste_preference: smooth
      brew_preference: cold
  - user: "Vậy pha sao?"
    expected:
      route: knowledge
      source_ids:
        must_include:
          - SKL-PRD-004
      must_not_ask_again:
        - taste_preference
        - brew_preference
severity_if_failed: S2
```

# Field Definitions

| Field | Required | Meaning |
|---|---:|---|
| `id` | yes | ID duy nhất. |
| `suite` | yes | Nhóm test. |
| `priority` | yes | P1–P4. |
| `input/turns` | yes | Một lượt hoặc nhiều lượt. |
| `expected.route` | when applicable | Knowledge/Tool/Human. |
| `source_ids` | when grounded | Source bắt buộc/cấm. |
| `must_convey` | optional | Ý nghĩa cần có, không bắt buộc nguyên văn. |
| `must_not_claim` | optional | Claim cấm. |
| `next_best_action` | optional | Hành động mong đợi. |
| `severity_if_failed` | yes | S0–S3. |

# Assertion Types

- Exact: IDs, enum, schema, Tool route.
- Semantic: must convey an approved meaning.
- Prohibited: unsupported claim, PII, static dynamic data.
- Behavioral: one question, handoff, no upsell.
- State: confirmed/inferred fields and corrections.

# Test Authoring Rules

- Một test nên nhắm một failure mode chính.
- Expected response kiểm tra ý, không khóa văn mẫu.
- Product Fact phải truy được về canonical source.
- Test lỗi production phải lưu nguyên cách hỏi đã làm sạch PII.
- Teencode/không dấu được dùng như variants, không thay thế test tiếng Việt chuẩn.

# Versioning

Test thay đổi khi source/behavior thay đổi có phê duyệt. Không sửa expected chỉ để model mới “pass” nếu behavior cũ vẫn đúng.

# Related Documents

- EV-001 — Evaluation Framework
- EV-003 — Retrieval and Routing Evaluation
- EV-004 — Response Quality and Safety Evaluation
