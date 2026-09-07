"""Loi agent: nhan tin nhan, sinh cau tra loi bang DeepSeek + RAG + tool calling.

Luong:
1. Lay lich su hoi thoai tu Redis (TTL 24h)
2. Tim top-4 chunks lien quan tu knowledge base (RAG) - kien thuc san pham tinh
   (cach pha, huong vi...), KHONG dung cho gia/ton kho/don hang.
3. Goi DeepSeek voi system prompt + RAG context + lich su + tool schema (TOOL_DEFINITIONS)
4. Neu model tra ve tool_calls: thuc thi tool that (DB that qua app/services/tools.py),
   nap ket qua tool nguoc lai cho model, lap lai toi da MAX_TOOL_ITERATIONS vong
5. Luu tin nhan (user + cau tra loi cuoi cung) vao Redis - KHONG luu buoc trung gian
   tool_calls de lich su gon nhe. Dong thoi ghi vao Postgres (bang messages) qua
   app/services/conversation_log.py de dashboard (#8) doc lai duoc lich su lau dai.
6. Tra ve cau tra loi cuoi cung
"""

import hashlib
import json
from pathlib import Path
from time import perf_counter

import redis.asyncio as aioredis
from openai import AsyncOpenAI

from app.config import settings
from app.services import conversation_log, data_deletion, handoff, products, tools
from app.services.address import live_verify as address_live_verify
from app.services.address.acceptance_gate import normalize as _normalize_admin
from app.services.messenger_profile import get_user_profile
from app.services.nlu_hint import get_nlu_hint
from app.services.pii import shadow as pii_shadow
from app.services.rag import search_knowledge
from app.services.safe_log import safe_exc

SYSTEM_PROMPT = (
    Path(__file__).resolve().parents[1] / "prompts" / "system_prompt.md"
).read_text(encoding="utf-8")

MAX_HISTORY = 10  # so luot chat giu lai (moi luot = 1 user + 1 assistant)
MAX_TOOL_ITERATIONS = 4  # chan vong lap tool_calls vo han neu model lien tuc goi tool

# Ngan sach token dau ra moi lan goi LLM. QUAN TRONG: model hien tai (deepseek-v4-flash)
# la model CO SUY LUAN - no sinh 'reasoning_content' (chuoi suy nghi) TRUOC khi sinh
# 'content'/'tool_calls', va reasoning_content cung tinh vao max_tokens. Voi budget cu 512,
# phan suy luan cho don hang (nhieu rang buoc: ten/sdt/dia chi/sku/so luong + xac nhan)
# thuong dot het budget -> API tra finish_reason='length' voi content RONG va KHONG co
# tool_call nao -> orchestrator roi vao fallback rong ("Doi ngu 3S Coffee se kiem tra va
# phan hoi..."), khong bao gio goi create_order (chinh la trieu chung canary Directive 207).
# Do bang API that: 512 hay bi cat, >=4096 thi create_order dat toi tin cay. Cap nay chi
# CHAN cat ngang, KHONG lam model suy luan dai them (model suy luan theo nhu cau, khong
# theo cap). Cau tra loi hien thi van ngan (~250-360 ky tu).
MAX_OUTPUT_TOKENS = 4096

# Kenh BAT BUOC khai bao "tro ly tu dong" o tin dau (yeu cau Meta App Review cho
# Messenger). Cac kenh khac (telegram/zalo/web) chi KHUYEN NGHI - xem mo ta bom
# vao system prompt ben duoi + docs/META-APP-REVIEW-VI.md §7. Truyen channel
# TUONG MINH tu tung caller (khong suy tu prefix sender_id) - bai hoc CLAUDE.md.
DISCLOSURE_REQUIRED_CHANNELS = {"messenger"}

# Dau hieu reply DANG BAO da tao don (dung de chan bia don - xem guard trong
# handle_message). Model chi duoc noi cac cum nay khi create_order that su tra
# ve order_id trong luot hien tai.
_ORDER_CLAIM_MARKERS = (
    "mã đơn",
    "đơn hàng đã được tạo",
    "đơn đã được tạo",
    "đơn của anh đã được tạo",
    "đơn của chị đã được tạo",
    "đã tạo đơn",
    "tạo đơn thành công",
    "đặt hàng thành công",
    "lên đơn thành công",
    "đơn hàng thành công",
)


def _reply_claims_order_created(reply: str) -> bool:
    """True neu reply co dau hieu bao KHACH rang don da duoc tao (de doi chieu
    voi viec create_order co that su chay thanh cong trong luot nay hay khong)."""
    low = reply.lower()
    return any(marker in low for marker in _ORDER_CLAIM_MARKERS)


# M5 discovery fix (CA 223 §5.5): tin khach HOI trang thai don CU (khong phai dat don moi). Dung de
# guard chong-bia KHONG escalate nham tren order-status query. So khop tren text da bo dau.
_ORDER_STATUS_MARKERS = (
    "kiem tra don", "trang thai don", "don hom qua", "don da dat", "don cua toi", "don cua minh",
    "don cua anh", "don cua chi", "check don", "xem don", "don truoc", "tra cuu don", "don da mua",
)


def _is_order_status_query(text: str) -> bool:
    t = _normalize_admin(text or "")
    return any(m in t for m in _ORDER_STATUS_MARKERS)


# M5 upgrade (Directive 214 §6.D + Memo 213 §6): TAT reasoning cho duong tool-calling giao dich.
# deepseek-v4-flash la REASONING model -> reasoning_content dot max_tokens + lam cham (den phut qua
# nhieu vong tool). Probe xac nhan extra_body={"thinking":{"type":"disabled"}} -> ~1.5s, tool-calling
# nguyen ven, het truncation 'length'. Giu FALLBACK khi provider KHONG ho tro tham so (Memo 213 §6):
# thu 1 lan co extra_body; neu bi tu choi dung tham so 'thinking' thi nho lai + goi lai KHONG co param.
_THINKING_DISABLED_BODY = {"thinking": {"type": "disabled"}}
_thinking_control_supported = True  # optimistic; flip False khi provider tu choi param


