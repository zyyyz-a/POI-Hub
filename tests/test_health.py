import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_safe_request_id_is_preserved(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/health/live", headers={"X-Request-ID": "commercial-batch-42"}
    )

    assert response.headers["X-Request-ID"] == "commercial-batch-42"


@pytest.mark.asyncio
async def test_readiness_checks_database_and_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
