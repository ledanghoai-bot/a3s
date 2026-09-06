"""M5 upgrade (Directive 214 §6.D, corpus §7.13): fallback khi provider KHONG ho tro thinking-control
chi kich hoat dung loi tham so 'thinking' — KHONG nuot cac loi khac (rate limit, timeout...)."""
from app.services import orchestrator as o


def test_detects_thinking_param_errors():
    assert o._thinking_unsupported(Exception("400 Bad Request: thinking: invalid type")) is True
    assert o._thinking_unsupported(Exception("thinking parameter not supported by this model")) is True
    assert o._thinking_unsupported(Exception("Failed to deserialize ... thinking ... unexpected")) is True


def test_ignores_unrelated_errors():
    assert o._thinking_unsupported(Exception("rate limit exceeded")) is False
    assert o._thinking_unsupported(Exception("connection timeout")) is False
    assert o._thinking_unsupported(Exception("insufficient balance")) is False
    # co chua 'thinking' nhung khong phai loi tham so -> van False (khong dau hieu unsupported/invalid)
    assert o._thinking_unsupported(Exception("model is thinking about your request")) is False
