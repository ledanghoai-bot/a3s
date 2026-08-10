#!/usr/bin/env python
"""I-B M4 Stage 0P — provisioning PIN nghiep vu (`m4_stage0p_actor_credentials.pin_secret_hash`)
qua single-use bootstrap token, dap lai
`PHASE1B-M4-REHEARSAL-READINESS-SNAPSHOT-REVIEW-1-VI.md` F-M4-PIN-R1-01,
`PHASE1B-M4-REHEARSAL-PIN-TOOL-REVIEW-2-VI.md` F-M4-PIN-R2-01/02/03, va
`PHASE1B-M4-REHEARSAL-PIN-TOOL-REVIEW-3-VI.md` F-M4-PIN-R3-01.

REV4 (dap CA Review #3 tren PR #7) — F-M4-PIN-R3-01: revoke/het han approval SAU khi bind
KHONG vo hieu hoa duoc token da bind, vi row token khong tham chieu approval nao va provision-pin
chi kiem lai chinh no (consumed_at/expires_at), khong join lai approval. Sua bang migration 042
them cot `approval_id` (NOT NULL, FK) vao `m4_stage0p_pin_bootstrap_tokens`:

- `bind-token`: `expires_at` gio la `MIN(now + ttl-minutes yeu cau, approval.valid_until)` —
  token khong the song lau hon chinh approval cho phep no ton tai; neu approval con lai duoi 1
  phut thi tu choi bind (khong du thoi gian toi thieu).
- `provision-pin`: buoc consume (trong `async with conn.transaction()`) gio JOIN + `FOR UPDATE`
  CA token LAN approval TRONG CUNG 1 cau lenh, yeu cau approval van CHUA revoke VA con trong
  validity window **TAI THOI DIEM CONSUME** (khong chi tai thoi diem bind truoc do). `FOR UPDATE`
  khoa ca 2 row: neu `revoke-bind-approval` chay dong thoi tren cung approval, no se bi CHAN toi
  khi transaction nay commit/rollback (Postgres row-level lock) — ai lay lock truoc thi thang,
  khong con trang thai vua-revoked-vua-provisioned.

REV3 (dap CA Review #2 tren PR #7):

1. `generate-token` (principal TU chay tren CHINH session cua ho, KHONG can DB): sinh 1 token
   ngau nhien (32 byte, `secrets.token_urlsafe`) hoan toan CUC BO -- in ra 2 gia tri TACH BIET:
   raw token (principal TU GIU, dung 1 lan o buoc `provision-pin` sau nay) va sha256(token) (GIA
   TRI DUY NHAT principal dua cho Dev/admin de bind -- KHONG PHAI secret, khong the dung nguoc
   lai de suy ra raw token hay PIN). Dap F-M4-PIN-R2-01: Dev/admin KHONG BAO GIO sinh ra hay
   nhin thay raw token duoi bat ky hinh thuc nao trong toan bo quy trinh.
2. `record-bind-approval` (PO / nguoi PO uy quyen TU chay, ngoai luong): ghi 1 approval record
   RIENG BIET (bang moi `m4_stage0p_pin_bind_approvals`, migration 041) co approval_ref/
   timestamp/validity-window/kha nang thu hoi, BUOC voi 1 target_staff_id cu the -- TRUOC va
   TACH BIET khoi buoc bind token. Day la "approval-bound request record PO ky nhan" CA yeu cau
   thay the cho 1 CLI flag tu do khai `--issued-by` (F-M4-PIN-R2-02). GIOI HAN TRUNG THUC: vi
   moi truong CLI nay KHONG co authenticated session/SSO cho thao tac van hanh (va day CHINH LA
   cong cu bootstrap PIN dau tien nen khong the dung pin_actor() de xac thuc nguoc - chicken-
   and-egg), code KHONG the chung minh bang mat ma ai THAT SU go lenh nay -- day la 1 audit
   trail co the thu hoi, dua tren ky luat quy trinh (PO/nguoi duoc PO uy quyen TU chay tren SSH
   session cua ho), CUNG mo hinh CA da chap nhan cho `record-approval`/PO Decision Record, KHONG
   phai 1 khang dinh danh tinh duoc ma hoa.
3. `revoke-bind-approval`: thu hoi 1 approval record neu ghi nham/doi y -- bind-token se tu choi
   ngay lap tuc sau do (khong can cho het valid_until).
4. `bind-token` (Dev/admin chay, CHI nhan HASH -- khong bao gio nhan/sinh raw token): yeu cau
   `--approval-id` tro toi 1 approval record CON HIEU LUC (chua thu hoi, dung target_staff_id,
   trong validity window) -- `issued_by` duoc SERVER-SIDE resolve TU chinh approval do, khong
   con la tham so CLI. `--ttl-minutes` bi CHAN CUNG 1-30 phut ca o CLI lan DB CHECK
   (F-M4-PIN-R2-03, migration 041 `m4_pin_bootstrap_ttl_bounded`).
5. `provision-pin` (nguoi dam nhan vai tro TU chay, tren chinh SSH session cua ho) -- KHONG DOI
   so voi REV2: chi hoi token (getpass, khong echo) -- staff_id duoc SERVER-SIDE RESOLVE tu
   chinh token do. Token tieu thu 1 lan, CUNG 1 transaction voi viec ghi PIN -- that bai xac
   nhan PIN (mismatch/qua ngan) KHONG tieu thu token (cho phep thu lai voi CUNG token); chi
   thanh cong that su moi tieu thu.

Thiet ke bao mat con lai giu nguyen tu REV1/REV2: khong CLI argument nao mang PIN, doc qua
`getpass.getpass()`, `del` bien PIN ngay sau dung, output CHI xac nhan row/metadata ton tai
(KHONG BAO GIO in `pin_secret_hash`).

QUAN TRONG: KHONG chay file nay tren production truoc khi PR merge/deploy qua dung merge/
deploy-dormant gate rieng (F-M4-PIN-R1-02) -- chay file untracked tren VPS bi CA tu choi ro rang.

Chay (principal, TU chay tren chinh session cua ho, KHONG can DATABASE_URL):
    python scripts/m4_stage0p_provision_pin.py generate-token

Chay (F-M4-PIN-R3-02: cho lan rehearsal synthetic-only nay, PO chi dinh staff_id=3
(`m4-approval-recorder`) la nguoi TU chay record-bind-approval cho CA BA target 3/4/5 -- KHONG
dung ID nao khac, approval_ref rieng cho tung target, khong nhap nhang):
    docker exec -it alpha3s-api-1 python scripts/m4_stage0p_provision_pin.py \\
        record-bind-approval --target-staff-id 5 --recorded-by 3 \\
        --approval-ref m4-pin-bind-5-20260806-01 --valid-minutes 60

Chay (Dev/admin, CHI nhan hash -- khong bao gio nhan raw token):
    docker exec -it alpha3s-api-1 python scripts/m4_stage0p_provision_pin.py bind-token \\
        --token-hash <hash-tu-principal> --target-staff-id 5 --approval-id 1 --ttl-minutes 15

Chay (nguoi dam nhan vai tro, TU chay tren chinh SSH session cua ho):
    docker exec -it alpha3s-api-1 python scripts/m4_stage0p_provision_pin.py provision-pin
"""

