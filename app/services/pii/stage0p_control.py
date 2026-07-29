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
qua ham SECURITY DEFINER `m4_stage0p_set_capture` (migration 039 §5b) — ham nay TU GIU
`pg_advisory_xact_lock(4013003)` (CUNG lock key voi `m4_stage0p_fetch_next_message`), validate
actor/approval_ref, UPDATE + INSERT audit_log ATOMIC trong 1 statement/transaction. Khong con
phu thuoc caller nho mo transaction dung cach (T1-05 goc: "caller dung autocommit co the commit
control change truoc, sau do audit loi rieng, tao thay doi khong duoc audit").

`read_capture_enabled()` van la 1 SELECT doc-tuoi don gian, dung cho hien thi trang thai /
logging — KHONG dung ket qua nay lam co so quyet dinh doc plaintext (quyet dinh THAT nam ben
trong `m4_stage0p_fetch_next_message`, doc control SAU KHI da giu advisory lock — xem
stage0p_sampling.py).
"""

import json

CONTROL_READ_TIMEOUT_MS = 2000  # F-M4-0P-01B: statement_timeout that, khong phai uoc luong


class ControlChangeRejectedError(Exception):
    """m4_stage0p_set_capture tu choi (actor khong hop le / approval_ref rong / loi khac)."""


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


async def set_capture_enabled(conn, *, enabled: bool, actor_staff_id: int,
                              approval_ref: str) -> bool:
    """Bat/tat control qua ham SECURITY DEFINER `m4_stage0p_set_capture` — PHAI goi tren
    connection xac thuc bang role `alpha3s_m4_control_plane` (migration 039 chi GRANT EXECUTE
    cho role nay, KHONG con UPDATE truc tiep tren bang — T1-05).

    Ham nay la 1 LENH DUY NHAT (khong phai caller tu quan ly transaction nhieu buoc) — fence
    (advisory lock), validate actor/approval_ref, UPDATE, va INSERT audit_log deu nam TRONG
    than ham SQL, atomic that su boi transaction cua chinh statement goi ham nay.

    Tra ve gia tri `before_enabled` (trang thai TRUOC khi doi) de caller log/so sanh.
    Nem `ControlChangeRejectedError` neu actor khong hop le hoac approval_ref rong."""
    if not approval_ref or not approval_ref.strip():
        raise ControlChangeRejectedError(
            "approval_ref bat buoc — khong duoc bat/tat control khi khong co tham chieu quyet dinh")
    try:
        row = await conn.fetchrow(
            "SELECT * FROM m4_stage0p_set_capture($1, $2, $3)",
            enabled, actor_staff_id, approval_ref,
        )
    except Exception as e:  # noqa: BLE001 — bao boc loi DB (actor khong active, v.v.) thanh loi ro rang cho caller
        _log("m4_control_change_rejected", enabled=enabled, actor_staff_id=actor_staff_id,
             error=str(e))
        raise ControlChangeRejectedError(str(e)) from e

    before_enabled = bool(row["before_enabled"])
    _log("m4_control_changed", enabled=enabled, actor_staff_id=actor_staff_id,
        before_enabled=before_enabled)
    return before_enabled
