# Alpha3S — Telegram Bot Documentation

> Describes the 2 independent Telegram bots in the system — the **admin**
> bot (internal) and the **customer** bot (fallback channel). Use this when
> deploying, configuring a new token, or debugging why messages aren't being
> received.
> Last updated: 7/16.

## Quick index
- [Overview — 2 different bots](#overview--2-different-bots)
- [Admin Bot (telegram_listener.py)](#admin-bot-telegram_listenerpy)
- [Customer Bot (telegram_customer_listener.py)](#customer-bot-telegram_customer_listenerpy)
- [Short customer code (resolve_psid)](#short-customer-code-resolve_psid)
- [How to create a new bot via @BotFather](#how-to-create-a-new-bot-via-botfather)
- [Configuration (.env)](#configuration-env)
- [Technical architecture](#technical-architecture)
- [Common debugging](#common-debugging)

---

## Overview — 2 different bots

| | Admin Bot | Customer Bot |
|---|---|---|
| File | `app/workers/telegram_listener.py` | `app/workers/telegram_customer_listener.py` |
| Docker service | `telegram_bot` | `telegram_customer_bot` |
| Token | `TELEGRAM_BOT_TOKEN` | `TELEGRAM_CUSTOMER_BOT_TOKEN` |
| Who can message it | **ONLY** the configured `TELEGRAM_ADMIN_CHAT_ID` — every other chat is silently ignored | **Anyone** who messages the bot (public channel) |
| Role | Receives escalation notifications + runs admin commands (`/resume`, `/note`, `/approve`, `/list`) | Replies to real customers — used when Messenger has an issue (e.g. Meta locking the test user) |
| Shares AI logic? | No — only handles commands, does not call `orchestrator.handle_message` | **Yes** — calls `orchestrator.handle_message()` directly, identical to the Messenger flow |

**⚠️ The 2 bots MUST use 2 different tokens** — never reuse the same
Telegram bot for both roles, since the admin bot has security logic
restricted to a single chat_id, while the customer bot must be open to
everyone.

Both use **long polling** (`getUpdates`), no webhook/public HTTPS needed —
suitable for the current dev stage / before a real domain is deployed (#9).

---

## Admin Bot (`telegram_listener.py`)

### Supported commands

| Command | Syntax | Description |
|---|---|---|
| `/resume` | `/resume <customer code> [note]` | Resume the bot for 1 conversation. Optional note — if provided, it's saved to `messages` (`role='agent'`) and injected into the bot's context |
| `/note` | `/note <customer code> <content>` | Add a note **at any time**, no need to pair it with resume — used when staff is negotiating over the phone while the bot is still running normally |
| `/approve` | `/approve <customer code> <quantity> <unit price> [note]` | Approve a special price/quantity (written to `price_overrides`) — lets the bot create an order beyond the standard limit if the customer confirms exactly this quantity |
| `/list` | `/list` | Lists every conversation currently `bot_paused=TRUE`, one message per conversation with a **"▶️ Resume now"** button |
| `/help` | `/help` | Usage instructions |

### Buttons (inline keyboard / callback_query)
- Every escalation notification (`notify_admin`) and every line in `/list`
  includes a **"▶️ Resume bot now"** button — clicking it calls `resume_bot()`
  directly, no need to type a command or copy the PSID.
- After a click, Telegram is sent an **`answerCallbackQuery`** to clear the
  loading icon on the button (required by the Telegram Bot API, otherwise the
  button gets stuck showing "loading" forever).

### Security
Every update (both regular messages AND callback_query) has its `chat_id`
compared against `TELEGRAM_ADMIN_CHAT_ID` before processing — if it doesn't
match, it is **completely ignored**, with no reply at all (not even an error),
to avoid revealing any information to a stranger who found the bot.

### Input validation (`is_valid_identifier`)
After an incident on 7/16 (staff accidentally typed the whole phrase
`"Customer code: 4"` from a notification message, creating a garbage
customer with `psid = "Code"`), every `/resume`, `/note`, `/approve` command
now validates the identifier before processing — only accepting:
- A pure numeric string (short customer code, e.g. `4`)
- `tg:<number>` or `manual:<hex>` (a full system PSID)

Anything else → the bot returns a clear error, **no garbage data is created**.

---

## Customer Bot (`telegram_customer_listener.py`)

A fallback channel for when Messenger has an issue — **NOT a long-term
replacement for Messenger**, only used in parallel to avoid being blocked
during dev/testing or when Meta has a problem (like the test-account lockout
incident on 7/16).

### How it works
1. Receives **any** text message sent to the bot.
2. Sets `sender_id = f"tg:{chat_id}"` — the `tg:` prefix guarantees it never
   collides with a real Facebook PSID (which is always a long pure-numeric
   string).
3. Checks `is_bot_paused(sender_id)` — if currently paused, only logs the
   customer's message, does not reply (identical logic to
   `app/workers/tasks.py` for Messenger).
4. If not paused: calls `orchestrator.handle_message(sender_id, text)`
   directly — **shares 100% of the AI logic** with Messenger (RAG, tool
   calling, human handoff, agent-notes context...), no separate copy of the
   code.
5. Sends the reply back via Telegram's `sendMessage`.

### Differences from a real Messenger customer
- `orchestrator.py` **skips** calling the Messenger Graph API to fetch the
  name (only called when `sender_id` doesn't have the `tg:`/`manual:`
  prefix) — a Telegram customer won't get a gender hint from their display
  name, the bot has to rely on how the customer refers to themselves in the
  conversation as usual.
- There is no "echo capture" mechanism (catching staff typing by hand) like
  on Messenger, because Telegram has no "Page Inbox" concept where a staff
  member replies on the bot's behalf. Staff still use `/note`/`/approve` from
  the Admin bot to add information.

---

## Short customer code (`resolve_psid`)

A Facebook PSID (15-17 digits) or `tg:<chat_id>` is hard to type by hand on
mobile. The system uses **`customers.id`** (an auto-incrementing integer,
usually 1-2 digits) as a "short customer code":

- Every notification message / `/list` shows a line reading **"Customer code
  — type ONLY this number into the command"**.
- `handoff.resolve_psid(identifier)`: if `identifier` is a pure numeric
  string that matches a real `customers.id` → returns the matching PSID. If
  not (already a full PSID, or the code doesn't exist) → treats `identifier`
  as the PSID itself (backward-compatible, you can still type the full PSID
  if you prefer).

---

## How to create a new bot via @BotFather

1. Open Telegram, chat with **@BotFather**.
2. `/newbot` → set a display name → set a username (must end in `bot`, e.g.
   `alpha3s_customer_bot`).
3. BotFather returns a **token** in the form
   `123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` — copy the whole string.
4. Paste it into `.env` under the correct variable (`TELEGRAM_BOT_TOKEN` for
   the admin bot, or `TELEGRAM_CUSTOMER_BOT_TOKEN` for the customer bot) —
   **never reuse an old token for a different role**.
5. **Get `TELEGRAM_ADMIN_CHAT_ID`** (only needed for the admin bot): send any
   message to the newly created admin bot, then call:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
   Find the `message.chat.id` field in the returned JSON — that's your
   `TELEGRAM_ADMIN_CHAT_ID`.

---

## Configuration (.env)

| Variable | Used for | Required? |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Admin bot | Yes (if you want handoff-via-Telegram) |
| `TELEGRAM_ADMIN_CHAT_ID` | Admin bot — restricts which chat can issue commands | Yes, together with the above |
| `TELEGRAM_CUSTOMER_BOT_TOKEN` | Customer bot | Optional — only needed if using the fallback channel |

If the corresponding token is missing, the service will log a warning and
**not start its polling loop** (the container does not crash, it just idles
waiting for configuration) — see the `_configured()`/`main()` function in
each file.

---

## Technical architecture

- **Long polling**, no webhook — each service calls `deleteWebhook` on
  startup (in case someone previously set a webhook manually, to avoid
  conflicts).
- Both run as separate Docker services, `restart: unless-stopped` (auto-
  restart on crash) — see `docker-compose.yml`.
- Not run in the same process as `worker` (arq, handling the Messenger
  queue) — 3 independent background processes: `worker`, `telegram_bot`,
  `telegram_customer_bot`.

---

## Common debugging

**The bot doesn't respond at all:**
```bash
docker compose logs telegram_bot --tail 100
# or
docker compose logs telegram_customer_bot --tail 100
```
Look for the line `Da ket noi, bat dau long-polling...` ("Connected,
starting long-polling...") — if it's missing, the token is wrong or
configuration is missing.

**Typed an admin command but got no response:** verify you're messaging from
a chat whose `chat_id` matches `TELEGRAM_ADMIN_CHAT_ID` — the log will show a
line like `Bo qua tin nhan tu chat la (chat_id=...)` ("Ignoring message from
unknown chat") if it was blocked due to a chat mismatch.

**Changed the code but nothing changed:** these 2 services are built from the
base `Dockerfile` (not dev mode like the dashboard) — after editing the
Python code, you need `docker compose restart telegram_bot` (or
`telegram_customer_bot`), they don't hot-reload automatically.