import argparse
import asyncio
import getpass
import hashlib
import re
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# F-EX-B2-02: normalization DSN nay gio nam trong 1 module dung CHUNG (m4_dsn_utils.py) voi
# scripts/m4_stage0p_rehearsal_runner.py - truoc day moi tool co 1 ban sao rieng cua CUNG 1 logic,
# dan toi runner bi bo sot khi PIN tool duoc sua o PR #9. Alias lai ten cu (_db_url) de khong doi
# API noi bo hien co (`_db_url()` van goi duoc y het truoc day).
from m4_dsn_utils import normalized_db_url as _db_url  # noqa: E402

MIN_PIN_LEN = 8
TOKEN_TTL_MIN_MINUTES = 1
TOKEN_TTL_MAX_MINUTES = 30
APPROVAL_TTL_MIN_MINUTES = 1
APPROVAL_TTL_MAX_MINUTES = 1440
_TOKEN_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_token() -> int:
    """F-M4-PIN-R2-01: chay HOAN TOAN cuc bo, KHONG mo ket noi DB -- Dev/admin khong the chan
    duoc/nhin thay buoc nay du co quyen truy cap DB the nao."""
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    print("Token da sinh CUC BO tren may/session nay -- KHONG ghi vao dau, KHONG gui qua bat ky")
    print("kenh nao ngoai 2 buoc duoi day.")
    print()
    print("[1] GIU LAI rieng cho minh (dung 1 LAN DUY NHAT o buoc `provision-pin` sau nay -- ")
    print("    KHONG dua cho Dev/admin hay bat ky ai khac duoi bat ky hinh thuc nao):")
    print(f"TOKEN={token}")
    print()
    print("[2] Dua CHINH XAC gia tri nay (chi gia tri nay) cho Dev/admin de ho `bind-token` --")
    print("    day la sha256 hash, KHONG the dung de suy nguoc ra token o [1] hay PIN cua ban:")
    print(f"TOKEN_HASH={token_hash}")
    del token
    return 0


