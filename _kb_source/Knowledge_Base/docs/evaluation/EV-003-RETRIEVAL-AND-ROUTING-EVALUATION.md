---
id: EV-003
title: Retrieval and Routing Evaluation
domain: evaluation
document_type: evaluation_guide
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
priority: P1
dependencies:
  - EV-001
  - EV-002
  - PA-001
  - PA-003
---

# Purpose

Đánh giá hệ thống có chọn đúng Knowledge Unit, Tool hoặc Human route trước khi model tạo câu trả lời hay không.

# Retrieval Evaluation

## Ground Truth

Mỗi câu hỏi retrieval phải có:

- Canonical source ID.
- Knowledge Unit/heading mong đợi nếu đã chunk.
- Các source không được dùng.
- Lý do source phù hợp.

## Metrics

- `Hit@1`: source đúng đứng đầu.
- `Hit@K`: source đúng nằm trong top K.
- `MRR`: vị trí source đúng đầu tiên.
- `unsupported_retrieval_rate`: tỷ lệ draft/superseded/unrelated units.
- `redundancy_rate`: tỷ lệ chunks lặp cùng fact.

MVP ưu tiên Hit@K và unsupported retrieval; chưa cần tối ưu mọi metric học thuật.

# Routing Evaluation

## Route Classes

```text
knowledge
tool
human
clarification
answer_without_retrieval
```

## Critical Routing Tests

| Query type | Required route |
|---|---|
| Giá/tồn kho/khuyến mãi hiện tại | Tool |
| Trạng thái đơn | Tool + verification |
| Khiếu nại/hoàn tiền | Human/Support |
| Triệu chứng sức khỏe | Safety + Human/medical guidance |
| Định nghĩa sản phẩm | Knowledge |
| Chào hỏi đơn giản | Answer without retrieval or CS Skill |

# Negative Retrieval Tests

Kiểm tra hệ thống không retrieve sai khi:

- “Có phải 100% Robusta không?” → không lấy định nghĩa cũ.
- “Giá hôm nay?” → không lấy FAQ/Product tĩnh thay Tool.
- “Cold brew?” → phân biệt pha nguội hòa tan với ủ cold brew.
- “Calories?” → không suy từ Total Glucose.
- “Đơn giao thiếu” → không load Sales upsell.

# Query Variants

Mỗi intent P1 nên có:

- Câu chuẩn.
- Câu ngắn.
- Không dấu.
- Teencode phổ biến.
- Câu chứa hai intent.
- Câu dùng tham chiếu “loại này/như lúc nãy” trong multi-turn test.

# Failure Diagnosis

| Symptom | Likely layer |
|---|---|
| Source đúng không vào top K | Embedding/query/chunk metadata |
| Source đúng nhưng model trả sai | Assembly/generation/guardrail |
| Tool question retrieve FAQ | Intent router/source policy |
| Draft được retrieve | Metadata filter/index pipeline |
| Too many duplicate chunks | Chunking/deduplication |

# Acceptance Baseline

- 100% P1 Tool-required cases route Tool trong smoke suite.
- 100% draft/superseded units bị loại khỏi production retrieval.
- 100% safety/complaint P1 cases không route sales recommendation.
- Product P1 questions retrieve canonical source trong configured top K.

# Things to Avoid

- Không chấm retrieval chỉ bằng chất lượng câu trả lời cuối cùng.
- Không tăng K vô hạn để che ranking kém.
- Không dùng source consumer thay canonical source chỉ vì từ khóa giống hơn.
- Không bỏ negative tests.

# Related Documents

- EV-001 — Evaluation Framework
- EV-002 — Test Case Schema
- PA-001 — Prompt Assembly Pipeline
- PA-003 — Source Ordering and Conflict Resolution
