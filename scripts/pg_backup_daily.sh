#!/bin/bash
# Alpha3S — daily DB backup (I-B M0, PO approved 2026-07-25).
# pg_dump + gzip vao /srv/backups + verify gzip + retention 14 ban gan nhat.
# Deploy tren VPS tai /srv/pg_backup_daily.sh (ngoai repo, tranh git drift); cron chay hang ngay.
set -euo pipefail
BK_DIR=/srv/backups
mkdir -p "$BK_DIR"
TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$BK_DIR/alpha3s_daily_$TS.sql.gz"
cd /srv/alpha3s
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U alpha3s -d alpha3s | gzip > "$OUT"
gzip -t "$OUT"   # verify toan ven; loi -> set -e dung + non-zero exit
# retention: xoa cac ban cu hon 14 ban gan nhat
ls -1t "$BK_DIR"/alpha3s_daily_*.sql.gz | tail -n +15 | xargs -r rm -f
echo "$(date -u +%FT%TZ) backup OK: $(basename "$OUT") ($(du -h "$OUT" | cut -f1))"
