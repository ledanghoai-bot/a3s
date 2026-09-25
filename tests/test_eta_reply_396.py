"""CA Directive 396 F1 — ETA khi khach hoi lai qua Bot (evidence don #254: bot hua "bao lai" du GHN da co ETA).

Thuan (CI-safe): intent ETA/ban giao co dau + khong dau + negative; template; guard hua suong; tin COD/CK lap ETA;
  loc su kien outbox ghi lich su.
DB (skipif not M6_TEST_DB): ETA quoted -> tra ETA (0 attention); chua ETA -> attention eta_question + admin notify
  THAT, idempotent; don huy/da giao -> None; outbox da giao -> 1 dong messages (dedupe outbox:<id>), tin admin khong
  ghi; COD lap ETA.
"""
import os

import pytest

from app.services.command import outbox_worker as OW
from app.services.command import reply_guard as RG
from app.services.fulfillment import conversation as C
from app.services.fulfillment import eta_reply as E

# --------------------------------------------------------------------------- intent (cap co dau / khong dau)
ETA_POS = [
    "Thời gian giao hàng tầm bao lâu e?",            # nguyen van don #254 msg 1812
    "thoi gian giao hang tam bao lau e?",
    "Bao lâu thì nhận được hàng ạ?", "bao lau thi nhan duoc hang a",
    "khi nào giao vậy shop", "khi nao giao vay shop",
    "mấy ngày thì tới nơi?", "may ngay thi toi noi",
    "Bao giờ nhận được hàng", "bao gio nhan duoc hang",
    "dự kiến giao ngày nào em", "du kien giao ngay nao em",
    "THỜI GIAN GIAO HÀNG BAO LÂU",
]
HANDOVER_POS = [
    "khi nào shop gửi hàng đi", "khi nao shop gui hang di",
    "bao giờ bàn giao cho GHN", "bao gio ban giao cho ghn",
    "hôm nào ship đi vậy", "hom nao ship di vay",
]
NEG = [
    "bao lâu thì pha được", "bao lau thi pha duoc",          # hoi cach pha, khong phai giao
    "giao diện web đẹp ghê, khi nào có sale",               # 'giao dien'
    "khi nào có hàng lại", "khi nao co hang lai",          # ton kho
    "khi nào shop nhận được tiền", "khi nao shop nhan duoc tien",  # thanh toan
    "bao lâu cũng được em", "khi nào giao cũng được",      # khang dinh, khong hoi
    "chưa nhận được hàng", "COD nhé", "cho anh 2 hũ", "hỏng rồi", "",
]


@pytest.mark.parametrize("t", ETA_POS)
def test_eta_intent_positive(t):
    assert E.classify(t) == "eta"


@pytest.mark.parametrize("t", HANDOVER_POS)
def test_handover_intent_positive(t):
    assert E.classify(t) == "handover"


@pytest.mark.parametrize("t", NEG)
def test_eta_intent_negative(t):
    assert E.classify(t) is None


def test_eta_intent_nfd_input_normalized():
    import unicodedata
    assert E.classify(unicodedata.normalize("NFD", "Thời gian giao hàng tầm bao lâu")) == "eta"


# --------------------------------------------------------------------------- template
def _row(**kw):
    base = {"order_id": 254, "order_status": "confirmed", "ship_status": "pending_prep", "fee_status": "quoted",
            "eta_text": "khoảng 2 ngày (GHN)", "quote_provider": "ghn", "quote_source": "auto_route"}
    base.update(kw)
    return base


def test_eta_reply_ghn_template():
    assert E.eta_text_reply(_row()) == ("Dạ đơn #254 dự kiến giao khoảng 2 ngày (GHN), tính từ khi bên GHN nhận hàng "
                                        "từ shop ạ.")


def test_eta_reply_non_ghn_and_in_transit():
    r = _row(quote_provider=None, quote_source="auto_rule", eta_text="khoảng 3 giờ (nội thành Buôn Ma Thuột)")
    assert "GHN" not in E.eta_text_reply(r) and "khoảng 3 giờ" in E.eta_text_reply(r)
    fb = _row(quote_source="fallback_policy", eta_text="dự kiến 1–7 ngày tùy khu vực (nhân viên xác nhận cụ thể)")
    assert "tính từ khi bên GHN" not in E.eta_text_reply(fb)
    assert "đã được bàn giao" in E.eta_text_reply(_row(ship_status="in_transit"))


def test_has_real_eta_rejects_placeholders_and_unquoted():
    assert E.has_real_eta(_row())
    assert not E.has_real_eta(_row(eta_text="GHN sẽ báo thời gian giao"))
    assert not E.has_real_eta(_row(eta_text="sẽ xác nhận sau khi kiểm tra địa chỉ"))
    assert not E.has_real_eta(_row(fee_status="quote_required"))
    assert not E.has_real_eta(_row(eta_text=None))


