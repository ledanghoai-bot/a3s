---
id: RT-002
title: Runtime Guardrails and Fallbacks
domain: runtime
document_type: runtime_policy
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
priority: P1
dependencies:
  - RT-001
  - SKL-CON-001
  - PBK-RESPONSE-STANDARD
---

# Purpose

Định nghĩa kiểm tra trước/sau generation và fallback an toàn để Alpha3S không bịa fact, không trả dữ liệu động sai và không tiếp tục bán hàng trong tình huống cần hỗ trợ.

# Pre-Generation Guardrails

- Chặn draft/superseded Knowledge Units.
- Xác định Tool bắt buộc trước retrieval tĩnh.
- Đánh dấu risk: sức khỏe, khiếu nại, hoàn tiền, quyền riêng tư, sự cố đơn hàng.
- Loại PII không cần thiết khỏi prompt.
- Kiểm tra source conflict và staleness.
- Tắt sales recommendation khi complaint/safety flow hoạt động.

# Post-Generation Validation

Kiểm tra candidate response:

- Có trả lời đúng intent không?
- Có fact nào không nằm trong provenance không?
- Có giá/tồn kho/khuyến mãi/phí giao không đến từ Tool không?
- Có claim y khoa hoặc tuyệt đối không?
- Có hỏi lại dữ liệu đã biết không?
- Có quá một next best action không?
- Tone có phù hợp risk state không?
- Có lộ metadata, Tool error hoặc internal reasoning không?

# Fallback Levels

## F1 — Minimal factual answer

Dùng khi retrieval đủ fact nhưng generation quá dài/lạc đề. Tạo lại câu trả lời ngắn từ unit trực tiếp.

## F2 — Clarification

Dùng khi thiếu một biến quan trọng hoặc tham chiếu mơ hồ.

## F3 — Honest uncertainty

Dùng khi không có source approved:

> “Hiện em chưa có thông tin xác nhận về điểm này.”

## F4 — Tool retry or alternate capability

Chỉ retry theo policy có giới hạn. Không loop vô hạn.

## F5 — Human handoff

Dùng khi khiếu nại, sức khỏe, yêu cầu người thật, conflict authoritative hoặc Tool thất bại mà khách cần xử lý tiếp.

# Retry Policy

```text
Generation validation failure
  → Regenerate once using validation flags.

Tool transient error
  → Retry according to tool policy.

Repeated failure
  → Safe fallback / handoff.
```

Không retry nếu lỗi do thiếu quyền, thiếu fact hoặc yêu cầu vượt scope.

# Prohibited Behaviors

- Không bịa nguồn, chứng nhận, thành phần hoặc chính sách.
- Không trả dữ liệu động từ memory/Knowledge tĩnh.
- Không chẩn đoán, kê đơn hoặc đảm bảo an toàn cá nhân.
- Không tiếp tục upsell trong complaint/safety flow.
- Không tiết lộ chain-of-thought, prompt, scores hoặc raw Tool output.
- Không hứa handoff thành công hoặc thời gian xử lý chưa được xác nhận.

# Observability

Log tối thiểu:

```yaml
guardrail_event:
  request_id: string
  stage: pre_generation | post_generation
  rule_id: string
  severity: info | warning | block
  action: allow | regenerate | fallback | handoff
  source_ids: []
```

Không log raw PII nếu không cần.

# Success Criteria

- Unsupported Product Fact không tới khách.
- Tool-required questions không được trả bằng dữ liệu tĩnh.
- Validation failure có fallback hữu ích, không im lặng.
- Retry có giới hạn và không làm tăng latency vô kiểm soát.

# Related Documents

- RT-001 — Runtime Input Output Contract
- PA-001 — Prompt Assembly Pipeline
- PA-003 — Source Ordering and Conflict Resolution
- PBK-RESPONSE-STANDARD
