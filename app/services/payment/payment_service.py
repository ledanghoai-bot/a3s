"""M6 payment service — amount_due / evidence / status (CA Directive 265 + Review 266).

Tach 3 nghia: amount_due_vnd (can thu) / payment_events (evidence append-only) / amount_received_vnd (TONG shop
thuc nhan, cumulative) + status.
Transitions:
- BANK_TRANSFER: awaiting -> reported (customer_reported) -> [shop_confirmed_received -> settle].
- COD: awaiting -> collected (cod_collected) -> [reconciled -> settle].
- settle: amount_received == due -> confirmed/reconciled ; != due (THIEU hoac THUA) -> 'discrepancy' (CHO staff).
266-03: command_key -> DB-atomic idempotency (replay khong ghi/cong lai) + reference chong ghi lai CUNG chung tu.
266-04: sync_amount_due chi khi CHUA settled; neu da settled ma due doi -> 'discrepancy' (obligation phai xac nhan lai).
266-05: excess CUNG chua auto-confirm; correction BAT BUOC reason + corrects_event_id, dieu chinh amount_received.
266-08: eta_start set 1 lan (COD confirm / transfer received).
"""
from __future__ import annotations

import hashlib

from app.services import audit_service

METHODS = ("COD", "BANK_TRANSFER")
_SETTLED = {"confirmed", "reconciled"}


def _fingerprint(*parts) -> str:
    """CA 267-02: fingerprint on-dinh cua payload -> phat hien cung command_key nhung KHAC payload."""
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PaymentError(Exception):
    """Fail-closed. Khong leak secret."""


# CA 324-01 §3.3: prefix compatibility CHI cho duong module-OFF (dormant baseline) — giu hanh vi CK M6/M7 pre-322.
# KHONG dung lam nguon cho module-ON hoac SePay matching (matching theo snapshot instruction). Khi Settings module ON,
# prefix effective CHI den tu Dashboard (code_prefix cua SePay integration).
_LEGACY_COMPAT_PREFIX = "3SCF"


def transfer_content(order_id: int, prefix: str) -> str:
    """Noi dung CK = "<prefix> <order_id>". CA 322/323: prefix do Dashboard cau hinh (code_prefix cua SePay
    integration), KHONG hard-code. Instruction luu snapshot bat bien; matching theo snapshot (khong regex global)."""
    return f"{prefix} {order_id}"


async def current_transfer_content(conn, order_id: int) -> str | None:
    """Snapshot transfer_content cua instruction HIEN HANH cua order (binding fulfillment_conversations.instruction_id,
    fallback instruction moi nhat cua payment). Dung cho DISPLAY (notify/status/reply) — KHONG re-derive prefix."""
    cur_iid = await conn.fetchval("SELECT instruction_id FROM fulfillment_conversations WHERE order_id=$1", order_id)
    if cur_iid is not None:
        tc = await conn.fetchval("SELECT transfer_content FROM payment_instructions WHERE id=$1", cur_iid)
        if tc is not None:
            return tc
    return await conn.fetchval(
        "SELECT pi.transfer_content FROM payment_instructions pi JOIN payments p ON p.id=pi.payment_id "
        "WHERE p.order_id=$1 ORDER BY pi.id DESC LIMIT 1", order_id)


def _settle_status(method: str) -> str:
    # CA Directive 293: COD exact-match settle point is 'collected' (customer confirmation + completion);
    # 'reconciled' is a later accounting-only transition reached ONLY via the explicit reconciled step.
    return "confirmed" if method == "BANK_TRANSFER" else "collected"


async def _order_total(conn, order_id: int) -> int:
    t = await conn.fetchval("SELECT total_vnd FROM orders WHERE id=$1", order_id)
    if t is None:
        raise PaymentError(f"order {order_id} khong ton tai")
    return int(t)


