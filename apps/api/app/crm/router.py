"""All CRM routes under /api/v1 (JWT + roles)."""

from fastapi import APIRouter

from app.crm.routers import (
    auth,
    calls,
    campaigns,
    clients,
    dnc,
    leads,
    sip_trunks,
    teams,
    users,
)

api_router = APIRouter(prefix="/api/v1")
for r in (auth, users, clients, campaigns, calls, leads, dnc, teams, sip_trunks):
    api_router.include_router(r.router)
