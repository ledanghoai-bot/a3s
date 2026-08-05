#!/usr/bin/env python
"""I-B M4-S3 — evidence hardening: property sweep corpus + integrity + concurrency.

Chay:  docker exec alpha3s-m4-test python scripts/m4_hardening_test.py
(thuan CPU — khong DB/vendor; slot store dung fake in-memory co binding)

Kiem tra (Directive §4 M4-S3):
  [1] Property sweep MASK tren TOAN BO corpus 92 case: (a) masked text khong con
      gia tri cua bat ky span nao detector tim thay trong ban goc; (b) re-detect
      masked text: 0 span phone/national_id/bank_account sot lai.
  [2] Placeholder integrity (spec §10): sua tag / thieu mapping / lap / cross-
      conversation -> rehydrate deu None (fail closed).
  [3] D2 sweep: moi case risk=D2 trong corpus qua trusted_flow -> vendor 0 call,
      escalate (fallback 3).
  [4] Concurrency/replay: 8 process_turn song song cung (customer, conversation)
      + replay cung message -> khong exception, moi outcome hop le, slot khong
      re-bind sang context khac.
  [5] Telemetry: toan bo stdout [m4-*] cua phien khong chua PII tu corpus.
  [6] Flag-OFF tong: m4_pii_shadow/m4_trusted_pii_path default False; orchestrator
      khong tham chieu trusted_flow/m4_trusted_pii_path (static).
"""

import asyncio
import base64
import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings, settings  # noqa: E402
from app.services.pii import slot_store as slot_store_mod  # noqa: E402
from app.services.pii import trusted_flow  # noqa: E402
from app.services.pii.detector import detect  # noqa: E402
from app.services.pii.masking import (  # noqa: E402
    mask_text,
    rehydrate_response,
)
from app.services.pii.normalize import nfc  # noqa: E402

CORPUS = ROOT / "datasets" / "pii" / "synthetic_corpus_v1.jsonl"
_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


class FakeStore:
    def __init__(self):
        self.rows = []

    async def store_slot(self, conn, *, customer_ref, conversation_ref, slot_type,
                         value, confidence, **_kw):
        key = (customer_ref, conversation_ref, slot_type, value)
        deduped = any(r[:4] == key for r in self.rows)
        if not deduped:
            self.rows.append((customer_ref, conversation_ref, slot_type, value, confidence))
        return slot_store_mod.StoredSlot(slot_id=f"f{len(self.rows)}", deduped=deduped)

    async def resolve_slot(self, conn, *, customer_ref, conversation_ref, slot_type,
                           min_confidence="low"):
        order = {"high": 2, "medium": 1, "low": 0}
        for c, v, st, val, conf in [r for r in reversed(self.rows)]:
            if (c, v, st) == (customer_ref, conversation_ref, slot_type) \
                    and order[conf] >= order[min_confidence]:
                return val
        return None


