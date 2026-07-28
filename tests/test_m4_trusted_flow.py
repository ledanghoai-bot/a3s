"""I-B M4-S2: unit test trusted flow — mock model + fake slot store (khong DB).

Bat bien kiem o day (spec §5): model chi nhan INPUT DA MASK; model khong lap
duoc tool args chua PII; D2 khong cham vendor; fallback 3 tang; placeholder
mangle bi tu choi; module KHONG duoc noi vao orchestrator (test tinh).
"""

import asyncio
import base64
from pathlib import Path

import pytest

from app.config import settings
from app.services.pii import slot_store as slot_store_mod
from app.services.pii import trusted_flow
from app.services.pii.masking import make_placeholder


@pytest.fixture(autouse=True)
def _fp_key():
    """S3: placeholder integrity tag can khoa HMAC — gan khoa synthetic co dinh."""
    old = settings.m4_slot_fp_key_b64
    settings.m4_slot_fp_key_b64 = base64.b64encode(bytes(range(32))).decode()
    yield
    settings.m4_slot_fp_key_b64 = old

_CONF = {"high": 2, "medium": 1, "low": 0}
PHONE, NAME, ADDR = "0912345678", "Nguyễn Văn An", "số 12 đường Lê Lợi, phường 5, quận 3"
ORDER_TEXT = f"Đặt 2 gói 500g. Người nhận {NAME}, {PHONE}, {ADDR}"


class FakeSlotStore:
    """In-memory thay pii_slots: van giu binding (customer, conversation)."""

    def __init__(self):
        self.rows = []  # (cust, conv, slot_type, value, conf)

    async def store_slot(self, conn, *, customer_ref, conversation_ref, slot_type,
                         value, confidence, **_kw):
        self.rows.append((customer_ref, conversation_ref, slot_type, value, confidence))
        return slot_store_mod.StoredSlot(slot_id=f"fake-{len(self.rows)}", deduped=False)

    async def resolve_slot(self, conn, *, customer_ref, conversation_ref, slot_type,
                           min_confidence="low"):
        for cust, conv, st, val, conf in reversed(self.rows):
            if (cust, conv, st) == (customer_ref, conversation_ref, slot_type) \
                    and _CONF[conf] >= _CONF[min_confidence]:
                return val
        return None


class SpyModel:
    def __init__(self, output):
        self.output = output
        self.calls: list[list[dict]] = []

    async def __call__(self, messages):
        self.calls.append(messages)
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


class SpyExecutor:
    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, args):
        self.calls.append(args)
        return {"order_id": "SYN-001", "status": "created"}


def _run(text, model_output, fake=None, history=None, monkeypatch=None):
    fake = fake or FakeSlotStore()
    model = SpyModel(model_output)
    executor = SpyExecutor()
    monkeypatch.setattr(trusted_flow.slot_store, "store_slot", fake.store_slot)
    monkeypatch.setattr(trusted_flow.slot_store, "resolve_slot", fake.resolve_slot)
    outcome = asyncio.run(trusted_flow.process_turn(
        None, customer_ref="cust-A", conversation_ref="conv-1", text=text,
        history=history or [], model_call=model, command_executor=executor))
    return outcome, model, executor, fake


_ORDER_OUTPUT = {
    "intent": "order.create", "missing_slot_types": [],
    "response_candidate": "Dạ em lên đơn ngay ạ",
    "context": {"items": [{"sku": "3S-500G", "qty": 2}]},
}


def test_happy_path_model_khong_thay_pii_va_args_tu_store(monkeypatch):
    outcome, model, executor, fake = _run(ORDER_TEXT, dict(_ORDER_OUTPUT),
                                          monkeypatch=monkeypatch)
    assert outcome.kind == "command_receipt"
    # model CHI thay ban mask
    sent = " ".join(m["content"] for call in model.calls for m in call)
    for leak in (PHONE, NAME, "Lê Lợi"):
        assert leak not in sent
    assert "[PII_PHONE_1_" in sent  # S3: placeholder kem integrity tag
    # command args do trusted code lap: refs tu tham so, PII tu store, items tu context
    args = executor.calls[0]
    assert args["customer_ref"] == "cust-A" and args["conversation_ref"] == "conv-1"
    assert args["shipping_phone"] == PHONE and args["shipping_name"] == NAME
    assert args["items"] == [{"sku": "3S-500G", "qty": 2}]
    # receipt deterministic tu committed result, phone da mask
    assert "SYN-001" in outcome.reply and PHONE not in outcome.reply and "***678" in outcome.reply


