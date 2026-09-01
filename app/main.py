from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.auth_router import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.inventory import router as inventory_router
from app.api.legal import router as legal_router
from app.api.m4_signer_access import router as m4_signer_access_router
from app.api.m4_signing import router as m4_signing_router
from app.api.m5_address_dataset import router as m5_address_dataset_router
from app.api.m5_address_resolution import router as m5_address_resolution_router
from app.api.m5_address_workflow import confirmation_router as m5_confirmation_router
from app.api.m5_address_workflow import review_router as m5_review_router
from app.api.webhook import router as webhook_router
from app.config import settings
from app.db_pool import close_pool
from app.security.headers import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup readiness FAIL-CLOSED (CA-REVIEW-M0-DEV-003 §6): quyet dinh qua startup_verdict (PURE).
    # KHONG catch-all bien loi thanh PASS. Chi skip khi CHAC CHAN pre-016 VA rbac_strict=false.
    from app.db_pool import get_pool
    from app.services import permission_service

    provisioned = ready = ready_reason = None
    error = None
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            provisioned = await permission_service.rbac_provisioned(conn)
            if provisioned:
                ready, ready_reason = await permission_service.rbac_ready(conn)
    except Exception as e:  # noqa: BLE001 - xu ly qua startup_verdict (strict -> fail)
        error = e
    ok, reason = permission_service.startup_verdict(
        provisioned, ready, ready_reason, error, settings.rbac_strict)
    if not ok:
        raise RuntimeError(f"STARTUP FAIL — {reason}")
    print(f"[startup] readiness: {reason}")
    # Pool tao lazy o lan query dau (sau fork). Dong sach luc shutdown (I-B M0.2).
    yield
    await close_pool()


app = FastAPI(title="Alpha3S – 3S Coffee Sales Agent", lifespan=lifespan)

# I-B M0.5: security headers cho API response (CA §12.2 — dashboard Next + Caddy tu set rieng)
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.dashboard_cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(inventory_router)  # I-B M2: order transitions + inventory + adjustments
app.include_router(legal_router)  # /privacy /terms /data-deletion (Meta App Review)
app.include_router(m4_signing_router)  # M4-9: dashboard-triggered signing run (control surface)
app.include_router(m4_signer_access_router)  # Directive 91: signer access request (role+window)
app.include_router(m5_address_dataset_router)  # M5 Phase 1 (Directive 104): admin dataset registry (dormant)
app.include_router(m5_address_resolution_router)  # M5 Phase 2 (Directive 108): address resolution (dormant)
app.include_router(m5_confirmation_router)  # M5 Phase 3 (Directive 112): customer confirmation (dormant)
app.include_router(m5_review_router)  # M5 Phase 3 (Directive 112): staff review queue (dormant)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
