from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.auth_router import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.webhook import router as webhook_router
from app.config import settings

app = FastAPI(title="Alpha3S – 3S Coffee Sales Agent")

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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
