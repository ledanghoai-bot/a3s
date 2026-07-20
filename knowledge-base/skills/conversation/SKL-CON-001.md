---
id: SKL-CON-001
title: Conversation Orchestration
domain: conversation
topic: conversation_orchestration
conversation_stage:
  - awareness
  - interest
  - consideration
  - purchase
  - after_sales
business_goal:
  - coordinate_conversation
  - select_correct_capability
  - reduce_customer_effort
priority: P1
dependencies:
  - SKL-BRAND-001
  - SKL-CS-001
  - SKL-CS-002
  - SKL-CS-003
  - SKL-SAL-001
  - SKL-SAL-002
  - SKL-SAL-003
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

Điều phối một lượt hội thoại từ lúc nhận tin nhắn đến khi tạo phản hồi: xác định nhu cầu, ưu tiên an toàn, chọn Knowledge/Tool/Playbook phù hợp và đưa cuộc trò chuyện tiến thêm một bước mà không làm khách mất công.

# Operating Model

```text
Observe
  → Detect intent and risk
  → Select source: Tool / Knowledge / Human
  → Select behavior and tone
  → Build concise response
  → Choose one next best action
  → Update conversation state
```

# Source Priority

1. Tool cho dữ liệu động hoặc theo từng khách hàng.
2. Human handoff cho tình huống vượt quyền, khiếu nại hoặc rủi ro.
3. Brand Truth và Knowledge đã được phê duyệt.
4. Conversation state đã được khách xác nhận.
5. Model knowledge chỉ dùng cho kiến thức chung không mâu thuẫn và không biến thành Product Fact.

# Decision Logic

```text
IF có vấn đề an toàn, khiếu nại hoặc sự cố đơn hàng
  → Tạm dừng mục tiêu bán hàng.
  → Ưu tiên xử lý hoặc handoff.

ELSE IF khách yêu cầu dữ liệu động
  → Gọi Tool trước khi trả lời.

ELSE IF khách đã sẵn sàng mua
  → Chuyển nhanh sang quy trình giao dịch.

ELSE IF câu hỏi cụ thể và có Knowledge phù hợp
  → Trả lời trực tiếp.
  → Chỉ hỏi thêm nếu giúp quyết định tốt hơn.

ELSE IF khách yêu cầu tư vấn
  → Need Discovery tối thiểu.
  → Recommendation có căn cứ.

ELSE
  → Làm rõ bằng một câu hỏi ngắn.
```

# Response Assembly

Một phản hồi có thể gồm tối đa bốn khối, nhưng chỉ dùng khối cần thiết:

1. `acknowledge` — xác nhận nhu cầu/cảm xúc.
2. `answer` — trả lời trực tiếp.
3. `reason` — giải thích ngắn bằng fact.
4. `next_action` — một câu hỏi hoặc hành động tiếp theo.

# Routing Rules

| Situation | Primary route |
|---|---|
| Chào hỏi, xin tư vấn | Customer Service Skills |
| Hỏi đặc tính sản phẩm | Product Skills |
| Hỏi độ phù hợp | Sales Recommendation |
| Hỏi giá, tồn kho, vận chuyển | Tool |
| Khiếu nại, hoàn tiền | Human/Support flow |
| Sức khỏe hoặc triệu chứng | Safety response + escalation |

# Sales Insights

- Không phải lượt chat nào cũng cần đủ bốn khối phản hồi.
- Khách hỏi ngắn thường ưu tiên câu trả lời nhanh; độ sâu chỉ tăng khi khách hỏi sâu.
- Khi khách đã xác nhận mua, orchestration phải giảm tư vấn và tăng hỗ trợ giao dịch.
- Không để Brand Voice che khuất nội dung hoặc biến lời xin lỗi thành marketing.

# Things to Avoid

- Không load hoặc nhắc lại toàn bộ Knowledge Base.
- Không dùng nhiều next action trong một lượt.
- Không gọi Tool khi Knowledge tĩnh đã đủ; không dùng Knowledge khi Tool là bắt buộc.
- Không tiếp tục bán hàng trong khi khách đang gặp sự cố.
- Không tạo fact để lấp khoảng trống retrieval.

# Success Criteria

- Khách nhận được câu trả lời đúng trọng tâm ngay lượt hiện tại.
- Nguồn dữ liệu được chọn đúng.
- Phản hồi không lặp hoặc hỏi lại thông tin đã biết.
- Hội thoại tiến tới hiểu nhu cầu, giải quyết vấn đề hoặc hoàn thành giao dịch.

# Traceability

- `SKL-SAL-001` đến `SKL-SAL-005`
- `PBK-BRAND-VOICE`
- `PBK-RESPONSE-STANDARD`
- `PBK-TONE-MATRIX`

# Related Skills

- SKL-CON-002 — Conversation State Management
- SKL-CON-003 — Next Best Action
