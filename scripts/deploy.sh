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

# F-PR24-01: `migrate` nam trong danh sach nay.
#
# Truoc PR nay, danh sach KHONG co migrate va deploy.sh khong chay migration nao — nen PR #24
# merge/deploy thanh cong trong khi migration 044 van PENDING, va ledger cho thay 040-043 deu duoc
# ap THU CONG. Moi PR mang migration deu co the deploy tren schema CU ma khong gi bao lech.
#
# Vi sao chi can them vao day: api/worker/telegram_bot/telegram_customer_bot deu co
# `depends_on: migrate: condition: service_completed_successfully` trong docker-compose.prod.yml.
# Compose se chay `migrate` TRUOC, va neu no exit != 0 thi `up` that bai -> `set -e` o dau file lam
# deploy.sh thoat != 0 -> stage deploy cua CI do -> ung dung KHONG duoc rollout tren schema cu.
# Day la fail-closed o CA HAI lop: Compose (khong start service) va CI (stage do).
SERVICES="db redis migrate api worker dashboard telegram_customer_bot telegram_bot"

# F-PR27-E01: tap con cua SERVICES duoc BUILD TU Dockerfile trong repo nay -- chi nhung image do
# moi mang duoc nhan commit. `db` (pgvector) va `redis` la image thuong nguon ngoai, khong co va
# KHONG NEN co nhan cua ta; dua chung vao buoc kiem se tao bao dong gia roi som muon bi lam ngo.
SERVICES_CO_NHAN="migrate api worker dashboard telegram_customer_bot telegram_bot"

# F-PR27-E01 (CA PHASE1B-M4-PR27-MERGE-DEPLOY-DORMANT-EVIDENCE-REVIEW-1-VI): commit dang deploy
# phai di VAO image, khong phai chi nam trong checkout.
#
# Truoc correction nay deploy.sh khong set GIT_COMMIT, nen Dockerfile roi ve mac dinh `unknown`
# va MOI image production deu mang nhan vo nghia. Evidence cua gate PR #27 vi vay khong chung
# minh duoc image DANG CHAY sinh ra tu commit nao -- mot image cu van co the ton tai trong cung
# checkout voi timestamp gan luc deploy.
#
# CI da `git reset --hard origin/main` truoc khi goi file nay, nen HEAD o day CHINH LA commit
# dang duoc deploy.
GIT_COMMIT="$(git rev-parse HEAD)"
export GIT_COMMIT
if ! printf '%s' "$GIT_COMMIT" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "LOI (F-PR27-E01): khong lay duoc commit hop le tu git rev-parse HEAD (nhan: '$GIT_COMMIT')" >&2
  exit 1
fi
echo "=== deploy commit: $GIT_COMMIT ==="

docker compose -f docker-compose.prod.yml up -d --build $SERVICES

# In ket qua migration ra log deploy de operator/CI thay duoc, khong phai doan.
echo "=== ket qua migration (job one-shot 'migrate') ==="
docker compose -f docker-compose.prod.yml logs --no-color --tail 30 migrate || true
MIGRATE_RC=$(docker compose -f docker-compose.prod.yml ps -a --format '{{.Name}} {{.ExitCode}}' \
  | awk '/migrate/ {print $2; exit}')
echo "migrate exit code = ${MIGRATE_RC:-khong-xac-dinh}"
if [ "${MIGRATE_RC:-1}" != "0" ]; then
  echo "LOI: migration KHONG thanh cong -> dung deploy, KHONG rollout ung dung tren schema cu"
  exit 1
fi

# Don image cu sau khi build de khong day disk (60GB)
docker image prune -f >/dev/null

# F-PR27-E01: DAT nhan thoi thi chua du -- phai KIEM lai tren container dang chay. Neu mot
# service nao do van chay image cu (cache/build that bai am tham), buoc nay lam deploy DO thay
# vi bao thanh cong roi de operator tu phat hien sau.
bash scripts/verify_image_provenance.sh "$GIT_COMMIT" $SERVICES_CO_NHAN

echo "=== deploy xong — trang thai container ==="
docker compose -f docker-compose.prod.yml ps --format '{{.Name}}: {{.Status}}'