async def record_bind_approval(target_staff_id: int, recorded_by: int, approval_ref: str,
                                valid_minutes: int) -> int:
    if not (APPROVAL_TTL_MIN_MINUTES <= valid_minutes <= APPROVAL_TTL_MAX_MINUTES):
        print(f"LOI: valid-minutes phai trong khoang [{APPROVAL_TTL_MIN_MINUTES}, "
              f"{APPROVAL_TTL_MAX_MINUTES}]", file=sys.stderr)
        return 1
    conn = await asyncpg.connect(_db_url())
    try:
        target = await conn.fetchrow(
            "SELECT id, username, is_active FROM staff_users WHERE id = $1", target_staff_id)
        if target is None or not target["is_active"]:
            print(f"LOI: target-staff-id {target_staff_id} khong ton tai/khong active",
                  file=sys.stderr)
            return 1
        recorder = await conn.fetchrow(
            "SELECT id, username, is_active FROM staff_users WHERE id = $1", recorded_by)
        if recorder is None or not recorder["is_active"]:
            print(f"LOI: recorded-by {recorded_by} khong ton tai/khong active", file=sys.stderr)
            return 1

        valid_from = datetime.now(timezone.utc)
        valid_until = valid_from + timedelta(minutes=valid_minutes)
        row = await conn.fetchrow(
            "INSERT INTO m4_stage0p_pin_bind_approvals "
            "  (approval_ref, target_staff_id, recorded_by, valid_from, valid_until) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            approval_ref, target_staff_id, recorded_by, valid_from, valid_until)

        print(f"Approval id={row['id']} da ghi: approval_ref={approval_ref!r} "
              f"target_staff_id={target_staff_id} (username={target['username']!r}) "
              f"recorded_by={recorded_by} (username={recorder['username']!r}) "
              f"valid_from={valid_from.isoformat()} valid_until={valid_until.isoformat()}")
        print(f"Dua approval id={row['id']} nay cho Dev/admin de ho `bind-token "
              f"--approval-id {row['id']}` -- id KHONG PHAI secret.")
        return 0
    finally:
        await conn.close()


async def revoke_bind_approval(approval_id: int, reason: str) -> int:
    conn = await asyncpg.connect(_db_url())
    try:
        row = await conn.fetchrow(
            "UPDATE m4_stage0p_pin_bind_approvals SET revoked_at = now(), revoke_reason = $2 "
            "WHERE id = $1 AND revoked_at IS NULL RETURNING id",
            approval_id, reason)
        if row is None:
            print(f"LOI: approval id={approval_id} khong ton tai hoac da bi thu hoi truoc do",
                  file=sys.stderr)
            return 1
        print(f"Approval id={approval_id} da bi thu hoi. bind-token voi approval nay se bi "
              f"tu choi ngay lap tuc.")
        return 0
    finally:
        await conn.close()


async def bind_token(token_hash: str, target_staff_id: int, approval_id: int,
                      ttl_minutes: int) -> int:
    """F-M4-PIN-R2-01: CHI nhan token_hash (da duoc principal hash san) -- KHONG BAO GIO sinh
    hay nhan raw token o day. F-M4-PIN-R2-02: issued_by resolve TU approval record, khong con
    la CLI flag. F-M4-PIN-R2-03: ttl-minutes CHAN CUNG [1, 30]."""
    if not _TOKEN_HASH_RE.match(token_hash):
        print("LOI: token-hash phai la chuoi sha256 hex (64 ky tu 0-9a-f) - tu choi truoc khi "
              "cham DB", file=sys.stderr)
        return 1
    if not (TOKEN_TTL_MIN_MINUTES <= ttl_minutes <= TOKEN_TTL_MAX_MINUTES):
        print(f"LOI: ttl-minutes phai trong khoang [{TOKEN_TTL_MIN_MINUTES}, "
              f"{TOKEN_TTL_MAX_MINUTES}]", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(_db_url())
    try:
        approval = await conn.fetchrow(
            "SELECT id, recorded_by, target_staff_id, valid_until FROM m4_stage0p_pin_bind_approvals "
            "WHERE id = $1 AND target_staff_id = $2 AND revoked_at IS NULL "
            "AND valid_from <= now() AND now() < valid_until",
            approval_id, target_staff_id)
        if approval is None:
            print("LOI: khong tim thay approval con hieu luc khop approval-id VA "
                  "target-staff-id nay (co the da het han/bi thu hoi/sai id) - huy, khong bind",
                  file=sys.stderr)
            return 1
        issued_by = approval["recorded_by"]

        target = await conn.fetchrow(
            "SELECT id, username, is_active FROM staff_users WHERE id = $1", target_staff_id)
        if target is None or not target["is_active"]:
            print(f"LOI: target-staff-id {target_staff_id} khong ton tai/khong active",
                  file=sys.stderr)
            return 1

        issued_at = datetime.now(timezone.utc)
        # F-M4-PIN-R3-01: token khong duoc song lau hon approval cho phep no ton tai - cap
        # expires_at o MIN(requested TTL, approval.valid_until), khong chi requested TTL.
        expires_at = min(issued_at + timedelta(minutes=ttl_minutes), approval["valid_until"])
        if expires_at < issued_at + timedelta(minutes=TOKEN_TTL_MIN_MINUTES):
            print("LOI: approval sap het han (con lai duoi 1 phut) - khong con du thoi gian "
                  "toi thieu de bind token, huy (khong tao token row)", file=sys.stderr)
            return 1

        await conn.execute(
            "INSERT INTO m4_stage0p_pin_bootstrap_tokens "
            "  (token_hash, staff_id, issued_by, approval_id, issued_at, expires_at) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            token_hash, target_staff_id, issued_by, approval_id, issued_at, expires_at)

        print(f"Token da bind cho staff_id={target_staff_id} username={target['username']!r}, "
              f"issued_by={issued_by} (resolve tu approval id={approval_id}), "
              f"het han luc {expires_at.isoformat()} "
              f"(min cua {ttl_minutes} phut yeu cau va approval.valid_until).")
        print("Dev/admin KHONG nhin thay/sinh ra raw token o buoc nay - chi hash duoc dung.")
        return 0
    finally:
        await conn.close()


async def provision_pin(*, token_reader=getpass.getpass, pin_reader=getpass.getpass) -> int:
    conn = await asyncpg.connect(_db_url())
    try:
        token = token_reader("Nhap token da duoc cap (khong hien thi khi go): ")
        token_hash = _hash_token(token)
        del token

        # F-M4-PIN-R3-01: kiem ca token LAN approval lien quan ngay tu buoc doc som (chua lock)
        # de bao loi ro rang som - buoc consume o duoi se kiem lai CO LOCK, day chi la UX.
        token_row = await conn.fetchrow(
            "SELECT t.staff_id FROM m4_stage0p_pin_bootstrap_tokens t "
            "JOIN m4_stage0p_pin_bind_approvals a ON a.id = t.approval_id "
            "WHERE t.token_hash = $1 AND t.consumed_at IS NULL AND t.expires_at > now() "
            "AND a.revoked_at IS NULL AND now() < a.valid_until",
            token_hash)
        if token_row is None:
            print("LOI: token khong hop le, da dung, het han, hoac approval lien quan da bi "
                  "thu hoi/het han - huy", file=sys.stderr)
            return 1
        staff_id = token_row["staff_id"]

        staff = await conn.fetchrow(
            "SELECT username, is_active FROM staff_users WHERE id = $1", staff_id)
        if staff is None or not staff["is_active"]:
            print(f"LOI: staff_id {staff_id} (tu token) khong ton tai/khong active", file=sys.stderr)
            return 1

        print(f"Token hop le - dang dat PIN M4 cho staff_id={staff_id} username={staff['username']!r}")
        print("PIN se KHONG hien thi khi go va KHONG luu shell history.")
        pin = pin_reader("Nhap PIN M4 moi (>=8 ky tu): ")
        pin_confirm = pin_reader("Nhap lai de xac nhan: ")

        if pin != pin_confirm:
            print("LOI: 2 lan nhap khong khop - huy, KHONG ghi gi (token VAN con dung duoc lai)",
                  file=sys.stderr)
            return 1
        if len(pin) < MIN_PIN_LEN:
            print(f"LOI: PIN can toi thieu {MIN_PIN_LEN} ky tu - huy, KHONG ghi gi "
                  "(token VAN con dung duoc lai)", file=sys.stderr)
            return 1

        async with conn.transaction():
            # F-M4-PIN-R3-01: JOIN + FOR UPDATE ca token LAN approval TRONG CUNG transaction voi
            # viec tieu thu — day la lan kiem CUOI CUNG, co gia tri, ngay truoc khi ghi PIN.
            # FOR UPDATE khoa CA HAI row: neu 1 revoke-bind-approval dang chay dong thoi tren
            # CUNG approval nay, no se BI CHAN toi khi transaction nay commit/rollback (Postgres
            # row-level lock tren UPDATE) — ai lay lock truoc thi thang, khong con trang thai
            # nua-vua-revoked-nua-vua-provisioned. Neu revoke da commit TRUOC khi ta toi day,
            # dieu kien a.revoked_at IS NULL don gian khong con dung, locked=None, tu choi sach.
            locked = await conn.fetchrow(
                "SELECT t.staff_id FROM m4_stage0p_pin_bootstrap_tokens t "
                "JOIN m4_stage0p_pin_bind_approvals a ON a.id = t.approval_id "
                "WHERE t.token_hash = $1 AND t.consumed_at IS NULL AND t.expires_at > now() "
                "AND a.revoked_at IS NULL AND now() < a.valid_until "
                "FOR UPDATE OF t, a",
                token_hash)
            if locked is None:
                print("LOI: token vua bi dung/het han, hoac approval lien quan vua bi thu hoi/"
                      "het han o noi khac giua chung (race) - huy", file=sys.stderr)
                return 1

            # Tieu thu token VA ghi PIN trong CUNG 1 transaction — token CHI thuc su "dung 1
            # lan" khi lan dung do THANH CONG; mismatch/qua ngan o tren khong cham toi day nen
            # token chua bao gio bi tieu thu trong cac truong hop do. WHERE ben duoi la 1 lop
            # bao ve them (defense-in-depth) — tai day ta da giu lock nen ve ly thuyet luon khop.
            consumed = await conn.fetchrow(
                "UPDATE m4_stage0p_pin_bootstrap_tokens SET consumed_at = now() "
                "WHERE token_hash = $1 AND consumed_at IS NULL AND expires_at > now() "
                "RETURNING staff_id", token_hash)
            if consumed is None:
                print("LOI: token vua bi dung/het han o noi khac giua chung (race) - huy",
                      file=sys.stderr)
                return 1
            await conn.execute(
                "INSERT INTO m4_stage0p_actor_credentials "
                "  (staff_id, pin_secret_hash, provisioned_by) "
                "VALUES ($1, crypt($2, gen_salt('bf')), $1) "
                "ON CONFLICT (staff_id) DO UPDATE SET "
                "  pin_secret_hash = crypt($2, gen_salt('bf')), "
                "  failed_attempts = 0, locked_until = NULL, provisioned_at = now()",
                staff_id, pin)
        del pin, pin_confirm

        row = await conn.fetchrow(
            "SELECT staff_id, provisioned_at, failed_attempts, locked_until "
            "FROM m4_stage0p_actor_credentials WHERE staff_id = $1", staff_id)
        print(f"OK - credential row ton tai: staff_id={row['staff_id']} "
              f"provisioned_at={row['provisioned_at'].isoformat()} "
              f"failed_attempts={row['failed_attempts']} locked_until={row['locked_until']}")
        print("(KHONG in pin_secret_hash - chi xac nhan row/metadata, dung yeu cau P-M4-PA-02)")
        return 0
    finally:
        await conn.close()


REVOKE_CREDENTIAL_PERMISSION = "m4.stage0p.approve"
_REASON_MAX_LEN = 500


async def revoke_credential(target_staff_id: int, actor_staff_id: int, reason: str) -> int:
    """F-EX-B2-03 (Amendment 07 Execution Blocker 1): supported, audited, fail-closed cach de
    thu hoi 1 PIN credential da provision - khong con raw SQL ad hoc. XOA HANG (khong chi danh
    dau) vi bang m4_stage0p_actor_credentials khong co cot "revoked"/"active" va them cot se can
    1 migration (CA yeu cau tranh migration neu khong that su can) - `m4_stage0p_pin_actor()` da
    tu RAISE EXCEPTION ro rang ("chua duoc provisioning pin_secret") khi khong tim thay hang,
    nen xoa hang dat dung hieu qua "revoked" ma khong can schema change. Ghi 1 dong vao
    `audit_log` (bang da co san, khong migration moi) de giu vet kiem toan ben ngoai bang M4 du
    hang credential da bi xoa hoan toan.

    F-RCR-R1-01 (Runner DSN/Credential Revocation Review 1): actor PHAI co quyen
    `m4.stage0p.approve` (`m4_stage0p_staff_permissions`) moi duoc revoke - truoc day chi kiem
    actor ton tai/active, nghia la BAT KY active staff nao cung tu revoke duoc credential cua
    nguoi khac. Target KHONG con bat buoc active - staff da bi deactivate lai CANG can duoc dat
    ra cleanup, khong phai truong hop ngoai le.

    F-RCR-R1-04: `reason` phai duoc trim va khong duoc rong sau trim, gioi han do dai hop ly
    (chong audit_log bi lam day bang input khong gioi han) - tu choi TRUOC khi cham DB."""
    reason = reason.strip()
    if not reason:
        print("LOI: --reason khong duoc rong/toan khoang trang sau khi trim - tu choi truoc "
              "khi ket noi DB", file=sys.stderr)
        return 1
    if len(reason) > _REASON_MAX_LEN:
        print(f"LOI: --reason vuot qua {_REASON_MAX_LEN} ky tu - tu choi truoc khi ket noi DB",
              file=sys.stderr)
        return 1

    conn = await asyncpg.connect(_db_url())
    try:
        target = await conn.fetchrow(
            "SELECT id, username FROM staff_users WHERE id = $1", target_staff_id)
        if target is None:
            print(f"LOI: target-staff-id {target_staff_id} khong ton tai", file=sys.stderr)
            return 1
        actor = await conn.fetchrow(
            "SELECT id, username, is_active FROM staff_users WHERE id = $1", actor_staff_id)
        if actor is None or not actor["is_active"]:
            print(f"LOI: actor-staff-id {actor_staff_id} khong ton tai/khong active",
                  file=sys.stderr)
            return 1
        has_permission = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM m4_stage0p_staff_permissions "
            "WHERE staff_id = $1 AND permission = $2)",
            actor_staff_id, REVOKE_CREDENTIAL_PERMISSION)
        if not has_permission:
            print(f"LOI: actor-staff-id {actor_staff_id} khong co quyen "
                  f"{REVOKE_CREDENTIAL_PERMISSION!r} - tu choi", file=sys.stderr)
            return 1

        async with conn.transaction():
            deleted = await conn.fetchrow(
                "DELETE FROM m4_stage0p_actor_credentials WHERE staff_id = $1 "
                "RETURNING staff_id", target_staff_id)
            await conn.execute(
                "INSERT INTO audit_log "
                "  (actor_type, actor_staff_id, action, entity_type, entity_id, reason) "
                "VALUES ('staff', $1, 'm4_stage0p.pin_credential.revoke', "
                "        'm4_stage0p_actor_credentials', $2, $3)",
                actor_staff_id, str(target_staff_id), reason)

        if deleted is None:
            print(f"Khong co credential nao cho staff_id={target_staff_id} (da revoke truoc do "
                  "hoac chua tung provision) - idempotent, coi la thanh cong.")
        else:
            print(f"Credential cho staff_id={target_staff_id} (username={target['username']!r}) "
                  f"da bi xoa boi actor_staff_id={actor_staff_id} "
                  f"(username={actor['username']!r}). Ly do da ghi vao audit_log.")
        print("(KHONG in pin_secret_hash - hang da bi xoa hoan toan, khong con gi de in)")
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dat PIN M4 nghiep vu qua single-use bootstrap token, principal tu sinh "
                    "token + approval-bound bind ceremony (F-M4-PIN-R2-01/02/03).")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate-token",
                    help="Principal TU chay tren session cua ho - sinh token cuc bo, khong DB")

    p_approve = sub.add_parser(
        "record-bind-approval",
        help="PO/nguoi PO uy quyen TU chay - ghi 1 approval record rieng biet cho 1 target")
    p_approve.add_argument("--target-staff-id", type=int, required=True)
    p_approve.add_argument("--recorded-by", type=int, required=True)
    p_approve.add_argument("--approval-ref", type=str, required=True)
    p_approve.add_argument("--valid-minutes", type=int, default=60)

    p_revoke = sub.add_parser("revoke-bind-approval", help="Thu hoi 1 approval record da ghi")
    p_revoke.add_argument("--approval-id", type=int, required=True)
    p_revoke.add_argument("--reason", type=str, required=True)

    p_bind = sub.add_parser(
        "bind-token",
        help="Dev/admin chay - CHI nhan token-hash (khong bao gio nhan/sinh raw token)")
    p_bind.add_argument("--token-hash", type=str, required=True)
    p_bind.add_argument("--target-staff-id", type=int, required=True)
    p_bind.add_argument("--approval-id", type=int, required=True)
    p_bind.add_argument("--ttl-minutes", type=int, default=15)

    sub.add_parser("provision-pin", help="Nguoi dam nhan vai tro TU chay - chi hoi token + PIN")

    p_revoke_cred = sub.add_parser(
        "revoke-credential",
        help="F-EX-B2-03: thu hoi/xoa 1 PIN credential da provision (supported, audited, "
             "idempotent, khong raw SQL)")
    p_revoke_cred.add_argument("--target-staff-id", type=int, required=True)
    p_revoke_cred.add_argument("--actor-staff-id", type=int, required=True)
    p_revoke_cred.add_argument("--reason", type=str, required=True)

    args = parser.parse_args()
    if args.command == "generate-token":
        return generate_token()
    if args.command == "record-bind-approval":
        return asyncio.run(record_bind_approval(
            args.target_staff_id, args.recorded_by, args.approval_ref, args.valid_minutes))
    if args.command == "revoke-bind-approval":
        return asyncio.run(revoke_bind_approval(args.approval_id, args.reason))
    if args.command == "bind-token":
        return asyncio.run(bind_token(
            args.token_hash, args.target_staff_id, args.approval_id, args.ttl_minutes))
    if args.command == "revoke-credential":
        return asyncio.run(revoke_credential(
            args.target_staff_id, args.actor_staff_id, args.reason))
    return asyncio.run(provision_pin())


if __name__ == "__main__":
    sys.exit(main())
