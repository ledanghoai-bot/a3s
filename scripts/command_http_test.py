#!/usr/bin/env python3
"""HTTP contract evidence (I-B M1 Slice 7). Spec §10.2.

In-process ASGI (httpx.AsyncClient + ASGITransport, MOT event loop -> asyncpg pool on-dinh),
override auth dependency = staff gia (id that de audit FK), flag BAT. Bao phu status codes:
  400 thieu Idempotency-Key / 201 first / 200 duplicate / 202 in_progress /
  409 conflict / 422 business reject + validation / receipt lookup 200/404.

  docker exec -e DATABASE_URL=...m1_itest -e PYTHONPATH=/srv -w /srv api python scripts/command_http_test.py
"""
import asyncio
import sys

import asyncpg

from app.config import settings

settings.m1_reliable_order_command = True

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.api.auth import require_staff_session  # noqa: E402
from app.main import app  # noqa: E402
from app.services import auth_service  # noqa: E402
from app.services.command import repository as repo  # noqa: E402
from app.services.command.envelope import (  # noqa: E402
    Actor,
    build_order_create_envelope,
)

STAFF = {"id": None, "username": "http_staff", "name": "HTTP", "rbac_provisioned": True,
         "permissions": {"commands.view"}, "must_change_password": False}
BODY = {"customer_name": "Http User", "phone": "0911222333", "address": "1 Test St",
        "sku": "3S-100G", "quantity": 1, "unit_price_vnd": 150000}
URL = "/dashboard/orders/manual"


def _db():
    return settings.database_url.replace("+asyncpg", "")


async def main() -> int:  # noqa: C901
    conn = await asyncpg.connect(_db())
    try:
        await conn.execute("TRUNCATE order_items, orders, command_executions, outbox_events, "
                           "delivery_attempts, price_overrides RESTART IDENTITY CASCADE")
        await conn.execute("UPDATE products SET stock=1000 WHERE sku='3S-100G'")
        st = await auth_service.create_staff_user("http_staff", "pw12345678", "HTTP", role_key="admin")
        STAFF["id"] = st["id"]
        env = build_order_create_envelope(raw_payload=dict(BODY), actor=Actor("staff", str(st["id"])),
                                          channel="dashboard", idempotency_key="idemp-http-inprog-01")
        await repo.insert_command(conn, env.as_insert_params(status="processing"))
    finally:
        await conn.close()

    app.dependency_overrides[require_staff_session] = lambda: STAFF
    fails: list[str] = []

    def H(k):
        return {"Idempotency-Key": k}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(URL, json=BODY)  # 400 thieu key
        if r.status_code != 400:
            fails.append(f"400 no-key: {r.status_code} {r.text[:120]}")

        r = await c.post(URL, json=BODY, headers=H("idemp-http-key-0001"))  # 201 first
        if r.status_code != 201 or "receipt" not in r.json():
            fails.append(f"201 first: {r.status_code} {r.text[:160]}")
        cmd_id = r.json().get("receipt", {}).get("command_id")
        order_id = r.json().get("order_id")

        r = await c.post(URL, json=BODY, headers=H("idemp-http-key-0001"))  # 200 duplicate
        if r.status_code != 200 or not r.json().get("duplicate") or r.json().get("order_id") != order_id:
            fails.append(f"200 dup: {r.status_code} {r.text[:160]}")

        r = await c.post(URL, json=dict(BODY, quantity=2), headers=H("idemp-http-key-0001"))  # 409
        if r.status_code != 409 or r.json().get("error_code") != "idempotency_conflict":
            fails.append(f"409 conflict: {r.status_code} {r.text[:160]}")

        r = await c.post(URL, json=dict(BODY, quantity=999999), headers=H("idemp-http-stock-01"))  # 422 stock
        if r.status_code != 422 or r.json().get("error_code") != "insufficient_stock":
            fails.append(f"422 stock: {r.status_code} {r.text[:160]}")

        r = await c.post(URL, json=dict(BODY, phone="123"), headers=H("idemp-http-phone-01"))  # 422 validation
        if r.status_code != 422 or r.json().get("error_code") != "invalid_phone":
            fails.append(f"422 phone: {r.status_code} {r.text[:160]}")

        r = await c.post(URL, json=BODY, headers=H("idemp-http-inprog-01"))  # 202 in_progress
        if r.status_code != 202 or r.headers.get("Retry-After") is None:
            fails.append(f"202 in_progress: {r.status_code} retry-after={r.headers.get('Retry-After')}")

        if cmd_id:
            r = await c.get(f"/dashboard/commands/{cmd_id}/receipt")  # lookup 200
            if r.status_code != 200 or r.json().get("outcome") != "succeeded":
                fails.append(f"receipt 200: {r.status_code} {r.text[:160]}")
        r = await c.get("/dashboard/commands/00000000-0000-0000-0000-000000000000/receipt")  # 404
        if r.status_code != 404:
            fails.append(f"receipt 404: {r.status_code}")

    if fails:
        print("COMMAND-HTTP FAIL:")
        for f in fails:
            print("  -", f)
        return 1
    print("COMMAND-HTTP PASS: 400 no-key / 201 first / 200 dup / 409 conflict / 422 stock+phone / "
          "202 in_progress+Retry-After / receipt lookup 200+404.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
