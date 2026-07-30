"""I-B M4 Stage 0P — kill switch DONG cho raw sample capture (F-M4-0P-01B, CLOSED AT DESIGN LEVEL).

Thay vi doc `settings` (pydantic singleton nap MOT LAN luc process khoi dong — khong bao gio
thay doi trong doi process, xem app/config.py), control THAT nam trong 1 row DB
`m4_stage0p_control` (migration 039). Doc TUOI bang SELECT truoc MOI don vi ghi (Postgres READ
COMMITTED dam bao thay gia tri commit gan nhat tu session khac).

Fail-closed toan dien:
- Doc loi/timeout/khong co row -> coi la OFF (khong bao gio "gia dinh van ON khi khong chac").
- `statement_timeout` gan cho CHINH cau doc -> maximum stop latency co CO CHE THAT (khong phai
  uoc luong "mili-giay" suong) — CA yeu cau tuong minh o Review #3.

REV 2 (CA Technical Review #1, finding T1-01/T1-05): doc/ghi kill switch KHONG con la 2 buoc
Python rieng (SELECT roi UPDATE+INSERT do caller tu quan ly transaction). Ghi (bat/tat) gio CHI
qua ham SECURITY DEFINER `m4_stage0p_set_capture` (migration 039 §5d) — ham nay TU GIU
`pg_advisory_xact_lock(4013003)`, validate actor/approval, UPDATE + INSERT audit_log ATOMIC
trong 1 statement/transaction.

REV 3 (CA Technical Review #2, T2-05): bat ON gio doi hoi 1 approval record THAT trong bang
`m4_stage0p_capture_approvals` (dung purpose/window, chua thu hoi) — khong con chi kiem
`approval_ref` la chuoi khong rong. Tat OFF KHONG doi hoi approval record (chi can actor hop le)
— CA yeu cau ro OFF khong duoc bi chan vi approval het han/thu hoi.

REV 4 (CA Technical Review #3, T3-05): bang approval BAT BIEN (khong con cot `status` — truoc day
"flip" tu approved sang revoked tren CUNG row la bat kha thi vi approval_ref la PK va recorder
khong co UPDATE). Thu hoi la 1 SU KIEN RIENG (bang `m4_stage0p_capture_approval_revocations`).
`record_capture_approval()`/`revoke_capture_approval()` duoi day goi 2 ham SECURITY DEFINER
tuong ung — role `alpha3s_m4_approval_recorder` KHONG con INSERT/SELECT bang truc tiep nua, CHI
con EXECUTE 2 ham nay (ca hai tu xac thuc actor + audit BEN TRONG).

REV 5 (CA Technical Review #4, T4-04): CA chi ro `p_actor_staff_id` REV4 la tham so caller TU
KHAI — 1 nguoi giu chung 1 role DB co the mao danh BAT KY staff active nao. Sua: XOA HAN tham so
actor khoi `set_capture_enabled()`/`record_capture_approval()`/`revoke_capture_approval()` — actor
phai duoc "pin" vao session TRUOC (ham moi `pin_actor()`, goi tren connection da `SET ROLE
alpha3s_m4_actor_binder` — role RIENG, tach biet HOAN TOAN moi role nghiep vu khac). Sau khi pin,
GUC `alpha3s.m4_actor_staff_id` (session-scoped, KHONG phai LOCAL) sinh ton qua moi lan `SET ROLE`
tiep theo tren CUNG connection — cac ham nghiep vu tu doc actor tu day + kiem QUYEN CU THE
(`m4.stage0p.approve`/`operate`/`review`/`evaluate`) qua `m4_stage0p_require_pinned_actor()`.

`read_capture_enabled()` van la 1 SELECT doc-tuoi don gian, dung cho hien thi trang thai /
logging — KHONG dung ket qua nay lam co so quyet dinh doc plaintext (quyet dinh THAT nam ben
trong `m4_stage0p_fetch_message_content`, doc control SAU KHI da giu advisory lock — xem
stage0p_sampling.py).
"""

import json

CONTROL_READ_TIMEOUT_MS = 2000  # F-M4-0P-01B: statement_timeout that, khong phai uoc luong


class ControlChangeRejectedError(Exception):
    """m4_stage0p_set_capture tu choi (actor khong hop le / approval khong hop le / loi khac)."""


class ActorNotPinnedError(Exception):
    """m4_stage0p_pin_actor tu choi (staff_id khong ton tai/khong active), hoac 1 ham nghiep vu
    tu choi vi session chua pin actor / actor khong co quyen cu the (T4-04)."""


async def pin_actor(conn, *, staff_id: int) -> int:
    """REV5 T4-04: pin 1 staff_id vao session TRUOC khi goi bat ky ham nghiep vu M4 nao con lai
    (set_capture/record_approval/revoke_approval/seal_labels/complete_evaluation — tat ca gio doc
    actor tu day, KHONG con nhan actor tu tham so). `conn` PHAI xac thuc bang role RIENG
    `alpha3s_m4_actor_binder` (tach biet moi role nghiep vu — dai dien lop da xac thuc staff
    truoc do, vd HTTP session/JWT). Hieu luc session-scoped (`set_config(...,false)`) — sinh ton
    qua moi lan `SET ROLE` tiep theo tren CUNG connection, cho toi khi connection dong."""
    try:
        row = await conn.fetchrow("SELECT * FROM m4_stage0p_pin_actor($1)", staff_id)
    except Exception as e:  # noqa: BLE001
        _log("m4_actor_pin_rejected", staff_id=staff_id, error=str(e))
        raise ActorNotPinnedError(str(e)) from e
    _log("m4_actor_pinned", staff_id=staff_id)
    return row["pinned_staff_id"]


