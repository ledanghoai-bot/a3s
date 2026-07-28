# Processing Purpose Registry — Alpha3S

```yaml
document: PROCESSING-PURPOSE-REGISTRY
owner: PO (purpose owner) / Dev (mapping kỹ thuật)
version: 1.0.0
status: living-document
created: 2026-07-28 (I-B M3-S0)
source_of_truth: Scalffold V2.0 §13.4; căn cứ pháp lý: Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 (đã hiệu lực)
rule: không xử lý dữ liệu nếu không có purpose_code hợp lệ; consent tư vấn KHÔNG mặc nhiên bao gồm marketing/UGC/model-training/public content
```

| Code | Mục đích | Trạng thái tại Alpha3S | Data class | Căn cứ/consent | Processor liên quan | Retention ref | Owner |
|---|---|---|---|---|---|---|---|
| `P01_CONSULT` | Tư vấn, trả lời khách | **active** (orchestrator + KB/NLU/LLM) | D1 (D2-possible trong free text) | Thực hiện dịch vụ theo yêu cầu khách; notice đã live (`/legal`) | DeepSeek (VDR-001), Meta/Telegram (kênh) | RET-01/02 | PO |
| `P02_COMMERCE` | Giá, tồn kho, đơn hàng | **active** (tools create_order, M2 inventory) | D0 (giá/kho) + D1 (đơn) | Thực hiện hợp đồng mua bán | — | RET-03 | PO |
| `P03_TRANSACTIONAL` | Xác nhận/thông báo giao dịch | **active** (receipt M1, customer notify M2, dispatcher S5) | D1 | Thực hiện hợp đồng; độc lập P06 | Meta/Telegram | RET-03 | PO |
| `P04_SUPPORT` | CSKH, khiếu nại, recovery | **active** (escalations, handoff Telegram admin) | D1/D2-possible | Thực hiện dịch vụ | Telegram (admin alert) | RET-04 | PO |
| `P05_LIFECYCLE` | First-success, chăm sóc sử dụng | **planned** (Orbit/Replenishment — chưa chạy) | D1/D3 | CẦN consent lifecycle riêng (S3 ledger) | — | TBD | PO |
| `P06_MARKETING` | Marketing/promotion/outbound thương mại | **planned — CHƯA được phép chạy** khi chưa có consent ledger + suppression (S3/S5) | D1 | Consent marketing riêng; opt-out có hiệu lực xuyên adapter | — | TBD | PO |
| `P07_ANALYTICS` | Cải thiện sản phẩm/hành trình | **partial** (metrics vận hành không PII) | D0/D4 hướng tới | Legitimate ops; label không chứa customer data | — | — | PO |
| `P08_CONTENT_INSIGHT` | Insight/content dạng giảm thiểu/khử nhận dạng | **planned** (Insight Zone — Orbit, sau M3) | D4 (qua boundary) | Privacy Transformation Boundary bắt buộc | — | TBD | PO (Orbit) |
| `P09_UGC_PUBLICATION` | Công khai quote/review/UGC | **not-active** | D1→D0 sau permission | Permission tường minh từng item | — | TBD | PO |
| `P10_AI_PROCESSING` | AI/model/vendor được phê duyệt | **active** (chat qua DeepSeek — UC-001) | D1 hiện tại (mục tiêu M4: masked) | AI Use Case Register + Vendor Review; khách đã được disclosure | DeepSeek | RET-02 | PO |
| `P11_LEGAL_RETENTION` | Lưu giữ do luật/tranh chấp | **active** (orders ẩn danh giữ cho kế toán) | D1→ẩn danh | Nghĩa vụ pháp lý; KHÔNG dùng cho marketing | — | RET-03 | PO |

## Enforcement points hiện có / sẽ có

| Điểm | Purpose check | Trạng thái |
|---|---|---|
| Outbound dispatcher (S5) | `check_permission(customer, purpose, channel)` — P03 pass mặc định, P05/P06 fail-closed khi `unavailable` | **S3+S5** |
| Chat trả lời (P01) | theo yêu cầu trực tiếp của khách trong phiên | active (mặc nhiên hợp lệ) |
| Marketing bất kỳ | BẮT BUỘC qua consent ledger S3 | chưa có luồng nào — giữ nguyên |

## Gap / Action

1. Purpose chưa được ghi máy-đọc-được trên từng flow (chỉ ở registry này) → event mới từ S1 mang
   `purpose_code` trong envelope; outbound mang purpose từ S5.
2. P05/P06 bị CHẶN cho tới khi S3 ledger + suppression hoạt động — mọi đề xuất Replenishment
   (Orbit) phải chờ mốc này.
3. Consent capture: Gateway chưa production → Alpha3S capture tạm theo contract §5 spec M3
   (`authority_system`, `authority_revision` monotonic, `synced_at`) — thiết kế S3.
