# Lớp NLU (#12) — Tài liệu as-built

> Mô tả Lớp NLU **như đang chạy thật** trong production (cập nhật 23/7/2026, sau
> quyết định PO chop Semantic Router). Thiết kế gốc theo `NLU-INTEGRATION-GUIDE.md`
> của team Knowledge (10 bước); tài liệu này ghi lại phần ĐÃ TRIỂN KHAI, các quyết
> định lệch khỏi guide và lý do. Trạng thái/lịch sử từng đợt: xem `ISSUES-VI.md`
> mục #12 và các Bat 1-8.

## 1. Vai trò trong hệ thống — ranh giới trách nhiệm

NLU **không trả lời khách và không gọi tool**. Nó chỉ sinh một đoạn **hint** bơm
thêm vào system prompt; `orchestrator.py` (LLM DeepSeek) vẫn toàn quyền quyết định.
Toàn bộ đường NLU bọc try/except — lỗi ở bất kỳ đâu trả về chuỗi rỗng, **không bao
giờ** làm vỡ luồng trả lời chính.

```
Tin nhắn khách
   │
   ▼
orchestrator.handle_message()
   │  (ENABLE_NLU_ROUTER=true)
   ▼
nlu_hint.get_nlu_hint(message, sender_id)
   │
   ├─ 0. Cache (Redis, TTL 1h, chỉ kết quả "accept")
   ├─ 1. Pattern Router  ── khớp → hint intent (+ KB V2 nếu type=knowledge)
   ├─ 2. (Semantic Router — ĐANG TẮT, xem §4)
   ├─ 3. Context-aware Resolution — câu nối tiếp ngắn → hint ngữ cảnh trước đó
   └─ 4. Fallback knowledge hint — search_kb() MiniLM, lọc cosine ≤ 0.55
   │
   ▼ (chuỗi hint hoặc "")
system prompt += "## Goi y tu he thong phan loai NLU (tham khao, khong bat buoc)"
```

## 2. Bản đồ file

