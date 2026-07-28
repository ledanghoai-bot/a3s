#!/usr/bin/env python
"""I-B M4-S2 — evidence E2E: masked conversation -> trusted command -> receipt.

Chay:  docker exec -e DATABASE_URL=postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s \
           alpha3s-m4-test python scripts/m4_masked_flow_test.py

Khac unit test (fake store): script nay dung Slot Store THAT (pii_slots, crypto
AES-GCM binding) tren DB rieng cua worktree M4. Model = SPY MOCK ghi lai MOI
payload nhan duoc — KHONG vendor call (Directive §5).

Kiem tra:
  [A] E2E don hang 2 turn: PII vao store, model chi thay mask (ca history),
      command args lap tu STORE, receipt deterministic + phone mask ***.
  [B] Tich luy slot qua nhieu turn cung hoi thoai: thieu -> hoi (fallback 1)
      -> khach cung cap -> du -> chot don.
  [C] D2 (mang thai/CCCD): vendor KHONG duoc goi, escalate (fallback 3).
  [D] Model doi pha rao: unknown key/tool_args PII/refs/placeholder mangle ->
      escalate, command executor KHONG chay.
  [E] Cross-conversation: slot conv nay khong keo sang conv khac (binding that).
  [F] Latency process_turn (co DB + crypto) p50/p95.
  [G] Toan bo stdout log cua phien: khong chua PII da gieo.
"""

import asyncio
import base64
import io
import os
import statistics
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.pii import trusted_flow  # noqa: E402

DB_URL = (os.environ.get("DATABASE_URL")
          or "postgresql://alpha3s:alpha3s@alpha3s-m4-db:5432/alpha3s").replace("+asyncpg", "")

PHONE, NAME = "0912345678", "Nguyễn Văn An"
ADDR_LEAK = "Lê Lợi"
ORDER_TEXT = f"Đặt 2 gói 500g. Người nhận {NAME}, {PHONE}, số 12 đường {ADDR_LEAK}, phường 5, quận 3"
PLANTED = [PHONE, "912345678", NAME, "Nguyễn", ADDR_LEAK, "0356789012"]

_fail: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        _fail.append(label)


class SpyModel:
    def __init__(self):
        self.script: list[dict] = []
        self.received: list[list[dict]] = []

    async def __call__(self, messages):
        self.received.append([dict(m) for m in messages])
        return self.script.pop(0)


class SpyExecutor:
    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, args):
        self.calls.append(args)
        return {"order_id": f"SYN-{len(self.calls):03d}", "status": "created"}


ORDER_OUT = {"intent": "order.create", "missing_slot_types": [],
             "response_candidate": "", "context": {"items": [{"sku": "3S-500G", "qty": 2}]}}
SMALL_OUT = {"intent": "smalltalk", "missing_slot_types": [],
             "response_candidate": "Dạ đơn đang được chuẩn bị ạ", "context": {}}


