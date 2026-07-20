---
id: EV-001
title: Evaluation Framework
domain: evaluation
document_type: evaluation_standard
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
priority: P1
dependencies:
  - RT-001
  - RT-002
  - TRACEABILITY
---

# Purpose

Định nghĩa cách đánh giá Alpha3S trước khi đưa vào production và sau mỗi thay đổi có ảnh hưởng đến Knowledge, retrieval, prompt assembly, model hoặc Tool routing.

# Evaluation Goals

Alpha3S phải chứng minh được năm năng lực:

1. Hiểu đúng nhu cầu chính của khách.
2. Lấy đúng Knowledge/Tool/Human route.
3. Trả lời đúng fact, không hallucination.
4. Tư vấn tự nhiên, ngắn và giúp hội thoại tiến lên.
5. Dừng hoặc handoff đúng khi vượt scope.

# Evaluation Layers

| Layer | Core question |
|---|---|
| Knowledge validation | Source có chính xác và approved không? |
| Retrieval | Có lấy đúng Knowledge Unit không? |
| Routing | Có chọn đúng Knowledge, Tool hoặc Human không? |
| Response quality | Câu trả lời có đúng, rõ và tự nhiên không? |
| Safety | Có claim sai, lời khuyên nguy hiểm hoặc lộ dữ liệu không? |
| Conversation | Có dùng state và chọn Next Best Action đúng không? |
| Business readiness | Có giảm công sức khách và hỗ trợ giao dịch không? |

# Test Suites

```text
smoke/
  → Các câu P1 bắt buộc phải chạy sau mỗi release.

regression/
  → Các lỗi đã từng xảy ra và behavior đã khóa.

retrieval/
  → Kiểm tra unit được lấy và thứ tự xếp hạng.

routing/
  → Tool/Human/Knowledge decisions.

safety/
  → Medical claims, complaint, PII, tool failure.

conversation/
  → Multi-turn state, correction, purchase readiness.
```

# Severity Levels

| Severity | Meaning | Release effect |
|---|---|---|
| `S0` | Sai an toàn nghiêm trọng, lộ dữ liệu, tạo giao dịch sai | Block release |
| `S1` | Hallucinated fact, giá/tồn kho sai, bỏ qua handoff bắt buộc | Block release |
| `S2` | Retrieval/routing sai làm câu trả lời kém đáng kể | Fix before production when P1 path |
| `S3` | Tone, độ dài hoặc wording chưa tối ưu | May release with tracked issue |

# Core Metrics

## Retrieval

- Hit@K cho Knowledge Unit đúng.
- MRR/NDCG nếu có reranking.
- Tỷ lệ retrieve nguồn không approved: phải bằng 0 trong production.

## Routing

- Tool routing accuracy.
- Human handoff recall cho safety/complaint.
- Static-answer leakage cho câu hỏi động: phải bằng 0 ở test P1.

## Response

- Factual correctness.
- Groundedness/provenance coverage.
- Intent completion.
- Next Best Action correctness.
- Response conciseness và tone compliance.

# Release Gates

Một release chỉ được thông qua khi:

- Không có lỗi S0/S1 còn mở.
- Tất cả smoke tests P1 đạt.
- Không có draft/superseded asset trong production provenance.
- Các Tool-required test không trả dữ liệu tĩnh.
- Regression suite không giảm dưới baseline đã khóa.
- PO/QA chấp nhận các ngoại lệ S2/S3 còn lại.

# Evaluation Modes

## Deterministic checks

Schema, status/version, source IDs, tool route, prohibited strings và required keywords.

## Human review

Độ tự nhiên, mức hữu ích, tone và judgment trong trường hợp mơ hồ.

## Model-assisted review

Có thể dùng để mở rộng quy mô nhưng không là trọng tài duy nhất cho safety, Product Fact hoặc release gate S0/S1.

# Things to Avoid

- Không đánh giá chỉ bằng cảm giác “nghe hay”.
- Không dùng một điểm tổng duy nhất che lỗi safety.
- Không dùng expected answer cứng từng chữ cho câu trả lời tự nhiên.
- Không benchmark model khi retrieval/context khác nhau mà không ghi nhận.
- Không mở rộng hàng trăm test trước khi P1 smoke suite ổn định.

# Success Criteria

- Có thể chạy một bộ smoke test nhỏ trước mỗi release.
- Mọi lỗi production quan trọng trở thành regression test.
- Báo cáo chỉ rõ lỗi nằm ở source, retrieval, routing hay generation.

# Related Documents

- EV-002 — Test Case Schema
- EV-003 — Retrieval and Routing Evaluation
- EV-004 — Response Quality and Safety Evaluation
- EV-005 — Continuous Learning Loop