async def _quoted_fee(conn, order_id: int) -> int | None:
    row = await conn.fetchrow("SELECT delivery_fee_vnd, fee_status FROM shipments WHERE order_id=$1", order_id)
    return int(row["delivery_fee_vnd"]) if row and row["fee_status"] == "quoted" else None


async def _compute_due(conn, order_id: int) -> int | None:
    fee = await _quoted_fee(conn, order_id)
    return (await _order_total(conn, order_id) + fee) if fee is not None else None


async def ensure_payment(conn, order_id: int, *, method: str, actor: str) -> dict:
    """Get-or-create. CA 266-01: cho DOI method chi khi status='awaiting' (chua co evidence)."""
    if method not in METHODS:
        raise PaymentError("method phai COD|BANK_TRANSFER")
    row = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id)
    if row:
        if row["method"] != method:
            if row["status"] != "awaiting":
                raise PaymentError(f"khong the doi phuong thuc khi da co evidence (status={row['status']})")
            row = await conn.fetchrow(
                "UPDATE payments SET method=$2, version=version+1, updated_at=now() WHERE id=$1 AND version=$3 "
                "RETURNING *", row["id"], method, row["version"])
            await audit_service.record(conn, actor_type="cli", action="payment.method", actor_ref=actor,
                                       entity_type="payments", entity_id=str(row["id"]), after={"method": method})
        return dict(row)
    due = await _compute_due(conn, order_id)
    row = await conn.fetchrow(
        "INSERT INTO payments (order_id, method, amount_due_vnd, status) VALUES ($1,$2,$3,'awaiting') "
        "ON CONFLICT (order_id) DO UPDATE SET updated_at=now() RETURNING *", order_id, method, due)
    await audit_service.record(conn, actor_type="cli", action="payment.create", actor_ref=actor,
                               entity_type="payments", entity_id=str(row["id"]),
                               after={"order_id": order_id, "method": method, "amount_due_vnd": due})
    if method == "COD":  # CA 266-08: COD -> ETA tinh tu order confirmed (payment ensure)
        from app.services.fulfillment import shipment_service as _sh
        await _sh.set_eta_start(conn, order_id, source="cod_confirmed")
    return dict(row)


async def sync_amount_due_if_unsettled(conn, order_id: int, *, actor: str) -> None:
    """CA 266-04: cap nhat amount_due khi fee doi. Neu payment CHUA settled -> update + recompute discrepancy.
    Neu DA settled ma due doi -> 'discrepancy' (obligation thay doi phai xac nhan lai)."""
    pay = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1", order_id)
    if not pay:
        return
    due = await _compute_due(conn, order_id)
    if due == pay["amount_due_vnd"]:
        return
    if pay["status"] in _SETTLED:
        await conn.execute(
            "UPDATE payments SET amount_due_vnd=$2, status='discrepancy', version=version+1, updated_at=now() "
            "WHERE id=$1", pay["id"], due)
        await audit_service.record(conn, actor_type="cli", action="payment.reopen", actor_ref=actor,
                                   entity_type="payments", entity_id=str(pay["id"]),
                                   before={"status": pay["status"]}, after={"amount_due_vnd": due,
                                                                            "status": "discrepancy"})
        return
    new_status = _reconcile_status(pay["method"], pay["amount_received_vnd"], due, pay["status"])
    await conn.execute("UPDATE payments SET amount_due_vnd=$2, status=$3, version=version+1, updated_at=now() "
                       "WHERE id=$1", pay["id"], due, new_status)


def _reconcile_status(method: str, received: int, due: int | None, cur: str) -> str:
    """Trang thai theo received vs due (chi cho cac buoc da co evidence nhan tien)."""
    if received <= 0:
        return cur
    if due is None:
        return "discrepancy"
    if received == due:
        return _settle_status(method)
    return "discrepancy"       # thieu HOAC thua -> cho staff