def _thinking_unsupported(exc: Exception) -> bool:
    """True neu loi la do tham so 'thinking' khong duoc provider ho tro (KHONG nuot loi khac)."""
    s = str(exc).lower()
    if "thinking" not in s:
        return False
    return any(t in s for t in ("unsupported", "invalid", "unexpected", "not support",
                                "deserialize", "unknown", "extra"))


async def _llm_create(client, **kwargs):
    """chat.completions.create voi thinking TAT (khi bat + duoc ho tro), fallback an toan 1 lan."""
    global _thinking_control_supported
    if settings.disable_llm_reasoning and _thinking_control_supported:
        try:
            return await client.chat.completions.create(extra_body=_THINKING_DISABLED_BODY, **kwargs)
        except Exception as e:  # noqa: BLE001 — chi fallback khi dung loi tham so thinking
            if _thinking_unsupported(e):
                _thinking_control_supported = False
                print(f"[orchestrator] thinking.disabled khong duoc ho tro -> fallback bo param: "
                      f"{safe_exc(e)}")
            else:
                raise
    return await client.chat.completions.create(**kwargs)


# M5 upgrade (Directive 214 §6.B + Q2 + Memo 213 §4-5): clarify-before-escalate. SERVER lam chu outcome
# + dem luot; LLM chi DIEN DAT cau hoi. <=2 luot hoi lam ro/dia chi chua verify, giu bot ACTIVE; het luot
# moi escalate. may_bind CHI tu server (auto_verified) — LLM khong the tu nang status/chon resolution.
_ADDRESS_CLARIFY_MAX = 2


def _proposal_fp(prov_prop, ward_prop) -> str:
    """Fingerprint XAC DINH cua de xuat dia chi hanh chinh (CA Review 216-02): normalize (bo dau/hoa/space
    NHAT QUAN) -> sha256 rut gon. Cung proposal (khac dau/cach viet) -> cung fp -> tiep tuc attempt; doi
    tinh/phuong thuc chat -> fp khac -> attempt moi (dem lai)."""
    # Normalize TUNG phan rieng (moi phan tu strip khoang trang cua no) roi noi — tranh khoang trang
    # quanh dau phan cach lam lech fingerprint giua cac bien the cung proposal.
    p = _normalize_admin(prov_prop if isinstance(prov_prop, str) else "")
    w = _normalize_admin(ward_prop if isinstance(ward_prop, str) else "")
    return hashlib.sha256(f"{p}|{w}".encode("utf-8")).hexdigest()[:16]


def _clarify_key(sender_id: str, prov_prop, ward_prop) -> str:
    # State thuoc (tester identity + proposal hien tai), KHONG chi tester -> dia chi moi khong ke thua
    # count cu (216-02). sender_id la danh tinh server-side.
    return f"addr_clarify:{sender_id}:{_proposal_fp(prov_prop, ward_prop)}"


async def _address_clarify(sender_id: str, vr: dict, prov_prop, ward_prop) -> dict | None:
    """Tra tool-result huong dan LLM HOI khach xac nhan dia chi (server-owned). None = da het <=2 luot
    (caller escalate). Dem luot keyed theo (sender + fingerprint proposal HIEN TAI), TTL 30 phut."""
    key = _clarify_key(sender_id, prov_prop, ward_prop)
    r = await aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 1800)
    finally:
        await r.aclose()
    if n > _ADDRESS_CLARIFY_MAX:
        return None  # het luot -> escalate (caller)
    pname = vr.get("province_name") or (prov_prop if isinstance(prov_prop, str) else "")
    wname = vr.get("ward_name") or (ward_prop if isinstance(ward_prop, str) else "")
    predicted = ", ".join(x for x in (wname, pname) if x)
    return {
        "address_needs_clarification": True,
        "resolver_outcome": vr.get("status"),
        "predicted_admin": predicted or None,
        "instruction": (
            "Dia chi hanh chinh CHUA duoc xac minh tu dong. "
            + (f"Du doan: {predicted}. HOI khach XAC NHAN co dung khong. " if predicted
               else "HOI khach cho biet ro TINH va PHUONG/XA. ")
            + "Neu chua dung, xin lai tinh/phuong. TUYET DOI CHUA tao don (chua goi lai create_order), "
            "KHONG noi da tao don. Sau khi khach xac nhan/sua thi moi thu tao don lai."),
    }


async def _address_clarify_reset(sender_id: str, prov_prop=None, ward_prop=None) -> None:
    """Ket thuc attempt clarify (khi dia chi verified/tao don thanh cong hoac escalate). Xoa dung key
    cua proposal hien tai."""
    r = await aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.delete(_clarify_key(sender_id, prov_prop, ward_prop))
    finally:
        await r.aclose()


def _redis_key(sender_id: str) -> str:
    return f"chat:{sender_id}"


async def _get_history(redis, sender_id: str) -> list[dict]:
    raw = await redis.get(_redis_key(sender_id))
    if not raw:
        return []
    return json.loads(raw)


async def _save_history(redis, sender_id: str, history: list[dict]) -> None:
    # Giu toi da MAX_HISTORY luot, TTL 24h
    trimmed = history[-(MAX_HISTORY * 2):]
    await redis.set(_redis_key(sender_id), json.dumps(trimmed, ensure_ascii=False), ex=86400)


# CA 225-05: tin hieu "don moi tuong minh" SERVER-OWNED (orchestrator tinh tu raw text khach, LLM KHONG
# duoc cap). CHI dung de PHAN BIET giua stale-confirmation vs dat-them SAU khi da co committed intent cung
# fingerprint (drive() ap explicit_new_order o nhanh nay). Cum tu re-order do dac hieu (dat them/don nua/
# mua them) — KHONG phai xac nhan tran ("ok"/"dung"/"xac nhan") -> false-positive tren stale-confirm rat
# thap. KHONG keyword-alone: chi co hieu luc khi durable committed intent cung fingerprint ton tai.
_REORDER_MARKERS = (
    "dat them", "them mot don", "them 1 don", "mot don nua", "1 don nua", "them don",
    "don nua", "mua them", "order them", "dat mot don nua", "dat 1 don nua", "lam them",
)


