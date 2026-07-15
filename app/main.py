from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.webhook import router as webhook_router

app = FastAPI(title="Alpha3S – 3S Coffee Sales Agent")
app.include_router(webhook_router)
app.include_router(admin_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
