---
id: SKL-CON-002
title: Conversation State Management
domain: conversation
topic: conversation_state
business_goal:
  - preserve_context
  - avoid_repetition
  - support_consistent_decisions
priority: P1
dependencies:
  - SKL-CON-001
  - SKL-SAL-002
  - SKL-SAL-003
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
confidence: medium
---

# Purpose

Quy định Alpha3S cần ghi nhận, sử dụng và cập nhật trạng thái hội thoại như thế nào để tư vấn liên tục, không hỏi lại và không biến giả định thành sự thật.

# State Model

```yaml
conversation_state:
  primary_intent: unknown
  secondary_intents: []
  stage: awareness
  customer_needs:
    usage_goal: unknown
    taste_preference: unknown
    brew_preference: unknown
  referenced_product: unknown
  purchase_readiness: unknown
  unresolved_questions: []
  tool_results: []
  escalation_required: false
```

# State Principles

## Confirmed over inferred

Thông tin khách nói rõ được đánh dấu `confirmed`. Nội dung suy ra từ ngữ cảnh phải là `inferred` kèm confidence và không được trình bày như fact của khách.

## Current over stale

Nếu khách thay đổi ý định hoặc khẩu vị, dữ liệu mới nhất được ưu tiên. Không cố bảo vệ phân loại trước đó.

## Minimum necessary state

Chỉ giữ thông tin phục vụ cuộc hội thoại và dịch vụ. Không thu thập dữ liệu cá nhân không cần thiết.

## Dynamic data expiry

Giá, tồn kho, khuyến mãi, phí giao và trạng thái đơn chỉ có giá trị theo kết quả Tool và thời điểm truy xuất. Không tái sử dụng như Knowledge lâu dài.

# State Update Logic

```text
ON every customer message
  → Detect new intent and corrections.
  → Resolve references using recent context.
  → Update only fields supported by evidence.
  → Preserve unresolved questions.
  → Mark stale tool results when context/time changes.

ON recommendation
  → Store need summary and recommendation rationale.

ON purchase signal
  → Update purchase_readiness.
  → Route to transaction without repeating discovery.

ON complaint or safety issue
  → Set escalation_required = true.
  → Suspend sales progression.
```

# Reference Resolution

- “Loại này” chỉ được gắn với sản phẩm đang được nhắc hoặc đang hiển thị rõ.
- “Như lúc nãy” phải tham chiếu nội dung gần nhất có cùng chủ đề.
- Nếu có từ hai đối tượng hợp lý trở lên, hỏi lại thay vì đoán.
- Không dùng ký ức ngoài phiên để khẳng định thông tin nhạy cảm nếu khách chưa xác nhận lại.

# Customer Corrections

Khi khách sửa thông tin:

1. Xác nhận ngắn.
2. Ghi đè trạng thái cũ.
3. Điều chỉnh khuyến nghị nếu thay đổi có ảnh hưởng.
4. Không tranh luận hoặc nhắc lại lỗi của khách.

# Things to Avoid

- Không coi intent là nhãn cố định của khách.
- Không ghi nhận bệnh lý, thu nhập hoặc đặc điểm nhạy cảm bằng suy đoán.
- Không hỏi lại dữ liệu vừa được cung cấp.
- Không dùng kết quả Tool cũ khi khách hỏi “hiện tại/hôm nay”.
- Không để state nội bộ xuất hiện nguyên dạng trong câu trả lời.

# Success Criteria

- Alpha3S duy trì được chủ đề và tham chiếu đúng.
- Khách không phải lặp lại nhu cầu.
- Recommendation thay đổi khi khách sửa thông tin.
- Dữ liệu động được làm mới đúng lúc.

# Traceability

- `SKL-SAL-002` — Customer Intent Recognition
- `SKL-SAL-003` — Questioning Framework
- `SKL-CON-001` — Conversation Orchestration

# Related Skills

- SKL-CON-003 — Next Best Action
- PBK-RESPONSE-STANDARD — Response Standard
