# VPS RUNBOOK — Hướng dẫn vận hành Alpha3S cho staff

> Tài liệu **cầm tay chỉ việc** để nhân viên kỹ thuật tự vận hành server production
> mà **không cần AI hỗ trợ**. Mỗi mục có lệnh copy-paste được + giải thích lệnh làm gì.
> Đọc kèm `docs/DEPLOYMENT-VI.md` (bản tóm tắt kỹ thuật) và `ISSUES-VI.md` (#9).
> English version: `docs/VPS-RUNBOOK-EN.md`.
>
> **Quy ước:** dòng bắt đầu bằng `$` là lệnh chạy trên **máy của bạn**; dòng bắt đầu bằng
> `root@vps:#` là lệnh chạy **trên VPS** (sau khi đã SSH vào). Không gõ ký tự `$`/`#`.

---

## 0. Bạn cần gì trước khi bắt đầu

| Thứ cần | Lấy ở đâu |
|---|---|
| **SSH key** vào VPS (`alpha3s_vps`) | File private key do người bàn giao đưa. VPS **đã tắt đăng nhập bằng mật khẩu** — không có key thì không vào được (trừ console trong panel nhà cung cấp). |
| **Quyền GitHub** repo `ledanghoai-bot/a3s` | Chủ repo mời bạn làm collaborator. Cần để push code (kích hoạt auto-deploy). |
| **Panel nhà cung cấp VPS** (AZ VPS) | Tài khoản quản trị — dùng khi mất SSH (console) hoặc reboot cứng. |
| **Panel DNS PA Vietnam** (domain `robanme.com`) | Chỉ cần khi đổi/thêm domain. |
| **Meta App dashboard** (Messenger) | Chỉ cần khi cấu hình webhook. |

Thông tin cố định:

| | |
|---|---|
| VPS IP | `160.30.157.235` |
| Hệ điều hành | Ubuntu 24.04 |
| Thư mục deploy | `/srv/alpha3s` |
| Domain API/webhook | `https://a3s.robanme.com` |
| Domain dashboard | `https://a3s-dash.robanme.com` |
| Repo | `github.com/ledanghoai-bot/a3s` (nhánh `main`) |

---

## 1. Kết nối vào VPS (SSH)

### Lần đầu: cài "lối tắt" cho tiện

**Trên Windows** (PowerShell hoặc Git Bash) hoặc **Mac/Linux** (Terminal), mở file
`~/.ssh/config` (Windows: `C:\Users\<tên bạn>\.ssh\config`) và thêm:

```
Host alpha3s-vps
  HostName 160.30.157.235
  User root
  IdentityFile ~/.ssh/alpha3s_vps
  ServerAliveInterval 30
```

Đặt file private key vào `~/.ssh/alpha3s_vps`. Trên Mac/Linux chỉnh quyền:

```
$ chmod 600 ~/.ssh/alpha3s_vps
```

### Vào VPS

```
$ ssh alpha3s-vps
```

Vào được sẽ thấy dấu nhắc `root@azvps-1784814855:~#`. Muốn thoát: gõ `exit`.

> Nếu báo `Permission denied (publickey)`: bạn chưa có đúng key, hoặc key chưa được cấp
> quyền trên VPS. Liên hệ người bàn giao — **đừng cố đăng nhập bằng mật khẩu, VPS đã tắt.**

Hầu hết lệnh vận hành đều chạy trong thư mục deploy, nên vào là `cd` luôn:

```
root@vps:# cd /srv/alpha3s
```

---

## 2. Bản đồ hệ thống (cái gì chạy ở đâu)

Toàn bộ chạy bằng **Docker Compose**, file `docker-compose.prod.yml`. Các "container":

| Container | Vai trò | Cổng |
|---|---|---|
| `caddy` | Cổng vào duy nhất từ Internet, tự lo HTTPS | 80, 443 (công khai) |
| `api` | Backend FastAPI (webhook + API cho dashboard) | 8000 (chỉ nội bộ) |
| `worker` | Xử lý tin nhắn nền (hàng đợi) | — |
| `dashboard` | Giao diện quản trị (Next.js) | 3000 (chỉ nội bộ) |
| `db` | PostgreSQL (pgvector) — dữ liệu | 5432 (chỉ nội bộ) |
| `redis` | Hàng đợi + cache | 6379 (chỉ nội bộ) |
| `telegram_bot` | Bot Telegram admin | **hiện TẮT** (xem §9) |
| `telegram_customer_bot` | Bot Telegram khách | **hiện TẮT** (xem §9) |

Luồng: **Internet → Caddy (HTTPS) → api/dashboard**. `db`/`redis` không mở ra ngoài, chỉ
các container nói chuyện với nhau. Tường lửa (`ufw`) chỉ mở cổng 22 (SSH), 80, 443.

---

## 3. Vận hành hằng ngày

> Luôn `cd /srv/alpha3s` trước. Mọi lệnh docker đều có `-f docker-compose.prod.yml`.

### 3.1. Xem trạng thái các container

```
root@vps:# docker compose -f docker-compose.prod.yml ps
```

Cột `STATUS` nên là `Up ...`. Nếu thấy `Exited` hoặc `Restarting` liên tục → có sự cố (xem §10).

### 3.2. Xem log

```
# 50 dòng cuối của api
root@vps:# docker compose -f docker-compose.prod.yml logs api --tail 50

# Theo dõi log trực tiếp (Ctrl+C để thoát)
root@vps:# docker compose -f docker-compose.prod.yml logs -f api

# Log của tất cả service
root@vps:# docker compose -f docker-compose.prod.yml logs --tail 30
```

Đổi `api` thành `worker`, `dashboard`, `db`, `caddy`... để xem service khác.

### 3.3. Khởi động lại 1 service

```
root@vps:# docker compose -f docker-compose.prod.yml restart api
```

### 3.4. Khởi động lại toàn bộ / bật lại sau khi tắt

```
root@vps:# docker compose -f docker-compose.prod.yml up -d
```

`up -d` chỉ tạo/khởi động cái nào chưa chạy, không đụng cái đang chạy.

### 3.5. Kiểm tra nhanh hệ thống còn "sống"

```
root@vps:# curl -s -o /dev/null -w "api: %{http_code}\n" http://localhost:8000/health
```

Từ máy bạn (kiểm tra HTTPS ngoài Internet):

```
$ curl -s -o /dev/null -w "%{http_code}\n" https://a3s.robanme.com/health
```

Cả hai nên trả `200`.

---

## 4. Triển khai thay đổi code (deploy)

### 4.1. Cách CHUẨN — tự động qua GitHub (khuyến nghị)

Chỉ cần **push code lên nhánh `main`** trên GitHub. GitHub Actions sẽ tự:
1. Chạy kiểm tra (`ruff` + test).
2. Nếu qua hết → SSH vào VPS, kéo code mới, build lại, khởi động lại.

Từ máy bạn (trong thư mục repo trên máy):

```
$ git add -A
$ git commit -m "mo ta ngan gon 1 dong"
$ git push origin main
```

> ⚠️ **Commit message LUÔN 1 dòng** trên Windows (lịch sử dự án từng bị lỗi tạo file rác
> khi message nhiều dòng). Cần nhiều dòng thì dùng nhiều cờ `-m`: `git commit -m "dòng 1" -m "dòng 2"`.

Theo dõi tiến trình deploy tại: **GitHub → repo → tab Actions**. Xanh (✓) là xong,
đỏ (✗) là hỏng — bấm vào xem bước nào lỗi.

### 4.2. Cách TAY — khi cần gấp hoặc CI đang hỏng

SSH vào VPS rồi:

```
root@vps:# cd /srv/alpha3s
root@vps:# git fetch origin main
root@vps:# git reset --hard origin/main
root@vps:# bash scripts/deploy.sh
```

`scripts/deploy.sh` sẽ build lại và khởi động các service, rồi dọn image cũ. Cuối lệnh
nó in trạng thái container để bạn kiểm tra.

> **Lưu ý:** file `scripts/deploy.sh` có biến `SERVICES` liệt kê service được deploy.
> Hiện là `db redis api worker dashboard` (chưa gồm 2 bot Telegram — xem §9 Cutover).

---

## 5. Cập nhật Knowledge Base (KB V2)

Khi nội dung tri thức (thư mục `knowledge-base/`) thay đổi và đã push lên VPS:

```
root@vps:# cd /srv/alpha3s
root@vps:# docker compose -f docker-compose.prod.yml exec -T api python scripts/kb_ingest.py
```

Lệnh in ra số "Knowledge Unit" đã nạp và **KHÔNG tự kích hoạt** (an toàn). Nó in ra 1 câu
SQL để kích hoạt phiên bản index mới — kiểm tra kết quả ở trên rồi chạy câu đó, ví dụ:

```
root@vps:# docker compose -f docker-compose.prod.yml exec -T db psql -U alpha3s -d alpha3s -c \
  "INSERT INTO kb_config (key, value) VALUES ('active_index_version', '2') \
   ON CONFLICT (key) DO UPDATE SET value = '2';"
```

(Thay `'2'` bằng đúng số `index_version` mà script vừa in ra.)

Kiểm tra số unit hiện có:

```
root@vps:# docker compose -f docker-compose.prod.yml exec -T db psql -U alpha3s -d alpha3s -c \
  "SELECT count(*) FROM kb_units; SELECT * FROM kb_config;"
```

---

## 6. Backup & Restore dữ liệu (QUAN TRỌNG)

### 6.1. Backup — đã tự động

Cron chạy `pg_dump` mỗi ngày **03:00 giờ VN**, giữ **14 bản gần nhất** tại `/root/backups/`.

```
# Xem các bản backup
root@vps:# ls -lh /root/backups/

# Xem log backup (OK/FAIL từng ngày)
root@vps:# cat /root/backups/backup.log
```

Chạy backup thủ công ngay lập tức (ví dụ trước khi làm việc nguy hiểm):

```
root@vps:# /root/bin/backup_db.sh && tail -1 /root/backups/backup.log
```

### 6.2. Restore — phục hồi từ 1 bản backup

> ⚠️ **Restore GHI ĐÈ toàn bộ dữ liệu hiện tại.** Chỉ làm khi chắc chắn. Nên chạy backup
> thủ công (6.1) ngay trước, phòng khi cần quay lại.

```
root@vps:# cd /srv/alpha3s

# 1) Tắt các service dùng DB (giữ db + redis chạy)
root@vps:# docker compose -f docker-compose.prod.yml stop api worker telegram_bot telegram_customer_bot

# 2) Xoá và tạo lại database rỗng
root@vps:# docker compose -f docker-compose.prod.yml exec -T db \
  psql -U alpha3s -d postgres -c "DROP DATABASE alpha3s WITH (FORCE); CREATE DATABASE alpha3s OWNER alpha3s;"

# 3) Nạp dữ liệu từ bản backup (thay tên file cho đúng)
root@vps:# gunzip -c /root/backups/alpha3s_2026-07-23_0300.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T db psql -U alpha3s -d alpha3s

# 4) Bật lại service
root@vps:# docker compose -f docker-compose.prod.yml start api worker
```

Kiểm tra lại dữ liệu (ví dụ số sản phẩm, số đơn):

```
root@vps:# docker compose -f docker-compose.prod.yml exec -T db psql -U alpha3s -d alpha3s -c \
  "SELECT count(*) FROM products; SELECT count(*) FROM orders;"
```

---

## 7. File cấu hình bí mật `.env`

Nằm tại `/srv/alpha3s/.env` trên VPS (quyền `600`, **KHÔNG bao giờ commit lên git**).
Chứa: token Meta/Telegram, key LLM, mật khẩu DB, domain...

```
# Xem các biến (cẩn thận, có secret — đừng chụp màn hình gửi đi)
root@vps:# grep -E "^[A-Z]" /srv/alpha3s/.env | cut -d= -f1
```

Sửa 1 biến (ví dụ đổi domain), dùng trình soạn `nano`:

```
root@vps:# nano /srv/alpha3s/.env
# Sửa xong: Ctrl+O (lưu), Enter, Ctrl+X (thoát)
```

**Sau khi đổi `.env` phải tạo lại container** để nạp giá trị mới:

```
root@vps:# cd /srv/alpha3s
root@vps:# docker compose -f docker-compose.prod.yml up -d
```

> Biến bắt đầu bằng `NEXT_PUBLIC_` (dashboard) được "nướng" vào lúc build — đổi xong phải
> `up -d dashboard` để nó build lại.

---

## 8. Domain & HTTPS (Caddy)

HTTPS **tự động** — Caddy tự xin và gia hạn chứng chỉ Let's Encrypt, không cần làm gì thủ công.

### Thêm / đổi domain

1. **Tạo bản ghi DNS** tại panel PA Vietnam (domain `robanme.com`):
   - Vào đúng mục **"Quản lý bản ghi" / danh sách Host–Loại–Giá trị–TTL**
     (KHÔNG phải mục "Tạo DNS con phụ" — mục đó không ghi vào zone thật).
   - Thêm bản ghi: **Host** = tên con (vd `a3s`), **Loại** = `A`, **Giá trị** = `160.30.157.235`, TTL `3600`. Lưu.
2. **Chờ DNS trỏ đúng** rồi kiểm tra (từ máy bạn hoặc VPS):
   ```
   root@vps:# dig +short a3s.robanme.com @1.1.1.1
   ```
   Phải trả `160.30.157.235`.
3. **Khai báo domain trong `.env`** (`DOMAIN` cho API/webhook, `DASH_DOMAIN` cho dashboard),
   rồi `up -d caddy`. Caddy tự lấy chứng chỉ trong ~30 giây. Xem log nếu cần:
   ```
   root@vps:# docker compose -f docker-compose.prod.yml logs caddy --tail 20
   ```

---

## 9. Cutover: chuyển kênh khách sang VPS (⚠️ đụng khách thật)

Hiện **máy local vẫn là nơi phục vụ khách thật** (webhook Messenger + 2 bot Telegram).
VPS chạy song song nhưng 2 bot Telegram **đang TẮT** để không tranh token với máy local
(2 nơi cùng chạy sẽ lỗi `409 Conflict`). Khi muốn chuyển hẳn sang VPS:

1. **Bật 2 bot Telegram trong deploy:** sửa `scripts/deploy.sh`, thêm
   `telegram_bot telegram_customer_bot` vào biến `SERVICES`, rồi commit + push (hoặc deploy tay).
2. **TẮT 2 bot Telegram ở máy local TRƯỚC** (nếu không sẽ 409 tranh `getUpdates`).
3. **Trỏ webhook Messenger sang VPS** (Meta App dashboard):
   - Callback URL: `https://a3s.robanme.com/webhook`
   - Verify Token: đúng giá trị `META_VERIFY_TOKEN` trong `.env` của VPS.
   - Meta gọi thử `GET /webhook` để xác thực — nếu token khớp sẽ báo thành công.
4. **Kiểm tra VPS nhận tin:** nhắn thử vào page, xem log:
   ```
   root@vps:# docker compose -f docker-compose.prod.yml logs -f api
   ```
   Thấy request `POST /webhook` là đã thông.
5. Theo dõi trong vài giờ đầu (log + alert Telegram). Muốn quay lại máy local: trỏ webhook
   về URL cũ + tắt bot trên VPS + bật lại ở local.

---

## 10. Xử lý sự cố thường gặp

| Triệu chứng | Cách xử lý |
|---|---|
| 1 container `Exited`/`Restarting` liên tục | Xem log của nó (`logs <tên> --tail 100`). Sửa xong: `up -d <tên>`. |
| Web trả `502 Bad Gateway` | Service phía sau (api/dashboard) đang khởi động hoặc chết. Chờ ~1 phút; nếu vẫn: `restart api` / `restart dashboard`, xem log. |
| Không vào được HTTPS, chứng chỉ lỗi | Xem `logs caddy`. Thường do DNS chưa trỏ đúng IP hoặc cổng 80 bị chặn. Kiểm tra `dig` (§8) và `ufw status`. |
| Webhook Messenger không nhận tin | Kiểm tra webhook URL/verify token bên Meta; xem `logs -f api` có `POST /webhook` không; kiểm tra `META_APP_SECRET` đúng (sai chữ ký → 403). |
| Bot Telegram lỗi `409 Conflict` | Đang chạy 2 nơi cùng lúc (local + VPS). Tắt 1 nơi. |
| Bot chậm/không trả lời, nghi tin bị kẹt | Xem hàng đợi lỗi: `docker compose -f docker-compose.prod.yml exec -T redis redis-cli LLEN dead_letter:messages`. >0 là có tin xử lý thất bại. |
| Hết dung lượng đĩa | `df -h /`. Dọn image cũ: `docker image prune -f`. Dọn log: `docker system df` để xem chỗ tốn. |
| VPS lag/hết RAM | `free -h` và `docker stats --no-stream`. Có swap 2G sẵn. |
| Lỡ tay/sự cố dữ liệu | Restore từ backup (§6.2). |

Kiểm tra tài nguyên nhanh:

```
root@vps:# free -h ; df -h / ; docker stats --no-stream --format "{{.Name}}: {{.MemUsage}}"
```

Cảnh báo tự động: hệ thống có cron 5 phút kiểm tra hàng đợi lỗi / container chết / đĩa >85%
và gửi Telegram vào group **"Alpha3s admin"** (script `/root/bin/alert_check.sh`).

---

## 11. Rollback khẩn cấp (quay về phiên bản trước)

Nếu bản deploy mới lỗi và cần quay lại ngay:

```
root@vps:# cd /srv/alpha3s

# Xem lịch sử commit
root@vps:# git log --oneline -5

# Quay về commit trước đó (thay <SHA> bằng mã commit tốt gần nhất)
root@vps:# git reset --hard <SHA>
root@vps:# bash scripts/deploy.sh
```

Sau khi ổn định, nhớ sửa lỗi trên nhánh `main` ở GitHub rồi deploy lại như bình thường
(lần push kế tiếp sẽ ghi đè trạng thái này).

---

## 12. Bảo mật & quy ước bắt buộc

- **KHÔNG commit `.env`** hay bất kỳ secret nào lên git.
- **KHÔNG bật lại đăng nhập SSH bằng mật khẩu.** Chỉ dùng key. Giữ file key cẩn thận, mất
  key thì dùng console trong panel nhà cung cấp.
- **Commit message 1 dòng** (bài học file rác của dự án — xem `CLAUDE.md`).
- Không mở thêm cổng tường lửa trừ khi thật cần (`ufw`). Hiện chỉ 22/80/443.
- Đổi `.env` xong luôn `up -d` để có hiệu lực; thay đổi code luôn qua git → CI deploy.
- Trước khi làm việc nguy hiểm với DB, **chạy backup thủ công trước** (§6.1).

---

## 13. Tra cứu nhanh

| Việc | Lệnh (đã `cd /srv/alpha3s`) |
|---|---|
| Trạng thái | `docker compose -f docker-compose.prod.yml ps` |
| Log 1 service | `docker compose -f docker-compose.prod.yml logs -f api` |
| Restart 1 service | `docker compose -f docker-compose.prod.yml restart api` |
| Bật lại tất cả | `docker compose -f docker-compose.prod.yml up -d` |
| Deploy tay | `git fetch origin main && git reset --hard origin/main && bash scripts/deploy.sh` |
| Backup ngay | `/root/bin/backup_db.sh` |
| Vào DB (psql) | `docker compose -f docker-compose.prod.yml exec db psql -U alpha3s -d alpha3s` |
| Health API | `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/health` |

- Dashboard: https://a3s-dash.robanme.com
- API/health: https://a3s.robanme.com/health
- Repo: https://github.com/ledanghoai-bot/a3s (Actions = trạng thái deploy)
