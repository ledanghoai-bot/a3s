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

**REV1**: chuyển sang **docker-compose profile service** — `docker compose` chính là supervisor
(quản lý lifecycle/log/restart), UID `m4-signer`/`m4-collector` được tạo **lúc build image**
(Dockerfile, version-controlled, giống hệt trên mọi container tạo từ image), không còn script
Python tự spawn process nào cả — không còn cảnh báo GC, không còn pidfile tự viết tay.

**REV2**, đáp `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-2-VI.md` F-A08-R2-01/02:

- **F-A08-R2-01**: REV1 vẫn đưa 3 khóa THẬT vào `environment:` của `m4-signer` (`${VAR}`
  interpolation) — `docker inspect m4-signer` hiện được giá trị plaintext ở `Config.Env`. REV2
  chuyển 3 khóa sang **file, bind-mount READ-ONLY** từ 1 thư mục host operator tự chuẩn bị (chown
  đúng UID `m4-signer`=5001/GID `m4-signing-ipc`=5000, chmod owner-only) — `environment:` chỉ còn
  chứa ĐƯỜNG DẪN file (`..._FILE`), không còn giá trị. `stage0p_signing_service.py`
  (`_read_secret_env_or_file`) TỰ KIỂM TRA LẠI quyền file lúc khởi động (không chỉ tin bind-mount
  host giữ đúng permission — xem §3), từ chối khởi động nếu file có bit group/other hoặc sai chủ
  sở hữu.
- **F-A08-R2-02**: REV1's `signing_probe.py` trao `M4_SIGNING_AUTH_VERIFY_KEY_B64` (khóa đối xứng)
  cho chính danh tính `m4-collector` để tự ký canary — về lý thuyết collector có thể tự mint 1
  authorization cho NỘI DUNG BẤT KỲ, vô hiệu hóa ranh giới signer/collector. REV2 tách `probe`
  thành 2 subcommand chạy ở 2 danh tính khác nhau: `mint-token` (danh tinh operator, GIỮ khóa) +
  `submit` (danh tính `m4-collector` THẬT, KHÔNG BAO GIỜ nhận khóa — chỉ nhận 1 token đã-ký-sẵn,
  dùng được ĐÚNG 1 lần, TTL 20 giây, chỉ hợp lệ cho canary nội dung cố định) — xem §4.

**REV3 (hiện tại)**, đáp `PHASE1B-M4-AMENDMENT-08-SIGNING-CLEANUP-CORRECTION-REVIEW-3-VI.md`
F-A08-R3-01/02:

- **F-A08-R3-01 (bug thật trong chính runbook REV2, không phải lý thuyết)**: REV2 tạo thư mục
  `/run/m4-signing-secrets` bằng `install -d -o root -g root` (chỉ root traverse được) trong khi
  `m4-signer` chạy dưới UID `5001` — signer KHÔNG BAO GIỜ mở được bất kỳ file nào bên trong dù
  TỪNG FILE có permission đúng, vì thiếu quyền `--x` trên chính THƯ MỤC CHA. REV3 sửa lệnh `install
  -d` để chown thư mục CHO ĐÚNG UID `5001`/GID `5000`, và bổ sung 1 hàm kiểm tra fail-closed RIÊNG
  cho thư mục cha (`_validate_secret_parent_directory()`, cùng pattern
  `_validate_socket_directory()`) — không chỉ kiểm từng file như REV2.
- **F-A08-R3-02**: 2 thiếu sót vận hành — (a) `submit` vẫn dùng `-e TEN="$TOKEN"` (có `=`) cho
  token thay vì dạng bare như mọi secret khác; (b) runbook `export` 3 khóa/2 PIN/token vào shell
  operator nhưng chưa từng `unset` sau ceremony, mâu thuẫn với mô tả "chỉ tồn tại trong suốt
  ceremony". REV3 sửa cả hai — xem §4/§6.

**REV4 (hiện tại)**, đáp `PHASE1B-M4-AMENDMENT-10-EXECUTION-ATTEMPT-1-ABORT-REVIEW-VI.md`:

