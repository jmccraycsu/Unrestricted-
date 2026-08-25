"""Run once at deployment time (or via the `migrate` service in
docker-compose) to create tables from ORM metadata. Switch to Alembic
once you have real data you can't afford to lose to a schema mistake."""

from __future__ import annotations

import asyncio

from .audit.db import create_engine, init_models
from .config import get_settings


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    await init_models(engine)
    print("Database tables created.")


if __name__ == "__main__":
    asyncio.run(main())
