# Alpha3S — Issue Backlog

> Restored from the GitLab export file (`2026-07-04_13-00-438_ledanghoai-group_alpha3s_export.tar.gz`).
> 9 original issues, only #1 closed on GitLab. The "Actual per code (review 7/14)" column is a
> quick cross-check against the current source in the repo — used to update issue status to match reality.

| # | Issue | GitLab | Actual per code (review 7/14) |
|---|-------|--------|----------------------------------|
| 1 | Messenger webhook + Meta auth | ✅ Closed | ✅ Matches — done |
| 2 | Redis queue + arq worker | ✅ Closed (7/14) | ✅ Core done — retry/dead-letter + load test moved to separate tracking, not blocking closure |
| 3 | PostgreSQL + pgvector: schema/migration/seed | ✅ Closed (7/14) | ✅ Done — schema, HNSW index, product seed all present |
| 4 | RAG pipeline: ingest + search | ✅ Closed (7/14) | ✅ Done — `ingest.py`, `rag.py` work — the 10-sample-question eval moved to separate tracking |
| 5 | System prompt & brand voice | ✅ Closed (7/14) | ✅ 20/20 scenarios pass after prompt fixes — still missing a direct tone review with anh Hoài |
| 6 | Tool calling (search_products/check_stock/create_order/escalate_to_human) | ✅ Closed (7/14) | ✅ 4 tools run for real, end-to-end DB test passes (order + correct stock deduction) |
| 7 | Human handoff: bot_paused | ✅ Closed (7/15) | ✅ End-to-end test passes: escalate → silence → log → resume all correct |
| 8 | Admin dashboard + analytics | 🟡 In progress (7/15) | 🟡 Part 1/3 done: conversations + pause/resume + orders (Next.js, tests pass) |
| 9 | CI/CD + VPS deploy + monitoring | 🔵 Opened | 🟡 Has `.gitlab-ci.yml` (lint + test) but no build/deploy/backup/alert yet |
| 10 | Fallback customer channel (Telegram) | ⚪ Not part of the original backlog | 🟡 Newly added 7/15, arose from the Meta test-account lockout incident |

---

## #1 · [Weeks 1-2] Messenger webhook + Meta auth (echo bot)
**GitLab status:** Closed

**Goal:** The FastAPI webhook works end-to-end with the test fanpage at the echo-bot level.

**Tasks:**
- [x] `GET /webhook`: verifies `hub.verify_token` with Meta
- [x] `POST /webhook`: verifies the `X-Hub-Signature-256` signature (HMAC app secret)
- [x] Send API client replies to messages
- [x] Secrets via env: `PAGE_ACCESS_TOKEN`, `META_APP_SECRET`, `META_VERIFY_TOKEN`
- [x] Connected to the test fanpage (ngrok/cloudflared during dev)

**Definition of done:** Messaging the fanpage receives an echo reply in < 2 seconds.

**Notes:** Confirmed via code (`app/api/webhook.py`) that `hmac.compare_digest` is used correctly.
⚠️ Side finding: the real `.env` file was once committed then deleted (commit `a9db226` → `a9638f9`) —
the secret is still in git history, need to rotate `META_APP_SECRET`/`PAGE_ACCESS_TOKEN` immediately.

---

## #2 · [Weeks 1-2] Redis queue + arq worker (async processing)
**Status:** ✅ Closed (7/14)

**Goal:** The webhook returns 200 to Meta immediately, all AI processing runs in the worker.
Avoids the system stalling when receiving many messages at once.
*(Original technical note: BullMQ is Node.js-only. The Python stack uses Redis + arq.)*

**Tasks:**
- [x] Redis service in docker-compose
- [x] `POST /webhook` only validates + enqueues the `process_message` job, then returns 200
- [x] arq worker: `app/workers/tasks.py`, a reasonable `max_jobs` (~20)
- [ ] Retry policy on Send API/LLM errors; dead-letter log
- [ ] Simple load test: 50 concurrent messages, no message loss

**Definition of done:** Webhook response time < 100ms; no message loss on worker restart.

**Reason for closing despite 2 unchecked items:** the core (enqueue + async worker) already meets the
issue's goal. Retry/dead-letter and the load test were moved into a separate technical item, tracked
under #9 (CI/CD & operations) instead of keeping this issue open indefinitely.