def test_no_eta_reply_says_escalated_not_promise():
    t = E.no_eta_reply(255)
    assert "#255" in t and "chuyển nhân viên" in t and "báo lại" not in t


def test_handover_reply_operational_not_sla():
    t = E.handover_reply(_row())
    assert "ngày làm việc kế tiếp nếu đơn đặt ngoài giờ" in t and "tính từ lúc GHN nhận hàng" in t
    assert "GHN" not in E.handover_reply(_row(quote_provider=None, quote_source="auto_rule"))


# --------------------------------------------------------------------------- COD / CK lap ETA
def test_cod_and_instruction_repeat_eta():
    assert "Dự kiến giao: khoảng 2 ngày (GHN)." in C.cod_text(254, 195000, "khoảng 2 ngày (GHN)")
    assert "Dự kiến giao" not in C.cod_text(254, 195000)
    instr = {"bank_snapshot": "VCB", "account_number_snapshot": "1", "holder_snapshot": "A", "amount_vnd": 195000,
             "transfer_content": "3S254"}
    assert "Dự kiến giao: khoảng 2 ngày (GHN)." in C.instruction_text(254, instr, wait_minutes=15,
                                                                      eta_text="khoảng 2 ngày (GHN)")
    assert "Dự kiến giao" not in C.instruction_text(254, instr, wait_minutes=15)


# --------------------------------------------------------------------------- guard hua suong
PROMISES = [
    # nguyen van bot don #254 msg 1813 / 1815
    "Dạ phần thời gian giao hàng cụ thể em chưa có thông tin xác nhận để báo chính xác cho anh ạ. "
    "Em xin phép kiểm tra và báo lại anh sớm nhất nhé.",
    "Dạ vâng ạ. Khi nào có thông tin em sẽ báo lại anh ngay. Anh cần gì thêm cứ nhắn em nhé ☕",
    "Da em se kiem tra va bao lai anh sau a.",
    "Đội ngũ 3S Coffee sẽ kiểm tra và phản hồi bạn sớm nhất.",
]


@pytest.mark.parametrize("t", PROMISES)
def test_empty_promise_stripped_when_not_escalated(t):
    out = RG.strip_empty_promise(t, escalated=False)
    assert not RG.has_followup_promise(out)
    assert "gặp nhân viên" in out


def test_msg1815_keeps_non_promise_sentences():
    out = RG.strip_empty_promise(PROMISES[1], escalated=False)
    assert out.startswith("Dạ vâng ạ.") and "Anh cần gì thêm cứ nhắn em nhé" in out


@pytest.mark.parametrize("t", PROMISES)
def test_promise_kept_when_really_escalated(t):
    assert RG.strip_empty_promise(t, escalated=True) == t


@pytest.mark.parametrize("t", [
    "Dạ hũ 100g giá 170.000đ ạ.", "Dạ bên em có ship toàn quốc ạ.",
    "Dạ em đã ghi nhận yêu cầu đặt hàng của anh/chị.", "Dạ không có gì ạ, anh cần gì cứ nhắn em.",
])
def test_innocuous_reply_untouched(t):
    assert RG.strip_empty_promise(t, escalated=False) == t


# --------------------------------------------------------------------------- loc su kien lich su
def test_history_event_filter():
    assert OW.is_history_event("fulfillment.prompt.notify", "telegram_customer")
    assert OW.is_history_event("shipment.handover.notify", "messenger")
    assert OW.is_history_event("order.status.customer", "telegram_customer")
    assert not OW.is_history_event("fulfillment.staff.notify", "telegram_admin")     # staff noi bo
    assert not OW.is_history_event("order.receipt.customer", "telegram_customer")    # da ghi rieng (233-05)
    assert not OW.is_history_event("order.created", "telegram_admin")


# =========================================================================== DB
DB = os.environ.get("M6_TEST_DB") == "1"


async def _conn():
    import asyncpg
    return await asyncpg.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


async def _customer_order(conn, tag, *, order_status="confirmed"):
    psid = f"tg:{tag}"
    cid = await conn.fetchval("INSERT INTO customers (psid, channel, external_chat_id, name, phone) "
                              "VALUES ($1,'telegram_customer',$1,'T','0900000000') RETURNING id", psid)
    oid = await conn.fetchval("INSERT INTO orders(customer_id,status,total_vnd,origin_channel) "
                              "VALUES($1,$2,170000,'telegram_customer') RETURNING id", cid, order_status)
    return psid, cid, oid


