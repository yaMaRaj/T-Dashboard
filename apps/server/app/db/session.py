"""Async SQLAlchemy engine/session and lightweight SQLite migrations."""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DATABASE_URL
from app.db.base import Base
from app.logging_setup import get_logger

log = get_logger("db")

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _migrate_sqlite(conn) -> None:
    """Add new columns on existing SQLite DBs (create_all will not alter)."""
    result = await conn.execute(text("PRAGMA table_info(cases)"))
    case_cols = {row[1] for row in result.fetchall()}
    if "mode" not in case_cols:
        await conn.execute(text("ALTER TABLE cases ADD COLUMN mode VARCHAR(20) DEFAULT 'steps'"))
    if "script" not in case_cols:
        await conn.execute(text("ALTER TABLE cases ADD COLUMN script TEXT DEFAULT ''"))

    result = await conn.execute(text("PRAGMA table_info(tasks)"))
    task_cols = {row[1] for row in result.fetchall()}
    if "capture_screenshots" not in task_cols:
        await conn.execute(
            text("ALTER TABLE tasks ADD COLUMN capture_screenshots BOOLEAN DEFAULT 0")
        )
    if "record_video" not in task_cols:
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN record_video BOOLEAN DEFAULT 0"))

    result = await conn.execute(text("PRAGMA table_info(case_results)"))
    cr_cols = {row[1] for row in result.fetchall()}
    if "artifacts" not in cr_cols:
        await conn.execute(text("ALTER TABLE case_results ADD COLUMN artifacts JSON DEFAULT '[]'"))

    result = await conn.execute(text("PRAGMA table_info(runs)"))
    run_cols = {row[1] for row in result.fetchall()}
    if "logs" not in run_cols:
        await conn.execute(text("ALTER TABLE runs ADD COLUMN logs JSON DEFAULT '[]'"))
    if "allure_results_path" not in run_cols:
        await conn.execute(
            text("ALTER TABLE runs ADD COLUMN allure_results_path VARCHAR(500) DEFAULT ''")
        )
    if "allure_report_path" not in run_cols:
        await conn.execute(
            text("ALTER TABLE runs ADD COLUMN allure_report_path VARCHAR(500) DEFAULT ''")
        )


async def init_db() -> None:
    log.info("init_db create_all + migrate")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_sqlite(conn)
    log.info("init_db done")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
