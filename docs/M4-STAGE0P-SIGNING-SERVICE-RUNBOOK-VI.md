# M4 Stage 0P — Runbook vận hành Signing Service (A08-COR-01)

> Đáp `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-DIRECTIVE-VI.md` A08-COR-01. Đọc cùng
> `docs/VPS-RUNBOOK-VI.md` (thao tác VPS chung) và `scripts/m4_stage0p_rehearsal_runner.py`
> docstring (toàn bộ chu kỳ ceremony PIN/approval). Tài liệu này CHỈ nói về signing service —
> tiến trình hệ điều hành riêng biệt giữ khóa ký/mã hóa, tách biệt hoàn toàn khỏi collector.

## 0. Vì sao cần tài liệu riêng

`app/services/pii/stage0p_signing_service.py` qua 14 vòng CA Technical Review (T10-T13) yêu cầu
chạy như **1 tiến trình hệ điều hành thật, dưới 1 UID khác với collector**, đọc khóa ký CHỈ từ
môi trường của chính nó. Production trước đây **cố ý để trống** `M4_STAGE0P_SIGNING_SOCKET` —
đây là lớp phòng thủ độc lập (nếu `capture_enabled` lỡ bật, bước ký vẫn fail-closed vì không có
service sống). Amendment 08 (11/8) là lần đầu thử execute thật — thất bại vì **chưa từng có ai
thực sự khởi động service này trên production** (F-A08-EXEC-01).

`scripts/m4_stage0p_signing_launcher.py` (mới, A08-COR-01) là công cụ vận hành **tường minh, đã
qua review**, để khởi động/dừng service đó một cách an toàn — tái sử dụng nguyên vẹn logic đã qua
14 vòng CA review trong `scripts/_stage0p_signing_service_helper.py` (không viết lại). Chỉ dùng
khi (và chỉ khi) 1 ceremony rehearsal thật cần chạy — **không có trong `docker-compose.prod.yml`
hay `deploy.sh`**, dormant deploy không tự khởi động nó.

## 1. Trình tự đầy đủ 1 ceremony (tóm tắt, chi tiết PIN/approval xem docstring runner)

```
record-approval (staff 3, PIN riêng)
  -> provision-keys (3 khóa mới, tự sinh ngẫu nhiên)
  -> signing_launcher.py start (CÙNG 3 khóa)          <-- bước MỚI (A08-COR-01)
  -> run --dry-run (xác nhận preflight)
  -> run (execute thật, chạy DƯỚI UID m4-collector)   <-- bước MỚI (A08-COR-01)
  -> signing_launcher.py stop                          <-- bước MỚI (A08-COR-01)
  -> retire-keys
  -> record-approval --revoke
```

## 2. Preflight bắt buộc trước khi start

- Xác nhận deployed HEAD đúng commit đã CA accept (`git rev-parse HEAD`).
- Xác nhận `signing_launcher.py status` báo `running: false` (không có service cũ sót lại).
- Xác nhận `m4_stage0p_transcript_signing_keys`/`m4_stage0p_signing_auth_keys` không có active key
  cũ (nếu có, `retire-keys` trước).

```bash
docker exec alpha3s-api-1 python scripts/m4_stage0p_signing_launcher.py status
```

## 3. Start — khởi động signing service

**Dùng CHÍNH XÁC 3 khóa vừa đưa cho `provision-keys`** (khác khóa = service ký nhưng DB xác thực
`signing_authorization` sẽ luôn từ chối — an toàn nhưng vô dụng, không phải lỗ hổng).

```bash
docker exec \
  -e M4_SAMPLE_KEY_B64="$M4_SAMPLE_KEY_B64" \
  -e M4_TRANSCRIPT_HMAC_KEY_B64="$M4_TRANSCRIPT_HMAC_KEY_B64" \
  -e M4_SIGNING_AUTH_VERIFY_KEY_B64="$M4_SIGNING_AUTH_VERIFY_KEY_B64" \
  alpha3s-api-1 python scripts/m4_stage0p_signing_launcher.py start
```

Output JSON xác nhận (không có secret nào): `pid`, `signer_uid`, `collector_uid`, `shared_gid`,
`socket_path`. Lần đầu chạy sẽ tự tạo (idempotent, `useradd`/`groupadd`) 2 tài khoản hệ thống
`m4-signer`/`m4-collector` + 1 group chia sẻ `m4-signing-ipc`.

> Lưu ý: có thể thấy 1 dòng `Exception ignored in: ... RuntimeError: Event loop is closed` sau
> dòng JSON — đây là cảnh báo vô hại của Python asyncio khi dọn dẹp transport SAU khi tiến trình
> đã detach thành công (đã kiểm chứng: không ảnh hưởng exit code, không giết tiến trình con, tiến
> trình signing service vẫn chạy). Không phải lỗi cần xử lý.

## 4. Execute — chạy rehearsal DƯỚI UID m4-collector

Đây là điểm khác biệt quan trọng nhất so với trước Amendment 08: lệnh `run` (execute thật) giờ
PHẢI chạy dưới UID `m4-collector` (không phải root mặc định của `docker exec`) để signing service
thực sự phân biệt được 2 UID khác nhau (T12-01) — và PHẢI trỏ đúng socket path:

```bash
docker exec --user m4-collector \
  -e STAGE0P_REHEARSAL_OPERATOR_PIN="$STAGE0P_REHEARSAL_OPERATOR_PIN" \
  -e STAGE0P_REHEARSAL_REVIEWER_PIN="$STAGE0P_REHEARSAL_REVIEWER_PIN" \
  -e M4_STAGE0P_SIGNING_SOCKET=/run/m4-signing/signing.sock \
  -e M4_SAMPLE_KEY_B64="$M4_SAMPLE_KEY_B64" \
  alpha3s-api-1 python scripts/m4_stage0p_rehearsal_runner.py run \
  --manifest datasets/pii/m4_stage0p_rehearsal_manifest_v2.jsonl \
  --approval-ref "<approval_ref>" \
  --operator-staff-id <N> --reviewer-staff-id <M>
```