async def _ship(conn, oid, *, status="pending_prep", fee_status="quoted", eta="khoảng 2 ngày (GHN)", provider="ghn",
                source="auto_route", fee=25000):
    await conn.execute("INSERT INTO shipments(order_id,status,zone,fee_status,delivery_fee_vnd,eta_text,quote_provider,"
                       "quote_source) VALUES($1,$2,'province',$3,$4,$5,$6,$7)",
                       oid, status, fee_status, fee if fee_status == "quoted" else None, eta, provider, source)


async def _ask(conn, psid, text):
    async with conn.transaction():
        return await E.handle(conn, psid, text)


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_eta_quoted_answers_without_attention():
    import time
    conn = await _conn()
    try:
        psid, _, oid = await _customer_order(conn, f"ETA1-{int(time.time()*1000)}")
        await _ship(conn, oid)
        r = await _ask(conn, psid, "Thời gian giao hàng tầm bao lâu e?")
        assert r == f"Dạ đơn #{oid} dự kiến giao khoảng 2 ngày (GHN), tính từ khi bên GHN nhận hàng từ shop ạ."
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id=$1", oid) == 0
        # ban giao
        h = await _ask(conn, psid, "khi nao shop gui hang di")
        assert "ngày làm việc" in h
        # khong phai cau hoi giao -> None
        assert await _ask(conn, psid, "bao lâu thì pha được") is None
    finally:
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_eta_missing_escalates_for_real_idempotent():
    import time
    conn = await _conn()
    try:
        psid, _, oid = await _customer_order(conn, f"ETA2-{int(time.time()*1000)}")
        await _ship(conn, oid, fee_status="quote_required", eta="sẽ xác nhận sau khi kiểm tra địa chỉ", provider=None,
                    source="auto_rule")
        r1 = await _ask(conn, psid, "bao lau thi nhan duoc hang")
        r2 = await _ask(conn, psid, "bao lau thi nhan duoc hang")   # hoi lai / duplicate
        assert r1 == r2 == E.no_eta_reply(oid)
        att = await conn.fetch("SELECT reason, status FROM staff_attention WHERE order_id=$1", oid)
        assert [(a["reason"], a["status"]) for a in att] == [("eta_question", "open")]
        # admin notify THAT (outbox, dung 1 lan theo attention)
        n = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE event_type='fulfillment.staff.notify' "
                                "AND destination='telegram_admin' AND (payload->>'order_id')::bigint=$1 "
                                "AND payload->>'reason'='eta_question'", oid)
        assert n == 1
        # quote placeholder GHN (leadtime loi) cung coi la chua co ETA
        psid3, _, oid3 = await _customer_order(conn, f"ETA3-{int(time.time()*1000)}")
        await _ship(conn, oid3, eta="GHN sẽ báo thời gian giao")
        assert await _ask(conn, psid3, "khi nào giao vậy") == E.no_eta_reply(oid3)
    finally:
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_no_open_order_falls_through():
    import time
    conn = await _conn()
    try:
        psid, _, oid = await _customer_order(conn, f"ETA4-{int(time.time()*1000)}", order_status="cancelled")
        await _ship(conn, oid, status="cancelled")
        assert await _ask(conn, psid, "khi nào giao") is None
        psid2, _, oid2 = await _customer_order(conn, f"ETA5-{int(time.time()*1000)}")
        await _ship(conn, oid2, status="delivered")
        assert await _ask(conn, psid2, "khi nào giao") is None
        assert await _ask(conn, "tg:khong-ton-tai-396", "khi nào giao") is None
        assert await conn.fetchval("SELECT count(*) FROM staff_attention WHERE order_id = ANY($1::bigint[])",
                                   [oid, oid2]) == 0
    finally:
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_outbox_delivered_persists_history_once():
    import time

    from app.services.command import repository as cmd_repo
    conn = await _conn()
    try:
        tag = f"ETA6-{int(time.time()*1000)}"
        psid, cid, oid = await _customer_order(conn, tag)
        conv = await conn.fetchval("INSERT INTO conversations(customer_id) VALUES($1) RETURNING id", cid)
        text = f"Dạ đơn #{oid} ... Dự kiến giao: khoảng 2 ngày (GHN)."
        await cmd_repo.insert_outbox(conn, command_id=None, event_type="fulfillment.prompt.notify", event_version=1,
                                     destination="telegram_customer", dedupe_key=f"t396:{tag}:c",
                                     payload={"customer_ref": psid, "order_id": oid, "text": text}, max_attempts=3)
        await cmd_repo.insert_outbox(conn, command_id=None, event_type="fulfillment.staff.notify", event_version=1,
                                     destination="telegram_admin", dedupe_key=f"t396:{tag}:a",
                                     payload={"customer_ref": psid, "order_id": oid, "text": "noi bo",
                                              "kind": "staff_attention", "reason": "quote"}, max_attempts=3)
        sent = []

        async def fake_send(dest, payload):
            sent.append(dest)
            return OW.SendResult(ok=True, http_status=200, provider_message_id="pm")
        # DB dung chung co the con event pending cua test khac (batch 25) -> drain toi khi 2 event cua test nay xong.
        for _ in range(40):
            left = await conn.fetchval("SELECT count(*) FROM outbox_events WHERE dedupe_key = ANY($1::text[]) "
                                       "AND status NOT IN ('delivered','cancelled','dead_lettered')",
                                       [f"t396:{tag}:c", f"t396:{tag}:a"])
            if left == 0:
                break
            await OW.run_once(send_fn=fake_send)
        rows = await conn.fetch("SELECT role, content, dedupe_key FROM messages WHERE conversation_id=$1", conv)
        assert len(rows) == 1 and rows[0]["role"] == "bot" and rows[0]["content"] == text
        assert rows[0]["dedupe_key"].startswith("outbox:")
        # redeliver cung event (vd reclaim sau crash) -> KHONG ghi trung
        ev = await conn.fetchrow("SELECT id, event_type, destination, payload FROM outbox_events WHERE dedupe_key=$1",
                                 f"t396:{tag}:c")
        import json
        pl = ev["payload"] if isinstance(ev["payload"], dict) else json.loads(ev["payload"])
        assert await OW.persist_customer_history(conn, ev["id"], ev["event_type"], ev["destination"], pl) is False
        assert await conn.fetchval("SELECT count(*) FROM messages WHERE conversation_id=$1", conv) == 1
    finally:
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_cod_confirmation_repeats_eta():
    import time
    conn = await _conn()
    try:
        tag = f"ETA7-{int(time.time()*1000)}"
        psid, _, oid = await _customer_order(conn, tag)
        await _ship(conn, oid)
        await conn.execute("INSERT INTO fulfillment_conversations(order_id,channel,customer_ref,step,policy_version) "
                           "VALUES($1,'telegram_customer',$2,'awaiting_method',1)", oid, psid)
        async with conn.transaction():
            r = await C.handle_customer_text(conn, psid, "COD nhé", command_key=f"{tag}-1")
        assert isinstance(r, str) and "COD" in r and "Dự kiến giao: khoảng 2 ngày (GHN)." in r
    finally:
        await conn.close()


