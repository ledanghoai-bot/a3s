# Alpha3S – 3S Coffee Sales Agent

Agent trả lời tự động cho fanpage **3S Coffee** – "3 Giây Sẵn Sàng".

Cà phê sấy lạnh nguyên chất (Freeze-Dried), phôi Ro-Express R100 (Robanme), 100% Robusta.

## Kiến trúc

```
Messenger ──webhook──▶ FastAPI (app/api/webhook.py)
                          │ enqueue (Redis + arq)
                          ▼
                    Worker (app/workers/tasks.py)
                          │
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
   Orchestrator     RAG (pgvector)    Send API client
   (LLM + tools)    knowledge_chunks  (app/services/messenger.py)
```

## Chạy local

```bash
cp .env.example .env   # điền PAGE_ACCESS_TOKEN, META_APP_SECRET, META_VERIFY_TOKEN
docker compose up --build
```

- API: http://localhost:8000 (health check: `GET /health`)
- Webhook cho Meta: `GET/POST /webhook` (cần HTTPS khi kết nối thật, dùng ngrok/cloudflared khi dev)

## Cấu trúc

- `app/api/webhook.py` – nhận sự kiện Messenger, xác thực chữ ký, đẩy vào queue
- `app/workers/tasks.py` – worker arq xử lý tin nhắn bất đồng bộ
- `app/services/orchestrator.py` – lõi agent (LLM + RAG + tool calling)
- `app/services/messenger.py` – gửi tin qua Send API
- `app/services/rag.py` – truy vấn knowledge base (pgvector)
- `app/prompts/system_prompt.md` – brand voice + quy tắc trả lời
- `data/knowledge/product_profile.md` – dữ liệu nguồn cho RAG
- `migrations/001_init.sql` – schema PostgreSQL + pgvector

Lộ trình chi tiết: xem Issues của project (#1–#9).
