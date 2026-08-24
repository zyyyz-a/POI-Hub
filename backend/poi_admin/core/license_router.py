"""Authenticated license status for local appliance operators."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from .dependencies import AuthContext, get_auth_context
from .licensing import LicenseState

license_router = APIRouter(prefix="/license", tags=["license"])


@license_router.get("/status")
async def license_status(
    request: Request,
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    del context
    state: LicenseState = request.app.state.license
    claims = state.claims
    return {
        "mode": state.mode,
        "status": state.current_status(),
        "license_id": claims.license_id if claims else None,
        "customer_id": claims.customer_id if claims else None,
        "customer_name": claims.customer_name if claims else None,
        "expires_at": claims.expires_at if claims else None,
        "max_stores": claims.max_stores if claims else None,
        "features": claims.features if claims else [],
    }


__all__ = ["license_router"]