@pytest.mark.skipif(not DB, reason="can DB (M6_TEST_DB=1)")
@pytest.mark.asyncio
async def test_db_orchestrator_eta_before_llm(monkeypatch):
    """Tai hien don #254: khach hoi 'Thoi gian giao hang tam bao lau e?' -> orchestrator tra ETA TAT DINH, KHONG goi
    LLM; tin khach + bot ghi vao messages. Ngoai M7 scope -> khong chan (roi xuong luong cu)."""
    import time

    from app.config import settings
    from app.services import orchestrator as O

    class _NoLLM:
        def __init__(self, *a, **k):
            raise AssertionError("LLM khong duoc goi cho cau hoi ETA")
    conn = await _conn()
    try:
        psid, cid, oid = await _customer_order(conn, f"ETA8-{int(time.time()*1000)}")
        await _ship(conn, oid)
        monkeypatch.setattr(settings, "m7_conversational_fulfillment", True)
        monkeypatch.setattr(settings, "m7_conversational_scope", "tester")
        monkeypatch.setattr(settings, "m7_tester_customer_ids", str(cid))
        monkeypatch.setattr(settings, "m7_eta_reply", True)
        monkeypatch.setattr(O, "AsyncOpenAI", _NoLLM)
        r = await O.handle_message(psid, "Thời gian giao hàng tầm bao lâu e?", channel="telegram_customer",
                                   provider_message_id=f"{psid}:m1")
        assert r == f"Dạ đơn #{oid} dự kiến giao khoảng 2 ngày (GHN), tính từ khi bên GHN nhận hàng từ shop ạ."
        logged = await conn.fetch("SELECT m.role FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                                  "WHERE c.customer_id=$1 ORDER BY m.id", cid)
        assert [x["role"] for x in logged][-2:] == ["customer", "bot"]
        # kill switch -> KHONG vao duong ETA (LLM se bi goi -> _NoLLM raise -> orchestrator fallback an toan)
        monkeypatch.setattr(settings, "m7_eta_reply", False)
        r2 = await O.handle_message(psid, "Thời gian giao hàng tầm bao lâu e?", channel="telegram_customer",
                                    provider_message_id=f"{psid}:m2")
        assert r2 != r
    finally:
        await conn.close()
