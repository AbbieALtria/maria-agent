"""FastAPI entrypoint: `uvicorn app.main:app`."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.crm.router import api_router
from app.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
settings.check_production_secrets()
log = logging.getLogger("maria.api")

app = FastAPI(title="Maria Outbound API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


log.info("api started", extra={"env": settings.env})
