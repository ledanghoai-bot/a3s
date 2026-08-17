FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir asyncpg
# COPY ca thu muc scripts/ — image production dung `COPY . .` nen co day du; ban sandbox truoc do
# chi copy migrate.py + manifest, thieu operational_seed_validation.sql => `up` exit 1 vi
# post-migration validation khong tim thay file. Do la loi cua SANDBOX, khong phai cua pipeline.
COPY scripts/ scripts/
COPY migrations/ migrations/
