---
document_id: PHASE1B-M4-PIN-TOOL-ACTIVATION-CYCLE-SUMMARY-EN
title: "Phase 1B M4 — Merge/Deploy/Preflight/Activation Gate Cycle Summary (PIN Tool)"
document_type: summary
owner: Dev
status: FINAL — cycle closed, awaiting a new cycle if rehearsal is retried
created_at: 2026-08-07
covers_period: "2026-08-06T13:10Z – 2026-08-07T07:30Z"
final_production_head: 405e75e29dd9792e732c0d6280ee3bf4e67c7a89
rehearsal_completed: false
language: en-US
note: "English translation of PHASE1B-M4-PIN-TOOL-ACTIVATION-CYCLE-SUMMARY-VI.md — keep in sync if either is edited."
---

# M4 — Merge/Deploy/Preflight/Activation Gate Cycle Summary (PIN Tool)

A single consolidated reference covering the entire cycle from merging PR #7 (secure PIN
provisioning tool) through CA closing the Internal Synthetic Activation Gate with no rehearsal
ever executed. Purpose: one place to understand the full sequence without re-reading every
individual CA-Docs/docs file.

## 1. Bottom line

**The PIN provisioning tool was merged and deployed to production in a fully dormant
(inactive) state — but the actual rehearsal (225 synthetic conversations) was NEVER run, and no
real PIN was ever set for anyone.** The gate closed because its execution window lapsed with no
one instructing a start — not because of any technical failure or security breach.

## 2. Full timeline

| # | Time (UTC) | Event | Document |
|---|---|---|---|
| 1 | before this session | PR #7 draft, head `7a7e92f`, CI green, already through 4 rounds of CA review (REV1-4), F-M4-PIN-R3-01/02 closed | `PHASE1B-M4-REHEARSAL-PIN-TOOL-REVIEW-4-VI.md` (CA) |
| 2 | — | CA issued a recovery handoff (after a Claude Desktop incident) plus a Merge/Deploy-Dormant Gate for exact head `7a7e92f` | `PHASE1B-M4-DEV-CONTINUATION-HANDOFF-VI.md`, `PHASE1B-M4-PIN-TOOL-MERGE-DEPLOY-DORMANT-GATE-VI.md` (CA) |
| 3 | `13:10:49Z` | PO merged PR #7 (Claude Code's own auto-mode classifier blocked the automated merge call) → merge commit `d8ef339d` | GitHub PR #7 |
| 4 | `13:12:39Z` | CI/CD auto-deployed the code to the VPS successfully (run `31104714489`) | — |
| 5 | `~13:16Z`-`13:25Z` | Discovered CI/CD deploy does not auto-run migrations → manual DB backup → PO manually ran `migrate.py up` (migrations 040-042) | — |
| 6 | `13:37:44Z` | Dev submitted the full evidence report, pushed to `main` (`67fb9b0`) | `PHASE1B-M4-PIN-TOOL-MERGE-DEPLOY-DORMANT-EVIDENCE-VI.md` |
| 7 | `14:46:13Z` | CA Review 1: EVIDENCE_SUPPLEMENT_REQUIRED (F-E1-01/02/03 — missing CI/deploy provenance and a detailed command/exit-code table) | `...EVIDENCE-REVIEW-1-VI.md` (CA) |
| 8 | `~14:47Z` | Dev supplemented the report, pushed to `main` (`405e75e`) — **this push inadvertently re-triggered CI/CD deploy** (the workflow has no path filter by file type), causing the production HEAD to drift from `d8ef339d` to `405e75e` | — |
| 9 | — | CA Review 2: ACCEPTED — evidence CLOSED | `...EVIDENCE-REVIEW-2-VI.md` (CA) |
| 10 | `~16:38Z` | PO Approval Amendment 02 (approval_ref `...amendment-01`→`02`, locked the exact commit to `d8ef339d`, staff 3/4/5, window `23:30Z`-following day `07:30Z`) | `...APPROVAL-AMENDMENT-02-VI.md` (CA/PO) |
| 11 | — | CA Preflight Directive: authorized Dev to run a fresh 14-point read-only preflight | `...PREFLIGHT-DIRECTIVE-VI.md` (CA) |
| 12 | `23:51:37Z`-`23:52:04Z` | **Preflight #1: FAIL** — production HEAD (`405e75e`) did not match Amendment 02's exact commit (`d8ef339d`) due to the drift at step 8; the other 13/14 technical checks all passed, with no sign of activation | `...PREFLIGHT-EVIDENCE-VI.md` (Dev) |
| 13 | `2026-08-07` | CA Preflight Review 1: FAIL-CLOSED confirmed Dev handled it correctly; determined this was "governance drift" (docs-only change — the three operational files: runner/manifest/PIN tool — had unchanged blobs); required a new Amendment 03 + fresh directive before retrying | `...PREFLIGHT-REVIEW-1-VI.md` (CA) |
| 14 | `04:00:10Z` | PO Approval Amendment 03: re-baselined the exact commit to match actual reality (`405e75e`), keeping scope/principals/window unchanged (`00:15Z`-`07:30Z`) | `...APPROVAL-AMENDMENT-03-VI.md` (CA/PO) |
| 15 | — | CA Preflight Directive 2: authorized re-running the preflight, **explicitly required NOT pushing the report to `main`** this time (to avoid repeating the drift) | `...PREFLIGHT-DIRECTIVE-2-VI.md` (CA) |
| 16 | `04:09:06Z`-`04:09:12Z` | **Preflight #2: PASS** — 8/8 checks passed, git blob SHAs for the runner/manifest/PIN-tool matched the accepted baseline, HEAD matched `405e75e`, OFF-state clean | `...PREFLIGHT-EVIDENCE-2-VI.md` (Dev, local-only at `E:\Alpha3s\dev\`) |
| 17 | — | CA Preflight Review 2: ACCEPTED_PREFLIGHT_CLOSED | `...PREFLIGHT-REVIEW-2-VI.md` (CA) |
| 18 | `~04:31Z` | **CA opened the Internal Synthetic Activation Gate** for exactly one full-lifecycle run (225 synthetic conversations), with a 06:45Z cutoff for starting a new run and a 07:30Z expiry, plus a detailed 9-step authorized sequence (re-check → PIN ceremony → operational approval → key provisioning → dry-run → full run → review → cleanup → revoke) | `...ACTIVATION-GATE-VI.md` (CA) |
| 19 | `06:45Z`-`06:58Z` | **No one instructed a start** — Dev did not initiate the ceremony on its own without an explicit instruction; the cutoff passed | — |
| 20 | `06:58Z` | CA issued a No-Start Closure Directive: closed the new-run window, required Dev to confirm no writes had occurred and to submit a no-run post-snapshot before `07:30Z` | `...NO-START-CLOSURE-DIRECTIVE-VI.md` (CA) |
| 21 | `07:01:14Z`-`07:01:15Z` | Dev ran a final read-only snapshot, confirming **0 audit_log rows related to M4/PIN** since the gate opened — fully clean dormant state; submitted before the deadline | `...NO-RUN-CLOSURE-EVIDENCE-VI.md` (Dev, local) |
| 22 | `2026-08-07` | **CA formally closed the gate**: CLOSED_NO_EXECUTION_DORMANT_CONFIRMED — not a successful rehearsal, and does not satisfy the Product Completion path's rehearsal requirement | `...NO-RUN-CLOSURE-VI.md` (CA) |

