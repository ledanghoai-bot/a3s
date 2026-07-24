#!/bin/bash
# Deploy len VPS production (issue #9) — duoc goi tu stage `deploy` trong
# .github/workflows/deploy.yml SAU KHI CI da fetch + reset ve origin/main tai
# /srv/alpha3s.
#
# Danh sach service duoc "up" dat o day (trong repo) de moi thay doi ve
# thanh phan chay production deu qua review + deploy chinh thuc.
#
# TRANG THAI CUTOVER (24/7/2026):
# - telegram_customer_bot + telegram_bot (admin): DA chay tren VPS. Bot local
#   da GO HAN (docker compose rm) => khong con tranh token getUpdates (409).
#   Ca 2 kenh Telegram gio thuoc ve VPS.
# - Messenger webhook: CHUA cutover (van tro may local / cho quyet dinh #7).
# - caddy: chi chay khi .env tren VPS co DOMAIN/DASH_DOMAIN that (da co).
set -euo pipefail
cd /srv/alpha3s

SERVICES="db redis api worker dashboard telegram_customer_bot telegram_bot"

docker compose -f docker-compose.prod.yml up -d --build $SERVICES

# Don image cu sau khi build de khong day disk (60GB)
docker image prune -f >/dev/null

echo "=== deploy xong — trang thai container ==="
docker compose -f docker-compose.prod.yml ps --format '{{.Name}}: {{.Status}}'
