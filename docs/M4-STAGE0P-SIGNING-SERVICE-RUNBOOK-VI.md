# M4 Stage 0P — Runbook vận hành Signing Service (A08-COR-01)

> Đáp `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-DIRECTIVE-VI.md` A08-COR-01, sửa lại
> theo `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-1-VI.md` F-A08-R1-01/02/03. Đọc
> cùng `docs/VPS-RUNBOOK-VI.md` (thao tác VPS chung) và `scripts/m4_stage0p_rehearsal_runner.py`
> docstring (toàn bộ chu kỳ ceremony PIN/approval). Tài liệu này CHỈ nói về signing service —
> tiến trình hệ điều hành riêng biệt giữ khóa ký/mã hóa, tách biệt hoàn toàn khỏi collector.

## 0. Vì sao cần tài liệu riêng — và vì sao topology đã đổi ở REV1

`app/services/pii/stage0p_signing_service.py` qua 14 vòng CA Technical Review (T10-T13) yêu cầu
chạy như **1 tiến trình hệ điều hành thật, dưới 1 UID khác với collector**. Production trước đây
cố ý để trống `M4_STAGE0P_SIGNING_SOCKET` — Amendment 08 (11/8) thất bại vì chưa từng có ai thực
sự khởi động service này.

**REV0** của correction này dùng 1 script Python (`m4_stage0p_signing_launcher.py`) tự spawn
process qua `asyncio` + tự `useradd` lúc container đang chạy. CA Review 1 (F-A08-R1-01) từ chối
hướng này: UID tạo lúc runtime là **mutable, ephemeral state** (mất khi container bị tạo lại),
không có supervisor/restart policy/log sink thật.

**REV1 (hiện tại)**: chuyển sang **docker-compose profile service** — `docker compose` chính là
supervisor (quản lý lifecycle/log/restart), UID `m4-signer`/`m4-collector` được tạo **lúc build
image** (Dockerfile, version-controlled, giống hệt trên mọi container tạo từ image), không còn
script Python tự spawn process nào cả — không còn cảnh báo GC, không còn pidfile tự viết tay.

## 1. Trình tự đầy đủ 1 ceremony (tóm tắt, chi tiết PIN/approval xem docstring runner)

```
record-approval (staff 3, PIN riêng)
  -> provision-keys (3 khóa mới, tự sinh ngẫu nhiên)
  -> docker compose --profile m4-signing up -d m4-signer   <-- bước MỚI (A08-COR-01)
  -> signing_probe.py (canary, xác nhận signing path THẬT hoạt động)  <-- bước MỚI (F-A08-R1-03)
  -> run --dry-run (xác nhận preflight)
  -> run (execute thật, chạy DƯỚI UID m4-collector)         <-- bước MỚI (A08-COR-01)
  -> docker compose --profile m4-signing stop m4-signer     <-- bước MỚI (A08-COR-01)
  -> retire-keys
  -> record-approval --revoke
```

## 2. Preflight bắt buộc trước khi start

```bash
docker compose -f docker-compose.prod.yml --profile m4-signing ps m4-signer
```

Xác nhận: không có container `m4-signer` nào đang `Up` (nếu có, `stop` trước — xem §5); deployed
HEAD đúng commit CA đã accept (`git rev-parse HEAD`); `m4_stage0p_transcript_signing_keys`/
`m4_stage0p_signing_auth_keys` không có active key cũ (nếu có, `retire-keys` trước).

## 3. Start — khởi động signing service qua docker compose

**Khóa PHẢI được export trong session shell hiện tại TRƯỚC khi gọi `up`** — `docker compose` đọc
`${VAR}` từ biến môi trường của chính shell đang gọi nó, KHÔNG cần và KHÔNG được ghi vào `.env`
hay bất kỳ file nào:

```bash
export M4_SAMPLE_KEY_B64="..."             # CÙNG giá trị đã đưa cho provision-keys
export M4_TRANSCRIPT_HMAC_KEY_B64="..."    # CÙNG giá trị đã đưa cho provision-keys
export M4_SIGNING_AUTH_VERIFY_KEY_B64="..." # CÙNG giá trị đã đưa cho provision-keys

docker compose -f docker-compose.prod.yml --profile m4-signing up -d m4-signer
```