**Outstanding risk to keep an eye on (out of the original issue's scope, but found during a code review):**
- `process_message` doesn't filter `is_echo` → risk of an infinite loop if the Page subscribes to `message_echoes`.
- No dedup by `mid` → Meta may send a duplicate event, which could produce 2 replies for 1 message.

---

## #3 · [Weeks 3-4] PostgreSQL + pgvector: schema, migration, seed
**Status:** ✅ Closed (7/14)

**Goal:** PostgreSQL as the main database, with pgvector installed directly as the Knowledge Base for RAG.

**Tasks:**
- [x] `pgvector/pgvector:pg16` image in docker-compose, `./migrations` mounted into initdb
- [x] Migration `001_init.sql`: `customers`, `conversations` (with a `bot_paused` flag), `messages`,
      `products`, `orders`, `order_items`, `knowledge_chunks`
- [x] HNSW cosine index on `knowledge_chunks.embedding`
- [x] Product seed `3S-100G`; sale price finalized with quantity tiers
- [x] Async SQLAlchemy + asyncpg connection from the app

**Definition of done:** `docker compose up` creates the full schema; the app connects and queries successfully.

**Notes:** The embedding dimension in the migration is 384 (fixed from the initial 1536 — matches the
`paraphrase-multilingual-MiniLM-L12-v2` model). All original tasks are complete → closing the issue.
Connection pooling in `rag.py` (currently opens a new connection per query) is out of this issue's
scope — tracked as a separate technical item when working on #6/#9.

---

## #4 · [Weeks 3-4] RAG pipeline: ingest the 3S Coffee profile + FAQ into the knowledge base
**Status:** ✅ Closed (7/14)

**Tasks:**
- [x] Source files `data/knowledge/product_profile.md` + `data/knowledge/faq.md`
- [x] Script `scripts/ingest.py`: chunk → embedding → insert into `knowledge_chunks`
- [x] `app/services/rag.py`: `search_knowledge(query, top_k)` using cosine `<=>`
- [ ] Evaluation: 10 sample questions return the correct chunk

**Definition of done:** The top-4 chunks return the correct context for ≥ 9/10 sample questions.

**Reason for closing despite 1 unchecked item:** the ingest + search pipeline already works correctly.
The "evaluate 10 sample questions" step is more of a recurring QA task than a hard blocker — suggest
reopening it as a small "RAG QA pass" issue whenever new content is added to `data/knowledge/`,
rather than keeping this original issue open.

**Outstanding technical item to track:** offload `embed()` (CPU-bound) to a thread pool so it doesn't
block the worker's event loop when multiple customers ask questions at once — should be folded into
#9 during infrastructure optimization.

---

## #5 · [Weeks 3-4] System prompt & brand voice: the LLM answers according to the 3S Coffee standard
**Status:** ✅ Closed (7/14)

**Brand voice (mandatory in the system prompt):**
- Consistent, formal self-reference: "We" / "The 3S Coffee Team"
- Tone: lean, practical, decisive, tenacious
- Flashy, exaggerated marketing language is forbidden
- No making up prices/promotions/stock — only use data from tools and RAG context

**Tasks:**
- [x] Finalize `app/prompts/system_prompt.md`
- [x] Integrate the LLM call in `orchestrator.py`: system prompt + RAG context + history (Redis, 24h TTL)
- [x] A 20-scenario conversation test set (advice, price questions, comparisons, off-topic questions)
- [ ] Review the output tone with anh Hoài before going live on the real fanpage

**Definition of done:** 20/20 scenarios reply with the right vibe, no wrong forms of address, no fabricated info.

**Notes:** The current prompt already has a very strict "Don't infer" and "When there's no information"
section — but since #6 wasn't done yet, the "don't make up price/stock" part was **relying only on RAG**,
with no real tool to trust per the priority order the prompt describes. So #5 and #6 should be treated as
a dependent pair when assessing "done".

**Update 7/14 — results from running the 20 scenarios:** 17/20 pass, 2 fails (scenario 10 — missed the
"shop ơi" signal, still said "bạn"; scenario 14 — didn't stop at the 2nd refusal), 1 soft-fail
(scenario 13 — skipped the step of asking what the customer dislikes about their current product). Fixed
`system_prompt.md` (added a sample phrase to avoid guessing a form of address + 3 WRONG/RIGHT example
pairs) and re-tested scenarios 10, 13, 14 individually → **all 3 now Pass**.
**Final status: 20/20 pass → closing the issue.** The remaining "review with anh Hoài" is a manual,
subjective sign-off step, not blocking the closure of this technical issue — track separately if anh
Hoài has further feedback.
⚠️ Note for the review: all 3 fixed replies are quite close to the example just added to the prompt —
worth trying a few phrasing variants outside the original 20 scenarios if you want more confidence in
the model's generalization, not just it "memorizing" the exact example sentence.

---

## #6 · [Weeks 5-6] Tool calling: search_products / check_stock / create_order / escalate_to_human
**Status:** ✅ Closed (7/14)

**Goal:** The LLM calls tools instead of making up data; a complete order-finalization flow.

**Tasks:**
- [x] Define the tool schema: `search_products`, `check_stock`, `create_order`, `escalate_to_human`
      (`app/services/tools.py`, using plain asyncpg like `rag.py`, no ORM added)
- [x] `create_order`: only called once name + phone + address + product + quantity are all present; validates VN phone numbers
- [x] Writes `orders` + `order_items`, updates stock (a `FOR UPDATE` transaction, avoiding race conditions)
- [x] The order-confirmation message follows the brand voice (order summary, total) — **dropped "estimated
      delivery time"** from scope since the system prompt forbids the bot from guessing shipping time, and
      there's no tool yet for real shipping data
- [x] Guard: the LLM must not announce a price unless `search_products` has returned one — now the price
      always comes from the real DB via the tool, no longer hardcoded in the prompt

**Definition of done:** A simulated order-finalization conversation, end to end, creates the correct DB record.

**Test results 7/14 (scenarios 21, 22 — `data/knowledge/scenarios_20.md`):**
- Scenario 21 (complete info, 5 jars): the order was written to the DB correctly — `total_vnd = 800,000₫`
  (5 × 160k, the correct tier), correct name/phone/address; `stock` decremented correctly from 1000 → 995.
- Scenario 22 (missing name): the bot stopped at the right point, asked for the name again, didn't call
  `create_order` — confirmed 0 garbage orders in the DB for the test phone number.
**Both pass → closing the issue.**

**Important note — depends on #7:** `escalate_to_human` currently only does "half the write" — it
really sets `bot_paused = TRUE` in `conversations`, but the "read" half (the worker ignoring messages
when `bot_paused = TRUE`, notifying admin in real time) is #7's scope, **not yet done**. The tool is
ready to be called correctly, but human handoff is not complete end-to-end until #7 is finished.

---

## #7 · [Weeks 5-6] Human handoff: bot_paused + staff notification
**Status:** ✅ Closed (7/15)

**Goal:** The bot knows when to stop: complaints, out-of-scope questions, or a customer asking for a real person.

**Tasks:**
- [x] `bot_paused` flag on `conversations`; when set, the worker ignores messages for that conversation
      (`app/workers/tasks.py` checks `is_bot_paused()` before calling `handle_message`)
- [x] Automatic trigger: the customer types "talk to a human" (a deterministic regex in
      `app/services/handoff.py`, not dependent on the LLM) / a complaint is detected / the LLM itself
      calls `escalate_to_human`
- [x] Instant notification to admin via Telegram (`notify_admin()`, doesn't raise an error if not configured)
- [x] A mechanism to resume the bot: `POST /admin/conversations/{psid}/resume`, protected by `ADMIN_API_TOKEN`
- [x] Logs the escalation reason into the new `escalations` table (`migrations/002_add_escalations.sql`)

**Definition of done:** A simulated complaint message → the bot goes silent correctly + admin gets notified in < 10 seconds.

**Test results 7/15 (scenario 23 — `data/knowledge/scenarios_20.md`):**
- Turn 1 (demanding a human): escalates immediately, without going through the LLM, replies with the
  correct confirmation. Ran twice in a row with consistent results.
- Turn 2 (a follow-up message while paused): the bot goes completely silent, exactly as the real worker
  would do.
- The `escalations` table logs correctly — confirmed both the deterministic (regex) branch and the
  LLM-initiated tool-call branch (found 1 record with the reason "Customer wants to talk to the boss/
  manager directly", entirely decided by the LLM itself, not the hard regex) both work.
- The `resume` endpoint returns exactly `{"psid": "test_scn_23", "bot_paused": false}`.
**All 3 parts pass → closing the issue.**

---

## #8 · [Week 7+] Admin dashboard + sales-funnel analytics
**Status:** 🟡 In progress (7/15) — part 1/3 done, end-to-end tests pass

**Goal:** An admin interface for daily operations and measurement, to optimize the order-conversion rate.

**Technical decision:** chose a standalone Next.js app (per the original proposal) instead of extending
FastAPI+HTML, running a separate `dashboard/` service on port 3000, calling JSON APIs under
`/dashboard/*` (CORS opened for `http://localhost:3000`).

**Tasks:**
- [x] Next.js dashboard: conversation list (`/conversations`), viewing message history
      (`/conversations/[psid]`) — needed to add `app/services/conversation_log.py` to write
      `messages` into Postgres, since before this only Redis (24h TTL) existed, not enough for the dashboard
- [x] Toggle the bot per conversation (`bot_paused`) — a button in the conversation list, calling
      `POST /dashboard/conversations/{psid}/pause|resume`
- [x] Order list (`/orders`) + status updates (dropdown, server validates the order
      new → confirmed → shipped → done, no going back, no cancelling a `done` order)
- [x] **(added per anh Hoài's request 7/15)** Resume via Telegram: `app/workers/telegram_listener.py`,
      the `telegram_bot` service in docker-compose, reusing the exact bot already configured in #7
      (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_ADMIN_CHAT_ID`). Long-polling, does NOT need a public domain/HTTPS.
      Only processes commands from the exact configured `TELEGRAM_ADMIN_CHAT_ID`, every other chat is
      silently ignored. Commands: `/resume <psid>` (calls the existing `handoff.resume_bot()`, no new
      logic written), `/list` (lists waiting conversations), `/help`.
- [ ] Product + FAQ CRUD (auto re-ingesting RAG when edited)
- [ ] Metrics: messages/day, conversation-to-order rate, top questions the bot fails to answer
- [ ] Simple admin auth (currently still shares the static `ADMIN_API_TOKEN` like #7, no real
      login/JWT yet)

**Definition of done:** anh Hoài runs the fanpage day-to-day purely through the dashboard, no need to touch the DB.

**Test results 7/15:** anh Hoài confirmed the dashboard runs, both tabs (Conversations, Orders) work
correctly. Current actual operating process: staff manually clicks resume on the dashboard after
finishing a conversation with the customer on Messenger (not automatic).

**Upgrade idea (implemented 7/15):** resume via a Telegram command instead of having to open the
dashboard — done, see details in the task list above. Not yet tested end-to-end (waiting for anh Hoài
to confirm `/resume` and `/list` work correctly on real Telegram).

**Update 7/15 — 3 further upgrades per anh Hoài's request:**
1. The dashboard auto-refreshes every 5s (silent background polling, no loading flicker) on both
   the conversation list and the detail page — no manual refresh needed when the handover state
   changes (e.g. a new escalation, or staff resuming via Telegram).
2. Added 2 ways to view an expanded conversation: (a) click the customer's name to **expand right in
   the row** (accordion, without leaving the list page), (b) an ↗ button to **open a separate popup
   window** (`window.open`, 420×650, kept unique per psid — clicking again for the same customer will
   focus the existing window instead of opening a duplicate). Note: this is a **self-built** chat panel
   (reading from our own `messages` table), NOT embedding the real Messenger UI directly —
   Facebook blocks iframes from external domains (X-Frame-Options), so it cannot be embedded.
3. Telegram: the escalation message and `/list` now come with an **inline "Resume bot now"**
   button (callback_query) — click it directly, no need to type/copy the PSID anymore. Still kept
   the manual `/resume <psid>` as a fallback — the PSID is displayed as `code` (Markdown), and on
   Telegram mobile tapping it auto-copies.

**Update 7/15 — handling messages/agreements during handover** (a real scenario: a customer proposes
buying 1000 jars, asks to talk to the boss to negotiate policy — previously the bot would completely
"forget" the agreement after resuming):
- The worker now **catches the real message from staff/the boss** sent through the Messenger Inbox
  while `bot_paused=TRUE`, using the `bot_paused` flag itself as the "time match" (anh Hoài's timetrap
  idea) — because the bot definitely sends nothing on its own during that time, so any echo caught
  exactly while paused must be a real person.
- Still logs the customer's messages while paused (previously they were completely ignored).
- Added an **explicit Note** at resume time (both the dashboard and Telegram `/resume <psid>
  <note>`) — in case the boss closes the deal over the phone, which can't be caught automatically.
- **Injects both sources** (real messages + notes, both stored with role='agent') back into the bot's
  system prompt on every subsequent chat turn — read from Postgres (not the 24h-TTL Redis), so it's
  never lost, preventing the bot from contradicting an agreement that was already finalized.
- The dashboard chat window automatically shows **ALL** (customer/bot/agent) in the correct time
  order, no further changes needed since the display mechanism already reads directly from
  `messages` — as long as the data is fully written (the 2 items above), it displays correctly on its own.
- **Not yet tested end-to-end** — need anh Hoài to try the real scenario: pause → reply by hand via
  Messenger → resume with/without a note → ask the customer follow-up questions to see whether the
  bot remembers correctly.

**Update 7/15 — "who records the order" for special prices/quantities** (example: a customer
negotiates 500 jars at 130k through staff): instead of building a separate manual order-entry form,
the final decision is to let the **bot create the order itself** after staff approval (safer than a
free-form form, since the LLM can never "grant itself" permission):
- New table `price_overrides` (migration 004) — staff approves exactly 1
  (customer, quantity, price) via a new Telegram command:
  `/approve <customer code> <quantity> <unit price> [note]`.
- `create_order` (in `tools.py`) automatically checks whether there's an approval that **EXACTLY**
  matches both the psid + quantity — if so, it bypasses the `MAX_AUTO_QUANTITY=100` guard and uses
  the approved unit price instead of the standard `price_tiers` table; if not, it's still rejected as
  before. An approval is marked `used=TRUE` after being used, and cannot be reused.
- Edited `system_prompt.md`: the bot is now allowed to call `create_order` directly for orders >100
  jars IF the handover notes show it was approved and the customer confirms the exact quantity —
  it must never infer that an approval exists when it's not clearly visible.
- **Not yet tested end-to-end** — need to try the real scenario: `/approve` → customer confirms the
  exact approved quantity → the bot successfully calls `create_order` on its own (without escalating
  again), verify the unit price in the DB exactly matches the approved price (not the standard tier price).

**Not closing the issue yet** — still missing product/FAQ CRUD, metrics, real auth per the original
scope, and everything listed above has not yet been tested for real by anh Hoài.

**Update 7/15 — order-creation UI on the dashboard:**
- In the expanded chat panel (`conversations/page.js`): added an order-creation form with 2 buttons
  — **"🤖 Bot creates order"** (calls `tools.create_order()` directly — the function the AI uses,
  still fully checking `price_overrides`/standard price tiers/quantity limits) and
  **"👤 Staff creates order"** (`app/services/orders.py:create_order_manual` — bypasses all
  validation, staff enters the unit price themselves, only real stock is still checked).
- A separate `/orders/new` page — an order-creation area **completely independent** of the chat panel,
  used for orders that don't go through Messenger (phone, in-store). Since `customers.psid` is
  `UNIQUE NOT NULL`, this kind of order auto-generates a fake psid of the form `manual:<short uuid>`
  to satisfy the constraint, not a real Facebook PSID.
- The `dashboard/app/components/OrderForm.js` component is shared between both locations
  (if no `psid` is passed, only the "Staff creates order" button shows, no "call the bot" since
  there's no conversation for the bot to read context from).
- New endpoints: `GET /dashboard/products`, `POST /dashboard/conversations/{psid}/create_order`,
  `POST /dashboard/conversations/{psid}/create_order_manual`, `POST /dashboard/orders/manual`.
- **Not yet tested end-to-end** — need to try all 3 flows: (1) "Bot creates order" with a quantity
  >100 without `/approve` → must be rejected just like the bot; (2) "Staff creates order" with any
  price/quantity → must succeed normally; (3) `/orders/new` → the created order must have a
  `psid` of the form `manual:...`, not accidentally attached to some other customer.

**Update 7/15 — auto-filling the form from `/approve` + `/note`** (per anh Hoài's request, to avoid
manually cross-referencing the chat panel):
- New endpoint `GET /dashboard/conversations/{psid}/order_draft` combines 3 sources: (1)
  name/phone/address from `customers` (if a previous order exists), (2) quantity + price from the
  most recent **unused** `/approve` approval (`price_overrides.get_latest_unused_override`),
  (3) the last 5 `/note` notes (shown raw, not auto-parsed since it's not reliable enough for a
  field like an address).
- `OrderForm.js` automatically calls this endpoint on open (if there's a `psid`) — pre-fills the
  quantity/price from `/approve`, name/phone/address if there's a previous order; shows a box of
  `/note` notes above the form so staff can manually cross-reference whatever's still missing
  (usually the address, if the customer has never ordered before).

**Note on the question about where `/note` is stored:** in the `messages` table (Postgres, NOT Redis)
— `role='agent'`, linked via `conversation_id` → `conversations` → `customer_id` →
`customers.psid`. Written via `handoff.log_note()` → `conversation_log.log_message()`.
Read back via `conversation_log.get_recent_agent_messages(psid)` — already used in 2 places:
(1) `orchestrator.py` injects it into the system prompt every chat turn (the bot knows), (2) the new
`order_draft` endpoint (staff sees it directly on the dashboard, no need for manual SQL queries anymore).
Manual query if needed: `SELECT role, content FROM messages WHERE conversation_id = (SELECT id FROM conversations WHERE customer_id = (SELECT id FROM customers WHERE psid = '...')) ORDER BY created_at DESC;`
- **Not yet tested** — need to confirm: after `/approve` → open that customer's chat panel on the
dashboard → the quantity/price must automatically appear correctly in the form, no need to retype.

**Update 7/15 (round 2) — reworked the flow per anh Hoài's feedback:** instead of embedding the form
directly in the chat panel (cluttered, hard to test), changed it into **1 navigation button** in the
expanded chat panel → straight to the `/orders/new?psid=...` page (the main "Create order" page):
- The button only carries the `psid` via a query param (**does not** put name/phone/address into
the URL since that's sensitive data).
- `/orders/new` reads `psid` from the query, passes it into `OrderForm` — automatically re-triggers
the existing `order_draft` fetch logic (no new logic written), showing both
"Bot creates order"/"Staff creates order" buttons exactly like when used on the standalone page.
- **Technical note:** `useSearchParams()` in the Next.js App Router must be wrapped in
`<Suspense>`, otherwise `next build` (production, what the Dockerfile uses) will error out
— split into a child component `NewOrderContent` wrapped in `<Suspense>`.
- **Diagnosing the issue anh Hoài reported, "`/approve`/`/note` isn't being recorded":** the
`/approve` code only sends the Telegram confirmation message **after** the DB write succeeds (if it
fails, nothing is sent at all), so most likely the data was written correctly, and the dashboard just
hadn't been rebuilt so it wasn't showing — not 100% confirmed since anh Hoài hasn't queried the DB directly.
- **Not yet re-tested** after this fix.

**Update 7/15 (round 3) — fixed 2 issues anh Hoài reported:**
1. **A real bug, root cause identified:** `price_overrides.create_override()` (the function
`/approve` calls) used to only create `customers`, WITHOUT the accompanying `conversations` record.
The dashboard lists conversations starting from the `conversations` table (INNER JOIN), so a
customer approved via `/approve` who had never chatted/used `/note` before would **never appear on
the dashboard** even though `price_overrides` had the correct data. Fix: `create_override()` now
calls `conversation_log.ensure_conversation()` first (like `/note` already does), guaranteeing both
`customers` and `conversations` always exist.
2. **Restored the "internal info" panel right inside the chat window** (lost in the previous fix
since everything moved to `/orders/new`) — now shown again in `conversations/page.js` via the
`expandedDraft` state (re-calling the existing `order_draft` API), but **display-only (read)** — order
creation still goes through the navigation button to `/orders/new` as agreed, the order form is not
embedded back into the chat panel.
- **Not yet re-tested.** Need to confirm: `/approve` for a NEW customer (who has never chatted) →
must appear immediately in the dashboard's conversation list, and opening it must show the yellow
internal-info panel.

**Update 7/16 — fixed the "psid = 'Mã'/'khách'" garbage-data bug:** anh Hoài re-tested,
`price_overrides` and `messages(role='agent')` were written correctly, but `conversations` had 2
garbage rows with `psid = "Mã"` and `psid = "khách"` (Vietnamese for "code" and "customer"). Root
cause: the Telegram message itself displays "Mã KH: `4`" ("Customer code: `4`"), which reasonably
led anh Hoài to type the whole phrase "Mã KH: 4" into the command instead of just the number `4`
— the code only split on whitespace and took the first token ("Mã") as the psid, creating a garbage
customer. Fix:
- Added `handoff.is_valid_identifier()` — blocks it right away if the input isn't a pure number or a
valid system sender_id (`tg:...`, `manual:...`), returning a clear error instead of silently
creating garbage data. Applied to `/resume`, `/note`, and `/approve`.
- Changed how the customer code is displayed on Telegram (`notify_admin`, `/list`, `/help`) —
explicitly emphasizing "type ONLY this number, DO NOT type the words 'Customer code'" to avoid a repeat.

**Cleaning up garbage data** (anh confirms it first, then runs it himself — not auto-deleted since
it needs anh Hoài's confirmation that it's really garbage first):
```sql
DELETE FROM messages WHERE conversation_id IN (
  SELECT c.id FROM conversations c JOIN customers cu ON cu.id = c.customer_id
  WHERE cu.psid IN ('Mã', 'khách'));
DELETE FROM conversations WHERE customer_id IN (
  SELECT id FROM customers WHERE psid IN ('Mã', 'khách'));
DELETE FROM customers WHERE psid IN ('Mã', 'khách');
```
- **Not yet re-tested** after this fix — need to try typing it wrong on purpose (e.g. `/note Mã KH: 4 test`)
to confirm the bot returns a clear error instead of creating garbage, and typing it correctly
(`/note 4 test`) to confirm it still works normally.

**Update 7/16 (round 2) — fixed the root cause of "habitually forgetting to rebuild the dashboard":**
After the same symptom repeated many times (the dashboard not picking up new code: missing buttons,
missing the notes panel, orders not showing...), switched the `dashboard` service entirely to
**dev mode with hot-reload** in `docker-compose.yml`, exactly like how `api` already uses `--reload`:
- `command: npm run dev` instead of `npm run build && npm start`.
- Bind-mount `./dashboard:/app` — editing a file shows up immediately, NO need for
`docker compose up --build dashboard` anymore (still need a **hard page refresh**, Ctrl+Shift+R).
- 2 separate volumes, `dashboard_node_modules` and `dashboard_next_cache`, so they don't get
overwritten by the host's bind mount (the host may not have `node_modules`, or a different OS).
- **From now on only `docker compose up -d dashboard` is needed once** (the first time, for
`npm install`), after that every Next.js code change applies automatically, no further command needed.

**Important note:** `price_overrides` is NOT an order — it's just a price/quantity permit. A real
order only exists in the `orders` table after clicking "Bot creates order"/"Staff creates order"
successfully. These 2 concepts need to be clearly distinguished when reporting "can't find the order".
- **Not yet re-tested** after switching to dev mode — need to confirm `docker compose up -d --build
dashboard` (the last time a build is needed, since the command changed) runs, the container doesn't
crash, and then edit any 1 line of text in the dashboard to confirm hot-reload really works.

**Update 7/16 (round 4) — compact Status labels + per-note/per-approval action buttons:**
After testing, anh Hoài realized the single "Status" (Action) column for the whole conversation
wasn't accurate (1 conversation can have several different notes/approvals). Redesigned:
- Migration 006: added `messages.handled` (reusing the existing `price_overrides.used` for
  approvals, no new column needed there).
- Removed the large badges → compact labels `/n(N)` (unhandled notes) and `/a(N)` (unused
  approvals), the number bold, gray when N=0 so it's still easy to spot when there's work to do.
- **Removed the "Status" (Action) column entirely** — no longer used (migration 005's `staff_action`
is still left in the DB, not deleted).
- The expanded panel now lists **EVERY** unhandled note and **EVERY** unhandled approval
individually (not just the most recent note like before) — each row has its own button:
  - Note: "✓ Handled" button — no confirmation popup needed.
  - Approval: "✓ Order created" button — REQUIRES a confirmation popup first (using `window.confirm`).
- New endpoints: `POST /dashboard/notes/{message_id}/mark-handled`,
  `POST /dashboard/overrides/{override_id}/mark-used`.
- **Important:** `conversation_log.get_recent_agent_messages()` (the function that pumps context into
  the bot) **DOES NOT** filter by `handled` — the bot must still know the full agreement whether or
  not staff has marked it "handled" on the dashboard — this flag only tidies up the UI, it doesn't
  invalidate the agreement.
- **Not yet tested** — need to run migration 006 first, restart `worker`, hard-refresh the dashboard
(auto hot-reload, no rebuild needed).

**Update 7/16 (round 5, end of session) — don't hide history + added a Reject flow:**
anh Hoài pointed out: notes/approvals that had been handled previously "disappeared" from the UI
because the dashboard was **filtering** (`WHERE used/handled = FALSE`), not deleting from the DB —
but they still need to be reviewable. Fixed:
- Migration 007: added `price_overrides.status` ('active'/'used'/'rejected') +
  `reject_reason`. `used` (boolean) is still the source of truth for `create_order` logic
  (unchanged), `status` is only for the dashboard to display the correct label.
- `order_draft` now returns **ALL** notes/approvals (unfiltered), along with the `handled`/`status`
  flag so the frontend can decide whether to show "Active" or "Frozen".
- Frontend: a handled item is shown **dimmed (opacity), gray background, no more button** — only a
  static label remains (✓ Handled / ✓ Order created / ✗ Rejected). An `active` item still shows the
  full button as before.
- Added a **"✗ Reject"** button next to "✓ Order created" for every active approval — a
  `window.prompt` popup asks for a reason (required, can't be blank), then calls
  `POST /dashboard/overrides/{id}/reject`. A rejected approval still has `used=TRUE` (cannot be
  reused for `create_order`) but clearly shows the rejection reason on the dashboard.
- **The `/n(N)`/`/a(N)` badges on the main table DO NOT change** — they still only count "Active/
  unhandled" items (matching the "needs attention" intent), not counting frozen items too.
- **Not yet tested** — need to run migration 007, restart `worker`, hard-refresh. Check: (1)
  marking 1 note/approval → still visible in the list (frozen, not disappearing); (2) rejecting
  1 approval with a reason → the reason displays correctly; (3) a rejected approval **cannot** be
  used for "Bot creates order" anymore (since `used=TRUE`).

**Accepted known limitation, NOT fixed (7/16):** even after switching `dashboard` to dev-mode
hot-reload, in practice `docker compose up -d --build dashboard` is still needed after every code
change (it doesn't fully pick up new code automatically as originally hoped). anh Hoài agreed
**not to dig further into fixing this** — the practical workflow: every time Claude edits
`dashboard/` code, always re-run `docker compose up -d --build dashboard` (not just
`restart`), then hard-refresh the page.

**Update 7/16 (round 3) — conversation table UX** (per feedback: everything before this actually
already worked, it was just hard to find since the only entry point was clicking the customer's name):
- Added a clear **"▼ Expand chat"** button right next to the customer's name (instead of only
being able to click the name itself).
- **Removed the ↗ "Open in separate window"** button at the end of the row — to avoid confusion
with the new expand button (the `/conversations/[psid]` page is still in the code, it just no longer
has a link pointing to it).
- Added a **"Notes/Approval"** (Status) column — shows a "Has notes"/"Has approval" badge right on
the row, no need to expand to find out. Backend added `has_notes`/`has_approve`
(EXISTS subquery) to `GET /dashboard/conversations`.
- Added a **"Status"** (Action) column — a dropdown for staff to manually mark "New/Seen/Order
created/Skipped", entirely independent of `bot_paused`. New `conversations.staff_action` column
(migration 005, CHECK constraint with 4 values), endpoint `PATCH /dashboard/conversations/{psid}/action`.
- **Not yet tested** — need to run migration 005 first, restart `worker` (the dashboard hot-reloads
on its own, no rebuild needed), hard-refresh, then check all 4 points above.

---

## #9 · [Infrastructure] GitLab CI/CD + VPS deploy + monitoring
**GitLab status:** Opened — only basic lint/test in place so far

**Goal:** The system runs 24/7 on a VPS, deployed automatically via GitLab CI/CD.

**Tasks:**
- [x] `.gitlab-ci.yml`: lint (ruff) → test (pytest)
- [ ] Build a Docker image → deploy to VPS (SSH)
- [ ] Secrets in GitLab CI/CD variables: `PAGE_ACCESS_TOKEN`, `META_APP_SECRET`, `LLM_API_KEY`
      (masked, protected) — not hardcoded
- [ ] A ~2GB RAM VPS, Docker Compose; HTTPS required for the webhook (Caddy or Nginx + Let's Encrypt)
- [ ] Daily PostgreSQL backups
- [ ] Alert on repeated webhook failures or an LLM API failure; fallback: "The 3S Coffee Team will
      get back to you right away." + notify staff
- [ ] Log every conversation for periodic review

**Definition of done:** Pushing to `main` → auto-deploys; webhook uptime > 99%.

**Notes:** The current pipeline lets it "pass" even with no tests at all (`pytest -q || [ $? -eq 5 ]`),
so consider the "test" step a placeholder, not a real quality gate yet.

---

## #10 · Fallback customer channel via Telegram (not part of the original backlog)
**Status:** 🟡 Newly added 7/15

**Context:** Meta revoked the dev role on the test account, making it impossible to test through
Messenger. To avoid being completely stuck, added a separate Telegram channel for **customers**
(quite different from the admin bot in #7/#8, which only receives internal notifications/commands)
— treat this as a parallel test/dev channel, not a long-term replacement for Messenger.

**Tasks:**
- [x] `app/workers/telegram_customer_listener.py` — a separate Telegram bot (a different token
      from the admin bot), long-polling, replies to ANYONE who messages it (no chat_id restriction
      unlike the admin bot).
- [x] `sender_id` uses a shared system with Messenger, formatted `tg:<chat_id>` (a prefix that
      never collides with a real Facebook PSID) — reuses `orchestrator.handle_message()` **as-is**,
      no AI/tool/RAG/handoff logic rewritten at all.
- [x] `orchestrator.py`: skips calling the Messenger Graph API (to fetch the name) for a
      non-Messenger `sender_id` (`tg:` or `manual:`), avoiding 1 pointless failed request every chat turn.
- [x] `is_bot_paused`/logging messages while paused: reuses the exact same Messenger worker logic
      (`app/workers/tasks.py`), no separate version for this channel.
- [x] New `telegram_customer_bot` service in `docker-compose.yml`, setting
      `TELEGRAM_CUSTOMER_BOT_TOKEN` (a bot **entirely different** from the `TELEGRAM_BOT_TOKEN` used for admin).
- [ ] **Not yet tested** — need to create a new Telegram bot via @BotFather (different from the
      admin bot), set `TELEGRAM_CUSTOMER_BOT_TOKEN`, restart, and try messaging it from Telegram to
      see whether the bot replies with the exact same tone/pricing/RAG as Messenger (since it shares 100% of the logic).

**Important note:** this is not a replacement for Messenger — the issue with Meta should still be
worked on in parallel (recreating the test user/requesting dev access again) since Messenger
remains the primary channel for real customers in Vietnam. 2 longer-term directions were also
discussed (a custom chat app on the website, Zalo OA) but not yet built — anh Hoài needs to decide
when to prioritize them.

---

## Suggested next priority order
1. Rotate the leaked secret right away (noted in #1) — still an outstanding item from the start of
   the project, independent of the order below, should be done soon if not already.
2. **#9 (real CI/CD + deploy)** — now the highest remaining technical priority: #5/#6/#7 have
   finished their core business logic, so shift to making the system run stably 24/7 before
   expanding features further (#8).
3. Outstanding technical items from #2/#3/#4 (dedup by `mid`, retry/dead-letter, connection
   pooling, offloading `embed()`, periodic RAG QA) — bundle these with #9.
4. #8 (dashboard) can wait, once the infrastructure (#9) is stable — the dashboard will also need
   the `/admin/conversations/{psid}/resume` endpoint (already in place from #7) as a foundation, so
   finishing #7 first makes sense.

## Reference documentation (docs/)
Created all 4 files in `docs/` (7/16) — like a `/help` file for each component, used when
deploying/handing off/debugging, no need to dig back through the code:
- `docs/DATABASE-VI.md` / `docs/DATABASE-EN.md` — the full schema, migration history, common lookup SQL
- `docs/DASHBOARD-VI.md` / `docs/DASHBOARD-EN.md` — every page/button of the Next.js dashboard, mapped to the right endpoint
- `docs/TELEGRAM_BOT-VI.md` / `docs/TELEGRAM_BOT-EN.md` — the 2 Telegram bots (admin/customer), commands, how to create a new bot
- `docs/BACKEND_API-VI.md` / `docs/BACKEND_API-EN.md` — the full FastAPI backend: webhook, orchestrator, tool calling, human
  handoff, the service/worker list, environment variables

**Not yet done:** `docs/DEPLOYMENT.md` — saved for when #9 (CI/CD + VPS deploy) is finished, at which
point a real deployment process will exist to document accurately.

---

## Batch 2 #8 — Product/FAQ CRUD + LLM reliability fixes (7/17)

> Note: from this point on, updates are summarized in English rather than
> translated line-by-line from `ISSUES-VI.md` (which grew very large during
> this session). See `ISSUES-VI.md` for the full blow-by-blow narrative,
> including exact chat transcripts, SQL diagnostics, and every intermediate
> fix attempt.

**Scope completed:** 1 of the 3 remaining #8 items — Product/FAQ CRUD.
Metrics/analytics and real per-staff auth are still not built.

### Product/FAQ CRUD (the planned work)
- **Migration 008** (`faq_entries` table + `knowledge_chunks.faq_entry_id`)
  and **migration 009** (`knowledge_chunks.product_id`).
- **`app/services/products.py`** — full product CRUD (name/description/
  price/stock; `sku` is immutable after creation) + price-tier CRUD (replaces
  the entire tier list on every save). Deleting a product is rejected by a
  foreign-key constraint if it has related orders/tiers (by design).
  Every create/update also auto-creates/replaces a matching `knowledge_chunks`
  row from the product's `description` field ("RAG Layer 2", see below).
- **`app/services/knowledge_entries.py`** — FAQ CRUD, computing the
  embedding and writing/deleting the matching `knowledge_chunks` row
  immediately on save/delete — no need to run `scripts/ingest.py`.
- **New dashboard pages** `/products` and `/faq`, new nav links, new
  `/dashboard/products*` and `/dashboard/faq*` endpoints.

### A chain of LLM-reliability bugs found during real testing (not code bugs, mostly)
After adding 2 new SKUs via the dashboard, real-world testing surfaced a
series of issues — each one diagnosed and fixed in turn:

1. **Bot insisted "only 1 SKU exists"** even after the new SKUs were added
   and confirmed in the DB. Root cause: `tools.py`'s tool schema literally
   said *"currently there is only 1 product"* in the `query` parameter
   description — this text is sent to the LLM on **every single turn**,
   independent of RAG, and actively discouraged it from trusting/checking
   for more products. Fixed by rewriting that description, and by adding a
   new **"Layer 1"** mechanism: `products.get_sku_summary_text()` is now
   injected fresh into the system prompt on every turn (bypassing the LLM's
   own discretion about whether to call `search_products`).
2. **Bot claimed "I just checked the database"** when it likely hadn't
   actually called the tool that turn, and kept flip-flopping between
   confirming and denying the same fact across a few messages. Fixed by
   adding an explicit system-prompt rule: never claim to have "checked"
   unless a tool was genuinely called this turn, and always re-verify via
   tool when the customer pushes back on a previous answer.
3. **Bot invented a nonexistent SKU** ("3S-25KG") when asked about a
   packaging-workshop use case that didn't match any real product — even
   though a real SKU with that exact code existed a few messages later in
   testing (a coincidence that initially caused a misdiagnosis on our part).
   Fixed by explicitly stating the SKU list is *closed* (complete, nothing
   else exists) in both the Layer-1 prompt injection and a SAI/ĐÚNG example
   added to `system_prompt.md`.
4. **Bot kept contradicting itself within the same conversation thread**
   even after the above fixes were deployed — traced to **stale Redis chat
   history**: the bot's own earlier wrong replies were still present in the
   24h-TTL Redis context, and the LLM tended to stay "consistent" with its
   own past mistakes rather than trust the freshly injected ground truth.
   Mitigated (not eliminated — inherent LLM behavior) via: `temperature`
   lowered from 0.3 to 0.1, an explicit "live data always outranks
   conversation history" priority rule added to the Layer-1 prompt text, and
   a new **dev-only utility script** `scripts/clear_chat_history.py` to wipe
   Redis history for a conversation (or everything) so retests start clean.
5. **A real, non-LLM code bug**: `search_products()` never returned
   `price_vnd` (the base retail price) — only the price-tier list. Products
   created via the new CRUD that had a base price set but no tiers added
   caused the bot to correctly report "I have no price to give you", which
   looked like more LLM flakiness but was actually a straightforward gap in
   the tool's return value. Fixed by adding `price_vnd_default` to every
   product in the tool's response, confirmed working end-to-end afterward
   (base price + tier price both reported correctly, with correct bulk-order
   math).

### Also fixed during this session
- **Restart-target confusion**: for a while, code changes affecting the
  dashboard's `/dashboard/*` endpoints were mistakenly diagnosed as needing
  a `worker` restart, when in fact the `api` service (which the dashboard
  actually talks to) needed it — `worker` only processes the Messenger
  Redis queue and never serves any HTTP endpoint. The going-forward rule is
  now to restart all 4 Python backend services together
  (`api worker telegram_bot telegram_customer_bot`) after any backend code
  change, rather than trying to reason about exactly which service imports
  which module each time.
- A migration-timing race condition (`UndefinedColumnError: product_id`) was
  hit once while migration 009 was still being applied concurrently with a
  dashboard save — no data was lost (the write was inside a transaction that
  rolled back cleanly), just needed a retry after the migration finished.

---

## Batch 3 #8 — Metrics/Analytics (7/17)

2 of the 3 remaining #8 items are now done (CRUD + Metrics); only real
per-staff auth is left.

**`app/services/metrics.py`** — 3 functions, 3 new endpoints
(`/dashboard/metrics/*`), **no new DB table**, fully reusing existing data:
1. **Messages/day** (`list_messages_per_day`) — counts `messages` per day,
   split by `role` (customer/bot/agent). Days with no messages simply don't
   appear in the result (not zero-filled).
2. **Chat-to-order rate** (`get_conversion_rate`) — % of customers (by
   `customer_id`) who have at least 1 order in `orders`, out of all customers
   who have ever chatted. **Intentionally simplified**: not broken down by
   time period (day/week) yet — just an overall rate, could be extended later.
3. **Top unanswered questions** (`list_unanswered_questions`) — scans for bot
   messages matching the fixed fallback phrase in `system_prompt.md` ("no
   confirmed information yet..."), pairs each with the customer's question
   from **immediately before** it in the same conversation, groups by
   normalized question text (lowercased/trimmed) to count frequency. **No
   NLP/fuzzy matching** — differently worded questions with the same meaning
   are counted separately (a known limitation, acceptable for the current scope).

**New `/metrics` dashboard page** — 3 overview cards (total customers /
customers with orders / rate) + a CSS-only bar chart (no charting library
added, to avoid an `npm install` inside the dev-mode container) for
messages/day, plus a table of unanswered questions.

**Not yet tested** — needs an `api` restart (the new endpoints live in
`dashboard.py`, not `worker`) and a hard refresh of the dashboard.

---

## Batch 4 #8 — Real auth (7/17) — CLOSES OUT ISSUE #8

The last remaining item of issue #8 — after Batch 4, #8's entire original
checklist is complete (CRUD, Metrics, Auth). **Fully replaces** the old
shared static `ADMIN_API_TOKEN` with real per-staff login.

**Key technical decision — no new dependencies added:**
- **No JWT** (avoids adding `PyJWT` to `requirements.txt`) — uses a random
  **session token** (`secrets.token_urlsafe`), stored in the `staff_sessions`
  table. Simpler than JWT, easy to revoke (just delete 1 DB row).
- **No bcrypt/passlib** — passwords hashed with `hashlib.pbkdf2_hmac`
  (Python's standard library, 200,000 SHA256 iterations + a per-user salt).
- **Why:** adding a new dependency means **rebuilding the `api` Docker
  image** (different from a simple restart) — this caused real friction
  multiple times in earlier batches (e.g. the `docker-compose.yml` dev-mode
  switch on 7/16).

**Implementation:**
- Migration 010: `staff_users` table (username/password_hash/password_salt/
  name/is_active) + `staff_sessions` (staff_id/token/expires_at, 7-day TTL).
- `app/services/auth_service.py`: password hash/verify, `authenticate()`,
  `create_session()`/`validate_session()`/`delete_session()`, `staff_users` CRUD.
- `app/api/auth.py`: `require_staff_session` — reads the standard
  `Authorization: Bearer <token>` header (replacing the old `X-Admin-Token`).
- `app/api/auth_router.py` (new): `/dashboard/auth/login|logout|me|staff` —
  does **not** apply the dependency at the router level (unlike
  `dashboard.py`) since `/login` must work BEFORE a token exists — each
  route declares its own dependency.
- `app/api/dashboard.py`, `app/api/admin.py`: switched to `require_staff_session`.
  The `/admin/ui` page (plain HTML, dashboard's predecessor) is kept as a
  lightweight fallback, now requiring a session token (grabbed via DevTools
  after logging into the main dashboard) instead of the old static token.
- **Frontend:** `login/page.js` changed to a username/password form;
  `lib/api.js` switched to the `Authorization: Bearer` header + renamed the
  localStorage key `admin_token` → `staff_token` (**no auto-migration** —
  anyone currently logged in gets bounced to `/login` and must log in again
  with a real account — acceptable since this is an intentional security
  change).
- **Fixed a known limitation from `DASHBOARD-VI.md`**: added a real logout
  button (`NavUser.js`, shows the name + a logout button in the nav; before
  this you had to clear it manually via DevTools).
- New `/staff` page — list/add/deactivate staff accounts. **No role-based
  permissions yet** — any logged-in staff can manage other accounts, fine
  for the current small-team scale.
- `scripts/create_staff_user.py` — a bootstrap script to create the
  **first** account (required, since nobody can log in yet to create one
  via `/staff` — chicken-and-egg). From the 2nd account onward, create
  directly via `/staff`.

**Not yet built** (out of Batch 4 scope, noted for the future if needed):
role-based permissions (e.g. only "admin" can create accounts), an audit
trail (recording which staff member did what in `messages`/`orders`...),
password change, password reset via email.

**Not yet tested** — needs: (1) run migration 010; (2) restart all 4
services; (3) run the bootstrap script to create the first account (required
before anyone can log in); (4) hard refresh the dashboard (will auto-bounce
to `/login` since the old token is no longer valid) and log in with the new
account; (5) confirm the logout button works, try adding a 2nd account via
`/staff`.
