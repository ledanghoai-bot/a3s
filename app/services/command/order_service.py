"""Application service: order.create.v1 (I-B M1). Spec §5.2, §8.1, §10.1.

Mot transaction duy nhat cho ca ba caller (AI tool, dashboard bot, manual):
  insert command (unique) -> lock+validate product -> customer/order/items/stock mutation
  -> persist deterministic result -> insert outbox -> audit (fail-closed) -> commit.
KHONG goi HTTP/LLM/Redis/Telegram trong transaction (§5.2). External delivery chay sau qua outbox.

Effective-once (§8.1): insert command truoc; trung unique -> loser doc receipt da commit (KHONG mutate
lan hai). Cung key + khac hash -> 409 conflict (audit). Business reject -> failed_terminal (idempotent).
"""
from __future__ import annotations

import json
import uuid

import asyncpg

from app.config import settings
from app.db_pool import acquire, release
from app.services import audit_service
from app.services.address import order_binding
from app.services.command import errors
from app.services.command import receipt as receipt_mod
from app.services.command import repository as repo
from app.services.command.envelope import CommandEnvelope
from app.services.command.observability import log_event
from app.services.command.retry import MAX_ATTEMPTS
from app.services.inventory import repository as inv_repo
from app.services.inventory.errors import InventoryError
from app.services.order import transition_service as order_txn
from app.services.tools import MAX_AUTO_QUANTITY, _unit_price_for_quantity

OUTBOX_DEST_TELEGRAM_ADMIN = "telegram_admin"
OUTBOX_EVENT_ORDER_CREATED = "order.created.notify"

_OVERRIDE_SQL = """
SELECT po.id, po.unit_price_vnd
FROM price_overrides po JOIN customers cu ON cu.id = po.customer_id
WHERE cu.psid = $1 AND po.quantity = $2 AND po.used = FALSE
ORDER BY po.created_at DESC LIMIT 1
"""


def _fmt_ts(dt) -> str | None:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt is not None else None


def _audit_actor(env: CommandEnvelope) -> tuple[str, str, int | None]:
    """Map envelope actor -> (audit actor_type, actor_ref, actor_staff_id)."""
    if env.actor.type == "staff":
        sid = int(env.actor.id) if env.actor.id.isdigit() else None
        return "staff", env.actor.id, sid
    if env.actor.type == "system":
        return "system", env.actor.id, None
    return "bot", env.actor.id, None  # customer-initiated, bot-executed


def _loads(v):
    return json.loads(v) if isinstance(v, str) else v


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def execute_order_create(env: CommandEnvelope) -> receipt_mod.CommandReceipt:
    """Thuc thi order.create idempotent. Tra CommandReceipt (succeeded/rejected/in_progress).
    Raise CommandError(409) khi idempotency conflict."""
    conn = await acquire()
    try:
        try:
            async with conn.transaction():
                await repo.insert_command(conn, env.as_insert_params(status="processing"))
                receipt = await _run_winner(conn, env)
            return receipt  # da commit
        except asyncpg.UniqueViolationError as e:
            # CHỈ idempotency-key conflict mới là "duplicate command". Unique khác (vd customers.psid
            # — dù đã ON CONFLICT phòng thủ, hoặc constraint M2-M6 tương lai) KHÔNG được coi là duplicate
            # -> raise (không nuốt, không misroute). FINDING 1 (adversarial self-review).
            if getattr(e, "constraint_name", None) == "command_executions_idem_key":
                return await _resolve_duplicate(conn, env)
            raise
    finally:
        await release(conn)


async def get_command_receipt(command_id: str, actor_context: dict | None = None
                              ) -> receipt_mod.CommandReceipt:
    """Doc receipt tu committed state (RBAC/ownership enforce o API layer — Slice 7)."""
    conn = await acquire()
    try:
        row = await repo.get_by_id(conn, command_id)
        if row is None:
            raise errors.CommandError("command_not_found", "Khong tim thay command.", http_status=404)
        return _receipt_from_row(row, duplicate=False)
    finally:
        await release(conn)


# ---------------------------------------------------------------------------
# Winner path (mutation trong transaction)
# ---------------------------------------------------------------------------

