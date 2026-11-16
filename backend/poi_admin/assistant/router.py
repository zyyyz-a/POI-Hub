"""Platform-admin only chat, encrypted key settings and bounded request parsing."""

from __future__ import annotations

import json
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ValidationError

from poi_admin.core.dependencies import AuthContext, auth_error, get_auth_context, require_csrf

from .service import ChatRequest, DeepSeekAssistant, KeyRequest

assistant_router = APIRouter(prefix="/assistant", tags=["assistant"])


async def platform_admin(
    context: Annotated[AuthContext, Depends(get_auth_context)],
) -> AuthContext:
    if not context.user.is_platform_admin:
        raise auth_error("permission_denied", "助手暂仅向平台管理员开放", 403)
    return context


async def parse[T: BaseModel](request: Request, schema: type[T]) -> T:
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 64 * 1024:
            raise auth_error(
                "assistant_request_too_large", "问题内容过长，请清空对话后简短提问", 413
            )
    try:
        return schema.model_validate(json.loads(data))
    except (ValueError, ValidationError):
        # Do not reflect submitted key or chat text in Pydantic validation errors.
        raise auth_error(
            "invalid_assistant_request", "请检查填写内容，并同意发送问题至DeepSeek", 422
        ) from None


def service(request: Request) -> DeepSeekAssistant:
    return cast(DeepSeekAssistant, request.app.state.assistant)


@assistant_router.get("/status")
async def get_status(
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(platform_admin)],
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return service(request).status()


@assistant_router.put("/settings")
async def save_settings(
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(platform_admin)],
    csrf: Annotated[AuthContext, Depends(require_csrf)],
) -> dict[str, object]:
    payload = await parse(request, KeyRequest)
    service(request).save_key(payload.api_key.get_secret_value())
    response.headers["Cache-Control"] = "no-store"
    return service(request).status()


@assistant_router.post("/chat")
async def chat(
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(platform_admin)],
    csrf: Annotated[AuthContext, Depends(require_csrf)],
) -> dict[str, str]:
    payload = await parse(request, ChatRequest)
    response.headers["Cache-Control"] = "no-store"
    return await service(request).chat(context.user.id, payload)