## 3. Why the rehearsal never ran — root causes

**Not a technical defect or a security gap.** All three contributing causes were coordination/
process issues:

1. **Governance drift (timeline item 8):** the GitHub Actions deploy job currently fires on
   every push to `main`, including docs-only changes — there is no path filter. Two rounds of
   Markdown-only evidence/correction submissions inadvertently pushed the production HEAD past
   the commit PO had approved, forcing a full Amendment + preflight redo. **CA explicitly
   directed that the workflow NOT be fixed mid-cycle** (doing so would create yet another commit
   and invalidate the gate again) — this is technical debt to address as its own change after
   the rehearsal is complete.
2. **Gate opened without an execution instruction:** CA validly opened the Activation Gate, but
   without an explicit "start now" instruction to Dev/the three principals. Dev followed the
   established principle of "only act on an explicit instruction" and did not infer authority
   from the gate merely being open — as a result, the window lapsed with no one starting.
3. **Lesson CA itself recorded** (in `...NO-RUN-CLOSURE-VI.md` §4): next time, "PO/CA must issue
   a clear execution instruction for DEV to begin the ceremony... not just grant authority and
   then wait."

## 4. Final verified-safe state (independently confirmed multiple times)

| Item | State |
|---|---|
| Production HEAD | `405e75e29dd9792e732c0d6280ee3bf4e67c7a89` |
| Migrations 040-042 (PIN bootstrap/bind/link) | `applied` — infrastructure exists but is dormant |
| `capture_enabled` | `false` |
| PIN credentials for staff 3/4/5 | `0` — no one has a real PIN |
| Bootstrap tokens / bind approvals / capture approvals | `0` / `0` / `0` |
| Synthetic residual (225 conversations) | `0` — never seeded |
| Active transcript/signing-auth keys | `0` / `0` |
| Internal/external health | `200` / `200` |
| Dead-letter queue | `0` |
| Audit log entries for M4/PIN since the gate opened | `0` rows |

## 5. Outstanding work if the rehearsal is retried

Per the 5 conditions CA laid out in `...NO-RUN-CLOSURE-VI.md` §4:

1. PO issues a new approval amendment (current exact HEAD, scope, principals, new window).
2. A fresh read-only preflight (Dev runs it, without pushing to `main`).
3. CA issues a new Activation Gate.
4. **Important — different from last time:** once the gate is open, PO/CA must issue an
   explicit execution instruction for Dev to begin the ceremony within the cutoff, not just open
   the gate and wait.
5. Execution evidence + CA operational closure once the rehearsal has actually run to completion.

Separate technical debt (does not block the rehearsal, address whenever convenient): add a
`paths-ignore` rule for the `docs/` directory to the GitHub Actions deploy workflow so future
documentation-only submissions no longer auto-trigger a production redeploy.

## 6. Operational note — who ran what during this cycle

Claude Code's own auto-mode classifier automatically blocked several mutating actions against
production/GitHub even after PO had confirmed them in chat (merging the PR, `migrate.py up`,
a couple of `git push origin main` calls, and one `git cherry-pick` on `main`) — those specific
commands were run by PO directly, verbatim as provided by Dev. All backups, every read-only
query, health check, and evidence collection were performed by Dev (Claude Code) over SSH.
