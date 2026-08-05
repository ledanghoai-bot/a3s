"""I-B M4-S2 — trusted orchestration core: masked message -> schema-bounded model
-> trusted slot resolution -> trusted command assembly -> deterministic receipt.

QUAN TRONG (Directive §8): module nay KHONG duoc noi vao orchestrator runtime
trong authority hien tai — `m4_trusted_pii_path` van la placeholder, khong co
call site production (test tinh giu bat bien nay). Chi evidence script/pytest
goi truc tiep voi model MOCK/LOCAL — khong vendor call.

Thu tu 1 turn (spec §9):
  1. detect PII tren tin nhan tho (local);
  2. D2/high-risk -> KHONG cham vendor path, fallback 3 (local/human) NGAY;
  3. luu slot phone/name/address vao Trusted Slot Store (binding context);
  4. mask tin nhan + toan bo history;
  5. goi model (callable inject — mock trong dev) voi INPUT DA MASK;
  6. validate schema-bounded output (fail -> fallback 3, khong retry mu);
  7. intent order.create: resolve slot tu STORE theo allowlist (KHONG lay tu
     model output), lap command args bang trusted code, goi command executor
     (callable inject), tra deterministic receipt tu committed result;
  8. intent khac: rehydrate placeholder trong response candidate (fail-closed).

Fallback (spec §9): (1) deterministic prompt hoi slot thieu -> (2) structured
form khi slot co nhung confidence thap -> (3) local process/human escalation.
"""

import json
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.services.pii import sku_catalog, slot_store
from app.services.pii.detector import detect
from app.services.pii.masking import mask_history, mask_text, rehydrate_response
from app.services.pii.semantic_schema import SchemaViolation, validate_semantic_output
from app.services.pii.taxonomy import RiskClass, SlotType

# Slot bat buoc de lap order.create (allowlist resolve — spec §9 buoc 2)
ORDER_REQUIRED_SLOTS = ("phone", "address", "name")
# Confidence toi thieu moi slot khi resolve cho command (phone sai la giao hong don)
_MIN_CONF = {"phone": "high", "address": "medium", "name": "low"}
# Cau hoi deterministic cho fallback 1 (hoi 1 slot moi luot, uu tien theo thu tu tren)
_ASK_TEMPLATES = {
    "phone": "Dạ anh/chị cho em xin số điện thoại người nhận để bên em giao hàng ạ.",
    "address": "Dạ anh/chị cho em xin địa chỉ giao hàng đầy đủ (số nhà, đường, phường/xã, tỉnh/thành) ạ.",
    "name": "Dạ anh/chị cho em xin tên người nhận hàng ạ.",
}
_FORM_REPLY = ("Dạ để chắc chắn thông tin giao hàng chính xác, anh/chị điền giúp em "
               "form ngắn này nhé: {form_ref}")
_ESCALATE_REPLY = ("Dạ, em đã chuyển yêu cầu này cho nhân viên hỗ trợ rồi ạ, "
                   "sẽ có người liên hệ anh/chị ngay nhé.")
# Marker thay the noi dung history turn D2 truoc khi gui vendor (F-M4-S3-03).
_D2_TURN_MARKER = "[TURN_REDACTED_D2]"

ModelCall = Callable[[list[dict]], Awaitable[dict]]
CommandExecutor = Callable[[dict], Awaitable[dict]]
# CA F-M4-S2-04: resolver catalog inject duoc (mock trong dev test); mac dinh
# dung sku_catalog.resolve_skus tren bang products qua conn.
SkuResolver = Callable[[list[str]], Awaitable[dict[str, str | None]]]

_SKU_UNKNOWN_REPLY = ("Dạ em chưa nhận ra sản phẩm anh/chị muốn đặt ạ. Anh/chị xem giúp em "
                      "tên/mã sản phẩm trên trang shop rồi nhắn lại giúp em nhé?")


@dataclass
class TurnOutcome:
    kind: str  # reply | command_receipt | ask_slot | form | escalate
    reply: str
    receipt: dict | None = None
    asked_slot: str | None = None
    escalate_reason: str | None = None
    vendor_called: bool = False
    stored_slots: int = 0
    detail: dict = field(default_factory=dict)


def _log(event: str, **fields) -> None:
    print("[m4-flow] " + json.dumps({"event": event, **fields}, ensure_ascii=False, sort_keys=True))


