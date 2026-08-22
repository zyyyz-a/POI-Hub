"""HTTP contracts for canonical stores and POI mapping workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _strip_required(value: object) -> object:
    if value is None:
        return value
    if not isinstance(value, str):
        return value
    return value.strip()


class StoreCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_phone: str | None = Field(default=None, max_length=32)
    province: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    address: str = Field(min_length=1, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    status: str = Field(default="active", pattern="^(active|inactive)$")

    @field_validator("code", "name", "address", mode="before")
    @classmethod
    def strip_required_fields(cls, value: object) -> object:
        return _strip_required(value)


class StoreUpdateRequest(BaseModel):
    version: int = Field(ge=1)
    code: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_phone: str | None = Field(default=None, max_length=32)
    province: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")

    @field_validator("code", "name", "address", mode="before")
    @classmethod
    def strip_required_fields(cls, value: object) -> object:
        return _strip_required(value)

    @model_validator(mode="before")
    @classmethod
    def reject_null_required_fields(cls, value: object) -> object:
        if isinstance(value, dict):
            for field in ("code", "name", "address"):
                if field in value and value[field] is None:
                    raise ValueError(f"{field} cannot be null")
        return value


class StoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    code: str
    name: str
    contact_name: str | None
    contact_phone_masked: str | None
    province: str | None
    city: str | None
    district: str | None
    address: str
    latitude: float | None
    longitude: float | None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class PoiResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    connection_id: str
    external_poi_id: str
    name: str
    address: str
    latitude: float | None
    longitude: float | None
    remote_status: str
    category: str | None
    qualification_summary: dict[str, Any] | None
    raw_checksum: str
    last_synced_at: datetime


class PoiSyncRequest(BaseModel):
    connection_id: str
    idempotency_key: str = Field(min_length=1, max_length=255)


class PoiSyncAcceptedResponse(BaseModel):
    operation_id: str
    status: str


class CandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    connection_id: str
    store_id: str
    service_poi_id: str
    total_score: float
    name_score: float
    address_score: float
    distance_score: float
    distance_meters: float | None
    evidence: dict[str, Any]
    generated_at: datetime
    dismissed_at: datetime | None


class MappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    connection_id: str
    store_id: str
    service_poi_id: str
    state: str
    match_score: float | None
    match_evidence: dict[str, Any]
    confirmed_by_user_id: str
    confirmed_at: datetime
    unbound_by_user_id: str | None
    unbound_at: datetime | None


class ManualMappingRequest(BaseModel):
    store_id: str
    service_poi_id: str


__all__ = [
    "CandidateResponse",
    "ManualMappingRequest",
    "MappingResponse",
    "PoiResponse",
    "PoiSyncAcceptedResponse",
    "PoiSyncRequest",
    "StoreCreateRequest",
    "StoreResponse",
    "StoreUpdateRequest",
]
