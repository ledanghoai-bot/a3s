FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .
RUN npm run build

# F-PR27-E01: image dashboard cung phai truy nguon duoc ve commit da deploy, cung quy tac
# fail-closed nhu Dockerfile goc. Dat CUOI file vi cung ly do cache (ARG invalidate moi layer
# sau no, khong duoc de npm install/build build lai moi lan doi commit).
ARG GIT_COMMIT
RUN set -eu; \
    if ! printf '%s' "${GIT_COMMIT:-}" | grep -Eq '^[0-9a-f]{40}$'; then \
      echo "STOP (F-PR27-E01): build-arg GIT_COMMIT thieu hoac khong phai commit SHA 40 hex." >&2; \
      echo "  nhan duoc: '${GIT_COMMIT:-<khong dat>}'" >&2; \
      exit 1; \
    fi
LABEL org.opencontainers.image.revision=$GIT_COMMIT
LABEL git_commit=$GIT_COMMIT

EXPOSE 3000
CMD ["npm", "start"]