def _mask_last3(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    return "***" + digits[-3:] if len(digits) >= 3 else "***"


async def process_turn(conn, *, customer_ref: str, conversation_ref: str, text: str,
                       history: list[dict] | None = None,
                       model_call: ModelCall, command_executor: CommandExecutor,
                       sku_resolver: SkuResolver | None = None,
                       source_message_ref: str | None = None,
                       form_ref: str = "[FORM_GIAO_HANG]") -> TurnOutcome:
    history = history or []

    # 1-2. Detect local + chan D2/high-risk TRUOC vendor path (spec §5.6, §9 fallback 3)
    det = detect(text)
    if det.risk_class == RiskClass.D2:
        _log("m4_flow_vendor_blocked", reason="d2_high_risk",
             categories=sorted(c.value for c in det.sensitive_categories))
        return TurnOutcome(kind="escalate", reply=_ESCALATE_REPLY,
                           escalate_reason="d2_high_risk")

    # 2b. CA F-M4-S3-03: sweep risk TUNG history turn truoc vendor call. Policy
    # fail-closed da chon (minimize theo contract): turn D2 bi THAY TOAN BO noi
    # dung bang marker trung tinh — khong bao gio den vendor, hoi thoai van tiep
    # tuc (D2 cu khong chan vinh vien conversation). Telemetry CHI reason/count.
    redacted_d2 = 0
    safe_history: list[dict] = []
    for turn in history:
        if detect(str(turn.get("content", ""))).risk_class == RiskClass.D2:
            redacted_d2 += 1
            safe_history.append({"role": turn.get("role", "user"),
                                 "content": _D2_TURN_MARKER})
        else:
            safe_history.append(turn)
    if redacted_d2:
        _log("m4_flow_history_d2_redacted", count=redacted_d2)
    history = safe_history

    # 3. Luu slot D1 (phone/name/address) vao store — binding (customer, conversation).
    stored = 0
    storable = {SlotType.PHONE.value, SlotType.NAME.value, SlotType.ADDRESS.value}
    for span in det.spans:
        if span.slot_type.value not in storable:
            continue
        await slot_store.store_slot(
            conn, customer_ref=customer_ref, conversation_ref=conversation_ref,
            slot_type=span.slot_type.value, value=text[span.start:span.end],
            confidence=span.confidence.value, data_class="D1",
            purpose_code="P02_COMMERCE",  # canonical id theo Purpose Registry M3
            source_message_ref=source_message_ref)
        stored += 1

    # 4. Mask current + history (assistant turns cung mask — receipt cu co PII
    # khach). S3: placeholder LUON kem integrity tag bind conversation nay.
    # CA F-M4-S3-02: MOT namespace counters duy nhat cho history + current ->
    # placeholder khong bao gio trung; guard collision fail-closed phong thu sau.
    counters: dict[str, int] = {}
    masked_hist, hist_map = mask_history(history, conversation_ref=conversation_ref,
                                         counters=counters)
    cur = mask_text(text, counters, conversation_ref=conversation_ref)
    if set(hist_map) & set(cur.mapping):
        _log("m4_flow_placeholder_collision", count=len(set(hist_map) & set(cur.mapping)))
        return TurnOutcome(kind="escalate", reply=_ESCALATE_REPLY,
                           escalate_reason="placeholder_collision", stored_slots=stored)
    mapping = {**hist_map, **cur.mapping}
    masked_messages = masked_hist + [{"role": "user", "content": cur.masked_text}]

    # 5. Model call — INPUT DA MASK. Loi model -> fallback 3 (fail-closed).
    try:
        raw_output = await model_call(masked_messages)
    except Exception as e:  # noqa: BLE001 — bien loi vendor/mock thanh escalation
        _log("m4_flow_model_error", error_type=type(e).__name__)
        return TurnOutcome(kind="escalate", reply=_ESCALATE_REPLY,
                           escalate_reason="model_error", vendor_called=True,
                           stored_slots=stored)

    # 6. Schema-bounded validation — violation la fail-closed, KHONG retry mu.
    try:
        sem = validate_semantic_output(raw_output)
    except SchemaViolation as v:
        _log("m4_flow_schema_violation", reasons=v.reasons)
        return TurnOutcome(kind="escalate", reply=_ESCALATE_REPLY,
                           escalate_reason="schema_violation", vendor_called=True,
                           stored_slots=stored, detail={"reasons": v.reasons})

    # 7. order.create: resolve tu STORE (allowlist) — model KHONG cap gia tri nao.
    if sem.intent == "order.create":
        if not sem.items:
            # khong co items non-PII hop le -> khong lap don; hoi lai bang duong thuong
            return TurnOutcome(kind="reply",
                               reply="Dạ anh/chị muốn đặt sản phẩm nào, số lượng bao nhiêu ạ?",
                               vendor_called=True, stored_slots=stored)

        # 7a. CA F-M4-S2-04: SKU authority = TRUSTED CATALOG, khong phai model.
        # Moi SKU model de xuat phai resolve ve canonical qua catalog; command
        # args CHI nhan canonical string cua resolver. Unknown/ambiguous ->
        # deterministic fallback (KHONG echo raw string — co the la PII
        # transliterate); catalog loi -> escalate fail-closed. Executor khong
        # chay trong moi truong hop tren.
        try:
            if sku_resolver is not None:
                sku_map = await sku_resolver([it["sku"] for it in sem.items])
            else:
                sku_map = await sku_catalog.resolve_skus(conn, [it["sku"] for it in sem.items])
        except Exception as e:  # noqa: BLE001 — catalog unavailable = fail closed
            _log("m4_flow_catalog_error", error_type=type(e).__name__)
            return TurnOutcome(kind="escalate", reply=_ESCALATE_REPLY,
                               escalate_reason="catalog_error", vendor_called=True,
                               stored_slots=stored)
        unknown_count = sum(1 for v in sku_map.values() if v is None)
        if unknown_count:
            _log("m4_flow_sku_unknown", count=unknown_count)
            return TurnOutcome(kind="reply", reply=_SKU_UNKNOWN_REPLY,
                               vendor_called=True, stored_slots=stored,
                               detail={"unknown_sku_count": unknown_count})
        canonical_items = [{"sku": sku_map[it["sku"]], "qty": it["qty"]}
                           for it in sem.items]

        resolved: dict[str, str] = {}
        missing: list[str] = []
        low_conf: list[str] = []
        for slot in ORDER_REQUIRED_SLOTS:
            val = await slot_store.resolve_slot(
                conn, customer_ref=customer_ref, conversation_ref=conversation_ref,
                slot_type=slot, min_confidence=_MIN_CONF[slot])
            if val is not None:
                resolved[slot] = val
                continue
            # co slot nhung duoi nguong confidence? -> fallback 2 (form)
            any_conf = await slot_store.resolve_slot(
                conn, customer_ref=customer_ref, conversation_ref=conversation_ref,
                slot_type=slot, min_confidence="low")
            (low_conf if any_conf is not None else missing).append(slot)

        if missing:
            ask = next(s for s in ORDER_REQUIRED_SLOTS if s in missing)
            _log("m4_flow_ask_slot", slot=ask, missing_count=len(missing))
            return TurnOutcome(kind="ask_slot", reply=_ASK_TEMPLATES[ask],
                               asked_slot=ask, vendor_called=True, stored_slots=stored)
        if low_conf:
            _log("m4_flow_form_fallback", slots=sorted(low_conf))
            return TurnOutcome(kind="form",
                               reply=_FORM_REPLY.format(form_ref=form_ref),
                               vendor_called=True, stored_slots=stored,
                               detail={"low_confidence_slots": sorted(low_conf)})

        # Trusted assembly: refs tu THAM SO trusted, PII tu STORE, items tu context.
        command_args = {
            "customer_ref": customer_ref,
            "conversation_ref": conversation_ref,
            "shipping_phone": resolved["phone"],
            "shipping_address": resolved["address"],
            "shipping_name": resolved["name"],
            "items": canonical_items,  # CHI canonical SKU tu trusted resolver
            "source_message_ref": source_message_ref,
        }
        committed = await command_executor(command_args)
        # 8. Deterministic receipt tu committed result — echo phone DANG MASK
        receipt_reply = (
            f"Dạ em đã lên đơn thành công ạ. Mã đơn: {committed['order_id']}. "
            f"Giao tới {resolved['address']} — người nhận {resolved['name']}, "
            f"SĐT {_mask_last3(resolved['phone'])}. Em cảm ơn anh/chị nhiều ạ!"
        )
        _log("m4_flow_command_receipt", items=len(canonical_items))
        return TurnOutcome(kind="command_receipt", reply=receipt_reply,
                           receipt=committed, vendor_called=True, stored_slots=stored)

    # Intent thuong: rehydrate placeholder fail-closed (sua/thieu/lap/cross-context
    # -> escalate; tag phai khop conversation nay — spec §10)
    rehydrated = rehydrate_response(sem.response_candidate, mapping,
                                    conversation_ref=conversation_ref)
    if rehydrated is None:
        _log("m4_flow_placeholder_reject")
        return TurnOutcome(kind="escalate", reply=_ESCALATE_REPLY,
                           escalate_reason="placeholder_reject", vendor_called=True,
                           stored_slots=stored)
    return TurnOutcome(kind="reply", reply=rehydrated, vendor_called=True,
                       stored_slots=stored)
