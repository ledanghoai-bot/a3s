---
id: A3S-PHASE1B-M4-STAGE-0P-TECHNICAL-CORRECTION-12-001
title: Alpha3S Phase I-B M4 Stage 0P — Technical Correction #12
document_type: technical_correction_submission
owner: Dev
status: SUBMITTED — chờ CA review
created_at: 2026-07-31
answers: PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-11-VI.md (CA, CHANGES_REQUIRED, reviewed_head 0610e6ae7b820aa2a8079eed0cf0878e59215ae4)
governing_spec: A3S-PHASE1B-M4-SPEC-001 v1.1.0
governing_package: docs/PHASE1B-M4-STAGE-0P-GOVERNANCE-PACKAGE-VI.md v4.0.0
language: vi-VN
---

# Stage 0P — Technical Correction #12

Đáp lại `PHASE1B-M4-STAGE-0P-TECHNICAL-REVIEW-11-VI.md` — sửa `T11-01` (P1, `asyncio.CancelledError`
kế thừa `BaseException` từ Python 3.8, nên `except Exception:` cũ trong `__aenter__()` bỏ sót
cancellation giữa chừng setup); sửa `T11-02` (P1, Unix socket của signing service chưa có
access-control boundary — bất kỳ tiến trình local nào cũng dùng được như 1 signing oracle); và
`T11-03` (P2, "có thể đóng cùng T11-02" theo CA — signer cần ràng buộc request với authority của
caller). `T10-01`/`T10-04` giữ nguyên KHÔNG đổi (CA đã xác nhận CLOSED, exact delta round này không
chạm). `T9-03` KHÔNG sửa bằng code — CA tiếp tục đóng khung đây là **activation blocker**. Phạm vi
KHÔNG đổi: dev/test trên branch M4 (worktree `D:\alpha3s-m4`, KHÔNG checkout M4 trong `D:\alpha3s`),
dữ liệu synthetic/test, **KHÔNG** merge/deploy/production-data-access/activation. Ngưỡng exclusion
`10%/200` (T4-05) tiếp tục ở nguyên trạng CA đề xuất, CHƯA có PO decision record chính thức.

## 1. Mapping finding → sửa

