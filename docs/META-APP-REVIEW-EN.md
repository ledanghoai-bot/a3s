# Alpha3S — Meta App Review Guide (Messenger gateway)

> **Date:** 2026-07-24 · **Author:** Claude Code (at Hoài's request)
> **Purpose:** An execution playbook to move the Alpha3S Messenger app from **Development mode**
> (only app-role accounts can message it) to **open for real customers**, via **Meta App Review**.
> This is the last open item of **#9** (see `ISSUES-EN.md` §#9) and depends on **#1** (rotate Meta
> secrets). Vietnamese source of truth: `docs/META-APP-REVIEW-VI.md`.

---

## 0. TL;DR — read this first

- **Why:** The `robanme.com` app is in Development mode. In this mode **only accounts with a role
  on the app** (admin/dev/tester) can message the bot. For **any real customer** to message the
  Page and get a reply, the `pages_messaging` permission must reach **Advanced Access** — which
  **requires App Review + Business Verification**.
- **What to request:** primarily **`pages_messaging`** (Advanced Access). Plus:
  `pages_manage_metadata` (webhook subscription), `pages_show_list`/`pages_read_engagement` (pick/
  read the Page). Customer profile (first/last name) comes **with** `pages_messaging` — **do not**
  request it separately.
- **3 remaining blockers only Hoài can do (manual, in Meta Console):**
  1. **Business Verification** for Robanme JSC — usually the longest path (days → weeks).
  2. **Rotate Meta secrets** (#1) before opening to real customers — old secrets leaked in git history.
  3. **Fill real company details** into the 3 built legal pages + **attach the URLs in App Settings**
     (see §5) — pages exist, only placeholders remain.
- **✅ Done (Code, 2026-07-24):** (a) built the 3 **Privacy / Terms / Data Deletion** pages served on
  `a3s.robanme.com` (§5); (b) fixed the **automated-service disclosure** in `system_prompt.md` +
  multi-channel via a `channel` param — Messenger mandatory, other channels recommended (§7).
  Previously `system_prompt.md` deliberately made the bot sound human (the highest rejection risk) —
  now removed.

---

## 1. Current app state (as-built)

| Item | Actual value in the project |
|---|---|
| App name / App ID | `robanme.com` · **541838039979536** |
| Product type | Messenger (Facebook Page) |
| Connected Page | **"3S Coffee"** |
| Webhook callback URL | `https://a3s.robanme.com/webhook` (VPS `160.30.157.235`, HTTPS via Caddy) |
| Verify token | `META_VERIFY_TOKEN` (env, checked in `GET /webhook`) |
| App secret | `META_APP_SECRET` (env, validates `X-Hub-Signature-256`) |
| Page access token | `PAGE_ACCESS_TOKEN` (env, calls Send API + User Profile) |
| Graph API version | Send API `v21.0`, User Profile `v19.0` |
| Subscribed webhook fields | `messaging` group (messages, messaging_postbacks…) |
| Webhook SLA | `POST /webhook` only validates + enqueues to Redis → returns 200 **< 100ms** (Meta wants ≤ 20s) ✅ |

**Meta APIs actually in use** (describe these in the submission so it matches real behavior):
1. **Messenger Platform webhook** — receives customer messages to the Page.
2. **Send API** (`POST /me/messages`, `messaging_type: RESPONSE`) — the bot replies.
3. **User Profile API** (`GET /{psid}?fields=first_name,last_name`) — fetch the name for polite
   address, cached in Redis for 7 days (`app/services/messenger_profile.py`).

> Everything is **standard in-24h-window replies** (`RESPONSE`). We currently use **no** message
> tags, **no** proactive outbound outside 24h, **no** one-time notifications — **do not** request
> those permissions/features in this submission (over-asking invites hard questions → slower
> review). If we later build follow-up/outbound (see `docs/SALES-FLOW-CURRENT-STATE-EN.md` G2),
> file a separate supplemental review.

---

## 2. Which permissions to request

| Permission / feature | What it's for in Alpha3S | Access level | Submit for review? |
|---|---|---|---|
| **`pages_messaging`** | Receive & send Messenger messages to **any customer** | **Advanced Access** | **Yes — the core one** |
| `pages_manage_metadata` | Subscribe the Page to webhooks via Graph API | Advanced Access | Yes (usually bundled) |
| `pages_show_list` | List Pages the account manages (token step) | Advanced Access | Yes if the flow needs it |
| `pages_read_engagement` | Read Page info/metadata | Advanced Access | Request only if actually used |
| User Profile (first/last name) | Address the customer | **Bundled with `pages_messaging`** | No separate request |
| `human_agent` tag | (Future) human replies outside 24h on escalation | Advanced Access + BV | **Not this round** |

**Rule:** only request **what the code actually calls**. Reviewers verify via the screencast;
requesting something you can't demo → rejection.

---

## 3. Prerequisite checklist (finish all before hitting Submit)

| # | Prerequisite | Alpha3S status | Owner |
|---|---|---|---|
| P1 | App set to **Live** (not Development) when opening to real customers | ⏳ flip after approval | Hoài |
| P2 | **Facebook Page published** (not hidden) | ✅ "3S Coffee" is live | — |
| P3 | Webhook returns **200 within ≤ 20s** | ✅ < 100ms | (done) |
| P4 | **Business Verification** complete for Robanme | ❌ **not yet** — see §4 | Hoài |
| P5 | Public **Privacy Policy / Terms / Data Deletion URLs** | ✅ **pages built** (`/privacy`, `/terms`, `/data-deletion`) — awaiting Hoài's real company details + go-live — see §5 | Code (done), Hoài (fill + attach URLs) |
| P6 | **App Icon** (1024×1024) + **Category** | ⏳ check App Settings | Hoài |
| P7 | Valid app name, contact info, notification email | ⏳ check | Hoài |
| P8 | **Rotate `META_APP_SECRET` + `PAGE_ACCESS_TOKEN`** (#1) | ❌ **not yet** — old secrets leaked | Hoài |
| P9 | A **test account/flow** for reviewers to message | ⏳ prepare — see §6 | Code + Hoài |
| P10 | Resolve the **automated-service disclosure** conflict (§7) | ✅ **system prompt fixed** (Direction A) — Messenger mandatory, other channels recommended | Code (done) |

> **Critical path:** P4 (Business Verification) is usually the slowest. **Start the business
> verification submission NOW**; do the rest (P5, P8, P9, P10) in parallel while it's pending.

---

## 4. Business Verification — start this earliest

Advanced Access **requires** a verified business. This is a legal/paperwork process; no code.

**Prepare (for Robanme JSC):**
- Legal name + registered address matching official documents.
- **Business license / tax ID** (government document proving the legal entity).
- Phone + a company-domain email (verifies faster than a personal email).
- Official website (ideally on the `robanme.com` domain).

**Steps (Meta Business Suite → Business Settings → Security Center / Business Verification):**
1. Create/select the **Meta Business Portfolio** that owns the `robanme.com` app.
2. Go to **Security Center** → start **Verify business**.
3. Enter the legal-entity details, upload documents, pick a verification-code channel (phone/email/mail).
4. Wait for Meta review (days → weeks). Track status in Security Center.

> If Robanme has no Business Portfolio yet, create one first; the app must sit **inside** that
> portfolio for the verification result to attach to Advanced Access.

---

## 5. Privacy Policy / Terms / Data Deletion — ✅ BUILT, awaiting real details

Meta **requires** these public URLs. **All three pages are built** in the repo (`app/api/legal.py`,
registered in `app/main.py`), served on the API domain (Caddy already proxies it, HTTPS automatic):

| App Settings URL | Path | Route |
|---|---|---|
| Privacy Policy URL | `https://a3s.robanme.com/privacy` | `GET /privacy` |
| Terms of Service URL | `https://a3s.robanme.com/terms` | `GET /terms` |
| User Data Deletion (Instructions URL) | `https://a3s.robanme.com/datadeletion` ⚠️ **no `-`** | `GET /datadeletion` (alias) + `GET /data-deletion` |

> ⚠️ **Real gotcha:** Meta's "Data Deletion Instructions URL" field **rejects a path with a `-`**
> (`/data-deletion` shows "name_placeholder should represent a valid URL" even though the URL is live
> 200, while `/privacy` and `/terms` on the same host pass). Added an **alias `/datadeletion`** (no
> hyphen) — Meta accepts it. Use `https://a3s.robanme.com/datadeletion` for this field.

All three verified returning **200** with full Vietnamese content. The **Privacy Policy** discloses
the real data collected (PSID, name, conversation content, and at order time: name–phone–address),
and explicitly states that **message content is sent to an LLM provider (DeepSeek) to generate
replies** — a point reviewers scrutinize. The **Data Deletion** page gives two paths: message "XÓA
DỮ LIỆU" to the Page, or email.

> ⚠️ **Remaining for Hoài (required before go-live):** open `app/api/legal.py`, replace the
> **PLACEHOLDERS in `[ ]`** with Robanme JSC's real details — **registered address, contact email,
> phone** (search for `[` to find them all). Adjust `EFFECTIVE_DATE` if needed. Then paste the 3 URLs
> into **App Settings → Basic** (Privacy Policy, Terms of Service, User Data Deletion).

**The "User Data Deletion" field has 2 options — both implemented, pick one in Meta:**

| Dropdown option | URL to set in Meta | Mechanism |
|---|---|---|
| Data Deletion Instructions URL | `https://a3s.robanme.com/datadeletion` | Instructions page; user messages "XÓA DỮ LIỆU" → bot asks to confirm → "XÁC NHẬN XÓA" → **auto-deletes + reports what was deleted** (self-service, no staff); or email |
| **Data Deletion Callback URL** — *recommended* | `https://a3s.robanme.com/datadeletion/callback` | Meta POSTs `signed_request` on app removal → system **auto-verifies + deletes immediately** |

**Self-service via chat (customer deletes their own data, no staff needed)** — deterministic in
`orchestrator.py` (before the LLM): the customer messages "XÓA DỮ LIỆU" → the bot asks to confirm
(Redis flag `del_pending`, 15 min) → the customer messages "XÁC NHẬN XÓA" → calls
`process_deletion(sender_id)` → deletes immediately and returns a message **listing what was deleted**
(message count, name, orders anonymized) + code + status link. Keyword match strips diacritics on both
sides (Vietnamese lesson). Works on every channel (Messenger/Telegram). E2E tested: step 1 keeps the
data, step 2 wipes it.

**Callback (`POST /datadeletion/callback`)** — `app/services/data_deletion.py` + route in `legal.py`:
verifies `signed_request` with `META_APP_SECRET` (HMAC-SHA256), extracts the PSID, then in one
transaction: **hard-deletes** messages/escalations/conversations, **anonymizes** orders (drops
name/phone/address, keeps the order for accounting), **anonymizes** the customer (`psid → deleted:<code>`),
**deletes** Redis `chat:`/`profile:` caches. Returns `{url, confirmation_code}`; the user checks status
at `GET /datadeletion/status?code=`. E2E tested: correct deletion, bad signature → HTTP 400. Requests
recorded in `data_deletion_requests` (**migration 013**).

> ⚠️ **Deploy:** migration `013_data_deletion_requests.sql` **does not auto-run** on the VPS (initdb
> only runs on volume creation) — after pushing, run it manually on the VPS DB **before** enabling the
> callback (missing table → callback 500). Command in §9.

---

## 6. Submission flow in the App Dashboard (step by step)

Go to **developers.facebook.com → App `robanme.com` → App Review → Permissions and Features**.

### 6.1. Prepare the description text (copy-paste, tune to reality)

**`pages_messaging` use case** (paste into "Tell us how you'll use this permission"):

> Our app powers an automated customer-service and sales assistant for the "3S Coffee" Facebook
> Page (a Vietnamese cold-brew coffee brand operated by Robanme JSC). When a customer sends a
> message to the Page, our webhook receives the event and our assistant replies within the
> standard 24-hour messaging window using the Send API (messaging_type: RESPONSE) to answer
> product questions, check stock, and take orders. We use the User Profile API only to retrieve
> the customer's first and last name so the assistant can address them politely in Vietnamese. We
> do not send promotional or outbound messages outside the 24-hour window. Conversations the
> assistant cannot handle are handed off to a human staff member.

**Why Advanced Access is required:**
> Advanced Access is required because real customers who message the "3S Coffee" Page are not
> users, testers, or admins of our app, and Standard Access does not allow the app to receive or
> reply to their messages.

### 6.2. Record the screencast (required)

Reviewers must see **the permission used for real, from the end-user's perspective**. Suggested
script (~2–3 min, with English narration/captions):
1. Open the "3S Coffee" Page in Messenger **from an account WITHOUT a role on the app** (play a
   real customer).
2. Send a product question → show the bot replying (proves `pages_messaging` + Send API).
3. Ask about stock / place a test order → the bot responds (shows a meaningful flow, not an echo).
4. (If the name is visible) show the bot addressing the customer by name (User Profile).
5. Show the webhook config screen (Callback URL `https://a3s.robanme.com/webhook`, `messaging`
   fields) to prove a real integration.
6. **If the bot disclosure is added (§7):** clearly show the opening line where the bot identifies
   itself as an automated assistant.

> The video does **not** need to reveal any token/secret. If you record the App Dashboard, mask
> sensitive fields.

### 6.3. Reviewer instructions (the "Instructions" box)

- Is the app gated: Yes. Trigger: **message the "3S Coffee" Page directly on Messenger**.
- Provide an **m.me/Page link** + a few sample prompts for the reviewer: ask about products, ask
  prices, place an order.
- Note that the bot replies **in Vietnamese** (the reviewer can use the Vietnamese sample prompts
  you provide).
- If the reviewer needs messaging access while the app is still in Dev mode, explain how, or point
  them to the test flow.

### 6.4. Submit

Once P1–P10 (§3) are done → select the §2 permissions → attach screencast + descriptions +
instructions → **Submit for review**. After approval, **switch the app to Live**, then open the
webhook to real customers.

---

## 7. Automated-service disclosure — ✅ RESOLVED (Direction A)

> **Implemented (2026-07-24):** chose **Direction A**. Edited `app/prompts/system_prompt.md`:
> repositioned the bot as an "automated advisory assistant", added a **"Automated-assistant
> disclosure"** section (the first message of a session must include a natural one-liner stating it's
> an automated assistant that hands off to staff when needed; answers truthfully if asked directly),
> and removed the contradictions in the pronoun/markdown rules. **Multi-channel (as requested):** added
> an explicit `channel` parameter to `orchestrator.handle_message()` (Messenger/Telegram pass their
> own), and the system injects a "current session context" block (channel + is-first-message +
> disclosure level). **Messenger = MANDATORY**; **Telegram/Zalo/web = RECOMMENDED** (easy to promote:
> add the channel to `DISCLOSURE_REQUIRED_CHANNELS`). Remaining: the screencast must clearly show the
> disclosure line on the first message.

Original context (why the fix was needed):

**Meta requirement (and CA/German law):** an automated experience must **let the user know they're
talking to an automated service** — at least at the **start of the thread**, after a long gap, and
when handing off from a human to the bot. This is a **common chatbot rejection reason**.

**Alpha3S current state (conflict):** `app/prompts/system_prompt.md` (lines ~3, 9–10) casts the bot
as a **"3S Coffee consultant"** and treats **"the customer realizing they're talking to a bot" as
"the most serious UX error."** So the bot is **deliberately hiding** its automated nature — the
opposite of what Meta requires. UAT-094 has a rule against "impersonating a human" *when asked
directly*, but Meta wants **proactive disclosure**, not only on demand.

**Decide (Hoài) + fix (Code) one of two directions:**
- **Direction A (recommended, Meta-safe):** add a **one-time** automated-service disclosure at the
  start of the conversation/greeting, e.g. *"I'm 3S Coffee's automated assistant; when needed I'll
  hand you over to a staff member."* Keep the friendly tone. Edit `system_prompt.md` + (if used)
  the Get Started/greeting text. The screencast must show this line.
- **Direction B (risky):** keep "sound fully human" → **likely rejected**, and even if it slips
  through, it violates policy in production (risk of being shut down later).

> This is a **must-fix** before recording the screencast, since the video is the reviewer's most
> scrutinized evidence.

---

## 8. Common rejection reasons & Alpha3S status

| Common rejection reason | Alpha3S | Action |
|---|---|---|
| No automated-service disclosure | ❌ currently hidden (§7) | **Fix system prompt (Direction A)** |
| Requesting a permission you can't demo | ⚠️ avoid over-asking | Request only §2, demo each |
| Missing/broken Privacy Policy URL | ❌ none (§5) | Create `/privacy` |
| No Business Verification | ❌ none (§4) | Submit early |
| Screencast doesn't show real behavior / just theory | — | Record real end-to-end flow |
| Bot just echoes, no real value | ✅ real sales tools | Demo price query + order |
| Slow webhook / dropped events | ✅ < 100ms, Redis enqueue | (met) |
| Page not published | ✅ published | — |

**Operational policy to remember (not a submission gate, but easy to hit in production):**
- **24-hour window:** outside 24h from the customer's last message you **cannot** message freely —
  you must use a valid message tag (none requested yet → **do not do outbound outside 24h** until a
  supplemental review).
- Tags `CONFIRMED_EVENT_UPDATE`, `ACCOUNT_UPDATE`, `POST_PURCHASE_UPDATE` were **removed as of
  April 2026** — if you later build follow-up, **do not** use these tags (calls will error).

---

## 9. Ownership & execution order

**Hoài (manual, in Meta — cannot be automated):**
1. **[Now]** Start **Business Verification** for Robanme (§4) — critical path.
2. **[Now]** **Rotate** `META_APP_SECRET` + `PAGE_ACCESS_TOKEN` (#1), update VPS `.env`, redeploy.
3. **[Decide]** Pick Direction A/B for bot disclosure (§7).
4. Add App Icon, Category, contact email, Privacy Policy URL in App Settings.
5. **[After pushing the callback code]** Run migration 013 on the VPS DB **before** selecting the
   callback URL:
   ```bash
   docker compose exec -T db psql -U alpha3s -d alpha3s < migrations/013_data_deletion_requests.sql
   ```
   Then set "User Data Deletion" = **Callback URL** `https://a3s.robanme.com/datadeletion/callback`
   (recommended) or **Instructions URL** `https://a3s.robanme.com/datadeletion` (§5).
6. Fill the use case + upload the screencast + instructions → **Submit** (§6). After approval:
   flip to **Live**.

**Claude Code:**
1. ✅ **Done** — built `/privacy`, `/terms`, `/data-deletion` (`app/api/legal.py` + `main.py`),
   verified 200. (Awaiting Hoài's placeholder fill + URL attach.)
2. ✅ **Done** — edited `system_prompt.md` (Direction A) + explicit `channel` param across
   `orchestrator.py`/`tasks.py`/`telegram_customer_listener.py` (§7).
3. (If needed) prepare the **Get Started / greeting text** via the Messenger Profile API
   (`app/services/messenger_profile.py` already has a Graph client — extend it).
4. Draft the **Vietnamese sample prompts** for reviewers + a detailed screencast script.
5. ✅ Updated `ISSUES-VI.md`/`ISSUES-EN.md` #9 + this doc.

---

## 10. References

- `ISSUES-EN.md` — #1 (rotate Meta secrets), #9 (open items "Meta App review", "rotate Meta secret").
- `docs/VPS-RUNBOOK-EN.md` §Cutover — Meta webhook config, Callback URL, field subscription.
- `docs/SALES-FLOW-CURRENT-STATE-EN.md` — real bot behavior, outbound gap (G2) & 24h policy.
- `app/api/webhook.py`, `app/services/messenger.py`, `app/services/messenger_profile.py` — Meta integration code.
- `app/prompts/system_prompt.md` — where §7 must be fixed.
- External sources (verified 2026-07-24):
  - [Meta — Permissions Reference](https://developers.facebook.com/docs/permissions/)
  - [Meta — Messenger App Review](https://developers.facebook.com/docs/messenger-platform/app-review/)
  - [Meta Advanced Access — which permissions need App Review](https://singhamandeep.com/what-is-meta-advanced-access/)
  - [Messenger Bot App Review — why chatbots get rejected (2026)](https://singhamandeep.com/facebook-messenger-bot-app-review-chatbot-saas/)
