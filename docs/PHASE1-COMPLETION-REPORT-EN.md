# Issue #9 Completion & Phase I Summary Report — Alpha3S

> **Date:** 2026-07-24 · **Author:** Claude Code (at Hoài's request)
> **Purpose:** Confirm Phase I is complete so the design team can sign off and open **Phase II —
> Alpha3S Gateway (Customer Terminal)**.
> Vietnamese version: `docs/PHASE1-COMPLETION-REPORT-VI.md`.

---

## 1. Executive summary

**Alpha3S Phase I is complete and running in production 24/7 on a real VPS.** The sales chatbot
(RAG + Knowledge Base V2 + NLU Layer + tool-calling + dashboard) has been packaged, tested, and
**all customer channels (Messenger + Telegram) have been cut over to the VPS**, with automated
CI/CD, HTTPS, daily backups, and alerting.

All 12 Phase I backlog issues are closed. The last open one — #9 (CI/CD + VPS deploy + monitoring)
— was completed in the 2026-07-23–24 session. The system now qualifies as the **"brain" foundation
(the App)** for the Phase II Gateway architecture.

---

## 2. Issue #9 — CI/CD + VPS deploy + monitoring (final Phase I item)

| Item | Result |
|---|---|
| **Production VPS** | Ubuntu 24.04, 4 vCPU / 8GB / 60GB (`160.30.157.235`). Docker + Compose, 2G swap, `ufw` allowing only 22/80/443. |
| **SSH security** | Key-only login (`PasswordAuthentication no`); root password fully disabled. |
| **CI/CD** | **GitHub Actions** — push `main` → lint (ruff) + test (pytest) + auto-deploy to VPS over SSH. Moved off GitLab (paid + blocked CI due to unverified identity). |
| **HTTPS** | Caddy + Let's Encrypt, automatic, for `a3s.robanme.com` (API/webhook) + `a3s-dash.robanme.com` (dashboard). |
| **Backup** | Daily `pg_dump` at 03:00 (VN time), keeps 14 copies; real run verified. |
| **Alerting** | 5-min cron: error queue (dead-letter) / dead container / disk >85% → admin Telegram group. |
| **Cutover** | All customer + admin channels (Messenger + 2 Telegram bots) moved to the VPS (see §4). |
| **Docs** | `DEPLOYMENT-{VI,EN}.md` (technical reference) + `VPS-RUNBOOK-{VI,EN}.md` (hands-on runbook for staff to operate without AI). |

**Definition of done met:** push `main` → auto-deploy (proven repeatedly); system runs 24/7 on the VPS.

---

## 3. Phase I summary (Issues #1–#12)

| # | Item | Status |
|---|---|---|
| 1 | Messenger webhook + Meta verification | ✅ |
| 2 | Redis queue + arq worker | ✅ |
| 3 | PostgreSQL + pgvector (schema/migration/seed) | ✅ |
| 4 | RAG pipeline (ingest + search) | ✅ |
| 5 | System prompt & brand voice | ✅ |
| 6 | Tool calling (search_products / check_stock / create_order / escalate) | ✅ |
| 7 | Human handoff (`bot_paused`) | ✅ |
| 8 | Admin dashboard + analytics | ✅ |
| 9 | CI/CD + VPS deploy + monitoring | ✅ (completed this session) |
| 10 | Fallback customer channel via Telegram | ✅ |
| 11 | **Knowledge Base V2** (Ingestion→Retrieval→Router→Prompt Assembly→Guardrails→Test) | ✅ wired into the live bot |
| 12 | **NLU Layer** (Normalization→Pattern→Semantic→Combined→production integration) | ✅ running in production |

**Core capabilities delivered by end of Phase I:**
- **Knowledge Base V2**: hybrid retrieval (vector + lexical + RRF), Intent/Risk Router, 9-block
  Prompt Assembly, Runtime Guardrails (including honest-uncertainty), a smoke-test suite with a
  Release Gate.
- **NLU Layer**: Vietnamese normalization (with/without diacritics), Pattern Router + Semantic
  Router learned from real data, Entity Extraction, cache — wrapped in try/except so it never
  breaks the reply path.
- **Multi-channel**: Messenger (primary) + customer Telegram + admin Telegram, sharing one
  orchestrator.
- **Operations**: admin dashboard, human handoff, real order-taking tools, CI/CD + backup + alert.

---

## 4. Production state (verified)

**Infrastructure (8/8 containers Up on the VPS):** `caddy`, `api`, `worker`, `dashboard`, `db`,
`redis`, `telegram_bot` (admin), `telegram_customer_bot` (customer).

**Channel cutover — completed 2026-07-24:**
- **Messenger**: the app-level webhook callback (app `robanme.com`, page "3S Coffee") was changed
  from the local machine's ngrok tunnel → `https://a3s.robanme.com/webhook` (Meta verified the
  endpoint, `success:true`).
