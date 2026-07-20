---
id: PA-001
title: Prompt Assembly Pipeline
domain: prompt_assembly
document_type: runtime_design
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
priority: P1
dependencies:
  - SKL-CON-001
  - SKL-CON-002
  - SKL-CON-003
  - KG-001
  - TRACEABILITY
---

# Purpose

Định nghĩa cách Alpha3S lắp ráp context cho từng lượt hội thoại. Runtime chỉ đưa vào model những instruction và Knowledge Unit cần thiết, không load toàn bộ repository.

# Assembly Principle

> **Management unit: Markdown document. Runtime unit: approved Knowledge Unit.**

# Assembly Pipeline

```text
Customer message
  ↓
Normalize channel input
  ↓
Detect risk + primary intent
  ↓
Resolve conversation state
  ↓
Decide Tool requirement
  ├─ Tool required → Execute and validate result
  └─ No Tool       → Continue
  ↓
Retrieve approved Knowledge Units
  ↓
Rerank and remove redundancy
  ↓
Select behavior + playbooks
  ↓
Build ordered prompt context
  ↓
Generate candidate response
  ↓
Post-generation validation
  ↓
Send response + update state
```

# Prompt Blocks

Runtime prompt được xây từ các block độc lập:

| Order | Block | Responsibility |
|---:|---|---|
| 1 | Runtime policy | Các luật không được vi phạm. |
| 2 | Agent mission | Vai trò và mục tiêu của Alpha3S. |
| 3 | Source priority | Tool > approved Knowledge > state > general model knowledge. |
| 4 | Current state | Intent, stage, nhu cầu đã xác nhận, câu hỏi chưa giải quyết. |
| 5 | Tool results | Dữ liệu động đã xác thực cho lượt hiện tại. |
| 6 | Knowledge Units | Fact và logic liên quan đã approved. |
| 7 | Behavior instructions | Conversation Skill và Next Best Action. |
| 8 | Voice/response/tone | Shared Playbooks cần cho tình huống. |
| 9 | Output contract | Yêu cầu cấu trúc và giới hạn phản hồi. |

# Inclusion Rules

- Chỉ dùng tài liệu `approved` cho production context.
- Chỉ lấy section/Knowledge Unit phù hợp intent.
- Brand Truth chỉ được chèn khi câu trả lời cần fact thương hiệu hoặc kiểm soát claim.
- Tool result chỉ tồn tại trong scope hợp lệ của lượt/phiên.
- Ví dụ hội thoại chỉ chèn khi giúp behavior khó diễn đạt bằng rule.
- Không chèn README, CHANGELOG, ADR hoặc tài liệu governance vào customer runtime, trừ rule đã được compile từ chúng.

# Assembly Logic

```text
IF safety or complaint
  → Load runtime policy + safety/support behavior + required Tool/Human route.
  → Suppress sales recommendation blocks.

IF dynamic information
  → Load Tool result + response standard.
  → Do not retrieve static price/stock/promotion content.

IF product question
  → Retrieve exact Product Knowledge Unit + relevant FAQ delivery unit.

IF consultation
  → Add Need Discovery / Recommendation / Next Best Action units.

IF simple direct question
  → Keep context minimal; avoid unrelated Sales Skills.
```

# Prompt Template Contract

```text
[RUNTIME_POLICY]
[MISSION]
[SOURCE_PRIORITY]
[CONVERSATION_STATE]
[TOOL_RESULTS]
[KNOWLEDGE_CONTEXT]
[BEHAVIOR_CONTEXT]
[STYLE_CONTEXT]
[OUTPUT_REQUIREMENTS]
[USER_MESSAGE]
```

Block trống phải được bỏ hoàn toàn, không để placeholder nhiễu.

# Things to Avoid

- Không load toàn bộ file/Wave.
- Không đưa draft hoặc superseded asset vào production.
- Không lặp cùng fact ở nhiều block.
- Không để example lấn át fact/rule.
- Không dùng prompt assembly để sửa hoặc tạo Product Fact.

# Success Criteria

- Context đủ để trả lời nhưng không chứa phần lớn nội dung không liên quan.
- Tool và Knowledge không mâu thuẫn trong cùng prompt.
- Có thể log ID/version của mọi block được sử dụng.
- Cùng input và cùng nguồn tạo behavior ổn định ở mức chấp nhận được.

# Related Documents

- PA-002 — Context Selection and Budget
- PA-003 — Source Ordering and Conflict Resolution
- RT-001 — Runtime Input Output Contract
- RT-002 — Runtime Guardrails and Fallbacks
