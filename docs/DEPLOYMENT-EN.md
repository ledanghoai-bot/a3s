# DEPLOYMENT — Alpha3S production (issue #9)

Real deployment runbook, updated after the VPS + GitHub CI/CD went live (2026-07-24).

> 👉 Need **step-by-step instructions for staff to operate the system themselves** (SSH,
> viewing logs, restart, deploy, restoring backups, troubleshooting...)? See
> **[`docs/VPS-RUNBOOK-EN.md`](VPS-RUNBOOK-EN.md)**. This file (DEPLOYMENT-EN.md) is the
> "what / where" technical reference. Vietnamese: `DEPLOYMENT-VI.md`.

## 1. Infrastructure overview

| Component | Value |
|---|---|
| VPS | `160.30.157.235` (Ubuntu 24.04, 4 vCPU / 8GB / 60GB), SSH alias `alpha3s-vps` |
| Deploy directory | `/srv/alpha3s` — a real git clone, `origin` = GitHub |
| Repo | `github.com/ledanghoai-bot/a3s` (moved off GitLab — GitLab is paid + blocked CI due to unverified identity) |
| Domains | `a3s.robanme.com` (API/webhook) · `a3s-dash.robanme.com` (dashboard) |
| HTTPS | Caddy auto-obtains/renews Let's Encrypt |
| Compose | `docker-compose.prod.yml` (standalone, no source bind-mount) |

## 2. Service tree (`docker-compose.prod.yml`)

- `api` (FastAPI, 2 uvicorn workers) — binds `127.0.0.1:8000`
- `worker` (arq) — durable message processing
- `dashboard` (Next.js production) — binds `127.0.0.1:3000`
- `db` (pgvector/pg16) · `redis` (7-alpine) — **not** exposed to the outside
- `caddy` — reverse proxy + HTTPS, publishes `80/443`; routes domains → api/dashboard
- `telegram_bot` + `telegram_customer_bot` — **currently STOPPED** on the VPS (see §6 Cutover)

> api/dashboard bind `127.0.0.1` because Docker's published ports bypass iptables so `ufw`
> can't block them. All external access must go through Caddy (HTTPS).

## 3. Automated deploy (default)

Push to GitHub `main` → GitHub Actions (`.github/workflows/deploy.yml`):
1. `lint-test`: `ruff check app` (config `ruff.toml` — E/F/I) + `pytest -v`
2. `deploy`: SSH into the VPS, run `git fetch/reset --hard origin/main` + `scripts/deploy.sh`

`scripts/deploy.sh` runs `docker compose -f docker-compose.prod.yml up -d --build` for the
services listed in `SERVICES`, then `docker image prune -f`.

**Secrets (GitHub → Settings → Secrets → Actions):**
- `VPS_HOST` = `160.30.157.235`
- `VPS_SSH_KEY` = ed25519 private key (public is in root's `~/.ssh/authorized_keys` on the VPS)

## 4. Manual deploy (when needed)

```bash
ssh alpha3s-vps
cd /srv/alpha3s
git fetch origin main && git reset --hard origin/main
bash scripts/deploy.sh
```

## 5. Production `.env` (VPS only, NEVER committed)

Differs from dev: `APP_ENV=production`, a randomly generated `POSTGRES_PASSWORD` (48 hex),
a matching `DATABASE_URL`, `DOMAIN`/`DASH_DOMAIN` = the two robanme domains,
`NEXT_PUBLIC_API_URL=https://a3s.robanme.com`. File is `chmod 600`.

## 6. Cutover to the VPS (NOT done yet — a deliberate action)

The local machine is still the de-facto production. To move fully to the VPS:
1. Add `telegram_bot telegram_customer_bot` to `SERVICES` in `scripts/deploy.sh`.
2. **Stop the 2 local Telegram bots first** (avoid two `getUpdates` pollers clashing → 409).
3. Point the Messenger webhook (Meta App) at `https://a3s.robanme.com/<webhook-path>`.
4. Redeploy + confirm the VPS logs receive the webhook.

## 7. Backup & Alert (issue #9 Batch 4)

- Backup: `/root/bin/backup_db.sh` via `/etc/cron.d/alpha3s-backup` — gzipped `pg_dump`
  daily at 03:00 (VN time), keeps 14 copies in `/root/backups/`, log at `backup.log`.
- Alert: `/root/bin/alert_check.sh` via `/etc/cron.d/alpha3s-alert` — every 5 min checks
  the Redis dead-letter / non-Up containers / disk >85%, messages the admin Telegram bot
  ("Alpha3s admin" group), rate-limited 1h/type.

## 8. SSH security

- Key-only login (`PasswordAuthentication no` — `/etc/ssh/sshd_config.d/00-hardening.conf`).
- Dev machine key: `~/.ssh/alpha3s_vps`. GitHub CI key: stored in the GitHub Secret `VPS_SSH_KEY`.
- `ufw` allows only `22/80/443`. Fallback if the key is lost: the provider's console.