| File | Vai trò |
|---|---|
| `app/services/nlu_hint.py` | Cầu nối duy nhất orchestrator ↔ NLU; cache module-level index; fallback knowledge hint |
| `app/services/nlu/router.py` | Pipeline Pattern → (Semantic); nhận `semantic_index=None` khi tầng semantic tắt |
| `app/services/nlu/pattern_router.py` | Exact match + token overlap (min_overlap 0.6) trên utterance library đã normalize |
| `app/services/nlu/high_precision_rules.py` | 25 rule RTE-001..025 từ `routing-rules.yaml`, ưu tiên theo `priority`, hỗ trợ điều kiện entity |
| `app/services/nlu/entity_extraction.py` | Regex/từ khóa: quantity, unit, order_id, payment_method, health_context, temperature, location (gazetteer 34 địa danh), product (biến thể kích thước) |
| `app/services/nlu/normalizer.py` | Khôi phục dấu/viết tắt theo `normalization.yaml` + protected phrases |
| `app/services/nlu/semantic_router.py` | Tầng fallback dùng mpnet — **đang tắt**, code giữ nguyên |
| `app/services/nlu/nlu_embedder.py` | Model mpnet riêng cho NLU — chỉ load khi `ENABLE_SEMANTIC_ROUTER=true` |
| `app/services/nlu/route_resolution.py` | intent → hành động gợi ý (tool / knowledge / handoff) theo `intent-catalog.yaml` |
| `app/services/nlu/context_state.py` | Redis lưu intent đã xác nhận, phục vụ câu nối tiếp (Bước 5) |
| `app/services/nlu/cache.py` | Cache normalized query → decision (chỉ `accept`), TTL 1h |
| `app/services/nlu/loader.py` | Đọc datasets/nlu/*.yaml + utterances |
| `datasets/nlu/` | Dữ liệu team Knowledge: 380 utterance, 30 intent, 25 rule, normalization, protected phrases |
| `datasets/tests/` | 150 test held-out (intent-routing-tests) |

## 3. Cấu hình (.env)

| Biến | Hiện tại | Ý nghĩa |
|---|---|---|
| `ENABLE_NLU_ROUTER` | `true` | Bật/tắt TOÀN BỘ lớp NLU (tắt = bot chạy như trước #12) |
| `ENABLE_SEMANTIC_ROUTER` | `false` | Tầng semantic mpnet. **Tắt theo quyết định PO 23/7** — khi tắt, mpnet không bao giờ được load (worker nhẹ đi ~1,1 GB); bật lại nếu quantize model hoặc VPS dư RAM |

## 4. Trạng thái từng tầng + số đo (150 test held-out)

| Tầng | Trạng thái | Số đo |
|---|---|---|
| Pattern Router (exact + token overlap) | ✅ Chạy | Phủ 40% số câu, **93,3-94,6% đúng trong phạm vi phủ** |
| High-precision rules + Entity | ✅ Chạy | Nằm trong số Pattern; RTE-006/008/009 đã mở khóa nhờ entity |
| Semantic Router (mpnet) | ⛔ **Tắt** (PO 23/7) | Khi còn bật: 71,3% trên 60% câu fallback; hầu hết trả `context_check` nên **vốn không sinh hint** — chop gần như không đổi hành vi bot |
| Cache (Bước 10) | ✅ Chạy | TTL 1h, chỉ cache `accept` |
| Context-aware (Bước 5) | ✅ Chạy | Câu nối tiếp ngắn → hint chủ đề gần nhất |
| Fallback knowledge hint | ✅ Chạy (mới 23/7) | search_kb MiniLM, top_k=4, cosine ≤ 0.55 — ngưỡng chọn từ số đo thật (liên quan 0.35-0.53, không liên quan 0.53-0.73) |
| Combined (khi semantic còn bật) | tham chiếu | 80,7% (121/150) — mốc trước chop |

**Vì sao chop semantic + vì sao không mất nhiều:** xem phân tích đầy đủ trong
`KB_NLU_RESOURCE_ASSESSMENT-VI.md` (PA2-5a) — tóm tắt: tầng semantic chiếm ~1,1 GB
RAM (model mpnet) nhưng là tầng kém chính xác nhất và hiếm khi đạt ngưỡng `accept`
để sinh hint thật. Fallback search_kb thay thế phần giá trị knowledge của nó với
**0 RAM thêm** (MiniLM vốn đã load cho KB V2).

## 5. Các loại hint bơm vào prompt

1. **Intent hint** (Pattern khớp): tên intent + độ tin cậy + via.
2. **Tool hint** (intent type=tool): "LUÔN gọi tool `<tên>` để trả lời chính xác".
3. **Handoff hint** (intent type=handoff): cân nhắc `escalate_to_human` — kèm nhắc
   TUÂN THỦ thứ tự khiếu nại (hỏi mã đơn trước, trừ khi khách đòi gặp người).
4. **Knowledge hint** (intent type=knowledge): nội dung Knowledge Unit thật từ
   `search_kb()` (domain brand/product/faq, top_k=2).
5. **Context hint**: câu ngắn nối tiếp → nhắc chủ đề gần nhất, không ép buộc.
6. **Fallback knowledge hint**: pattern miss + không phải câu nối tiếp → search_kb
   top_k=4 lọc cosine ≤ 0.55; preamble dặn rõ "chưa chắc chắn — lạc đề thì bỏ qua";
   không tìm thấy → im lặng ("").

## 6. Bài học đắt giá đã nạp vào thiết kế (đọc trước khi sửa)

- **Đồng âm khi bỏ dấu tiếng Việt** — lớp bug tái phát nhiều nhất dự án: "chưa/chua",
  "ly/lý", "hỏng"~"không" (substring), "Ca Mau/Cà Mau" (chiều ngược). Quy tắc: so
  khớp rule/từ khóa GIỮ NGUYÊN DẤU; chỉ bỏ dấu khi bỏ CẢ 2 phía nhất quán (như
  gazetteer location); luôn dùng `\b`; test cả cặp có dấu/không dấu.
- **Câu hoàn toàn không dấu không kích được rule RTE** (`normalize()` chưa khôi phục
  cụm như "co giao toi") — đã đề xuất team Knowledge thêm mapping CẤP CỤM TỪ vào
  normalization.yaml (cụm ≥2 từ tránh được đồng âm từ đơn).
- **Batch encode 1 lần** thay vì vòng lặp từng câu (380 utterance từng mất nhiều
  phút khi gọi lẻ — xem docstring `nlu_embedder.py`).
- **Import torch là trả trước ~300MB RSS** — không import `semantic_router`/
  `sentence_transformers` ở cấp module trong code chạy production; dùng lazy import
  trong nhánh cần (xem `router.py`).
- **Hint chỉ là gợi ý** — mọi chữ trong hint phải dặn "tham khảo, không bắt buộc";
  hint từng xúi LLM nhảy cóc quy trình khiếu nại cho tới khi thêm câu nhắc thứ tự.

## 7. Bộ test & cách chạy

```bash
docker compose exec api python scripts/nlu_pattern_test.py --eval    # pattern-only, 150 held-out
docker compose exec api python scripts/nlu_pattern_test.py "cau hoi"
docker compose exec api python scripts/nlu_entity_test.py --eval     # entity, có cặp dấu/không dấu
docker compose exec api python scripts/nlu_combined_test.py --eval   # cần bật semantic (tải mpnet)
docker compose exec api python scripts/nlu_hint_test.py "cau hoi"    # hint end-to-end như orchestrator thấy
docker compose exec api python scripts/measure_embedding_rss.py      # đo RAM 2 model (A3)
```

## 8. Giới hạn đã biết / việc để sau

- Câu knowledge ngoài phủ pattern phụ thuộc fallback search_kb (ngưỡng 0.55 có ca
  biên: "cho anh 5 hũ" d=0.530 có thể lọt hint FAQ nhẹ — chấp nhận, preamble đỡ).
- `taste_preference`/`brewing_method` chưa có entity extraction (mơ hồ, thiếu dữ liệu).
- Semantic Router tắt — muốn bật lại: quantize mpnet (PA2-5d) rồi
  `ENABLE_SEMANTIC_ROUTER=true`, chạy lại `nlu_combined_test.py --eval` so mốc 80,7%.
- Accuracy tổng khi semantic còn bật dừng ở 80,7% (mục tiêu README ≥95%) — hướng
  tăng: thêm utterance/rule từ team Knowledge (xem `NLU_ACCURACY_IMPROVEMENT_PROPOSAL-VI.md`).