_ADVANCE = {
    ("BANK_TRANSFER", "customer_reported"): ("reported", ("awaiting", "reported", "discrepancy")),
    ("BANK_TRANSFER", "shop_confirmed_received"): ("settle", ("reported", "discrepancy", "confirmed")),
    # CA Directive 293: cod_collected = money + customer-confirmation + M7 completion point (exact match);
    # reconciled = accounting-only transition from an exact 'collected' (no money add, no customer notify).
    ("COD", "cod_collected"): ("cod_settle", ("awaiting", "collected", "discrepancy")),
    ("COD", "reconciled"): ("cod_reconcile", ("collected",)),
    # M7-C0 (Directive 272 §3.5): xac nhan TU DONG tu provider (SePay test) — CHI payment service ghi sau khi
    # matching (account/code/amount/state) pass o provider_ingest. Cung semantics settle (== due -> confirmed).
    ("BANK_TRANSFER", "bank_auto_confirmed"): ("settle", ("awaiting", "reported", "discrepancy")),
}


def _ev_fp(kind, amount_vnd, reference, corrects_event_id) -> str:
    return _fingerprint("ev", kind, amount_vnd, reference, corrects_event_id)


def _replay(pay, ev_row, new_fp: str, cur: str) -> dict:
    """CA 267-02: replay cung command_key -> so fingerprint. Khac payload -> reject (khong tra nham ket qua cu)."""
    stored = ev_row["command_fingerprint"]
    if stored is not None and stored != new_fp:
        raise PaymentError("command_key da dung cho payload khac — tu choi (idempotency mismatch)")
    return {"payment": dict(pay), "event_id": str(ev_row["id"]), "duplicate": True,
            "status": cur, "discrepancy": _disc(pay)}


async def _cod_collected_effect(conn, order_id: int, pay, *, notify: bool, actor: str) -> None:
    """CA Directive 293: khi COD đạt 'collected' đúng số — phát ĐÚNG 1 customer confirmation "đã thu tiền COD"
    + hoàn thành hội thoại M7 + auto-resolve payment attention. Gọi ở exact cod_collected (hoặc correction đưa về
    đúng số), KHÔNG đợi reconcile. dedupe theo (order, version) đảm bảo effective-once."""
    if notify:
        from app.services.fulfillment import notify as _n
        await _n.notify_payment(conn, order_id, kind="cod_collected", new_status="collected", version=pay["version"])
    from app.services.fulfillment import conversation as _fc
    await _fc.on_payment_confirmed(conn, order_id, actor=actor)