async def main() -> int:
    settings.m4_slot_fp_key_b64 = base64.b64encode(os.urandom(32)).decode()
    cases = [json.loads(x) for x in CORPUS.read_text(encoding="utf-8").splitlines() if x.strip()]
    logs = io.StringIO()

    print("== [1] Property sweep mask tren corpus ==")
    leak_cases, residual_cases = [], []
    pii_values: set[str] = set()
    for c in cases:
        text = nfc(c["text"])
        spans = detect(text).spans
        values = [text[s.start:s.end] for s in spans]
        pii_values.update(v for v in values if len(v) >= 4)
        r = mask_text(text, conversation_ref="conv-sweep")
        if any(v in r.masked_text for v in values):
            leak_cases.append(c["id"])
        left = detect(r.masked_text)
        if any(s.slot_type.value in ("phone", "national_id", "bank_account")
               for s in left.spans):
            residual_cases.append(c["id"])
    check(not leak_cases, f"masked text khong chua gia tri span goc (fail={leak_cases})")
    check(not residual_cases,
          f"re-detect masked: 0 slot so (phone/nid/bank) sot (fail={residual_cases})")

    print("== [2] Placeholder integrity (sua/thieu/lap/cross-context) ==")
    r = mask_text("goi cho minh so 0912345678 nhe", conversation_ref="conv-A")
    (ph,) = list(r.mapping)
    ok = rehydrate_response(f"Em goi {ph} ngay", r.mapping, conversation_ref="conv-A")
    check(ok is not None and "0912345678" in ok, "tag dung conv -> rehydrate OK")
    mangled = re.sub(r"_[0-9a-f]{8}\]$", "_deadbeef]", ph)
    check(rehydrate_response(f"Em goi {mangled}", {**r.mapping, mangled: r.mapping[ph]},
                             conversation_ref="conv-A") is None,
          "tag bi sua -> reject (ke ca khi mapping bi tron)")
    check(rehydrate_response(f"Em goi {ph}", r.mapping, conversation_ref="conv-B") is None,
          "placeholder conv-A dung trong conv-B -> reject")
    check(rehydrate_response(f"{ph} va {ph}", r.mapping, conversation_ref="conv-A") is None,
          "placeholder lap 2 lan -> reject")
    check(rehydrate_response("Goi [PII_PHONE_9] nhe", r.mapping,
                             conversation_ref="conv-A") is None,
          "placeholder thieu trong mapping -> reject")

    print("== [3] D2 sweep qua trusted_flow (vendor 0 call) ==")
    fake = FakeStore()
    trusted_flow.slot_store.store_slot = fake.store_slot
    trusted_flow.slot_store.resolve_slot = fake.resolve_slot
    model_calls = []

    async def spy_model(messages):
        model_calls.append(messages)
        return {"intent": "other", "missing_slot_types": [],
                "response_candidate": "ok", "context": {}}

    async def spy_exec(args):
        return {"order_id": "X", "status": "created"}

    d2_cases = [c for c in cases if c["risk"] == "D2"]
    bad = []
    for c in d2_cases:
        with redirect_stdout(logs):
            out = await trusted_flow.process_turn(
                None, customer_ref="cust-D2", conversation_ref="conv-D2",
                text=c["text"], model_call=spy_model, command_executor=spy_exec)
        if out.kind != "escalate" or model_calls:
            bad.append(c["id"])
    check(not bad and len(d2_cases) >= 10,
          f"{len(d2_cases)} case D2: deu escalate, model 0 call (fail={bad})")

    print("== [4] Concurrency/replay process_turn ==")
    fake2 = FakeStore()
    trusted_flow.slot_store.store_slot = fake2.store_slot
    trusted_flow.slot_store.resolve_slot = fake2.resolve_slot

    async def order_model(messages):
        return {"intent": "order.create", "missing_slot_types": [],
                "response_candidate": "",
                "context": {"items": [{"sku": "3S-500G", "qty": 2}]}}

    async def catalog_fake(proposed):
        return {p: ("3S-500G" if p.replace("-", "").upper() == "3S500G" else None)
                for p in proposed}

    exec_calls = []

    async def exec2(args):
        exec_calls.append(args)
        return {"order_id": f"SYN-{len(exec_calls)}", "status": "created"}

    msg = "Nguoi nhan Tran Binh, 0912345678, so 12 duong Le Loi, phuong 5, quan 3, dat 2 goi"
    with redirect_stdout(logs):
        outs = await asyncio.gather(*[
            trusted_flow.process_turn(None, customer_ref="cust-CC",
                                      conversation_ref="conv-CC", text=msg,
                                      model_call=order_model, command_executor=exec2,
                                      sku_resolver=catalog_fake)
            for _ in range(8)])
    kinds = {o.kind for o in outs}
    cross = [r for r in fake2.rows if r[0] != "cust-CC" or r[1] != "conv-CC"]
    check(kinds <= {"command_receipt", "ask_slot"} and not cross,
          f"8 turn song song + replay: outcome hop le {sorted(kinds)}, khong re-bind context")
    dup_phone = [r for r in fake2.rows if r[2] == "phone"]
    check(len(dup_phone) == 1, "replay cung phone -> dedupe 1 row trong fake store")

    print("== [5] Telemetry khong PII ==")
    content = logs.getvalue()
    leaked = sorted(v for v in pii_values if v in content)[:5]
    check("[m4-flow]" in content and not leaked,
          f"log [m4-*] khong chua gia tri PII corpus (leaked={leaked})")

    print("== [6] Flag-OFF tong + static ==")
    fresh = Settings(_env_file=None)
    check(fresh.m4_pii_shadow is False and fresh.m4_trusted_pii_path is False,
          "m4_* default OFF (missing config = OFF)")
    src = (ROOT / "app" / "services" / "orchestrator.py").read_text(encoding="utf-8")
    check("trusted_flow" not in src and "m4_trusted_pii_path" not in src,
          "orchestrator khong noi trusted_flow / khong tham chieu m4_trusted_pii_path")

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
