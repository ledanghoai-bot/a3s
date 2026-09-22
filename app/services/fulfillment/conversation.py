"""M7-A conversational fulfillment — state machine TAT DINH sau chot don (CA Directive 272 §3.1).

Buoc (fulfillment_conversations.step):
  routing           : vua chot don; worker se dinh tuyen + bao phi (GHN goi NGOAI transaction, 2 pha).
  awaiting_method   : da gui tong tien, cho khach chon COD / BANK_TRANSFER.
  cod_handoff       : COD — payment COD dam bao, ban giao dashboard (bot ket thuc buoc chon phuong thuc).
  awaiting_transfer : CK — instruction bat bien + VietQR da gui; han 15 phut, nhac t+7/t+13 (CA Amend 273).
  staff_attention   : ngoai le (phi/dia chi/tai khoan/method/payment_timeout/mismatch/large_order/unit) -> nhan vien.
  completed         : payment confirmed (shop xac nhan hoac provider auto-confirm).

Moi transition ghi fulfillment_conversation_events (UNIQUE order_id+command_key): duplicate inbound/outbox/retry ->
replay tra reply cu, KHONG tao payment/instruction/QR/reminder thu 2. AI KHONG goi module nay de "quyet dinh":
orchestrator chi chuyen text khach vao handle_customer_text; tien/route/state do service tinh.
Template KHONG bao gio noi "da nhan tien" — chi payment service (state confirmed) moi phat notify do.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from app.services import audit_service
from app.services.command import repository as cmd_repo
from app.services.fulfillment import attention as _att
from app.services.fulfillment import shipment_service as _sh
from app.services.payment import payment_service as _pay

ROUTING, AWAITING_METHOD, COD_HANDOFF = "routing", "awaiting_method", "cod_handoff"
AWAITING_TRANSFER, STAFF_ATTENTION, COMPLETED = "awaiting_transfer", "staff_attention", "completed"
MAX_METHOD_PROMPTS = 3
# CA Review 292-02: khi đơn đang chờ nhân viên, bot trả 1 acknowledgement XÁC ĐỊNH (không im hoàn toàn), RATE-LIMIT
# 1 lần / cooldown để retry/nhiều tin không spam; không đưa tin sang LLM, không đổi order/payment/shipment.
STAFF_ACK_COOLDOWN_MIN = 30

# CA 274-02/03: contract tra ve handle_customer_text — 1 delivery authority.
#   str  = reply TAT DINH cho luot khach (orchestrator direct-send DUY NHAT; M7 KHONG enqueue outbox cho reply nay).
#   SILENT = M7 da xu ly nhung KHONG gui reply luot nay (vd dang staff_attention -> bot im lang) -> chan LLM.
#   None = khong lien quan M7 -> fall-through (M6/LLM).
SILENT = object()
MAX_ATTEMPTS = 8
_CUSTOMER_DEST = {"telegram_customer", "messenger"}

EV_PROMPT, EV_INSTRUCTION = "fulfillment.prompt.notify", "fulfillment.instruction.notify"
EV_REMINDER, EV_STAFF, EV_COD = "fulfillment.reminder.notify", "fulfillment.staff.notify", "fulfillment.cod.notify"

# --- Parser phuong thuc (giu dau + bien the khong dau, ranh gioi tu; CLAUDE.md §6) ---
_COD_RE = re.compile(
    r"(?:\bcod\b|\bti[eề]n\s*m[aặ]t\b|\bkhi\s*nh[aậ]n\s*h[aà]ng\b|\bnh[aậ]n\s*h[aà]ng\s*(?:r[oồ]i|m[oớ]i)\s*tr[aả]\b"
    r"|\bship\s*cod\b|^\s*1\s*[.)]?\s*$)", re.IGNORECASE)
_BANK_RE = re.compile(
    r"(?:\bchuy[eể]n\s*kho[aả]n\b|\bck\b|\bbanking\b|\bqu[eé]t\s*m[aã]\b|\bvietqr\b|\bqr\b|\bchuy[eể]n\s*ti[eề]n\b"
    r"|\binternet\s*banking\b|^\s*2\s*[.)]?\s*$)", re.IGNORECASE)
_REPORTED_RE = re.compile(
    r"(?:\b(?:đã|da)\s*(?:chuy[eể]n|ck|thanh\s*to[aá]n|g[uử]i\s*ti[eề]n)\b|\bchuy[eể]n\s*(?:kho[aả]n\s*)?(?:r[oồ]i|xong)\b"
    r"|\bck\s*(?:r[oồ]i|xong)\b)", re.IGNORECASE)
_NEGATION_RE = re.compile(r"\b(?:ch[uư]a|kh[oô]ng|ko|chua)\b", re.IGNORECASE)
_VAGUE_RE = re.compile(r"^\s*(?:ok|oke|okay|[đd][uư][oợ]c|sao\s*c[uũ]ng\s*[đd][uư][oợ]c|c[aả]\s*hai|c[aả]\s*2|t[uù]y|tuy|\?)\s*[.!]*\s*$",
                       re.IGNORECASE)


def parse_method(text: str) -> str:
    """'COD' | 'BANK_TRANSFER' | 'ambiguous' (ca hai / mo ho) | 'none' (khong lien quan)."""
    t = (text or "").strip()
    cod, bank = bool(_COD_RE.search(t)), bool(_BANK_RE.search(t))
    if cod and bank:
        return "ambiguous"
    if cod:
        return "COD"
    if bank:
        return "BANK_TRANSFER"
    if _VAGUE_RE.match(t):
        return "ambiguous"
    return "none"


def is_transfer_reported(text: str) -> bool:
    t = (text or "").strip()
    return bool(_REPORTED_RE.search(t)) and not _NEGATION_RE.search(t)


def _vnd(n) -> str:
    return "—" if n is None else f"{int(n):,}".replace(",", ".") + "đ"


_ROUTE_LABEL = {"SELF_DELIVERY": "shop tự giao nội thành Buôn Ma Thuột", "GHN": "giao qua GHN",
                "MANUAL_REVIEW": "nhân viên xác nhận"}


def prompt_text(order_id: int, *, goods_vnd: int, fee_vnd: int, total_vnd: int, route: str | None,
                eta_text: str | None) -> str:
    fee_txt = "0đ (miễn phí)" if fee_vnd == 0 else _vnd(fee_vnd)
    eta = f" Dự kiến giao: {eta_text}." if eta_text else ""
    return (f"Dạ đơn #{order_id} của anh/chị: tiền hàng {_vnd(goods_vnd)} + phí giao {fee_txt} "
            f"({_ROUTE_LABEL.get(route or '', 'giao hàng')}) = TỔNG {_vnd(total_vnd)}.{eta}\n"
            "Anh/chị muốn thanh toán bằng cách nào ạ?\n"
            "1) COD — trả tiền mặt khi nhận hàng\n"
            "2) Chuyển khoản — em gửi mã VietQR để quét\n"
            "Anh/chị trả lời \"COD\" hoặc \"chuyển khoản\" giúp em nhé.")


# CA Amendment 273 §4: 4 template báo lý do TẤT ĐỊNH, không tiết lộ số thiếu/thừa, không nói "đã nhận tiền".
_ESCALATION_TEXT = {
    "large_order_review": "Đơn hàng có số lượng lớn nên shop cần nhân viên kiểm tra và hỗ trợ trực tiếp. "
                          "Shop sẽ liên hệ lại với bạn.",
    "payment_timeout": "Shop chưa xác nhận được khoản chuyển trong thời gian chờ nên cần nhân viên kiểm tra. "
                       "Shop sẽ liên hệ lại với bạn.",
    "payment_mismatch": "Thông tin thanh toán chưa khớp hoàn toàn nên shop cần nhân viên kiểm tra. "
                        "Shop sẽ liên hệ lại với bạn.",
    "quantity_unit_review": "Thông tin số lượng cần được nhân viên kiểm tra thêm. Shop sẽ liên hệ lại với bạn.",
}


def staff_ack_text(order_id: int) -> str:
    """CA Review 292-02: ack XÁC ĐỊNH khi đơn đang chờ nhân viên. KHÔNG hứa đã xử lý xong, KHÔNG nói tiền/giao —
    chỉ trấn an là nhân viên đang xử lý và sẽ liên hệ."""
    return (f"Dạ đơn #{order_id} của anh/chị đang được nhân viên shop kiểm tra và sẽ liên hệ lại với anh/chị sớm ạ. "
            "Anh/chị vui lòng chờ giúp em một chút nhé.")


def staff_text(order_id: int, reason: str) -> str:
    if reason in _ESCALATION_TEXT:                 # 273 §4 — nguyên văn, không kèm order id
        return _ESCALATION_TEXT[reason]
    why = {"quote": "Phí giao cho địa chỉ này cần nhân viên xác nhận",
           "address": "Địa chỉ giao cần nhân viên kiểm tra lại",
           "account": "Thông tin nhận chuyển khoản cần nhân viên xác nhận",
           "method": "Em chưa rõ phương thức thanh toán anh/chị chọn",
           "provider_error": "Hệ thống tính phí vận chuyển tạm gián đoạn"}.get(reason, "Đơn cần nhân viên hỗ trợ")
    return (f"Dạ đơn #{order_id} đã được ghi nhận. {why}, nhân viên shop sẽ liên hệ anh/chị sớm để hoàn tất ạ. "
            "Đơn vẫn được giữ cho anh/chị.")


# --------------------------------------------------------------------------
# CA Amendment 273 §2/§3: policy CO VERSION (nguong 100 hũ + moc timeout/nhac). Order snapshot policy_version.
async def _active_policy(conn, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    row = await conn.fetchrow(
        "SELECT * FROM fulfillment_policy_versions WHERE effective_from <= $1 "
        "AND (effective_to IS NULL OR effective_to > $1) ORDER BY version DESC LIMIT 1", now)
    if not row:
        raise RuntimeError("khong co fulfillment_policy_version hieu luc")
    return dict(row)


async def _policy_for(conn, fc: dict) -> dict:
    """Policy theo snapshot cua hoi thoai (fc.policy_version); fallback active neu chua snapshot (legacy)."""
    if fc.get("policy_version"):
        row = await conn.fetchrow("SELECT * FROM fulfillment_policy_versions WHERE version=$1", fc["policy_version"])
        if row:
            return dict(row)
    return await _active_policy(conn)


async def _large_order_decision(conn, order_id: int, policy: dict) -> tuple[str | None, int | None]:
    """CA 273 §2: tinh tu COMMITTED order_items.quantity. Chi tinh khi MOI item co sales_unit == policy.unit;
    khac/thieu unit -> ('quantity_unit_review', None). Tong >= threshold -> ('large_order_review', total).
    Con lai -> (None, total). KHONG tu coi moi item la 1 hu."""
    rows = await conn.fetch(
        "SELECT oi.quantity, p.sales_unit FROM order_items oi JOIN products p ON p.id=oi.product_id "
        "WHERE oi.order_id=$1", order_id)
    if not rows:
        return None, None
    unit = policy["large_order_unit"]
    total = 0
    for r in rows:
        if r["sales_unit"] is None or r["sales_unit"] != unit:
            return "quantity_unit_review", None
        total += int(r["quantity"])
    if total >= int(policy["large_order_threshold"]):
        return "large_order_review", total
    return None, total


def cod_text(order_id: int, total_vnd: int | None) -> str:
    return (f"Dạ em đã ghi nhận đơn #{order_id} thanh toán khi nhận hàng (COD), tổng {_vnd(total_vnd)}. "
            "Bộ phận giao hàng sẽ liên hệ anh/chị khi giao. Cảm ơn anh/chị ạ!")


def instruction_text(order_id: int, instr: dict, *, wait_minutes: int) -> str:
    test = "\n⚠️ TEST — KHÔNG CHUYỂN TIỀN (tài khoản thử nghiệm)" if instr.get("is_test") else ""
    qr = "\nEm gửi kèm mã VietQR để anh/chị quét (đúng số tiền + nội dung)." if instr.get("qr_payload") else ""
    return (f"Dạ anh/chị chuyển khoản giúp em theo thông tin:\n"
            f"Ngân hàng: {instr['bank_snapshot']}\nSố TK: {instr['account_number_snapshot']}\n"
            f"Chủ TK: {instr['holder_snapshot']}\nSố tiền: {_vnd(instr['amount_vnd'])}\n"
            f"Nội dung: {instr['transfer_content']}{test}{qr}\n"
            f"Shop giữ đơn trong {wait_minutes} phút. Khi ghi nhận được tiền, hệ thống sẽ báo lại anh/chị ạ.")


def reminder_text(order_id: int, instr: dict) -> str:
    return (f"Dạ shop chưa ghi nhận được chuyển khoản cho đơn #{order_id} ({_vnd(instr['amount_vnd'])}, nội dung "
            f"{instr['transfer_content']}). Nếu anh/chị đã chuyển, nhắn \"đã chuyển\" để nhân viên kiểm tra; "
            "nếu muốn đổi sang COD, nhắn \"COD\" giúp em ạ.")


def reported_text(order_id: int, content: str | None = None) -> str:
    # CA 323: content = snapshot instruction (caller truyen); None -> khong nhac noi dung (khong re-derive prefix).
    nd = f" (nội dung {content})" if content else ""
    return (f"Dạ shop đã nhận thông tin chuyển khoản đơn #{order_id}{nd}, "
            "đang kiểm tra và sẽ xác nhận với anh/chị ạ.")


def reask_text(order_id: int) -> str:
    return (f"Dạ em chưa rõ ạ. Đơn #{order_id} anh/chị muốn thanh toán \"COD\" (trả tiền mặt khi nhận hàng) "
            "hay \"chuyển khoản\" (em gửi mã VietQR)? Anh/chị trả lời một trong hai giúp em nhé.")


# --------------------------------------------------------------------------
async def _enqueue_customer(conn, fc, *, event_type: str, dedupe_key: str, text: str, extra: dict | None = None,
                            stale_check: dict | None = None) -> None:
    if fc["channel"] not in _CUSTOMER_DEST:
        return
    payload = {"customer_ref": fc["customer_ref"], "order_id": fc["order_id"], "text": text}
    if extra:
        payload.update(extra)
    if stale_check:
        payload["stale_check"] = stale_check
    await cmd_repo.insert_outbox(conn, command_id=None, event_type=event_type, event_version=1,
                                 destination=fc["channel"], dedupe_key=dedupe_key, payload=payload,
                                 max_attempts=MAX_ATTEMPTS)


async def _journal(conn, order_id: int, *, command_key: str, source: str, from_step: str | None, to_step: str,
                   detail: dict | None, reply_text: str | None) -> bool:
    rid = await conn.fetchval(
        "INSERT INTO fulfillment_conversation_events (order_id, command_key, source, from_step, to_step, detail, "
        "reply_text) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7) ON CONFLICT (order_id, command_key) DO NOTHING RETURNING id",
        order_id, command_key, source, from_step, to_step, json.dumps(detail or {}), reply_text)
    return rid is not None


async def _replay(conn, order_id: int, command_key: str):
    return await conn.fetchrow(
        "SELECT reply_text, to_step FROM fulfillment_conversation_events WHERE order_id=$1 AND command_key=$2",
        order_id, command_key)


async def _set_step(conn, fc, *, step: str, **cols) -> dict:
    sets = ["step=$2", "version=version+1", "updated_at=now()"]
    args = [fc["id"], step]
    for k, v in cols.items():
        args.append(v)
        sets.append(f"{k}=${len(args)}")
    args.append(fc["version"])
    row = await conn.fetchrow(
        f"UPDATE fulfillment_conversations SET {', '.join(sets)} WHERE id=$1 AND version=${len(args)} RETURNING *",
        *args)
    if row is None:
        raise RuntimeError("fulfillment_conversation version conflict")
    return dict(row)


async def get(conn, order_id: int, *, lock: bool = False) -> dict | None:
    row = await conn.fetchrow(
        "SELECT * FROM fulfillment_conversations WHERE order_id=$1" + (" FOR UPDATE" if lock else ""), order_id)
    return dict(row) if row else None


async def get_by_customer(conn, customer_ref: str, *, lock: bool = False) -> dict | None:
    """Hoi thoai fulfillment MO gan nhat cua khach (theo psid) — cho orchestrator bat reply."""
    row = await conn.fetchrow(
        "SELECT * FROM fulfillment_conversations WHERE customer_ref=$1 AND step IN ($2,$3,$4,$5) "
        "ORDER BY updated_at DESC, id DESC LIMIT 1" + (" FOR UPDATE" if lock else ""),
        customer_ref, AWAITING_METHOD, AWAITING_TRANSFER, COD_HANDOFF, STAFF_ATTENTION)
    return dict(row) if row else None


# --------------------------------------------------------------------------
async def ensure_started(conn, order_id: int, *, channel: str, customer_ref: str, command_key: str) -> bool:
    """Goi TRONG transaction chot don (order_service). Chi tao row step='routing' + journal — KHONG goi provider,
    KHONG bao phi o day (worker lam, 2 pha). Idempotent: da co -> False."""
    # CA 273 §2: snapshot policy_version luc chot don (nguong/moc doi sau KHONG doi don cu). Non-fatal.
    try:
        policy_version = (await _active_policy(conn))["version"]
    except Exception:  # noqa: BLE001 — thieu policy khong duoc lam vo chot don
        policy_version = None
    rid = await conn.fetchval(
        "INSERT INTO fulfillment_conversations (order_id, channel, customer_ref, step, policy_version) "
        "VALUES ($1,$2,$3,$4,$5) ON CONFLICT (order_id) DO NOTHING RETURNING id",
        order_id, channel, customer_ref, ROUTING, policy_version)
    if rid is None:
        return False
    await _journal(conn, order_id, command_key=command_key, source="system", from_step=None, to_step=ROUTING,
                   detail={"channel": channel, "policy_version": policy_version}, reply_text=None)
    return True


async def advance_routing(conn, order_id: int, *, ghn_result=None, actor: str = "m7:worker") -> dict | None:
    """Pha 2 (trong tx): dinh tuyen + snapshot quote (ghn_result da tinh NGOAI tx) -> gui tong tien + hoi method,
    hoac staff_attention (fee unknown/dia chi/provider). Idempotent theo step (chi khi step=routing)."""
    fc = await get(conn, order_id, lock=True)
    if not fc or fc["step"] != ROUTING:
        return None
    # CA 273 §2: guard số lượng NGAY trước khi báo phí/thanh toán — >=100 hũ hoặc unit mơ hồ -> staff.
    policy = await _policy_for(conn, fc)
    lo_reason, lo_qty = await _large_order_decision(conn, order_id, policy)
    if lo_reason:
        text = staff_text(order_id, lo_reason)
        fc2 = await _set_step(conn, fc, step=STAFF_ATTENTION, attention_reason=lo_reason,
                              attention_at=datetime.now(timezone.utc), policy_version=policy["version"],
                              large_order_qty=lo_qty)
        # 273 §4: commit notification intent (reason) TRƯỚC -> commit staff_attention cùng atomic -> outbox.
        await _journal(conn, order_id, command_key=f"largeorder:{fc['version']}", source="system",
                       from_step=ROUTING, to_step=STAFF_ATTENTION,
                       detail={"reason": lo_reason, "qty": lo_qty, "threshold": policy["large_order_threshold"],
                               "unit": policy["large_order_unit"], "policy_version": policy["version"]},
                       reply_text=text)
        await _enqueue_customer(conn, fc2, event_type=EV_STAFF,
                                dedupe_key=f"fc_staff:{order_id}:{fc2['version']}", text=text)
        await _att.open_attention(conn, order_id, reason=lo_reason,
                                  detail={"qty": lo_qty, "threshold": policy["large_order_threshold"],
                                          "policy_version": policy["version"]}, created_by=actor)
        return fc2
    cur = await conn.fetchrow("SELECT * FROM shipments WHERE order_id=$1", order_id)
    if cur and cur["fee_status"] == "quoted" and cur["quote_source"] == "staff_manual":
        # Staff da bao phi thu cong (sau staff_attention/resume) -> DUNG quote do, KHONG re-route de ghi de.
        sh = dict(cur)
        sh["attention_reason"] = None
    else:
        sh = await _sh.route_and_quote(conn, order_id, actor=actor, ghn_result=ghn_result)
    ck = f"route:{sh['version']}:{fc['version']}"
    if sh["fee_status"] == "quoted":
        goods = int(await conn.fetchval("SELECT total_vnd FROM orders WHERE id=$1", order_id))
        fee = int(sh["delivery_fee_vnd"])
        text = prompt_text(order_id, goods_vnd=goods, fee_vnd=fee, total_vnd=goods + fee,
                           route=sh.get("routing_source"), eta_text=sh.get("eta_text"))
        fc2 = await _set_step(conn, fc, step=AWAITING_METHOD, policy_version=policy["version"],
                              large_order_qty=lo_qty)
        await _journal(conn, order_id, command_key=ck, source="system", from_step=ROUTING, to_step=AWAITING_METHOD,
                       detail={"route": sh.get("routing_source"), "fee_vnd": fee, "total_vnd": goods + fee,
                               "shipment_version": sh["version"]}, reply_text=text)
        await _enqueue_customer(conn, fc2, event_type=EV_PROMPT, dedupe_key=f"fc_prompt:{order_id}:{fc2['version']}",
                                text=text, stale_check={"kind": "fulfillment", "order_id": order_id,
                                                        "step": AWAITING_METHOD})
        return fc2
    reason = sh.get("attention_reason") or "quote"
    text = staff_text(order_id, reason)
    fc2 = await _set_step(conn, fc, step=STAFF_ATTENTION, attention_reason=reason, attention_at=datetime.now(timezone.utc))
    await _journal(conn, order_id, command_key=ck, source="system", from_step=ROUTING, to_step=STAFF_ATTENTION,
                   detail={"route": sh.get("routing_source"), "reason": reason, "fee_status": sh["fee_status"]},
                   reply_text=text)
    await _enqueue_customer(conn, fc2, event_type=EV_STAFF, dedupe_key=f"fc_staff:{order_id}:{fc2['version']}",
                            text=text)
    return fc2


async def _to_cod(conn, fc, *, command_key: str, source: str, actor: str) -> str:
    # CA 274-03: reply luot khach -> DIRECT-SEND (return) la delivery authority DUY NHAT. KHONG enqueue outbox
    # (tranh gui 2 lan). Chi worker-context (advance_routing/run_due/escalate) moi dung outbox.
    order_id = fc["order_id"]
    pay = await _pay.ensure_payment(conn, order_id, method="COD", actor=actor)
    text = cod_text(order_id, pay.get("amount_due_vnd"))
    await _set_step(conn, fc, step=COD_HANDOFF, method="COD", transfer_deadline_at=None)
    await _journal(conn, order_id, command_key=command_key, source=source, from_step=fc["step"], to_step=COD_HANDOFF,
                   detail={"payment_id": pay["id"], "amount_due_vnd": pay.get("amount_due_vnd")}, reply_text=text)
    return text


async def _to_transfer(conn, fc, *, command_key: str, source: str, actor: str) -> str:
    order_id = fc["order_id"]
    policy = await _policy_for(conn, fc)
    wait = int(policy["timeout_minutes"])       # CA 273: t+15 (config versioned)
    await _pay.ensure_payment(conn, order_id, method="BANK_TRANSFER", actor=actor)
    try:
        instr = await _pay.generate_instruction(conn, order_id, actor=actor, command_key=f"fc:{order_id}:{command_key}")
    except _pay.PaymentError as e:
        reason = "account" if "tai khoan" in str(e) else "quote"
        text = staff_text(order_id, reason)
        fc2 = await _set_step(conn, fc, step=STAFF_ATTENTION, method="BANK_TRANSFER", attention_reason=reason,
                              attention_at=datetime.now(timezone.utc))
        await _journal(conn, order_id, command_key=command_key, source=source, from_step=fc["step"],
                       to_step=STAFF_ATTENTION, detail={"reason": reason, "error": str(e)[:160]}, reply_text=text)
        await _att.open_attention(conn, order_id, reason=reason, detail={"error": str(e)[:160]}, created_by=actor)
        await _enqueue_customer(conn, fc2, event_type=EV_STAFF, dedupe_key=f"fc_staff:{order_id}:{fc2['version']}",
                                text=text)
        return text
    # CA 273 §3: moc thoi gian tu payment_instruction.created_at ĐÃ COMMIT (không phải now() lúc transition).
    started = instr["created_at"]
    deadline = started + timedelta(minutes=wait)
    text = instruction_text(order_id, instr, wait_minutes=wait)
    fc2 = await _set_step(conn, fc, step=AWAITING_TRANSFER, method="BANK_TRANSFER", instruction_id=instr["id"],
                          policy_version=policy["version"], transfer_started_at=started,
                          transfer_deadline_at=deadline)
    await _journal(conn, order_id, command_key=command_key, source=source, from_step=fc["step"],
                   to_step=AWAITING_TRANSFER, detail={"instruction_id": instr["id"],
                                                      "started_at": started.isoformat(),
                                                      "deadline_at": deadline.isoformat(),
                                                      "has_qr": bool(instr.get("qr_payload"))}, reply_text=text)
    if instr.get("qr_payload"):
        await _enqueue_customer(
            conn, fc2, event_type=EV_INSTRUCTION, dedupe_key=f"fc_qr:{order_id}:{instr['id']}",
            text=(f"Mã VietQR đơn #{order_id} — quét để chuyển đúng {_vnd(instr['amount_vnd'])}, nội dung "
                  f"{instr['transfer_content']}" + (" [TEST — KHÔNG CHUYỂN TIỀN]" if instr.get("is_test") else "")),
            extra={"qr_payload": instr["qr_payload"], "instruction_id": instr["id"]},
            stale_check={"kind": "payment", "order_id": order_id, "new_status": "awaiting"})
    return text


async def escalate(conn, order_id: int, *, reason: str, actor: str, detail: dict | None = None,
                   notify_customer: bool = True) -> dict | None:
    """CA 274-02: handoff escalation DUNG CHUNG (worker-context) — ATOMIC trong tx caller:
    lock conversation -> (notify_customer) notification intent (template reason, outbox) -> step=staff_attention ->
    open_attention idempotent -> reminder/instruction notify cu -> stale (do step doi). Bot IM LANG sau handoff
    (handle_customer_text tra SILENT). Idempotent: da o staff_attention cung reason -> khong re-notify.
    notify_customer=False khi caller tu gui reply luot khach (vd huy don) — tranh gui 2 lan.
    payment_mismatch/timeout/large_order/quantity_unit/account/quote/method/other dung CHUNG semantics nay."""
    fc = await get(conn, order_id, lock=True)
    if not fc:
        return None
    if fc["step"] == COMPLETED:
        # CA 275-03: KHONG mo lai hoi thoai da completed (don da thanh toan/xong) — chi mo attention cho staff.
        aid = await _att.open_attention(conn, order_id, reason=reason, detail=detail, created_by=actor)
        return {"step": COMPLETED, "reason": reason, "attention_id": aid, "already": True}
    already = fc["step"] == STAFF_ATTENTION and fc["attention_reason"] == reason
    if not already:
        frm = fc["step"]
        fc = await _set_step(conn, fc, step=STAFF_ATTENTION, attention_reason=reason,
                             attention_at=datetime.now(timezone.utc))
        await _journal(conn, order_id, command_key=f"escalate:{reason}:{fc['version']}", source="system",
                       from_step=frm, to_step=STAFF_ATTENTION, detail={"reason": reason, **(detail or {})},
                       reply_text=None)
        if notify_customer:
            # notification intent (reason) TRUOC -> outbox; stale-check step=staff_attention (late confirm -> huy)
            await _enqueue_customer(conn, fc, event_type=EV_STAFF, dedupe_key=f"fc_staff:{order_id}:{reason}",
                                    text=staff_text(order_id, reason),
                                    stale_check={"kind": "fulfillment", "order_id": order_id, "step": STAFF_ATTENTION})
    aid = await _att.open_attention(conn, order_id, reason=reason, detail=detail, created_by=actor)
    return {"step": STAFF_ATTENTION, "reason": reason, "attention_id": aid, "already": already}


async def handle_customer_text(conn, customer_ref: str, text: str, *, command_key: str, actor: str = "m7:bot"):
    """Orchestrator goi TRONG tx. CA 274-02/03 return contract: str (direct-send) | SILENT (M7 xu ly, bot im lang,
    chan LLM) | None (khong lien quan -> fall-through). command_key = provider_message_id -> duplicate inbound
    tra reply cu."""
    fc = await get_by_customer(conn, customer_ref, lock=True)
    if not fc:
        return None
    order_id = fc["order_id"]
    rp = await _replay(conn, order_id, command_key)
    if rp:
        return rp["reply_text"] if rp["reply_text"] is not None else SILENT
    step = fc["step"]
    # CA Review 292-02: đang chờ nhân viên -> bot KHÔNG rơi xuống LLM, KHÔNG đổi order/payment/shipment; trả 1 ack
    # XÁC ĐỊNH, RATE-LIMIT 1 lần / STAFF_ACK_COOLDOWN_MIN (theo staff_ack event gần nhất). Trong cooldown -> SILENT.
    # (duplicate cùng command_key đã được _replay ở trên trả lại reply cũ -> không gửi 2 lần.)
    if step == STAFF_ATTENTION:
        # CA Review 299-02: cooldown thuộc EPISODE hiện tại — lọc staff_ack theo `attention_at` (mốc vào episode).
        # resolve rồi re-escalate cập nhật attention_at -> episode mới được ack lại (ack cũ không suppress).
        att_at = fc.get("attention_at")
        last_ack = await conn.fetchval(
            "SELECT max(created_at) FROM fulfillment_conversation_events WHERE order_id=$1 "
            "AND (detail->>'staff_ack')='1' AND ($2::timestamptz IS NULL OR created_at >= $2)", order_id, att_at)
        now = datetime.now(timezone.utc)
        if last_ack is not None and (now - last_ack) < timedelta(minutes=STAFF_ACK_COOLDOWN_MIN):
            await _journal(conn, order_id, command_key=command_key, source="customer", from_step=step, to_step=step,
                           detail={"silenced_during_staff_attention": True}, reply_text=None)
            return SILENT
        ack = staff_ack_text(order_id)
        # CA Review 299-01: journal reply_text=None -> replay cùng command_key (duplicate inbound) trả SILENT, KHÔNG
        # để orchestrator re-send ack lần 2. detail 'staff_ack' đánh dấu episode. Ack chỉ direct-send ĐÚNG 1 lần (lượt đầu).
        await _journal(conn, order_id, command_key=command_key, source="customer", from_step=step, to_step=step,
                       detail={"staff_ack": "1"}, reply_text=None)
        return ack
    m = parse_method(text)
    if step == AWAITING_METHOD:
        if m == "COD":
            return await _to_cod(conn, fc, command_key=command_key, source="customer", actor=actor)
        if m == "BANK_TRANSFER":
            return await _to_transfer(conn, fc, command_key=command_key, source="customer", actor=actor)
        if m == "ambiguous":
            n = int(fc["method_prompts"] or 0) + 1
            if n >= MAX_METHOD_PROMPTS:
                reply = staff_text(order_id, "method")
                fc2 = await _set_step(conn, fc, step=STAFF_ATTENTION, method_prompts=n, attention_reason="method",
                                      attention_at=datetime.now(timezone.utc))
                await _journal(conn, order_id, command_key=command_key, source="customer", from_step=step,
                               to_step=STAFF_ATTENTION, detail={"reason": "method", "prompts": n}, reply_text=reply)
                await _att.open_attention(conn, order_id, reason="method", detail={"prompts": n}, created_by=actor)
                _ = fc2
                return reply
            reply = reask_text(order_id)
            await _set_step(conn, fc, step=AWAITING_METHOD, method_prompts=n)
            await _journal(conn, order_id, command_key=command_key, source="customer", from_step=step,
                           to_step=AWAITING_METHOD, detail={"reask": n}, reply_text=reply)
            return reply
        return None
    if step == AWAITING_TRANSFER:
        pay = await conn.fetchrow("SELECT status, amount_received_vnd FROM payments WHERE order_id=$1", order_id)
        if is_transfer_reported(text):
            if pay and pay["status"] in ("awaiting", "reported", "discrepancy"):
                await _pay.record_evidence(conn, order_id, kind="customer_reported", amount_vnd=None,
                                           recorded_by=actor, command_key=f"fc:{order_id}:{command_key}",
                                           note="khach bao da chuyen (bot)", notify=False)
            reply = reported_text(order_id, await _pay.current_transfer_content(conn, order_id))
            await _journal(conn, order_id, command_key=command_key, source="customer", from_step=step,
                           to_step=step, detail={"customer_reported": True}, reply_text=reply)
            return reply
        if m == "COD":
            # doi method chi khi CHUA co evidence/confirmed (payment awaiting) — sau do chuyen staff.
            if pay and pay["status"] == "awaiting" and int(pay["amount_received_vnd"] or 0) == 0:
                return await _to_cod(conn, fc, command_key=command_key, source="customer", actor=actor)
            reply = staff_text(order_id, "method")
            await _set_step(conn, fc, step=STAFF_ATTENTION, attention_reason="method",
                            attention_at=datetime.now(timezone.utc))
            await _journal(conn, order_id, command_key=command_key, source="customer", from_step=step,
                           to_step=STAFF_ATTENTION, detail={"reason": "method_change_after_evidence"}, reply_text=reply)
            await _att.open_attention(conn, order_id, reason="method",
                                      detail={"change": "BANK_TRANSFER->COD", "payment_status": pay["status"] if pay else None},
                                      created_by=actor)
            return reply
        return None
    if step == COD_HANDOFF and m == "BANK_TRANSFER":
        pay = await conn.fetchrow("SELECT status, amount_received_vnd FROM payments WHERE order_id=$1", order_id)
        if pay and pay["status"] == "awaiting" and int(pay["amount_received_vnd"] or 0) == 0:
            return await _to_transfer(conn, fc, command_key=command_key, source="customer", actor=actor)
        reply = staff_text(order_id, "method")
        await _set_step(conn, fc, step=STAFF_ATTENTION, attention_reason="method",
                        attention_at=datetime.now(timezone.utc))
        await _journal(conn, order_id, command_key=command_key, source="customer", from_step=step,
                       to_step=STAFF_ATTENTION, detail={"reason": "method_change_after_evidence"}, reply_text=reply)
        await _att.open_attention(conn, order_id, reason="method", detail={"change": "COD->BANK_TRANSFER"},
                                  created_by=actor)
        return reply
    return None


# --------------------------------------------------------------------------
async def run_due(conn, *, now: datetime | None = None, actor: str = "m7:worker") -> dict:
    """Cron 60s (CA Amendment 273 §3). Moc tu transfer_started_at (=instruction.created_at): t+r1, t+r2, t+timeout.
    Payment confirmed/reconciled -> completed (khong nhac). Chua confirmed: >=timeout -> thong bao ly do +
    staff_attention(payment_timeout) cung atomic; else >=r2/r1 (chua gui) -> DUNG 1 reminder (dedupe
    (instruction_id, reminder_no)). KHONG huy don, KHONG doi inventory. Restart/retry khong tao effect 2 lan.
    `now` inject duoc (fake clock cho test)."""
    from app.services.fulfillment import m7_scope as _m7s
    now = now or datetime.now(timezone.utc)
    stats = {"reminded": 0, "escalated": 0, "completed": 0, "skipped_scope": 0}
    rows = await conn.fetch(
        "SELECT * FROM fulfillment_conversations WHERE step=$1 AND transfer_started_at IS NOT NULL "
        "ORDER BY transfer_started_at LIMIT 100 FOR UPDATE SKIP LOCKED", AWAITING_TRANSFER)
    for r in rows:
        fc = dict(r)
        oid, iid = fc["order_id"], fc["instruction_id"]
        # CA Directive 286: customer khong con eligible -> KHONG gui reminder/escalation moi (state giu cho staff).
        if not _m7s.m7_enabled_for(await conn.fetchval("SELECT customer_id FROM orders WHERE id=$1", oid)):
            stats["skipped_scope"] += 1
            continue
        policy = await _policy_for(conn, fc)
        started = fc["transfer_started_at"]
        r1_at = started + timedelta(minutes=int(policy["reminder1_minutes"]))
        r2_at = started + timedelta(minutes=int(policy["reminder2_minutes"]))
        to_at = started + timedelta(minutes=int(policy["timeout_minutes"]))
        pay = await conn.fetchrow("SELECT status FROM payments WHERE order_id=$1 FOR UPDATE", oid)
        if pay and pay["status"] in ("confirmed", "reconciled"):
            await _set_step(conn, fc, step=COMPLETED, completed_at=now)
            await _journal(conn, oid, command_key=f"due:{iid}:completed", source="worker",
                           from_step=AWAITING_TRANSFER, to_step=COMPLETED, detail={}, reply_text=None)
            stats["completed"] += 1
            continue
        instr = await conn.fetchrow("SELECT * FROM payment_instructions WHERE id=$1", iid)
        if now >= to_at:
            # CA 274-02: timeout -> escalate handoff DUNG CHUNG (notification intent + staff_attention + open atten
            # atomic). Reminder cu pending bi stale (step doi awaiting_transfer -> staff_attention).
            await escalate(conn, oid, reason="payment_timeout", actor=actor,
                           detail={"instruction_id": iid, "payment_status": pay["status"] if pay else None})
            stats["escalated"] += 1
            continue
        # reminders: chon moc cao nhat da toi, dedupe DB-atomic (instruction_id, reminder_no)
        for rn, rat in ((2, r2_at), (1, r1_at)):
            if now < rat:
                continue
            claimed = await conn.fetchval(
                "INSERT INTO fulfillment_reminders (payment_instruction_id, reminder_no, sent_at) VALUES ($1,$2,$3) "
                "ON CONFLICT DO NOTHING RETURNING reminder_no", iid, rn, now)
            if claimed is not None:
                text = reminder_text(oid, dict(instr)) if instr else staff_text(oid, "payment_timeout")
                await _journal(conn, oid, command_key=f"due:{iid}:reminder:{rn}", source="worker",
                               from_step=AWAITING_TRANSFER, to_step=AWAITING_TRANSFER,
                               detail={"reminder_no": rn, "payment_status": pay["status"] if pay else None},
                               reply_text=text)
                # CA 274-02: stale-check theo STEP — escalation/completed (step doi khoi awaiting_transfer) -> huy
                # reminder pending chua gui.
                await _enqueue_customer(conn, fc, event_type=EV_REMINDER,
                                        dedupe_key=f"fc_reminder:{oid}:{iid}:{rn}", text=text,
                                        stale_check={"kind": "fulfillment", "order_id": oid,
                                                     "step": AWAITING_TRANSFER})
                stats["reminded"] += 1
            break   # xu ly toi da 1 slot reminder/tick (slot cao nhat da toi)
    return stats


async def on_payment_confirmed(conn, order_id: int, *, actor: str = "payment") -> None:
    """Hook tu payment service khi status -> confirmed/reconciled: hoi thoai -> completed; auto-resolve cac attention
    LIEN QUAN THANH TOAN ('payment_timeout'/'payment_mismatch') — KHONG phat notify (payment service da phat
    'payment.confirmed.notify' 1 lan). CA 274-02: late valid confirm resolve handoff, khong tao mau thuan."""
    fc = await get(conn, order_id, lock=True)
    if not fc or fc["step"] in (COMPLETED,):
        return
    now = datetime.now(timezone.utc)
    await _set_step(conn, fc, step=COMPLETED, completed_at=now)
    await _journal(conn, order_id, command_key=f"paid:{fc['version']}", source="provider" if actor.startswith("provider")
                   else "staff", from_step=fc["step"], to_step=COMPLETED, detail={"by": actor}, reply_text=None)
    for row in await conn.fetch(
            "SELECT id FROM staff_attention WHERE order_id=$1 AND status='open' "
            "AND reason IN ('payment_timeout','payment_mismatch')", order_id):
        await _att.resolve(conn, row["id"], resolved_by="system", note=f"auto: payment confirmed ({actor})")
    await audit_service.record(conn, actor_type="system", action="fulfillment.conversation_completed",
                               actor_ref=actor, entity_type="fulfillment_conversations", entity_id=str(fc["id"]),
                               after={"order_id": order_id})


class AttentionOpenError(Exception):
    """CA 275-04: con open attention -> resume bi tu choi (staff phai resolve truoc)."""


async def resume(conn, order_id: int, *, actor: str) -> dict | None:
    """Staff da xu ly ngoai le -> staff_attention -> routing (worker gui lai tong tien + hoi method). Quote thu cong
    (quote_source=staff_manual) duoc giu nguyen o advance_routing.
    CA 275-04: FAIL-CLOSED khi con open attention — buoc staff Resolve (co note) TRUOC khi Resume, tranh worker
    bao gia/gui prompt moi trong luc mismatch chua duoc xu ly. Idempotent: da routing -> None (no-op)."""
    fc = await get(conn, order_id, lock=True)
    if not fc or fc["step"] != STAFF_ATTENTION:
        return None
    open_att = await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1 AND status='open'", order_id)
    if open_att and int(open_att) > 0:
        raise AttentionOpenError(f"con {open_att} attention chua resolve — resolve truoc khi resume")
    fc2 = await _set_step(conn, fc, step=ROUTING, method_prompts=0)
    await _journal(conn, order_id, command_key=f"resume:{fc['version']}", source="staff", from_step=STAFF_ATTENTION,
                   to_step=ROUTING, detail={"by": actor}, reply_text=None)
    await audit_service.record(conn, actor_type="staff", action="fulfillment.conversation_resume", actor_ref=actor,
                               entity_type="fulfillment_conversations", entity_id=str(fc["id"]),
                               after={"order_id": order_id})
    return fc2


async def on_quote_changed(conn, order_id: int, *, actor: str) -> None:
    """Hook tu _apply_quote (staff re-quote/manual) sau khi da gui tong tien: tong da gui KHONG con dung -> chuyen
    staff_attention 'quote' de nhan vien reconfirm voi khach (KHONG tu gui tong moi)."""
    fc = await get(conn, order_id, lock=True)
    if not fc or fc["step"] not in (AWAITING_METHOD, AWAITING_TRANSFER, COD_HANDOFF):
        return
    await _set_step(conn, fc, step=STAFF_ATTENTION, attention_reason="quote", attention_at=datetime.now(timezone.utc))
    await _journal(conn, order_id, command_key=f"requote:{fc['version']}", source="staff", from_step=fc["step"],
                   to_step=STAFF_ATTENTION, detail={"reason": "quote_changed_after_prompt", "by": actor}, reply_text=None)
    await _att.open_attention(conn, order_id, reason="quote", detail={"quote_changed_after_prompt": True, "by": actor},
                              created_by=actor)


# --------------------------------------------------------------------------
async def prepare_ghn_quote(conn, order_id: int, provider=None):
    """Pha 1 (NGOAI tx): neu route = GHN va dung duoc request (weight + kich thuoc dong thung D340) -> goi provider
    (HTTP) -> QuoteResult. Khac -> None (KHONG goi provider). CA 341-01: request tu build_ghn_request (nguon duy nhat)."""
    from app.services.fulfillment import fallback_quote as _fb
    from app.services.fulfillment import routing as _r
    from app.services.providers import ghn as _ghn
    route = await _r.resolve_for_order(conn, order_id)
    if route.source != _r.GHN:
        return None
    weight = await _sh._order_weight(conn, order_id)
    if weight is None:
        return None
    req, _reason, _detail = await _fb.build_ghn_request(conn, order_id, route, weight)
    if req is None:
        return None   # thieu kich thuoc/x -> KHONG goi provider (route_and_quote -> manual)
    prov = provider or _ghn.GhnQuoteProvider()
    return await prov.quote(conn, req)


async def run_routing(*, limit: int = 25, provider=None) -> dict:
    """Cron 10s: xu ly step='routing' — pha 1 GHN quote NGOAI tx, pha 2 advance_routing TRONG tx ngan."""
    from app.db_pool import acquire, release
    from app.services.fulfillment import m7_scope as _m7s
    stats = {"claimed": 0, "advanced": 0, "errors": 0, "skipped_scope": 0}
    conn = await acquire()
    try:
        rows = await conn.fetch(
            "SELECT fc.order_id, o.customer_id FROM fulfillment_conversations fc JOIN orders o ON o.id=fc.order_id "
            "WHERE fc.step=$1 ORDER BY fc.created_at LIMIT $2", ROUTING, limit)
        for _r in rows:
            oid = _r["order_id"]
            # CA Directive 286: customer khong con eligible (removed mid-flow / khong tester) -> KHONG advance/send.
            if not _m7s.m7_enabled_for(_r["customer_id"]):
                stats["skipped_scope"] += 1
                continue
            stats["claimed"] += 1
            try:
                ghn_res = await prepare_ghn_quote(conn, oid, provider=provider)
                async with conn.transaction():
                    out = await advance_routing(conn, oid, ghn_result=ghn_res)
                if out is not None:
                    stats["advanced"] += 1
            except Exception as e:  # noqa: BLE001 — 1 don loi khong chan don khac
                stats["errors"] += 1
                from app.services.safe_log import safe_exc
                print(f"[m7] routing order {oid} loi: {safe_exc(e)}")
    finally:
        await release(conn)
    return stats
