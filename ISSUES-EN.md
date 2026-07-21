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
| 12 | NLU layer (Normalization → Pattern Router → Semantic Router → Combined Pipeline) | ✅ Paused at 80% (accepted milestone) |

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

## #12 · NLU layer (Normalization → Pattern Router → Semantic Router → Combined Pipeline)
**Status:** ✅ Paused at 80% — anh Hoài accepted the current milestone, moving to real bot integration

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

**Not yet done (paused, out of the decided scope):**
- [ ] Entity Extraction (Step 6) — 3 rules in `routing-rules.yaml` with entity conditions are
      explicitly skipped since this layer doesn't exist yet
- [ ] Full Route Resolution (Step 8), Context-aware Resolution (Step 5, multi-turn)
- [ ] Integration into `orchestrator.py`/the real production bot — **next priority**

---

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
