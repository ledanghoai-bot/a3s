> English translation of NLU_LAYER-VI.md (source of truth is the Vietnamese version).

# NLU Layer (#12) — As-built documentation

> Describes the NLU Layer **as it actually runs** in production (updated 23/7/2026, after
> the PO decision to chop the Semantic Router). Original design follows `NLU-INTEGRATION-GUIDE.md`
> from team Knowledge (10 steps); this document records what has been DEPLOYED, the decisions
> that deviate from the guide, and the reasons. Status/history of each batch: see `ISSUES-VI.md`
> section #12 and Bat 1-8 (work batches).

## 1. Role in the system — responsibility boundaries

The NLU **does not answer customers and does not call tools**. It only generates a **hint**
snippet injected into the system prompt; `orchestrator.py` (the DeepSeek LLM) retains full
decision-making authority. The entire NLU path is wrapped in try/except — an error anywhere
returns an empty string and **never** breaks the main reply flow.

```
Customer message
   │
   ▼
orchestrator.handle_message()
   │  (ENABLE_NLU_ROUTER=true)
   ▼
nlu_hint.get_nlu_hint(message, sender_id)
   │
   ├─ 0. Cache (Redis, TTL 1h, "accept" results only)
   ├─ 1. Pattern Router  ── match → intent hint (+ KB V2 if type=knowledge)
   ├─ 2. (Semantic Router — CURRENTLY OFF, see §4)
   ├─ 3. Context-aware Resolution — short follow-up → hint from prior context
   └─ 4. Fallback knowledge hint — search_kb() MiniLM, cosine filter ≤ 0.55
   │
   ▼ (hint string or "")
system prompt += "## NLU classifier suggestion (reference only, not mandatory)"
```

## 2. File map

