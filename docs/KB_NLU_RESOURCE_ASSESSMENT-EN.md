> English translation of KB_NLU_RESOURCE_ASSESSMENT-VI.md (source of truth is the Vietnamese version).

# Independent assessment: KB V2 + NLU layer on a 4GB VPS budget

> **Nature of this document:** an INDEPENDENT technical analysis, based solely on (1) real
> measurements taken on 23/7/2026 on the dev machine (i7-3720QM, Docker Desktop/WSL2) and
> (2) direct reading of the code in the repo. It does NOT inherit conclusions from CA's
> guiding documents (AGW-ARCH/IMPL/REVIEW) — from the budget figures it takes exactly 1
> input parameter: target VPS of 2 vCPU / 4 GB RAM / 60 GB disk.
>
> Prepared by: Claude Code (dev session 23/7). Decision maker: anh Hoài (PO).

---

## 1. What the system actually has (per the code, not the docs)

Two independent subsystems, both loaded into the **worker** when processing messages:

| Subsystem | Embedding model | Parameter size | Actual role in the reply flow |
|---|---|---|---|
| **KB V2** (#11) | `paraphrase-multilingual-MiniLM-L12-v2` (384 dims) | 118M | Finds real content (24 assets / 364 Knowledge Units) to inject into the system prompt — **the knowledge source for answering customers** |
| **NLU** (#12) | `paraphrase-multilingual-mpnet-base-v2` (768 dims) | 278M | Guesses intent to inject **1 hint sentence** into the system prompt — the LLM retains full decision authority |

The key point about ROLES (directly affects the "can we drop it?" assessment):
- KB V2 produces **content** — drop it and the bot loses its brand/product knowledge.
- NLU only produces a **reference hint** ("not mandatory" — verbatim in the prompt of
  `orchestrator.py`). The entire NLU path is wrapped in try/except; on error the bot
  still replies.
  → NLU is a **conditional quality-improvement layer**, not a life-critical layer.

NLU actually consists of 3 tiers with very different RAM costs:

| NLU tier | Needs a model? | RAM | Measured accuracy (150 held-out) |
|---|---|---|---|
| Pattern Router (exact + token overlap) | No | ~a few MB | **94,6%** within a coverage of 40,0% of sentences |
| High-precision rules (25 RTE) + Entity Extraction | No | ~negligible | included in the Pattern figure above |
| Semantic Router (mpnet, fallback) | **YES — this is the 1,1 GB chunk** | see §2 | **71,3%** on the remaining 60% of sentences |

Full pipeline: 80,7% correct / 14,7% wrong / 4,7% clarify.

---

## 2. Actual resource measurements (23/7, dev machine)

### 2.1. Embedding model RAM (VmHWM — peak, each scenario in its own process)

| Scenario | Peak |
|---|---|
| Bare Python interpreter | 12 MB |
| MiniLM only (KB), after a real encode | **1.126 MB** |
| mpnet only (NLU), after a real encode | **1.132 MB** |
| Both models in 1 process | **1.532 MB** |

Important technical observations:
- Most of the cost is the **shared PyTorch + sentence-transformers runtime** (~600-700
  MB), not the model weights. Evidence: loading the 2nd model into the same process costs
  only **+400 MB**, whereas standalone it costs 1.132 MB.
- Architectural consequence: **combining the 2 models into 1 process is far cheaper than
  2 separate processes** (1,53 GB vs 2,26 GB). And conversely: any process that
  "accidentally" imports torch pays ~300 MB up front even before loading any model.

### 2.2. Encode latency per message (warmed up, average of 10 runs)

| Model | ms/sentence |
|---|---|
| MiniLM (KB) | **65 ms** |
| mpnet (NLU) | **177 ms** |

→ On 2 vCPU, encoding is NOT a latency bottleneck (DeepSeek LLM calls are measured in
seconds). CPU only becomes an issue when **building the semantic index at startup**
(batch of 380 utterances, tens of seconds) — happens once per worker restart, acceptable.

### 2.3. Per-database resources (actually measured)

**PostgreSQL** (container `db`: 75 MB RAM near idle):

| Table | Total size | Of which index | Notes |
|---|---|---|---|
| `kb_units` (364 rows, 384d vectors) | **2,1 MB** | 1,1 MB | The entire "vector database" of KB V2 |
| `kb_assets` (24 rows) | 72 kB | — | |
| `knowledge_chunks` (legacy RAG #4) | 48 kB | — | empty on the new machine |
| All remaining tables combined | < 0,5 MB | — | orders/messages/customers... still empty |

Conclusion for Postgres: **the data is so small it is meaningless for RAM**. Postgres RAM
is determined by CONFIGURATION (`shared_buffers`, connection count), not by data. A
brute-force scan over 364 rows × 384-dim vectors reads only ~0,5 MB per query — no need
to even discuss IVF/HNSW indexes at this scale. Projection: even if the KB grows ×100
(36.400 units) the vector table would only be ~210 MB — still well within 4GB.

**Redis** (container `redis`: **10 MB**): holds the arq queue + NLU context (TTL) +
intent cache (TTL 1h). Everything is small keys with TTLs → growth is bounded. Just set
`maxmemory 128mb` + policy `allkeys-lru` to fully close off the risk.

**A separate "vector DB": there is NONE** — pgvector lives inside Postgres, no extra
service. The NLU semantic index (380 utterances × 768d) lives in worker RAM: **~1,2 MB**
— negligible; the heavy piece is the MODEL that produces it, not the index.

### 2.4. Actual running container RAM (docker stats, dev mode)

| Container | Measured RAM | Interpretation for production |
|---|---|---|
| worker | 350 MB (model NOT loaded yet — lazy) | → **~1,85-1,9 GB** after the first message (350 + 1.532) |
| api | 1,7 GB (noisy: contains model page cache from test commands exec'd into it) | → ~300 MB if it does NOT embed; **~1,4 GB if it does** (see §3) |
| telegram_customer_bot | 371 MB ⚠️ | suspected import chain pulling in torch — worth auditing, could save ~300 MB |
| telegram_bot | 38 MB | a "clean" listener — proves a polling bot only needs ~40 MB |
| dashboard (next dev) | 132 MB | production build estimated ~150-250 MB |
| db | 75 MB | with `shared_buffers=256MB` + connections → ~350 MB |
| redis | 10 MB | capped at 128 MB |

---

## 3. Answering the main question: is 4 GB feasible?

### Risk number 1, found from the code (independent of any document)

`app/services/products.py` and `app/services/knowledge_entries.py` (dashboard routes in
**api**) both import `embed_async` → editing KB/products from the dashboard will make
**api load MiniLM a second time** (~+1,1 GB in addition to the worker). Similarly,
`telegram_customer_bot` is occupying 371 MB in the "torch paid up front" fashion.

### Three scenarios on a 4 GB VPS (estimated from measurements, production build)

| Component | KB1: leave code as-is | KB2: force embedding into worker only | KB3: KB2 + trim listener imports |
|---|---|---|---|
| worker (2 models) | 1,90 GB | 1,90 GB | 1,90 GB |
| api | 1,40 GB (embeds when dashboard is used) | 0,30 GB | 0,30 GB |
| 2 Telegram bots | 0,41 GB | 0,41 GB | 0,10 GB |
| Postgres | 0,35 GB | 0,35 GB | 0,35 GB |
| Redis (capped) | 0,13 GB | 0,13 GB | 0,13 GB |
| dashboard (prod) | 0,20 GB | 0,20 GB | 0,20 GB |
| OS + Docker + proxy | 0,45 GB | 0,45 GB | 0,45 GB |
| **Total** | **~4,8 GB — OVERFLOW** | **~3,7 GB** | **~3,4 GB** |

### Feasibility conclusion

- **4 GB is CONDITIONALLY feasible** — not "comfortably feasible":
  1. It is MANDATORY to force embedding to live only in the worker (route the 2 dashboard
     paths through the queue) — otherwise it overflows the moment a staff member edits
     the KB while the bot is busy (KB1).
  2. The imports in `telegram_customer_bot` should be trimmed (+0,3 GB for nothing).
  3. 2-4 GB of swap is a safety net, not a place to run permanently.
- Safety margin after doing all of the above: **~0,6 GB (KB3)** — thin. Everything
  unexpected (index-build spikes on restart, overnight backups, image upgrades) eats
  into this margin.
- This is a system that **runs but has no room to breathe** — operations must be
  disciplined (RAM alerts, orderly restarts, no new services).

---

## 4. Option 1 (PO's proposal): increase RAM to 6 GB

**Impact:** the worst-case total demand (KB1 ~4,8 GB) < 6 GB → even the "forgot the
guardrail, dashboard embeds inside api" scenario does NOT die. The safety margin of the
correct scenario (KB3 ~3,4 GB) rises to **~2,6 GB** — the system gets real breathing
room.

| Criterion | Assessment |
|---|---|
| Technical | Absolutely feasible — not a single line of code changes, no accuracy re-measurement |
| Cost | VPS 4→6/8 GB typically differs ~50-100% in rental price (~a few hundred thousand ₫/month). Note: many providers do not offer a 6 GB tier — the practical choice is often **8 GB** |
| Time | 0 dev days |
| Risk | Near zero. The only risk is "RAM masking an architectural flaw": double-loading the model is still waste, it just no longer kills the system |
| What it does NOT solve | The 2 vCPU CPU (unchanged — but §2.2 shows encoding is not the bottleneck); the habit of every process importing torch |

**Conclusion for Option 1: highest feasibility, trading money for safety + schedule.**
Even if choosing Option 1, item 3.1 (forcing 1 process) SHOULD still be done as
architectural hygiene — later, not urgent.

---

## 5. Option 2 (PO's proposal): redesign KB+NLU, or drop NLU

Assessment of each variant — with accompanying numbers:

### 5a. Drop ONLY the Semantic Router (keep Pattern + Rules + Entity) — "dropping NLU in the right place"
- Savings: mpnet leaves the worker → worker drops to ~1,4-1,5 GB → KB3 total drops to
  **~3,0 GB** → safety margin ~1 GB on 4 GB. This is the only large chunk of RAM that
  can be dropped without touching the KB.
- What is lost: 60% of sentences no longer get an intent hint (the LLM handles them on
  its own as before #12 — the bot STILL runs). What is lost is the layer with the
  **lowest** accuracy in the system (71,3%). What is KEPT
  (Pattern+Rules+Entity, 94,6% within 40% coverage) is nearly **RAM-free**.
- Caveat: the real value of the semantic hint for FINAL ANSWER QUALITY has never been
  A/B tested — the 71,3% figure is classification accuracy, not its contribution to
  customer experience. A decision to drop it would rest on reasoning, not direct
  measurement.
- Effort: ~0,5-1 day (flag to disable semantic + re-run the 150 tests + update docs).

### 5b. Share MiniLM for NLU as well (1 model for both subsystems)
- **ELIMINATED by existing data:** measured on 18/7 — the semantic router running MiniLM
  reached only **38,3%** on 60 held-out (the reason mpnet was chosen from the start).
  Saving 400 MB in exchange for a classifier worse than a coin flip is a losing trade.

### 5c. Replace the Semantic Router with the LLM itself (DeepSeek classifies intent in the prompt)
- RAM = 0 (no 2nd model), latency +0 if merged into the existing LLM call, token cost
  negligible at DeepSeek's unit price.
- In essence: this is "5a but compensating for the loss with a better prompt" — the LLM
  classifies its own intent; quality depends on DeepSeek (not controllable/measurable
  with the 150-test set in the cleanly separated way it is today).
- Effort: ~1 day (prompt engineering + manual evaluation).

### 5d. Quantize/ONNX int8 for mpnet (keep the NLU architecture unchanged)
- mpnet int8 estimated ~300-400 MB instead of ~1,1 GB → 2 models + runtime down to
  **~0,9-1,1 GB** → KB3 total down to ~2,9-3,1 GB on 4 GB. Preserves the ENTIRE current
  NLU value.
- Risk: accuracy typically drops slightly (1-2 points) — the 150-test set MUST be re-run
  to confirm; adds dependencies (optimum/onnxruntime); effort ~1-2 days.

### 5e. Hosted embedding API (push encoding off-box)
- RAM ~0, but in exchange: network dependency for EVERY message, extra ~100-300 ms/call,
  extra recurring cost, and loss of the current advantage of "local embedding, no API
  key needed". For a system short on RAM but not on CPU, this is the least attractive
  trade-off.

### As for the KB itself: can it be "redesigned"?
It should not be. KB V2 is where the real value lives (the content answered to
customers), MiniLM is 65 ms/sentence, the data is 2,1 MB, and the alternative (plain
full-text search) is poor for Vietnamese (no word segmentation, homonyms when diacritics
are stripped — exactly the class of bug this project has hit repeatedly). The KB's RAM
cost (~1,1 GB standalone, +400 MB when co-located in the process) is a **core cost worth
paying**.

---

## 6. Summary & recommendations

| Option | Est. total RAM (correct scenario) | Margin on 4GB | Dev effort | Functional loss | Feasibility |
|---|---|---|---|---|---|
| Keep as-is + 1-process guardrail (baseline §3) | ~3,4 GB | ~0,6 GB — thin | 1-2 days | None | ✅ conditional |
| **Option 1: 6 GB RAM (or 8 GB)** | ~3,4 GB / 6 GB | **~2,6 GB** | 0 | None | ✅✅ highest |
| Option 2-5a: drop semantic router | ~3,0 GB | ~1,0 GB | 0,5-1 day | Hints for 60% of sentences (the 71,3% layer) | ✅ high |
| Option 2-5d: quantize mpnet | ~3,0 GB | ~1,0 GB | 1-2 days | Possibly -1-2 accuracy points | ✅ high |
| Option 2-5b: shared MiniLM | ~3,0 GB | ~1,0 GB | 0,5 day | Semantic collapses to 38,3% | ❌ eliminated |
| Option 2-5e: hosted API | ~2,3 GB | ~1,7 GB | 1-2 days | Network dependency/cost/latency | ⚠️ low |

**Preparer's recommendations (for the PO to decide):**
1. Whichever option is chosen, implement the **1-process guardrail** (route the
   dashboard's 2 embed paths through the worker + trim telegram_customer_bot imports) —
   this is an architectural flaw to fix, not an optional optimization.
2. If the budget allows: **Option 1** — cheap compared to dev days, and it widens the
   safety margin for Stages C-E (Chặng C-E) as well (terminal, web, Zalo will all
   consume additional RAM on the same VPS — something the table in §3 does NOT yet
   account for).
3. If 4 GB must be kept: **Option 2-5d (quantize)** first — preserves functionality;
   **Option 2-5a** (drop semantic) is the simple escape hatch if 5d runs into trouble.
   Do NOT "drop NLU" entirely — Pattern+Rules+Entity is nearly RAM-free and is the most
   accurate part of the system.
4. The most important numbers still to be measured on the real VPS (HOST-003): repeat
   exactly the `scripts/measure_embedding_rss.py` script + `docker stats` after deploy —
   the dev-machine numbers are a good estimate, not a commitment.
