"""M5 Messenger standby — end-to-end signed-webhook harness (CA Directive 264 DoD §5).

Chay tren m5lab (isolated). Duong THAT: sign payload -> webhook.receive (parse + source marker) -> feed job
vao worker process_message (real redis dedup + real DB handle_message) voi Meta-outbound (send_text) +
take_thread_control MOCK (khong goi Meta). Chung minh:
- standby inbound -> customer + message row + bot reply sinh trong DB (canonical path nhu messaging);
- same-mid xuat hien o messaging LAN standby -> effective-once (khong tao 2 reply).
KHONG PII ra log. Re-runnable (RUN suffix).
"""
import asyncio
import hashlib
import hmac
import json
import sys
import time
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import webhook as wh
from app.config import settings
from app.db_pool import acquire, close_pool, release
from app.workers import tasks

RUN = str(int(time.time()))
FAILS = []


def ck(n, c, x=""):
    print(f"  [{'PASS' if c else 'FAIL'}] {n}{(' :: ' + str(x)) if x else ''}")
    if not c:
        FAILS.append(n)


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(settings.meta_app_secret.encode(), body, hashlib.sha256).hexdigest()


def _payload(container, mid, psid, text):
    return json.dumps({"object": "page", "entry": [{"id": "101836879023068", "time": 1,
        container: [{"sender": {"id": psid}, "recipient": {"id": "101836879023068"},
                     "timestamp": 1, "message": {"mid": mid, "text": text}}]}]}).encode()


class _RealishRedis:
    """enqueue capture + real-ish dedupe (in-proc) — dung cho ca webhook parse va worker dedup."""
    def __init__(self):
        self.jobs = []
        self.kv = {}

    async def enqueue_job(self, name, *args):
        self.jobs.append((name, args))

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True


async def q(s, *a):
    c = await acquire()
    try:
        return await c.fetchval(s, *a)
    finally:
        await release(c)


async def main():
    settings.enable_nlu_router = False
    redis = _RealishRedis()
    app = FastAPI(); app.include_router(wh.router)

    # 1) signed webhook -> parse standby -> enqueue voi source
    psid = f"mstest{RUN}"
    body = _payload("standby", f"s-{RUN}", psid, "cho em hoi ca phe sua da")
    with patch.object(wh, "_get_redis", AsyncMock(return_value=redis)):
        r = TestClient(app).post("/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    ck("signed standby webhook -> 200", r.status_code == 200, r.status_code)
    ck("enqueued 1 job source=standby",
       len(redis.jobs) == 1 and redis.jobs[0][1][1] == "standby", redis.jobs)

    # 2) worker xu ly job (real DB handle_message; Meta-outbound + take-control MOCK)
    ctx = {"redis": redis, "job_try": 1, "max_tries": 3}
    _, args = redis.jobs[0]
    event, source = args
    with patch.object(tasks, "try_take_thread_control", AsyncMock(return_value=True)) as tc, \
         patch.object(tasks, "send_text", AsyncMock()) as st:
        await tasks.process_message(ctx, event, source)
    ck("standby unpaused -> take_thread_control goi", tc.await_count == 1)
    ck("standby -> send_text goi (bot reply)", st.await_count == 1)

    cid = await q("SELECT id FROM customers WHERE psid=$1", psid)
    n_cust_msg = await q("SELECT count(*) FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                         "WHERE c.customer_id=$1 AND m.role='customer'", cid) if cid else 0
    n_bot_msg = await q("SELECT count(*) FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                        "WHERE c.customer_id=$1 AND m.role='bot'", cid) if cid else 0
    ck("standby -> customer message row tao trong DB", (n_cust_msg or 0) >= 1, f"cust_msg={n_cust_msg}")
    ck("standby -> bot reply row tao trong DB (canonical path)", (n_bot_msg or 0) >= 1, f"bot_msg={n_bot_msg}")

    # 3) same-mid xuat hien lai qua 'messaging' -> effective-once (deduped, khong reply lan 2)
    with patch.object(tasks, "try_take_thread_control", AsyncMock(return_value=True)), \
         patch.object(tasks, "send_text", AsyncMock()) as st2:
        await tasks.process_message(ctx, event, "messaging")  # cung mid
    ck("same-mid replay (messaging) -> effective-once (khong reply lan 2)", st2.await_count == 0)

    await close_pool()
    print("RESULT:", "ALL PASS" if not FAILS else f"FAIL {FAILS}")
    sys.exit(1 if FAILS else 0)


asyncio.run(main())
