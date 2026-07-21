---
id: ALPHA3S-NLU-README
title: Alpha3S NLU Intent and Utterance Library
document_type: dataset_readme
domain: nlu
owner: Alpha3S
version: 1.1.0
status: approved
approved_by: PO
approved_at: 2026-07-20
created_at: 2026-07-20
last_updated: 2026-07-20
---

# Alpha3S NLU Intent & Utterance Library

## Purpose

Giúp Alpha3S nhận diện khách đang muốn gì trước khi chọn Knowledge, Tool, Playbook hoặc Human Handoff.

NLU trả lời câu hỏi:

> **Khách đang muốn hệ thống làm gì?**

Knowledge trả lời câu hỏi:

> **Hệ thống cần biết gì để phản hồi đúng?**

Hai lớp không được trộn lẫn.

## Canonical Layout

```text
datasets/nlu/
├── README.md
├── intent-catalog.yaml
├── normalization.yaml
├── routing-rules.yaml
├── utterances/
│   ├── 01_greetings.yaml
│   ├── 02_price.yaml
│   ├── 03_product_inquiry.yaml
│   ├── 04_purchase.yaml
│   ├── 05_shipping.yaml
│   ├── 06_support.yaml
│   ├── 07_language_variants.yaml
│   └── 08_contrastive_boundaries.yaml
└── tests/
    ├── intent-routing.yaml
    ├── intent-routing-v1.1-additions.yaml
    └── normalization.yaml
```

## Source-of-Truth Rules

- Intent chỉ được định nghĩa tại `intent-catalog.yaml`.
- Một utterance có một ID duy nhất.
- Utterance có thể gắn một primary intent; multi-intent được đánh dấu riêng.
- Normalization chỉ thay đổi hình thức, không thay đổi ý nghĩa.
- Test utterances phải được giữ ngoài tập train/reference.
- Dynamic data thuộc Tool, không thuộc NLU dataset.
- Ranh giới intent dễ nhầm được mô tả bằng `confusable_with` và `boundary` trong contrastive dataset.
- High-precision/entity-aware routing được quản lý tại `routing-rules.yaml`.

## Train/Test Leakage Scope

Quy tắc không trùng train/test áp dụng giữa:

```text
utterances train/reference
↔ intent-routing-tests.yaml
```

Quy tắc này không áp dụng cho `normalization-tests.yaml`. Normalization tests được phép dùng chính các cách viết phổ biến có trong mappings hoặc utterances vì mục tiêu của chúng là kiểm tra hàm biến đổi đầu vào, không đánh giá khả năng tổng quát hóa của intent classifier.

Protected phrases như tên thương hiệu/sản phẩm phải được giữ nguyên qua normalization và được quản lý trong `normalization.yaml`.

## Naming

Intent dùng `snake_case` và động từ rõ ràng:

```text
ask_price
purchase_product
request_refund
end_conversation
```

Entity dùng danh từ số ít:

```text
product
quantity
location
order_id
```

Utterance ID:

```text
UTT-{DOMAIN}-{NUMBER}
```

Ví dụ:

```text
UTT-PRICE-001
UTT-SHIP-014
```

## Lifecycle

```text
draft
  → review
  → approved
  → compiled
  → production
  → deprecated
```

Chỉ dữ liệu `approved` được compile vào runtime.

## MVP Baseline

- 30 intent P1/P2.
- 300–400 utterances.
- 80–120 normalization mappings.
- Tối thiểu 5 held-out test utterances cho mỗi intent P1.
- Không mở rộng taxonomy chỉ để bao phủ cách nói khác nhau; cách nói khác nhau là utterance, không phải intent mới.

## Contribution Workflow

```text
Conversation log đã làm sạch
  → đề xuất utterance/intent
  → kiểm tra duplicate
  → CA review taxonomy
  → PO approve/amend
  → DEV compile
  → QA regression test
```

## Prohibited Practices

- Embed utterance cùng Product Knowledge.
- Paste danh sách utterance vào system prompt.
- Tạo intent riêng cho từng cách viết sai.
- Tạo intent riêng cho từng số lượng/màu/size.
- Dùng cùng utterance cho train và test.
- Cache giá, tồn kho, khuyến mãi hoặc trạng thái đơn trong NLU.

## Related Documents

- `ADR-NLU-001.md`
- `NLU-INTEGRATION-GUIDE.md`
- `taxonomy.yaml`
- `UAT-001-ALPHA3S-TEST-PACK.md`
