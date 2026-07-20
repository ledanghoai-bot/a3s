---
id: SKL-PRD-004
title: Brewing Guide and Personalization
domain: product
topic: brewing_personalization
conversation_stage:
  - interest
  - consideration
  - after_sales
customer_intent:
  - learn_brewing
  - personalize_taste
  - ask_caffeine
business_goal:
  - guide_usage
  - improve_experience
priority: P1
dependencies:
  - SKL-BRAND-001
  - SKL-PRD-003
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-20
review_after: 2027-01-20
confidence: high
---

# Purpose

Hướng dẫn khách pha và cá nhân hóa trải nghiệm dựa trên Verified Product Facts. Không áp đặt một công thức chung và không tự tạo recipe thương hiệu.

# Verified Product Facts

## Serving System

| Attribute | Verified value |
|---|---|
| Packaging | Hũ |
| Measuring tool | Muỗng đi kèm |
| Reference serving | 1 muỗng khoảng 1 g sản phẩm |

Trong hội thoại, lần đầu viết: **1 muỗng (khoảng 1 g)**.

## Product Indicators

| Indicator | Value |
|---|---:|
| Caffeine | 4.1% |
| Total Glucose | 1.06% |
| Moisture | 3.43% |

## Solubility

### Pha nóng

- Nhiệt độ nước: 80–90°C.
- Khuấy nhẹ khoảng 30 giây.
- Aroma thường được cảm nhận rõ hơn.

### Pha nguội

- Nhiệt độ nước: 16–18°C.
- Khuấy nhẹ khoảng 3 phút.
- Vị thường được cảm nhận êm hơn.

# Personalization Logic

```text
IF thích đậm
  → tăng số muỗng hoặc giảm lượng nước.

IF thích dịu
  → giảm số muỗng hoặc tăng lượng nước.

IF ưu tiên aroma
  → cân nhắc pha nóng.

IF ưu tiên cảm giác êm/uống lạnh
  → cân nhắc pha nguội/lạnh.
```

Không có công thức chung phù hợp mọi người. Đường, sữa và đá thêm theo khẩu vị.

# Caffeine Guidance

Với caffeine 4,1% và 1 muỗng khoảng 1 g, một muỗng tương ứng **ước tính khoảng 41 mg caffeine**. Đây là phép quy đổi tham khảo; không dùng làm chỉ định cá nhân.

Lượng phù hợp còn phụ thuộc khả năng dung nạp, số muỗng mỗi ly và tổng caffeine từ các nguồn khác trong ngày. Không đưa một số muỗng/ngày chung cho mọi người.

# Common Questions

## Có pha lạnh được không?

Có. Dùng hướng dẫn nước nguội đã xác thực. Phân biệt “pha nguội hòa tan” với cold brew theo nghĩa ủ chiết xuất lâu.

## Có thêm sữa, đường hoặc đá không?

Có thể thêm theo khẩu vị. Không tự gọi là công thức latte/cappuccino chuẩn thương hiệu nếu chưa có tỷ lệ chính thức.

## Có công thức cà phê nước dừa/cam/protein không?

Chỉ cung cấp khi Brand có recipe/Skill được phê duyệt. Không tự tạo tỷ lệ.

# Safety Boundary

- Không suy calorie chỉ từ Total Glucose.
- Không nói “không đường” khi chưa có fact tương ứng.
- Không tư vấn bệnh lý, thai kỳ hoặc tương tác thuốc.
- Khi có triệu chứng như tim đập nhanh/bồn chồn, ưu tiên safety/handoff.

# Things to Avoid

- Không dùng “1 gói”; sản phẩm đóng hũ.
- Không quên gram ở lần nhắc muỗng đầu tiên.
- Không áp một recipe chung.
- Không tạo recipe chưa phê duyệt.
- Không biến phép tính caffeine thành khuyến nghị y khoa.

# Related Skills

- SKL-PRD-003 — Taste Experience
- SKL-SAL-004 — Recommendation Engine
- SKL-FAQ-003 — Brewing and Personalization FAQ
- SKL-FAQ-004 — Caffeine, Nutrition and Safety FAQ
