"""Local durable operation worker process."""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
from uuid import uuid4

import httpx

from .core.config import Settings, get_settings
from .core.database import Database, create_database
from .operations.worker import OperationWorker


async def _run_slot(
    database: Database,
    settings: Settings,
    *,
    slot: int,
    poll_seconds: float,
    burst_size: int,
    http_client: httpx.AsyncClient,
) -> None:
    instance = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:12]}:{slot}"[-100:]
    prefer_webhook = slot % 2 == 0
    while True:
        processed = 0
        for _ in range(burst_size):
            async with database.session_factory() as session:
                worker = OperationWorker(
                    session,
                    worker_id=instance,
                    settings=settings,
                    session_factory=database.session_factory,
                    prefer_webhook=prefer_webhook,
                    http_client=http_client,
                )
                await worker.run_once()
                if not getattr(worker, "processed_last_cycle", False):
                    break
            processed += 1
            prefer_webhook = not prefer_webhook
        if processed == 0:
            await asyncio.sleep(max(0.1, poll_seconds))


async def run(
    poll_seconds: float,
    *,
    concurrency: int | None = None,
    burst_size: int | None = None,
) -> None:
    settings = get_settings()
    database = create_database(settings)
    resolved_concurrency = concurrency or int(getattr(settings, "worker_concurrency", 1))
    resolved_burst_size = burst_size or int(getattr(settings, "worker_burst_size", 100))
    database_url = str(getattr(settings, "database_url", ""))
    if database_url.casefold().startswith("sqlite") and resolved_concurrency != 1:
        raise ValueError("SQLite deployments require exactly one worker slot")
    try:
        limits = httpx.Limits(
            max_connections=int(getattr(settings, "wechat_http_max_connections", 100)),
            max_keepalive_connections=int(
                getattr(settings, "wechat_http_max_keepalive_connections", 20)
            ),
        )
        async with httpx.AsyncClient(timeout=15.0, limits=limits) as http_client:
            await asyncio.gather(
                *(
                    _run_slot(
                        database,
                        settings,
                        slot=slot,
                        poll_seconds=poll_seconds,
                        burst_size=max(1, resolved_burst_size),
                        http_client=http_client,
                    )
                    for slot in range(max(1, resolved_concurrency))
                )
            )
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--burst-size", type=int, default=None)
    args = parser.parse_args()
    try:
        asyncio.run(
            run(
                args.poll_seconds,
                concurrency=args.concurrency,
                burst_size=args.burst_size,
            )
        )
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
