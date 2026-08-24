from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DashboardSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pending_audits: int = 0
    failed_operations: int = 0
    low_stock: int = 0
    unmapped_stores: int = 0
    reconciliation_differences: int = 0
    unhealthy_connections: int = 0


class DashboardResponse(BaseModel):
    summary: DashboardSummary


__all__ = ["DashboardResponse", "DashboardSummary"]
