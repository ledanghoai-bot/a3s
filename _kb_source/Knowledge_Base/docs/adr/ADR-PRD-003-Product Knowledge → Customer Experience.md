# ADR-W2-PRD-003 --- Product Knowledge to Customer Experience

**Status:** Approved\
**Version:** 1.0.0\
**Date:** 2026-07-17

------------------------------------------------------------------------

# Context

Trong quá trình xây dựng Product Knowledge cho Alpha3S, nhóm kiến trúc
nhận thấy khách hàng không ra quyết định mua dựa trên mô tả công nghệ
hay thông số kỹ thuật. Khách hàng quan tâm nhiều hơn đến trải nghiệm
thực tế khi sử dụng sản phẩm.

Do đó, Product Knowledge cần chuyển từ việc mô tả sản phẩm sang mô tả
trải nghiệm mà sản phẩm mang lại.

------------------------------------------------------------------------

# Decision

## 1. Đổi tên Product Skill

PRD-003 được đổi tên thành:

> **SKL-PRD-003 --- Taste Experience**

Tên mới phản ánh đúng mục tiêu: giúp AI hiểu và diễn giải trải nghiệm
hương vị dưới góc nhìn của khách hàng.

## 2. Chuỗi suy luận chuẩn

Mọi tư vấn liên quan đến sản phẩm phải tuân theo mô hình:

``` text
Manufacturing Technology
        ↓
Product Characteristics
        ↓
Taste Experience
        ↓
Customer Expectation
        ↓
Recommendation
```

AI không được bỏ qua các bước trung gian hoặc đưa ra kết luận mang tính
quảng cáo.

## 3. Nguyên tắc trả lời

Alpha3S luôn áp dụng:

> **Fact → Observation → Recommendation**

Trong đó:

-   **Fact:** thông tin đã được xác thực.
-   **Observation:** mô tả cảm nhận hoặc đặc tính phổ biến, không tuyệt
    đối hóa.
-   **Recommendation:** gợi ý phù hợp với nhu cầu của khách hàng.

## 4. Experience Mapping

Alpha3S phải chuyển ngôn ngữ đời thường của khách hàng thành các thuộc
tính cảm quan.

Ví dụ:

  Khách hàng nói             AI hiểu
  -------------------------- --------------------------
  Có thơm không?             Aroma
  Có đậm không?              Body
  Có đắng không?             Bitterness
  Có giống espresso không?   Taste Experience Mapping

## 5. Sales Insights

Từ PRD-003 trở đi, mỗi Product Skill phải có mục **Sales Insights**.

Mục này giúp AI hiểu:

-   Khách thực sự đang muốn biết điều gì.
-   Cách trả lời phù hợp với bối cảnh bán hàng.
-   Khi nào nên giải thích sâu hơn và khi nào nên dừng.

Sales Insights là cầu nối giữa Product Knowledge và Sales Skills.

------------------------------------------------------------------------

# Consequences

## Benefits

-   Product Knowledge tập trung vào trải nghiệm khách hàng.
-   Tăng tính tự nhiên và khả năng tư vấn của Alpha3S.
-   Duy trì nguyên tắc minh bạch, tránh phóng đại.
-   Tạo nền tảng cho Recommendation Engine trong tương lai.

## Risks

-   Cần kiểm soát chặt chẽ ranh giới giữa trải nghiệm và tuyên bố khẳng
    định.
-   Mọi nội dung phải nhất quán với SKL-BRAND-001.

------------------------------------------------------------------------

# References

-   SKL-BRAND-001
-   SKL-PRD-001
-   SKL-PRD-002
-   SKL-CS-002
-   SKL-CS-003