def test_d2_khong_cham_vendor(monkeypatch):
    outcome, model, executor, fake = _run(
        "mình đang mang thai, uống loại này được không, sđt 0912345678",
        dict(_ORDER_OUTPUT), monkeypatch=monkeypatch)
    assert outcome.kind == "escalate" and outcome.escalate_reason == "d2_high_risk"
    assert model.calls == []  # vendor path KHONG duoc goi
    assert executor.calls == []
    assert fake.rows == []  # D2 turn: khong luu slot nao


def test_thieu_slot_hoi_deterministic(monkeypatch):
    # tin nhan chi co items, khong PII -> store rong -> hoi phone truoc tien
    outcome, model, executor, _ = _run("cho mình 2 gói 500g nhé",
                                       dict(_ORDER_OUTPUT), monkeypatch=monkeypatch)
    assert outcome.kind == "ask_slot" and outcome.asked_slot == "phone"
    assert executor.calls == []
    assert "số điện thoại" in outcome.reply


def test_confidence_thap_roi_xuong_form(monkeypatch):
    fake = FakeSlotStore()
    fake.rows = [("cust-A", "conv-1", "phone", "123456789", "low"),  # phone LOW
                 ("cust-A", "conv-1", "address", ADDR, "high"),
                 ("cust-A", "conv-1", "name", NAME, "medium")]
    outcome, model, executor, _ = _run("chốt đơn 2 gói 500g nhé", dict(_ORDER_OUTPUT),
                                       fake=fake, monkeypatch=monkeypatch)
    assert outcome.kind == "form"
    assert outcome.detail["low_confidence_slots"] == ["phone"]
    assert executor.calls == []


def test_schema_violation_escalate_khong_goi_command(monkeypatch):
    bad = dict(_ORDER_OUTPUT)
    bad["tool_args"] = {"phone": PHONE}  # model doi lap tool args chua PII
    outcome, model, executor, _ = _run(ORDER_TEXT, bad, monkeypatch=monkeypatch)
    assert outcome.kind == "escalate" and outcome.escalate_reason == "schema_violation"
    assert executor.calls == []


def test_model_chon_ref_bi_chan(monkeypatch):
    bad = {"intent": "order.create", "missing_slot_types": [],
           "response_candidate": "",
           "context": {"items": [{"sku": "X", "qty": 1}], "conversation_ref": "conv-B"}}
    outcome, _, executor, _ = _run(ORDER_TEXT, bad, monkeypatch=monkeypatch)
    assert outcome.kind == "escalate" and executor.calls == []


def test_placeholder_mangle_bi_tu_choi(monkeypatch):
    out = {"intent": "smalltalk", "missing_slot_types": [],
           "response_candidate": "Em gọi lại số [PII_PHONE_7] nhé", "context": {}}
    outcome, _, _, _ = _run("gọi mình qua 0912345678", out, monkeypatch=monkeypatch)
    assert outcome.kind == "escalate" and outcome.escalate_reason == "placeholder_reject"


def test_placeholder_hop_le_duoc_rehydrate(monkeypatch):
    ph = make_placeholder("phone", 1, "conv-1")  # dung tag cua CHINH conv-1
    out = {"intent": "smalltalk", "missing_slot_types": [],
           "response_candidate": f"Dạ em sẽ gọi {ph} trước khi giao ạ", "context": {}}
    outcome, _, _, _ = _run("gọi mình qua 0912345678", out, monkeypatch=monkeypatch)
    assert outcome.kind == "reply" and "0912345678" in outcome.reply


def test_placeholder_conversation_khac_bi_tu_choi(monkeypatch):
    """S3 cross-context: placeholder duc tu conv-KHAC (tag khac) -> reject."""
    ph_other = make_placeholder("phone", 1, "conv-KHAC")
    out = {"intent": "smalltalk", "missing_slot_types": [],
           "response_candidate": f"Em gọi {ph_other} nhé", "context": {}}
    outcome, _, _, _ = _run("gọi mình qua 0912345678", out, monkeypatch=monkeypatch)
    assert outcome.kind == "escalate" and outcome.escalate_reason == "placeholder_reject"


def test_placeholder_lap_bi_tu_choi(monkeypatch):
    ph = make_placeholder("phone", 1, "conv-1")
    out = {"intent": "smalltalk", "missing_slot_types": [],
           "response_candidate": f"Gọi {ph} hoặc {ph} đều được", "context": {}}
    outcome, _, _, _ = _run("gọi mình qua 0912345678", out, monkeypatch=monkeypatch)
    assert outcome.kind == "escalate" and outcome.escalate_reason == "placeholder_reject"


def test_model_loi_escalate(monkeypatch):
    outcome, _, executor, _ = _run(ORDER_TEXT, RuntimeError("boom"), monkeypatch=monkeypatch)
    assert outcome.kind == "escalate" and outcome.escalate_reason == "model_error"
    assert executor.calls == []


