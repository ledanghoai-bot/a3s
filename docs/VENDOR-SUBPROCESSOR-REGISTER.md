# Vendor / Subprocessor Register — Alpha3S

```yaml
document: VENDOR-SUBPROCESSOR-REGISTER
owner: PO (quyết định vendor) / Dev (facts kỹ thuật)
version: 1.0.0
status: living-document
created: 2026-07-28 (I-B M3-S0)
source_of_truth: Scalffold V2.0 §13.10; luật 91/2025/QH15 (cross-border); code thực tại base 9b49628
rule: "API key không phải là approval xử lý dữ liệu" — mọi vendor chạm personal data phải có entry ở đây TRƯỚC khi production
```

## VDR-001 — DeepSeek (LLM provider) — ĐANG DÙNG PRODUCTION

| Mục | Nội dung |
|---|---|
| Vai trò | **Processor** (xử lý nội dung chat để sinh trả lời) |
| Tích hợp | `app/services/orchestrator.py` → `https://api.deepseek.com`, model `deepseek-v4-flash` (config.py:35-36), OpenAI-compatible API |
| Data vào | System prompt + **raw message khách + toàn bộ history phiên (~24h)** + KB context + agent notes. Class: **D1, D2-possible** (free text). Với tool-calling `create_order`: model nhận và trả **tên/SĐT/địa chỉ trong tool args** |
| Data ra | Reply text, tool_calls. Class D1 |
| Region/lưu trữ | Theo privacy policy chính thức (bản cập nhật **2026-02-10**): "directly collect, process and store your Personal Data in **People's Republic of China**" |
| Retention phía vendor | "as long as necessary to provide our Services" — KHÔNG có cam kết thời hạn cụ thể cho API input |
| Training | Policy ghi user có "right to **opt-out** of using your Personal Data for training"; **default cho API KHÔNG được nêu tường minh trong policy** (nguồn thứ cấp nói paid API không train mặc định từ 3/2026 — CHƯA XÁC MINH chính thức) |
| Subprocessor | "Service providers access data only in the course of performing their duties" — danh sách không công bố |
| Cross-border (91/2025/QH15) | **CÓ chuyển dữ liệu cá nhân ra nước ngoài (VN → TQ)** → thuộc phạm vi đánh giá tác động chuyển dữ liệu xuyên biên giới. Hồ sơ đánh giá: CHƯA CÓ — gap pháp lý cần PO/legal xử lý |
| Disclosure cho khách | ĐÃ live: trang privacy (`app/api/legal.py`) nêu rõ "nội dung tin nhắn được gửi tới nhà cung cấp mô hình ngôn ngữ (DeepSeek)" |
| Deletion khi chấm dứt | Không có API deletion cho dữ liệu đã gửi — ghi nhận trong Deletion Propagation Map (vendor copy = best-effort opt-out/contact) |
| Kết luận review | **Chấp nhận có điều kiện cho hiện trạng** (đã disclosure, phục vụ P01/P10). **Hành vi cần thay đổi → M4**: masked input (không gửi raw PII/tool-args PII), cấu trúc lại để "task không cần identity thì không gửi PII" (§13.8). Hành động PO/legal: (a) xác minh chính thức training-default cho API + thực hiện opt-out; (b) lập hồ sơ cross-border theo 91/2025/QH15; (c) đánh giá lại khi đổi model/provider |

## VDR-002 — Meta Platforms (Messenger) — ĐANG DÙNG PRODUCTION

| Mục | Nội dung |
|---|---|
| Vai trò | Kênh nhắn tin (independent controller cho nền tảng của họ) + Graph API lấy tên profile |
| Data | Toàn bộ hội thoại đi qua hạ tầng Meta (bản chất kênh); app lấy `first_name,last_name` qua Graph API (cache Redis 7 ngày) |
| Disclosure | ĐÃ live trong privacy notice (dẫn link chính sách Meta) |
| Nghĩa vụ đặc thù | Meta Data Deletion Callback đã có (self-service deletion + status URL — `data_deletion.py`) |
| Action | Không có gap mới trong M3; webhook cutover VPS vẫn là việc #9 |

## VDR-003 — Telegram (bot admin + bot khách) — ĐANG DÙNG

| Mục | Nội dung |
|---|---|
| Vai trò | Kênh (customer bot) + kênh vận hành nội bộ (admin alert) |
| Data | Hội thoại khách kênh Telegram; **admin alert hiện chứa tên/SĐT/địa chỉ + trích 300 ký tự tin nhắn** (`handoff.py:240-307`) |
| Gap | Alert vận hành mang PII sang chat admin — S5 template minimization (chỉ refs + link dashboard) — MED |
| Action | S5 dispatcher: template version hóa, giảm PII trong alert |

## VDR-004 — VPS provider (hosting production, VN)

| Mục | Nội dung |
|---|---|
| Vai trò | Infrastructure (lưu trữ toàn bộ DB) |
| Region | Việt Nam (đúng tuyên bố trong privacy notice "máy chủ đặt tại Việt Nam") |
| Action | Backup pg_dump cần expiry policy (Retention Schedule RET-06) |

## VDR-005 — GitHub (code hosting + CI)

| Vai trò | Code + CI. **Không chứa customer data**; cấm production data trong test/fixture (Directive §9) |
| Action | Giữ nguyên tắc synthetic fixtures |

## VDR-006 — Zalo ZNS — CHƯA TÍCH HỢP

| Trạng thái | Interface/stub only trong M3-S5. **Production integration BỊ CHẶN** cho tới khi OA duyệt + Vendor Review riêng hoàn tất (spec §4.2) |

## Embedding models (KHÔNG phải vendor — chạy local)

`app/services/embedder.py` (MiniLM-L12-v2, KB) + `app/services/nlu/nlu_embedder.py` (mpnet-base-v2, NLU)
— sentence-transformers chạy trong container, **không gửi dữ liệu ra ngoài**. Không cần vendor entry;
ghi để tránh hiểu nhầm.

## Tổng hợp gap

| # | Gap | Owner | Deadline đề xuất |
|---|---|---|---|
| 1 | Hồ sơ cross-border DeepSeek theo 91/2025/QH15 chưa có | PO/legal | trước khi M4 canary (hoặc sớm hơn theo legal) |
| 2 | Training-default API DeepSeek chưa xác minh chính thức + chưa thực hiện opt-out | PO | cùng #1 |
| 3 | Telegram admin alert chứa PII | Dev | **M3-S5** |
| 4 | Zalo ZNS vendor review | PO | khi OA sẵn sàng |
