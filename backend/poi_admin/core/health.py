"""Health endpoints for process and database probes."""

from typing import TypedDict

from fastapi import APIRouter, HTTPException, Request, status

from .database import Database


class HealthPayload(TypedDict):
    status: str


health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get("/live", response_model=HealthPayload)
async def liveness() -> HealthPayload:
    return {"status": "ok"}


@health_router.get("/ready", response_model=HealthPayload)
async def readiness(request: Request) -> HealthPayload:
    database = getattr(request.app.state, "database", None)
    if database is None:
        database = getattr(request.app.state, "db", None)
    if not isinstance(database, Database):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database is not initialized",
        )
    try:
        await database.check_database()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database is unavailable",
        ) from exc
    return {"status": "ok"}


__all__ = ["HealthPayload", "health_router"]