def _is_explicit_reorder(text: str) -> bool:
    """True neu khach TUONG MINH muon dat THEM 1 don (khong phai xac nhan don vua roi). Server-side,
    bo dau 2 phia (marker da bo dau)."""
    t = _normalize_admin(text or "")
    return any(m in t for m in _REORDER_MARKERS)


_CANCEL_MARKERS = ("huy don", "huy bo don", "khong dat nua", "khong mua nua", "khong lay nua",
                   "thoi khong mua", "bo don", "huy don hang")


def _is_explicit_cancel(text: str) -> bool:
    """True neu khach TUONG MINH huy don dang dat (CA 225-01 cancel transition). Server-side, high-precision
    (khong bat 'khong' tran)."""
    t = _normalize_admin(text or "")
    return any(m in t for m in _CANCEL_MARKERS)


# CA 226-03: nhan dien SO KHOI "order proposal" (server-owned draft recognition) de tao COLLECTING intent
# durable khi khach bat dau dat don NHUNG chua du thong tin (LLM chua goi create_order). KHONG phai NLU
# platform — chi marker dat-hang do dac hieu, LOAI TRU order-status. Sai duong tinh -> COLLECTING vo hai
# (het han 24h, 0 don); sai am tinh -> COLLECTING tao khi create_order (drive) — van dung.
_ORDER_INTENT_MARKERS = (
    "dat hang", "dat mua", "dat 1", "dat mot", "dat 2", "dat goi", "dat ly", "dat hop", "dat don",
    "mua goi", "mua 1", "mua mot", "lay goi", "cho minh 1", "cho minh mot", "cho toi 1", "cho toi mot",
    "cho minh dat", "cho toi dat", "minh muon dat", "toi muon dat", "muon dat", "order",
)


def _is_order_intent(text: str) -> bool:
    """True neu tin nhan la YEU CAU DAT DON (khoi tao/dang gom), KHONG phai order-status/chat thuong."""
    if _is_order_status_query(text):
        return False
    t = _normalize_admin(text or "")
    return any(m in t for m in _ORDER_INTENT_MARKERS)


async def _ensure_collecting_intent(sender_id: str, conversation_id, channel: str) -> None:
    """CA 226-03b: dam bao co MOT open intent (COLLECTING) cho hoi thoai khi khach dang dat don ma chua
    commit/chua co open intent. Message sau tai dung (get-or-create) -> progress cung intent. Chi cho
    enrolled-eligible (m1 HOAC Gate E pilot). Best-effort, khong vo reply."""
    try:
        from app.db_pool import acquire as _acq
        from app.db_pool import release as _rel
        from app.services.command import order_gateway as _ogw
        from app.services.command import order_intent_service as _svc
        cmd_ctx = {"channel": channel}
        eligible = _ogw.can_route(channel) and (
            settings.m1_reliable_order_command or await tools._gate_e_pilot_route(sender_id, cmd_ctx))
        if not eligible:
            return
        _c = await _acq()
        try:
            cid = await _c.fetchval("SELECT id FROM customers WHERE psid=$1", sender_id)
            if cid is None:
                return
            async with _c.transaction():
                open_row = await _svc.find_open_intent(
                    _c, customer_id=cid, conversation_id=conversation_id, for_update=True)
                if open_row is None:
                    await _svc.create_intent(_c, customer_id=cid, conversation_id=conversation_id,
                                             channel=channel)  # COLLECTING durable, 0 order
        finally:
            await _rel(_c)
    except Exception as e:  # noqa: BLE001
        print(f"[orchestrator] ensure COLLECTING intent skipped: {safe_exc(e)}")