async def _run_winner(conn, env: CommandEnvelope) -> receipt_mod.CommandReceipt:
    p = env.payload  # normalized FULL (co address/psid) — chi in-memory
    sku = p["sku"]
    qty = p["quantity"]

    product = await conn.fetchrow(
        "SELECT id, price_vnd, stock FROM products WHERE sku = $1 FOR UPDATE", sku
    )
    if product is None:
        return await _reject(conn, env, errors.PRODUCT_NOT_FOUND, f"sku khong ton tai: {sku}")
    # --- Availability authority (AC-M2-13, CA M2-S1-F05) ---
    # Phase A/B: legacy products.stock là authority. Phase C (m2_balance_authority ON): đọc
    # availability TỪ balance (default location); products.stock chỉ còn mirror. Chống split-brain:
    # dùng ĐÚNG một nguồn cho accept decision. Reserve dưới FOR UPDATE mới là guard cuối (no oversell).
    if settings.m2_inventory_ledger and settings.m2_balance_authority:
        loc_auth = await inv_repo.resolve_default_location(conn)
        bal_auth = await inv_repo.get_balance(conn, loc_auth, product["id"])
        available = (bal_auth["on_hand"] - bal_auth["reserved"]) if bal_auth else 0
    else:
        available = product["stock"]
    if available < qty:
        return await _reject(conn, env, errors.INSUFFICIENT_STOCK,
                             f"con {available}, can {qty}")

    # --- Pricing: staff-priced (manual) vs system-priced (AI/bot) ---
    if "unit_price_vnd" in p:
        unit_price = p["unit_price_vnd"]
    else:
        psid = p.get("psid")
        override_price = None  # != None nghĩa là ĐÃ consume được override (single-use)
        if psid:
            override_row = await conn.fetchrow(_OVERRIDE_SQL, psid, qty)
            if override_row is not None:
                # Consume ATOMIC single-use: chỉ thắng nếu vẫn used=FALSE. Chặn double-spend khi 2 đơn
                # khác SKU cùng psid+qty (SELECT products FOR UPDATE chỉ khóa cùng SKU). FINDING 2.
                # Trong cùng transaction -> nếu đơn reject sau đó, consume cũng rollback.
                consumed_id = await conn.fetchval(
                    "UPDATE price_overrides SET used=TRUE, status='used' "
                    "WHERE id=$1 AND used=FALSE RETURNING id", override_row["id"])
                if consumed_id is not None:
                    override_price = override_row["unit_price_vnd"]
        if qty > MAX_AUTO_QUANTITY and override_price is None:
            return await _reject(conn, env, errors.QUANTITY_EXCEEDS_AUTO_LIMIT,
                                 f"qty {qty} > {MAX_AUTO_QUANTITY} khong co override")
        if override_price is not None:
            unit_price = override_price
        else:
            tiers = await conn.fetch(
                "SELECT min_qty, unit_price_vnd FROM price_tiers WHERE product_id = $1",
                product["id"],
            )
            unit_price = _unit_price_for_quantity(tiers, qty) or product["price_vnd"]

    total = unit_price * qty

    # --- Customer upsert ATOMIC (psid hoac manual:<uuid>) ---
    # ON CONFLICT (psid) DO UPDATE: 2 đơn đồng thời của khách MỚI (khác idempotency key) không còn
    # đâm nhau ở customers.psid UNIQUE -> cả hai tạo đơn đúng. FINDING 1 (adversarial self-review).
    customer_psid = p.get("psid") or f"manual:{uuid.uuid4().hex[:12]}"
    name, phone, address = p["customer_name"], p["phone"], p["address"]
    customer_id = await conn.fetchval(
        "INSERT INTO customers (psid, name, phone, address) VALUES ($1,$2,$3,$4) "
        "ON CONFLICT (psid) DO UPDATE SET name=EXCLUDED.name, phone=EXCLUDED.phone, "
        "address=EXCLUDED.address RETURNING id",
        customer_psid, name, phone, address,
    )

    # --- Order + items + stock ---
    # M3-S2: UTM chi ghi khi flag bat (OFF = hanh vi cu, cot NULL); gia tri da validate o registry.
    utm = (p.get("utm") or {}) if settings.m3_utm_attribution else {}
    order_id = await conn.fetchval(
        "INSERT INTO orders (customer_id, status, total_vnd, shipping_name, shipping_phone, "
        "shipping_address, origin_channel, utm_source, utm_medium, utm_campaign, utm_content, utm_term) "
        "VALUES ($1,'new',$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id",
        customer_id, total, name, phone, address, env.channel,
        utm.get("utm_source"), utm.get("utm_medium"), utm.get("utm_campaign"),
        utm.get("utm_content"), utm.get("utm_term"),
    )
    order_item_id = await conn.fetchval(
        "INSERT INTO order_items (order_id, product_id, quantity, unit_price_vnd) VALUES ($1,$2,$3,$4) "
        "RETURNING id",
        order_id, product["id"], qty, unit_price,
    )
    # (override đã consume atomic ở bước pricing — FINDING 2)

    # --- M5 Gate E: verified-address binding + immutable snapshot TRONG CUNG transaction (CA Directive 190) ---
    # Branch-only, default OFF. Bind loi -> raise -> rollback CA don (fail-closed, khong order mo coi/snapshot le).
    await _maybe_bind_gate_e(conn, env, order_id, customer_id)

    # --- M2: reserve ATOMIC khi flag ledger bật; products.stock là MIRROR của balance (CA M2-S2-F01) ---
    # Ledger ON: reserve trên balance rồi materialize stock := available (KHÔNG delta trên giá trị stale
    #   -> Phase C an toàn, không stock âm). Ledger OFF: legacy stock -= qty (hành vi M1).
    if settings.m2_inventory_ledger:
        atype2, aref2, _ = _audit_actor(env)
        try:
            loc_reserve = await order_txn.reserve_on_create(
                conn, order_id=order_id, order_item_id=order_item_id, product_id=product["id"],
                quantity=qty, actor_type=atype2, actor_id=aref2 or "system",
                correlation_id=env.correlation_id, command_id=env.command_id,
            )
        except InventoryError as ie:
            # Bất nhất ledger↔balance (vd chưa backfill) -> rollback toàn bộ create (no partial).
            raise errors.CommandError(errors.INSUFFICIENT_STOCK, ie.message, http_status=422) from ie
        await inv_repo.materialize_stock_mirror(conn, loc_reserve, product["id"])
    else:
        await conn.execute("UPDATE products SET stock = stock - $1 WHERE id = $2", qty, product["id"])

    # --- Persist deterministic result (committed truth) ---
    result_payload = {
        "order_id": order_id, "status": "new", "sku": sku, "quantity": qty,
        "unit_price_vnd": unit_price, "total_vnd": total,
    }
    completed_at = await repo.mark_succeeded(
        conn, env.command_id, result_payload, "order", str(order_id), customer_id
    )

    # --- Outbox: Telegram admin notify (redacted; dedupe theo order_id) ---
    await repo.insert_outbox(
        conn, command_id=env.command_id, event_type=OUTBOX_EVENT_ORDER_CREATED, event_version=1,
        destination=OUTBOX_DEST_TELEGRAM_ADMIN, dedupe_key=f"order_created:{order_id}",
        payload={
            "order_id": order_id, "status": "new", "sku": sku, "quantity": qty,
            "unit_price_vnd": unit_price, "total_vnd": total,
            "customer_name": name, "phone_masked": _mask(phone),
            "correlation_id": env.correlation_id,
        },
        max_attempts=MAX_ATTEMPTS,
    )

    # --- CR-03: customer receipt DURABLE qua outbox (chỉ kênh khách có chat) ---
    # Receipt deterministic tới khách đi qua outbox (retry/dead-letter/reconcile) thay vì gửi trực
    # tiếp — nếu send lỗi sau commit vẫn không mất. dedupe order_receipt:{id} -> giao đúng-một-lần.
    if env.channel in ("messenger", "telegram_customer"):
        await repo.insert_outbox(
            conn, command_id=env.command_id, event_type="order.receipt.customer", event_version=1,
            destination=env.channel, dedupe_key=f"order_receipt:{order_id}",
            payload={"customer_ref": env.actor.id, "order_id": order_id,
                     "text": receipt_mod.order_confirmation_line(f"#{order_id}", qty, sku, total)},
            max_attempts=MAX_ATTEMPTS,
        )

    # --- Audit fail-closed BẮT BUỘC (CR-05) ---
    # M1 schema (>=015) luôn có audit_log; KHÔNG guard audit_exists nữa -> nếu thiếu/hỏng audit thì
    # record() raise -> transaction rollback (không commit business mutation mà không có audit).
    atype, aref, asid = _audit_actor(env)
    await audit_service.record(
        conn, atype, "order.create", actor_ref=aref, actor_staff_id=asid,
        entity_type="order", entity_id=str(order_id),
        after={"order_id": order_id, "sku": sku, "quantity": qty,
               "unit_price_vnd": unit_price, "total_vnd": total, "status": "new"},
        correlation_id=env.correlation_id,
    )

    log_event("order.create.succeeded", command_id=env.command_id, correlation_id=env.correlation_id,
              causation_id=env.causation_id, channel=env.channel, resource_id=order_id)
    return receipt_mod.build_order_create_receipt(
        command_id=env.command_id, correlation_id=env.correlation_id,
        outcome=receipt_mod.SUCCEEDED, result_payload=result_payload,
        committed_at=_fmt_ts(completed_at), duplicate=False,
    )


