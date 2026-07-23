# Alpha3S — Issue Backlog

> Restored from the GitLab export file (`2026-07-04_13-00-438_ledanghoai-group_alpha3s_export.tar.gz`),
> reorganized 7/21 into clean markdown, consolidating scattered updates into current-state summaries.
> 12 issues (9 original + #10 that arose along the way + #11/#12 new), all closed except #9.

| # | Issue | Status |
|---|-------|--------|
| 1 | Messenger webhook + Meta auth | ✅ Closed |
| 2 | Redis queue + arq worker | ✅ Closed |
| 3 | PostgreSQL + pgvector: schema/migration/seed | ✅ Closed |
| 4 | RAG pipeline: ingest + search | ✅ Closed |
| 5 | System prompt & brand voice | ✅ Closed |
| 6 | Tool calling (search_products/check_stock/create_order/escalate_to_human) | ✅ Closed |
| 7 | Human handoff: bot_paused | ✅ Closed |
| 8 | Admin dashboard + analytics | ✅ Closed |
| 9 | CI/CD + VPS deploy + monitoring | 🟡 In progress (2/several batches) |
| 10 | Fallback customer channel (Telegram) | ✅ Closed |
| 11 | Knowledge Base V2 (Ingestion → Retrieval → Router → Prompt Assembly → Guardrails → Test Suite) | ✅ Closed (parallel to production) |
| 12 | NLU layer (Normalization → Pattern Router → Semantic Router → Combined Pipeline → Real bot integration) | 🟡 Integration in progress (Batches 1-2/several) |

---

## #1 · Messenger webhook + Meta auth (echo bot)
**Status:** ✅ Closed

**Goal:** The FastAPI webhook works end-to-end with the test fanpage at the echo-bot level.

**Tasks:**
- [x] `GET /webhook`: verifies `hub.verify_token` with Meta
- [x] `POST /webhook`: verifies the `X-Hub-Signature-256` signature (HMAC app secret, `hmac.compare_digest`)
- [x] Send API client replies to messages
- [x] Secrets via env: `PAGE_ACCESS_TOKEN`, `META_APP_SECRET`, `META_VERIFY_TOKEN`
- [x] Connected to the test fanpage (ngrok/cloudflared during dev)

**Definition of done:** Messaging the fanpage receives an echo reply in < 2 seconds. — Met.

**⚠️ Outstanding security risk:** the real `.env` file was once committed then deleted (commit
`a9db226` → `a9638f9`) — the secret is still in git history. **Need to rotate
`META_APP_SECRET`/`PAGE_ACCESS_TOKEN` as soon as possible** — this can't be automated, anh Hoài
needs to do it himself via the Meta Developer Console.

---

## #2 · Redis queue + arq worker (async processing)
**Status:** ✅ Closed

**Goal:** The webhook returns 200 to Meta immediately, all AI processing runs in the worker.
*(Note: BullMQ is Node.js-only — the Python stack uses Redis + arq.)*

**Tasks:**
- [x] Redis service in docker-compose
- [x] `POST /webhook` only validates + enqueues the `process_message` job, then returns 200
- [x] arq worker: `app/workers/tasks.py`
- [x] Retry policy + dead-letter (completed in #9 Batch 1)
- [x] Dedup by `mid` (completed in #9 Batch 1)

**Definition of done:** Webhook response time < 100ms; no message loss on worker restart. — Met.

---

## #3 · PostgreSQL + pgvector: schema, migration, seed
**Status:** ✅ Closed

**Goal:** PostgreSQL as the main database, with pgvector as the Knowledge Base for RAG.

**Tasks:**
- [x] `pgvector/pgvector:pg16` image, `./migrations` mounted into initdb
- [x] Migration `001_init.sql`: `customers`, `conversations` (`bot_paused` flag), `messages`,
      `products`, `orders`, `order_items`, `knowledge_chunks`
- [x] HNSW cosine index on `knowledge_chunks.embedding` (384 dims, matching
      `paraphrase-multilingual-MiniLM-L12-v2`)
- [x] Product seed `3S-100G` with quantity price tiers
- [x] Async SQLAlchemy + asyncpg connection

**Definition of done:** `docker compose up` creates the full schema; the app connects and queries
successfully. — Met.

---

## #4 · RAG pipeline: ingest the 3S Coffee profile + FAQ
**Status:** ✅ Closed

**Tasks:**
- [x] Source `data/knowledge/product_profile.md` + `data/knowledge/faq.md`
- [x] `scripts/ingest.py`: chunk → embedding → insert into `knowledge_chunks`
- [x] `app/services/rag.py`: `search_knowledge(query, top_k)` using cosine `<=>`
- [x] `embed()` offloaded to a thread pool (completed in #9 Batch 1, avoids blocking the worker's
      event loop)

**Definition of done:** Top-4 chunks return the correct context for most sample questions. — Met.

---

## #5 · System prompt & brand voice
**Status:** ✅ Closed

**Brand voice (mandatory in the system prompt):**
- Consistent, formal self-reference: "We" / "The 3S Coffee Team"
- Lean, practical, decisive tone — no flashy, exaggerated marketing language
- No making up prices/promotions/stock — only use data from tools and RAG context

**Tasks:**
- [x] `app/prompts/system_prompt.md` finalized
- [x] LLM call integrated in `orchestrator.py`: system prompt + RAG context + history (Redis, 24h TTL)
- [x] 20-scenario conversation test set

**Result:** 20/20 scenarios pass (2 rounds of fixes: missed the "shop ơi" form-of-address signal,
didn't stop correctly after 2 consecutive refusals — fixed with WRONG/RIGHT examples in the prompt).

---

## #6 · Tool calling: search_products / check_stock / create_order / escalate_to_human
**Status:** ✅ Closed

**Goal:** The LLM calls tools instead of making up data; a complete order-finalization flow.

**Tasks:**
- [x] Tool schema in `app/services/tools.py` (plain asyncpg, no ORM)
- [x] `create_order`: only called once name + phone + address + product + quantity are complete;
      validates VN phone numbers
- [x] Writes `orders` + `order_items`, updates stock (a `FOR UPDATE` transaction, avoiding race conditions)
- [x] Guard: price always comes from the real DB via the tool, never hardcoded in the prompt

**Test results:** End-to-end order creation writes the correct DB record (correct total per price
tier, correct stock deduction); missing info → the bot stops at the right point, no garbage orders.

---

## #7 · Human handoff: bot_paused + staff notification
**Status:** ✅ Closed

**Goal:** The bot knows when to stop: complaints, out-of-scope, or a customer asking for a human.

**Tasks:**
- [x] `bot_paused` flag on `conversations`; the worker ignores messages when it's set
- [x] Automatic trigger: regex "talk to a human" (`app/services/handoff.py`, LLM-independent) + the
      LLM itself calling `escalate_to_human` on detecting a complaint
- [x] Instant admin notification via Telegram (`notify_admin()`)
- [x] Resume the bot: `POST /admin/conversations/{psid}/resume`
- [x] Logs the escalation reason into an `escalations` table

**Test results:** Both the deterministic (regex) and the LLM-decided branches work correctly;
resume returns the correct state; the bot goes fully silent while paused.

---

## #8 · Admin dashboard + analytics
**Status:** ✅ Closed — the entire original checklist (CRUD, Metrics, Auth) is complete

**Technical decision:** a standalone Next.js app (`dashboard/`, port 3000), calling JSON APIs
under `/dashboard/*` (CORS opened for `http://localhost:3000`). Dev mode uses hot-reload
(`npm run dev` + bind-mount) — **note:** `docker compose up -d --build dashboard` is still needed
after every code change to be sure new code is picked up (hot-reload isn't 100% reliable on Docker
Desktop for Windows), not just a browser hard refresh.

### Conversations & handoff
- [x] Conversation list + message history (written via `app/services/conversation_log.py` into
      Postgres, not just the 24h-TTL Redis)
- [x] Toggle the bot per conversation, auto-refresh every 5s
- [x] Expandable chat panel (accordion) right in the list
- [x] **Resume via Telegram** (`app/workers/telegram_listener.py`) — long-polling, no public
      domain/HTTPS needed, only accepts commands from the configured `TELEGRAM_ADMIN_CHAT_ID`:
      `/resume <psid>`, `/list`, `/help`, an inline "Resume now" button
- [x] **Captures real staff messages** sent via the Messenger Inbox while `bot_paused=TRUE` (using
      the `bot_paused` flag itself as a "time match" — the bot definitely sends nothing on its own
      then) + **explicit notes** via `/note <customer code> <content>` — both sources are injected
      into the system prompt on every subsequent turn, preventing the bot from contradicting an
      agreement finalized by phone/in person

### Orders & special-price approval
- [x] Order list + status updates (server validates the order
      `new → confirmed → shipped → done`, no going back / no cancelling a `done` order)
- [x] `price_overrides` (a dedicated table) — staff approves exactly 1 (customer, quantity, price)
      via `/approve <customer code> <quantity> <unit price>`; `create_order` checks for an EXACT
      match before bypassing the `MAX_AUTO_QUANTITY=100` limit
- [x] `/orders/new` page — standalone order creation (phone/in-store), auto-generates a `psid` like
      `manual:<uuid>`; 2 buttons "🤖 Bot creates order" (via `tools.create_order()`, fully validated)
      and "👤 Staff creates order" (`orders.py:create_order_manual`, bypasses price validation)
- [x] Form auto-fills from `/approve` + the last 5 `/note` entries
      (`GET /dashboard/conversations/{psid}/order_draft`)
- [x] Note/approval state: compact `/n(N)`/`/a(N)` labels, history not hidden (a handled item shows
      dimmed, doesn't disappear), a "✗ Reject" flow with a required reason

**⚠️ Important note:** `price_overrides` is NOT an order — it's just a price/quantity permit. A
real order only exists in `orders` after order creation succeeds.

### Product & FAQ CRUD
- [x] Edit a product (`sku` can't be changed after creation); deletion is blocked if related
      orders/tiers exist
- [x] Price tiers: `PUT /products/{id}/tiers` replaces the entire list on every save
- [x] FAQ: a dedicated `faq_entries` table, written straight into `knowledge_chunks` on
      create/edit (no need to re-run `ingest.py`)
- [x] **"Layer 2" — RAG auto-sync for products** — each product automatically gets its own
      `knowledge_chunk` (`products.py`, embedding from `{sku} - {name}: {description}`), running
      unconditionally on every chat turn (independent of whether the LLM decides to call a tool) —
      more reliable than the `search_products` tool layer (which depends on the LLM's decision)
- [x] **"Layer 1" safety net** — `get_sku_summary_text()` injected directly into the system prompt
      every turn, emphasizing this is the SOLE and COMPLETE SKU list, never invent anything beyond it

### Metrics
- [x] `/dashboard/metrics/*`: messages/day by role, chat-to-order conversion rate, top unanswered
      questions (matched against a fixed fallback phrase, no NLP fuzzy matching)

### Real auth
- [x] Fully replaced the static `ADMIN_API_TOKEN` with per-staff login
      (`staff_users`/`staff_sessions`, session tokens via `secrets.token_urlsafe`, passwords hashed
      with `hashlib.pbkdf2_hmac` at 200k rounds — no JWT/bcrypt dependency added, to avoid a rebuild)
- [x] `/staff` page for account management (no role-based permissions yet — accepted limitation for
      a small team)
- [x] `scripts/create_staff_user.py` bootstraps the first account

**Accepted known limitations, not fixed further:**
- No role-based permissions (any staff can manage other accounts)
- No audit trail, no password change/reset via email
- Product descriptions used for RAG and the static `product_profile.md` don't auto-sync bidirectionally

**Key technical lesson:** when designing a tool schema for the LLM, don't hardcode assumptions about
current data (e.g. "only 1 product exists") into a parameter description — that assumption goes
stale the moment the data changes. LLM reliability (self-contradiction across turns) is an inherent
model issue, mitigated with multiple layers (lower temperature, live data outranking history, tool
results re-asserting themselves) rather than eliminated entirely.

---

## #9 · CI/CD GitLab + VPS deploy + monitoring
**Status:** 🟡 In progress — Batches 1-2/several done (the part that doesn't need a VPS)

**Goal:** The system runs 24/7 on a VPS, deployed automatically via GitLab CI/CD.

### Batch 1 — Technical debt cleanup + production prep
- [x] Dedup by `mid` (Redis `SET NX EX`, blocks duplicate webhook event processing)
- [x] Retry + dead-letter (`max_tries=3`, writes to the Redis list `dead_letter:messages` on the
      final failed attempt)
- [x] `asyncpg` connection pool (`app/db_pool.py`) — only the 2 hottest modules migrated so far
      (`conversation_log.py`, `products.py`); ~8 other services still connect directly
- [x] `embed()` offloaded to a thread pool (`embed_async()`)
- [x] Cleaned up the legacy `ADMIN_API_TOKEN` from config
- [x] A standalone `docker-compose.prod.yml`: no source bind-mounts, production dashboard build,
      DB/Redis ports not exposed, `POSTGRES_PASSWORD` required via env (tested to correctly error
      when missing)

### Batch 2 — Real CI tests
- [x] New `tests/` — 38 test cases / 60 assertions, focused on pure logic functions (no DB access):
      `is_valid_identifier`, `wants_human`, `validate_transition` (order state machine),
      `PHONE_RE`, `_unit_price_for_quantity`, `_hash_password`/`_verify_password`
- [x] `.gitlab-ci.yml`: removed the fake placeholder condition (`|| [ $? -eq 5 ]`) — CI now really
      fails; added a `build` stage (confirms `docker build` succeeds on the `main` branch)
- [x] Confirmed with a real run: 38/38 PASSED in the container

**Remaining (not yet done, needs a real VPS/domain):**
- [ ] Build a Docker image → deploy to VPS (SSH)
- [ ] Secrets in GitLab CI/CD variables (masked, protected)
- [ ] Reverse proxy + HTTPS (Caddy/Nginx + Let's Encrypt)
- [ ] Daily PostgreSQL backups
- [ ] Alerting on repeated webhook failures / LLM API failure
- [ ] `docs/DEPLOYMENT.md` (saved for when a real deployment process exists)

**Definition of done:** Pushing to `main` → auto-deploys; webhook uptime > 99%.

---

## #10 · Fallback customer channel via Telegram
**Status:** ✅ Closed (not part of the original backlog — arose from the Meta test-account lockout)

**Context:** Meta revoked the dev role on the test account, blocking testing through Messenger.
Added a separate Telegram channel for **customers** (distinct from the admin bot in #7/#8) as a
parallel test/dev channel.

**Tasks:**
- [x] `app/workers/telegram_customer_listener.py` — a separate bot (a different token from the
      admin bot), replies to anyone who messages it
- [x] `sender_id` formatted `tg:<chat_id>` — reuses `orchestrator.handle_message()` as-is, no
      AI/tool/RAG/handoff logic rewritten
- [x] Shares the `is_bot_paused`/message-logging logic with the Messenger worker

**Note:** not a replacement for Messenger — the Meta issue should still be worked in parallel
(Messenger remains the primary channel for real customers in Vietnam). No decision yet on a
longer-term direction (a custom website chat app, Zalo OA).

---

## #11 · Knowledge Base V2 (Ingestion → Retrieval → Router → Prompt Assembly → Guardrails → Test Suite)
**Status:** ✅ Closed — parallel to production, not yet integrated into the real bot

**Context:** New scope outside the original backlog — the Knowledge team sent a full Knowledge
Base architecture (governance, hybrid retrieval, Prompt Assembly, Runtime). Agreed scope: build
all 6 milestones (M1-M6) per the original `IMPLEMENTATION_PLAN.md`, **fully separate** from
`knowledge_chunks`/`rag.py`/the running production bot — no changes to #4 at all.

### M1 — Ingestion
- [x] `app/services/kb_ingest/` — a parser for 4 different front-matter formats (proper YAML, a
      single text line, bold with "& Locked", multi-line bold), heading-based chunking that
      auto-detects `primary_level`
- [x] `scripts/kb_normalize_source.py` — auto-normalizes a directory structure that drifted from
      spec (`skill/` vs `skills/`, misplaced FAQ)
- [x] `scripts/kb_ingest.py` — a full pipeline, manual atomic switch by design (prints the SQL,
      doesn't auto-activate)
- [x] Migration `011_knowledge_base_v2.sql` — 4 new tables, purely additive

### M2 — Retrieval
- [x] `app/services/kb_retrieval.py` — hybrid vector (pgvector) + lexical (Postgres tsvector) +
      Reciprocal Rank Fusion + domain/priority boost
- [x] **A serious bug fixed:** the initial domain boost coefficient (`P1: +0.03`) was larger than
      the max possible RRF score, causing P1-labeled content to dominate regardless of relevance —
      reduced to `1e-7` (a true tiebreaker only)
- [x] **An embedding bug fixed:** the heading was diluted in long-content embeddings — added a
      dedicated `embedding_text` field, with the heading repeat count auto-scaled by content length
      (≥~50% of the weight)
- [x] Confirmed: brewing/brand questions return the correct KU #1 with a score near the theoretical maximum

### M3 — Intent/Risk Router
- [x] `app/services/kb_router.py` — classifies per the "Decision Logic" already defined in
      `SKL-CON-001.md` (not invented), keyword/regex MVP (no LLM yet)
- [x] **2 bugs fixed:** missing diacritic normalization (VN customers often type without accents);
      substring false-match ("hỏng" caught inside "không") — added `\b` word boundaries
- [x] **A systemic bug fixed:** the regex only matched adjacent phrases, but real sentences insert
      a noun in between (e.g. "How do I brew **3S coffee**?") — added a gapped-match mechanism (`_gap_re`)

### M4 — Prompt Assembly
- [x] `app/services/kb_prompt_assembly.py` — exactly the 9 blocks from `PA-001`, empty blocks
      fully omitted, assembly logic driven by route (hides Knowledge when route=human/tool)

### M5 — Runtime Guardrails
- [x] `app/services/kb_runtime.py` — Pre-Generation Guardrails (real, based on existing data) +
      Post-Generation Validation (heuristic, clear limits — needs an LLM-as-judge for full evaluation)
- [x] Fallback F2 (Clarification), F3 (Honest uncertainty), F5 (Human handoff)
- [x] A bug fixed: the price pattern lacked a word boundary, "85 degrees" (temperature) was
      mistaken for a price mention

### M6 — P1 Smoke Test Suite
- [x] `tests/kb_eval/smoke.yaml` + `scripts/kb_eval_runner.py` — 10 test cases per the "Critical
      Routing Tests" table in `EV-003`/`EV-004`, with a severity-based Release Gate
- [x] **A bug only visible when testing the full pipeline:** `product_understanding` was missing
      the `faq` domain in the Router → Retrieval mapping table — a clear demonstration of the value
      of end-to-end testing over testing components in isolation

**Not yet done (out of agreed scope):**
- [ ] Integration into `orchestrator.py`/the real production bot
- [ ] Real `STYLE_CONTEXT` (Playbook via retrieval), a real token-based context budget
- [ ] Real Tool calls instead of mocked ones in tests, Fallbacks F1/F4
- [ ] Real atomic switch/rollback (currently `kb_units.id` is the sole primary key, overwritten on re-ingest)

---

## #12 · NLU layer (Normalization → Pattern Router → Semantic Router → Combined Pipeline → Real bot integration)
**Status:** 🟡 Being integrated into the production bot (Batches 1-2/several) — see the details from
Batch A through Batch 2 (orchestrator integration + Entity Extraction) in the sections below

**Context:** Upgrading #11's M3 Router (originally hardcoded regex) into an NLU system that
learns from real data — the Knowledge team sent `datasets/nlu/` (an intent catalog, normalization
rules, 300+ utterances, 150 held-out tests) per `NLU-INTEGRATION-GUIDE.md`.

### Batch A — Loader + Validator + Normalization
- [x] `app/services/nlu/` — reads `intent-catalog.yaml` (30 intents), `normalization.yaml` (100
      rules), `utterances/*.yaml` (300+ examples), `tests/*.yaml`
- [x] Validator: 0 errors on the real dataset (duplicate IDs, dangling intents, duplicate text,
      train/test leakage)
- [x] **A cascading bug fixed:** applying phrase rules sequentially let a later rule accidentally
      match the *output* of an earlier one (e.g. `"con ko"`/`"con k"` both produce `"còn không"`,
      then a 2nd rule re-matches on top of that, producing the wrong `"còn khônghông"`) — fixed by
      applying all phrase rules in a single simultaneous pass
- [x] 4 data gaps written up in `docs/NLU_DATASET_FEEDBACK-VI.md` for the Knowledge team (missing
      unaccented variants, missing abbreviation rules, a brand-name protection mechanism)

### Batch B — Pattern/Exact Router
- [x] Exact match (indexed on both `text` + `normalized_text`) + token overlap (Jaccard, a 0.6
      threshold — favoring safety over coverage, confirmed 0% wrong on held-out data)
- [x] Clear conclusion on scope: only handles utterances **close** to the training data (by design,
      a "fast path") — genuinely different phrasing requires the Semantic Router

### Batch B+ — High-Precision Rules (routing-rules.yaml, 25 priority rules)
- [x] `app/services/nlu/high_precision_rules.py` — matches by `priority`, automatically satisfies
      the "explicit action outranks a general complaint" policy just by picking the highest-priority match
- [x] **A serious homonym bug fixed:** stripping diacritics for matching caused "chưa" (extremely
      common, "not yet") and "chua" (rule RTE-012, "sour taste") to collapse into the same string —
      a different nature of bug than the earlier substring issue (this is a homonym collision at the
      whole-word level, `\b` boundaries don't help) — fixed by matching rules with diacritics
      preserved, while still `normalize()`-ing the query first so abbreviations are still handled
- [x] After the fix: the Pattern Router reaches 35.3% self-coverage with only 2.0% wrong (down
      from 25/150 to 3/150) — the 3 remaining cases are genuine rule-semantics ambiguity (a missing
      `b2b_inquiry` rule, the polysemous word "giống", unhandled negation in "not exchanging...
      wanting a refund instead") — written up in `docs/NLU_ACCURACY_IMPROVEMENT_PROPOSAL-VI.md`
- [x] Real protected phrases (`protected-phrases.yaml`: "3S Coffee", "Robanme", "Công ty Cổ phần
      Robanme") — processed longest-phrase-first when one phrase contains another

### Batch C — Semantic Router
- [x] Embeddings kept in memory (numpy, not pgvector — the "Intent Index" is small)
- [x] `decide_confidence()` — per-intent thresholds + a **margin check** (v1.1,
      `Top-1 - Top-2 ≥ 0.10`) per an updated spec from the Knowledge team
- [x] A dedicated embedding model for NLU (`paraphrase-multilingual-mpnet-base-v2`, kept separate
      from #11's embedder so as not to disturb the already-working Knowledge Base) — improved from
      38.3% → 55.0% correct after switching from the smaller MiniLM model

### Batch D — Combined pipeline
- [x] `app/services/nlu/router.py` — the Pattern Router runs first (fast, already proven at 2%
      wrong), the Semantic Router is the fallback when Pattern doesn't match
- [x] **Final accuracy result (7/18):** `nlu_combined_test.py --eval` on the 150 held-out tests —
      **Correct 120/150 (80.0%) | Wrong 23/150 (15.3%) | Clarify 7/150 (4.7%)**. By layer: the
      Pattern Router handles 56 utterances (37.3%), reaching **94.6% accuracy** within its own
      scope; the Semantic Router handles the remaining 94 (62.7%, fallback), reaching **71.3%** —
      matching the standalone number measured earlier. **~15 points below** the README's ≥95%
      target — the reason is clear: the Pattern Router is near-perfect but only covers 37% of
      utterances, with most falling through to the less-accurate Semantic Router.
- **Decision (7/18):** anh Hoài chose to **accept 80% as the current milestone**, pausing #12
  here to move to real bot integration instead of continuing to optimize further (options
  considered but not chosen: sending results to the Knowledge team requesting more
  utterances/rules to grow Pattern Router coverage; building Entity Extraction to unlock the 3
  skipped rules).

**Not yet done (continuing per the Integration Guide, beyond the Batch A-D scope):**
- [x] ~~Entity Extraction (Step 6)~~ → partially done in Batch 2 below (quantity/unit/order_id/
      payment_method/health_context/temperature; location/product not yet)
- [x] ~~Route Resolution (Step 8)~~ → done in Batch 1 below
- [ ] Context-aware Resolution (Step 5, multi-turn)
- [ ] Integration into `orchestrator.py`/the real production bot — **see the details in Batches 1-2 right below**

---

## Integrating #11 + #12 into the real production bot
Following the architecture in `NLU-INTEGRATION-GUIDE.md` Section 6 ("Orchestrator
Responsibilities"): the NLU does **NOT** generate answers or call Tools directly — it only
returns a route hint; the **Orchestrator** makes the actual decision.

### Safety design agreed with anh Hoài
- **Feature flag** `ENABLE_NLU_ROUTER` (default `false`) — anh Hoài decides when to turn it on.
- **Additive only, no replacement**: the NLU Router only adds one hint block to the current
  system prompt (the same way `rag_context`/`agent_notes` are already injected) — it doesn't
  block or replace the LLM+tool-calling flow that already works correctly.
- **Absolute safety**: every error on the NLU path (missing files, model failing to load...)
  is caught and SILENTLY ignored — it can never break the main reply flow; it returns an
  empty string instead of raising.
- **Fallback when unsure**: if `decision.action != "accept"` (Semantic Router
  context_check/clarify), **nothing is injected at all** — avoiding prompt noise from
  ambiguous suggestions.

### Coded
- **`app/services/nlu/route_resolution.py`** — Route Resolution (Step 8): looks up the `route`
  field in `intent-catalog.yaml` to know the exact action type (knowledge/tool/playbook/
  handoff) for each intent. Verified 8/8 tests against real data via sandbox.
- **An important finding when cross-checking against the real `tools.py`:** many `target`s in
  `intent-catalog.yaml` (e.g. `get_payment_options`, `get_cod_policy`, `get_shipping_quote`,
  `get_delivery_estimate`, `get_tracking_information`) have **NO corresponding real tool** in
  current production — only EXACTLY 3 pairs truly match: `get_current_price`→`search_products`,
  `get_current_stock`→`check_stock`, `create_or_confirm_order`→`create_order`
  (`TOOL_NAME_MAP` in `route_resolution.py`). Targets without a real tool still resolve
  correctly, but the calling module (`nlu_hint.py`) knows not to force a call to a nonexistent
  tool — it only emits a generic hint for that type.
- **`app/services/nlu_hint.py`** (new) — the single bridge orchestrator.py needs to call:
  `get_nlu_hint(message) -> str`. Caches the index (pattern + semantic) at module level,
  computing embeddings only ONCE when the worker process first loads (not on every message).
  The entire function is wrapped in try/except — verified via sandbox: simulated a load
  failure, confirmed it returns `""` as designed, without raising.
- **Integration into `orchestrator.py`** — exactly 1 block added after the current RAG step,
  entirely behind `if settings.enable_nlu_router:` — no other logic in the current flow changed.
- **`app/config.py`** + **`.env.example`** — added `ENABLE_NLU_ROUTER` (default `false`).
- **`scripts/nlu_hint_test.py`** (new) — a standalone CLI test for `get_nlu_hint()` to check
  BEFORE enabling the real flag in the bot — safer than testing directly via Messenger/Telegram.

### Not yet tested on anh Hoài's machine
**Step 1 — test the hint standalone, WITHOUT enabling the flag:**
```bash
docker compose exec api python scripts/nlu_hint_test.py "giá bao nhiêu"
docker compose exec api python scripts/nlu_hint_test.py "câu hỏi mơ hồ bất kỳ"
```
The first is expected to produce a hint (route=tool, suggesting `search_products`); the second
is expected to produce **no hint** (empty) since it isn't confident enough.

**Step 2 — only once Step 1 is fine, enable the real flag to test via chat:**
```bash
# add to .env: ENABLE_NLU_ROUTER=true
docker compose restart api worker telegram_bot telegram_customer_bot
```
Then chat through the Telegram customer bot (the test channel, #10) before considering real
Messenger.

**✅ STEP 1 CONFIRMED (7/18)** — anh Hoài tested 2 utterances: "giá bao nhiêu" ("how much") →
correct hint (`ask_price`, `exact_phrase`, confidence 1.0, suggesting `search_products`);
"hôm nay thứ mấy" ("what day is it today", out of scope) → **no hint** (empty), matching the
design of not injecting ambiguous suggestions. The `nlu_hint.py` bridge works correctly.
**Ready for Step 2** (actually enabling `ENABLE_NLU_ROUTER=true` to test via chat).

### Incident while testing Step 2 (7/18) — unrelated to the NLU code
After enabling the flag, `telegram_customer_bot` and `api` **crashed and stayed down** (no
auto-restart since the dev environment has no restart policy) — the bot went completely
silent. Log trace: `OSError: [Errno 5] Input/output error: '/srv'` — an I/O error while
importing `torch` (via the chain `orchestrator.py` → `products.py` → `embedder.py`, a
PRE-EXISTING dependency, unrelated to the newly added NLU code). This is a transient
infrastructure issue of Docker Desktop on Windows reading files over a bind-mount (most
likely triggered by many containers restarting in rapid succession during testing) — not a
logic bug.

**Recovery:** `docker compose up -d api telegram_customer_bot` (not `restart`, since the
containers had fully stopped) — confirmed both back to "Up".

### A real performance issue proactively fixed (7/18)
While diagnosing, discovered that `build_semantic_index()` was calling `nlu_embed_async()`
**one utterance at a time in a loop** (380 individual threadpool calls) instead of batching —
with a large model (mpnet-base-v2, 278M params) running on CPU, this could make the VERY
FIRST message after a container restart take a very long time (the bot appears
"unresponsive" even though it isn't actually crashed/hung). Fixed: added
`nlu_embed_batch_async()` in `nlu_embedder.py` (calls `model.encode()` EXACTLY ONCE for the
whole list, leveraging sentence-transformers' internal batching instead of 380 individual
calls) and updated `build_semantic_index()` to use it. Verified via sandbox: returns the
correct number of vectors for the input list.

### Not yet re-tested on anh Hoài's machine
1. Confirm `docker compose ps` still shows all 6 services "Up" (no more crashes).
2. Restart (Python code changed, no new dependency, so a restart is enough — no `--build`):
```bash
docker compose restart api worker telegram_bot telegram_customer_bot
```
3. Chat through the Telegram customer bot again — this time the first message after the
restart should be much faster (batch embedding instead of sequential).

**✅ CONFIRMED VIA REAL CHAT (7/18)** — anh Hoài tested a multi-turn conversation through
the Telegram customer bot (#10) after the recovery + performance fix — good quality, no
errors: correct answers on price/COD/brewing/factory SKUs, correctly understood slang
("mấy xèng"), no invented SKUs. Verifying whether the NLU directly contributed to each
individual answer (the hint is "invisible" in the output by design) was judged less
important than continuing with the Integration Guide. **Batch 1 complete.**

### Batch 2 — Entity Extraction (Step 6, 7/18)
`app/services/nlu/entity_extraction.py` (new) — regex/keyword extraction (no ML NER),
supporting: `quantity`, `unit`, `order_id`, `payment_method`, `health_context`,
`temperature`. **Not yet supported:** `location`/`product`/`taste_preference`/`brewing_method`
(needs a gazetteer/data that doesn't exist yet).

**The homonym bug recurred — the exact lesson from `high_precision_rules.py` re-applied:**
"ly" (a cup unit) and "lý" (as in "xử lý", "to handle") both become "ly" after stripping
diacritics, causing false unit matches in unrelated sentences. Fix: match with Vietnamese
diacritics preserved (only `quantity`/`order_id` — digits — use the stripped form, since
they're diacritic-insensitive).

**Integration into `high_precision_rules.py`:** added entity-gating — rules with
`entity_any`/`required_entity_any` conditions now check the actually extracted entities
instead of being skipped wholesale as before. Unlocks `RTE-008` (`ask_order_status`) and
`RTE-009` (`ask_tracking`) — both need `order_id`. `RTE-006` (needs `location`) **remains
explicitly skipped** since there's no place-name gazetteer yet — no wild guessing.

**✅ CONFIRMED (7/18)** — `nlu_pattern_test.py --eval`: self-coverage up from 35.3% →
**37.3%** (matching exactly the number of `order_id` cases unlocked), no new wrong cases.
**Batch 2 complete.**

**✅ OVERALL ACCURACY CONFIRMED AFTER BATCHES 1-2 (7/18)** — `nlu_combined_test.py --eval`:
Correct 121/150 (**80.7%**, up slightly from 80.0%) | Wrong 22/150 (14.7%) | Clarify 7/150
(4.7%). The Pattern Router handles 59/150 (**39.3%**, up from 37.3%). A small improvement
but in the right direction — exactly the 2 percentage points corresponding to the `order_id`
cases newly unlocked in Batch 2, consistent with the design.

**Not yet done (continuing from here per the Integration Guide):**
- [ ] Extend Entity Extraction (`location`, `product`) to unlock `RTE-006`
- [x] ~~Context-aware Resolution (Step 5, multi-turn, using `conversation_state`)~~ → done in Batch 3 below
- [ ] Deeper Knowledge Base V2 (#11) integration into `nlu_hint.py` (currently type=knowledge
      only emits a generic hint, doesn't actually call `kb_retrieval.search_kb()`)
- [ ] Cache (Step 10)

### Batch 3 — Context-aware Resolution (Step 5, 7/18)
`app/services/nlu/context_state.py` (new) — uses a `conversation_state` stored in Redis (24h
TTL, same as chat history) to help resolve ambiguous FOLLOW-UP questions (e.g. "Can this be
brewed cold?" then "What about two spoons then?"). True to the guide's spirit — "don't use
state to override the current message's clear intent" — state is **only** consulted when the
Router (Pattern+Semantic) is **already unsure** (`action != accept`), and the result is
**only** an additional reference hint, never forced.

**Finding while self-testing the "follow-up utterance" heuristic:** using the standalone
word "vậy" as an initial signal caused **2/6 wrong cases** — "3S Coffee là gì vậy" (a
complete, common question) and "Giá bao nhiêu" (≤ 4 words) were both mistaken for
follow-ups, because "vậy" is too common as an ordinary sentence-final particle. Fix: dropped
standalone "vậy", keeping only CLEARER-meaning phrases ("vậy còn", "thì sao"...) plus a list
of short-but-self-contained common utterances ("giá", "còn hàng"...) as exclusions.
Re-verified 7/7 tests via sandbox before landing the code.

**Integration:** `get_nlu_hint()` (`nlu_hint.py`) takes a new optional `sender_id` parameter
— on a successful route (`accept`), it stores the intent as context for next time; when
unsure AND the utterance "looks like a follow-up", it consults the stored context to suggest
(not force). `orchestrator.py` passes `sender_id` into the single existing call site.
`scripts/nlu_hint_test.py` gains `--context`, demoing 2 consecutive messages with the same
simulated `sender_id`.

### Not yet tested on anh Hoài's machine
```bash
docker compose exec api python scripts/nlu_hint_test.py --context
```
Expected: message 1 ("Loại này pha lạnh được không?" / "Can this be brewed cold?") gets a
normal hint (routed via Pattern/Semantic); message 2 ("Vậy hai muỗng thì sao?" / "What about
two spoons then?") is expected to get a hint like "possibly a follow-up question from prior
context..." rather than being completely empty.

**⚠️ A demo-utterance mistake self-detected and fixed (7/18):** in reality both messages
came back empty — it turned out message 1 ("Loại này pha lạnh được không?") **itself never
reaches `accept`** (no High-Precision Rule matches "pha lạnh" / "brew cold" specifically),
so nothing was ever stored in `context_state.py` for message 2 to consult — **not a
mechanism bug**, just a bad choice of demo utterance. Fixed `nlu_hint_test.py --context` to
use `"gia bao nhieu"` as message 1 (confirmed many times before to ALWAYS `accept` via
`exact_phrase`), and changed message 2 to "Vậy 60g thì sao?" ("What about 60g then?").

### Not yet re-tested on anh Hoài's machine
```bash
docker compose exec api python scripts/nlu_hint_test.py --context
```
Expected this time: message 1 gets an `ask_price` hint; message 2 gets a context-reference
hint (not empty).

**✅ FULLY CONFIRMED (7/18)** — after a restart, a Redis DNS issue (`Error -5 connecting to
redis:6379`) self-recovered (a transient Docker Desktop infrastructure issue, the same kind
as the earlier `/srv` error — not a code bug). Results: message 1 ("gia bao nhieu") →
correct `ask_price` hint; message 2 ("Vậy 60g thì sao?") → **a correct context-reference
hint**: "possibly a FOLLOW-UP question from prior context (most recent topic:
'ask_price')..." — exactly the intended design. **Batch 3 complete.**

🎉 **All 10/10 Steps in `NLU-INTEGRATION-GUIDE.md` are now implemented** (with some limits
noted explicitly: `location`/`product` entities not done, the Step 10 Cache not done,
Knowledge Base V2 still only a generic hint without real retrieval calls). This is a
reasonable stopping point for an overall evaluation before considering enabling
`ENABLE_NLU_ROUTER=true` for real Messenger (so far only tested via the Telegram customer
bot #10).

### Batch 4 — Really wiring Knowledge Base V2 (#11) into `nlu_hint.py` (7/18)
**A serious finding during anh Hoài's full review of the integration:** re-reading the
actual code confirmed that `nlu_hint.py` (from Batch 1) **NEVER calls**
`kb_retrieval.search_kb()` — the `type="knowledge"` branch only returns **1 generic
suggestion sentence**, never fetching real Knowledge Unit content from M1-M6. This is
exactly why in an earlier real conversation ("3s coffee của ai?" / "who owns 3s coffee?")
the bot answered "no specific information yet" instead of "Công ty Cổ phần Robanme"
(ingested as `SKL-BRAND-001` back in M1) — the bot was still using the old RAG (#4),
**not** Knowledge Base V2.

**Verified before fixing:** checked `kb_config.active_index_version` — confirmed it was
activated (`value = 3`), so `search_kb()` is ready to work correctly.

**Fixed:** added `_build_knowledge_hint()` (async) that really calls
`kb_retrieval.search_kb(message, top_k=2)`, injecting real Knowledge Unit content (not a
generic sentence) into the hint. **No specific domain filter** — the `targets` in
`intent-catalog.yaml` are asset-level (e.g. `SKL-PRD-001`) and don't map directly onto
`search_kb()`'s domain-level filter (e.g. `product`/`brand`) — for simplicity and safety,
`search_kb()`'s semantic+lexical ranking finds the most relevant content on its own.
Everything wrapped in try/except — keeping the safety principle applied throughout.

### Not yet tested on anh Hoài's machine
```bash
docker compose exec api python scripts/nlu_hint_test.py "3s coffee cua ai"
```
Expected: the hint now includes a "Related knowledge from the Knowledge Base..." section
with real content from `SKL-BRAND-001` (mentioning "Robanme"), instead of only the generic
sentence as before. Then re-test through the Telegram customer bot with the exact utterance
that hit the bug earlier ("3s coffee của ai?") to confirm the bot answers "Công ty Cổ phần
Robanme".

**✅ MECHANISM CONFIRMED WORKING (7/18)** — tested `"nguyên liệu là gì"` ("what are the
ingredients"; `ask_ingredients`, `high_precision_rule`, conf 0.95) → the hint now
**contains real Knowledge Unit content** (`[SKL-SAL-002]`, `[SKL-PRD-001]`) instead of the
generic sentence as before — confirming the Knowledge Base V2 wiring works correctly.

**An observation noted (non-blocking, a refinement for later):** `SKL-SAL-002` ("Customer
Intent Recognition") leaked into the results — it's an INTERNAL guidance document (an
intent-recognition playbook), not real customer-facing answer content — it got mixed in
because it also mentions "ingredients" as an illustrative example within the document.
Suggestion for later: filter the `conversation`/`playbook` domains out of
`_build_knowledge_hint()` (keeping only `product`/`brand`/`faq`/`sales` as genuine content)
to keep internal process documents out of the customer-answer context.

The specific utterances "3s coffee của ai?"/"3S Coffee là gì" need the Semantic Router
(Batch C) to be classified (the plain Pattern Router reports "no match") — this exact
utterance hasn't been tested end-to-end through `nlu_hint_test.py` yet (it needs the
Semantic Router to actually accept, not just Pattern), but the wiring mechanism is
confirmed correct. **Batch 4 complete mechanism-wise.**

### Batch 5 — Filtering internal documents out of the customer-facing context (7/18)
SQL investigation confirmed: `SKL-SAL-002` (domain=`sales`) is **an entire internal
playbook document** (26 units: "Purpose", "Priority rules", "Do"/"Don't", "Escalation",
"Traceability"...), not customer-facing answer content — and all 5 assets in the `sales`
domain (SKL-SAL-001..005) are the same playbook style. The `sales` domain has **113 units**
(the most of the 7 domains), so without filtering, the risk of pulling internal process
documents into the customer-answer context is very high.

**Fixed:** `_build_knowledge_hint()` now calls `search_kb(message, top_k=2,
allowed_domains=["brand", "product", "faq"])` — only the 3 domains confirmed REPEATEDLY in
this session to be genuine customer-facing content (FAQ-BREW-001, FAQ-BRAND-001, the
freeze-dried information...). Excludes `sales`/`conversation`/`customer_service`/`playbook`.

### Not yet tested on anh Hoài's machine
```bash
docker compose exec api python scripts/nlu_hint_test.py "nguyen lieu la gi"
```
Expected: the hint **no longer** contains `[SKL-SAL-002]`, only content from
`product`/`brand`/`faq` (e.g. `SKL-PRD-001`/`SKL-PRD-002`/`SKL-FAQ-001`).

### Batch 6 — Extending Entity Extraction: `location`/`product` (7/18)
`app/services/nlu/entity_extraction.py` — added `_extract_location()` (a gazetteer of 34
common Vietnamese place names, using stable names independent of administrative-boundary
changes) and `_extract_product()` (MVP — only recognizes size variants like "100g"/"25kg",
not full SKU names yet). Updated `high_precision_rules.py`: removed `location`/`product`
from `_ENTITY_UNSUPPORTED` — **unlocking the last rule, `RTE-006`**
(`ask_shipping_availability`, needs `location`) — all 3 entity-conditioned rules in
`routing-rules.yaml` are now unlocked (RTE-006/008/009). Only
`taste_preference`/`brewing_method` remain unsupported (more ambiguous, needing more
keywords to be precise).

Verified 7/7 entity tests + 2/2 `RTE-006` unlock tests via sandbox before landing the code.

#### The "unaccented Ca Mau" patch — a paste error found and fixed (7/23, new machine D:\alpha3s)
The `_extract_location` patch (matching place names when customers type without diacritics —
stripping diacritics on BOTH sides, returning the canonical accented form) had previously
been pasted by hand due to an MCP disconnection. Re-checking on the new machine found **a
paste error: the old `def` line wasn't deleted → 2 nested `def`s → SyntaxError, the whole
module failed to import** (the bot was running without entity extraction, the error
silently swallowed by the NLU path's try/except). Removed the redundant `def` line — the
remaining patch body is intact as originally written.

- Verified: the patch logic was simulated identically in Node (the new machine doesn't have
  Python/Docker yet) — 14/14 PASS, including real accented/unaccented pairs ("ship ve Ca Mau
  giup em", "giao hang di da nang", "minh o buon ma thuot"...) plus a word-boundary case
  ("camau" run together must NOT match).
- Added `scripts/nlu_entity_test.py` (a CLI test following the convention of the existing
  nlu_*_test.py scripts) for a real-Python confirmation once Docker is up.

### Not yet tested on anh Hoài's machine
```bash
docker compose exec api python scripts/nlu_entity_test.py --eval
docker compose exec api python scripts/nlu_pattern_test.py "shop co giao toi Ca Mau khong"
```
Expected: command 1 — all PASS (confirming the module imports + unaccented location matching
with real Python). Command 2 — `intent=ask_shipping_availability`,
`via=high_precision_rule` (previously it would have been skipped entirely due to `RTE-006`).

### Batch 7 — Cache (Step 10, 7/18)
`app/services/nlu/cache.py` (new) — caches only exactly what the guide's allowlist permits
("Normalized query → intent candidate"), 1h TTL. **Only `action="accept"` results are
cached** (already confident) — `context_check`/`clarify` are not cached (they depend on the
Batch 3 context; caching could cause mixups between different customers). **Knowledge Base
content is not cached** (`search_kb()` is still called fresh every time) — true to the
guide's "don't cache dynamic data" spirit.

Integrated into `get_nlu_hint()`: checks the cache before calling `route()`, writes to the
cache only when the result is `accept`.

### Not yet tested on anh Hoài's machine
```bash
docker compose restart api worker telegram_bot telegram_customer_bot
docker compose exec api python scripts/nlu_hint_test.py "gia bao nhieu"
docker compose exec api python scripts/nlu_hint_test.py "gia bao nhieu"
```
Run the same utterance **twice in a row** — the results must be identical (nothing
observable changes from the outside — the cache is an internal optimization, not a change
in displayed results).

### Batch 8 — No-regression check (7/18)
After all of Batches 4-7 (real KB V2 calls, domain filtering, new entities, cache),
`nlu_combined_test.py --eval` needs to be re-run to confirm no drop in accuracy on the 150
held-out tests (in theory there should be no impact, since the test suite measures intent
classification, not answer content/caching — but the new `location`/`product` entities
COULD change results, since they additionally unlock RTE-006).

### Not yet tested on anh Hoài's machine
```bash
docker compose exec api python scripts/nlu_combined_test.py --eval
```
Expected: accuracy **unchanged or slightly higher** than the previous **80.7%** mark (a
slight increase is plausible if any of the 150 tests are shipping questions mentioning a
place name); it must not drop.

---

### Per-cup price conversion: moved from prompt hardcode to the `search_products` tool — PO decision 7/23, done (7/23)
> Note: ISSUES-EN is still missing several other 7/23 entries (see ISSUES-VI); this
> section is added to keep the pair in sync for this specific change.

PO decision: the "170k/50 cups = ~3,400đ/cup" conversion used when a customer says
"too expensive" must NOT be hardcoded in `system_prompt.md` — cups-per-jar and
price-per-cup must be DATA (the `products` table), changeable via DB/dashboard
without touching the prompt.

- `migrations/012_products_serving.sql` — adds `products.net_weight_g` (INTEGER) +
  `products.serving_size_g` (NUMERIC(5,2)); seeds `3S-100G` = 100g, 2g/cup — keeps
  the current brand numbers (~50 cups/jar, ~3,400đ/cup), phrased per KB V2
  SKL-PRD-004 ("1 scoop ≈ 1g" → 2g = ~2 scoops). **Already applied by hand to the
  running DB** via `docker exec psql` (the initdb mount only runs on a fresh volume).
- `app/services/tools.py` — new `_serving_info()` helper; `search_products` now
  returns `serving_info`: `servings_per_unit_approx`, `price_per_serving_vnd_approx`
  (retail) + `price_per_serving_by_tier`, with a note telling the LLM to say
  "about/approximately" only. Products without serving data (NULL columns) → field
  omitted; the bot must not invent cup counts. The `TOOL_DEFINITIONS` description
  mandates using `serving_info` for the conversion instead of computing/remembering.
- `app/prompts/system_prompt.md` — removed both hardcodes (the "too expensive"
  bullet and "jar 100g, 2g/cup → ~50 cups/jar"), replaced with instructions to use
  `serving_info`. Note: the task description said the hardcode was "already
  deleted", but the file still had it — deleted in this pass. (The "coffee-shop
  25-30k/cup" comparison stays — market context, not product data.)
- Legacy RAG `data/knowledge/product_profile.md` + `faq.md` — removed the hard
  "2g/cup → 50 cups → 3,400đ/cup" conversions; also fixed the scoop-definition
  conflict (old faq: "2g = 1 level teaspoon" ≠ KB V2 "1 scoop ≈ 1g" → now "~2
  included scoops ≈ 2g"). ⚠️ **NOT re-ingested yet**: `knowledge_chunks` still holds
  the old text — run `docker compose exec api python scripts/ingest.py` AFTER
  merging this worktree branch into the main checkout (containers mount `D:\alpha3s`,
  they can't see worktree files).
- Sandboxed BEFORE touching real files (per project process): (1) SQL dry-run in a
  ROLLBACK transaction; (2) pure-logic tests 9/9 PASS (NULL/0/negative, non-integer
  division 250g÷1.5g, `Decimal` from NUMERIC, JSON-serializable); (3) ran a copy and
  then the ACTUAL edited `tools.py` inside the api container against the live DB →
  50 cups/jar, 3,400đ/cup (retail), 3,200đ (tier 5+), 2,800đ (tier 20+).
- Found along the way: the live `3S-100G` description already differs from the 001
  seed (it already says "1 scoop ≈ 1g", no "50 cups" — edited via dashboard
  earlier) — migration 012 guards with `LIKE '%50 ly%'` so it won't overwrite it.
- `docs/BACKEND_API-VI.md` + `-EN.md` — `search_products` row updated.

**Not yet tested on anh Hoài's machine (after merging the branch):**
- [ ] Restart api/worker to load the new `tools.py` + `system_prompt.md`, re-run
      scenarios S01/S03 (price question / "too expensive") — displayed numbers
      should be UNCHANGED (~3,400đ/cup) but sourced from `serving_info`.
- [ ] Re-ingest legacy RAG (command above) and check the new "unit economics" chunk.

## Suggested next priority order
1. **Integrate #11 + #12 into `orchestrator.py`/the real production bot** — the latest decision
   (7/18), replacing further #12 accuracy optimization.
2. **#1** — rotate `META_APP_SECRET`/`PAGE_ACCESS_TOKEN` (independent, should be done soon if not
   already).
3. **#9** — real VPS deployment once infrastructure exists, so #11/#12 have a real operating
   environment.

## Reference documentation (`docs/`)
- `docs/DATABASE-EN.md` — schema, migration history, common lookup SQL
- `docs/DASHBOARD-EN.md` — every dashboard page/button, mapped to the right endpoint
- `docs/TELEGRAM_BOT-EN.md` — the 2 Telegram bots (admin/customer), commands, how to create a new bot
- `docs/BACKEND_API-EN.md` — the full FastAPI backend, services/workers, environment variables, known limitations
- `docs/KNOWLEDGE_BASE_V2_DESIGN-VI.md` — detailed design for #11 (Vietnamese only)
- `docs/NLU_DATASET_FEEDBACK-VI.md`, `docs/NLU_ACCURACY_IMPROVEMENT_PROPOSAL-VI.md` — data
  feedback sent to the Knowledge team for #12 (Vietnamese only)
- **Not yet done:** `docs/DEPLOYMENT.md` (saved for when #9 has a real VPS)