Kiểm trạng thái (không secret nào hiện ra):

```bash
docker compose -f docker-compose.prod.yml --profile m4-signing ps m4-signer
docker compose -f docker-compose.prod.yml logs m4-signer --tail 20
```

`STATUS` nên là `Up (healthy)` sau vài giây (`healthcheck` chỉ kiểm socket file tồn tại đúng
mode — xem §4 để xác nhận sâu hơn signing path THẬT SỰ dùng được).

`m4-signer` chạy dưới UID cố định `5001` (group `5000`, cả hai bake sẵn trong image qua
`Dockerfile`) — không còn `useradd` lúc runtime nào cả.

## 4. Canary probe — xác nhận signing path THẬT hoạt động (F-A08-R1-03)

`healthcheck` của compose chỉ chứng minh **tiến trình đang lắng nghe** (socket file tồn tại đúng
mode) — KHÔNG chứng minh peer-UID/rate-limit/nonce/chữ ký/canonicalize/mã hóa/ký THẬT SỰ hoạt
động đúng. Chạy canary probe THẬT (dữ liệu hoàn toàn giả lập, không ghi DB, không chạm dữ liệu
rehearsal/khách hàng) từ ĐÚNG danh tính collector:

```bash
docker compose -f docker-compose.prod.yml exec --user m4-collector \
  -e M4_SIGNING_AUTH_VERIFY_KEY_B64 \
  api python scripts/m4_stage0p_signing_probe.py
```

**Lưu ý dạng `-e TEN_BIEN` (KHÔNG có `=gia_tri`, F-A08-R1-02)**: đây KHÔNG phải thiếu sót đánh
máy — dạng có `=` (`-e TEN="$TEN"`) khiến giá trị secret xuất hiện làm 1 token literal trong chính
argv của tiến trình `docker`/`docker compose` client trên host (ai có quyền `ps aux`/đọc
`/proc/<pid>/cmdline` trên host TRONG lúc lệnh đang chạy đều đọc được). Dạng bare `-e TEN` yêu cầu
Docker client tự đọc giá trị từ MÔI TRƯỜNG CỦA CHÍNH CLIENT (đã `export` ở §3) rồi chuyển qua
Docker API — secret không bao giờ là 1 token argv (đã kiểm chứng thực tế: `docker exec -e VAR
<container> printenv VAR` cho ra đúng giá trị dù `VAR` không hề có `=value` trên command line).

Output JSON `{"event": "m4_signing_probe_ok", "ok": true, ...}` xác nhận: peer UID `m4-collector`
được service chấp nhận, rate-limit/nonce/chữ ký `signing_authorization` (tự ký bằng CHÍNH khóa
`M4_SIGNING_AUTH_VERIFY_KEY_B64`, thuật toán import trực tiếp từ `stage0p_signing_service.py`,
không copy tay) đều hợp lệ, và service THẬT SỰ canonicalize + mã hóa + ký thành công. `ok: false`
→ xem §6 (rollback/xử lý sự cố), **không tiến hành ceremony**.

## 5. Execute — chạy rehearsal DƯỚI UID m4-collector

Ngoài `M4_SAMPLE_KEY_B64` (đã `export` ở §3), operator còn cần `export` riêng 2 PIN của chính
mình (`STAGE0P_REHEARSAL_OPERATOR_PIN`/`STAGE0P_REHEARSAL_REVIEWER_PIN` — của operator/reviewer
thật đang chạy ceremony, KHÔNG liên quan 3 khóa ký/mã hóa ở §3) TRƯỚC khi gọi `exec`:

```bash
export M4_STAGE0P_SIGNING_SOCKET=/run/m4-signing/signing.sock   # khong phai secret, nhung dat
                                                                  # qua bien de dong bo cach truyen
docker compose -f docker-compose.prod.yml exec --user m4-collector \
  -e STAGE0P_REHEARSAL_OPERATOR_PIN \
  -e STAGE0P_REHEARSAL_REVIEWER_PIN \
  -e M4_STAGE0P_SIGNING_SOCKET \
  -e M4_SAMPLE_KEY_B64 \
  api python scripts/m4_stage0p_rehearsal_runner.py run \
  --manifest datasets/pii/m4_stage0p_rehearsal_manifest_v2.jsonl \
  --approval-ref "<approval_ref>" \
  --operator-staff-id <N> --reviewer-staff-id <M>
```