async def _execute_tool(name: str, args: dict, sender_id: str, last_message: str,
                        command_ctx: dict | None = None) -> dict:
    """Dispatch 1 tool call toi ham that trong app/services/tools.py.

    psid (sender_id) va last_message duoc bom o day, KHONG lay tu args model
    tra ve - tranh model tu bia/nham lan sender_id hoac tin nhan goc cua khach.
    command_ctx (I-B M1): boi canh idempotency/actor cho create_order (chi khi flag bat).
    """
    try:
        if name == "search_products":
            return await tools.search_products(**args)
        if name == "check_stock":
            return await tools.check_stock(**args)
        if name == "create_order":
            # M5 Nửa A (Directive 196 + Review 197): tach de xuat ten tinh/phuong khoi args -> KHONG di vao
            # create_order (order free-text giu nguyen, §3.12). create_order signature khong doi.
            prov_prop = args.pop("province", None)
            ward_prop = args.pop("ward", None)
            # C1: verify + auto-link chay TRUOC create_order -> khi Gate E bat, pointer verified da san sang
            # cho create_order (khong deadlock). Flag default OFF; loi KHONG BAO GIO lam vo reply/don (§3.11,
            # bat NGOAI transaction verify). C3: KHONG fallback sender_id — thieu event id that thi verify skip.
            # --- Enrolled route? (command bus se xu ly: m1 global HOAC Gate E pilot) ---
            _enrolled = False
            if command_ctx is not None:
                try:
                    from app.services.command import order_gateway as _ogw
                    _enrolled = _ogw.can_route(command_ctx.get("channel", "")) and (
                        settings.m1_reliable_order_command
                        or await tools._gate_e_pilot_route(sender_id, command_ctx))
                except Exception as e:  # noqa: BLE001
                    print(f"[orchestrator] enrolled-route check loi: {safe_exc(e)}")
                    _enrolled = False
            # --- Verify dia chi (§6.C sua F2) -> verified + fingerprint canonical (225-06) ---
            vr = None
            _verified = not settings.enable_address_resolver  # resolver OFF: khong co address gate
            if settings.enable_address_resolver:
                try:
                    vr = await address_live_verify.verify_and_link(
                        psid=sender_id, channel=(command_ctx or {}).get("channel"),
                        province_proposal=prov_prop, ward_proposal=ward_prop,
                        event_id=(command_ctx or {}).get("provider_message_id"))
                    if vr.get("may_bind") and vr.get("resolution_id"):
                        _verified = True
                        if command_ctx is not None:
                            command_ctx["verified_resolution_id"] = vr["resolution_id"]
                            from app.services.command import order_intent as _oi
                            _detail = _oi.canonical_delivery_detail(
                                args.get("address"), vr.get("province_name"), vr.get("ward_name"))
                            command_ctx["verified_address_fingerprint"] = _oi.verified_address_fingerprint(
                                vr.get("dataset_version"), vr.get("province_code"), vr.get("ward_code"), _detail)
                        await _address_clarify_reset(sender_id, prov_prop, ward_prop)
                except Exception as e:  # noqa: BLE001 — never break the customer reply/order
                    print(f"[orchestrator] M5 live address verify skipped: {safe_exc(e)}")
                    vr = None
            # --- INTENT CONTROL PLANE (CA 225-01): tren enrolled route, intent DRIVE lifecycle + la truth ---
            if _enrolled and command_ctx is not None:
                from app.db_pool import acquire as _acq
                from app.db_pool import release as _rel
                from app.services.command import order_intent as _oi
                from app.services.command import order_intent_flow as _oif
                _cid = None
                try:
                    _c = await _acq()
                    try:
                        _cid = await _c.fetchval("SELECT id FROM customers WHERE psid=$1", sender_id)
                    finally:
                        await _rel(_c)
                except Exception as e:  # noqa: BLE001
                    print(f"[orchestrator] intent customer resolve loi: {safe_exc(e)}")
                _ofp = _oi.order_fingerprint(
                    sku=args.get("sku", ""), quantity=args.get("quantity"),
                    customer_name=args.get("customer_name", ""), phone=args.get("phone", ""),
                    address_fp=command_ctx.get("verified_address_fingerprint"))
                drive = await _oif.drive(
                    customer_id=_cid, conversation_id=command_ctx.get("conversation_id"),
                    channel=command_ctx["channel"], order_fp=_ofp,
                    addr_fp=command_ctx.get("verified_address_fingerprint"),
                    verified_resolution_id=command_ctx.get("verified_resolution_id"),
                    verified=_verified, explicit_new_order=_is_explicit_reorder(last_message))
                _act = drive.get("action")
                if _act in ("ready", "duplicate"):
                    # ready -> intent READY_TO_COMMIT (commit ben duoi); duplicate -> intent COMMITTED
                    # (stale-confirm, _run_winner tra receipt cu ZERO mutation + finalize replay row 225-03).
                    command_ctx["order_intent_id"] = drive["order_intent_id"]
                elif _act == "clarify":
                    # 225-01: intent da o NEEDS_CLARIFICATION (durable) TRUOC khi hoi. UX <=2 luot; het -> escalate.
                    clarify = await _address_clarify(sender_id, vr, prov_prop, ward_prop) if vr else None
                    if clarify is not None:
                        return clarify
                    await tools.escalate_to_human(
                        psid=sender_id, reason="Dia chi khong xac minh duoc sau 2 luot lam ro",
                        last_message=last_message)
                    await _oif.terminalize(customer_id=_cid,
                                           conversation_id=command_ctx.get("conversation_id"),
                                           to_state="ESCALATED", reason="address_unresolved")
                    await _address_clarify_reset(sender_id, prov_prop, ward_prop)
                    return {"address_unresolved_escalated": True,
                            "instruction": ("Da chuyen nhan vien ho tro xac minh dia chi. Bao khach doi "
                                            "phan hoi trong it phut. KHONG noi da tao don.")}
                elif _act == "error":
                    # FAIL-CLOSED (225-04): khong thiet lap/validate duoc intent tren enrolled route -> KHONG
                    # tao don (zero mutation), tra loi an toan (khong khang dinh da dat hang).
                    print(f"[orchestrator] order-intent FAIL-CLOSED sender={sender_id}")
                    return {"error": "He thong dang ban, em chua chot duoc don. Anh/chi thu lai giup em sau it phut a.",
                            "intent_fail_closed": True}
                # _act == 'skip' -> khong enrolled thuc su -> legacy (order_intent_id None)
            result = await tools.create_order(psid=sender_id, command_ctx=command_ctx, **args)
            return result
        if name == "escalate_to_human":
            return await tools.escalate_to_human(psid=sender_id, last_message=last_message, **args)
        return {"error": f"Tool khong ton tai: {name}"}
    except TypeError as e:
        # Model truyen sai/thieu tham so so voi schema
        return {"error": f"Tham so khong hop le cho tool '{name}': {safe_exc(e)}"}
    except Exception as e:
        print(f"[orchestrator] Tool '{name}' loi: {safe_exc(e)}")
        return {"error": f"Loi he thong khi chay tool '{name}', vui long thu lai."}


