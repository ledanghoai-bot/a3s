# Migration pipeline — thiết kế, vận hành, rollback (F-PR24-01)

> Đáp `CA-Docs/PHASE1B-M4-F-PR24-01-MIGRATION-PIPELINE-PREPARATION-DIRECTIVE-VI.md`.
> Baseline: `fda233bed0aa1088fc6b27cb6d20300285fda5f0`.

## 1. Vấn đề

PR #24 merge và deploy **thành công**, CI xanh, nhưng migration `044` vẫn `PENDING` và hai bảng
H2-A không tồn tại trên production.

Nguyên nhân: `scripts/deploy.sh` chỉ `docker compose up -d --build` cho bảy service ứng dụng.
**Không có bước migration nào**, và `docker-compose.prod.yml` **không có** service `migrate` — dù
`docs/PHASE1B-IMPLEMENTATION-PLAN-VI.md` §192 đã mô tả *"one-shot service `migrate`: chờ DB healthy
→ xong trước api/worker"*. Service đó chưa từng tồn tại.

Ledger xác nhận migration luôn được áp **thủ công**, không trùng nhịp deploy:

```
043_m4_amendment08_correction   2026-08-12 06:50:56Z
042_m4_pin_token_approval_link  2026-08-06 13:25:10Z
041_m4_pin_bind_approval        2026-08-06 13:25:10Z   ← ba cái cùng một giây: dấu hiệu chạy tay
040_m4_pin_bootstrap            2026-08-06 13:25:10Z
```

**Hệ quả nguy hiểm:** một PR mang migration merge và deploy trót lọt trong khi schema vẫn cũ, và
**không có gì báo lệch**. Với 044 thì vô hại (thuần cộng thêm, chưa ai đọc). Với H2-A-2 — PR đầu
tiên có code thật sự phụ thuộc schema mới — nó sẽ thành lỗi production thật.

## 2. Thiết kế sau thay đổi

### 2.1. Luồng deploy

```
git reset --hard origin/main
        │
        ├─► db        khởi động, healthcheck TCP (§2.2)
        │        │
        │        └─► migrate   one-shot: `python scripts/migrate.py up`
        │                 │         exit 0 ──► api / worker / telegram_bot / telegram_customer_bot
        │                 │         exit ≠0 ─► KHÔNG service nào start; deploy.sh exit 1; CI đỏ
        └─► redis
```

Fail-closed ở **hai lớp độc lập**:

| Lớp | Cơ chế | Hỏng thì sao |
|---|---|---|
| Compose | `depends_on: migrate: condition: service_completed_successfully` | không service ứng dụng nào được start |
| CI/deploy | `deploy.sh` đọc exit code của `migrate`, `exit 1` nếu ≠ 0 | stage deploy đỏ, người vận hành thấy ngay |

Lớp thứ hai không thừa: nó biến một lỗi âm thầm thành một CI đỏ có log.

### 2.2. Healthcheck PHẢI qua TCP — kết luận từ thực nghiệm, không phải lý thuyết

Bản đầu Dev viết `pg_isready -U ... -d ...` (mặc định **unix socket**). Sandbox trên DB mới tinh
cho kết quả:

```
Container db-1 Healthy
Container migrate-1 Started
ConnectionRefusedError: [Errno 111] Connect call failed ('172.21.0.2', 5432)
```

Vì entrypoint Postgres chạy `initdb` rồi dựng một **server TẠM chỉ lắng nghe unix socket** để nạp
`/docker-entrypoint-initdb.d`; lúc đó `pg_isready` qua socket báo READY. Compose thấy "healthy" →
start `migrate` → Postgres tắt server tạm để khởi động thật → migrate kết nối vào đúng khoảng trống.

Server tạm **không** lắng nghe TCP, nên kiểm qua `-h 127.0.0.1 -p 5432` phân biệt được
"đang initdb" với "đã sẵn sàng nhận kết nối".

Lỗi này **chỉ lộ ra trên DB mới tinh**. Nếu chỉ thử trên DB có sẵn, nó sẽ ngủ yên đến lần đầu ai đó
dựng DB mới trên production — đúng lúc tệ nhất.

### 2.3. Idempotent + serialize: dùng lại cái đã có, không phát minh

`scripts/migrate.py` vốn đã có đủ:

- `pg_try_advisory_lock(4013001)` — **fail-fast**, không xếp hàng;
- ledger `schema_migrations` có `checksum`, phát hiện drift trên migration đã applied;
- post-migration validation theo manifest, fail-closed;
- exit code rõ ràng.

PR này **không sửa** `migrate.py`. Chỉ nối nó vào pipeline.

**Đánh đổi của fail-fast, nói rõ:** hai deploy chạy chồng nhau thì một cái **fail** thay vì chờ.
Đây là lựa chọn có sẵn từ M0 (xem docstring `migrate.py` §9). Với dự án một VPS, deploy tuần tự,
Dev giữ nguyên: một deploy đỏ rõ ràng tốt hơn hai runner cùng ghi.

## 3. Least privilege — nói thẳng: KHÔNG đạt tuyệt đối

Directive yêu cầu *"least privilege DB role cho migration"*. Dev **không** dán nhãn đó cho thứ chưa
đạt được.

Dữ kiện đo được:

