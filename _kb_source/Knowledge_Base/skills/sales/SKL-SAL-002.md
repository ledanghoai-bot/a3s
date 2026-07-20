---
id: SKL-SAL-002
title: Customer Intent Recognition
domain: sales
topic: customer_intent_recognition
conversation_stage:
  - awareness
  - interest
  - consideration
  - purchase
  - after_sales
customer_intent:
  - discover_product
  - compare
  - evaluate_taste
  - learn_brewing
  - ask_dynamic_information
  - order
  - request_support
business_goal:
  - identify_primary_intent
  - route_correctly
  - reduce_customer_effort
priority: P1
dependencies:
  - SKL-SAL-001
  - SKL-CS-002
  - SKL-PRD-001
  - SKL-PRD-003
  - SKL-PRD-004
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
confidence: medium
---

# Purpose

Giúp Alpha3S nhận diện khách đang thực sự muốn làm gì, chọn đúng nguồn tri thức hoặc Tool và phản hồi mà không bắt khách giải thích lại nhiều lần.

# Business Context

Một câu nói có thể chứa nhiều tín hiệu. “Loại này có đắng không, tối uống được chứ?” vừa liên quan khẩu vị vừa liên quan caffeine và sức khỏe. Alpha3S cần xác định intent chính, xử lý câu hỏi có thể trả lời an toàn, rồi làm rõ phần còn thiếu.

Intent recognition là bước định tuyến, không phải gắn nhãn khách hàng cứng nhắc. Nhãn chỉ có giá trị trong ngữ cảnh hiện tại và có thể thay đổi ở lượt tiếp theo.

# Learning Objectives

- Xác định intent chính và các intent phụ.
- Phân biệt câu hỏi thông tin, tín hiệu mua, phản đối, yêu cầu hỗ trợ và trò chuyện xã giao.
- Nhận biết dữ liệu tĩnh so với dữ liệu động.
- Không suy luận đặc điểm cá nhân nhạy cảm từ lời nói ngắn.
- Chọn hỏi lại khi độ mơ hồ ảnh hưởng đáng kể tới câu trả lời.

# Intent Taxonomy

## Greeting and reception

Ví dụ: “shop ơi”, “alo”, “còn online không?”.

Hành động: tiếp nhận ngắn, hỏi nhu cầu mở.

## Product understanding

Ví dụ: “cà phê sấy lạnh là gì?”, “nguyên liệu gì?”.

Hành động: lấy Product Knowledge tương ứng; không kể toàn bộ catalogue.

## Taste evaluation

Ví dụ: “có đắng không?”, “giống cà phê pha máy không?”, “uống có êm không?”.

Hành động: dùng `SKL-PRD-003`; tránh khẳng định tuyệt đối.

## Usage and brewing

Ví dụ: “pha lạnh được không?”, “mấy muỗng?”, “thêm sữa được chứ?”.

Hành động: dùng `SKL-PRD-004`; cá nhân hóa theo khẩu vị nếu đủ dữ liệu.

## Comparison

Ví dụ: “khác cà phê phin/G7/Nescafé thế nào?”.

Hành động: so sánh theo tiêu chí khách quan và nhu cầu; không chê đối thủ.

## Dynamic information

Ví dụ: giá, tồn kho, phí giao, khuyến mãi, trạng thái đơn.

Hành động: gọi Tool; Knowledge tĩnh không được dùng để đoán.

## Purchase intent

Ví dụ: “lấy cho mình một hũ”, “đặt thế nào?”, “ship về Hà Nội”.

Hành động: giảm câu hỏi tư vấn; chuyển nhanh sang quy trình đặt hàng.

## Objection or hesitation

Ví dụ: “đắt quá”, “để suy nghĩ”, “sợ đắng”, “sợ mất ngủ”.

Hành động: xác nhận mối lo, trả lời có căn cứ, không tranh luận hoặc ép mua.

## After-sales support

Ví dụ: sản phẩm khó tan, hũ bị ẩm, giao thiếu, muốn đổi trả.

Hành động: phân biệt hướng dẫn sử dụng với sự cố cần Tool/human handoff.

## Health and safety

Ví dụ: mang thai, huyết áp, dùng thuốc, phản ứng tim đập nhanh.

Hành động: trả lời ở mức thông tin chung đã xác thực; không chẩn đoán; chuyển chuyên môn khi cần.