def _gate_e_scope() -> set[int]:
    """Parse canary customer-id allowlist (CSV) -> set[int]. Rong/khong hop le = khong ai trong scope."""
    out: set[int] = set()
    for tok in (settings.gate_e_canary_customer_ids or "").split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.add(int(tok))
    return out


async def _maybe_bind_gate_e(conn, env: CommandEnvelope, order_id: int, customer_id: int | None) -> None:
    """M5 Gate E (CA Directive 190): trong CUNG transaction tao don, bind verified resolution + snapshot bat
    bien khi selector ON + kill switch OFF + customer trong canary scope + customer co
    current_address_resolution_id (server-side, KHONG lay tu request body -> body khong the chon owner, §4.1).
    Bind loi -> BindingError propagate -> _run_winner vo -> rollback CA don (fail-closed, §4.4/§4.7)."""
    if not settings.enable_gate_e_order_wiring:
        return  # OFF (default): hanh vi legacy y het, KHONG snapshot, KHONG coi free-text la verified (§4.8)
    if settings.gate_e_kill_switch:
        return  # kill switch engaged: chan MOI bind moi o request boundary ke tiep (§4.9)
    if customer_id is None or customer_id not in _gate_e_scope():
        return  # ngoai canary scope -> hanh vi legacy (§4.8)
    rid = await conn.fetchval(
        "SELECT current_address_resolution_id FROM customers WHERE id=$1", customer_id)
    if rid is None:
        # Trong canary scope (selector ON, kill OFF) NHUNG khach chua co verified resolution linked
        # (server-side): fail-closed — KHONG tao don khong verified (§5.4). Ngoai scope moi la legacy
        # passthrough; da o trong scope thi enrollment = yeu cau verified address.
        raise order_binding.BindingError(
            "gate-e: khach trong canary scope nhung chua co verified resolution — tu choi (fail-closed)")
    atype, aref, _ = _audit_actor(env)
    await order_binding.bind_in_order_tx(
        conn, order_id=order_id, resolution_id=str(rid), actor=(aref or "system"),
        reason="gate-e-order-wiring", ticket=f"GATEE:{env.command_id}")