def test_cross_conversation_khong_dung_slot_conv_khac(monkeypatch):
    fake = FakeSlotStore()
    fake.rows = [("cust-A", "conv-1", "phone", PHONE, "high"),
                 ("cust-A", "conv-1", "address", ADDR, "high"),
                 ("cust-A", "conv-1", "name", NAME, "medium")]
    model = SpyModel(dict(_ORDER_OUTPUT))
    executor = SpyExecutor()
    monkeypatch.setattr(trusted_flow.slot_store, "store_slot", fake.store_slot)
    monkeypatch.setattr(trusted_flow.slot_store, "resolve_slot", fake.resolve_slot)
    outcome = asyncio.run(trusted_flow.process_turn(
        None, customer_ref="cust-A", conversation_ref="conv-2",  # HOI THOAI KHAC
        text="chốt đơn 2 gói nhé", history=[], model_call=model,
        command_executor=executor))
    assert outcome.kind == "ask_slot"  # khong keo slot tu conv-1 sang
    assert executor.calls == []


def test_history_current_placeholder_khong_va_cham(monkeypatch):
    """CA F-M4-S3-02: history co phone A, current co phone B — MOT namespace ->
    echo placeholder history phai rehydrate ra A (khong bi B ghi de)."""
    hist = [{"role": "user", "content": "số cũ của mình là 0356789012"}]
    ph_hist = make_placeholder("phone", 1, "conv-1")  # history mask truoc -> n=1
    ph_cur = make_placeholder("phone", 2, "conv-1")  # current tiep namespace -> n=2
    out_echo_hist = {"intent": "smalltalk", "missing_slot_types": [],
                     "response_candidate": f"Số cũ là {ph_hist} đúng không ạ", "context": {}}
    outcome, model, _, _ = _run("đổi qua số mới 0912345678 nhé", out_echo_hist,
                                history=hist, monkeypatch=monkeypatch)
    assert outcome.kind == "reply"
    assert "0356789012" in outcome.reply  # PHAI la value cua history
    assert "0912345678" not in outcome.reply
    # model thay ca 2 placeholder khac nhau, khong trung so
    sent = " ".join(m["content"] for call in model.calls for m in call)
    assert ph_hist in sent and ph_cur in sent

    out_echo_cur = {"intent": "smalltalk", "missing_slot_types": [],
                    "response_candidate": f"Đã ghi nhận số mới {ph_cur} ạ", "context": {}}
    outcome2, _, _, _ = _run("đổi qua số mới 0912345678 nhé", out_echo_cur,
                             history=hist, monkeypatch=monkeypatch)
    assert outcome2.kind == "reply" and "0912345678" in outcome2.reply
    assert "0356789012" not in outcome2.reply


def test_history_d2_bi_redact_truoc_vendor(monkeypatch):
    """CA F-M4-S3-03: history co D2 health (khong slot so de mask), current D0 ->
    model duoc goi nhung payload KHONG chua noi dung D2, turn bi thay marker."""
    hist = [
        {"role": "user", "content": "mình bị tiểu đường với huyết áp cao lắm"},
        {"role": "assistant", "content": "Dạ em ghi nhận ạ"},
    ]
    out = {"intent": "smalltalk", "missing_slot_types": [],
           "response_candidate": "Dạ shop mở tới 21h ạ", "context": {}}
    outcome, model, _, _ = _run("shop mở cửa tới mấy giờ", out,
                                history=hist, monkeypatch=monkeypatch)
    assert outcome.kind == "reply"
    assert len(model.calls) == 1  # D2 o history KHONG chan turn D0 hien tai
    sent = " ".join(m["content"] for call in model.calls for m in call)
    assert "tiểu đường" not in sent and "huyết áp" not in sent
    assert "[TURN_REDACTED_D2]" in sent
    assert "Dạ em ghi nhận ạ" in sent  # turn sach giu nguyen


def test_sku_smuggle_qua_flow_bi_escalate(monkeypatch):
    """CA F-M4-S2-04 o tang flow: model tra sku = phone -> schema_violation,
    command executor KHONG chay."""
    bad = {"intent": "order.create", "missing_slot_types": [],
           "response_candidate": "",
           "context": {"items": [{"sku": "0912345678", "qty": 1}]}}
    outcome, _, executor, _ = _run(ORDER_TEXT, bad, monkeypatch=monkeypatch)
    assert outcome.kind == "escalate" and outcome.escalate_reason == "schema_violation"
    assert executor.calls == []


def test_orchestrator_khong_noi_trusted_flow():
    """Directive §8: m4_trusted_pii_path KHONG co active code path — orchestrator
    khong duoc import trusted_flow hay tham chieu flag nay."""
    src = (Path(__file__).resolve().parents[1] / "app" / "services"
           / "orchestrator.py").read_text(encoding="utf-8")
    assert "trusted_flow" not in src
    assert "m4_trusted_pii_path" not in src