Dạng bare `-e TEN` (không `=giá trị`) — xem giải thích §4, áp dụng CHO CẢ 3 secret ở đây
(`STAGE0P_REHEARSAL_OPERATOR_PIN`/`STAGE0P_REHEARSAL_REVIEWER_PIN`/`M4_SAMPLE_KEY_B64`): giá trị
không bao giờ là 1 token argv của tiến trình `docker compose` client trên host.

`api` service đã mount CHUNG volume `m4_signing_socket` với `m4-signer` (xem
`docker-compose.prod.yml`) nên socket path `/run/m4-signing/signing.sock` nhìn thấy được từ cả
hai. `M4_SAMPLE_KEY_B64` ở bước này KHÔNG phải bí mật của signing service — đây LÀ secret nhạy
cảm thật (khóa giải mã sample), nhưng cần thiết để prediction writer (chạy trong tiến trình
runner, không phải signing service) tự giải mã sample AEAD đối xứng khi chạy detector (thiết kế
có từ trước A08-COR-01).

**Nếu quên `--user m4-collector`**: signing service từ chối kết nối NGAY (peer UID không khớp,
T11-02/T12-01) — fail-closed đúng thiết kế, không leak gì, rehearsal thất bại sạch.

## 6. Stop — dừng signing service (sau khi rehearsal xong, dù thành công hay thất bại)

```bash
docker compose -f docker-compose.prod.yml --profile m4-signing stop m4-signer
docker compose -f docker-compose.prod.yml --profile m4-signing rm -f m4-signer
```

`stop` gửi SIGTERM (graceful); container không tự khởi động lại (`restart: "no"` chủ ý — xem
comment trong `docker-compose.prod.yml`). `rm -f` dọn hẳn container đã dừng (không bắt buộc nhưng
khuyến nghị, tránh nhầm lẫn ở lần `ps` sau).

## 7. Key lifecycle — tóm tắt vòng đời 3 khóa

| Khóa | Sinh ở đâu | Sống ở đâu | Retire khi nào |
|---|---|---|---|
| `M4_SAMPLE_KEY_B64` | Operator tự `openssl rand -base64 32` trước `provision-keys` | Biến môi trường shell của operator trong suốt ceremony (đưa cho `provision-keys`, `m4-signer` service, và `run`/prediction writer) — KHÔNG bảng DB nào lưu | Không cần "retire" DB — chỉ ngừng dùng lại giá trị sau `stop` |
| `M4_TRANSCRIPT_HMAC_KEY_B64` | Cùng lúc | `m4_stage0p_transcript_signing_keys` (DB) + môi trường container `m4-signer` | `retire-keys` (DB) SAU KHI `stop` |
| `M4_SIGNING_AUTH_VERIFY_KEY_B64` | Cùng lúc | `m4_stage0p_signing_auth_keys` (DB) + môi trường container `m4-signer` (+ operator tự giữ để chạy canary probe §4) | `retire-keys` (DB) SAU KHI `stop` |

**3 khóa CHỈ tồn tại trong biến môi trường shell của operator** trong suốt ceremony — không bao
giờ ghi vào file, `.env`, log hay evidence. `docker compose up`/`exec -e <TEN>` (dạng bare, không
`=giá trị` — xem §4/§5) đọc trực tiếp từ shell environment của operator, không cần và không tạo
file trung gian nào, và (khác REV0 của tài liệu này) không còn để giá trị lọt vào argv của tiến
trình `docker`/`docker compose` client trên host nữa.

**Giới hạn cố hữu còn lại (F-A08-R1-02), không che giấu — 2 kênh KHÁC NHAU, không nhầm lẫn**:

1. **`m4-signer` container's OWN environment** (`M4_SAMPLE_KEY_B64`/`M4_TRANSCRIPT_HMAC_KEY_B64`/
   `M4_SIGNING_AUTH_VERIFY_KEY_B64` khai báo qua `environment:` trong `docker-compose.prod.yml`,
   đọc `${VAR}` lúc `up`) THẬT SỰ được Docker bake vào `Config.Env` của container lúc tạo, và
   `docker inspect m4-signer` hiện được dạng plaintext cho bất kỳ ai có quyền Docker API/root trên
   host — đây là giới hạn cố hữu của CHÍNH CƠ CHẾ biến môi trường container Docker (không riêng gì
   thiết kế này, áp dụng cho MỌI service dùng `environment:` với secret), không phải lỗ hổng do
   runbook này tạo ra.
