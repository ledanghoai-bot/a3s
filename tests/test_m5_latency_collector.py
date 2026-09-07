"""M5 upgrade (CA Review 216-04): parser test + probe schema log latency hop le.

Dung DUNG dinh dang dong orchestrator emit -> chung minh collector parse + aggregate dung, va 4 nhan
route (order/clarify/escalate/reply) phan biet duoc.
"""
from scripts import m5_latency_collector as c

# Dong mau DUNG schema orchestrator emit (khong payload/PII).
_SAMPLE = [
    "[latency] event=chat channel=telegram_customer route=order ms_total=1600 ms_llm=1400 ms_tool=180 "
    "iters=2 tok_in=1700 tok_out=150 finish=tool_calls think_off=True",
    "[latency] event=chat channel=telegram_customer route=clarify ms_total=1500 ms_llm=1450 ms_tool=0 "
    "iters=1 tok_in=1600 tok_out=120 finish=stop think_off=True",
    "[latency] event=chat channel=telegram_customer route=order ms_total=2000 ms_llm=1700 ms_tool=250 "
    "iters=3 tok_in=1800 tok_out=200 finish=tool_calls think_off=True",
    "[latency] event=chat channel=messenger route=reply ms_total=1200 ms_llm=1100 ms_tool=0 "
    "iters=1 tok_in=1500 tok_out=90 finish=stop think_off=True",
    "some unrelated log line without latency prefix",
    "[latency] event=chat channel=telegram_customer route=escalate ms_total=1800 ms_llm=1600 ms_tool=50 "
    "iters=2 tok_in=1750 tok_out=130 finish=stop think_off=True",
]


def test_parse_valid_and_ignores_noise():
    parsed = [c.parse_line(x) for x in _SAMPLE]
    ok = [p for p in parsed if p]
    assert len(ok) == 5  # 5 dong latency, bo dong nhieu
    assert c.parse_line("random") is None


def test_route_labels_distinct():
    routes = {p["route"] for p in (c.parse_line(x) for x in _SAMPLE) if p}
    assert {"order", "clarify", "escalate", "reply"}.issubset(routes)
    assert routes <= c._VALID_ROUTES


def test_aggregate_by_channel_route():
    samples = [p for p in (c.parse_line(x) for x in _SAMPLE) if p]
    agg = c.aggregate(samples)
    tg_order = next(a for a in agg if a["channel"] == "telegram_customer" and a["route"] == "order")
    assert tg_order["n"] == 2
    assert tg_order["max_ms"] == 2000
    assert tg_order["p50_ms"] in (1600, 1800, 1799, 1801)  # noi suy giua 1600 va 2000
    assert tg_order["tok_out"] == 350


def test_percentile_single_sample():
    assert c._pct([1500], 0.95) == 1500.0
    assert c._pct([], 0.5) is None