# Decision Logic

```text
1. Xác định khách muốn biết, muốn làm hoặc đang lo điều gì.
2. Chọn một primary_intent theo mục tiêu tức thời của lượt chat.
3. Ghi nhận secondary_intents nếu có nhưng không làm câu trả lời lan man.
4. Kiểm tra intent cần Knowledge, Tool hay Human.
5. Nếu confidence thấp và lựa chọn sai có hậu quả đáng kể → hỏi lại một câu.
6. Nếu confidence đủ → trả lời trực tiếp và dẫn tới bước phù hợp tiếp theo.
```

## Priority rules

```text
Safety / complaint / order problem
  > direct purchase request
  > direct product question
  > consultation opportunity
  > general conversation
```

# Ambiguity Handling

## Ambiguous product reference

**Khách:** Loại này pha sao?

Nếu hệ thống có ngữ cảnh sản phẩm vừa xem, dùng ngữ cảnh đó. Nếu không có, hỏi khách đang nói tới sản phẩm nào; không đoán.

## Multiple questions

**Khách:** Có đắng không, giá bao nhiêu, ship tỉnh được chứ?

Trả lời theo thứ tự có ích: thông tin sản phẩm có thể trả lời → dữ liệu giá/giao hàng qua Tool → một bước đặt hàng nếu khách sẵn sàng.

## Vague buying signal

**Khách:** Mình đang tìm cà phê uống ở văn phòng.

Intent chính: tư vấn theo mục đích sử dụng. Hỏi một tiêu chí có sức phân loại cao, ví dụ khẩu vị đậm hay êm.

# Sales Insights

- Intent mua hàng thường thể hiện qua động từ hành động: lấy, đặt, ship, thanh toán, giao.
- Câu hỏi giá không đồng nghĩa khách chỉ quan tâm giá; nhưng phải báo giá trước khi hỏi sâu.
- “Có ngon không?” là intent đánh giá độ phù hợp, không phải yêu cầu một lời khen sản phẩm.
- “Giống espresso không?” là nhu cầu hình dung trải nghiệm, không nhất thiết là yêu cầu phân tích kỹ thuật.
- Khi khách đã ra quyết định, hỏi thêm quá nhiều có thể làm chậm chốt đơn.

# Examples

## Example 1

**Input:** Tôi thích espresso nhưng không có máy.

**Primary intent:** `evaluate_fit`

**Secondary intent:** `seek_convenience`

**Route:** Taste Experience + Brand Truth.

## Example 2

**Input:** Hôm nay giá sao?

**Primary intent:** `ask_dynamic_information`

**Route:** Pricing Tool.

## Example 3

**Input:** Uống xong tim đập nhanh thì làm sao?

**Primary intent:** `health_safety`

**Route:** Safety response + human/medical escalation as appropriate.

# Do / Don't

## Do

- Dựa vào lời khách và ngữ cảnh hội thoại hiện có.
- Giữ intent dưới dạng giả thuyết có confidence.
- Ưu tiên xử lý rủi ro, sự cố và yêu cầu mua rõ ràng.
- Route dữ liệu động sang Tool.

## Don't

- Không gắn nhãn tính cách, thu nhập hoặc bệnh lý khi khách chưa nói.
- Không dùng một intent cũ cho toàn bộ cuộc hội thoại.
- Không bỏ sót câu hỏi phụ quan trọng.
- Không hỏi lại điều khách đã cung cấp.

# Escalation

- Intent liên quan khiếu nại, hoàn tiền hoặc sự cố đơn hàng.
- Nội dung sức khỏe có triệu chứng hoặc yêu cầu chỉ định cá nhân.
- Ý định B2B/đại lý chưa có chính sách xác thực.
- Không thể xác định đúng sản phẩm/đơn hàng sau một lần làm rõ.

# Traceability

- Consultative selling: `SKL-SAL-001`
- Need discovery: `SKL-CS-002`
- Taste: `SKL-PRD-003`
- Brewing: `SKL-PRD-004`
- Source priority: ADR liên quan Tool/Knowledge trong Wave 1

# Related Skills

- SKL-SAL-003 — Questioning Framework
- SKL-SAL-004 — Recommendation Engine
- SKL-SAL-005 — Sales Conversation Patterns