async def handle_message(sender_id: str, text: str, channel: str = "messenger",
                         provider_message_id: str | None = None) -> str:
    # provider_message_id (CR-04): mid Messenger / message_id Telegram — neo causation + idempotency
    # key cho command (order.create). None -> fallback sender_id.
    # channel: kenh goi toi (tuong minh, do caller truyen) - quyet dinh muc do
    # bat buoc khai bao "tro ly tu dong". Mac dinh "messenger" (kenh chinh).
    _t_start = perf_counter()  # M5 upgrade §6.D: do end-to-end handle_message (SAFE, khong payload)
    # Ket noi Redis
    redis = await aioredis.from_url(settings.redis_url, decode_responses=True)

    try:
        # -1. Dam bao co conversation trong Postgres cho dashboard (issue #8) -
        # doc lai duoc lich su lau dai, khac voi Redis chi giu 24h.
        conversation_id = await conversation_log.ensure_conversation(sender_id)

        # -0.5. I-B M4-S0 shadow: quet PII cuc bo (regex thuan, khong model/vendor)
        # de do recall/precision cho gate M4-G1. CHI quan sat — khong doi response/
        # tool flow, khong cham vendor path; loi detector bi nuot trong shadow_scan
        # (khong bao gio vo flow tra loi). Flag MAC DINH TAT (Directive §8).
        if settings.m4_pii_shadow:
            pii_shadow.shadow_scan(text)

        # 0. Luoi an toan deterministic: khach CHU DONG doi gap nguoi that ->
        # escalate ngay, KHONG di qua LLM (khong phu thuoc LLM co nho goi tool
        # dung luc hay khong - xem ghi chu "rui ro cao nhat" o ISSUES.md #7).
        # CA 225-01: cancel/escalate transition INTENT that (durable), khong chi Redis/UX. Resolve
        # customer_id server-side de terminalize open intent hien tai (best-effort, khong vo reply).
        async def _terminalize_open_intent(to_state: str, reason: str) -> None:
            try:
                from app.db_pool import acquire as _acq
                from app.db_pool import release as _rel
                from app.services.command import order_intent_flow as _oif
                _c = await _acq()
                try:
                    _cid = await _c.fetchval("SELECT id FROM customers WHERE psid=$1", sender_id)
                finally:
                    await _rel(_c)
                if _cid is not None:
                    await _oif.terminalize(customer_id=_cid, conversation_id=conversation_id,
                                           to_state=to_state, reason=reason)
            except Exception as e:  # noqa: BLE001
                print(f"[orchestrator] terminalize open intent skipped: {safe_exc(e)}")

        # CA 226-03: khach TUONG MINH huy don -> transition open intent CANCELLED (durable) + SHORT-CIRCUIT
        # luot nay (KHONG vao LLM loop -> KHONG the goi create_order tao intent/don moi undo cancel). Tra
        # phan hoi huy tat dinh.
        if _is_explicit_cancel(text):
            await _terminalize_open_intent("CANCELLED", "customer_cancel")
            reply = ("Dạ em đã huỷ yêu cầu đặt hàng đang xử lý cho anh/chị rồi ạ. "
                     "Khi nào cần đặt lại, anh/chị nhắn em nhé.")
            history = await _get_history(redis, sender_id)
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": reply})
            await _save_history(redis, sender_id, history)
            await conversation_log.log_message(conversation_id, "customer", text)
            await conversation_log.log_message(conversation_id, "bot", reply)
            return reply

        if handoff.wants_human(text):
            await _terminalize_open_intent("ESCALATED", "customer_wants_human")
            await tools.escalate_to_human(
                psid=sender_id,
                reason="Khach chu dong yeu cau gap nhan vien",
                last_message=text,
            )
            reply = (
                "Dạ, em đã chuyển yêu cầu này cho nhân viên hỗ trợ rồi ạ, "
                "sẽ có người liên hệ anh/chị ngay nhé."
            )
            history = await _get_history(redis, sender_id)
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": reply})
            await _save_history(redis, sender_id, history)
            await conversation_log.log_message(conversation_id, "customer", text)
            await conversation_log.log_message(conversation_id, "bot", reply)
            return reply

        # 0.1. Self-service XOA DU LIEU (khach chu dong) - deterministic, KHONG
        # qua LLM (giong luoi wants_human). 2 buoc de tranh xoa nham vi xoa la
        # KHONG KHOI PHUC duoc. Xoa theo dung sender_id -> chac chan danh tinh
        # (khach dang nhan tin tu chinh tai khoan cua ho). Xem data_deletion.py.
        # Kiem is_delete_confirm TRUOC vi "xac nhan xoa du lieu" khop ca hai cum.
        if data_deletion.is_delete_confirm(text):
            pending = await redis.get(f"del_pending:{sender_id}")
            if pending:
                await redis.delete(f"del_pending:{sender_id}")
                result = await data_deletion.process_deletion(sender_id)
                reply = data_deletion.customer_deletion_report(result)
                # KHONG log/luu lai sau khi xoa: log_message se ensure_conversation
                # -> tao lai customer vua xoa. Tra thang cho kenh gui.
                return reply
            reply = (
                "Dạ, để xóa dữ liệu, anh/chị vui lòng nhắn 'XÓA DỮ LIỆU' trước, "
                "rồi làm theo hướng dẫn xác nhận ạ."
            )
            history = await _get_history(redis, sender_id)
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": reply})
            await _save_history(redis, sender_id, history)
            await conversation_log.log_message(conversation_id, "customer", text)
            await conversation_log.log_message(conversation_id, "bot", reply)
            return reply

        if data_deletion.is_delete_request(text):
            await redis.set(f"del_pending:{sender_id}", "1", ex=900)  # cho xac nhan 15 phut
            reply = data_deletion.confirm_prompt()
            history = await _get_history(redis, sender_id)
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": reply})
            await _save_history(redis, sender_id, history)
            await conversation_log.log_message(conversation_id, "customer", text)
            await conversation_log.log_message(conversation_id, "bot", reply)
            return reply

        # 1. Lay lich su + profile khach (ten tu Messenger Graph API - CHI goi
        # cho khach Messenger that; cac kenh khac nhu Telegram (sender_id dang
        # "tg:<chat_id>") khong co Graph API tuong duong nen bo qua, tranh goi
        # API that vo ich moi luot chat - issue "nhieu kenh" phat sinh tu vu Meta
        # khoa test user, xem ISSUES.md.
        history = await _get_history(redis, sender_id)
        if sender_id.startswith("tg:") or sender_id.startswith("manual:"):
            profile = {}
        else:
            profile = await get_user_profile(redis, sender_id)

        # 2. Kien thuc tham khao: Knowledge Base V2 (#11) THAY THE RAG cu (#4)
        # tu 23/7 theo chi dao PO ("cach pha phai tuan theo quy trinh KB V2") -
        # phat hien XUNG DOT kien thuc khi test Telegram that: RAG cu
        # (data/knowledge, vd "dinh luong chuan 2g/ly", "muong 2g") lech voi
        # KB V2 da duyet ("1 muong ~ 1g", khong dua cong thuc cung, caffeine
        # 4,1%). KB V2 phu rong hon han (BRAND/PRD/ORD/TASTE/BREW/CAF/HEALTH,
        # 364 unit vs 51 chunk). Chi lay domain danh cho khach (bai hoc Bat 5:
        # sales/playbook la tai lieu noi bo). rag.py/knowledge_chunks GIU
        # NGUYEN lam duong lui khi KB V2 loi - khong xoa.
        try:
            from app.services.kb_retrieval import search_kb
            units = await search_kb(text, top_k=4, allowed_domains=["brand", "product", "faq"])
            rag_context = "\n\n".join(
                f"[{u['asset_id']}] {u['heading']}:\n{u['content'][:600]}" for u in units
            )
        except Exception as e:
            print(f"[orchestrator] KB V2 loi, dung tam RAG cu: {safe_exc(e)}")
            chunks = await search_knowledge(text, top_k=4)
            rag_context = "\n\n".join(chunks) if chunks else ""

        # 3. Xay dung messages cho LLM
        system = SYSTEM_PROMPT

        # Boi canh phien: kenh + co phai tin dau khong + muc do bat buoc khai bao
        # tro ly tu dong. Lich su rong = tin dau cua phien 24h (cung xap xi
        # "sau khoang lang dai" theo yeu cau Meta). Quy tac chi tiet o
        # system_prompt.md muc "Khai bao la tro ly tu dong".
        is_first_turn = len(history) == 0
        disclosure_level = (
            "BAT BUOC" if channel in DISCLOSURE_REQUIRED_CHANNELS else "KHUYEN NGHI"
        )
        system += (
            "\n\n## Boi canh phien hien tai\n"
            f"- Kenh dang phuc vu: {channel}\n"
            f"- Day la tin nhan DAU TIEN cua khach trong phien nay: "
            f"{'CO' if is_first_turn else 'KHONG'}\n"
            f"- Muc do yeu cau khai bao tro ly tu dong o tin dau: {disclosure_level}\n"
        )

        full_name = f"{profile.get('last_name', '')} {profile.get('first_name', '')}".strip()
        if full_name:
            system += (
                f"\n\n## Thong tin khach hang\nTen tren Messenger: {full_name}. "
                "Dung ten nay de suy doan gioi tinh va danh xung phu hop "
                "(theo quy tac 'Cach goi khach')."
            )
        if rag_context:
            system += f"\n\n## Thong tin tham khao lien quan\n{rag_context}"

        # 2.5. Lop NLU (issue #12) - CHI khi bat co ENABLE_NLU_ROUTER, CHI bo
        # sung THEM 1 doan hint ngan cho LLM, KHONG thay the/chan flow hien
        # tai. An toan tuyet doi: get_nlu_hint() tu bat moi loi ben trong,
        # khong bao gio raise ra day - xem app/services/nlu_hint.py.
        if settings.enable_nlu_router:
            nlu_hint = await get_nlu_hint(text, sender_id=sender_id)
            if nlu_hint:
                system += f"\n\n## Goi y tu he thong phan loai NLU (tham khao, khong bat buoc)\n{nlu_hint}"

        # Bom THANG danh sach SKU vao system prompt moi luot chat - KHONG phu
        # thuoc viec LLM co tu quyet dinh goi search_products hay khong (bug
        # 17/7: du prompt/tool schema da nhac goi tool, DeepSeek van tung
        # khang dinh sai "chi co 1 SKU" nhieu lan lien tiep trong 1 hoi thoai,
        # ke ca khi khach phan bac). Day la nguon that ve SU TON TAI cua SKU -
        # gia/ton kho/bac gia chi tiet van phai qua search_products/check_stock.
        sku_summary = await products.get_sku_summary_text()
        system += (
            "\n\n## Danh sach SKU hien co (nguon that DUY NHAT va DAY DU, LUON\n"
            "dung, khong duoc noi trai hay phu nhan du lieu nay du lich su hoi\n"
            "thoai truoc do co the da noi sai)\n"
            f"{sku_summary}\n\n"
            "TUYET DOI KHONG duoc bia them BAT KY SKU nao ngoai danh sach tren,\n"
            "ke ca khi nghe co ve hop ly voi nhu cau khach (vd khach hoi 'co loai\n"
            "nao dong goi lon/thung/bao khong' ma danh sach tren khong co loai do\n"
            "-> phai noi that la CHUA CO, KHONG duoc tu dat ten 1 SKU moi nghe hop ly).\n\n"
            "QUAN TRONG - THU TU UU TIEN khi co mau thuan: danh sach tren la du\n"
            "lieu SONG, luon duoc lay lai moi luot chat - LUON dung hon lich su\n"
            "hoi thoai o duoi (ke ca cau tra loi TRUOC DAY cua chinh ban). Neu ban\n"
            "thay minh (hoac lich su) tung noi 1 SKU KHONG co trong danh sach nay,\n"
            "hay TIN THEO danh sach nay (SKU do CO THAT), KHONG duoc tu 'sua lai'\n"
            "thanh phu nhan no chi vi muon nghe nhat quan voi cau truoc - chi duoc\n"
            "phep thay doi ket luan khi VUA goi lai tool va nhan ket qua khac.\n"
            "Van phai goi search_products de lay gia/bac gia/ton kho chi tiet cho\n"
            "tung SKU truoc khi bao gia cu the."
        )

        # Bom nguoc tin nhan/ghi chu that cua nhan vien trong luc handover (neu co) -
        # doc tu Postgres (khong phai Redis) de KHONG bao gio mat, tranh bot noi
        # trai thoa thuan sep/nhan vien da chot voi khach (issue #8 - xu ly tin
        # nhan luc handover). Xem app/services/conversation_log.py:get_recent_agent_messages.
        agent_notes = await conversation_log.get_recent_agent_messages(sender_id, limit=10)
        if agent_notes:
            notes_text = "\n".join(f"- {n['content']}" for n in agent_notes)
            system += (
                "\n\n## Ghi chu/thoa thuan tu nhan vien trong qua trinh handover\n"
                "(KHONG doc nguyen van cho khach, chi dung de hieu boi canh va "
                "KHONG duoc noi trai nhung gi nhan vien/sep da chot voi khach)\n"
                f"{notes_text}"
            )

        # messages cho vong lap tool-calling cua luot nay - khong dinh vao history
        # da luu tru khi con tool_calls trung gian
        turn_messages = [{"role": "system", "content": system}]
        turn_messages += history
        turn_messages.append({"role": "user", "content": text})

        client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

        reply = ""
        created_order_ids: list = []  # order_id create_order tra ve THAT trong luot nay
        _committed_via_bus = False    # CA 225-07: co order di qua command bus (co receipt) trong luot nay
        # M5 upgrade (Directive 214 §6.D + Memo 213 §6): do latency + token (SAFE — khong payload).
        _llm_ms = 0.0
        _tool_ms = 0.0
        _tok_in = 0
        _tok_out = 0
        _n_iter = 0
        _route_signal = None  # 216-04: 'clarify' | 'escalate' phat hien tu tool-result
        finish_reason = None
        for _iter in range(MAX_TOOL_ITERATIONS):
            _n_iter += 1
            _t_llm = perf_counter()
            response = await _llm_create(
                client,
                model=settings.llm_model,
                messages=turn_messages,
                tools=tools.TOOL_DEFINITIONS,
                tool_choice="auto",
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.1,
            )
            _llm_ms += (perf_counter() - _t_llm) * 1000.0
            _usage = getattr(response, "usage", None)
            if _usage is not None:
                _tok_in += getattr(_usage, "prompt_tokens", 0) or 0
                _tok_out += getattr(_usage, "completion_tokens", 0) or 0
            message = response.choices[0].message
            finish_reason = response.choices[0].finish_reason

            if not message.tool_calls:
                reply = (message.content or "").strip()
                if not reply:
                    # Model tra ve KHONG tool_call ma content cung RONG. Voi model co suy luan,
                    # nguyen nhan pho bien nhat la reasoning_content dot het budget ->
                    # finish_reason='length' (xem MAX_OUTPUT_TOKENS). Log SAFE-TRACE (Directive 209-02):
                    # CHI event class + finish_reason + iteration; TUYET DOI KHONG log sender_id/telegram id,
                    # dia chi, ten, sdt, message, tool-arg, prompt, reasoning content hay token.
                    # Neu con tai dien voi finish_reason='length' thi tang MAX_OUTPUT_TOKENS them.
                    print(f"[orchestrator] empty_reply_fallback finish_reason={finish_reason} "
                          f"iteration={_iter} — khong goi tool nao.")
                break

            # Ghi lai message cua assistant (co tool_calls) vao messages de model
            # thay duoc ngu canh no vua goi tool gi o vong sau
            turn_messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
            )

            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                # I-B M1 (Slice 4): boi canh command cho create_order — stable idempotency key
                # theo tool_call_id (luong AI don-luong; webhook redelivery da duoc Redis mid-dedup
                # chan o worker). Chi anh huong khi settings.m1_reliable_order_command BAT.
                cmd_ctx = None
                if tc.function.name == "create_order":
                    # CR-04R: KHÔNG precompute idempotency key ở đây (không dùng tool_call_id — LLM
                    # sinh lại sẽ khác). Chỉ truyền PROVIDER MESSAGE ID thật (mid/message_id) + context;
                    # gateway derive key ỔN ĐỊNH từ channel + provider msg id + danh tính nghiệp vụ.
                    pmid = provider_message_id or sender_id
                    cmd_ctx = {
                        "channel": channel,
                        "actor_type": "customer",
                        "actor_id": sender_id,
                        "conversation_id": conversation_id,
                        "causation_id": pmid,
                        "provider_message_id": pmid,
                    }
                _t_tool = perf_counter()
                result = await _execute_tool(tc.function.name, args, sender_id, text,
                                             command_ctx=cmd_ctx)
                _tool_ms += (perf_counter() - _t_tool) * 1000.0
                if isinstance(result, dict):  # 216-04: nhan dien route clarify/escalate tu tool-result
                    if result.get("address_needs_clarification"):
                        _route_signal = "clarify"
                    elif result.get("address_unresolved_escalated"):
                        _route_signal = "escalate"
                if (
                    tc.function.name == "create_order"
                    and isinstance(result, dict)
                    and result.get("order_id")
                    and not result.get("error")
                ):
                    created_order_ids.append(result["order_id"])
                    # CA 225-07: order di qua COMMAND BUS (co "receipt") -> receipt finalization phai ap
                    # DU global m1=False (Gate E pilot route). Deterministic reply dua tren ket qua thuc te.
                    if result.get("receipt") is not None:
                        _committed_via_bus = True
                turn_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
        else:
            # Het MAX_TOOL_ITERATIONS ma van con tool_calls - tra loi an toan thay vi treo
            print(f"[orchestrator] Vuot qua {MAX_TOOL_ITERATIONS} vong tool_calls cho {sender_id}")
            reply = "Đội ngũ 3S Coffee sẽ kiểm tra và phản hồi bạn sớm nhất."

        if not reply:
            reply = "Đội ngũ 3S Coffee sẽ kiểm tra và phản hồi bạn sớm nhất."

        # Safety net: loc ky hieu markdown lot luoi (Messenger khong render markdown)
        reply = (
            reply.replace("**", "")
            .replace("###", "")
            .replace("##", "")
            .replace("`", "")
        )

        # I-B M1 (Slice 6): bom dong xac nhan DETERMINISTIC tu committed receipt (order#/tong khong
        # de LLM viet lai) + shadow evaluate (buoc rollout marker->structured guard §10.4). Chi khi
        # flag BAT — flag TAT giu nguyen hanh vi legacy ben duoi (marker guard van chay).
        if settings.m1_reliable_order_command or _committed_via_bus:
            from app.services.command import reply_guard
            shadow = reply_guard.shadow_evaluate(_reply_claims_order_created(reply), created_order_ids)
            if not shadow["consistent"]:
                # M3-S4: KHONG in noi dung reply (chua ten/ma don) — chi metadata.
                print(f"[orchestrator][M1-shadow] CLAIM-KHONG-RECEIPT sender={sender_id} "
                      f"reply_len={len(reply)}")
            # CR-08: order đã commit -> reply tức thì TRUNG TÍNH (không để LLM nói sai mã đơn/tổng tiền);
            # xác nhận CHÍNH THỨC (đúng committed data) đi qua durable receipt (outbox, CR-03).
            reply = reply_guard.finalize_customer_reply(reply, bool(created_order_ids))

        # GUARD CHONG BIA DON (lop code, khong chi dua vao prompt): neu model bao
        # KHACH rang don da duoc tao ("ma don #...", "dat hang thanh cong"...) nhung
        # KHONG co create_order thanh cong nao trong luot nay -> gan nhu chac chan
        # bia (da gap that: bot tu che "Ma don #3" ma khong goi tool -> DB khong co
        # don, khach tuong da mua). Chuyen human that su + tra loi an toan, KHONG de
        # khach tin nham la da dat hang thanh cong.
        if not created_order_ids and _reply_claims_order_created(reply) and _is_order_status_query(text):
            # M5 discovery fix (CA 223 §5.5 / 224 §10.9): khach HOI trang thai don CU ("kiem tra don hom
            # qua"...) — out-of-scope tao don. Guard chong-bia bat vi reply nhac "don" nhung day KHONG
            # phai bia don-moi. -> KHONG escalate/pause; tra neutral (khong khang dinh da tao don moi).
            print(f"[orchestrator] order-status query -> neutral, khong escalate. sender={sender_id}")
            _route_signal = "reply"
            reply = ("Dạ hiện em chưa tra cứu được chi tiết đơn cũ qua kênh này ạ. Anh/chị cho em xin "
                     "mã đơn hoặc SĐT đã đặt để em kiểm tra giúp, hoặc em chuyển nhân viên hỗ trợ nhé ạ.")
        elif not created_order_ids and _reply_claims_order_created(reply):
            # M3-S4: KHONG in noi dung reply (ngu canh xac nhan don thuong chua ten/tien) — metadata.
            print(
                f"[orchestrator] CHAN BIA DON: reply bao da tao don nhung khong co "
                f"create_order thanh cong trong luot nay. sender={sender_id} "
                f"reply_len={len(reply)}"
            )
            try:
                await tools.escalate_to_human(
                    psid=sender_id,
                    reason=(
                        "Nghi bia xac nhan don: model bao da tao don nhung khong "
                        "goi create_order thanh cong trong luot nay"
                    ),
                    last_message=text,
                )
            except Exception as e:  # noqa: BLE001 - escalate loi khong duoc lam sap luong
                print(f"[orchestrator] escalate sau chan bia don loi: {safe_exc(e)}")
            await _terminalize_open_intent("ESCALATED", "suspected_fabrication")  # CA 225-01
            _route_signal = "escalate"  # 216-04
            reply = (
                "Dạ để em kiểm tra lại cho chắc chắn rồi xác nhận đơn với anh/chị "
                "ngay ạ. Đội ngũ 3S Coffee sẽ liên hệ anh/chị trong ít phút để chốt đơn."
            )

        # CA 226-03b: order-proposal chua du thong tin (khach dat don, LLM chua tao order + chua co open
        # intent) -> tao COLLECTING durable de lifecycle bat dau tu proposal DAU TIEN. Non-order/status chat
        # -> _is_order_intent False -> khong tao. Complete order sau -> drive() get-or-create tai dung intent
        # nay -> ADDRESS_CHECK (khong parallel). Bo qua khi da commit/clarify/escalate luot nay.
        if not created_order_ids and _route_signal not in ("clarify", "escalate") \
                and _is_order_intent(text):
            await _ensure_collecting_intent(sender_id, conversation_id, channel)

        # 5. Luu lich su - CHI luot user/assistant cuoi cung, khong luu buoc tool_calls
        # trung gian (giu Redis gon nhe, dung format cu tuong thich nguoc)
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        await _save_history(redis, sender_id, history)
        await conversation_log.log_message(conversation_id, "customer", text)
        await conversation_log.log_message(conversation_id, "bot", reply)

        # M5 upgrade (§6.D + Memo 213 §6 + Review 216-04): 1 dong metric AN TOAN — TUYET DOI khong
        # ten/sdt/dia chi/message/prompt/reasoning/payload; chi so lieu tong hop de collector tinh
        # p50/p95/max theo kenh/route. route: order (co create_order thanh cong) | clarify | escalate |
        # reply — 4 nhan phan biet (clarify KHONG con bi ghi thanh reply).
        _route = "order" if created_order_ids else (_route_signal or "reply")
        print(f"[latency] event=chat channel={channel} route={_route} "
              f"ms_total={int((perf_counter() - _t_start) * 1000)} ms_llm={int(_llm_ms)} "
              f"ms_tool={int(_tool_ms)} iters={_n_iter} tok_in={_tok_in} tok_out={_tok_out} "
              f"finish={finish_reason} "
              f"think_off={settings.disable_llm_reasoning and _thinking_control_supported}")

        return reply

    except Exception as e:
        # Fallback an toan neu LLM loi
        print(f"[orchestrator] LLM error: {safe_exc(e)}")
        return "Đội ngũ 3S Coffee sẽ phản hồi bạn ngay."

    finally:
        await redis.aclose()
