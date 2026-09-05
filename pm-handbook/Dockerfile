# pm_site — "Sổ tay PM" (a3s-pmm.robanme.com): site tĩnh build từ Markdown trong ./content.
#
# Stage 1 (node): npm ci + node site/build.mjs -> /build/dist
# Stage 2 (caddy): chỉ chứa HTML/CSS đã build + Caddyfile phục vụ tĩnh cổng 80.
# Caddy chính (docker/caddy/Caddyfile) reverse_proxy {$PM_DOMAIN} -> pm_site:80.

FROM node:20-alpine AS build
WORKDIR /build
COPY site/package.json site/package-lock.json ./site/
RUN cd site && npm ci --no-audit --no-fund
COPY site ./site
COPY content ./content
ARG GIT_COMMIT
RUN GIT_COMMIT="${GIT_COMMIT:-}" node site/build.mjs --content content --out dist

FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /build/dist /srv

# F-PR27-E01: image phải truy nguồn được về commit đã deploy, fail-closed như các Dockerfile khác
# trong repo (scripts/verify_image_provenance.sh kiểm nhãn org.opencontainers.image.revision).
ARG GIT_COMMIT
RUN set -eu; \
    if ! printf '%s' "${GIT_COMMIT:-}" | grep -Eq '^[0-9a-f]{40}$'; then \
      echo "STOP (F-PR27-E01): build-arg GIT_COMMIT thieu hoac khong phai commit SHA 40 hex." >&2; \
      echo "  nhan duoc: '${GIT_COMMIT:-<khong dat>}'" >&2; \
      exit 1; \
    fi
LABEL org.opencontainers.image.revision=$GIT_COMMIT
LABEL git_commit=$GIT_COMMIT

EXPOSE 80