2. **Secret truyền lúc `exec`** (3 giá trị ở §4/§5: `M4_SIGNING_AUTH_VERIFY_KEY_B64` cho probe,
   `STAGE0P_REHEARSAL_OPERATOR_PIN`/`STAGE0P_REHEARSAL_REVIEWER_PIN`/`M4_SAMPLE_KEY_B64` cho
   execute) KHÔNG thuộc `Config.Env` của container (`docker exec -e` là override tạm thời cho
   riêng tiến trình exec, không persist) nên `docker inspect` KHÔNG hiện được các giá trị này —
   dạng bare `-e TEN` (đã áp dụng ở §4/§5) đóng luôn kênh rò rỉ còn lại (argv của tiến trình
   client trên host).

Cả 2 trường hợp: ai có quyền Docker API/root trên host vốn đã có quyền đọc `.env`/kết nối DB trực
tiếp — không mở rộng bề mặt tấn công so với mức truy cập đã có sẵn.

## 8. Rollback / xử lý sự cố

| Tình huống | Xử lý |
|---|---|
| `up -d m4-signer` báo thiếu biến môi trường (`Phai dat M4_...`) | Chưa `export` đủ 3 khóa trong shell hiện tại — export rồi thử lại |
| `ps m4-signer` báo `Exited`/`unhealthy` | `docker compose logs m4-signer --tail 50` đọc lý do THẬT (vd `_validate_socket_directory` từ chối) — KHÔNG retry mù quáng |
| `signing_probe.py` báo `ok: false` | Kiểm `docker compose ps m4-signer` còn `Up` không; xác nhận `M4_SIGNING_AUTH_VERIFY_KEY_B64` truyền cho probe ĐÚNG bằng giá trị đã đưa cho `up -d m4-signer` (khác khóa = chữ ký không khớp, an toàn nhưng vô dụng) |
| Execute báo `SigningServiceError: khong ket noi duoc signing service` | `ps m4-signer` xác nhận còn `Up`; xác nhận `--user m4-collector` và `M4_STAGE0P_SIGNING_SOCKET` truyền đúng cho lệnh `exec` |
| Execute báo "chua co signing_auth_key hieu luc" | Khóa `provision-keys` (DB) và khóa đưa cho `up -d m4-signer` KHÔNG khớp (vd `retire-keys` chạy giữa chừng) — `stop`, `retire-keys`, sinh khóa MỚI, làm lại từ `provision-keys` |
| Cần dừng khẩn cấp | `docker compose --profile m4-signing stop m4-signer` (SIGTERM, Docker tự SIGKILL sau timeout mặc định nếu cần) — an toàn gọi bất kỳ lúc nào |
| `m4-signer` crash giữa lúc đang chạy rehearsal | **KHÔNG tự phục hồi** (`restart: "no"` chủ ý) — collector sẽ tự fail-closed sau vài lần retry (xem `COLLECTOR_MAX_ATTEMPTS`/`_run_collector_with_retry` trong runner), runner tự cleanup + terminalize batch `'aborted'`. Xem log `m4-signer` (nếu container còn giữ lại, `docker compose logs`) để tìm nguyên nhân crash trước khi thử ceremony mới — không `up -d` lại giữa chừng 1 gate đang mở |

## 9. Evidence commands (không lộ secret)

```bash
docker compose -f docker-compose.prod.yml --profile m4-signing ps m4-signer
docker compose -f docker-compose.prod.yml logs m4-signer --tail 50
docker compose -f docker-compose.prod.yml exec api printenv | grep -iE "M4_SAMPLE_KEY|TRANSCRIPT_HMAC_KEY|SIGNING_AUTH_VERIFY_KEY"  # PHAI rong trong container api - key CHI trong tien trinh m4-signer
```

Dòng cuối là bằng chứng độc lập quan trọng: chạy trong `api` (nơi collector/runner sống), 3 biến
khóa PHẢI **không xuất hiện** — nếu có, dừng ngay và báo CA.
