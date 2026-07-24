# VPS RUNBOOK — Operating Alpha3S, for staff

> A **hands-on, step-by-step** guide for a technical staff member to operate the production
> server **without AI help**. Every section has copy-pasteable commands + an explanation of
> what each does. Read alongside `docs/DEPLOYMENT-EN.md` (technical summary) and `ISSUES-EN.md` (#9).
> Vietnamese version: `docs/VPS-RUNBOOK-VI.md`.
>
> **Conventions:** a line starting with `$` runs on **your machine**; a line starting with
> `root@vps:#` runs **on the VPS** (after you SSH in). Don't type the `$`/`#` characters.

---

## 0. What you need before starting

| What | Where to get it |
|---|---|
| **SSH key** to the VPS (`alpha3s_vps`) | The private key file, handed to you. The VPS **has password login disabled** — without the key you cannot get in (except the provider console). |
| **GitHub access** to `ledanghoai-bot/a3s` | The repo owner invites you as a collaborator. Needed to push code (triggers auto-deploy). |
| **VPS provider panel** (AZ VPS) | Admin account — used when you lose SSH (console) or need a hard reboot. |
| **PA Vietnam DNS panel** (domain `robanme.com`) | Only needed when changing/adding a domain. |
| **Meta App dashboard** (Messenger) | Only needed when configuring the webhook. |

Fixed facts:

| | |
|---|---|
| VPS IP | `160.30.157.235` |
| OS | Ubuntu 24.04 |
| Deploy directory | `/srv/alpha3s` |
| API/webhook domain | `https://a3s.robanme.com` |
| Dashboard domain | `https://a3s-dash.robanme.com` |
| Repo | `github.com/ledanghoai-bot/a3s` (branch `main`) |

---

## 1. Connect to the VPS (SSH)

### First time: set up a shortcut

On **Windows** (PowerShell or Git Bash) or **Mac/Linux** (Terminal), open `~/.ssh/config`
(Windows: `C:\Users\<you>\.ssh\config`) and add:

```
Host alpha3s-vps
  HostName 160.30.157.235
  User root
  IdentityFile ~/.ssh/alpha3s_vps
  ServerAliveInterval 30
```

Put the private key at `~/.ssh/alpha3s_vps`. On Mac/Linux fix its permissions:

```
$ chmod 600 ~/.ssh/alpha3s_vps
```

### Log in

```
$ ssh alpha3s-vps
```

You should see the prompt `root@azvps-1784814855:~#`. To leave: type `exit`.

> If you get `Permission denied (publickey)`: you don't have the right key, or it isn't
> authorized on the VPS. Contact whoever handed it over — **do not try a password, the VPS
> has it disabled.**

Most operations run in the deploy directory, so `cd` there right away:

```
root@vps:# cd /srv/alpha3s
```

---

## 2. System map (what runs where)

Everything runs via **Docker Compose**, file `docker-compose.prod.yml`. The containers:

| Container | Role | Ports |
|---|---|---|
| `caddy` | The only entry point from the Internet, handles HTTPS | 80, 443 (public) |
| `api` | FastAPI backend (webhook + API for the dashboard) | 8000 (internal only) |
| `worker` | Background message processing (queue) | — |
| `dashboard` | Admin UI (Next.js) | 3000 (internal only) |
| `db` | PostgreSQL (pgvector) — the data | 5432 (internal only) |
| `redis` | Queue + cache | 6379 (internal only) |
| `telegram_bot` | Admin Telegram bot | **currently OFF** (see §9) |
| `telegram_customer_bot` | Customer Telegram bot | **currently OFF** (see §9) |

Flow: **Internet → Caddy (HTTPS) → api/dashboard**. `db`/`redis` are not exposed; only the
containers talk to each other. The firewall (`ufw`) allows only ports 22 (SSH), 80, 443.

---

## 3. Everyday operations

> Always `cd /srv/alpha3s` first. Every docker command includes `-f docker-compose.prod.yml`.

### 3.1. Container status

```
root@vps:# docker compose -f docker-compose.prod.yml ps
```

The `STATUS` column should read `Up ...`. If you see `Exited` or a constant `Restarting` → there's a problem (see §10).

### 3.2. View logs

```
# Last 50 lines of api
root@vps:# docker compose -f docker-compose.prod.yml logs api --tail 50

# Follow the log live (Ctrl+C to exit)
root@vps:# docker compose -f docker-compose.prod.yml logs -f api

# Logs of all services
root@vps:# docker compose -f docker-compose.prod.yml logs --tail 30
```

Replace `api` with `worker`, `dashboard`, `db`, `caddy`... for other services.

### 3.3. Restart one service

```
root@vps:# docker compose -f docker-compose.prod.yml restart api
```

### 3.4. Restart everything / bring back up after a stop

```
root@vps:# docker compose -f docker-compose.prod.yml up -d
```

`up -d` only creates/starts whatever isn't running; it leaves running ones untouched.

### 3.5. Quick "is it alive" check

```
root@vps:# curl -s -o /dev/null -w "api: %{http_code}\n" http://localhost:8000/health
```

From your machine (checks external HTTPS):

```
$ curl -s -o /dev/null -w "%{http_code}\n" https://a3s.robanme.com/health
```

Both should return `200`.

---

## 4. Deploying code changes

### 4.1. The STANDARD way — automatic via GitHub (recommended)

Just **push to the `main` branch** on GitHub. GitHub Actions will automatically:
1. Run checks (`ruff` + tests).
2. If all pass → SSH into the VPS, pull the new code, rebuild, restart.

From your machine (inside the repo folder):

```
$ git add -A
$ git commit -m "short one-line description"
$ git push origin main
```

> ⚠️ **Commit messages must be ONE line** on Windows (the project has repeatedly created junk
> files from multi-line messages). For multiple lines use several `-m` flags: `git commit -m "line 1" -m "line 2"`.

Watch progress at: **GitHub → repo → Actions tab**. Green (✓) = done, red (✗) = failed —
click in to see which step broke.

### 4.2. The MANUAL way — when urgent or CI is broken

SSH into the VPS then:

```
root@vps:# cd /srv/alpha3s
root@vps:# git fetch origin main
root@vps:# git reset --hard origin/main
root@vps:# bash scripts/deploy.sh
```

`scripts/deploy.sh` rebuilds and restarts the services, then prunes old images. It prints the
container status at the end so you can check.

> **Note:** `scripts/deploy.sh` has a `SERVICES` variable listing which services get deployed.
> It's currently `db redis api worker dashboard` (the 2 Telegram bots excluded — see §9 Cutover).

---

## 5. Updating the Knowledge Base (KB V2)

When the knowledge content (`knowledge-base/` folder) changes and has been pushed to the VPS:

```
root@vps:# cd /srv/alpha3s
root@vps:# docker compose -f docker-compose.prod.yml exec -T api python scripts/kb_ingest.py
```

It prints how many "Knowledge Units" were ingested and **does NOT auto-activate** (safe). It
prints a SQL statement to activate the new index version — check the results above, then run
that statement, e.g.:

```
root@vps:# docker compose -f docker-compose.prod.yml exec -T db psql -U alpha3s -d alpha3s -c \
  "INSERT INTO kb_config (key, value) VALUES ('active_index_version', '2') \
   ON CONFLICT (key) DO UPDATE SET value = '2';"
```

(Replace `'2'` with the `index_version` the script just printed.)

Check the current unit count:

```
root@vps:# docker compose -f docker-compose.prod.yml exec -T db psql -U alpha3s -d alpha3s -c \
  "SELECT count(*) FROM kb_units; SELECT * FROM kb_config;"
```

---

## 6. Backup & Restore (IMPORTANT)

### 6.1. Backup — already automatic

A cron runs `pg_dump` daily at **03:00 VN time**, keeping the **14 most recent** copies in `/root/backups/`.

```
# List backups
root@vps:# ls -lh /root/backups/

# View the backup log (OK/FAIL per day)
root@vps:# cat /root/backups/backup.log
```

Run a manual backup right now (e.g. before doing something risky):

```
root@vps:# /root/bin/backup_db.sh && tail -1 /root/backups/backup.log
```

### 6.2. Restore — recover from a backup

> ⚠️ **A restore OVERWRITES all current data.** Only do it when you're sure. Run a manual
> backup (6.1) right before, in case you need to come back.

```
root@vps:# cd /srv/alpha3s

# 1) Stop the services that use the DB (keep db + redis running)
root@vps:# docker compose -f docker-compose.prod.yml stop api worker telegram_bot telegram_customer_bot

# 2) Drop and recreate an empty database
root@vps:# docker compose -f docker-compose.prod.yml exec -T db \
  psql -U alpha3s -d postgres -c "DROP DATABASE alpha3s WITH (FORCE); CREATE DATABASE alpha3s OWNER alpha3s;"

# 3) Load data from the backup (use the correct file name)
root@vps:# gunzip -c /root/backups/alpha3s_2026-07-23_0300.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T db psql -U alpha3s -d alpha3s

# 4) Start the services back up
root@vps:# docker compose -f docker-compose.prod.yml start api worker
```

Verify the data (e.g. product / order counts):

```
root@vps:# docker compose -f docker-compose.prod.yml exec -T db psql -U alpha3s -d alpha3s -c \
  "SELECT count(*) FROM products; SELECT count(*) FROM orders;"
```

---

## 7. The secret config file `.env`

Located at `/srv/alpha3s/.env` on the VPS (mode `600`, **never committed to git**).
Holds: Meta/Telegram tokens, LLM key, DB password, domains...

```
# View the variable names (careful — it has secrets, don't screenshot & share)
root@vps:# grep -E "^[A-Z]" /srv/alpha3s/.env | cut -d= -f1
```

Edit a variable (e.g. change the domain) with the `nano` editor:

```
root@vps:# nano /srv/alpha3s/.env
# When done: Ctrl+O (save), Enter, Ctrl+X (exit)
```

**After changing `.env` you must recreate the containers** to load the new values:

```
root@vps:# cd /srv/alpha3s
root@vps:# docker compose -f docker-compose.prod.yml up -d
```

> Variables starting with `NEXT_PUBLIC_` (dashboard) are baked in at build time — after
> changing them run `up -d dashboard` to rebuild.

---

## 8. Domains & HTTPS (Caddy)

HTTPS is **automatic** — Caddy obtains and renews Let's Encrypt certificates itself; nothing manual.

### Add / change a domain

1. **Create the DNS record** in the PA Vietnam panel (domain `robanme.com`):
   - Go to the correct **"record management" / Host–Type–Value–TTL list** section
     (NOT the "create child DNS" section — that one doesn't write to the real zone).
   - Add a record: **Host** = the subdomain (e.g. `a3s`), **Type** = `A`, **Value** = `160.30.157.235`, TTL `3600`. Save.
2. **Wait for DNS to point correctly**, then check (from your machine or the VPS):
   ```
   root@vps:# dig +short a3s.robanme.com @1.1.1.1
   ```
   It must return `160.30.157.235`.
3. **Declare the domain in `.env`** (`DOMAIN` for API/webhook, `DASH_DOMAIN` for the dashboard),
   then `up -d caddy`. Caddy fetches the certificate in ~30 seconds. Check the log if needed:
   ```
   root@vps:# docker compose -f docker-compose.prod.yml logs caddy --tail 20
   ```

---

## 8b. First dashboard login

The dashboard requires a staff account, and two things commonly trip you up on a domain:
1. **CORS** — the API must allow the dashboard's origin. Make sure `.env` has
   `DASHBOARD_CORS_ORIGINS=https://a3s-dash.robanme.com` (missing it makes login report a
   *fetch error*). After changing: `docker compose -f docker-compose.prod.yml up -d api`.
2. **No account yet** — `staff_users` is empty on a fresh deploy. Create the first admin account
   (one-time, replace `<...>` with real values):
   ```
   docker compose -f docker-compose.prod.yml exec -T api \
     python scripts/create_staff_user.py <username> '<password>' '<display name>'
   ```
   Later accounts are created right in the dashboard (Staff section) — no need to rerun this.

## 9. Cutover: move the customer channel to the VPS (⚠️ touches real customers)

The **local machine is still serving real customers** (Messenger webhook + 2 Telegram bots).
The VPS runs in parallel but its 2 Telegram bots are **OFF** so they don't fight the local ones
for the token (running both causes `409 Conflict`). To move fully to the VPS:

1. **Enable the 2 Telegram bots in the deploy:** edit `scripts/deploy.sh`, add
   `telegram_bot telegram_customer_bot` to the `SERVICES` variable, then commit + push (or manual deploy).
2. **Turn OFF the 2 local Telegram bots FIRST** (otherwise 409 fighting over `getUpdates`).
3. **Point the Messenger webhook at the VPS** (Meta App dashboard):
   - Callback URL: `https://a3s.robanme.com/webhook`
   - Verify Token: exactly the `META_VERIFY_TOKEN` value from the VPS `.env`.
   - Meta calls `GET /webhook` to verify — if the token matches it succeeds.
4. **Confirm the VPS receives messages:** send a test message to the page, watch the log:
   ```
   root@vps:# docker compose -f docker-compose.prod.yml logs -f api
   ```
   Seeing a `POST /webhook` request means it's live.
5. Watch closely for the first few hours (logs + Telegram alerts). To revert: point the webhook
   back to the old URL + turn off the bots on the VPS + turn them back on locally.

---

## 10. Common troubleshooting

| Symptom | What to do |
|---|---|
| A container is `Exited`/constantly `Restarting` | View its log (`logs <name> --tail 100`). After fixing: `up -d <name>`. |
| The site returns `502 Bad Gateway` | The backend (api/dashboard) is starting or has died. Wait ~1 min; if still down: `restart api` / `restart dashboard`, check the log. |
| Can't reach HTTPS, cert error | Check `logs caddy`. Usually DNS not pointing at the right IP, or port 80 blocked. Check `dig` (§8) and `ufw status`. |
| Messenger webhook not receiving | Check the webhook URL/verify token on Meta; check `logs -f api` for `POST /webhook`; check `META_APP_SECRET` is correct (wrong signature → 403). |
| Telegram bot `409 Conflict` | Running in two places at once (local + VPS). Turn one off. |
| Bot slow/not replying, messages seem stuck | Check the error queue: `docker compose -f docker-compose.prod.yml exec -T redis redis-cli LLEN dead_letter:messages`. >0 means failed messages. |
| Out of disk | `df -h /`. Prune old images: `docker image prune -f`. See usage with `docker system df`. |
| VPS laggy / out of RAM | `free -h` and `docker stats --no-stream`. There's a 2G swap available. |
| Data mistake/incident | Restore from a backup (§6.2). |

Quick resource check:

```
root@vps:# free -h ; df -h / ; docker stats --no-stream --format "{{.Name}}: {{.MemUsage}}"
```

Automatic alerting: a 5-minute cron checks the error queue / dead containers / disk >85% and
messages the **"Alpha3s admin"** Telegram group (script `/root/bin/alert_check.sh`).

---

## 11. Emergency rollback (revert to the previous version)

If a new deploy is broken and you need to revert immediately:

```
root@vps:# cd /srv/alpha3s

# Look at the commit history
root@vps:# git log --oneline -5

# Go back to the previous commit (replace <SHA> with the last good commit id)
root@vps:# git reset --hard <SHA>
root@vps:# bash scripts/deploy.sh
```

Once stable, remember to fix the bug on `main` at GitHub and deploy again normally (the next
push will override this state).

---

## 12. Security & mandatory conventions

- **Never commit `.env`** or any secret to git.
- **Never re-enable SSH password login.** Key only. Keep the key file safe; if lost, use the
  provider console.
- **One-line commit messages** (the project's junk-file lesson — see `CLAUDE.md`).
- Don't open extra firewall ports unless truly needed (`ufw`). Currently only 22/80/443.
- After editing `.env` always `up -d` to take effect; change code always via git → CI deploy.
- Before doing anything risky to the DB, **run a manual backup first** (§6.1).

---

## 13. Quick reference

| Task | Command (already `cd /srv/alpha3s`) |
|---|---|
| Status | `docker compose -f docker-compose.prod.yml ps` |
| Log one service | `docker compose -f docker-compose.prod.yml logs -f api` |
| Restart one service | `docker compose -f docker-compose.prod.yml restart api` |
| Bring all back up | `docker compose -f docker-compose.prod.yml up -d` |
| Manual deploy | `git fetch origin main && git reset --hard origin/main && bash scripts/deploy.sh` |
| Backup now | `/root/bin/backup_db.sh` |
| Open the DB (psql) | `docker compose -f docker-compose.prod.yml exec db psql -U alpha3s -d alpha3s` |
| API health | `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/health` |

- Dashboard: https://a3s-dash.robanme.com
- API/health: https://a3s.robanme.com/health
- Repo: https://github.com/ledanghoai-bot/a3s (Actions = deploy status)
