#!/bin/bash
# F-PR27-E01 — kiem PROVENANCE cua image DANG CHAY: nhan cua image phai khop DUNG commit dang deploy.
#
# VI SAO TACH RIENG KHOI deploy.sh
# CA (PHASE1B-M4-PR27-MERGE-DEPLOY-DORMANT-EVIDENCE-REVIEW-1-VI) doi "dat VA kiem" nhan, kem test
# chung minh fail-closed. Mot doan kiem nam long trong deploy.sh thi chi chay duoc khi deploy that
# -- tuc khong the test truoc khi merge. Tach ra thanh script rieng de:
#   * deploy.sh goi no (duong that), va
#   * kich ban evidence goi CHINH no tren container that voi nhan dung/sai (xem
#     scripts/m4_image_provenance_evidence.sh) -> chung minh no THUC SU do, khong phai tin loi.
#
# Kiem tren CONTAINER DANG CHAY chu khong phai tren image vua build: dieu can chung minh la "thu
# dang phuc vu sinh ra tu commit nay", khong phai "co ton tai mot image dung o dau do".
#
# Dung:  verify_image_provenance.sh <commit-40-hex> <service...>
# Exit:  0 tat ca khop | 1 co service lech/thieu nhan | 2 sai cach dung
set -uo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
LABEL_KEY="${LABEL_KEY:-org.opencontainers.image.revision}"

MONG_DOI="${1:-}"
shift || true
if ! printf '%s' "$MONG_DOI" | grep -Eq '^[0-9a-f]{40}$' || [ "$#" -eq 0 ]; then
  echo "dung: $0 <commit-40-hex> <service...>" >&2
  exit 2
fi

echo "=== kiem image provenance (nhan '$LABEL_KEY' phai = $MONG_DOI) ==="
lech=0
for svc in "$@"; do
  cid=$(docker compose -f "$COMPOSE_FILE" ps -q "$svc" 2>/dev/null | head -1)
  if [ -z "$cid" ]; then
    # Service one-shot (vd migrate) da thoat: van phai kiem duoc -> tim ca container da dung.
    cid=$(docker compose -f "$COMPOSE_FILE" ps -aq "$svc" 2>/dev/null | head -1)
  fi
  if [ -z "$cid" ]; then
    echo "  THIEU   $svc: khong tim thay container nao"
    lech=$((lech + 1))
    continue
  fi
  img=$(docker inspect "$cid" --format '{{.Image}}' 2>/dev/null)
  thuc_te=$(docker inspect "$img" --format "{{index .Config.Labels \"$LABEL_KEY\"}}" 2>/dev/null)
  if [ "$thuc_te" = "$MONG_DOI" ]; then
    echo "  OK      $svc: $thuc_te"
  else
    echo "  LECH    $svc: nhan='${thuc_te:-<khong co>}' nhung dang deploy commit $MONG_DOI"
    lech=$((lech + 1))
  fi
done

if [ "$lech" -ne 0 ]; then
  echo "STOP (F-PR27-E01): $lech service khong chung minh duoc nguon goc image." >&2
  echo "  Nghia la co the mot image CU dang phuc vu du checkout da o commit moi." >&2
  exit 1
fi
echo "tat ca service deu khop commit dang deploy."
