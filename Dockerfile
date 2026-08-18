FROM python:3.12-slim
WORKDIR /srv

# Cai torch CPU-only truoc (nhe hon ~800MB so voi full torch)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# I-B M4 Stage 0P (A08-COR-01/F-A08-R1-01): 2 tai khoan he thong CO DINH, tao luc BUILD IMAGE
# (khong phai runtime `useradd` trong container dang chay) -- UID/GID on dinh, version-controlled,
# giong het nhau tren MOI container tao tu image nay (api/worker/m4-signer...), khong con phu
# thuoc mutable/ephemeral container state. `m4-signer` chay signing service that (giu khoa ky,
# xem docker-compose.prod.yml service `m4-signer`); `m4-collector` la UID rehearsal
# runner/collector chay duoi khi execute that (qua `docker compose exec --user m4-collector`) --
# 2 UID he dieu hanh THAT tach biet dung yeu cau CA T12-01.
RUN groupadd -g 5000 m4-signing-ipc \
    && useradd -r -M -s /usr/sbin/nologin -u 5001 -g m4-signing-ipc m4-signer \
    && useradd -r -M -s /usr/sbin/nologin -u 5002 -g m4-signing-ipc m4-collector

COPY . .

# I-B M4 image-freshness correction (dap PHASE1B-M4-AMENDMENT-10-EXECUTION-ATTEMPT-1-ABORT-REVIEW-VI.md):
# nhan commit git luc BUILD vao image, de co the xac minh 1 image dormant/profile-only (vd m4-signer,
# khong nam trong deploy.sh SERVICES nen khong tu rebuild) co dung tu SOURCE moi nhat hay dang la cache
# cu truoc 1 fix da merge (day chinh la nguyen nhan Amendment 10 Attempt 1 crash lai loi .env da fix).
#
# VI TRI CO Y dat SAU TAT CA cac layer nang (pip torch/requirements) va SAU `COPY . .`: `ARG` lam
# INVALIDATE CACHE cua MOI layer dung sau no, nen neu dat ARG o dau file thi MOI lan doi GIT_COMMIT
# (tuc MOI ceremony) se build lai tu dau -- tai lai ~800MB torch + toan bo pip, va sinh them ~2GB
# layer moi moi lan tren VPS 60GB. Dat cuoi file: doi GIT_COMMIT chi rebuild layer metadata LABEL
# (tuc thi), con cac layer pip van CACHED khi requirements.txt khong doi.
#
# F-PR27-E01 (CA PHASE1B-M4-PR27-MERGE-DEPLOY-DORMANT-EVIDENCE-REVIEW-1-VI): TRUOC correction nay
# dong duoi la `ARG GIT_COMMIT=unknown`, tuc mot FALLBACK IM LANG. Hau qua do duoc tren production:
# `deploy.sh` khong set GIT_COMMIT, `api`/`worker`/2 bot lai dung `build: .` tran (khong truyen arg
# nao), nen MOI image production deu mang nhan `git_commit=unknown`. Nhan ton tai nhung khong noi
# len dieu gi -- khong the chung minh image DANG CHAY sinh ra tu commit nao.
#
# Gio KHONG con mac dinh: thieu/sai GIT_COMMIT thi BUILD HONG (fail-closed), khong the tao ra mot
# image production khong truy nguon duoc. Kiem tai day (build) chu khong o Compose interpolation la
# co y -- bai hoc F-H2A2-01: `${VAR:?}` trong Compose noi suy TOAN FILE truoc khi chon profile, nen
# no lam hong ca `docker compose config` cua deploy dormant. Rang buoc phai nam o noi thuc su tao
# ra image.
ARG GIT_COMMIT
RUN set -eu; \
    if ! printf '%s' "${GIT_COMMIT:-}" | grep -Eq '^[0-9a-f]{40}$'; then \
      echo "STOP (F-PR27-E01): build-arg GIT_COMMIT thieu hoac khong phai commit SHA 40 hex." >&2; \
      echo "  nhan duoc: '${GIT_COMMIT:-<khong dat>}'" >&2; \
      echo "  deploy path phai truyen DUNG commit dang duoc deploy, vd:" >&2; \
      echo "    GIT_COMMIT=\$(git rev-parse HEAD) docker compose -f docker-compose.prod.yml up -d --build" >&2; \
      exit 1; \
    fi

# Nhan chuan OCI (CA yeu cau) + giu `git_commit` cu de runbook/lenh kiem da co khong vo.
LABEL org.opencontainers.image.revision=$GIT_COMMIT
LABEL git_commit=$GIT_COMMIT

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