| Migration | Số thao tác ROLE/GRANT/REVOKE |
|---|---|
| `024_runtime_db_role.sql` | 12 |
| `038_m4_slot_store.sql` | 4 |
| `039_m4_stage0p.sql` | **161** |

Ba file này chứa `CREATE ROLE` (`alpha3s_app`, `alpha3s_vendor_path`, `alpha3s_m4_definer`,
`alpha3s_m4_sample_collector`, `alpha3s_m4_sample_reviewer_api`…). Một role "tối thiểu" thật sự
**không chạy nổi chúng** — tối thiểu vẫn phải có `CREATEROLE` cộng quyền DDL trên schema.

Những gì PR này làm được, và đó là bước đi đúng hướng chứ không phải giải pháp cuối:

- Tách biến `MIGRATION_DATABASE_URL` riêng cho service `migrate` (mặc định về `DATABASE_URL` để
  không bắt người vận hành cấu hình thêm ngay). Quyền của migration từ nay **tường minh** và **thu
  hẹp được** mà không đụng vào DSN của ứng dụng.
- Ghi lại chính xác migration nào cần quyền gì (bảng trên), để lần siết quyền sau có dữ kiện.

**Đề xuất cho bước sau (ngoài PR này):** tạo `alpha3s_migrator` với `CREATEROLE` + `CREATE` trên
schema `public`, **không** superuser, rồi trỏ `MIGRATION_DATABASE_URL` vào đó. Việc này cần một
migration bootstrap + gate riêng, và phải kiểm lại toàn bộ 44 migration chạy được dưới role mới —
Dev không gộp vào đây để giữ PR nhỏ và rollback rõ.

## 4. Đường schema THỨ HAI — `initdb.d`

`db` mount `./migrations:/docker-entrypoint-initdb.d`. Postgres chạy thư mục này **chỉ khi data dir
còn rỗng** (lần `initdb` đầu tiên), và nó **không** ghi `schema_migrations`.

Hệ quả trên một DB mới tinh: DDL được nạp bởi initdb, nhưng ledger trống → `migrate` thấy toàn bộ
44 migration là pending → áp lại từ đầu. Phần lớn migration dùng `IF NOT EXISTS`/`CREATE OR REPLACE`
nên qua được, nhưng đây là hai nguồn sự thật cho cùng một schema.

Sandbox của PR này **không** mount `initdb.d`, nên kịch bản [1] đo đúng đường pipeline mới: ledger
trống → 44 migration áp theo thứ tự → 044 vào ledger.

Dev **không gỡ** mount đó trong PR này: nó có thể đang là cách bootstrap DB dev/test của người
khác, và gỡ nó là thay đổi hành vi ngoài phạm vi F-PR24-01. Ghi lại thành hạng mục cần quyết riêng.

## 5. Runbook vận hành

### 5.1. Deploy bình thường

Không cần thao tác tay. CI chạy `deploy.sh`; log deploy có khối:

```
=== ket qua migration (job one-shot 'migrate') ===
...
migrate exit code = 0
```

### 5.2. Migration thất bại

Triệu chứng: CI stage `deploy` đỏ; log có `LOI: migration KHONG thanh cong`; **không** service ứng
dụng nào được restart.

Trạng thái hệ thống: **ứng dụng cũ vẫn đang chạy trên schema cũ.** Đây là trạng thái an toàn — sự
cố *chưa* xảy ra với người dùng.

Xử lý:

1. Đọc log: `docker compose -f docker-compose.prod.yml logs migrate`.
2. Xem migration nào dừng: `docker compose -f docker-compose.prod.yml run --rm migrate python scripts/migrate.py status`.
3. **Không** sửa DB bằng tay để "cho qua". Sửa migration trong repo → PR mới → gate.
4. Nếu migration đã áp một phần: mỗi migration chạy trong **một transaction**
   (`transactional=True`), nên nó hoặc vào trọn hoặc không vào. Ledger không ghi migration lỗi —
   đã đo ở kịch bản [3].

### 5.3. Rollback

`migrate.py` **không** tự rollback schema, và PR này **không** thêm khả năng đó — đúng ràng buộc
directive (*"không tự chạy destructive migration hoặc tự rollback schema trong deploy path"*).

Rollback ứng dụng (`git revert` + deploy) **không** rollback schema. Vì vậy:

- Migration phải **cộng thêm** (additive) để bản cũ vẫn chạy được trên schema mới — như `044`.
- Migration destructive (DROP/RENAME cột đang dùng) cần **expand → migrate → contract** qua nhiều
  release, có gate riêng, không bao giờ đi kèm một PR tính năng.

### 5.4. Sự cố: hai deploy chạy chồng

Một cái sẽ đỏ với `STOP: mot process migration khac dang giu advisory lock (fail-fast)`. Không có
hỏng dữ liệu. Chạy lại deploy sau khi cái kia xong.

## 6. Giới hạn đã biết

| # | Giới hạn |
|---|---|
| G1 | Least privilege **chưa đạt** — xem §3. Migration vẫn dùng DSN quyền cao. |
| G2 | Đường `initdb.d` vẫn tồn tại song song ledger — §4. |
| G3 | Fail-fast lock: hai deploy chồng nhau thì một cái đỏ (chấp nhận có ý thức, §2.3). |
| G4 | Chưa đo trên production. Toàn bộ số liệu ở đây từ sandbox; áp lên production cần gate riêng. |
