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


class PoiCreateRequest(BaseModel):
    connection_id: str
    idempotency_key: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=160)
    address: str = Field(min_length=1, max_length=500)
    province: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    district: str | None = Field(default=None, max_length=80)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    category: str | None = Field(default=None, max_length=160)
    telephone: str | None = Field(default=None, max_length=64)
    photo: str | None = Field(default=None, max_length=1000)
    license: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=1000)
    districtid: int | None = Field(default=None, gt=0)
    map_poi_id: str | None = Field(default=None, max_length=160)
    pic_list: list[str] | None = Field(default=None, min_length=1, max_length=20)
    contract_phone: str | None = Field(default=None, max_length=64)
    hour: str | None = Field(default=None, max_length=160)
    credential: str | None = Field(default=None, max_length=160)
    company_name: str | None = Field(default=None, max_length=200)
    card_id: str | None = Field(default=None, max_length=160)
    qualification_list: list[str] | None = Field(default=None, max_length=5)

    @field_validator("name", "address", mode="before")
    @classmethod
    def strip_required_fields(cls, value: object) -> object:
        return _strip_required(value)

    @model_validator(mode="after")
    def validate_submission_stage(self) -> PoiCreateRequest:
        if self.map_poi_id:
            required: dict[str, object] = {
                "pic_list": self.pic_list,
                "contract_phone": self.contract_phone,
                "hour": self.hour,
                "credential": self.credential,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError("绑定微信门店缺少字段: " + ", ".join(missing))
            return self

        required = {
            "province": self.province,
            "city": self.city,
            "district": self.district,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "category": self.category,
            "telephone": self.telephone,
            "photo": self.photo,
            "license": self.license,
            "description": self.description,
            "districtid": self.districtid,
        }
        missing = [name for name, value in required.items() if value in (None, "")]
        if missing:
            raise ValueError("创建腾讯地图点位缺少字段: " + ", ".join(missing))
        return self


class PoiUpdateRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    address: str | None = Field(default=None, min_length=1, max_length=500)
    category: str | None = Field(default=None, max_length=160)
    telephone: str | None = Field(default=None, max_length=64)
    photo: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name", "address", mode="before")
    @classmethod
    def strip_optional_fields(cls, value: object) -> object:
        return _strip_required(value)


class PoiActionRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)


class PoiOperationAcceptedResponse(BaseModel):
    operation_id: str
    status: str


class RemotePoiResponse(BaseModel):
    poi_id: str
    name: str
    address: str
    latitude: float | None = None
    longitude: float | None = None
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
    "PoiActionRequest",
    "PoiCreateRequest",
    "PoiOperationAcceptedResponse",
    "PoiResponse",
    "PoiSyncAcceptedResponse",
    "PoiSyncRequest",
    "PoiUpdateRequest",
    "RemotePoiResponse",
    "StoreCreateRequest",
    "StoreResponse",
    "StoreUpdateRequest",
]