async def record_evidence(conn, order_id: int, *, kind: str, amount_vnd: int | None, recorded_by: str,
                          command_key: str, reference: str | None = None, note: str | None = None,
                          attachment_ref: str | None = None, corrects_event_id: int | None = None,
                          notify: bool = True) -> dict:
    """CA 266-03/267-02: command_key idempotent + fingerprint + DB lock serialize. 266-05: cumulative received.
    M7: notify=False khi caller (bot conversation) tu tra reply cung noi dung — tranh thong bao trung."""
    if not command_key:
        raise PaymentError("thieu command_key (idempotency)")
    # CA 267-02: khoa aggregate payment -> cac request tren cung payment SERIALIZE (khong dua count/insert).
    pay = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1 FOR UPDATE", order_id)
    if not pay:
        raise PaymentError(f"payment cho order {order_id} chua ton tai")
    method, cur = pay["method"], pay["status"]
    fp = _ev_fp(kind, amount_vnd, reference, corrects_event_id)

    # idempotency 1: command_key (DB-atomic) + fingerprint compare (reject mismatch)
    dup = await conn.fetchrow("SELECT * FROM payment_events WHERE payment_id=$1 AND command_key=$2",
                              pay["id"], command_key)
    if dup:
        return _replay(pay, dup, fp, cur)
    # idempotency 2 (business): cung reference cho cung kind -> khong cong lai chung tu (DB uq_pe_kind_reference)
    if reference:
        rdup = await conn.fetchrow(
            "SELECT * FROM payment_events WHERE payment_id=$1 AND kind=$2 AND reference=$3",
            pay["id"], kind, reference)
        if rdup:
            return _replay(pay, rdup, fp, cur)

    if kind == "correction":
        if not note:
            raise PaymentError("correction BAT BUOC ly do (note)")
        if not corrects_event_id:
            raise PaymentError("correction phai tro ve event goc (corrects_event_id)")
        orig = await conn.fetchval("SELECT id FROM payment_events WHERE id=$1 AND payment_id=$2",
                                   corrects_event_id, pay["id"])
        if not orig:
            raise PaymentError("corrects_event_id khong thuoc payment nay")
        delta = int(amount_vnd or 0)     # dieu chinh received (co the am)
        ev = await _insert(conn, pay["id"], kind, amount_vnd, recorded_by, reference, note, attachment_ref,
                           command_key, corrects_event_id, fp)
        if ev is None:  # race: cung command_key vao truoc -> replay
            ev = await conn.fetchrow("SELECT * FROM payment_events WHERE payment_id=$1 AND command_key=$2",
                                     pay["id"], command_key)
            return _replay(pay, ev, fp, cur)
        new_received = max(0, pay["amount_received_vnd"] + delta)
        new_status = _reconcile_status(method, new_received, pay["amount_due_vnd"], cur)
        pay = await _update_payment(conn, pay, received=new_received, status=new_status)
        # CA Directive 293: nếu correction đưa COD về đúng số (discrepancy -> collected) thì đây là mốc xác nhận
        # COD -> phát ĐÚNG 1 confirmation cho khách + hoàn thành hội thoại (chỉ khi TRANSITION vào 'collected').
        if method == "COD" and new_status == "collected" and cur != "collected":
            await _cod_collected_effect(conn, order_id, pay, notify=notify, actor=recorded_by)
        await audit_service.record(conn, actor_type="cli", action="payment.correction", actor_ref=recorded_by,
                                   entity_type="payments", entity_id=str(pay["id"]),
                                   after={"delta": delta, "received": new_received, "status": new_status})
        return {"payment": dict(pay), "event_id": str(ev["id"]), "duplicate": False,
                "status": new_status, "discrepancy": _disc(pay)}

    spec = _ADVANCE.get((method, kind))
    if spec is None:
        raise PaymentError(f"kind '{kind}' khong hop le cho method {method}")
    to_status, valid_from = spec
    if cur not in valid_from:
        raise PaymentError(f"sai thu tu: {method} status={cur} khong the ghi '{kind}'")
    # CA Directive 293: validate cod_collected TRUOC khi insert (so tien > 0 + da co due) — fail-closed, khong ghi
    # event rac. (Amount am se vi pham CHECK constraint neu de xuong _insert.)
    if kind == "cod_collected":
        if amount_vnd is None or int(amount_vnd) <= 0:
            raise PaymentError("cod_collected phai co so tien thuc thu > 0")
        if pay["amount_due_vnd"] is None:
            raise PaymentError("amount_due chua chot — khong the ghi nhan thu tien COD")

    ev = await _insert(conn, pay["id"], kind, amount_vnd, recorded_by, reference, note, attachment_ref,
                       command_key, None, fp)
    if ev is None:  # race cung command_key -> replay
        ev = await conn.fetchrow("SELECT * FROM payment_events WHERE payment_id=$1 AND command_key=$2",
                                 pay["id"], command_key)
        return _replay(pay, ev, fp, cur)

    if to_status == "settle":
        # BANK_TRANSFER (shop_confirmed_received / bank_auto_confirmed): cong vao TONG thuc nhan, so voi due
        # (== -> confirmed ; != -> discrepancy).
        got = int(amount_vnd or 0)
        new_received = pay["amount_received_vnd"] + got
        due = pay["amount_due_vnd"]
        if due is None:
            raise PaymentError("amount_due chua chot (fee chua co) — khong the xac nhan da nhan")
        new_status = _reconcile_status(method, new_received, due, cur)
        pay = await _update_payment(conn, pay, received=new_received, status=new_status)
        if new_status == "confirmed":   # transfer received -> ETA start
            from app.services.fulfillment import shipment_service as _sh
            await _sh.set_eta_start(conn, order_id, source="transfer_received")
        if notify:
            from app.services.fulfillment import notify as _n
            await _n.notify_payment(conn, order_id, kind=kind, new_status=new_status, version=pay["version"])
        if new_status == "confirmed":
            # M7: hoi thoai fulfillment (neu co) -> completed; best-effort trong cung tx (khong vo evidence).
            from app.services.fulfillment import conversation as _fc
            await _fc.on_payment_confirmed(conn, order_id, actor=recorded_by)
    elif to_status == "cod_settle":
        # CA Directive 293: cod_collected = mốc tiền + xác nhận khách + hoàn thành hội thoại.
        got = int(amount_vnd or 0)
        if got <= 0:
            raise PaymentError("cod_collected phai co so tien thuc thu > 0")
        due = pay["amount_due_vnd"]
        if due is None:
            raise PaymentError("amount_due chua chot — khong the ghi nhan thu tien COD")
        new_received = pay["amount_received_vnd"] + got
        new_status = "collected" if new_received == due else "discrepancy"   # thieu/thua -> staff, KHONG confirm
        pay = await _update_payment(conn, pay, received=new_received, status=new_status)
        if new_status == "collected" and cur != "collected":
            await _cod_collected_effect(conn, order_id, pay, notify=notify, actor=recorded_by)
    elif to_status == "cod_reconcile":
        # CA Directive 293: reconciled = accounting-only. Chi tu 'collected' da thu DU (received == due);
        # KHONG cong tien, KHONG notify lan 2. Legacy collected received=0 hoac discrepancy -> reject (fail-closed).
        due = pay["amount_due_vnd"]
        if due is None or pay["amount_received_vnd"] != due:
            raise PaymentError("chi doi soat khi da thu du (received == due); discrepancy phai correction truoc")
        new_status = "reconciled"
        pay = await _update_payment(conn, pay, received=pay["amount_received_vnd"], status=new_status)
    else:
        new_status = to_status
        if new_status != cur:
            pay = await _update_payment(conn, pay, received=pay["amount_received_vnd"], status=new_status)
        if kind == "customer_reported" and notify:
            from app.services.fulfillment import notify as _n
            await _n.notify_payment(conn, order_id, kind=kind, new_status=new_status, version=pay["version"])

    await audit_service.record(conn, actor_type="cli", action="payment.evidence", actor_ref=recorded_by,
                               entity_type="payments", entity_id=str(pay["id"]),
                               before={"status": cur}, after={"kind": kind, "status": pay["status"],
                                                              "received": pay["amount_received_vnd"]})
    return {"payment": dict(pay), "event_id": str(ev["id"]), "duplicate": False,
            "status": pay["status"], "discrepancy": _disc(pay)}


