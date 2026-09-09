"""M5 Messenger standby inbound — webhook + worker tests. CA Directive 264.

Phu: signature valid/invalid; parse messaging + standby + mixed; ignore non-message (delivery/read); malformed
payload khong crash; structured metadata log KHONG PII; worker standby unpaused -> take-control + canonical;
paused -> khong take-control/reply; take-control fail khong crash/khong dup; dedupe cung-mid effective-once
xuyen messaging/standby.
"""
import asyncio
import hashlib
import hmac
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.api import webhook as wh
from app.config import settings
from app.workers import tasks


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(settings.meta_app_secret.encode(), body, hashlib.sha256).hexdigest()


def _msg_event(mid="m1", text="cho em hoi gia ca phe", psid="PSID123"):
    return {"sender": {"id": psid}, "recipient": {"id": "101836879023068"},
            "timestamp": 1, "message": {"mid": mid, "text": text}}


def _payload(messaging=None, standby=None):
    entry = {"id": "101836879023068", "time": 1}
    if messaging is not None:
        entry["messaging"] = messaging
    if standby is not None:
        entry["standby"] = standby
    return json.dumps({"object": "page", "entry": [entry]}).encode()


class _FakeRedis:
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


@pytest.fixture
def client_and_redis():
    app = FastAPI()
    app.include_router(wh.router)
    fake = _FakeRedis()
    with patch.object(wh, "_get_redis", AsyncMock(return_value=fake)):
        yield TestClient(app), fake


# ---------------- webhook boundary (§3.1) ----------------

def test_invalid_signature_403(client_and_redis):
    client, fake = client_and_redis
    body = _payload(messaging=[_msg_event()])
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=deadbeef"})
    assert r.status_code == 403
    assert fake.jobs == []


def test_messaging_enqueued_with_source(client_and_redis):
    client, fake = client_and_redis
    body = _payload(messaging=[_msg_event(mid="m1")])
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    assert r.status_code == 200
    assert len(fake.jobs) == 1
    name, args = fake.jobs[0]
    assert name == "process_message" and args[1] == "messaging"


def test_standby_enqueued_with_source(client_and_redis):
    client, fake = client_and_redis
    body = _payload(standby=[_msg_event(mid="s1")])
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    assert r.status_code == 200
    assert len(fake.jobs) == 1 and fake.jobs[0][1][1] == "standby"


def test_mixed_containers(client_and_redis):
    client, fake = client_and_redis
    body = _payload(messaging=[_msg_event(mid="m1")], standby=[_msg_event(mid="s1")])
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    assert r.status_code == 200
    sources = sorted(a[1] for _, a in fake.jobs)
    assert sources == ["messaging", "standby"]


def test_non_message_events_ignored(client_and_redis):
    client, fake = client_and_redis
    # delivery + read metadata (khong co `message`) -> KHONG enqueue
    delivery = {"sender": {"id": "P"}, "recipient": {"id": "PG"}, "delivery": {"mids": ["m1"]}}
    read = {"sender": {"id": "P"}, "recipient": {"id": "PG"}, "read": {"watermark": 1}}
    body = _payload(messaging=[delivery, read])
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    assert r.status_code == 200 and fake.jobs == []


def test_malformed_payload_no_crash(client_and_redis):
    client, fake = client_and_redis
    body = b"{not json"
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    assert r.status_code == 200 and fake.jobs == []


def test_structured_log_metadata_only(client_and_redis, capsys):
    client, fake = client_and_redis
    body = _payload(messaging=[_msg_event(mid="m1", text="SECRETTEXT", psid="PSIDSECRET")],
                    standby=[_msg_event(mid="s1", text="SECRETTEXT", psid="PSIDSECRET")])
    client.post("/webhook", content=body, headers={"X-Hub-Signature-256": _sign(body)})
    out = capsys.readouterr().out
    assert "entries=1" in out and "messaging=1" in out and "standby=1" in out and "enqueued=2" in out
    # KHONG PII/secret trong log
    assert "SECRETTEXT" not in out and "PSIDSECRET" not in out and "sha256=" not in out


# ---------------- worker standby processing (§3.3 / §3.4) ----------------

def _ctx():
    return {"redis": _FakeRedis(), "job_try": 1, "max_tries": 3}


def test_standby_unpaused_takes_control_and_replies():
    async def _run():
        ev = _msg_event(mid="s1")
        with patch.object(tasks, "is_bot_paused", AsyncMock(return_value=False)), \
             patch.object(tasks, "try_take_thread_control", AsyncMock(return_value=True)) as tc, \
             patch.object(tasks, "handle_message", AsyncMock(return_value="reply")) as hm, \
             patch.object(tasks, "send_text", AsyncMock()) as st:
            await tasks.process_message(_ctx(), ev, "standby")
        tc.assert_awaited_once()
        hm.assert_awaited_once()
        assert hm.call_args.kwargs["channel"] == "messenger"
        st.assert_awaited_once()
    asyncio.run(_run())


def test_paused_no_control_no_reply():
    async def _run():
        ev = _msg_event(mid="s1")
        fake_cl = AsyncMock()
        fake_cl.ensure_conversation = AsyncMock(return_value=7)
        fake_cl.log_message = AsyncMock()
        with patch.object(tasks, "is_bot_paused", AsyncMock(return_value=True)), \
             patch.object(tasks, "try_take_thread_control", AsyncMock()) as tc, \
             patch.object(tasks, "handle_message", AsyncMock()) as hm, \
             patch.object(tasks, "send_text", AsyncMock()) as st, \
             patch.object(tasks, "conversation_log", fake_cl):
            await tasks.process_message(_ctx(), ev, "standby")
        tc.assert_not_awaited()
        hm.assert_not_awaited()
        st.assert_not_awaited()
        fake_cl.log_message.assert_awaited_once()  # van log de giu lien tuc hoi thoai
    asyncio.run(_run())


def test_take_control_failure_no_crash_still_replies():
    async def _run():
        ev = _msg_event(mid="s1")
        with patch.object(tasks, "is_bot_paused", AsyncMock(return_value=False)), \
             patch.object(tasks, "try_take_thread_control", AsyncMock(return_value=False)), \
             patch.object(tasks, "handle_message", AsyncMock(return_value="reply")) as hm, \
             patch.object(tasks, "send_text", AsyncMock()) as st:
            await tasks.process_message(_ctx(), ev, "standby")  # khong raise
        hm.assert_awaited_once()
        st.assert_awaited_once()
    asyncio.run(_run())


def test_same_mid_effective_once_across_sources():
    async def _run():
        ctx = _ctx()  # cung redis -> dedup xuyen 2 lan
        ev = _msg_event(mid="dupmid")
        with patch.object(tasks, "is_bot_paused", AsyncMock(return_value=False)), \
             patch.object(tasks, "try_take_thread_control", AsyncMock(return_value=True)), \
             patch.object(tasks, "handle_message", AsyncMock(return_value="reply")) as hm, \
             patch.object(tasks, "send_text", AsyncMock()) as st:
            await tasks.process_message(ctx, ev, "messaging")  # lan 1 (messaging)
            await tasks.process_message(ctx, ev, "standby")    # lan 2 cung mid (standby) -> deduped
        assert hm.await_count == 1 and st.await_count == 1
    asyncio.run(_run())
