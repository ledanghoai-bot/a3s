"""M5 upgrade (Directive 214 §6.E): live verify event id theo kenh (Telegram co so thu tu; Messenger
mid opaque). Test THUAN _event_ok — dam bao non-tester/sai-dinh-dang bi tu choi, dung kenh moi qua."""
from app.services.address import live_verify as lv


def test_telegram_valid_returns_seq():
    assert lv._event_ok("tg:296", "telegram_customer") == (True, 296)


def test_telegram_bare_number_rejected():
    assert lv._event_ok("296", "telegram_customer") == (False, None)


def test_telegram_mid_rejected():
    assert lv._event_ok("m_abc", "telegram_customer") == (False, None)


def test_messenger_mid_valid_no_seq():
    assert lv._event_ok("m_abc123", "messenger") == (True, None)


def test_messenger_empty_rejected():
    assert lv._event_ok("", "messenger") == (False, None)
    assert lv._event_ok(None, "messenger") == (False, None)


def test_unknown_channel_rejected():
    assert lv._event_ok("tg:1", "web") == (False, None)


def test_customer_channels_set():
    assert lv._CUSTOMER_CHANNELS == frozenset({"telegram_customer", "messenger"})