`M4_SAMPLE_KEY_B64` ở bước này KHÔNG phải bí mật của signing service (đã đưa cho `provision-keys`
ở bước trước) — prediction writer (chạy trong tiến trình runner, không phải signing service) cần
giá trị này để tự giải mã sample AEAD đối xứng khi chạy detector, đúng thiết kế đã có từ trước
A08-COR-01 (xem docstring `_run_execute`).

**Nếu quên `--user m4-collector`**: lệnh chạy dưới UID mặc định (thường là root/UID 0) — signing
service sẽ từ chối kết nối NGAY (peer UID không khớp `collector_uid`, T11-02/T12-01), collector
fail-closed đúng thiết kế (không leak gì, chỉ log `m4_signing_peer_rejected`), rehearsal thất bại
sạch — sửa lại `--user` rồi thử lại đúng vòng ceremony mới (gate trước đó đã consumed, không
retry dưới cùng gate).

## 5. Stop — dừng signing service (sau khi rehearsal xong, dù thành công hay thất bại)

```bash
docker exec alpha3s-api-1 python scripts/m4_stage0p_signing_launcher.py stop
```

Idempotent — gọi khi không có gì đang chạy cũng exit 0 an toàn (chỉ log
`signing_service_not_running`). Tự xóa pidfile + socket + thư mục socket.

## 6. Key lifecycle — tóm tắt vòng đời 3 khóa

| Khóa | Sinh ở đâu | Sống ở đâu | Retire khi nào |
|---|---|---|---|
| `M4_SAMPLE_KEY_B64` | Operator tự `openssl rand -base64 32` (hoặc tương đương) trước `provision-keys` | Chỉ trong biến môi trường của lệnh `provision-keys` + `signing_launcher start` + `run` (prediction writer) — KHÔNG có bảng DB nào lưu | Không cần "retire" DB (không provisioning DB) — chỉ ngừng dùng lại giá trị đó sau `stop` |
| `M4_TRANSCRIPT_HMAC_KEY_B64` | Cùng lúc | `m4_stage0p_transcript_signing_keys` (DB) + môi trường signing service | `retire-keys` (DB) SAU KHI `signing_launcher stop` |
| `M4_SIGNING_AUTH_VERIFY_KEY_B64` | Cùng lúc | `m4_stage0p_signing_auth_keys` (DB) + môi trường signing service | `retire-keys` (DB) SAU KHI `signing_launcher stop` |

**Không bao giờ** ghi 3 khóa này vào file, `.env`, log hay evidence — chỉ tồn tại trong biến môi
trường của các lệnh trên, tự mất khi shell session kết thúc.

## 7. Rollback / xử lý sự cố

| Tình huống | Xử lý |
|---|---|
| `start` báo lỗi "da chay (pid=...)" | Đã có service cũ chạy — `stop` trước, hoặc nếu chắc chắn đó là service của ceremony hiện tại, `status` để xác nhận trước khi tiếp tục |
| `start` báo `RuntimeError: signing service khong tao socket ... trong 5s` hoặc "thoat som" | Signing service tự từ chối khởi động (thư mục socket không an toàn, khóa sai độ dài...) — đọc log JSON đầy đủ trong output, KHÔNG retry mù quáng, đối chiếu với `_validate_socket_directory`/`main()` trong `stage0p_signing_service.py` |
| Execute báo `SigningServiceError: khong ket noi duoc signing service` | `status` để xác nhận service còn sống + đúng socket path; xác nhận `--user m4-collector` và `M4_STAGE0P_SIGNING_SOCKET` được truyền đúng (không bị shell/tool nào đó biến đổi path) |
| Execute báo lỗi "chua co signing_auth_key hieu luc" | Khóa `provision-keys` (DB) và khóa đưa cho `signing_launcher start` KHÔNG khớp (vd 1 lần cleanup đã `retire-keys` giữa chừng) — `stop`, `retire-keys`, sinh khóa MỚI, làm lại từ `provision-keys` |
| Cần dừng khẩn cấp | `signing_launcher.py stop` (SIGTERM rồi SIGKILL nếu cần trong 5s) — an toàn gọi bất kỳ lúc nào, không phá dữ liệu đã ghi (chỉ dừng nhận request mới) |
| pidfile còn nhưng tiến trình đã chết (crash) | `status`/`stop` tự phát hiện qua đối chiếu `/proc/<pid>/cmdline` — không gửi tín hiệu nhầm sang tiến trình khác lỡ tái sử dụng PID |

## 8. Evidence commands (không lộ secret)

```bash
docker exec alpha3s-api-1 python scripts/m4_stage0p_signing_launcher.py status
docker exec alpha3s-api-1 ps aux | grep -i signing_service
docker exec alpha3s-api-1 printenv | grep -iE "M4_SAMPLE_KEY|TRANSCRIPT_HMAC_KEY|SIGNING_AUTH_VERIFY_KEY"  # PHAI rong trong container api (collector) - key CHI trong tien trinh signer
```

Dòng cuối là 1 bằng chứng độc lập quan trọng: chạy trong container `api` (nơi collector/runner
sống), 3 biến khóa PHẢI **không xuất hiện** — nếu có, đó là dấu hiệu key đã bị leak vào sai môi
trường, dừng ngay và báo CA.