- **Image-freshness gap (Amendment 10 Attempt 1, KHÔNG phải lỗi signer/collector boundary)**:
  `m4-signer` dùng image riêng (`alpha3s-m4-signer`), build từ CÙNG `Dockerfile` với `api` nhưng
  KHÔNG nằm trong `deploy.sh SERVICES` — deploy thường không bao giờ rebuild nó. `docker compose
  up -d` (không `--build`) chỉ build image nếu image CHƯA từng tồn tại; sau lần build đầu tiên
  (Amendment 09), mọi `up -d` sau đó ÂM THẦM tái sử dụng image cache cũ, dù `main`/deployed commit
  đã có fix mới (PR #13's `.dockerignore`) — bug `.env` "tái phát" ở Amendment 10 Attempt 1 dù
  code đã đúng từ lâu, chỉ vì image chưa từng được rebuild. REV4 thêm 1 `ARG GIT_COMMIT`/`LABEL
  git_commit` vào `Dockerfile` + build tường minh + xác minh label khớp `git rev-parse HEAD`
  BẮT BUỘC trước MỌI lần `up -d m4-signer` — xem §2/§3/§9.

## 1. Trình tự đầy đủ 1 ceremony (tóm tắt, chi tiết PIN/approval xem docstring runner)

```
record-approval (staff 3, PIN riêng)
  -> build m4-signer + xac minh label git_commit khop deployed HEAD    <-- bước MỚI (REV4)
  -> chuẩn bị 3 file khóa trong /run/m4-signing-secrets (chown/chmod)  <-- bước MỚI (F-A08-R2-01)
  -> provision-keys (3 khóa mới, tự sinh ngẫu nhiên, CÙNG giá trị vừa ghi vào file)
  -> docker compose --profile m4-signing up -d m4-signer   <-- bước MỚI (A08-COR-01)
  -> mint-token (danh tính operator, giữ khóa)             <-- bước MỚI (F-A08-R2-02)
  -> submit (canary, danh tính m4-collector, KHÔNG giữ khóa) <-- bước MỚI (F-A08-R1-03/F-A08-R2-02)
  -> run --dry-run (xác nhận preflight)
  -> run (execute thật, chạy DƯỚI UID m4-collector)         <-- bước MỚI (A08-COR-01)
  -> docker compose --profile m4-signing stop m4-signer     <-- bước MỚI (A08-COR-01)
  -> retire-keys
  -> xóa 3 file khóa trong /run/m4-signing-secrets           <-- bước MỚI (F-A08-R2-01)
  -> record-approval --revoke
```

## 2. Preflight bắt buộc trước khi start

```bash
docker compose -f docker-compose.prod.yml --profile m4-signing ps m4-signer
```

Xác nhận: không có container `m4-signer` nào đang `Up` (nếu có, `stop` trước — xem §5); deployed
HEAD đúng commit CA đã accept (`git rev-parse HEAD`); `m4_stage0p_transcript_signing_keys`/
`m4_stage0p_signing_auth_keys` không có active key cũ (nếu có, `retire-keys` trước).

**REV4 — bắt buộc, đáp `PHASE1B-M4-AMENDMENT-10-EXECUTION-ATTEMPT-1-ABORT-REVIEW-VI.md`**:
`m4-signer` là service dormant/profile-only, **KHÔNG nằm trong `deploy.sh SERVICES`** — deploy
thường (`api`/`worker`/bot/`dashboard`) KHÔNG BAO GIỜ rebuild image này. `docker compose ... up -d`
(không `--build`) chỉ build image nếu image CHƯA từng tồn tại — nếu đã tồn tại (từ 1 ceremony
trước), lệnh `up` sẽ **âm thầm tái sử dụng image cache cũ**, dù source/deployed commit đã đổi
(Amendment 10 Attempt 1 chạy đúng cảnh này: image cache từ Amendment 09, trước PR #13, khiến bug
`.env` đã fix "tái phát" dù merge/deploy đúng commit). **Do đó §3 dưới đây LUÔN build tường minh
+ xác minh label commit TRƯỚC MỌI lần `up -d m4-signer`, không có ngoại lệ, kể cả khi tin rằng
image "chắc còn mới".**

## 3. Start — khởi động signing service qua docker compose

**REV4 (Correction 2, đáp `PHASE1B-M4-SIGNER-IMAGE-FRESHNESS-CORRECTION-REVIEW-1-VI.md` F-IMG-01)
— build tường minh TRƯỚC KHI `up`, xác minh ĐÚNG image mà Compose sẽ chạy khớp deployed commit
(KHÔNG dùng `--pull`, KHÔNG đổi base image):**

**F-IMG-01**: KHÔNG được hard-code tag `alpha3s-m4-signer:latest` — tên này do Compose suy ra từ
project name (`COMPOSE_PROJECT_NAME`/tên thư mục/`name:` trong compose file), có thể khác nhau
giữa các lần chạy. Nếu hard-code, guard có thể inspect nhầm 1 image cũ/không liên quan trong khi
Compose thật sự dùng 1 image khác — false green, không còn chặn được đúng lỗi Amendment 10
Attempt 1. **Lưu ý**: `docker compose config --images m4-signer` liệt kê CẢ image của dependency
(`redis:7-alpine` qua `depends_on`), không CHỈ riêng `m4-signer` — không dùng trực tiếp giá trị đó.
Lấy identifier chính xác qua `config --format json` (đòi hỏi `jq`, đã xác nhận có sẵn trên VPS):
đọc `.services["m4-signer"].image` nếu Compose có set tường minh, nếu không (trường hợp thật — chỉ
`build:`, không `image:`) thì ghép từ CHÍNH project name Compose đã resolve (`.name` trong CÙNG
JSON, không phải giả định "alpha3s") theo đúng quy ước đặt tên mặc định của Compose
(`${project}-${service}`):

```bash
GIT_COMMIT=$(git rev-parse HEAD)

CONFIG_JSON=$(docker compose -f docker-compose.prod.yml --profile m4-signing config --format json)
IMAGE_REF=$(echo "$CONFIG_JSON" | jq -r '.services["m4-signer"].image // empty')
if [ -z "$IMAGE_REF" ]; then
  PROJECT_NAME=$(echo "$CONFIG_JSON" | jq -r '.name')
  if [ -z "$PROJECT_NAME" ] || [ "$PROJECT_NAME" = "null" ]; then
    echo "LOI: khong resolve duoc project name tu Compose config - DUNG" >&2
    exit 1
  fi
  IMAGE_REF="${PROJECT_NAME}-m4-signer"
fi
echo "resolved image_ref: $IMAGE_REF"

GIT_COMMIT="$GIT_COMMIT" docker compose -f docker-compose.prod.yml --profile m4-signing build m4-signer

IMAGE_COMMIT=$(docker inspect "$IMAGE_REF" --format '{{index .Config.Labels "git_commit"}}' 2>/dev/null)
if [ -z "$IMAGE_COMMIT" ] || [ "$IMAGE_COMMIT" = "<no value>" ] || [ "$IMAGE_COMMIT" = "unknown" ] || [ "$IMAGE_COMMIT" != "$GIT_COMMIT" ]; then
  echo "LOI: image m4-signer ($IMAGE_REF, label git_commit=$IMAGE_COMMIT) KHONG khop deployed HEAD ($GIT_COMMIT) - DUNG, khong up -d" >&2
  exit 1
fi
echo "OK: image m4-signer ($IMAGE_REF) khop dung deployed commit $GIT_COMMIT"
```

`IMAGE_REF` luôn phản ánh ĐÚNG identifier mà `up -d m4-signer` (bước dưới) sẽ dùng, bất kể project
name là gì — cả `.image` (nếu Compose từng set tường minh) lẫn phần fallback `${project}-service`
đều đọc TỪ CHÍNH JSON output của CÙNG invocation context (`-f`/`--profile`/thư mục hiện tại) sẽ
dùng để `build`/`up`, không phải 1 giá trị suy đoán tách biệt. Xác nhận thực tế trên VPS (không
phải lý thuyết): `docker compose ... config --format json | jq -r '.name'` đổi đúng theo
`COMPOSE_PROJECT_NAME`/`-p` (vd `alpha3s` → `differentproj` cho ra `differentproj-m4-signer`) —
nếu vẫn hard-code `alpha3s-m4-signer:latest`, guard sẽ inspect nhầm 1 image không liên quan (hoặc
không tồn tại) thay vì image Compose thực sự chọn.

Guard fail-closed ở CẢ 3 tình huống: (a) không resolve được `IMAGE_REF` (rỗng), (b) label rỗng/
`<no value>`/`unknown` (image chưa từng gắn label, vd build cũ trước REV4), (c) label có giá trị
nhưng không khớp `git rev-parse HEAD`.

Chỉ tiếp tục phần dưới (chuẩn bị secret + `up -d`) SAU KHI dòng `OK:` xuất hiện — nếu báo `LOI:`,
dừng ngay, không `up -d` với image chưa xác minh, báo lại (không tự sửa bằng `--pull` hay đổi
Dockerfile giữa ceremony).

**F-A08-R2-01: 3 khóa PHẢI nằm trong FILE (không còn `environment:`/`${VAR}` như REV1)** — chuẩn
bị thư mục + file TRƯỚC khi `up` (mọi lệnh dưới đây chạy với quyền root trên VPS, ví dụ SSH root
đã xác nhận — xem `docs/VPS-RUNBOOK-VI.md`):

```bash
# F-A08-R3-01: THU MUC CHA phai chown cho DUNG UID m4-signer (5001)/GID m4-signing-ipc (5000) -
# KHONG duoc de root:root (loi da xay ra o REV2: signer khong the traverse VAO thu muc du tung
# file ben trong permission dung, service tu choi khoi dong o buoi kiem thu muc cha rieng, xem
# _validate_secret_parent_directory() trong stage0p_signing_service.py).
install -d -m 0700 -o 5001 -g 5000 /run/m4-signing-secrets   # /run la tmpfs (RAM) - khong dong dia

umask 077
openssl rand -base64 32 > /run/m4-signing-secrets/sample_key
openssl rand -base64 32 > /run/m4-signing-secrets/transcript_hmac_key
openssl rand -base64 32 > /run/m4-signing-secrets/signing_auth_key

# 5001 = UID m4-signer, 5000 = GID m4-signing-ipc (Dockerfile, CO DINH, khong doi) - CHI UID nay
# doc duoc file (owner-only, mode 0400 - khong group/other du group co khop).
chown 5001:5000 /run/m4-signing-secrets/*
chmod 0400 /run/m4-signing-secrets/*
```

Đưa CÙNG 3 giá trị vừa sinh cho `provision-keys` (đọc file lại để lấy giá trị, dùng dạng bare
`-e TEN` — xem §5 giải thích tại sao):

```bash
export M4_SAMPLE_KEY_B64=$(cat /run/m4-signing-secrets/sample_key)
export M4_TRANSCRIPT_HMAC_KEY_B64=$(cat /run/m4-signing-secrets/transcript_hmac_key)
export M4_SIGNING_AUTH_VERIFY_KEY_B64=$(cat /run/m4-signing-secrets/signing_auth_key)
docker compose -f docker-compose.prod.yml exec \
  -e M4_SAMPLE_KEY_B64 -e M4_TRANSCRIPT_HMAC_KEY_B64 -e M4_SIGNING_AUTH_VERIFY_KEY_B64 \
  api python scripts/m4_stage0p_rehearsal_runner.py provision-keys
```

**Không cần `export` gì thêm để `up`** — `docker-compose.prod.yml` đã trỏ sẵn `..._FILE` tới
đường dẫn cố định ở trên, không đọc `${VAR}` nào từ shell nữa (khác REV1):

```bash
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

Nếu `chown`/`chmod` ở trên bị bỏ sót hoặc sai (vd file world-readable, hoặc thuộc sai UID) — **HOẶC
nếu chính thư mục `/run/m4-signing-secrets` sai chủ sở hữu/permission** (F-A08-R3-01: đây là lỗi
thật đã từng xảy ra ở REV2 — thư mục `root:root` khiến signer không traverse được VÀO thư mục dù
từng file bên trong đúng) — `m4-signer` **tự phát hiện VÀ từ chối khởi động** ở CẢ 2 lớp: thư mục
cha (`_validate_secret_parent_directory()`, kiểm TRƯỚC KHI đụng tới file) và từng file
(`_read_secret_env_or_file()` tự `stat()` lại — không chỉ tin bind-mount host giữ đúng permission,
cùng triết lý phòng thủ-nhiều-lớp đã áp dụng cho thư mục socket): `docker compose logs m4-signer`
sẽ hiện `"...thu muc cha ... khong thuoc so huu..."`/`"...thu muc cha ... qua rong quyen..."` (lỗi
thư mục) hoặc `"...qua rong quyen..."`/`"...khong thuoc so huu tien trinh nay..."` (lỗi từng file)
— sửa quyền thư mục/file rồi `up -d m4-signer` lại.

## 4. Canary probe — xác nhận signing path THẬT hoạt động (F-A08-R1-03/F-A08-R2-02)

`healthcheck` của compose chỉ chứng minh **tiến trình đang lắng nghe** (socket file tồn tại đúng
mode) — KHÔNG chứng minh peer-UID/rate-limit/nonce/chữ ký/canonicalize/mã hóa/ký THẬT SỰ hoạt
động đúng. Canary probe THẬT (dữ liệu hoàn toàn giả lập, không ghi DB, không chạm dữ liệu
rehearsal/khách hàng) — **tách làm 2 bước, chạy ở 2 danh tính KHÁC NHAU** (F-A08-R2-02: REV1 trao
khóa cho chính danh tính `m4-collector`, để collector có thể tự mint authorization cho nội dung
bất kỳ — vô hiệu hóa ranh giới signer/collector; REV2 sửa bằng cách KHÔNG BAO GIỜ để `m4-collector`
nắm giữ khóa):

**Bước 1 — `mint-token`, danh tính operator (KHÔNG `--user m4-collector`), CẦN khóa:**

```bash
export M4_SIGNING_PROBE_TOKEN=$(docker compose -f docker-compose.prod.yml exec \
  -e M4_SIGNING_AUTH_VERIFY_KEY_B64 \
  api python scripts/m4_stage0p_signing_probe.py mint-token)
```

Ký 1 `signing_authorization` DUY NHẤT cho nội dung canary cố định (TTL 20 giây, dùng được ĐÚNG 1
lần — tiêu thụ nonce qua Redis giống mọi request thật), in ra 1 dòng base64(JSON) chứa token +
các trường mô tả request (sample_id/txid/canonical_digest_hex/...) — KHÔNG chứa khóa dưới bất kỳ
dạng nào. **F-A08-R3-02**: `export` THẲNG vào `M4_SIGNING_PROBE_TOKEN` (không dùng tên biến tạm
`TOKEN` riêng như REV2) — cùng tên với biến `submit` sẽ đọc, cho phép dùng dạng bare `-e` nhất
quán ở bước 2 (không phải giữ 2 tên biến chỉ để 1 giá trị).

**Bước 2 — `submit`, danh tính `m4-collector` THẬT, KHÔNG cần và KHÔNG được đưa khóa:**

```bash
docker compose -f docker-compose.prod.yml exec --user m4-collector \
  -e M4_SIGNING_PROBE_TOKEN \
  api python scripts/m4_stage0p_signing_probe.py submit
```

`submit` KHÔNG có code path nào đọc `M4_SIGNING_AUTH_VERIFY_KEY_B64` (xác nhận bằng static audit
tự động, `scripts/m4_stage0p_signing_probe_test.py` [P-08]) — dù giá trị này có lỡ bị đặt vào env
của lệnh `exec` (vd thao tác nhầm), `submit` cũng không dùng tới (evidence [P-09]). Nếu ai đó thử
sửa 1 trường trong `$M4_SIGNING_PROBE_TOKEN` trước khi `submit` (vd đổi `sample_id`), service từ
chối vì chữ ký không còn khớp — `m4-collector` chỉ có thể replay ĐÚNG NGUYÊN token được cấp, không
tự tạo được authorization khác (evidence [P-10]).

**Lưu ý dạng `-e TEN_BIEN` (KHÔNG có `=gia_tri`, F-A08-R1-02, áp dụng NHẤT QUÁN cho MỌI giá trị kể
cả token — F-A08-R3-02 sửa lại điểm REV2 còn dùng `=`)**: đây KHÔNG phải thiếu sót đánh máy — dạng
có `=` (`-e TEN="$TEN"`) khiến giá trị xuất hiện làm 1 token literal trong chính argv của tiến
trình `docker`/`docker compose` client trên host (ai có quyền `ps aux`/đọc `/proc/<pid>/cmdline`
trên host TRONG lúc lệnh đang chạy đều đọc được). Dạng bare `-e TEN` yêu cầu Docker client tự đọc
giá trị từ MÔI TRƯỜNG CỦA CHÍNH CLIENT rồi chuyển qua Docker API — giá trị không bao giờ là 1
token argv (đã kiểm chứng thực tế: `docker exec -e VAR <container> printenv VAR` cho ra đúng giá
trị dù `VAR` không hề có `=value` trên command line).

Output JSON `{"event": "m4_signing_probe_ok", "ok": true, ...}` xác nhận: peer UID `m4-collector`
được service chấp nhận, rate-limit/nonce/chữ ký `signing_authorization` đều hợp lệ, và service
THẬT SỰ canonicalize + mã hóa + ký thành công. `ok: false` → xem §8 (rollback/xử lý sự cố),
**không tiến hành ceremony**.

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

**F-A08-R2-01: xóa 3 file khóa NGAY SAU KHI `stop`** (dù `/run` là tmpfs — không đụng đĩa — vẫn
đóng cửa sổ đọc được sớm nhất có thể, cùng triết lý "chỉ tồn tại trong suốt ceremony" như REV1
dùng cho biến môi trường):

```bash
rm -f /run/m4-signing-secrets/sample_key /run/m4-signing-secrets/transcript_hmac_key \
  /run/m4-signing-secrets/signing_auth_key
```

**F-A08-R3-02: `unset` TOÀN BỘ biến shell operator NGAY SAU ĐÓ** — runbook trước đây `export` các
biến này nhưng chưa từng hướng dẫn dọn khỏi shell, mâu thuẫn với mô tả "chỉ tồn tại trong suốt
ceremony" (§7). Chạy dòng này trong CÙNG session shell đã `export` (BẮT BUỘC dù ceremony **thành
công, thất bại, hay dừng khẩn cấp** — không có trường hợp ngoại lệ):

```bash
unset M4_SAMPLE_KEY_B64 M4_TRANSCRIPT_HMAC_KEY_B64 M4_SIGNING_AUTH_VERIFY_KEY_B64 \
  M4_SIGNING_PROBE_TOKEN STAGE0P_REHEARSAL_OPERATOR_PIN STAGE0P_REHEARSAL_REVIEWER_PIN
```

Xác nhận SẠCH (chỉ in TÊN BIẾN + trạng thái `absent`/`SET`, KHÔNG BAO GIỜ in giá trị — xem §9):

```bash
for VAR in M4_SAMPLE_KEY_B64 M4_TRANSCRIPT_HMAC_KEY_B64 M4_SIGNING_AUTH_VERIFY_KEY_B64 \
           M4_SIGNING_PROBE_TOKEN STAGE0P_REHEARSAL_OPERATOR_PIN STAGE0P_REHEARSAL_REVIEWER_PIN; do
  if [ -z "${!VAR+x}" ]; then echo "$VAR: absent"; else echo "$VAR: VAN CON SET - unset lai ngay"; fi
done
```

Nếu ceremony dừng khẩn cấp giữa chừng (§8) — chạy CẢ 2 khối lệnh này (xóa file §6 + `unset` ở
trên) như bước dọn dẹp cuối cùng, bất kể tiến trình dừng ở bước nào.

## 7. Key lifecycle — tóm tắt vòng đời 3 khóa

| Khóa | Sinh ở đâu | Sống ở đâu | Retire khi nào |
|---|---|---|---|
| `M4_SAMPLE_KEY_B64` | Operator tự `openssl rand -base64 32` trước `provision-keys` (§3) | `/run/m4-signing-secrets/sample_key` (file, chown 5001:5000/chmod 0400, bind-mount READ-ONLY vào `m4-signer`) + biến môi trường shell của operator (đưa cho `provision-keys`, `run`/prediction writer — xem §5) — KHÔNG bảng DB nào lưu | Không cần "retire" DB — xóa file + ngừng dùng lại giá trị sau `stop` (§6) |
| `M4_TRANSCRIPT_HMAC_KEY_B64` | Cùng lúc | `m4_stage0p_transcript_signing_keys` (DB) + `/run/m4-signing-secrets/transcript_hmac_key` (file) | `retire-keys` (DB) SAU KHI `stop`, xóa file (§6) |
| `M4_SIGNING_AUTH_VERIFY_KEY_B64` | Cùng lúc | `m4_stage0p_signing_auth_keys` (DB) + `/run/m4-signing-secrets/signing_auth_key` (file) + operator tự giữ trong shell để chạy `mint-token` (§4) | `retire-keys` (DB) SAU KHI `stop`, xóa file (§6) |

**F-A08-R2-01 (REV2)**: `m4-signer` KHÔNG còn nhận giá trị khóa qua `environment:`/`${VAR}` (REV1
cũ) — CHỈ nhận 3 ĐƯỜNG DẪN FILE (`..._FILE`, xem `docker-compose.prod.yml`), đọc qua
`_read_secret_env_or_file()` (`stage0p_signing_service.py`) tự kiểm tra lại quyền/chủ sở hữu file
lúc khởi động (§3). File sống trong `/run` (tmpfs, RAM-backed, không đụng đĩa, tự mất khi reboot)
— chỉ tồn tại trong suốt ceremony, xóa tường minh sau `stop` (§6).

3 khóa CHỈ tồn tại: (a) trong file `/run/m4-signing-secrets/*` (đọc bởi `m4-signer`, xóa ở §6), và
(b) trong biến môi trường shell của operator (đưa cho `provision-keys`/`mint-token`/`run` qua
`exec -e <TEN>` dạng bare, không `=giá trị` — xem §4/§5, **`unset` bắt buộc ở §6 sau ceremony,
F-A08-R3-02**) — không bao giờ ghi vào `.env`, log hay evidence.

**Giới hạn cố hữu còn lại, không che giấu — 2 kênh KHÁC NHAU, không nhầm lẫn**:

1. **File secret trên host** (`/run/m4-signing-secrets/*`): bất kỳ ai có quyền root trên host đọc
   được trực tiếp (`cat` file) — đây là giới hạn cố hữu của MỌI thiết kế secret-qua-file trên máy
   chủ chia sẻ (không riêng gì thiết kế này); giảm thiểu bằng permission 0400/chown đúng UID +
   tmpfs (không tồn tại lâu dài trên đĩa) + xóa tường minh sau `stop`.
2. **Secret truyền lúc `exec`** (§3/§4/§5: `M4_SAMPLE_KEY_B64`/`M4_TRANSCRIPT_HMAC_KEY_B64`/
   `M4_SIGNING_AUTH_VERIFY_KEY_B64` cho `provision-keys`, `M4_SIGNING_AUTH_VERIFY_KEY_B64` cho
   `mint-token`, `M4_SIGNING_PROBE_TOKEN` cho `submit`,
   `STAGE0P_REHEARSAL_OPERATOR_PIN`/`STAGE0P_REHEARSAL_REVIEWER_PIN`/`M4_SAMPLE_KEY_B64` cho
   execute) KHÔNG thuộc `Config.Env` của container (`docker exec -e` là override tạm thời cho
   riêng tiến trình exec, không persist) nên `docker inspect` KHÔNG hiện được các giá trị này —
   dạng bare `-e TEN` (F-A08-R3-02: áp dụng NHẤT QUÁN cho MỌI giá trị ở §3/§4/§5, kể cả token) đóng
   luôn kênh rò rỉ còn lại (argv của tiến trình client trên host).

Cả 2 trường hợp: ai có quyền Docker API/root trên host vốn đã có quyền đọc `.env`/kết nối DB trực
tiếp — không mở rộng bề mặt tấn công so với mức truy cập đã có sẵn.

## 8. Rollback / xử lý sự cố

| Tình huống | Xử lý |
|---|---|
| `git_commit` label mismatch ở bước build §3 (REV4) | Image `m4-signer` build từ commit cũ hơn deployed HEAD hiện tại — **KHÔNG** `up -d`; chạy lại đúng lệnh `build` §3 (không `--pull`, không sửa Dockerfile giữa ceremony); nếu vẫn mismatch, dừng và báo CA/PO — có thể deployed HEAD trên VPS chưa khớp gate đã accept |
| `up -d m4-signer` báo `signing service tu choi khoi dong: ... chua duoc dat day du` | File khóa chưa tồn tại ở `/run/m4-signing-secrets/` — chạy lại §3 (`openssl rand` + `chown`/`chmod`) |
| `up -d m4-signer` báo `... qua rong quyen (mode=...)` | 1 trong 3 file có bit group/other — `chmod 0400 /run/m4-signing-secrets/*` rồi thử lại |
| `up -d m4-signer` báo `... khong thuoc so huu tien trinh nay` | 1 trong 3 file sai chủ sở hữu — `chown 5001:5000 /run/m4-signing-secrets/*` rồi thử lại |
| `up -d m4-signer` báo `thu muc cha cua secret file khong thuoc so huu tien trinh nay` (F-A08-R3-01) | Chính thư mục `/run/m4-signing-secrets` sai chủ sở hữu (vd còn `root:root` từ `install -d` cũ) — `chown 5001:5000 /run/m4-signing-secrets` (thư mục, KHÔNG chỉ file bên trong) rồi thử lại; xác nhận đang dùng ĐÚNG lệnh `install -d -m 0700 -o 5001 -g 5000` ở §3 |
| `up -d m4-signer` báo `thu muc cha cua secret file qua rong quyen` | Thư mục có bit group/other — `chmod 0700 /run/m4-signing-secrets` rồi thử lại |
| `ps m4-signer` báo `Exited`/`unhealthy` | `docker compose logs m4-signer --tail 50` đọc lý do THẬT (vd `_validate_socket_directory` hoặc `_read_secret_env_or_file`/`_validate_secret_parent_directory` từ chối) — KHÔNG retry mù quáng |
| `mint-token`/`submit` báo `ok: false` | Kiểm `docker compose ps m4-signer` còn `Up` không; xác nhận `M4_SIGNING_AUTH_VERIFY_KEY_B64` truyền cho `mint-token` ĐÚNG bằng giá trị đã ghi vào `/run/m4-signing-secrets/signing_auth_key` (khác khóa = chữ ký không khớp, an toàn nhưng vô dụng); nếu `submit` báo lỗi mà `mint-token` đã thành công, kiểm `$M4_SIGNING_PROBE_TOKEN` có bị cắt/hỏng không (`echo -n "$M4_SIGNING_PROBE_TOKEN" | wc -c` để kiểm độ dài, KHÔNG in giá trị ra) |
| Execute báo `SigningServiceError: khong ket noi duoc signing service` | `ps m4-signer` xác nhận còn `Up`; xác nhận `--user m4-collector` và `M4_STAGE0P_SIGNING_SOCKET` truyền đúng cho lệnh `exec` |
| Execute báo "chua co signing_auth_key hieu luc" | Khóa `provision-keys` (DB) và khóa trong `/run/m4-signing-secrets/` (đưa cho `up -d m4-signer`) KHÔNG khớp (vd `retire-keys` chạy giữa chừng) — `stop`, `retire-keys`, sinh khóa MỚI (ghi đè cả 3 file lẫn DB), làm lại từ `provision-keys` |
| Cần dừng khẩn cấp | `docker compose --profile m4-signing stop m4-signer` (SIGTERM, Docker tự SIGKILL sau timeout mặc định nếu cần) — an toàn gọi bất kỳ lúc nào |
| `m4-signer` crash giữa lúc đang chạy rehearsal | **KHÔNG tự phục hồi** (`restart: "no"` chủ ý) — collector sẽ tự fail-closed sau vài lần retry (xem `COLLECTOR_MAX_ATTEMPTS`/`_run_collector_with_retry` trong runner), runner tự cleanup + terminalize batch `'aborted'`. Xem log `m4-signer` (nếu container còn giữ lại, `docker compose logs`) để tìm nguyên nhân crash trước khi thử ceremony mới — không `up -d` lại giữa chừng 1 gate đang mở |

## 9. Evidence commands (không lộ secret)

**REV4 — bằng chứng image freshness (chạy SAU §3 build, TRƯỚC `up -d`; F-IMG-01: resolve identifier
qua `config --format json`/`jq`, KHÔNG hard-code tag, KHÔNG dùng `config --images <service>` trực
tiếp vì lệnh đó gộp cả image của dependency như `redis:7-alpine`):**

```bash
CONFIG_JSON=$(docker compose -f docker-compose.prod.yml --profile m4-signing config --format json)
IMAGE_REF=$(echo "$CONFIG_JSON" | jq -r '.services["m4-signer"].image // empty')
if [ -z "$IMAGE_REF" ]; then
  IMAGE_REF="$(echo "$CONFIG_JSON" | jq -r '.name')-m4-signer"
fi
echo "image_ref=$IMAGE_REF"
docker inspect "$IMAGE_REF" --format 'git_commit={{index .Config.Labels "git_commit"}}'
git rev-parse HEAD
# 2 gia tri (label vs git rev-parse HEAD) PHAI khop nhau tuyet doi - day la bang chung image KHONG
# phai cache cu VA la DUNG image ma Compose se dung (khong phai 1 tag doan/hard-code).
```

```bash
docker compose -f docker-compose.prod.yml --profile m4-signing ps m4-signer
docker compose -f docker-compose.prod.yml logs m4-signer --tail 50
docker compose -f docker-compose.prod.yml exec api printenv | grep -iE "M4_SAMPLE_KEY|TRANSCRIPT_HMAC_KEY|SIGNING_AUTH_VERIFY_KEY"  # PHAI rong trong container api - key CHI trong file mount cua m4-signer

# F-A08-R2-01: xac nhan docker inspect KHONG hien gia tri khoa (chi hien duong dan mount, khong
# phai secret) - grep tim base64 KHONG khop (khong co gia tri THAT nao de tim, chi list lenh nay
# de xac nhan Config.Env/Mounts KHONG chua ky tu la ("=" ngay sau ten bien khoa).
docker inspect $(docker compose -f docker-compose.prod.yml --profile m4-signing ps -q m4-signer) \
  --format '{{json .Config.Env}}' | grep -oE "M4_(SAMPLE|TRANSCRIPT_HMAC|SIGNING_AUTH_VERIFY)_KEY_B64=[^,\"]+"
# PHAI khong co dong nao o tren (Config.Env chi con "..._FILE=/run/m4-signing-secrets/..." - duong
# dan, khong phai gia tri) - neu co dong nao khop pattern tren, dung ngay va bao CA.
```

Dòng `printenv` là bằng chứng độc lập quan trọng: chạy trong `api` (nơi collector/runner sống), 3
biến khóa PHẢI **không xuất hiện** — nếu có, dừng ngay và báo CA. Dòng `docker inspect` xác nhận
`Config.Env` của CHÍNH `m4-signer` cũng không còn giá trị plaintext (F-A08-R2-01) — chỉ còn đường
dẫn file.

**F-A08-R3-02 — bằng chứng cleanup shell operator** (chạy SAU `unset` ở §6, chỉ in tên biến +
trạng thái, KHÔNG BAO GIỜ in giá trị dù còn `SET`):

```bash
for VAR in M4_SAMPLE_KEY_B64 M4_TRANSCRIPT_HMAC_KEY_B64 M4_SIGNING_AUTH_VERIFY_KEY_B64 \
           M4_SIGNING_PROBE_TOKEN STAGE0P_REHEARSAL_OPERATOR_PIN STAGE0P_REHEARSAL_REVIEWER_PIN; do
  if [ -z "${!VAR+x}" ]; then echo "$VAR: absent"; else echo "$VAR: VAN CON SET"; fi
done
ls -la /run/m4-signing-secrets/ 2>&1   # PHAI bao "No such file or directory" hoac thu muc rong
                                        # (3 file da xoa) sau §6
```

Cả 6 biến PHẢI báo `absent` VÀ thư mục `/run/m4-signing-secrets/` PHẢI rỗng/không còn file — nếu
không, `unset`/`rm -f` lại ngay (§6), không để sang phiên SSH sau.
