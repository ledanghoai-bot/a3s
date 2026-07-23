# DEPLOYMENT — Alpha3S production (issue #9)

Tài liệu quy trình deploy thật, cập nhật sau khi VPS + CI/CD GitHub đã chạy (24/07/2026).

> 👉 Cần hướng dẫn **thao tác từng bước cho staff tự vận hành** (SSH, xem log, restart,
> deploy, restore backup, xử lý sự cố...)? Xem **[`docs/VPS-RUNBOOK-VI.md`](VPS-RUNBOOK-VI.md)**.
> File này (DEPLOYMENT-VI.md) là bản tham chiếu kỹ thuật "cái gì / ở đâu". English: `DEPLOYMENT-EN.md`.

## 1. Tổng quan hạ tầng

| Thành phần | Giá trị |
|---|---|
| VPS | `160.30.157.235` (Ubuntu 24.04, 4 vCPU / 8GB / 60GB), SSH alias `alpha3s-vps` |
| Thư mục deploy | `/srv/alpha3s` — git clone thật, remote `origin` = GitHub |
| Repo | `github.com/ledanghoai-bot/a3s` (đã chuyển từ GitLab — GitLab trả phí + chặn CI vì chưa xác minh danh tính) |
| Domain | `a3s.robanme.com` (API/webhook) · `a3s-dash.robanme.com` (dashboard) |
| HTTPS | Caddy tự xin/gia hạn Let's Encrypt |
| Compose | `docker-compose.prod.yml` (độc lập, không bind-mount source) |

## 2. Cây service (`docker-compose.prod.yml`)

- `api` (FastAPI, uvicorn 2 worker) — bind `127.0.0.1:8000`
- `worker` (arq) — xử lý message durable
- `dashboard` (Next.js production) — bind `127.0.0.1:3000`
- `db` (pgvector/pg16) · `redis` (7-alpine) — **không** expose port ra ngoài
- `caddy` — reverse proxy + HTTPS, publish `80/443`; route domain → api/dashboard
- `telegram_bot` + `telegram_customer_bot` — **hiện STOP** trên VPS (xem §6 Cutover)

> api/dashboard bind `127.0.0.1` vì Docker publish port đi tắt qua iptables → `ufw`
> không chặn được. Mọi truy cập ngoài bắt buộc qua Caddy (HTTPS).

## 3. Deploy tự động (mặc định)

Push lên `main` của GitHub → GitHub Actions (`.github/workflows/deploy.yml`):
1. `lint-test`: `ruff check app` (config `ruff.toml` — E/F/I) + `pytest -v`
2. `deploy`: SSH vào VPS chạy `git fetch/reset --hard origin/main` + `scripts/deploy.sh`

`scripts/deploy.sh` chạy `docker compose -f docker-compose.prod.yml up -d --build`
cho danh sách service trong biến `SERVICES`, rồi `docker image prune -f`.

**Secrets (GitHub → Settings → Secrets → Actions):**
- `VPS_HOST` = `160.30.157.235`
- `VPS_SSH_KEY` = private key ed25519 (public đã nằm trong `~/.ssh/authorized_keys` của root VPS)

## 4. Deploy tay (khi cần)

```bash
ssh alpha3s-vps
cd /srv/alpha3s
git fetch origin main && git reset --hard origin/main
bash scripts/deploy.sh
```

## 5. `.env` production (chỉ trên VPS, KHÔNG commit)

Khác bản dev: `APP_ENV=production`, `POSTGRES_PASSWORD` sinh ngẫu nhiên (48 hex),
`DATABASE_URL` khớp mật khẩu đó, `DOMAIN`/`DASH_DOMAIN` = 2 domain robanme,
`NEXT_PUBLIC_API_URL=https://a3s.robanme.com`. File `chmod 600`.

## 6. Cutover sang VPS (CHƯA làm — cần thao tác có chủ đích)

Hiện máy local vẫn là production thực tế. Để chuyển hẳn sang VPS:
1. Thêm `telegram_bot telegram_customer_bot` vào `SERVICES` trong `scripts/deploy.sh`.
2. **Stop 2 bot Telegram trên máy local trước** (tránh 2 nơi cùng polling `getUpdates` → 409).
3. Trỏ webhook Messenger (Meta App) về `https://a3s.robanme.com/<đường-webhook>`.
4. Deploy lại + xác nhận log nhận webhook trên VPS.

## 7. Backup & Alert (issue #9 Bat 4)

- Backup: `/root/bin/backup_db.sh` qua `/etc/cron.d/alpha3s-backup` — `pg_dump`
  gzip mỗi 03:00 (giờ VN), giữ 14 bản tại `/root/backups/`, log `backup.log`.
- Alert: `/root/bin/alert_check.sh` qua `/etc/cron.d/alpha3s-alert` — mỗi 5 phút
  kiểm tra dead-letter Redis / container không Up / disk >85%, gửi Telegram bot
  admin (group "Alpha3s admin"), rate-limit 1h/loại.

## 8. Bảo mật SSH

- Chỉ đăng nhập bằng key (`PasswordAuthentication no` — `/etc/ssh/sshd_config.d/00-hardening.conf`).
- Key máy dev: `~/.ssh/alpha3s_vps`. Key GitHub CI: lưu trong GitHub Secret `VPS_SSH_KEY`.
- `ufw` chỉ mở `22/80/443`. Fallback nếu mất key: console trong panel nhà cung cấp.
