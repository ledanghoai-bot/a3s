#!/bin/bash
# Deploy len VPS production (issue #9) — duoc goi tu stage `deploy` trong
# .gitlab-ci.yml SAU KHI CI da fetch + reset ve origin/main tai /srv/alpha3s.
#
# Danh sach service duoc "up" dat o day (trong repo) de moi thay doi ve
# thanh phan chay production deu qua review + deploy chinh thuc.
#
# LUU Y CUTOVER (tam thoi, xoa ghi chu nay khi xong):
# - telegram_bot + telegram_customer_bot CHUA chay tren VPS — may local van
#   dang la production thuc te (polling getUpdates se tranh token neu chay
#   ca 2 noi). Khi cutover: them 2 service do vao SERVICES ben duoi.
# - caddy chi chay khi .env tren VPS da co DOMAIN/DASH_DOMAIN that.
set -euo pipefail
cd /srv/alpha3s

SERVICES="db redis api worker dashboard"

docker compose -f docker-compose.prod.yml up -d --build $SERVICES

# Don image cu sau khi build de khong day disk (60GB)
docker image prune -f >/dev/null

echo "=== deploy xong — trang thai container ==="
docker compose -f docker-compose.prod.yml ps --format '{{.Name}}: {{.Status}}'
