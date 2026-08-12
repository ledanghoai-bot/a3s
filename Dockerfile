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
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
