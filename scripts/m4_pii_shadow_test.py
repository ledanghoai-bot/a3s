#!/usr/bin/env python
"""I-B M4-S0 — evidence script: eval detector tren synthetic corpus + shadow safety.

Chay:  docker exec alpha3s-m4-test python scripts/m4_pii_shadow_test.py

Kiem tra (Directive §7/§9):
  [1] Recall theo slot tren gate cases: phone >= 99%, address >= 95%, name >= 90%.
  [2] Precision theo slot >= 80% (bao cao so chinh xac; gate that o M4-G1 dung
      production shadow data — day la nguong development tren synthetic).
  [3] Risk class: moi case D2 phai ra D2; moi case D0 phai ra D0 (khong slot).
  [4] Latency detect(): p50/p95 tren toan corpus (nguong dev: p95 < 20ms).
  [5] Shadow metric KHONG chua plaintext PII (so dien thoai/ten/dia chi da gieo).
  [6] Detector exception bi shadow_scan nuot (containment) — khong raise, emit
      dong loi khong co noi dung tin nhan.
  [7] Flag OFF: shadow_scan tra None, khong in gi (baseline equivalence).
  [8] Known-limitation cases (gate=false): bao cao miss ky vong (failure taxonomy).

KHONG cham DB/Redis/vendor — thuan CPU. Corpus 100% synthetic (xem
scripts/m4_gen_synthetic_corpus.py).
"""

import io
import json
import statistics
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.pii import shadow as shadow_mod  # noqa: E402
from app.services.pii.detector import detect  # noqa: E402

CORPUS = ROOT / "datasets" / "pii" / "synthetic_corpus_v1.jsonl"
SLOTS = ["phone", "name", "address", "national_id", "bank_account"]
RECALL_GATE = {"phone": 0.99, "address": 0.95, "name": 0.90}
PRECISION_MIN = 0.80
LATENCY_P95_MS = 20.0

# Gia tri PII da gieo trong corpus — de assert KHONG xuat hien trong metric output.
PLANTED = [
    "0912345678", "0912 345 678", "0912.345.678", "0356789012", "0789012345",
    "02838123456", "84912345678", "079123456789", "0071000123456",
    "Nguyễn Văn An", "nguyen thi thu ha", "Lê Thị Mai", "Trần Bình",
    "đường Lê Lợi", "duong le loi", "ngõ 34 phố Huế", "ấp Bình Đông",
]

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