def _disc(pay) -> dict | None:
    due, got = pay["amount_due_vnd"], pay["amount_received_vnd"]
    if pay["status"] != "discrepancy" or due is None:
        return None
    return {"kind": "excess" if got > due else "partial", "due": due, "received": got, "delta": got - due}


async def _update_payment(conn, pay, *, received: int, status: str) -> dict:
    row = await conn.fetchrow(
        "UPDATE payments SET amount_received_vnd=$2, status=$3, version=version+1, updated_at=now() "
        "WHERE id=$1 AND version=$4 RETURNING *", pay["id"], received, status, pay["version"])
    if row is None:
        raise PaymentError("version conflict (concurrent) — huy")
    return dict(row)


async def _insert(conn, payment_id, kind, amount_vnd, recorded_by, reference, note, attachment_ref,
                  command_key, corrects_event_id, fingerprint):
    return await conn.fetchrow(
        "INSERT INTO payment_events (payment_id, kind, amount_vnd, recorded_by, reference, note, attachment_ref, "
        "command_key, corrects_event_id, command_fingerprint) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) "
        "ON CONFLICT (payment_id, command_key) DO NOTHING RETURNING *",
        payment_id, kind, amount_vnd, recorded_by, reference, note, attachment_ref, command_key, corrects_event_id,
        fingerprint)


