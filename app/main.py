from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.auth_router import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.legal import router as legal_router
from app.api.webhook import router as webhook_router
from app.config import settings
from app.db_pool import close_pool
from app.security.headers import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup readiness (I-B M0.4, CA-REVIEW-M0-DEV-002 §7.7): fail startup neu RBAC ĐÃ provisioned
    # nhung permission catalog/mapping thieu (half-provisioned). Chua provisioned (dev) -> bo qua.
    try:
        from app.db_pool import get_pool
        from app.services import permission_service
        pool = await get_pool()
        async with pool.acquire() as conn:
            ready, reason = await permission_service.rbac_ready(conn)
        if not ready:
            raise RuntimeError(f"STARTUP FAIL — RBAC readiness: {reason}")
        print(f"[startup] {reason}")
    except RuntimeError:
        raise  # readiness fail -> chan startup (fail-closed, cho production strict)
    except Exception as e:  # noqa: BLE001 - loi ket noi DB tam thoi khong duoc chan startup
        print(f"[startup] RBAC readiness check bo qua (loi khong phai readiness): {e}")
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
app.include_router(legal_router)  # /privacy /terms /data-deletion (Meta App Review)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
