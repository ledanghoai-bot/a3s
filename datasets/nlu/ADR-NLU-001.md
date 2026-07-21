---
id: ADR-NLU-001
title: Separate NLU Routing Data from Knowledge Retrieval
document_type: architecture_decision_record
domain: nlu
owner: Alpha3S
version: 1.0.0
status: approved
approved_by: PO
approved_at: 2026-07-20
created_at: 2026-07-20
last_updated: 2026-07-20
---

# ADR-NLU-001 — Separate NLU Routing Data from Knowledge Retrieval

## Context

Khách hàng có thể diễn đạt cùng một nhu cầu bằng tiếng Việt chuẩn, không dấu, từ viết tắt, tiếng địa phương, teen code hoặc câu thiếu chủ ngữ. Nếu đưa toàn bộ câu mẫu vào Knowledge Base hoặc LLM prompt, context sẽ lớn hơn, retrieval dễ nhiễu và thời gian phản hồi có thể tăng.

## Decision

Alpha3S quản lý Intent & Utterance Library như một dataset NLU độc lập tại `datasets/nlu/`.

NLU chạy trước Retriever/Tool/LLM và chỉ trả về:

- Intent candidate.
- Confidence.
- Entity nhẹ.
- Route hint.

Utterance Library:

- Không embed chung với Product/FAQ Knowledge.
- Không đưa vào LLM context.
- Không trực tiếp tạo câu trả lời cho khách.
- Được compile thành runtime indices khi build.

## Runtime Order

```text
Message
  → Normalize
  → Pattern Fast Path
  → Semantic Router nếu cần
  → Entity Extraction
  → Route Resolution
  → Tool / Knowledge / Playbook / Handoff
  → Minimal Context Builder
  → LLM
```

## Canonical Sources

- `intent-catalog.yaml`: nguồn chuẩn cho intent, entity requirement và route.
- `normalization.yaml`: nguồn chuẩn cho mappings ngôn ngữ.
- `utterances/*.yaml`: dữ liệu huấn luyện/reference.
- `tests/*.yaml`: held-out evaluation, không trộn với training/reference.

## Performance Decision

- Pattern fast path phải chạy trước semantic routing.
- Semantic router không chạy khi pattern đã đạt confidence threshold.
- Tổng NLU overhead mục tiêu p95 không vượt 80 ms.
- Dữ liệu động không được cache trong NLU.

## Consequences

### Positive

- Hiểu tốt hơn cách nói tự nhiên, không dấu và viết tắt.
- Giảm context gửi vào LLM.
- Dễ đo intent accuracy và wrong-route rate.
- Có thể cập nhật ngôn ngữ mà không sửa Product Knowledge.

### Trade-offs

- Cần quản trị taxonomy và held-out test set.
- Cần theo dõi intent drift.
- Cần kiểm soát duplicate và train/test leakage.

## Guardrails

- Confidence thấp phải clarify hoặc fallback; không ép route.
- Intent sức khỏe, hoàn tiền, đơn hàng và quyền riêng tư dùng threshold cao.
- Tool intent không được fallback sang Knowledge để tạo dữ liệu động.
- Original message phải được bảo toàn để audit theo privacy policy.

## References

- `NLU-INTEGRATION-GUIDE.md`
- `EV-002-TEST-CASE-SCHEMA.md`
- `EV-003-RETRIEVAL-AND-ROUTING-EVALUATION.md`
- `PA-002-CONTEXT-SELECTION-AND-BUDGET.md`
- `PA-003-SOURCE-ORDERING-AND-CONFLICT-RESOLUTION.md`