async def _reject(conn, env: CommandEnvelope, code: str, detail: str
                  ) -> receipt_mod.CommandReceipt:
    """Business reject -> command failed_terminal (persist + commit -> reject idempotent). KHONG order."""
    completed_at = await repo.mark_failed_terminal(conn, env.command_id, code, {"detail": detail})
    log_event("order.create.rejected", command_id=env.command_id, correlation_id=env.correlation_id,
              channel=env.channel, error_code=code)
    return receipt_mod.build_order_create_receipt(
        command_id=env.command_id, correlation_id=env.correlation_id,
        outcome=receipt_mod.REJECTED, result_payload=None,
        committed_at=_fmt_ts(completed_at), duplicate=False, error_code=code,
    )


# ---------------------------------------------------------------------------
# Loser path (duplicate resolution)
# ---------------------------------------------------------------------------

async def _resolve_duplicate(conn, env: CommandEnvelope) -> receipt_mod.CommandReceipt:
    existing = await repo.get_by_scope_key(
        conn, env.command_type, env.command_version, env.idempotency_scope, env.idempotency_key
    )
    if existing is None:
        # Race hiem: winner rollback dung luc nay -> coi nhu in-progress, caller retry an toan.
        return receipt_mod.build_order_create_receipt(
            command_id=env.command_id, correlation_id=env.correlation_id,
            outcome=receipt_mod.IN_PROGRESS, result_payload=None, committed_at=None, duplicate=True,
        )
    if existing["request_hash"] != env.request_hash:
        # §6.2 cung key + khac hash -> 409, audit fail-closed BẮT BUỘC (CR-05), KHONG mutation.
        async with conn.transaction():
            atype, aref, asid = _audit_actor(env)
            await audit_service.record(
                conn, atype, "command.idempotency_conflict", actor_ref=aref, actor_staff_id=asid,
                entity_type="command", entity_id=str(existing["id"]),
                reason="idempotency-key reuse voi payload khac",
                correlation_id=env.correlation_id,
            )
        log_event("command.idempotency_conflict", command_id=env.command_id,
                  correlation_id=env.correlation_id, existing_command_id=str(existing["id"]))
        raise errors.idempotency_conflict()
    return _receipt_from_row(existing, duplicate=True)


def _receipt_from_row(row, *, duplicate: bool) -> receipt_mod.CommandReceipt:
    status = row["status"]
    if status == "succeeded":
        outcome, rp = receipt_mod.SUCCEEDED, _loads(row["result_payload"])
    elif status == "failed_terminal":
        outcome, rp = receipt_mod.REJECTED, None
    else:  # accepted | processing
        outcome, rp = receipt_mod.IN_PROGRESS, None
    return receipt_mod.build_order_create_receipt(
        command_id=str(row["id"]), correlation_id=str(row["correlation_id"]),
        outcome=outcome, result_payload=rp, committed_at=_fmt_ts(row["completed_at"]),
        duplicate=duplicate, error_code=row["error_code"],
    )


def _mask(phone: str) -> str | None:
    from app.services.command.redaction import mask_phone
    return mask_phone(phone)