| Finding | Xử lý | File |
|---|---|---|
| **T11-01** (P1) — `except Exception:` REV11 quanh chuỗi setup trong `__aenter__()` KHÔNG bắt được `asyncio.CancelledError` (kế thừa `BaseException` trực tiếp từ Python 3.8, không còn kế thừa `Exception`) — 1 lần cancel() THẬT tới task đang chạy `__aenter__()` giữa chừng setup xuyên thẳng qua nhánh except, bỏ qua `_wait_cleanup_and_release` hoàn toàn; Python không bao giờ gọi `__aexit__()` khi `__aenter__()` tự raise, nên connection bị "kẹt" checked-out với pin/role còn sống vĩnh viễn | `except Exception:` → `except BaseException:`. AN TOÀN (không giống 1 `except BaseException` "bắt tất cả" thông thường hay bị cảnh báo vì có thể nuốt nhầm `KeyboardInterrupt`/`SystemExit`) VÌ nhánh này LUÔN LUÔN `raise` lại NGUYÊN VẸN VÔ ĐIỀU KIỆN ở cuối — không có logic re-raise có điều kiện, không có đường nào "nuốt lỗi rồi tiếp tục" | `app/services/pii/stage0p_pool.py` (`_PinnedSession.__aenter__`) |
| **T11-02** (P1) — `asyncio.start_unix_server(..., path=socket_path)` REV11 không có private parent directory/mode, không chmod socket, không xác minh peer credential, không giới hạn frame/concurrency/rate/timeout server-side — bất kỳ tiến trình local nào mở được socket path đều dùng service như 1 "encryption/signing oracle" tùy ý | `_validate_socket_directory()`: startup FAIL NGAY nếu thư mục cha không tồn tại, LÀ symlink, KHÔNG thuộc sở hữu chính tiến trình này, hoặc có bit quyền group/other (mode & 0o077 != 0 — vd `/tmp` mode 1777 bị TỪ CHỐI); socket path tự nó nếu ĐÃ là 1 symlink có sẵn cũng bị từ chối. Sau khi bind, `os.chmod(socket_path, 0o600)`. `_peer_uid()` đọc UID THẬT của tiến trình đang kết nối qua `SO_PEERCRED` TRƯỚC KHI đọc bất kỳ frame nào, so sánh với `allowed_uid` (mặc định = uid của chính tiến trình service — mô hình dev/test 1 host; ghi đè qua `STAGE0P_SIGNING_ALLOWED_UID`) — không khớp thì từ chối ngay, đóng kết nối, KHÔNG đọc frame nào. `asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS=8)` giới hạn request đồng thời; `asyncio.wait_for(..., timeout=_REQUEST_TIMEOUT_SECONDS=5.0)` bọc toàn bộ vòng đời 1 kết nối (đọc frame + xử lý + ghi response) — chặn cả frame quá lớn (đã có `_MAX_FRAME_BYTES` từ REV11) lẫn frame "chậm" kiểu slow-loris | `app/services/pii/stage0p_signing_service.py` (`_validate_socket_directory`, `_peer_uid`, `_allowed_uid`, `_handle_conn`, `run_signing_service`, `main`); `scripts/_stage0p_signing_service_helper.py` (tự tạo thư mục riêng mode 0700, hỗ trợ `allowed_uid` override cho test) |
| **T11-03** (P2) — signer chưa ràng buộc request với authority của caller — "có thể đóng cùng T11-02" theo CA (cho phép chọn HOẶC one-time-token DB-issued HOẶC signer verify caller identity/scope) | Chọn nhánh "signer verify caller identity" — CHÍNH là cơ chế peer-UID của T11-02 (không xây thêm hệ thống one-time-token DB-issued riêng). "Không log/trả raw content trong error": đã đúng từ REV11 (xác nhận lại qua rà soát — mọi `SlotCryptoError`/`KeyError`/`ValueError`/`TypeError` chỉ log `error_type`, không log message chứa plaintext). "Rejected request/peer chỉ audit count-worthy": `m4_signing_peer_rejected` log peer_uid (không phải content). "Transcript/response one-time/short-lived": đã do DB enforce (T10-04, TTL 60s + one-time capability) — không cần thêm ở tầng signing service | `app/services/pii/stage0p_signing_service.py` (cùng thay đổi T11-02, không có code riêng) |
| **T9-03** (P1 activation blocker) — không đổi từ Correction #11 | **KHÔNG sửa bằng code** — CA tiếp tục xác nhận đây là activation blocker. Khai báo lại known limitation, xem §6 | — (không có thay đổi code) |

## 2. Nguyên tắc sửa chung

