"""Live adapter for WeChat Service POI/store APIs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .ports import GatewayTerminalError, PoiResult, ServicePoiGateway
from .tokens import AccessTokenProvider
from .wechat_http import WeChatHttpClient


def _poi(data: Mapping[str, Any]) -> PoiResult:
    nested = data.get("base_info")
    base: dict[str, Any] = dict(nested) if isinstance(nested, Mapping) else dict(data)
    poi_id = str(base.get("poi_id") or base.get("sosomap_poi_uid") or base.get("id") or "")
    raw_status = base.get("status", base.get("audit_status", "approved"))
    statuses = {1: "approved", 2: "under_review", 3: "rejected"}
    try:
        status = statuses.get(int(raw_status), str(raw_status))
    except (TypeError, ValueError):
        status = str(raw_status)
    return PoiResult(
        poi_id,
        str(base.get("business_name") or base.get("branch_name") or base.get("name") or poi_id),
        str(base.get("address") or ""),
        _float(base.get("latitude")),
        _float(base.get("longitude")),
        status,
        dict(data),
    )


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class LiveServicePoiGateway(ServicePoiGateway):
    def __init__(
        self,
        token_provider: AccessTokenProvider,
        *,
        base_url: str = "https://api.weixin.qq.com",
        http_client: Any = None,
        district_id: int = 0,
    ) -> None:
        self.http = WeChatHttpClient(token_provider, base_url=base_url, http_client=http_client)
        self.district_id = district_id

    async def list_pois(self, cursor: str | None = None) -> list[PoiResult]:
        offset = int(cursor or 0) if str(cursor or "0").isdigit() else 0
        results: list[PoiResult] = []
        for _ in range(200):
            response = await self.http.post_json(
                "/wxa/get_store_list", {"offset": offset, "limit": 50}
            )
            values = (
                response.get("business_list")
                or response.get("poi_list")
                or response.get("data")
                or []
            )
            page = [_poi(item) for item in values if isinstance(item, Mapping)]
            results.extend(page)
            if len(page) < 50:
                return results
            offset += len(page)
        raise GatewayTerminalError(
            "微信门店分页超过安全上限", code="upstream_pagination_limit"
        )

    async def get_poi(self, poi_id: str) -> PoiResult:
        response = await self.http.post_json("/wxa/get_store_info", {"poi_id": poi_id})
        data_value = (
            response.get("business")
            or response.get("base_info")
            or response.get("data")
            or response
        )
        data: Mapping[str, Any] = (
            data_value if isinstance(data_value, Mapping) else {"poi_id": poi_id}
        )
        return _poi(data)

    async def search_pois(self, keyword: str) -> list[PoiResult]:
        response = await self.http.post_json(
            "/wxa/search_map_poi", {"districtid": self.district_id, "keyword": keyword}
        )
        data = response.get("data") if isinstance(response.get("data"), Mapping) else response
        values = data.get("item", []) if isinstance(data, Mapping) else []
        return [
            _poi({**dict(item), "status": "map_candidate"})
            for item in values
            if isinstance(item, Mapping)
        ]

    async def create_poi(self, payload: dict[str, Any]) -> PoiResult:
        map_poi_id = payload.get("map_poi_id")
        if isinstance(map_poi_id, str) and map_poi_id.strip():
            return await self._add_store(map_poi_id.strip(), payload)
        return await self._create_map_poi(payload)

    async def _create_map_poi(self, payload: dict[str, Any]) -> PoiResult:
        body = {
            "name": payload.get("name"),
            "longitude": str(payload.get("longitude", "")),
            "latitude": str(payload.get("latitude", "")),
            "province": payload.get("province", ""),
            "city": payload.get("city", ""),
            "district": payload.get("district", ""),
            "address": payload.get("address", ""),
            "category": payload.get("category", ""),
            "telephone": payload.get("telephone", payload.get("contact_phone", "")),
            "photo": payload.get("photo", ""),
            "license": payload.get("license", ""),
            "introduct": payload.get("introduct", payload.get("description", "")),
            "districtid": payload.get("districtid", self.district_id),
        }
        missing = [key for key, value in body.items() if value in {None, ""}]
        if missing:
            raise GatewayTerminalError(
                "创建腾讯地图点位缺少字段: " + ", ".join(missing),
                code="map_poi_fields_required",
            )
        response = await self.http.post_json("/wxa/create_map_poi", body)
        data_value = response.get("data")
        data: Mapping[str, Any] = data_value if isinstance(data_value, Mapping) else response
        base_id = str(data.get("base_id") or "")
        rich_id = str(data.get("rich_id") or "")
        if not base_id:
            raise GatewayTerminalError(
                "微信未返回地图点位审核单号", code="map_poi_submission_invalid"
            )
        return _poi(
            {
                **body,
                **dict(data),
                "poi_id": f"map:{base_id}:{rich_id}",
                "status": "map_pending",
            }
        )

    async def _add_store(self, map_poi_id: str, payload: dict[str, Any]) -> PoiResult:
        pictures = payload.get("pic_list")
        if pictures is None and payload.get("photo"):
            pictures = [payload["photo"]]
        if isinstance(pictures, str):
            pic_list = pictures
        elif isinstance(pictures, list):
            pic_list = json.dumps({"list": pictures}, ensure_ascii=False)
        else:
            pic_list = ""
        body: dict[str, Any] = {
            "map_poi_id": map_poi_id,
            "pic_list": pic_list,
            "contract_phone": payload.get("contract_phone", payload.get("telephone", "")),
            "hour": payload.get("hour", ""),
            "credential": payload.get("credential", ""),
            "company_name": payload.get("company_name", ""),
            "card_id": payload.get("card_id", ""),
        }
        if payload.get("qualification_list"):
            body["qualification_list"] = payload["qualification_list"]
        if payload.get("poi_id"):
            body["poi_id"] = payload["poi_id"]
        required = ("map_poi_id", "pic_list", "contract_phone", "hour", "credential")
        missing = [key for key in required if not body.get(key)]
        if missing:
            raise GatewayTerminalError(
                "绑定微信门店缺少字段: " + ", ".join(missing),
                code="store_binding_fields_required",
            )
        response = await self.http.post_json("/wxa/add_store", body)
        data_value = response.get("data")
        data: Mapping[str, Any] = data_value if isinstance(data_value, Mapping) else response
        audit_id = str(data.get("audit_id") or "")
        if not audit_id:
            raise GatewayTerminalError(
                "微信未返回门店审核单号", code="store_submission_invalid"
            )
        return _poi(
            {
                **payload,
                **body,
                **dict(data),
                "poi_id": f"audit:{audit_id}",
                "business_name": payload.get("name", ""),
                "status": "under_review",
            }
        )

    async def update_poi(self, poi_id: str, payload: dict[str, Any]) -> PoiResult:
        body: dict[str, Any] = {"poi_id": poi_id}
        body.update(
            {
                key: value
                for key, value in payload.items()
                if key in {"map_poi_id", "contract_phone", "hour", "card_id"}
            }
        )
        if "pic_list" in payload:
            body["pic_list"] = (
                payload["pic_list"]
                if isinstance(payload["pic_list"], str)
                else json.dumps(payload["pic_list"], ensure_ascii=False)
            )
        response = await self.http.post_json("/wxa/update_store", body)
        response_data = response.get("data")
        response_mapping = dict(response_data) if isinstance(response_data, Mapping) else {}
        return _poi({**payload, "poi_id": poi_id, "status": "pending", **response_mapping})

    async def delete_poi(self, poi_id: str) -> None:
        await self.http.post_json("/wxa/del_store", {"poi_id": poi_id})

    async def get_audit_status(self, poi_id: str) -> str:
        return (await self.get_poi(poi_id)).status


__all__ = ["LiveServicePoiGateway"]
