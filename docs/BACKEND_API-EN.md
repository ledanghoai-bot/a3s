# Alpha3S — Backend API Documentation (FastAPI)

> Describes the entire FastAPI backend: the Messenger webhook, the AI
> processing flow (orchestrator + tool calling), the services, and the
> internal APIs (`/admin/*`, `/dashboard/*`). Use this when deploying,
> debugging, or continuing development.
> Last updated: 7/16.

## Quick index
- [Architecture overview](#architecture-overview)
- [Processing flow for 1 Messenger message](#processing-flow-for-1-messenger-message)
- [orchestrator.py — the AI brain](#orchestratorpy--the-ai-brain)
- [4 Tools (function calling)](#4-tools-function-calling)
- [Human handoff](#human-handoff)
- [`/webhook` router](#webhook-router)
- [`/admin` router](#admin-router)
- [`/dashboard` router](#dashboard-router)
- [Service list (app/services/)](#service-list-appservices)
- [Worker list (app/workers/)](#worker-list-appworkers)
- [Full environment variable list](#full-environment-variable-list)
- [Known limitations](#known-limitations)

---

## Architecture overview

```
Messenger/Telegram customer
        │
        ▼
  webhook.py (validates + enqueues only, returns 200 immediately)
        │  (Redis queue, arq)
        ▼
  tasks.py (worker) ──── telegram_customer_listener.py (fallback channel)
        │                         │
        └────────┬────────────────┘
                  ▼
        orchestrator.py (handle_message)
        ├── RAG (rag.py + knowledge_chunks)
        ├── Tool calling (tools.py: search_products, check_stock,
        │                 create_order, escalate_to_human)
        ├── Agent notes injection (conversation_log.py)
        └── Human handoff check (handoff.py)
                  │
                  ▼
        Postgres (messages, orders, price_overrides...) + Redis (24h context)
```

**Core principle:** `orchestrator.handle_message(sender_id, text) -> str` is
the **single function** that contains all the AI logic — it is completely
agnostic to which channel called it (Messenger, Telegram customer, or in the
future Zalo/a web widget). Adding a new channel only requires writing the
receive/send-message layer, reusing this exact function unchanged.

No SQLAlchemy ORM is used — every service uses **plain asyncpg** (a
convention established in `app/services/rag.py`, the first service written in
this style).

---

## Processing flow for 1 Messenger message

1. **`POST /webhook`** (`app/api/webhook.py`) — verifies the
   `X-Hub-Signature-256` signature (HMAC with `META_APP_SECRET`), enqueues a
   `process_message` job into Redis (via `arq`), and returns `200`
   immediately. **No AI processing happens inside the webhook request** — to
   avoid Meta timeouts/retries causing duplicates.
2. **`tasks.py` (arq worker)** picks up the job:
   - If it's an **echo** (a message the Page sent, echoed back by Meta) AND
     the conversation is currently `bot_paused=TRUE` → it's logged into
     `messages` with `role='agent'` (capturing a real message typed by staff
     through the Messenger Inbox — the "timetrap" mechanism, see
     `docs/DATABASE-EN.md`).
   - If it's a regular customer message AND the conversation is currently
     `bot_paused=TRUE` → it's only logged (`role='customer'`), the AI is not
     called.
   - Otherwise → calls `orchestrator.handle_message()`, sends the reply via
     `messenger.send_text()`.

---

## `orchestrator.py` — the AI brain

The function `handle_message(sender_id: str, text: str) -> str`, steps:

1. **`ensure_conversation()`** — guarantees `customers`/`conversations`
   records exist for this `sender_id` (Postgres, not Redis).
2. **Deterministic safety net** — if the message matches
   `handoff.wants_human()` (regex detecting "talk to a human"...), it
   escalates **immediately, without going through the LLM** — replying with a
   fixed confirmation message, not dependent on the LLM remembering to call
   the tool.
3. **Fetches history** from Redis (`chat:{sender_id}`, 24h TTL, up to
   `MAX_HISTORY=10` turns) + **customer profile** (Messenger Graph API —
   skipped for non-Messenger channels, see `docs/TELEGRAM_BOT-EN.md`).
4. **RAG**: `search_knowledge()` retrieves the top-4 relevant chunks from
   `knowledge_chunks` (static product knowledge — brewing method, flavor
   notes... **NOT used for price/stock/orders**, that goes through tools).
5. **Injects agent notes**: `conversation_log.get_recent_agent_messages()` —
   fetches up to 10 of the most recent staff notes/messages, injects them
   into the system prompt. **Not filtered by `handled`** — the bot must
   always know the full agreement whether or not the dashboard has marked it
   as "handled" yet.
6. **Calls the LLM** (DeepSeek, OpenAI-compatible) with
   `tools=TOOL_DEFINITIONS`, `tool_choice="auto"`. Loops up to
   `MAX_TOOL_ITERATIONS=4` if the model calls multiple tools in a row (to
   avoid an infinite hang).
7. **Strips markdown** as a safety net (Messenger doesn't render `**`, `#`,
   `` ` ``).
8. **Saves history** — Redis (short-term context) + Postgres `messages`
   (long-term, for the dashboard).

---

## 4 Tools (function calling)

Full definitions in `app/services/tools.py:TOOL_DEFINITIONS`. **`psid` is NOT
part of the schema exposed to the LLM** — `orchestrator.py` injects it
automatically at execution time (to prevent the model from inventing/mixing
up the sender).

| Tool | Parameters the LLM provides | Notes |
|---|---|---|
| `search_products` | `query` (optional) | Returns products + price tiers **straight from the DB**, not hardcoded in the prompt |
| `check_stock` | `sku`, `quantity` | |
| `create_order` | `customer_name`, `phone`, `address`, `sku`, `quantity` | Validates the phone number (VN regex), blocks `quantity > 100` **unless** a `price_overrides` record exactly matches (staff-approved via `/approve`). Uses a `FOR UPDATE` transaction to avoid race conditions when decrementing stock. |
| `escalate_to_human` | `reason` | Sets `bot_paused=TRUE`, logs to `escalations`, sends a Telegram notification to admin (with a Resume button) |

**The price/quantity limit (`MAX_AUTO_QUANTITY=100`)** is the key safety
mechanism: the LLM can never "grant itself" permission beyond this limit —
it can only be used when a `price_overrides` record exists, created by
**real staff** via the Telegram `/approve` command (there is no path for the
LLM to write to that table itself).

---

## Human handoff

3 ways a conversation switches to `bot_paused=TRUE`:
1. **The LLM calls it itself** — `escalate_to_human` (complaints,
   out-of-scope questions, orders >100 jars with no approval...).
2. **Deterministic** — the customer types an exact "talk to a human" phrase
   (see `handoff.wants_human`), escalating immediately without going through
   the LLM.
3. **Staff clicks it manually** — "Take over" on the dashboard
   (`handoff.pause_bot()`).

**Resuming the bot** (`bot_paused=FALSE`) via 3 channels: the dashboard,
`/admin/ui`, or the Telegram `/resume` command — all call the shared
`handoff.resume_bot()`.

---

## `/webhook` router

File: `app/api/webhook.py`

| Method | Path | Description |
|---|---|---|
| GET | `/webhook` | Meta's registration verification (echoes `hub.challenge` if `hub.verify_token` matches `META_VERIFY_TOKEN`) |
| POST | `/webhook` | Receives Messenger events, verifies the signature, enqueues a job, returns 200 immediately |

---

## `/admin` router

File: `app/api/admin.py` — the **original internal API** (issue #7), built
before the full dashboard (issue #8) existed. Still used in parallel, not
fully replaced.

| Method | Path | Description |
|---|---|---|
| POST | `/admin/conversations/{psid}/resume` | Resume the bot |
| GET | `/admin/conversations/paused` | List conversations currently waiting on staff |
| GET | `/admin/ui` | A simple HTML page (not Next.js) — view the list + resume with 1 click, used when it's not convenient to open the full dashboard |

Protected by the `X-Admin-Token` header (dependency `require_admin_token` in
`app/api/auth.py`, shared with the `/dashboard` router).

---

## `/dashboard` router

File: `app/api/dashboard.py` — the API for the Next.js dashboard (issue #8).
See the full breakdown in **`docs/DASHBOARD-EN.md`** (every endpoint mapped
to the exact button/screen it belongs to).

---

## Service list (`app/services/`)

| File | Responsibility |
|---|---|
| `orchestrator.py` | The main brain — see the dedicated section above |
| `tools.py` | The 4 function-calling tools — see the dedicated section above |
| `handoff.py` | `bot_paused` check/pause/resume, deterministic `wants_human()`, `resolve_psid()` (short customer code), sending Telegram messages (`notify_admin`), `log_note()` |
| `conversation_log.py` | Writes/reads `messages` + `conversations` in Postgres — the long-term data source (as opposed to Redis, which only keeps 24h) |
| `price_overrides.py` | CRUD for the `price_overrides` table — approving/using/rejecting special prices |
| `orders.py` | `list_orders`, `update_order_status` (validates the status-transition order), `create_order_manual`, `list_products_brief` |
| `rag.py` | `search_knowledge()` — queries `knowledge_chunks` via cosine similarity (pgvector) |
| `embedder.py` | Generates embeddings (model `paraphrase-multilingual-MiniLM-L12-v2`, runs locally) |
| `messenger.py` | `send_text()` — calls the Facebook Send API |
| `messenger_profile.py` | Fetches the customer's name via the Messenger Graph API (cached in Redis for 7 days) |

---

## Worker list (`app/workers/`)

| File | Role | Run with |
|---|---|---|
| `tasks.py` | Processes jobs from the Redis queue (Messenger) | `arq app.workers.tasks.WorkerSettings` |
| `telegram_listener.py` | The admin Telegram bot | `python -m app.workers.telegram_listener` |
| `telegram_customer_listener.py` | The customer Telegram bot | `python -m app.workers.telegram_customer_listener` |

See the full details of both Telegram bots in **`docs/TELEGRAM_BOT-EN.md`**.

Scripts that are not persistent workers (`scripts/`):
- `ingest.py` — loads `data/knowledge/*.md` into `knowledge_chunks`
- `test_scenarios.py` / `retest_scenarios.py` — run test scenarios directly
  through `handle_message()`, no real webhook needed
- `push_issues_to_gitlab.py` — syncs `ISSUES-VI.md` to GitLab Issues

---

## Full environment variable list

See `.env.example` at the repo root. Grouped by purpose:

| Group | Variables |
|---|---|
| Meta/Messenger | `META_VERIFY_TOKEN`, `META_APP_SECRET`, `PAGE_ACCESS_TOKEN` |
| Infrastructure | `DATABASE_URL`, `REDIS_URL` |
| LLM | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` |
| Embedding | `EMBEDDING_MODEL`, `EMBEDDING_DIM` |
| Human handoff | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`, `ADMIN_API_TOKEN` |
| Dashboard | `DASHBOARD_CORS_ORIGINS` |
| Fallback channel | `TELEGRAM_CUSTOMER_BOT_TOKEN` |

---

## Known limitations

- **No ORM is used** — `app/db.py` (the SQLAlchemy engine) exists in the
  code but **is not used anywhere**, every service opens its own separate
  `asyncpg` connection (no connection pooling) — a leftover technical debt
  item from #2/#3/#4, not yet fixed.
- **`embed()` (the embedding model) runs synchronously, CPU-bound** inside an
  async function — it can block the worker's event loop when multiple
  customers ask questions at once — not yet offloaded to a thread pool.
- **No deduplication by `mid`** — Meta may send a duplicate webhook event,
  there is no anti-duplicate mechanism yet, which could produce 2 replies for
  1 message under flaky network conditions.
- **CI/CD + production deployment (#9)** not yet done — currently only runs
  via Docker Compose on a dev machine, no HTTPS, backups, or alerting yet.

See the full development history + technical decisions in `ISSUES-VI.md`
(Vietnamese) / `ISSUES-EN.md` (English).