T11-01 tiếp tục nguyên tắc "cleanup phải thật sự bảo vệ được resource, không chỉ tuyên bố bảo vệ"
(T9-01/T10-03) nhưng lộ ra 1 tầng sâu hơn: bảo vệ chỉ đúng nếu nó bắt được ĐÚNG LOẠI exception có
thể xảy ra tại điểm đó — `except Exception:` là 1 giả định NGẦM rằng mọi thất bại đều kế thừa
`Exception`, giả định này SAI đối với cancellation kể từ khi Python 3.8 tách `CancelledError` khỏi
`Exception` (chính vì lý do ngược lại: để code KHÔNG VÔ TÌNH nuốt cancellation qua `except
Exception:` — nhưng ở ĐÂY, code CẦN chủ động xử lý cancellation như 1 điều kiện dọn dẹp, không phải
để nó tự do lan truyền mà bỏ qua cleanup). Bài học: bất kỳ `try/except` nào đóng vai trò "resource
guard" (cam kết dọn dẹp resource TRƯỚC KHI truyền lỗi tiếp) phải cân nhắc `BaseException`, không
mặc định `Exception` — và AN TOÀN của việc mở rộng phạm vi bắt phụ thuộc HOÀN TOÀN vào việc nhánh
đó có `raise` lại vô điều kiện hay không (nếu có, mở rộng an toàn; nếu có logic "xử lý rồi tiếp
tục", mở rộng sẽ nuốt nhầm `KeyboardInterrupt`/`SystemExit`).

T11-02 áp dụng lại nguyên tắc T10-02 ("ranh giới bảo mật đòi hỏi cô lập THẬT, không phải tổ chức
code") sang 1 lớp: tách PROCESS đúng là điều kiện CẦN nhưng chưa ĐỦ cho 1 security boundary — nếu
kênh giao tiếp giữa 2 process không có access control, việc tách process chỉ dời "ai đọc được key"
từ "bất kỳ code nào trong process" sang "bất kỳ process nào mở được socket path", vẫn là 1 phạm vi
quá rộng. Access-control filesystem-level (private directory) + identity-level (`SO_PEERCRED`) +
resource-level (semaphore/timeout) là 3 lớp ĐỘC LẬP cùng thu hẹp phạm vi "ai dùng được service" từ
"bất kỳ ai" xuống "đúng 1 UID cụ thể, trong giới hạn tài nguyên xác định".

## 3. Bug tự phát hiện trong lúc triển khai (khai báo minh bạch)

1. **`asyncpg.Connection`/`PoolConnectionProxy` từ chối gán lại attribute method ở cấp INSTANCE**
   (`AttributeError: 'Connection' object attribute 'execute' is read-only`) — phát hiện khi viết
   test T11-01 (cần mô phỏng cancellation ĐÚNG 1 await cụ thể trong `__aenter__()`, vì `task.cancel()`
   thật không thể nhắm chính xác 1 trong 5 await liên tiếp chạy trong vài micro-giây). Thử monkeypatch
   `conn.execute`/`conn.fetchrow` ở cấp instance (cùng kiểu kỹ thuật dùng được cho object Python
   thường) thất bại ngay ở dòng gán đầu tiên. Xác nhận bằng thực nghiệm độc lập trước khi viết lại
   test: `asyncpg.Connection` (được implement với hạn chế attribute-assignment, khả năng do
   `__slots__`/Cython) từ chối MỌI gán instance-level cho method có sẵn. Sửa: patch ở CẤP CLASS
   (`asyncpg.Connection.execute`/`fetchrow`), nhưng CHỈ thực sự can thiệp khi `self is target_conn`
   (so sánh identity với CHÍNH physical `Connection` — lấy qua `PoolConnectionProxy._con` — đang
   test) — các connection khác đang sống song song trong CÙNG tiến trình (vd `admin`, các connection
   của kịch bản `[7]`) không bị ảnh hưởng dù dùng CHUNG 1 class bị patch tạm thời.
2. **Slow-loris test ([6] trong `signing_service_test.py`) crash `ConnectionResetError` thay vì
   PASS/FAIL có kiểm soát** — thiết kế ban đầu gửi từng byte trong vòng lặp `write()`/`drain()`
   không bọc try/except, giả định server sẽ chỉ đóng kết nối SAU KHI client gửi xong (hoặc timeout
   đọc phía client sẽ bắt được). Thực tế: server-side timeout (`_REQUEST_TIMEOUT_SECONDS=5.0`) kích
   hoạt VÀ đóng kết nối NGAY GIỮA lúc client đang trickle-write (~5s vào vòng lặp 6s) — lần
   `writer.drain()` tiếp theo ném `ConnectionResetError` (đúng hành vi, chứng minh timeout THẬT SỰ
   có hiệu lực, không phải lỗi test) — nhưng test không bọc lỗi này nên crash toàn bộ script thay vì
   ghi nhận PASS. Sửa: bọc vòng lặp trickle-write trong try/except `(ConnectionResetError,
   BrokenPipeError, OSError)`, coi kết nối bị reset SỚM là 1 kết quả HỢP LỆ (thậm chí còn mạnh hơn
   bằng chứng "đóng sau khi đọc đủ frame rồi timeout") thay vì lỗi test.
3. `PoolConnectionProxy` MỖI LẦN `pool.acquire()` trả về 1 object Proxy MỚI (bọc quanh CÙNG 1
   `Connection` vật lý thật, `._con`) — không phải cùng 1 object Proxy tái sử dụng như giả định ban
   đầu khi thiết kế `_CancelOnce` (dẫn tới phát hiện #1 ở trên khi cố lưu lại 1 tham chiếu Proxy để
   patch identity-based mà không nhận ra Proxy đổi object mỗi lần acquire — phải lấy `._con` để có
   1 tham chiếu ỔN ĐỊNH xuyên suốt nhiều lần acquire/release trên CÙNG connection vật lý, khớp với
   cách `pg_backend_pid()` đã được dùng làm bằng chứng "cùng connection" xuyên suốt các round trước).

## 4. Evidence chạy lần cuối (môi trường: `alpha3s-m4-test` + `alpha3s-m4-db` + `alpha3s-m4-redis`, network `m4net`; DB reset từ `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` rồi `migrate.py up` lại từ đầu ngay trước loạt chạy cuối)

| # | Lệnh | Exit | Kết quả |
|---|---|---|---|
| 1 | `DROP SCHEMA public CASCADE` + `redis-cli FLUSHALL` + `migrate.py up` (001..039 từ trạng thái sạch thật sự) | 0 | `OK 039_m4_stage0p`, postcondition PASS ngay lần đầu — round này không đổi migration |
| 2 | `m4_stage0p_pool_test.py` | 0 | RESULT: PASS — 16 nhóm kịch bản (giữ nguyên `[1]`-`[11]` + MỚI `[12]`-`[16]` T11-01, mỗi kịch bản mô phỏng `CancelledError` tại 1 trong 5 await của `__aenter__`: sau acquire/trong SET ROLE actor_binder, sau actor-binder role/trong safety-unpin, sau safety-unpin/trong pin_actor, sau pin/trong RESET ROLE, sau reset-role/trong SET ROLE business_role — CẢ 5 đều xác nhận CancelledError lan truyền ra ngoài KHÔNG bị nuốt, VÀ pool trả về connection SẠCH cho actor kế tiếp) |
| 3 | `m4_stage0p_signing_service_test.py` (MỚI, evidence riêng cho T11-02/T11-03) | 0 | RESULT: PASS — 8 kịch bản: `[1]` round-trip hợp lệ qua peer được phép, `[2]` peer UID không khớp bị từ chối trước khi đọc frame, `[3]` thư mục mode 0755 → service tự thoát lúc khởi động, `[4]` socket path là symlink có sẵn → service tự thoát, KHÔNG đụng file đích, `[5]` frame quá khổ bị từ chối ngay, `[6]` frame gửi chậm (slow-loris) bị chặn trong khoảng thời gian bị chặn (~5.0s, không treo vô thời hạn), `[7]` 20 request đồng thời (> `_MAX_CONCURRENT_REQUESTS=8`) đều thành công đúng, không trộn lẫn nội dung/digest giữa các request, `[8]` request thiếu trường bắt buộc từ peer hợp lệ → lỗi có cấu trúc, KHÔNG chứa plaintext |
| 4 | `m4_stage0p_kill_test.py` | 0 | RESULT: PASS — 9 kịch bản REV3 không đổi hành vi; xác nhận collector vẫn round-trip đúng qua signing service SAU KHI áp dụng access-control (thư mục socket riêng mode 0700 do helper tự tạo) |
| 5 | `m4_stage0p_sampling_test.py` | 0 | RESULT: PASS (10 kịch bản A-J) — cùng xác nhận round-trip qua signing service đã hardening |
| 6 | `m4_stage0p_permissions_test.py` | 0 | RESULT: PASS — không đổi (round này không chạm DB function/transcript schema) |
| 7 | `m4_stage0p_evaluation_test.py` | 0 | RESULT: PASS — không đổi |
| 8 | `pytest -q` (full) | 0 | **241 passed** (không đổi — T11-01/02/03 chỉ chạm pool-wrapper cancellation path/signing-service access-control, không chạm logic thuần đã có unit test) |
| 9 | `ruff check app/services/pii/ app/config.py scripts/m4_stage0p_*.py scripts/_stage0p_signing_service_helper.py tests/test_m4_*.py` | 0 | All checks passed (sau khi sửa 2 lỗi import-sort/unused-import ở `signing_service_test.py` mới, xem §3) |
| 10 | Xác nhận control OFF cuối mỗi script | — | `m4_stage0p_permissions_test.py`/`m4_stage0p_kill_test.py` tự xác nhận `capture_enabled=False` trước khi kết thúc |

Không có sự cố hạ tầng (Docker/DB) nào xảy ra trong round này.

## 5. Chưa/không cần sửa lại (theo đúng phạm vi CA giới hạn ở §6 Review #11)

- `T10-01` (signer tự derive canonical_digest/len/truncated) — CA xác nhận **CLOSED AT DEV/TEST
  CODE-DESIGN LEVEL**, exact delta round này KHÔNG chạm logic đó.
- `T10-04` (transcript lifetime/key-version schema) — CA xác nhận **CLOSED**, không chạm.

## 6. Known limitations (không đổi so với Correction #11 §6, cộng thêm)

30-33. Không đổi nội dung so với Correction #11 (T8-02 vẫn HMAC đối xứng, cần nâng KMS/HSM trước
    production; T9-01/T10-03 chỉ đóng đúng lớp truy cập qua `pinned_actor_session()`; T9-03 vẫn
    activation blocker theo khung CA; ngưỡng gate T4-05/T6-03 vẫn chờ PO decision record).
34. Không đổi — signing service vẫn chạy như subprocess trên CÙNG HOST với collector trong mô hình
    dev/test (Unix domain socket cục bộ). Round này (T11-02) đóng đúng phần "access control TRÊN
    CÙNG HOST" (private directory/mode, peer UID, resource limit) — KHÔNG thay đổi giới hạn kiến
    trúc "cùng host" đã ghi nhận: production cần network boundary/service credential/audit hạ tầng
    độc lập thật sự, không dùng lại Unix socket cục bộ dev/test này.
35. **MỚI — `_peer_uid()`/`_allowed_uid()` xác thực bằng UID CẤP HỆ ĐIỀU HÀNH (`SO_PEERCRED`),
    KHÔNG PHẢI 1 credential ứng dụng (token/certificate) độc lập với quyền truy cập filesystem/OS
    của host**. Trong mô hình dev/test 1 host hiện tại, collector và signing service CHẠY CÙNG UID
    (không có tách biệt user/service-account thật) — cơ chế này chặn được các tiến trình KHÁC trên
    CÙNG host (khác UID) nhưng KHÔNG chặn được 1 tiến trình ĐỘC HẠI chạy DƯỚI CÙNG UID với
    collector (vd 1 dependency bị compromise trong CHÍNH ứng dụng collector). Đây là giới hạn CỐ Ý
    của phạm vi dev/test 1 host (CA đã xác nhận "process separation hiện tại được chấp nhận như nền
    tảng" cho phạm vi này) — trước production, mô hình identity phải chuyển sang service
    account/container/namespace THẬT SỰ tách biệt (không chỉ UID logic trên cùng host).

## 7. Đề nghị

CA review Correction #12 đối chiếu `T11-01` (`except BaseException` an toàn vì luôn re-raise vô
điều kiện, đóng đúng khoảng cách cancellation-vs-Exception; 5 kịch bản injected-cancellation tại
từng await của `__aenter__`), `T11-02` (private directory/mode + symlink rejection + peer UID qua
`SO_PEERCRED` + concurrency/timeout server-side — 8 kịch bản access-control độc lập trong evidence
mới `signing_service_test.py`), và `T11-03` (đóng cùng T11-02 qua nhánh "signer verify caller
identity" CA cho phép, cộng xác nhận lại không log/trả raw content + audit count-worthy). `T9-03`
giữ nguyên trạng activation blocker theo đúng khung CA đã đặt — không xin đóng finding này round
này. Không xin quyền production-data-access/activation — gate đó vẫn tách riêng theo Design
Acceptance §6.
