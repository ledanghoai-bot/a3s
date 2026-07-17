# Alpha3S — Database Documentation

> Full reference for the PostgreSQL (+ pgvector) schema of the 3S Coffee system.
> Use this when deploying, operating, or debugging — think of it as a `/help`
> file for the database.
> Last updated: 7/17 (after migration 009). If you add a new migration,
> remember to update this file too.

## Quick index
- [Data flow overview](#data-flow-overview)
- [Table list](#table-list)
- [Table details](#table-details)
- [Migration history](#migration-history)
- [Common lookup queries](#common-lookup-queries)
- [Important operational notes](#important-operational-notes)

---

## Data flow overview

```
customers (1 customer = 1 psid, regardless of channel)
    │
    ├── conversations (each customer currently keeps 1 "active" session)
    │       │
    │       └── messages (full chat history: customer/bot/staff)
    │
    ├── orders ──── order_items ──── products (+ price_tiers)
    │
    ├── price_overrides (staff-approved special price/quantity via /approve)
    │
    └── escalations (log of the reason for every handoff to staff)

knowledge_chunks — used for RAG, linkage depends on source: static (no FK),
via faq_entries, or via products — see "Table details" below. Never linked
to any customer.
```

**The central key of the whole system is `customers.psid`** — a customer
identifier string, formatted differently depending on the channel:
- Customer via **real Messenger**: Facebook PSID (a long numeric string,
  15-17 digits).
- Customer via **Telegram** (fallback channel): `tg:<telegram_chat_id>`.
- Order created **manually with no associated chat** (`/orders/new` without a
  psid): auto-generates `manual:<short uuid>`.

All business logic code (`orchestrator.py`, `tools.py`, `handoff.py`,
`dashboard.py`...) treats the 3 formats above as equivalent — it does not
distinguish by channel when processing logic, only in the
receive/send-message layer (Messenger webhook vs
`telegram_customer_listener.py`).

---

## Table list

| Table | Role |
|---|---|
| `customers` | Customer info (name/phone/address), keyed by `psid` |
| `conversations` | 1 chat session per customer; holds the `bot_paused` flag (human handoff) |
| `messages` | Full message history (customer/bot/staff) — data source for the dashboard + bot context |
| `products` | Product catalog (multi-SKU, CRUD via dashboard `/products`) |
| `price_tiers` | Quantity-based price tiers, tied to 1 product |
| `orders` | Real orders |
| `order_items` | Line items of each order |
| `knowledge_chunks` | Knowledge for RAG (vector embedding) — covers static content, FAQ, and product descriptions |
| `escalations` | Log of the reason for every escalation to staff |
| `price_overrides` | Staff-approved special price/quantity via the Telegram `/approve` command |
| `faq_entries` | FAQ created via the dashboard (`/faq`) — auto-synced into `knowledge_chunks` |

---

## Table details

### `customers`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | Used as the **"short customer code"** on Telegram (`/note 4 ...` instead of the long PSID) |
| `psid` | TEXT UNIQUE NOT NULL | Customer identifier key — see the 3-format explanation above |
| `name`, `phone`, `address` | TEXT (nullable) | Only populated when a real order goes through (`create_order`/`create_order_manual`) — **NOT** auto-filled just from normal chatting |
| `created_at` | TIMESTAMPTZ | |

### `conversations`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `customer_id` | FK → customers | |
| `bot_paused` | BOOLEAN DEFAULT FALSE | **The single most important flag in the system** — `TRUE` = staff is handling this, the bot stays completely silent (the worker/listener checks this flag before every reply) |
| `staff_action` | TEXT DEFAULT 'moi' | ⚠️ **Legacy column, NO LONGER used in the UI** (migration 005) — used to be a single "Status" column for the whole conversation, later replaced by per-note/per-approval tracking (see `messages.handled` / `price_overrides.status`). Still present in the DB, not dropped, just no longer referenced. |
| `created_at` | TIMESTAMPTZ | |

Simplification: each customer currently keeps only **1 "active" conversation**
(always the latest record by `customer_id`) — splitting into separate
time-based sessions is not yet supported.

### `messages`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `conversation_id` | FK → conversations | |
| `role` | TEXT CHECK IN ('customer','bot','agent') | `customer` = customer typed it; `bot` = AI replied; `agent` = **staff/boss** (explicit note via `/note`, or a real message typed by hand through the Messenger Inbox while `bot_paused=TRUE`, captured via the "timetrap" mechanism — see `app/workers/tasks.py`) |
| `content` | TEXT NOT NULL | |
| `handled` | BOOLEAN DEFAULT FALSE (migration 006) | Only meaningful for `role='agent'` — staff marks it as handled on the dashboard. **NOT filtered on when injected into bot context** (`conversation_log.get_recent_agent_messages`) — the bot must always know the full agreement regardless of whether the dashboard has "tidied up" the display yet. |
| `created_at` | TIMESTAMPTZ | |

### `products`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `sku` | TEXT UNIQUE | **Immutable after creation** (not editable via CRUD) — this is the key tools use for lookup |
| `name`, `description` | TEXT | `description` has, since 7/17, been **automatically used for RAG** (see the `knowledge_chunks` section below) |
| `price_vnd` | INTEGER | Default retail price (fallback if no tier in `price_tiers` matches) |
| `stock` | INTEGER | Inventory — decremented directly every time `create_order`/`create_order_manual` succeeds |

Full CRUD via `/products` (dashboard) except `sku` (immutable). Deleting a
product is **rejected by a foreign-key constraint** if it already has related
orders/price tiers (this is intentional).

### `price_tiers`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `product_id` | FK → products | |
| `min_qty` | INTEGER | Minimum quantity threshold for this price to apply |
| `unit_price_vnd` | INTEGER | |

Current pricing tiers for `3S-100G`: **1-4 jars → 170,000₫** ·
**5-19 jars → 160,000₫** · **20-100 jars → 140,000₫**. Above 100 jars: **no
automatic pricing**, the bot must `escalate_to_human` — unless a matching
`price_overrides` record exists (see below).

### `orders`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `customer_id` | FK → customers | |
| `status` | TEXT DEFAULT 'new', CHECK IN ('new','confirmed','shipped','done','cancelled') (constraint added in migration 003) | Can only move **forward in order** `new → confirmed → shipped → done` (no going back), `cancelled` is allowed from any step **except** `done` — see `app/services/orders.py:validate_transition` |
| `total_vnd` | INTEGER | |
| `shipping_name`, `shipping_phone`, `shipping_address` | TEXT | Snapshot taken at order-creation time (independent of `customers.name/phone/address` — the customer may update their info later, but the old order keeps the exact data at the time it was placed) |
| `created_at` | TIMESTAMPTZ | |

### `order_items`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `order_id` | FK → orders | |
| `product_id` | FK → products | |
| `quantity` | INTEGER | |
| `unit_price_vnd` | INTEGER | Unit price **at the time the order was finalized** (does not auto-update if `price_tiers` changes later) |

### `knowledge_chunks`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `source` | TEXT | `product_profile.md`/`faq.md` (static content) • `dashboard:faq` (from `/faq`) • `dashboard:product` (product description, from `/products`) |
| `content` | TEXT | The chunked text segment |
| `embedding` | `vector(384)` | Model: `paraphrase-multilingual-MiniLM-L12-v2`. HNSW cosine index. |
| `faq_entry_id` | BIGINT FK → faq_entries, `ON DELETE CASCADE` (migration 008) | Only set for chunks from `source='dashboard:faq'` |
| `product_id` | BIGINT FK → products, `ON DELETE CASCADE` (migration 009) | Only set for chunks from `source='dashboard:product'` |
| `created_at` | TIMESTAMPTZ | |

**3 content sources coexist side by side, never overwriting each other:**
1. **Static content** (`product_profile.md`, `faq.md`) — written via
   `scripts/ingest.py`, run manually once, not auto-updated when the `.md`
   files change.
2. **FAQ via dashboard** (`dashboard:faq`) — CRUD via `/faq`
   (`app/services/knowledge_entries.py`), computes the embedding and writes/
   deletes the chunk **immediately** on create/edit/delete, no need to run
   `ingest.py`.
3. **Product description via dashboard** (`dashboard:product`) — CRUD via
   `/products` (`app/services/products.py`), auto-creates/edits/deletes the
   matching chunk whenever a product's `description` is edited — the exact
   same pattern as FAQ.

Populated via `scripts/ingest.py` (source 1 only). **Not linked to any
customer** — this is knowledge shared across every chat (RAG).

### `faq_entries` (migration 008)
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `question`, `answer` | TEXT NOT NULL | |
| `created_at`, `updated_at` | TIMESTAMPTZ | |

The source of truth for dashboard-created FAQ — see the `knowledge_chunks`
section above for details. Editing an FAQ entry **DELETES the old chunk and
CREATES a new one** (does not update the embedding in place), avoiding any
content/embedding mismatch.

### `escalations`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `conversation_id` | FK → conversations | |
| `reason` | TEXT NOT NULL | Reason for the escalation — may come from the LLM deciding to call the tool on its own, from the customer typing an exact "talk to a human" phrase (deterministic branch), or from staff pausing manually from the dashboard |
| `created_at` | TIMESTAMPTZ | |

Logs the history of **every time** `bot_paused` switches to `TRUE` (both
automatic escalation and manual staff pause) — used to review and improve the
prompt later.

### `price_overrides`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `customer_id` | FK → customers | |
| `quantity` | INTEGER NOT NULL | The EXACT approved quantity — `create_order` only applies it when the quantity confirmed by the customer matches **exactly** (no rounding/inference) |
| `unit_price_vnd` | INTEGER NOT NULL | The approved special unit price, overriding the standard `price_tiers` |
| `note` | TEXT | Extra note added at `/approve` time (e.g. delivery conditions) |
| `used` | BOOLEAN DEFAULT FALSE | **The single source of truth** for `create_order` logic — `TRUE` means it **can no longer be reused**, whether because an order was created (`status='used'`) or it was declined (`status='rejected'`) |
| `status` | TEXT DEFAULT 'active', CHECK IN ('active','used','rejected') (migration 007) | Only for **dashboard display labeling** — not the source of truth for business logic (that's the `used` column) |
| `reject_reason` | TEXT (migration 007) | Only populated when `status='rejected'` |
| `created_at` | TIMESTAMPTZ | |

**The single most important safety rule for this table:** it can **ONLY be
written to by a real staff command** (the Telegram admin bot — restricted to
exactly `TELEGRAM_ADMIN_CHAT_ID` — or the dashboard with a token). **The LLM
can never write to it** — this is how the system prevents the AI from
"granting itself" permission to exceed price/quantity limits
(`app/services/tools.py:create_order` only reads this table, never writes to it).

---

## Migration history

| # | File | Content |
|---|---|---|
| 001 | `001_init.sql` | Base schema: customers, conversations, messages, products, orders, order_items, knowledge_chunks, price_tiers + product seed data |
| 002 | `002_add_escalations.sql` | `escalations` table |
| 003 | `003_orders_status_check.sql` | CHECK constraint for `orders.status` |
| 004 | `004_price_overrides.sql` | `price_overrides` table (no `status`/`reject_reason` yet) |
| 005 | `005_staff_action.sql` | `conversations.staff_action` — **legacy, no longer used in the UI** |
| 006 | `006_messages_handled.sql` | `messages.handled` |
| 007 | `007_override_status.sql` | `price_overrides.status` + `reject_reason` |
| 008 | `008_faq_entries.sql` | `faq_entries` table + `knowledge_chunks.faq_entry_id` |
| 009 | `009_product_knowledge.sql` | `knowledge_chunks.product_id` — per-product RAG sync |

**Important deployment note:** `docker-entrypoint-initdb.d` (the `./migrations`
folder mounted into the `db` container) **only runs automatically ONCE, when
a brand-new Postgres volume is created**. If the DB already exists (as it has
throughout this dev process), every migration from 002 onward must be run
**manually**:
```bash
docker compose exec db psql -U alpha3s -d alpha3s -f /docker-entrypoint-initdb.d/00X_file_name.sql
```
When deploying to a **completely fresh** environment (empty Postgres volume),
all 9 files run automatically in filename order — no manual step needed.

---

## Common lookup queries

Connect directly to Postgres:
```bash
docker compose exec db psql -U alpha3s -d alpha3s
```

**View the 5 most recent conversations with their status:**
```sql
SELECT c.id, c.bot_paused, cu.psid, cu.name, cu.phone
FROM conversations c JOIN customers cu ON cu.id = c.customer_id
ORDER BY c.id DESC LIMIT 5;
```

**View the full chat history of 1 customer (by PSID):**
```sql
SELECT m.role, m.content, m.created_at
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
JOIN customers cu ON cu.id = c.customer_id
WHERE cu.psid = '<PSID>'
ORDER BY m.created_at ASC;
```

**Look up the PSID from a short customer code (the ID in `customers`):**
```sql
SELECT psid, name, phone FROM customers WHERE id = <customer_code>;
```

**View the most recent real orders (different from `price_overrides` — see
the note below):**
```sql
SELECT id, status, total_vnd, shipping_name, shipping_phone, created_at
FROM orders ORDER BY id DESC LIMIT 10;
```

**View `/approve` approvals that are still active (not used/not rejected):**
```sql
SELECT po.id, cu.psid, cu.name, po.quantity, po.unit_price_vnd, po.note, po.created_at
FROM price_overrides po JOIN customers cu ON cu.id = po.customer_id
WHERE po.status = 'active' ORDER BY po.created_at DESC;
```

**View internal (agent) notes that haven't been handled yet:**
```sql
SELECT m.id, cu.psid, cu.name, m.content, m.created_at
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
JOIN customers cu ON cu.id = c.customer_id
WHERE m.role = 'agent' AND m.handled = FALSE
ORDER BY m.created_at DESC;
```

**Check current stock:**
```sql
SELECT sku, name, stock FROM products;
```

**View all FAQ entries created via the dashboard:**
```sql
SELECT id, question, answer, updated_at FROM faq_entries ORDER BY id;
```

**Count knowledge_chunks by source (check whether RAG is synced correctly):**
```sql
SELECT source, COUNT(*) FROM knowledge_chunks GROUP BY source;
```

---

## Important operational notes

1. **`price_overrides` is NOT an order** — it's only a "permit" for a special
   price/quantity. Real orders only exist in the `orders` table, created when
   "🤖 Bot creates order" / "👤 Staff creates order" succeeds. Don't confuse
   these two tables when checking "is there an order yet".

2. **Redis (`chat:{sender_id}`) only keeps 24h of chat history** to serve as
   the LLM's context — **it is not a long-term data store**. The dashboard
   always reads from Postgres (`messages`), never from Redis.

3. **`customers.name/phone/address` is only filled in once a real order goes
   through** — a brand-new customer who has chatted a lot but never placed an
   order will have these columns as `NULL`.

4. **`used = TRUE` on `price_overrides` is permanent** (there's no "un-reject"
   or "un-use" mechanism in the UI) — if staff clicks it by mistake, fix it
   manually via SQL:
   ```sql
   UPDATE price_overrides SET used = FALSE, status = 'active', reject_reason = NULL
   WHERE id = <id>;
   ```

5. **No data is ever deleted** — the system is designed around a
   "never delete" principle, only flags/statuses change
   (`handled`, `used`, `status`, `bot_paused`). The full history of every
   note/approval/message is always preserved in the DB for later lookup, even
   when the dashboard "hides" them from the main screen.
