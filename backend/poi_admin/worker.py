"""Local durable operation worker process."""

from __future__ import annotations

import argparse
import asyncio

from .core.config import get_settings
from .core.database import create_database
from .operations.worker import OperationWorker


async def run(poll_seconds: float) -> None:
    database = create_database(get_settings())
    try:
        while True:
            async with database.session_factory() as session:
                worker = OperationWorker(session, settings=get_settings())
                await worker.run_once()
            await asyncio.sleep(max(0.1, poll_seconds))
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.poll_seconds))
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