# ---------------- Bank account config + instruction ----------------

async def set_bank_account(conn, *, bank: str, account_number: str, holder_name: str, actor: str,
                           branch: str | None = None, is_test: bool = False, bin_code: str | None = None) -> dict:
    """M7: bin_code (NAPAS BIN 6 so, vd VietinBank 970415) de sinh VietQR; thieu BIN -> instruction KHONG co QR."""
    if not (bank and account_number and holder_name):
        raise PaymentError("thieu bank/account_number/holder_name")
    if bin_code is not None and not (isinstance(bin_code, str) and bin_code.isdigit() and len(bin_code) == 6):
        raise PaymentError("bin phai 6 chu so (NAPAS BIN)")
    prev = await conn.fetchrow("SELECT * FROM bank_accounts WHERE active")
    new_version = (prev["version"] + 1) if prev else 1
    if prev:
        await conn.execute("UPDATE bank_accounts SET active=false, updated_at=now() WHERE id=$1", prev["id"])
    row = await conn.fetchrow(
        "INSERT INTO bank_accounts (bank, account_number, holder_name, branch, version, active, is_test, bin) "
        "VALUES ($1,$2,$3,$4,$5,true,$6,$7) RETURNING *", bank, account_number, holder_name, branch, new_version,
        is_test, bin_code)
    await audit_service.record(conn, actor_type="cli", action="bank.config", actor_ref=actor,
                               entity_type="bank_accounts", entity_id=str(row["id"]),
                               after={"bank": bank, "version": new_version, "is_test": is_test})
    return dict(row)