- **Customer Telegram** `@CSKH_3S_Coffee_bot` + **admin Telegram**: running on the VPS; the local
  bots were fully removed to avoid fighting over the token (`getUpdates` 409). Both poll cleanly
  (pending 0, no errors).

**End-to-end test on the VPS (Customer Care channel):**
- Brewing advice grounded in the Knowledge Base (dosage, temperature, caffeine figures).
- **Honest-uncertainty guardrail** working correctly: did not fabricate the Robusta/Arabica blend
  ratio.
- **Real order placed successfully** (order #1: 1× 100g jar × 170,000 VND, correct name/phone/
  address captured, status `new`).
- Near-instant latency (VPS located in Vietnam).

**Verification metrics (VPS ≡ Local — proving cross-environment stability):**
- KB smoke test: **10/10 PASS** (both VPS and local), Release Gate PASS.
- NLU held-out, 150 utterances: **121 correct (80.7%)** on both; the failing cases match, and the
  confidence scores agree to 4 decimal places → the embedding thresholds are **stable across
  different CPUs**.
- RAM: bot (2 embedding models) ~1.0GB; whole stack ~2.7GB / 7.8GB → ~5GB headroom.

> Measurement takeaway: **logic/accuracy** measurements on the local machine are trustworthy (same
> code + data → same result); only **performance** measurements (latency, RAM) are
> environment-dependent and must be taken on the VPS itself (now done).

---

## 5. Open items (do not block opening Phase II)

| Item | Note | Owner |
|---|---|---|
| **Rotate Meta secrets** | `META_APP_SECRET`/`PAGE_ACCESS_TOKEN` were once leaked in git history (#1) — need rotating. | Hoài (Meta Developer Console) |
| **Meta App review** | Get the app approved before opening Messenger to real customers. The fanpage has no customers yet, so we cut over early for dev/test. | Hoài |
| **Product catalog** | Currently exactly 1 real SKU (100g jar). Expanding the line means entering more via the dashboard. | Ops/business |
| **FAQ table / staff_users** | `faq_entries` and `staff_users` are empty (FAQs are served via the KB; no dashboard login accounts created). | Ops |

None of the above technically blocks starting Phase II.

---

## 6. Readiness for Phase II — Alpha3S Gateway (Customer Terminal)

Phase I delivers exactly what Phase II needs: a **complete "App" holding the entire brain**
(KB V2 / NLU / LLM / tools / DB / dashboard) running stably on a single VPS (2–4 vCPU / 8GB) — the
premise of the "thin Customer Terminal" architecture the design team proposed (roadmap
`AGW-ROADMAP-001`).

**What is already in place as a foundation for the Gateway:**
- A single message-processing orchestrator/endpoint shared across all channels (proven with
  Messenger + 2 Telegram) → the Gateway only needs to be a thin front-facing layer, not a rewrite
  of the brain.
- Automated deploy + HTTPS + backup + alert already exist → new channels (Web/Zalo) follow the
  same pipeline.
- The RAM bottleneck of the 2 embedding models was measured on the real VPS (~1GB) → real data for
  deciding the Gateway architecture on a small VPS (one of the roadmap's open questions).

**Proposal to open Phase II:** the design team signs off on this report, then work begins per
`AGW-ROADMAP-001` — starting at §9 "Immediate Next Actions", running Stage A (normalization +
embedding RSS measurement — now with real data) in parallel with Stage B (VPS — already available).

---

## 7. Reference documents

- `ISSUES-VI.md` / `ISSUES-EN.md` — full backlog #1–#12, status, fixed bugs.
- `docs/DEPLOYMENT-{VI,EN}.md` — production infrastructure technical reference.
- `docs/VPS-RUNBOOK-{VI,EN}.md` — VPS operations guide for staff.
- `docs/KNOWLEDGE_BASE_V2_DESIGN-VI.md`, `docs/NLU_LAYER-{VI,EN}.md` — KB V2 (#11) & NLU (#12) design.
- `AGW-ROADMAP-001-diem-bat-dau.md` — Phase II roadmap (Alpha3S Gateway).