def main() -> int:
    cases = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    gate_cases = [c for c in cases if c["gate"]]
    limit_cases = [c for c in cases if not c["gate"]]
    print(f"corpus: {len(cases)} cases ({len(gate_cases)} gate / {len(limit_cases)} known-limit)\n")

    # ---- [1]+[2] recall/precision instance-level tren gate cases ----
    tp = dict.fromkeys(SLOTS, 0)
    fn = dict.fromkeys(SLOTS, 0)
    fp = dict.fromkeys(SLOTS, 0)
    risk_bad: list[str] = []
    latencies: list[float] = []
    fp_detail: list[str] = []
    fn_detail: list[str] = []

    for c in gate_cases:
        t0 = time.perf_counter()
        r = detect(c["text"])
        latencies.append((time.perf_counter() - t0) * 1000)
        for slot in SLOTS:
            got = sum(1 for s in r.spans if s.slot_type.value == slot)
            want = c["expect"][slot]
            tp[slot] += min(got, want)
            if got < want:
                fn[slot] += want - got
                fn_detail.append(f"{c['id']}:{slot} want={want} got={got}")
            elif got > want:
                fp[slot] += got - want
                fp_detail.append(f"{c['id']}:{slot} want={want} got={got}")
        if c["risk"] == "D2" and r.risk_class.value != "D2":
            risk_bad.append(f"{c['id']} want=D2 got={r.risk_class.value}")
        if c["risk"] == "D0" and r.risk_class.value != "D0":
            risk_bad.append(f"{c['id']} want=D0 got={r.risk_class.value}")

    print("== [1]/[2] Recall & precision (gate cases, instance-level) ==")
    for slot in SLOTS:
        denom_r = tp[slot] + fn[slot]
        denom_p = tp[slot] + fp[slot]
        recall = tp[slot] / denom_r if denom_r else 1.0
        precision = tp[slot] / denom_p if denom_p else 1.0
        print(f"  {slot:13s} recall={recall:6.1%} ({tp[slot]}/{denom_r})  "
              f"precision={precision:6.1%} ({tp[slot]}/{denom_p})")
        if slot in RECALL_GATE:
            check(recall >= RECALL_GATE[slot],
                  f"recall {slot} >= {RECALL_GATE[slot]:.0%}")
        if denom_p:
            check(precision >= PRECISION_MIN, f"precision {slot} >= {PRECISION_MIN:.0%}")
    if fn_detail:
        print("  false negatives: " + "; ".join(fn_detail))
    if fp_detail:
        print("  false positives: " + "; ".join(fp_detail))

    print("\n== [3] Risk class (D2 phai D2, D0 phai D0) ==")
    check(not risk_bad, "risk class dung het" + ("" if not risk_bad else f" — sai: {risk_bad}"))

    print("\n== [4] Latency detect() ==")
    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95) - 1]
    print(f"  p50={p50:.3f}ms p95={p95:.3f}ms n={len(latencies)}")
    check(p95 < LATENCY_P95_MS, f"latency p95 < {LATENCY_P95_MS}ms")

    # ---- [5] shadow metric khong lo plaintext ----
    print("\n== [5] Shadow metric PII-safe ==")
    settings.m4_pii_shadow = True
    buf = io.StringIO()
    with redirect_stdout(buf):
        for c in cases:
            shadow_mod.shadow_scan(c["text"])
    out = buf.getvalue()
    settings.m4_pii_shadow = False
    leaked = [p for p in PLANTED if p in out]
    # so dem/enum khong sao; kiem them: khong co day >=7 chu so lien trong output
    import re as _re
    digit_leak = _re.search(r"\d{7,}", out)
    check(not leaked, f"khong lo gia tri da gieo (leaked={leaked})")
    check(not digit_leak, "khong co day >=7 chu so trong metric output")
    check('"event": "m4_shadow_scan"' in out or '"event":"m4_shadow_scan"' in out.replace(" ", ""),
          "co emit event m4_shadow_scan")

    # ---- [6] containment ----
    print("\n== [6] Detector exception containment ==")
    settings.m4_pii_shadow = True
    orig = shadow_mod.detect

    def _boom(text):
        raise RuntimeError("loi gia lap CHUA NOI DUNG TIN NHAN: 0912345678")

    shadow_mod.detect = _boom
    buf2 = io.StringIO()
    try:
        with redirect_stdout(buf2):
            ret = shadow_mod.shadow_scan("tin nhan bat ky")
    finally:
        shadow_mod.detect = orig
        settings.m4_pii_shadow = False
    err_out = buf2.getvalue()
    check(ret is None, "shadow_scan khong raise, tra None khi detector loi")
    check("m4_shadow_error" in err_out, "co emit dong loi m4_shadow_error")
    check("0912345678" not in err_out and "CHUA NOI DUNG" not in err_out,
          "dong loi KHONG chua message cua exception (chi error_type)")

    # ---- [7] flag OFF ----
    print("\n== [7] Flag OFF equivalence ==")
    settings.m4_pii_shadow = False
    buf3 = io.StringIO()
    with redirect_stdout(buf3):
        ret_off = shadow_mod.shadow_scan("sđt 0912345678")
    check(ret_off is None and buf3.getvalue() == "", "flag OFF: khong scan, khong output")
    check(settings.m4_trusted_pii_path is False, "m4_trusted_pii_path placeholder OFF")

    # ---- [8] known limitations (bao cao, khong gate) ----
    print("\n== [8] Known-limitation cases (gate=false, ky vong miss) ==")
    for c in limit_cases:
        r = detect(c["text"])
        got = {s: sum(1 for x in r.spans if x.slot_type.value == s) for s in SLOTS}
        missed = {s: c["expect"][s] - got[s] for s in SLOTS if c["expect"][s] > got[s]}
        status = "MISS(ky vong)" if missed else "DETECTED(vuot ky vong)"
        print(f"  {c['id']}: {status} — {c['note']}")

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