def _log(event: str, **fields) -> None:
    print("[m4-stage0p-control] " + json.dumps({"event": event, **fields},
                                                ensure_ascii=False, sort_keys=True))


async def read_capture_enabled(conn) -> bool:
    """Doc TUOI trang thai capture (tham khao/hien thi). Loi/timeout/thieu row -> False.

    `conn` phai la connection RIENG cho lan doc nay (khong tai dung transaction dang mo lau —
    de statement_timeout khong anh huong cau khac)."""
    try:
        row = await conn.fetchrow("SELECT capture_enabled FROM m4_stage0p_control WHERE id = 1",
                                  timeout=CONTROL_READ_TIMEOUT_MS / 1000)
    except Exception as e:  # noqa: BLE001 — fail closed la hop dong, khong phai loi can sua
        _log("m4_control_read_failed", error_type=type(e).__name__)
        return False
    if row is None:
        _log("m4_control_read_missing_row")
        return False
    return bool(row["capture_enabled"])


async def set_capture_enabled(conn, *, enabled: bool, approval_ref: str) -> bool:
    """Bat/tat control qua ham SECURITY DEFINER `m4_stage0p_set_capture` — PHAI goi tren
    connection xac thuc bang role `alpha3s_m4_control_plane` (KHONG con UPDATE truc tiep tren
    bang, KHONG doc/ghi bang `m4_stage0p_capture_approvals` truc tiep — T1-05/T2-05), VA da
    `pin_actor()` truoc do TREN CUNG connection (REV5 T4-04 — actor khong con la tham so, ham tu
    doc tu session + kiem quyen `m4.stage0p.operate`).

    Ham nay la 1 LENH DUY NHAT — fence (advisory lock), doc actor da pin + kiem quyen + (khi bat
    ON) validate approval record, UPDATE, va INSERT audit_log deu nam TRONG than ham SQL, atomic
    that su.

    Tra ve gia tri `before_enabled` (trang thai TRUOC khi doi) de caller log/so sanh.
    Nem `ControlChangeRejectedError` neu actor/quyen/approval khong hop le."""
    try:
        row = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_set_capture($1, $2)",
            enabled, approval_ref,
        )
    except Exception as e:  # noqa: BLE001 — bao boc loi DB (actor/approval khong hop le, v.v.) thanh loi ro rang cho caller
        _log("m4_control_change_rejected", enabled=enabled, error=str(e))
        raise ControlChangeRejectedError(str(e)) from e

    before_enabled = bool(row["before_enabled"])
    _log("m4_control_changed", enabled=enabled, before_enabled=before_enabled)
    return before_enabled


class ApprovalRejectedError(Exception):
    """m4_stage0p_record_approval/m4_stage0p_revoke_approval tu choi (actor khong hop le / du
    lieu khong hop le / da thu hoi truoc do / v.v.)."""


async def record_capture_approval(conn, *, approval_ref: str, requested_enabled: bool,
                                  valid_from, valid_until, note: str | None = None) -> str:
    """REV4 T3-05: ghi 1 approval record BAT BIEN qua ham SECURITY DEFINER
    `m4_stage0p_record_approval` — PHAI goi tren connection xac thuc bang role
    `alpha3s_m4_approval_recorder` (TACH BIET `alpha3s_m4_control_plane` — chong tu duyet cho
    chinh minh), VA da `pin_actor()` truoc do TREN CUNG connection (REV5 T4-04 — actor khong con
    la tham so, ham tu doc tu session + kiem quyen `m4.stage0p.approve`). Row nay KHONG con
    "status" — bat bien tu luc ghi; thu hoi la 1 su kien rieng, xem `revoke_capture_approval()`.

    `requested_enabled=True` danh dau record nay dung cho yeu cau BAT (ON) —
    `m4_stage0p_set_capture(ON)` chi chap nhan record co `requested_enabled=True`, con hieu luc,
    VA khong xuat hien trong bang revocations."""
    try:
        row = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_record_approval($1, $2, $3, $4, $5)",
            approval_ref, requested_enabled, valid_from, valid_until, note,
        )
    except Exception as e:  # noqa: BLE001 — boc loi DB thanh loi ro rang cho caller
        _log("m4_capture_approval_rejected", approval_ref=approval_ref, error=str(e))
        raise ApprovalRejectedError(str(e)) from e
    _log("m4_capture_approval_recorded", approval_ref=approval_ref,
        requested_enabled=requested_enabled)
    return row["approval_ref"]


async def revoke_capture_approval(conn, *, approval_ref: str, reason: str):
    """REV4 T3-05 (MOI); REV5 T4-04: thu hoi 1 approval record qua ham SECURITY DEFINER
    `m4_stage0p_revoke_approval` — ghi 1 row RIENG trong `m4_stage0p_capture_approval_revocations`
    (append-only, PK ngan thu hoi lap). Actor doc tu session da pin (khong con la tham so), kiem
    quyen `m4.stage0p.approve`. Sau khi goi thanh cong, `m4_stage0p_set_capture(ON)` voi
    `approval_ref` nay se BI TU CHOI ngay lap tuc (khong can cho het `valid_until`)."""
    try:
        row = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_revoke_approval($1, $2)",
            approval_ref, reason,
        )
    except Exception as e:  # noqa: BLE001
        _log("m4_capture_approval_revoke_rejected", approval_ref=approval_ref, error=str(e))
        raise ApprovalRejectedError(str(e)) from e
    _log("m4_capture_approval_revoked", approval_ref=approval_ref, reason=reason)
    return row["revoked_at"]