async def generate_instruction(conn, order_id: int, *, actor: str, command_key: str | None = None,
                               code_prefix: str | None = None) -> dict:
    """Instruction CK bat bien (snapshot account version + noi dung tat dinh + VietQR payload).
    M7 (272 §3.3): command_key -> idempotent (replay tra DUNG row cu, khong tao instruction/QR thu 2); regenerate
    (command_key moi) tao version moi ro rang (instruction_version), KHONG sua noi dung da gui. Doi active bank
    KHONG anh huong row cu. Thieu BIN -> qr_payload NULL (khong bia QR).
    CA 322/323: prefix = code_prefix (neu goi truyen) HOAC code_prefix cua SePay integration (Dashboard). KHONG co
    prefix hop le -> FAIL-CLOSED (khong hard-code/default). Snapshot transfer_content bat bien."""
    pay = await conn.fetchrow("SELECT * FROM payments WHERE order_id=$1 FOR UPDATE", order_id)
    if not pay:
        raise PaymentError(f"payment cho order {order_id} chua ton tai")
    if pay["method"] != "BANK_TRANSFER":
        raise PaymentError("instruction chi cho BANK_TRANSFER")
    if pay["amount_due_vnd"] is None:   # CA 266-04: khong phat instruction tu amount chua chot
        raise PaymentError("chua chot tong tien (phi giao chua co) — khong phat huong dan chuyen khoan")
    if command_key:
        ex = await conn.fetchrow("SELECT * FROM payment_instructions WHERE payment_id=$1 AND command_key=$2",
                                 pay["id"], command_key)
        if ex:
            out = dict(ex)
            out["duplicate"] = True
            return out
    # CA 322/323/324-01: resolve effective code_prefix.
    #  - caller truyen code_prefix -> dung (validate).
    #  - Settings module ON -> Dashboard la NGUON DUY NHAT; missing/invalid -> FAIL-CLOSED cho instruction moi.
    #  - Settings module OFF (dormant) -> LEGACY COMPAT PATH (324 §3.3): giu hanh vi CK M6/M7 baseline, khong lam
    #    bank-transfer unusable truoc khi PO bat Dashboard. CHI cho module-OFF; KHONG phai source cho module-ON/matching
    #    (connector OFF khi module OFF -> instruction chi de xac nhan thu cong).
    from app.config import settings as _settings
    from app.services.settings.integrations import (
        effective_sepay_prefix,
        validate_code_prefix,
    )
    if code_prefix is not None:
        prefix = validate_code_prefix(code_prefix)
    elif _settings.settings_integrations_enabled:
        prefix = await effective_sepay_prefix(conn)
        if not prefix:
            raise PaymentError("chua cau hinh ma thanh toan (code_prefix) tren Dashboard — cau hinh SePay integration "
                               "truoc khi phat huong dan chuyen khoan")
    else:
        prefix = _LEGACY_COMPAT_PREFIX
    acct = await conn.fetchrow("SELECT * FROM bank_accounts WHERE active")
    if not acct:
        raise PaymentError("chua cau hinh tai khoan nhan tien — chon COD hoac lien he nhan vien")
    content = transfer_content(order_id, prefix)
    qr_payload = None
    if acct["bin"]:
        from app.services.payment import vietqr as _vq
        try:
            qr_payload = _vq.build_payload(bin_code=acct["bin"], account_number=str(acct["account_number"]),
                                           amount_vnd=int(pay["amount_due_vnd"]), add_info=content)
        except _vq.VietQRError as e:
            raise PaymentError(f"khong sinh duoc VietQR: {e}") from e
    ver = (await conn.fetchval("SELECT count(*) FROM payment_instructions WHERE payment_id=$1", pay["id"])) + 1
    row = await conn.fetchrow(
        "INSERT INTO payment_instructions (order_id, payment_id, bank_account_id, account_version, "
        "bank_snapshot, account_number_snapshot, holder_snapshot, transfer_content, amount_vnd, is_test, "
        "bin_snapshot, qr_payload, qr_version, command_key, instruction_version) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,1,$13,$14) "
        "ON CONFLICT (payment_id, command_key) WHERE command_key IS NOT NULL DO NOTHING RETURNING *",
        order_id, pay["id"], acct["id"], acct["version"], acct["bank"], acct["account_number"],
        acct["holder_name"], content, pay["amount_due_vnd"], acct["is_test"], acct["bin"], qr_payload,
        command_key, ver)
    if row is None:  # race cung command_key
        ex = await conn.fetchrow("SELECT * FROM payment_instructions WHERE payment_id=$1 AND command_key=$2",
                                 pay["id"], command_key)
        out = dict(ex)
        out["duplicate"] = True
        return out
    await audit_service.record(conn, actor_type="cli", action="payment.instruction", actor_ref=actor,
                               entity_type="payment_instructions", entity_id=str(row["id"]),
                               after={"order_id": order_id, "account_version": acct["version"],
                                      "instruction_version": ver, "has_qr": qr_payload is not None})
    out = dict(row)
    out["duplicate"] = False
    return out


async def record_provider_confirmation(conn, order_id: int, *, amount_vnd: int, provider: str,
                                       provider_event_id: str, reference: str | None) -> dict:
    """M7-C0: ghi event bank_auto_confirmed sau khi provider_ingest match PASS. command_key = provider event key
    (retry/duplicate -> replay, khong 2 effect). reference = ma giao dich ngan hang (uq_pe_kind_reference)."""
    return await record_evidence(conn, order_id, kind="bank_auto_confirmed", amount_vnd=int(amount_vnd),
                                 recorded_by=f"provider:{provider}", command_key=f"{provider}:{provider_event_id}",
                                 reference=reference or f"{provider}:{provider_event_id}",
                                 note=f"auto-confirm tu {provider} event {provider_event_id}")
