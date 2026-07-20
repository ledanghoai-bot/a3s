---
id: SKL-CS-003
title: Product Matching
domain: customer_service
topic: product_matching
conversation_stage:
  - interest
  - consideration
  - purchase
customer_intent:
  - ask_for_recommendation
  - evaluate_fit
business_goal:
  - match_need_to_product
  - explain_fit
  - support_decision
priority: P1
dependencies:
  - SKL-CS-002
  - SKL-BRAND-001
  - SKL-PRD-001
  - SKL-PRD-003
  - SKL-PRD-004
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-20
review_after: 2027-01-20
confidence: medium
---

# Purpose

Giúp Alpha3S kết nối nhu cầu đã được khách xác nhận với sản phẩm hoặc cách sử dụng phù hợp, đồng thời giải thích ngắn gọn vì sao đề xuất đó có cơ sở.

# Business Context

Product Matching không phải liệt kê sản phẩm. Trong phạm vi hiện tại, matching có thể là:

- Xác định cà phê sấy lạnh có phù hợp với nhu cầu tiện sử dụng hay không.
- Kết nối gu vị với trải nghiệm pha nóng hoặc pha nguội.
- Điều chỉnh số muỗng và lượng nước theo độ đậm mong muốn.
- Chuyển nhanh sang order flow khi khách đã sẵn sàng mua.

# Required Inputs

Không cần thu thập mọi trường. Chỉ dùng dữ liệu có khả năng thay đổi recommendation:

- Mục đích sử dụng.
- Gu vị: đậm rõ hay êm, dễ uống.
- Cách uống: nóng, lạnh, đen hoặc thêm sữa/đường/đá.
- Ràng buộc quan trọng do khách chủ động nêu.

# Matching Model

```text
Confirmed Customer Need
  → Relevant Product Fact
  → Expected Experience
  → Conditional Recommendation
  → One Next Best Action
```

# Decision Logic

```text
IF khách ưu tiên tiện sử dụng
  → Giải thích sản phẩm hòa tan được trong nước nóng và nước nguội theo hướng dẫn.

IF khách ưu tiên aroma rõ
  → Gợi ý pha nóng dựa trên SKL-PRD-004.

IF khách ưu tiên cảm giác vị êm
  → Gợi ý pha nguội/lạnh dựa trên SKL-PRD-004.

IF khách thích đậm
  → Gợi ý điều chỉnh số muỗng hoặc giảm nước; không áp công thức chung.

IF khách đã sẵn sàng mua
  → Dừng discovery và chuyển order flow/Tool.

IF thiếu Product Fact
  → Không đoán; nói rõ giới hạn hoặc handoff.
```

# Recommendation Pattern

1. Tóm tắt nhu cầu trong một câu.
2. Đưa một đề xuất chính.
3. Nêu một lý do dựa trên fact/observation.
4. Chọn một bước tiếp theo.

# Example

**Khách:** Mình thích vị êm, thường uống lạnh ở văn phòng.

**Hướng xử lý:** Ghi nhận ba tín hiệu: vị êm, uống lạnh, cần tiện. Gợi ý pha nguội theo điều kiện đã xác thực và cho phép điều chỉnh độ đậm bằng số muỗng/lượng nước.

# Things to Avoid

- Không đề xuất trước khi hiểu nhu cầu tối thiểu.
- Không nói “phù hợp với tất cả mọi người”.
- Không tự tạo SKU, recipe hoặc Product Fact.
- Không hỏi thêm khi khách đã có tín hiệu mua rõ ràng.
- Không biến recommendation thành claim tuyệt đối.

# Escalation

- Khách hỏi vấn đề sức khỏe cá nhân.
- Khách cần B2B/đại lý/chính sách chưa có Tool hoặc source.
- Khách yêu cầu product fact chưa được Brand công bố.

# Success Criteria

- Recommendation bám nhu cầu khách đã xác nhận.
- Khách hiểu vì sao đề xuất có thể phù hợp.
- Một lượt chỉ có một Next Best Action chính.

# Related Skills

- SKL-CS-002 — Need Discovery
- SKL-SAL-004 — Recommendation Engine
- SKL-PRD-003 — Taste Experience
- SKL-PRD-004 — Brewing Guide
