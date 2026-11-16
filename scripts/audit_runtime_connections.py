"""Print non-secret runtime integration status for deployment audits."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from poi_admin.core.config import get_settings
from poi_admin.core.database import create_database


QUERIES = (
    ("TENANTS", "select id, name, status from tenants order by created_at"),
    (
        "STORES",
        "select code, name, status, city, district, latitude, longitude "
        "from stores order by created_at",
    ),
    (
        "CONNECTIONS",
        "select capability, mode, status, app_id, merchant_id, "
        "case when encrypted_secrets is null then 'NO_SECRETS' else 'HAS_SECRETS' end, "
        "last_error from wechat_connections order by created_at",
    ),
    (
        "PROGRAMS",
        "select name, app_id, owner_subject, status, callback_configured, connection_id "
        "from platform_mini_programs order by created_at",
    ),
    (
        "BINDINGS",
        "select store_code, status, discoverable, tencent_poi_id, entry_path "
        "from mini_program_store_bindings order by created_at",
    ),
    (
        "PAYMENTS",
        "select mode, status, verified, mchid, sp_mchid, sub_mchid, connection_id "
        "from merchant_payment_profiles order by created_at",
    ),
)


async def main() -> None:
    database = create_database(get_settings())
    try:
        async with database.session_factory() as session:
            for label, query in QUERIES:
                print(f"==={label}===")
                rows = (await session.execute(text(query))).all()
                if not rows:
                    print("EMPTY")
                for row in rows:
                    print("|".join("" if value is None else str(value) for value in row))
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
