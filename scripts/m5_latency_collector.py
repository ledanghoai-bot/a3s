"""M5 upgrade (CA Review 216-04): collector latency/token TAI CHAY DUOC.

Parse cac dong SAFE metric do orchestrator emit:
  [latency] event=chat channel=<ch> route=<order|clarify|escalate|reply> ms_total=.. ms_llm=.. ms_tool=..
            iters=.. tok_in=.. tok_out=.. finish=.. think_off=..
Tong hop p50/p95/max theo (channel, route). CHI so lieu tong hop — KHONG payload/prompt/PII.

Dung: docker compose logs <bot> | python scripts/m5_latency_collector.py
"""
from __future__ import annotations

import json
import re
import sys

_LINE_RE = re.compile(
    r"\[latency\] event=chat channel=(\S+) route=(\S+) ms_total=(\d+) ms_llm=(\d+) "
    r"ms_tool=(\d+) iters=(\d+) tok_in=(\d+) tok_out=(\d+) finish=(\S+) think_off=(\S+)")

_VALID_ROUTES = {"order", "clarify", "escalate", "reply"}


def parse_line(line: str) -> dict | None:
    m = _LINE_RE.search(line)
    if not m:
        return None
    return {
        "channel": m.group(1), "route": m.group(2),
        "ms_total": int(m.group(3)), "ms_llm": int(m.group(4)), "ms_tool": int(m.group(5)),
        "iters": int(m.group(6)), "tok_in": int(m.group(7)), "tok_out": int(m.group(8)),
        "finish": m.group(9), "think_off": m.group(10),
    }


def _pct(vals: list[int], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def aggregate(samples: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for s in samples:
        groups.setdefault((s["channel"], s["route"]), []).append(s)
    out = []
    for (ch, rt), g in sorted(groups.items()):
        tot = [x["ms_total"] for x in g]
        out.append({
            "channel": ch, "route": rt, "n": len(g),
            "p50_ms": round(_pct(tot, 0.5)), "p95_ms": round(_pct(tot, 0.95)), "max_ms": max(tot),
            "llm_p95_ms": round(_pct([x["ms_llm"] for x in g], 0.95)),
            "tok_in": sum(x["tok_in"] for x in g), "tok_out": sum(x["tok_out"] for x in g),
        })
    return out


def main() -> None:
    samples = []
    for line in sys.stdin:
        p = parse_line(line)
        if p:
            samples.append(p)
    print(json.dumps({"samples": len(samples), "by_channel_route": aggregate(samples)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
