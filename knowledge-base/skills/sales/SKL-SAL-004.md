---
id: SKL-SAL-004
title: Recommendation Engine
domain: sales
topic: product_recommendation
conversation_stage:
  - interest
  - consideration
  - purchase
customer_intent:
  - seek_recommendation
  - evaluate_fit
  - choose_usage_method
business_goal:
  - match_need_to_product
  - explain_reasoning
  - support_purchase_decision
priority: P1
dependencies:
  - SKL-BRAND-001
  - SKL-CS-003
  - SKL-PRD-001
  - SKL-PRD-002
  - SKL-PRD-003
  - SKL-PRD-004
  - SKL-SAL-001
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

Giúp Alpha3S chuyển nhu cầu đã hiểu thành khuyến nghị có căn cứ, dễ giải thích và không vượt quá Brand Truth hoặc Product Facts đã xác thực.

# Business Context

Ở phạm vi hiện tại, recommendation không nhất thiết là chọn giữa nhiều SKU. Nó có thể là xác định sản phẩm có phù hợp không, chọn cách pha nóng/lạnh, điều chỉnh số muỗng và lượng nước theo khẩu vị, hoặc đề nghị khách cung cấp thêm thông tin trước khi tư vấn.

# Learning Objectives

- Tách fact, quan sát cảm quan và khuyến nghị.
- Dựa trên nhu cầu khách thay vì dùng một lời giới thiệu chung cho mọi người.
- Giải thích ngắn “vì sao phù hợp”.
- Không tạo công thức hoặc claim chưa được phê duyệt.
- Biết khi nào không nên khuyến nghị.

# Recommendation Model

```text
Customer Need
  ↓
Relevant Verified Facts
  ↓
Expected Taste / Usage Experience
  ↓
Conditional Recommendation
  ↓
One Next Best Action
```

# Input Signals

## Usage goal

- Uống hằng ngày.
- Pha nhanh ở nhà hoặc văn phòng.
- Muốn trải nghiệm gần phong cách cà phê pha máy nhưng tiện sử dụng.
- Uống nóng để cảm nhận aroma rõ hơn.
- Uống nguội/lạnh để có cảm giác vị êm hơn.

## Taste preference

- Đậm hoặc dịu.
- Nhạy với vị đắng/chua.
- Ưu tiên aroma.
- Thích uống đen hoặc thêm sữa/đường/đá.

## Constraints

- Thời gian pha.
- Thiết bị hiện có.
- Tổng lượng caffeine trong ngày khi khách quan tâm.
- Dữ liệu sản phẩm, giá hoặc tồn kho hiện có.

# Verified Recommendation Inputs

- 3S Coffee là thương hiệu bán lẻ cà phê sấy lạnh.
- Brand Pillars: Convenience, Consistency, Transparency.
- Sản phẩm đóng hũ, có muỗng đi kèm; 1 muỗng khoảng 1 g.
- Caffeine tham chiếu: 4,1% theo dữ liệu sản phẩm đã cung cấp.
- Nước nóng 80–90°C: khuấy nhẹ khoảng 30 giây; aroma thường rõ hơn.
- Nước nguội 16–18°C: khuấy nhẹ khoảng 3 phút; vị thường được cảm nhận êm hơn.
- Đường, sữa và đá tùy khẩu vị.
- Các công thức biến thể chỉ được dùng sau khi có Product Skill/fact chính thức.

# Decision Logic

```text
IF khách ưu tiên aroma
  → Gợi ý pha nóng theo điều kiện đã xác thực.

IF khách ưu tiên cảm giác êm hoặc thích uống lạnh
  → Gợi ý pha nguội/lạnh theo điều kiện đã xác thực.

IF khách thích đậm
  → Có thể tăng số muỗng hoặc giảm lượng nước.
  → Không ấn định công thức duy nhất khi chưa có chuẩn thương hiệu.

IF khách thích dịu
  → Có thể tăng lượng nước hoặc điều chỉnh số muỗng.

IF khách thích sữa/đường/đá
  → Xác nhận có thể tùy chỉnh theo khẩu vị.
  → Không tự tạo recipe có tên thương mại chưa được duyệt.

IF khách quan tâm caffeine
  → Nêu dữ liệu tham chiếu và phép quy đổi chỉ khi đơn vị/giả định rõ ràng.
  → Hỏi tổng nguồn caffeine trong ngày khi cần.
  → Không biến ngưỡng chung thành chỉ định cá nhân.

IF thiếu fact để so sánh hoặc đề xuất
  → Nói rõ giới hạn.
  → Không suy diễn từ Brand Pillars.

IF khách đã muốn mua
  → Không tiếp tục tối ưu khuyến nghị quá mức.
  → Chuyển sang đặt hàng/Tool.
```

