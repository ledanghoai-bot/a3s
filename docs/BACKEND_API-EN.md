# Alpha3S — Backend API Documentation (FastAPI)

> Describes the entire FastAPI backend: the Messenger webhook, the AI
> processing flow (orchestrator + tool calling), the services, and the
> internal APIs (`/admin/*`, `/dashboard/*`). Use this when deploying,
> debugging, or continuing development.
> Last updated: 7/17 (after Batch 4 — real auth, closing out issue #8).

## Quick index
- [Architecture overview](#architecture-overview)
- [Processing flow for 1 Messenger message](#processing-flow-for-1-messenger-message)
- [orchestrator.py — the AI brain](#orchestratorpy--the-ai-brain)
- [4 Tools (function calling)](#4-tools-function-calling)
- [Human handoff](#human-handoff)
- [`/webhook` router](#webhook-router)
- [`/admin` router](#admin-router)
- [`/dashboard` router](#dashboard-router)
- [`/dashboard/auth` router — authentication](#dashboardauth-router--authentication)
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

**Core principle:** `orchestrator.handle_message(sender_id, text, channel="messenger") -> str`
is the **single function** that contains all the AI logic — it works the same
across channels (Messenger, Telegram customer, or in the future Zalo/a web
widget). Each caller passes its `channel` **explicitly** (not inferred from a
`sender_id` prefix); it only drives the automated-assistant disclosure level
(Messenger = mandatory, others = recommended — see `DISCLOSURE_REQUIRED_CHANNELS`
and `docs/META-APP-REVIEW-EN.md` §7). Adding a new channel only requires writing
the receive/send-message layer and passing a `channel` string.

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
6. **Injects the SKU list ("Layer 1", added 7/17)**: `products.get_sku_summary_text()`
   — a single line listing every current SKU, injected into the system
   prompt on **EVERY turn** (not via tool_calls) — independent of whether the
   LLM decides to call `search_products` on its own. Includes explicit
   instructions that "this list is complete, do not invent extra SKUs" and
   the "priority order when there's a conflict" (live data always beats
   conversation history, including the bot's own earlier replies). See the
   "Layer 2" note under `products.py` below for the richer (RAG) source.
7. **Calls the LLM** (DeepSeek, OpenAI-compatible) with
   `tools=TOOL_DEFINITIONS`, `tool_choice="auto"`, **`temperature=0.1`**
   (lowered from 0.3 on 7/17 — prioritizing sticking to the supplied data
   over "creativity"). Loops up to `MAX_TOOL_ITERATIONS=4` if the model calls
   multiple tools in a row (to avoid an infinite hang).
8. **Strips markdown** as a safety net (Messenger doesn't render `**`, `#`,
   `` ` ``).
9. **Saves history** — Redis (short-term context) + Postgres `messages`
   (long-term, for the dashboard).

---

## 4 Tools (function calling)

Full definitions in `app/services/tools.py:TOOL_DEFINITIONS`. **`psid` is NOT
part of the schema exposed to the LLM** — `orchestrator.py` injects it
automatically at execution time (to prevent the model from inventing/mixing
up the sender).

| Tool | Parameters the LLM provides | Notes |
|---|---|---|
| `search_products` | `query` (optional) | Returns products + price tiers **straight from the DB**, not hardcoded in the prompt. Since 7/17, each product also includes `price_vnd_default` (the base retail price, used as a fallback when no tier matches) and a `note` explicitly stating this is the complete list (fixes a bug where the bot denied/invented SKUs). Since 7/23 (PO decision), also includes `serving_info` — per-cup price conversion computed from `products.net_weight_g` + `products.serving_size_g` (migration 012): `servings_per_unit_approx`, `price_per_serving_vnd_approx` (retail) + `price_per_serving_by_tier`; only returned when the product has serving data (NULL → field omitted, the bot must not invent cup counts) |
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

Protected by `require_staff_session` (`app/api/auth.py`) — the standard
`Authorization: Bearer <token>` header, shared with the `/dashboard` router.
Before Batch 4 this used a static `X-Admin-Token` — fully replaced (see
`docs/DASHBOARD-EN.md`).

---

## `/dashboard` router

File: `app/api/dashboard.py` — the API for the Next.js dashboard (issue #8).
See the full breakdown in **`docs/DASHBOARD-EN.md`** (every endpoint mapped
to the exact button/screen it belongs to).

---

## `/dashboard/auth` router — Authentication

File: `app/api/auth_router.py` (Batch 4, 7/17) — **UNLIKE** the `/dashboard`
router, it does **not** apply a dependency at the router level, since
`/login` must be callable BEFORE a token exists. Each route declares its own
`Depends(require_staff_session)` (except `/login`).

| Method | Path | Description |
|---|---|---|
| POST | `/dashboard/auth/login` | `{username, password}` → session token, NO token required |
| POST | `/dashboard/auth/logout` | Deletes exactly the current session |
| GET | `/dashboard/auth/me` | Info about the currently logged-in staff member |
| GET/POST | `/dashboard/auth/staff` | List / create staff accounts |
| PATCH | `/dashboard/auth/staff/{id}` | Deactivate/reactivate |

Full logic in `app/services/auth_service.py`:
- Password hashing: `hashlib.pbkdf2_hmac("sha256", ..., 200_000)` + a
  per-user salt — **no bcrypt/passlib** (to avoid adding a new dependency to
  `requirements.txt`, which would require rebuilding the `api` Docker image).
- Session token: `secrets.token_urlsafe(32)`, stored in the `staff_sessions`
  table, 7-day TTL — **no JWT** (avoids adding `PyJWT`, simpler to revoke).
- `authenticate()` doesn't distinguish "wrong username" from "wrong password"
  in the error message (avoids leaking which accounts exist).

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
| `products.py` (Batch 2, 7/17) | Product/price-tier CRUD (dashboard) + `get_sku_summary_text()` ("Layer 1") + auto-syncs RAG whenever `description` is edited ("Layer 2") |
| `knowledge_entries.py` (Batch 2, 7/17) | FAQ CRUD (dashboard) — computes the embedding and writes/deletes `knowledge_chunks` immediately, no need to run `ingest.py` |
| `metrics.py` (Batch 3, 7/17) | Metrics/Analytics for `/metrics` — messages/day, chat-to-order rate, top unanswered questions — no new DB table |
| `auth_service.py` (Batch 4, 7/17) | Password hashing (PBKDF2), `authenticate()`, session tokens (`create_session`/`validate_session`/`delete_session`), `staff_users` CRUD |
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
- `clear_chat_history.py` (Batch 2, 7/17) — clears Redis chat history (all
  conversations, or a single sender_id) — a dev-only tool, used to get a
  clean test after fixing bot behavior when an existing conversation still
  contains an earlier wrong reply — **do not use in production**
- `create_staff_user.py` (Batch 4, 7/17) — creates the **first** staff
  account (bootstrap, run once — nobody can log in yet to create one
  themselves via `/staff`, chicken-and-egg). From the 2nd account onward,
  create them directly via the dashboard.
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
| Human handoff | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID` |
| Dashboard | `DASHBOARD_CORS_ORIGINS` |
| NLU layer (#12) | `ENABLE_NLU_ROUTER` (toggles the whole NLU hint layer — currently `true`), `ENABLE_SEMANTIC_ROUTER` (semantic tier using mpnet, ~1.1GB RAM — **`false` per PO decision 23/7**, see `docs/NLU_LAYER-EN.md` + `docs/KB_NLU_RESOURCE_ASSESSMENT-EN.md`) |
| ⚠️ Legacy (no longer used) | `ADMIN_API_TOKEN` — replaced by `staff_users`/`staff_sessions` since Batch 4 |
| Fallback channel | `TELEGRAM_CUSTOMER_BOT_TOKEN` |

> **Orchestrator knowledge source (changed 23/7):** the "Reference information"
> section of the system prompt now comes from **Knowledge Base V2**
> (`kb_retrieval.search_kb`, domains brand/product/faq) instead of the legacy RAG
> (`rag.search_knowledge`/`knowledge_chunks`); the legacy RAG remains only as an
> except-branch fallback when KB V2 errors out.

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
- **Turn-to-turn LLM reliability** — DeepSeek sometimes contradicts its own
  earlier reply within the same conversation (e.g. confirming a SKU exists,
  then later denying it) — mitigated via `temperature=0.1` + injecting live
  data every turn, but **not eliminated entirely** — an inherent model
  limitation, see the "Fix bug 7/17" section of `ISSUES-VI.md` for the full
  story.
- **No role-based permissions yet** — any logged-in staff can call every
  `/dashboard/auth/staff/*` endpoint (create/deactivate other accounts) —
  fine for the current small-team scale (Batch 4, 7/17).

See the full development history + technical decisions in `ISSUES-VI.md`
(Vietnamese) / `ISSUES-EN.md` (English).
