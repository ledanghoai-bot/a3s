# Alpha3S — Dashboard Documentation (Next.js)

> Full reference for the admin dashboard (`dashboard/`) — use this when
> deploying, onboarding new staff, or continuing development. Think of it as
> a `/help` file for the dashboard.
> Last updated: 7/16 (after UX upgrade round 5 — per-item note/approval
> tracking).

## Quick index
- [Overview](#overview)
- [Login](#login)
- [/conversations page (main screen)](#conversations-page-main-screen)
- [/orders page](#orders-page)
- [/orders/new page](#ordersnew-page)
- [Shared component: OrderForm](#shared-component-orderform)
- [Folder structure](#folder-structure)
- [Backend API endpoints used by the dashboard](#backend-api-endpoints-used-by-the-dashboard)
- [Environment variables](#environment-variables)
- [How to run / deploy](#how-to-run--deploy)
- [Known limitations](#known-limitations)
- [Not yet built (out of current scope)](#not-yet-built-out-of-current-scope)

---

## Overview

The dashboard is a standalone **Next.js App Router** application (Docker
service `dashboard`, port **3000**), calling the FastAPI backend via REST
JSON (`NEXT_PUBLIC_API_URL`, default `http://localhost:8000`).

**Purpose:** lets staff operate the fanpage day-to-day without going straight
into the database — view conversations, take over/hand back the bot, manage
notes and special-price approvals, create and track orders.

**Authentication:** a simple static token (`ADMIN_API_TOKEN`, taken from the
backend's `.env`) — **there is no** real login/JWT system yet, which is
sufficient for the current scale but should be upgraded once multiple staff
members use it concurrently.

---

## Login

**Page:** `/login`

- Enter the `ADMIN_API_TOKEN` (from the backend's `.env` file, the
  `ADMIN_API_TOKEN` variable).
- The token is stored in the browser's `localStorage` (key `admin_token`) —
  **it does not expire automatically**, it's only lost when the browser
  cache is cleared or (currently **there is no logout button** in the UI —
  clear it manually via DevTools if you need to change tokens).
- Authenticated by calling `GET /dashboard/ping` — a wrong token is rejected
  immediately, no bad token is ever saved to localStorage.
- Any other request that gets a `401` automatically clears the token and
  redirects to `/login`.

---

## /conversations page (main screen)

Lists all conversations, **auto-refreshing every 5 seconds** (no manual
refresh needed) — pauses refreshing while an action is in progress (to avoid
UI flicker).

### Table columns
| Column | Content |
|---|---|
| **Customer** | Name (or "no name yet") + **"▼ Expand chat"** button + phone/PSID below |
| **Status** | `/n(N)` = number of **unhandled** notes, `/a(N)` = number of **still-active** `/approve` approvals. Number is bold, gray when N=0, orange when N>0 |
| **Latest message** | 1-line preview, truncated if long |
| **Time** | Timestamp of the latest message |
| **Bot status** | Badge "Bot is replying" / "Waiting on staff" (reflects `conversations.bot_paused`) |
| *(last, no header)* | **"Take over"** or **"Resume bot"** button |

### "Take over" / "Resume bot" button
- **Take over** (bot → paused): calls `POST /dashboard/conversations/{psid}/pause`.
  Staff sets this manually, distinct from the bot escalating itself.
- **Resume bot** (paused → bot): calls `POST /dashboard/conversations/{psid}/resume`.
  Before resuming, **a popup asks for an optional note** — if filled in, the
  note is saved to the message history (`role='agent'`) AND injected back
  into the bot's context on the very next turn (so the bot doesn't "forget"
  the agreement just reached while paused).

### "▼ Expand chat" button
Opens a row below, showing:

1. **Full chat history** — bubble style, distinguishing Customer (left) from
   Bot & Staff (right, different colors per `role`).
2. **📝 Notes (all)** — lists **every** note (`role='agent'` in `messages`),
   not just unhandled ones:
   - **Unhandled** note: yellow background, has a **"✓ Mark handled"** button
     (clicking it saves immediately, **no** confirmation needed).
   - **Handled** note: gray background, dimmed, only a static "✓ Handled"
     label remains — **it does not disappear from the list**, only its
     displayed state changes.
3. **✅ Approvals (/approve) (all)** — similarly, lists everything:
   - **Active**: yellow background, 2 buttons **"✓ Order created"** (requires
     a confirmation popup before saving) and **"✗ Reject"** (requires a popup
     asking for a reason, which cannot be left blank).
   - **Used** (order created): gray background, static "✓ Order created" label.
   - **Rejected**: gray background, static "✗ Rejected" label showing the
     reason that was entered.
4. **"🧾 Create order (auto-filled from /approve, /note)"** button — navigates
   to `/orders/new?psid=<psid>` (see below), it does **not** create the order
   right there.

---

## /orders page

Lists real orders (the `orders` table), with a **"+ Create order manually"**
button in the top right (navigates to `/orders/new` **without** a `psid`).

Each row has a dropdown to change the order status — calls
`PATCH /dashboard/orders/{id}/status`. The backend validates the transition
order: `new → confirmed → shipped → done` (no going back), `cancelled` is
allowed from any step **except** `done`. An invalid transition is rejected by
the backend with an error message.

---

## /orders/new page

The manual order-creation page, playing **2 different roles** depending on
whether `?psid=` is present in the URL:

| Accessed from | Has `psid`? | Behavior |
|---|---|---|
| "🧾 Create order" button in `/conversations` | Yes (`?psid=...`) | Automatically calls `order_draft` to **pre-fill** quantity/price from the latest `/approve`, plus name/phone/address if the customer has ordered before. Shows **both** buttons "🤖 Bot creates order" and "👤 Staff creates order". |
| "+ Create order manually" button in `/orders` | No | Empty form. Only shows the **"👤 Staff creates order"** button (no "bot" option since there's no conversation for the bot to read context from). |

**Security note:** the URL only carries the `psid` (not sensitive) —
name/phone/address are **never** put into the query string, always re-fetched
via the API.

### 2 different submit buttons
- **🤖 Bot creates order** — calls `POST /dashboard/conversations/{psid}/create_order`,
  using **the exact same logic as the AI tool** (`app/services/tools.py:create_order`)
  — still fully checks the standard price tiers / `MAX_AUTO_QUANTITY` /
  `price_overrides` matching the exact quantity. May be rejected if there is
  no valid approval.
- **👤 Staff creates order** — calls `create_order_manual`, **bypassing all**
  the checks above, staff enters the unit price themselves and takes full
  responsibility. Only stock availability is still checked (won't oversell
  what's in stock).

---

## Shared component: OrderForm

File: `dashboard/app/components/OrderForm.js`

Accepts a `psid` prop (default `null`):
- `psid` passed in → automatically fetches `order_draft`, pre-fills the form,
  shows both buttons.
- `psid = null` → empty form, only shows the "Staff creates order" button,
  calls `POST /dashboard/orders/manual` (a standalone order, auto-generating
  a `psid` in the form `manual:<uuid>`).

Reused as-is in both `/orders/new` scenarios above — no duplicate code.

---

## Folder structure

```
dashboard/
├── app/
│   ├── layout.js              # Root layout: nav (Conversations / Orders)
│   ├── page.js                 # Redirects -> /conversations
│   ├── globals.css
│   ├── login/page.js
│   ├── conversations/
│   │   ├── page.js              # Main page (described above)
│   │   └── [psid]/page.js       # ⚠️ Still in code but NO LONGER linked to
│   │                             #    from the UI (the "Open in separate
│   │                             #    window" button was removed per the
│   │                             #    7/16 request) — dead code, could be
│   │                             #    removed or repurposed later.
│   ├── orders/
│   │   ├── page.js
│   │   └── new/page.js
│   └── components/
│       └── OrderForm.js
├── lib/
│   ├── api.js                  # apiFetch() - auto-attaches the token, handles 401
│   └── useAuthGuard.js         # Hook that checks the token, redirects to /login if missing
├── Dockerfile
├── package.json
└── next.config.mjs
```

---

## Backend API endpoints used by the dashboard

All endpoints are under `/dashboard/*`, requiring the `X-Admin-Token` header
(including `ping`, which is used to validate the token at login).

| Method | Path | Used in |
|---|---|---|
| GET | `/dashboard/ping` | Login — token validation |
| GET | `/dashboard/conversations` | `/conversations` — the list + `/n(N)` `/a(N)` |
| GET | `/dashboard/conversations/{psid}/messages` | The expanded chat panel |
| GET | `/dashboard/conversations/{psid}/order_draft` | The expanded note/approval panel + auto-filling `OrderForm` |
| POST | `/dashboard/conversations/{psid}/pause` | "Take over" button |
| POST | `/dashboard/conversations/{psid}/resume` | "Resume bot" button |
| POST | `/dashboard/notes/{message_id}/mark-handled` | "✓ Mark handled" button (note) |
| POST | `/dashboard/overrides/{override_id}/mark-used` | "✓ Order created" button (approval) |
| POST | `/dashboard/overrides/{override_id}/reject` | "✗ Reject" button (approval) |
| GET | `/dashboard/products` | The SKU dropdown in `OrderForm` |
| POST | `/dashboard/conversations/{psid}/create_order` | "🤖 Bot creates order" button |
| POST | `/dashboard/conversations/{psid}/create_order_manual` | "👤 Staff creates order" button (tied to a conversation) |
| POST | `/dashboard/orders/manual` | "👤 Staff creates order" button (standalone, `/orders/new` without psid) |
| GET | `/dashboard/orders` | `/orders` — the order list |
| PATCH | `/dashboard/orders/{order_id}/status` | The order status dropdown |

---

## Environment variables

| Variable | Used in | Default |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `dashboard/lib/api.js` | `http://localhost:8000` |
| `ADMIN_API_TOKEN` | Backend (root `.env`, **not** the dashboard's own) — used for login | `change-me` (change this for a real deployment) |
| `DASHBOARD_CORS_ORIGINS` | Backend — origins allowed to call the API | `http://localhost:3000` |

---

## How to run / deploy

The `dashboard` service in `docker-compose.yml` runs in **dev-mode
hot-reload** (`npm run dev`, bind-mounting `./dashboard:/app`):

```bash
docker compose up -d --build dashboard   # first time, or after changing command/volumes
docker compose up -d dashboard            # subsequent runs (in theory sufficient)
```

⚠️ **See "Known limitations" below** — in practice, `--build` is still
required after every code change, hot-reload is not as complete as hoped.

**When deploying to real production (#9, not yet done):** switch back to a
production build (`npm run build && npm start`) instead of dev mode, since
dev mode is slower and not optimized — dev mode is currently used as a
temporary convenience for faster iteration during the development phase.

---

## Known limitations

1. **Still requires `docker compose up -d --build dashboard`** after every
   code change, despite switching to dev-mode hot-reload — it does not fully
   pick up new code automatically as originally hoped. Logged in
   `ISSUES.md`, decided **not to dig deeper into fixing it** (7/16).
2. **No logout in the UI** — changing tokens requires manually clearing it
   via DevTools (`localStorage.removeItem('admin_token')`) or clearing the
   browser cache.
3. **1 shared token for all staff** — no distinction of who performed which
   action, no "who clicked what" audit trail. Sufficient for the current scale.
4. The `/conversations/[psid]` page (separate popup window) is **still in
   the code but no button links to it anymore** — safe to remove if you want
   to clean up the code later.

---

## Not yet built (out of current scope)

Per the original scope of issue #8, the following are **not yet built**:
- Product/FAQ CRUD (automatically re-ingesting RAG when content is edited)
- Metrics/analytics (messages/day, conversation-to-order rate, top questions
  the bot fails to answer)
- Real auth (per-staff login, JWT/session)

See the full development history + technical decisions in `ISSUES-VI.md`
(and its English translation `ISSUES-EN.md`), section **#8**.