| File | Role |
|---|---|
| `app/services/nlu_hint.py` | The single bridge between orchestrator ↔ NLU; module-level index cache; fallback knowledge hint |
| `app/services/nlu/router.py` | Pattern → (Semantic) pipeline; receives `semantic_index=None` when the semantic tier is off |
| `app/services/nlu/pattern_router.py` | Exact match + token overlap (min_overlap 0.6) over the normalized utterance library |
| `app/services/nlu/high_precision_rules.py` | 25 rules RTE-001..025 from `routing-rules.yaml`, ordered by `priority`, supports entity conditions |
| `app/services/nlu/entity_extraction.py` | Regex/keywords: quantity, unit, order_id, payment_method, health_context, temperature, location (gazetteer of 34 place names), product (size variants) |
| `app/services/nlu/normalizer.py` | Restores diacritics/abbreviations per `normalization.yaml` + protected phrases |
| `app/services/nlu/semantic_router.py` | Fallback tier using mpnet — **currently off**, code kept intact |
| `app/services/nlu/nlu_embedder.py` | Separate mpnet model for NLU — only loaded when `ENABLE_SEMANTIC_ROUTER=true` |
| `app/services/nlu/route_resolution.py` | intent → suggested action (tool / knowledge / handoff) per `intent-catalog.yaml` |
| `app/services/nlu/context_state.py` | Redis storage of confirmed intents, serving follow-up sentences (Step 5) |
| `app/services/nlu/cache.py` | Cache of normalized query → decision (only `accept`), TTL 1h |
| `app/services/nlu/loader.py` | Reads datasets/nlu/*.yaml + utterances |
| `datasets/nlu/` | Data from team Knowledge: 380 utterances, 30 intents, 25 rules, normalization, protected phrases |
| `datasets/tests/` | 150 held-out tests (intent-routing-tests) |

## 3. Configuration (.env)

| Variable | Current | Meaning |
|---|---|---|
| `ENABLE_NLU_ROUTER` | `true` | Enables/disables the ENTIRE NLU layer (off = bot runs as before #12) |
| `ENABLE_SEMANTIC_ROUTER` | `false` | The mpnet semantic tier. **Off per PO decision 23/7** — when off, mpnet is never loaded (worker gets ~1.1 GB lighter); re-enable if the model gets quantized or the VPS has spare RAM |

## 4. Status of each tier + measurements (150 held-out tests)

| Tier | Status | Measurement |
|---|---|---|
| Pattern Router (exact + token overlap) | ✅ Running | Covers 40% of queries, **93.3-94.6% correct within its coverage** |
| High-precision rules + Entity | ✅ Running | Counted within Pattern; RTE-006/008/009 unlocked thanks to entities |
| Semantic Router (mpnet) | ⛔ **Off** (PO 23/7) | While still on: 71.3% on the 60% of fallback queries; most returned `context_check` so it **inherently produced no hint** — chopping it changes bot behavior almost not at all |
| Cache (Step 10) | ✅ Running | TTL 1h, only caches `accept` |
| Context-aware (Step 5) | ✅ Running | Short follow-up sentence → hint about the most recent topic |
| Fallback knowledge hint | ✅ Running (new 23/7) | search_kb MiniLM, top_k=4, cosine ≤ 0.55 — threshold chosen from real measurements (relevant 0.35-0.53, irrelevant 0.53-0.73) |
| Combined (while semantic was still on) | reference | 80.7% (121/150) — the pre-chop baseline |

**Why the semantic tier was chopped + why not much is lost:** see the full analysis in
`KB_NLU_RESOURCE_ASSESSMENT-VI.md` (PA2-5a) — summary: the semantic tier consumes ~1.1 GB
of RAM (the mpnet model) but is the least accurate tier and rarely reaches the `accept`
threshold to produce a real hint. The fallback search_kb replaces its knowledge value with
**0 extra RAM** (MiniLM is already loaded for KB V2).

## 5. Hint types injected into the prompt

1. **Intent hint** (Pattern match): intent name + confidence + via.
2. **Tool hint** (intent type=tool): "ALWAYS call tool `<name>` to answer accurately".
3. **Handoff hint** (intent type=handoff): consider `escalate_to_human` — with a reminder
   to FOLLOW the complaint-handling order (ask for the order id first, unless the customer
   demands a human).
4. **Knowledge hint** (intent type=knowledge): real Knowledge Unit content from
   `search_kb()` (domain brand/product/faq, top_k=2).
5. **Context hint**: short follow-up sentence → mentions the most recent topic, not binding.
6. **Fallback knowledge hint**: pattern miss + not a follow-up sentence → search_kb
   top_k=4 filtered at cosine ≤ 0.55; the preamble explicitly says "not certain — ignore if
   off-topic"; nothing found → stays silent ("").

## 6. Hard-won lessons baked into the design (read before editing)

- **Homophones when stripping Vietnamese diacritics** — the most frequently recurring bug
  class in the project: "chưa/chua" ("not yet" vs. "sour"), "ly/lý" ("cup/glass" vs. "lý" as
  in "xử lý", to process), "hỏng"~"không" ("broken" vs. "no/not", substring collision),
  "Ca Mau/Cà Mau" (unaccented user input vs. accented gazetteer — the reverse direction).
  Rule: match rules/keywords WITH DIACRITICS KEPT; only strip diacritics when stripping
  BOTH sides consistently (as with the location gazetteer); always use `\b`; test both the
  accented/unaccented pair.
- **Fully unaccented sentences fail to trigger RTE rules** (`normalize()` does not yet
  restore phrases such as "co giao toi" → "có giao tới", "do you deliver to") — proposed
  to team Knowledge to add PHRASE-LEVEL mappings to normalization.yaml (phrases of ≥2 words
  avoid single-word homophones).
- **Batch encode in one pass** instead of a per-sentence loop (380 utterances once took
  many minutes when called one by one — see the docstring in `nlu_embedder.py`).
- **Importing torch pays ~300MB RSS up front** — do not import `semantic_router`/
  `sentence_transformers` at module level in production code; use lazy imports inside the
  branch that needs them (see `router.py`).
- **A hint is only a suggestion** — every word in a hint must say "for reference, not
  mandatory"; a hint once tempted the LLM to skip steps in the complaint process until the
  ordering reminder was added.

## 7. Test suite & how to run

```bash
docker compose exec api python scripts/nlu_pattern_test.py --eval    # pattern-only, 150 held-out
docker compose exec api python scripts/nlu_pattern_test.py "cau hoi"
docker compose exec api python scripts/nlu_entity_test.py --eval     # entity, có cặp dấu/không dấu
docker compose exec api python scripts/nlu_combined_test.py --eval   # cần bật semantic (tải mpnet)
docker compose exec api python scripts/nlu_hint_test.py "cau hoi"    # hint end-to-end như orchestrator thấy
docker compose exec api python scripts/measure_embedding_rss.py      # đo RAM 2 model (A3)
```

## 8. Known limits / deferred work

- Knowledge queries outside pattern coverage depend on the fallback search_kb (the 0.55
  threshold has edge cases: "cho anh 5 hũ" ("give me 5 jars") at d=0.530 may let a light FAQ
  hint through — accepted, the preamble mitigates it).
- `taste_preference`/`brewing_method` have no entity extraction yet (ambiguous, lacking data).
- Semantic Router is off — to re-enable: quantize mpnet (PA2-5d) then
  `ENABLE_SEMANTIC_ROUTER=true`, re-run `nlu_combined_test.py --eval` against the 80.7% baseline.
- Overall accuracy while semantic was still on stopped at 80.7% (README target ≥95%) — path
  to improve: add utterances/rules from team Knowledge (see `NLU_ACCURACY_IMPROVEMENT_PROPOSAL-VI.md`).