async def main() -> int:
    settings.m4_slot_key_b64 = base64.b64encode(os.urandom(32)).decode()
    settings.m4_slot_fp_key_b64 = base64.b64encode(os.urandom(32)).decode()

    conn = await asyncpg.connect(DB_URL)
    logs = io.StringIO()
    model = SpyModel()
    executor = SpyExecutor()
    latencies: list[float] = []

    async def turn(cust, conv, text, output, history=None):
        model.script = [output] if not isinstance(output, list) else output
        t0 = time.perf_counter()
        with redirect_stdout(logs):
            out = await trusted_flow.process_turn(
                conn, customer_ref=cust, conversation_ref=conv, text=text,
                history=history or [], model_call=model, command_executor=executor)
        latencies.append((time.perf_counter() - t0) * 1000)
        return out

    try:
        await conn.execute("DELETE FROM pii_slots")

        print("== [A] E2E don hang 2 turn (store that + mask history) ==")
        o1 = await turn("cust-A", "conv-1", ORDER_TEXT, dict(ORDER_OUT))
        check(o1.kind == "command_receipt" and "SYN-001" in o1.reply,
              "turn 1: chot don, receipt deterministic")
        check("***678" in o1.reply and PHONE not in o1.reply,
              "receipt mask phone (***678), khong lo so day du")
        args = executor.calls[0]
        check(args["shipping_phone"] == PHONE and args["shipping_name"] == NAME
              and args["customer_ref"] == "cust-A" and args["conversation_ref"] == "conv-1",
              "command args lap tu STORE + refs trusted (khong tu model)")
        hist = [{"role": "user", "content": ORDER_TEXT},
                {"role": "assistant", "content": o1.reply}]
        o2 = await turn("cust-A", "conv-1", f"đơn của {NAME} tới đâu rồi, gọi {PHONE} nhé",
                        dict(SMALL_OUT), history=hist)
        check(o2.kind == "reply", "turn 2: tra loi thuong")
        sent = " ".join(m["content"] for call in model.received for m in call)
        leaked = [p for p in PLANTED if p in sent]
        check(not leaked, f"model KHONG BAO GIO thay PII tho (ca history) — leaked={leaked}")

        print("== [B] Tich luy slot qua nhieu turn ==")
        await conn.execute("DELETE FROM pii_slots")
        executor.calls.clear()
        b1 = await turn("cust-B", "conv-9", "cho mình 2 gói 500g nhé", dict(ORDER_OUT))
        check(b1.kind == "ask_slot" and b1.asked_slot == "phone", "thieu het -> hoi phone")
        b2 = await turn("cust-B", "conv-9", f"số mình là {PHONE} nha", dict(ORDER_OUT))
        check(b2.kind == "ask_slot" and b2.asked_slot == "address",
              "co phone -> hoi tiep address")
        b3 = await turn("cust-B", "conv-9",
                        "giao về số 45 ngõ 78 phố Huế, quận Hai Bà Trưng, Hà Nội, tên Trần Bình",
                        dict(ORDER_OUT))
        check(b3.kind == "command_receipt" and len(executor.calls) == 1,
              "du 3 slot sau 3 turn -> chot don")

        print("== [C] D2 khong cham vendor ==")
        before = len(model.received)
        c1 = await turn("cust-C", "conv-2", "mình đang mang thai uống được không", dict(SMALL_OUT))
        check(c1.kind == "escalate" and c1.escalate_reason == "d2_high_risk"
              and len(model.received) == before, "health D2 -> escalate, model 0 call")
        c2 = await turn("cust-C", "conv-2", "CCCD 079123456789 nhận hàng đúng không", dict(SMALL_OUT))
        check(c2.kind == "escalate" and len(model.received) == before,
              "CCCD (high-risk slot) -> escalate, model 0 call")

        print("== [D] Model doi pha rao -> fail closed ==")
        executor.calls.clear()
        d1 = await turn("cust-A", "conv-1", ORDER_TEXT,
                        {**ORDER_OUT, "tool_args": {"phone": PHONE}})
        d2 = await turn("cust-A", "conv-1", ORDER_TEXT,
                        {"intent": "order.create", "missing_slot_types": [],
                         "response_candidate": "",
                         "context": {"items": [{"sku": "X", "qty": 1}],
                                     "customer_ref": "cust-VICTIM"}})
        d3 = await turn("cust-A", "conv-1", f"gọi {PHONE} nhé",
                        {"intent": "smalltalk", "missing_slot_types": [],
                         "response_candidate": "goi [PII_PHONE_99] ngay", "context": {}})
        check(d1.kind == d2.kind == d3.kind == "escalate",
              "tool_args PII / chon ref / placeholder mangle -> deu escalate")
        # CA F-M4-S2-04: smuggle phone qua sku
        d5 = await turn("cust-A", "conv-1", ORDER_TEXT,
                        {"intent": "order.create", "missing_slot_types": [],
                         "response_candidate": "",
                         "context": {"items": [{"sku": PHONE, "qty": 1}]}})
        check(d5.kind == "escalate", "sku = phone (smuggle) -> escalate")
        check(executor.calls == [], "command executor KHONG chay trong moi ca pha rao")
        # CA F-M4-S3-03: history D2 (khong slot so) + current D0 -> model van goi
        # nhung payload PHAI sach D2
        before_d2h = len(model.received)
        d6 = await turn("cust-A", "conv-1", "shop mở cửa tới mấy giờ", dict(SMALL_OUT),
                        history=[{"role": "user", "content": "mình bị tiểu đường nặng"}])
        d6_sent = " ".join(m["content"] for m in model.received[before_d2h])
        check(d6.kind == "reply" and "tiểu đường" not in d6_sent
              and "[TURN_REDACTED_D2]" in d6_sent,
              "history D2 bi redact truoc vendor (marker thay noi dung)")

        print("== [E] Cross-conversation binding ==")
        e1 = await turn("cust-B", "conv-KHAC", "chốt 2 gói như cũ nhé", dict(ORDER_OUT))
        check(e1.kind == "ask_slot", "slot conv-9 khong keo sang conv-KHAC -> hoi lai")

        print("== [F] Latency process_turn (DB + crypto that) ==")
        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
        print(f"  p50={p50:.1f}ms p95={p95:.1f}ms n={len(latencies)}")
        check(p95 < 250, "p95 < 250ms (nguong dev, chua tinh vendor)")

        print("== [G] Log phien khong PII ==")
        content = logs.getvalue()
        leaked = [p for p in PLANTED if p in content]
        check(not leaked, f"log [m4-*] khong chua PII gieo — leaked={leaked}")

        await conn.execute("DELETE FROM pii_slots")
    finally:
        await conn.close()

    print()
    if _fail:
        print(f"RESULT: FAIL ({len(_fail)}): " + "; ".join(_fail))
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