# Recommendation Output Pattern

Một khuyến nghị tốt nên có tối đa bốn thành phần:

1. Tóm tắt nhu cầu.
2. Khuyến nghị có điều kiện.
3. Một lý do dựa trên fact/observation.
4. Một hành động tiếp theo.

Ví dụ:

> Nếu anh/chị ưu tiên aroma rõ và muốn pha nhanh, em nghiêng về cách pha nóng 80–90°C, khuấy nhẹ khoảng 30 giây. Anh/chị có thể bắt đầu với số muỗng vừa khẩu vị rồi điều chỉnh lượng nước ở lần sau; mỗi muỗng đi kèm khoảng 1 g.

# Confidence Handling

## High confidence

Nhu cầu rõ và fact trực tiếp hỗ trợ. Đưa khuyến nghị ngắn.

## Medium confidence

Có đủ hướng tư vấn nhưng còn một biến quan trọng. Đưa khuyến nghị có điều kiện hoặc hỏi một câu.

## Low confidence

Thiếu product fact, khách nói mơ hồ hoặc câu hỏi liên quan an toàn. Không đoán; làm rõ hoặc chuyển người thật.

# Sales Insights

- Khách cần hiểu “phù hợp với tôi vì sao”, không cần xem toàn bộ logic nội bộ.
- Một khuyến nghị có điều kiện đáng tin hơn lời khẳng định chắc chắn khi trải nghiệm phụ thuộc khẩu vị.
- Cách pha là một phần của product matching: cùng sản phẩm có thể tạo trải nghiệm khác khi pha nóng hoặc nguội.
- Không để recommendation engine tạo biến thể sản phẩm hoặc công thức chưa được công bố.
- Khi chưa có nhiều SKU, cá nhân hóa cách dùng có thể mang lại giá trị hơn việc giả lập lựa chọn sản phẩm.

# Examples

## Aroma-first customer

**Khách:** Mình thích cà phê thơm rõ.

**Khuyến nghị:** Ưu tiên pha nóng vì aroma thường được cảm nhận rõ hơn; nêu điều kiện pha đã xác thực.

## Smooth-taste customer

**Khách:** Mình thích vị êm, uống lạnh.

**Khuyến nghị:** Pha với nước nguội theo hướng dẫn; giải thích thời gian hòa tan lâu hơn và cảm giác vị thường êm hơn.

## Unsupported recipe request

**Khách:** Cho công thức cà phê nước dừa chuẩn 3S.

**Khuyến nghị:** Nếu chưa có recipe chính thức, nói rõ thương hiệu chưa cung cấp công thức chuẩn trong Knowledge hiện tại; không tự tạo tỷ lệ.

# Do / Don't

## Do

- Dựa trên nhu cầu đã được khách xác nhận.
- Nói rõ điều kiện và giới hạn.
- Ưu tiên một khuyến nghị chính.
- Dùng “muỗng (khoảng 1 g)” ở lần nhắc đầu tiên.

## Don't

- Không suy diễn tỷ lệ nguyên liệu.
- Không tuyên bố “giống hệt espresso”.
- Không tạo recipe hoặc claim sức khỏe.
- Không dùng dữ liệu động từ Knowledge tĩnh.
- Không đưa quá nhiều lựa chọn khiến khách khó quyết định.

# Escalation

- Khuyến nghị liên quan bệnh lý, thai kỳ, thuốc hoặc triệu chứng.
- Khách cần công thức/tiêu chuẩn B2B chưa được phê duyệt.
- Thiếu fact quan trọng về SKU, lô hàng hoặc chính sách.
- Khiếu nại về chất lượng cần xác minh lô/đơn hàng.

# Traceability

- Brand Truth: `SKL-BRAND-001`
- Product Matching: `SKL-CS-003`
- Taste Experience: `SKL-PRD-003`
- Brewing Guide: `SKL-PRD-004`
- Product experience architecture: `ADR-PRD-003`

# Related Skills

- SKL-SAL-002 — Customer Intent Recognition
- SKL-SAL-003 — Questioning Framework
- SKL-SAL-005 — Sales Conversation Patterns
