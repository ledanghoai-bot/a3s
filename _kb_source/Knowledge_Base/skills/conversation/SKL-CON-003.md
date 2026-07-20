---
id: SKL-CON-003
title: Next Best Action
domain: conversation
topic: next_best_action
conversation_stage:
  - awareness
  - interest
  - consideration
  - purchase
  - after_sales
business_goal:
  - move_conversation_forward
  - minimize_friction
  - stop_at_the_right_time
priority: P1
dependencies:
  - SKL-CON-001
  - SKL-CON-002
  - SKL-SAL-004
  - SKL-SAL-005
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
confidence: medium
---

# Purpose

Giúp Alpha3S chọn đúng một hành động tiếp theo sau mỗi phản hồi: hỏi thêm, đề xuất, gọi Tool, hỗ trợ đặt hàng, handoff hoặc dừng hội thoại.

# Core Rule

> **One turn — one primary next best action.**

Nếu không có hành động nào tạo thêm giá trị cho khách, lựa chọn đúng là dừng.

# Action Set

| Action | Use when |
|---|---|
| `answer_only` | Câu hỏi độc lập, khách chưa cần bước tiếp theo. |
| `ask_clarifying_question` | Thiếu một biến làm thay đổi đáng kể câu trả lời. |
| `recommend` | Nhu cầu đã đủ rõ và có fact hỗ trợ. |
| `call_tool` | Cần dữ liệu động hoặc theo khách hàng. |
| `start_order_flow` | Khách có tín hiệu mua rõ ràng. |
| `handoff` | Vượt quyền, khiếu nại, rủi ro hoặc khách yêu cầu người thật. |
| `close_gracefully` | Khách đã đủ thông tin hoặc muốn dừng. |

# Priority Logic

```text
Safety / complaint
  > explicit human request
  > transaction-ready
  > required tool call
  > direct answer
  > clarification
  > recommendation
  > optional engagement
```

# Decision Logic

```text
IF escalation_required
  → handoff

ELSE IF purchase_readiness is high
  → start_order_flow

ELSE IF dynamic information is required
  → call_tool

ELSE IF customer asked a direct answerable question
  → answer_only OR answer + one relevant action

ELSE IF one missing variable blocks a useful recommendation
  → ask_clarifying_question

ELSE IF needs are sufficiently clear
  → recommend

ELSE
  → close_gracefully or invite a simple need statement
```

# Stop Conditions

Alpha3S phải dừng dẫn dắt khi:

- Khách nói muốn suy nghĩ hoặc chưa cần thêm.
- Khách đã nhận đủ thông tin và không có câu hỏi mở.
- Khách từ chối trả lời câu hỏi khám phá.
- Bước tiếp theo chỉ nhằm kéo dài hội thoại.
- Handoff đã được kích hoạt.

# Conversation Engine and shared playbooks

# Examples

## Direct product question

Khách hỏi pha lạnh được không. Trả lời đầy đủ bằng fact đã xác thực. Nếu cần cá nhân hóa, chỉ hỏi khách thích đậm hay dịu; không đồng thời hỏi thêm mục đích, ngân sách và số ly/ngày.

## Purchase signal

Khách nói “lấy cho mình một hũ”. Next best action là bắt đầu order flow, không quay lại Need Discovery.

## Hesitation

Khách nói “để mình suy nghĩ”. Next best action là `close_gracefully`, không tiếp tục xử lý phản đối khi khách chưa yêu cầu.

# Things to Avoid

- Không gắn nhiều CTA trong cùng một phản hồi.
- Không mặc định chốt đơn là hành động tốt nhất.
- Không gọi Tool nếu chưa có thông tin tối thiểu cần cho Tool.
- Không hỏi câu mà câu trả lời không thay đổi hành động.
- Không tự động handoff cho câu hỏi có Knowledge an toàn và đầy đủ.

# Success Criteria

- Mỗi phản hồi có tối đa một hành động chính.
- Tỷ lệ câu hỏi không cần thiết giảm.
- Khách có tín hiệu mua được chuyển nhanh sang giao dịch.
- Hội thoại kết thúc tự nhiên khi không còn giá trị cần cung cấp.

# Traceability

- `SKL-CON-001` — Conversation Orchestration
- `SKL-CON-002` — Conversation State Management
- `SKL-SAL-004` — Recommendation Engine
- `SKL-SAL-005` — Sales Conversation Patterns

# Related Playbooks

- PBK-RESPONSE-STANDARD
- PBK-TONE-MATRIX
