# AI Use Case Register — Alpha3S

```yaml
document: AI-USE-CASE-REGISTER
owner: PO (approval) / Dev (facts)
version: 1.0.0
status: living-document
created: 2026-07-28 (I-B M3-S0)
source_of_truth: Scalffold V2.0 §13.8 (ai_processing_record schema); code thực tại base 9b49628
rule: mọi AI flow production phải có record; review lại khi input/model/provider/purpose thay đổi
```

## UC-001 — Chat tư vấn + chốt đơn qua LLM (HIỆN TRẠNG — ghi nhận TRƯỚC M4)

```yaml
ai_processing_record:
  use_case_id: UC-001
  model_provider: DeepSeek (VDR-001)
  model_name_or_class: deepseek-v4-flash (OpenAI-compatible chat + tool-calling)
  purpose_code: [P01_CONSULT, P02_COMMERCE, P10_AI_PROCESSING]
  input_data_classes: [D1_PERSONAL_BASIC, D2-possible trong free text]  # raw message + history ~24h + KB context + agent notes
  output_data_classes: [D1]  # reply + tool_calls (create_order args chứa tên/SĐT/địa chỉ)
  retention_mode: vendor "as long as necessary" (không cam kết thời hạn) — xem VDR-001
  training_usage_allowed: CHƯA XÁC MINH default cho API; policy có quyền opt-out — action PO tại VDR-001
  region: People's Republic of China (policy 2026-02-10)
  cross_border_status: CÓ (VN→TQ) — hồ sơ 91/2025/QH15 CHƯA CÓ (gap, owner PO/legal)
  human_review: escalation/handoff sang admin (P04); guard chống bịa xác nhận đơn (M1 receipt, false-confirmation-zero)
  risk_class: HIGH (raw PII tới vendor) — mitigations hiện có: disclosure live, history TTL 24h, receipt guard
  approved_at: hiện trạng vận hành từ trước M3 — record này là GHI NHẬN hiện trạng, không phải approval mới
  approved_by: PO (vận hành hiện hành); thay đổi cách thức → gate M4
```

**Hành vi cần thay đổi (trỏ M4 — spec A3S-PHASE1B-M4-SPEC-001):**
1. Masked input: PII detect nội bộ → Slot Store → model chỉ nhận masked message/history.
2. Model không lắp PII vào tool args — trusted code lắp từ Slot Store (chấm dứt việc model
   nhận/trả tên/SĐT/địa chỉ trong `create_order` args).
3. High-risk/low-confidence không qua vendor path.
4. Sau M4 canary: cập nhật record này sang `input_data_classes: masked/minimized` + cập nhật VDR-001.

## UC-002 — KB V2 embedding (local)

```yaml
ai_processing_record:
  use_case_id: UC-002
  model_provider: local (sentence-transformers, không vendor)
  model_name_or_class: paraphrase-multilingual-MiniLM-L12-v2
  purpose_code: [P01_CONSULT]
  input_data_classes: [D0]  # KB product truth + query khách (D1) embed tạm để search
  output_data_classes: [D0 vector KB; query vector không lưu]
  retention_mode: vector KB theo vòng đời KB asset; lineage theo kb_units
  training_usage_allowed: không train
  region: local container (VN)
  cross_border_status: KHÔNG
  human_review: n/a
  risk_class: LOW
```

## UC-003 — NLU router embedding/intent (local)

```yaml
ai_processing_record:
  use_case_id: UC-003
  model_provider: local (sentence-transformers)
  model_name_or_class: paraphrase-multilingual-mpnet-base-v2
  purpose_code: [P01_CONSULT]
  input_data_classes: [D1]  # message khách xử lý in-memory, hint không lưu PII
  output_data_classes: [route hint nội bộ]
  retention_mode: in-memory + cache key dẫn xuất
  training_usage_allowed: không train
  region: local container
  cross_border_status: KHÔNG
  risk_class: LOW
  note: M4 sẽ nâng entity_extraction thành PII detector (shadow trước) — record mới khi M4 mở
```

## Quy tắc chung đang áp (spec §13.8)

- D2 default deny vendor path — hiện chưa có detector (M4); tạm thời mitigate bằng disclosure +
  không dùng free text ngoài mục đích trả lời.
- Không dùng raw conversation fine-tune model.
- Prompt/response log phải redaction — gap hiện tại xem `PHASE1B-M3-PII-LOG-AUDIT-VI.md` → S4.
- Embedding/vector thừa hưởng classification + deletion lineage.
