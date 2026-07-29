"""I-B M4 Stage 0P — kill switch DONG cho raw sample capture (F-M4-0P-01B, CLOSED AT DESIGN LEVEL).

Thay vi doc `settings` (pydantic singleton nap MOT LAN luc process khoi dong — khong bao gio
thay doi trong doi process, xem app/config.py), control THAT nam trong 1 row DB
`m4_stage0p_control` (migration 039). Doc TUOI bang SELECT truoc MOI don vi ghi (Postgres READ
COMMITTED dam bao thay gia tri commit gan nhat tu session khac).

Fail-closed toan dien:
- Doc loi/timeout/khong co row -> coi la OFF (khong bao gio "gia dinh van ON khi khong chac").
- `statement_timeout` gan cho CHINH cau doc -> maximum stop latency co CO CHE THAT (khong phai
  uoc luong "mili-giay" suong) — CA yeu cau tuong minh o Review #3.

Ghi (bat/tat) PHAI qua role rieng `alpha3s_m4_control_plane` (F-M4-0P-01B acceptance criteria
muc 4) — KHONG dung cot `updated_by_note` (chi de tham khao) lam nguon tham quyen; tham quyen
THAT la audit_log record (actor_staff_id + approval_ref) ghi trong CUNG transaction voi UPDATE.
"""

import json

CONTROL_READ_TIMEOUT_MS = 2000  # F-M4-0P-01B: statement_timeout that, khong phai uoc luong


def _log(event: str, **fields) -> None:
    print("[m4-stage0p-control] " + json.dumps({"event": event, **fields},
                                                ensure_ascii=False, sort_keys=True))


async def read_capture_enabled(conn) -> bool:
    """Doc TUOI trang thai capture. Loi/timeout/thieu row -> False (fail closed).

    `conn` phai la connection RIENG cho lan doc nay (khong tai dung transaction dang mo lau —
    de statement_timeout khong anh huong cau khac). Goi truoc MOI don vi ghi (1 tin nhan)."""
    try:
        # asyncpg `timeout=` la client-side deadline cho DUNG cau nay — dung hon SET LOCAL
        # statement_timeout (SET LOCAL chi co hieu luc trong 1 transaction block ro rang; goi
        # rieng le nhu 2 statement khac nhau se KHONG mang tac dung sang cau SELECT ke tiep).
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
                              approval_ref: str) -> None:
    """Bat/tat control — PHAI goi tren connection xac thuc bang role
    `alpha3s_m4_control_plane` (migration 039 chi GRANT UPDATE cho role nay).

    Ghi audit_log TRONG CUNG transaction voi UPDATE (conn.transaction() do caller mo, giong
    convention command repository M1) — audit that bai se rollback ca UPDATE, khong co thay doi
    "am tham" nao khong duoc ghi lai. `approval_ref` la bat buoc (khong duoc rong) — day la
    tham chieu quyet dinh PO/CA cho phep bat/tat, KHONG phai tu Dev tu quyet."""
    if not approval_ref or not approval_ref.strip():
        raise ValueError("approval_ref bat buoc — khong duoc bat/tat control khi khong co tham chieu quyet dinh")

    before = await conn.fetchrow("SELECT capture_enabled FROM m4_stage0p_control WHERE id = 1")
    await conn.execute(
        "UPDATE m4_stage0p_control SET capture_enabled = $1, updated_at = now(), "
        "updated_by_note = $2 WHERE id = 1",
        enabled, f"staff:{actor_staff_id} ref:{approval_ref}",
    )
    await conn.execute(
        "INSERT INTO audit_log (actor_type, actor_staff_id, action, entity_type, entity_id, "
        "before, after, reason) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8)",
        "staff", actor_staff_id, "m4_capture_control_change", "m4_stage0p_control", "1",
        json.dumps({"capture_enabled": before["capture_enabled"] if before else None}),
        json.dumps({"capture_enabled": enabled}),
        approval_ref,
    )
    _log("m4_control_changed", enabled=enabled, actor_staff_id=actor_staff_id)
