#!/bin/bash
# F-PR27-E01 — bang chung THUC THI cho image provenance. CHI SANDBOX, khong cham production.
#
# CA doi "test chung minh missing/invalid commit metadata fail-closed hoac deployment bi chan".
# Kich ban nay khong doc source roi khang dinh; no CHAY docker build THAT va CHINH script
# verify_image_provenance.sh that:
#
#   [A] build voi commit hop le          -> THANH CONG, nhan mang dung commit do
#   [B] build KHONG truyen GIT_COMMIT    -> HONG (khong the tao image khong truy nguon duoc)
#   [C] build voi gia tri rac            -> HONG
#   [D] build voi chuoi rong (dung gia tri Compose truyen khi bien chua dat) -> HONG
#   [E] verify tren CONTAINER THAT, nhan dung   -> exit 0
#   [F] verify tren CONTAINER THAT, nhan lech   -> exit 1  (day la nua "deployment bi chan")
#
# Dung: bash scripts/m4_image_provenance_evidence.sh [duong-dan-repo]
set -uo pipefail
REPO="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
COMMIT_GIA="1111111111111111111111111111111111111111"
COMMIT_KHAC="2222222222222222222222222222222222222222"
TAG="a3s-provenance-evidence:tmp"
CTN="a3s-provenance-evidence-ctn"
loi=0

kiem() {  # kiem <mong doi: 0|khac0> <nhan>
  if [ "$1" -eq 0 ] && [ "$2" -eq 0 ]; then echo "  PASS  $3"; return; fi
  if [ "$1" -ne 0 ] && [ "$2" -ne 0 ]; then echo "  PASS  $3 (exit=$2)"; return; fi
  echo "  FAIL  $3 (exit=$2, mong doi $([ "$1" -eq 0 ] && echo 0 || echo 'khac 0'))"
  loi=$((loi + 1))
}

don_dep() {
  rm -rf "${REPO:-.}/.tmp-provenance-evidence"
  docker rm -f "$CTN" >/dev/null 2>&1
  docker rmi -f "$TAG" >/dev/null 2>&1
}
trap don_dep EXIT

cd "$REPO" || exit 2
echo "=== [A] build voi commit hop le -> phai THANH CONG va mang dung nhan ==="
docker build -q --build-arg GIT_COMMIT="$COMMIT_GIA" -t "$TAG" . >/dev/null 2>&1
kiem 0 $? "build voi GIT_COMMIT hop le thanh cong"
for k in org.opencontainers.image.revision git_commit; do
  gt=$(docker inspect "$TAG" --format "{{index .Config.Labels \"$k\"}}" 2>/dev/null)
  [ "$gt" = "$COMMIT_GIA" ]
  kiem 0 $? "nhan $k = commit da truyen ($gt)"
done

echo "=== [B]/[C]/[D] build KHONG hop le -> phai HONG (fail-closed) ==="
docker build -q -t "$TAG-b" . >/dev/null 2>&1
kiem 1 $? "khong truyen GIT_COMMIT: build bi tu choi"
docker rmi -f "$TAG-b" >/dev/null 2>&1

docker build -q --build-arg GIT_COMMIT="khong-phai-sha" -t "$TAG-c" . >/dev/null 2>&1
kiem 1 $? "GIT_COMMIT rac: build bi tu choi"
docker rmi -f "$TAG-c" >/dev/null 2>&1

docker build -q --build-arg GIT_COMMIT="" -t "$TAG-d" . >/dev/null 2>&1
kiem 1 $? "GIT_COMMIT rong (gia tri Compose truyen khi bien chua dat): build bi tu choi"
docker rmi -f "$TAG-d" >/dev/null 2>&1

echo "=== [E]/[F] chay CHINH verify_image_provenance.sh qua mot compose project THAT ==="
# Dung compose project tam de goi DUNG duong ma deploy.sh goi (tra cuu container qua
# `docker compose ps -q <service>`), nen ca hai ca duoi deu di qua y HET logic chay tren
# production.
#
# Thu muc tam dat TRONG repo, khong dung mktemp -d: tren may dev Windows, /tmp cua MSYS anh xa
# ra mot duong dan ma docker.exe KHONG thay (da gap that: "open D:	mp\...: cannot find path"),
# lam container probe khong dung duoc va bien phep thu [F] thanh xanh vi LY DO SAI.
# Duong dan TUONG DOI (da `cd "$REPO"` o tren): tren Git Bash/Windows, mot duong dan POSIX tuyet
# doi kieu /d/alpha3s/... khong duoc docker.exe hieu khi MSYS_NO_PATHCONV=1. Tuong doi thi dung
# tren ca Linux (CI/VPS) lan may dev.
TMP=".tmp-provenance-evidence"
rm -rf "$TMP"; mkdir -p "$TMP"
cat > "$TMP/compose.yml" <<YAML
services:
  probe:
    image: TAG_PLACEHOLDER
    entrypoint: ["sleep", "infinity"]
YAML
sed -i "s|TAG_PLACEHOLDER|$TAG|" "$TMP/compose.yml"
docker compose -f "$TMP/compose.yml" up -d >/dev/null 2>&1
kiem 0 $? "dung container that tu image vua build (qua docker compose)"

ket_E=$(COMPOSE_FILE="$TMP/compose.yml" bash scripts/verify_image_provenance.sh "$COMMIT_GIA" probe 2>&1); rc_E=$?
kiem 0 $rc_E "[E] nhan KHOP commit dang deploy -> verify exit 0"
printf '%s
' "$ket_E" | grep -q "OK      probe"
kiem 0 $? "[E] bao cao dung service probe la OK (khong phai xanh vi bo qua)"

ket_F=$(COMPOSE_FILE="$TMP/compose.yml" bash scripts/verify_image_provenance.sh "$COMMIT_KHAC" probe 2>&1); rc_F=$?
kiem 1 $rc_F "[F] nhan LECH (image cu dang chay) -> verify exit 1 = deploy bi CHAN"
# Chan false-green: [F] phai do vi LECH NHAN, khong phai vi khong tim thay container.
printf '%s
' "$ket_F" | grep -q "LECH    probe"
kiem 0 $? "[F] do DUNG LY DO: bao LECH nhan (khong phai THIEU container)"
printf '%s
' "$ket_F" | grep -q "THIEU"
kiem 1 $? "[F] KHONG bao THIEU (xac nhan container that su ton tai luc kiem)"

ket_G=$(COMPOSE_FILE="$TMP/compose.yml" bash scripts/verify_image_provenance.sh "$COMMIT_GIA" khong-ton-tai 2>&1); rc_G=$?
kiem 1 $rc_G "service khong co container -> exit 1 (khong im lang bo qua)"

bash scripts/verify_image_provenance.sh "$COMMIT_GIA" >/dev/null 2>&1
kiem 1 $? "goi thieu tham so service -> exit khac 0"

docker compose -f "$TMP/compose.yml" down -v >/dev/null 2>&1
rm -rf "$TMP"

echo
if [ "$loi" -ne 0 ]; then echo "KHONG DAT: $loi muc."; exit 1; fi
echo "TAT CA DAT: build fail-closed, va verify CHAN duoc image lech commit."
