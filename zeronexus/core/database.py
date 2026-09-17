"""ZeroNexus Database Management Layer.

Supports asynchronous SQLAlchemy 2.0 with:
- SQLite (aiosqlite) for zero-dependency standalone local persistence
- PostgreSQL (asyncpg) via DATABASE_URL for high-concurrency production deployments
- Automatic schema generation & health check probe
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict, Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event, text

from zeronexus.core.config import config
from zeronexus.core.logger import log


class Base(DeclarativeBase):
    """Base declarative class for all ZeroNexus ORM models."""
    pass


class DatabaseManager:
    """Asynchronous database lifecycle and session manager."""

    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None
        self._is_initialized: bool = False

    async def initialize(self) -> None:
        """Initializes database engine, connection pool, and ensures tables exist."""
        if self._is_initialized and self.engine is not None:
            return

        db_url = config.database.url

        # Ensure sqlite parent directory exists
        if "sqlite" in db_url:
            raw_path = db_url.split("///")[-1].split("?")[0]
            if raw_path and raw_path != ":memory:":
                db_file = Path(raw_path)
                db_file.parent.mkdir(parents=True, exist_ok=True)

        log.info(f"💾 正在建立資料庫連線池：{self._mask_db_url(db_url)}")

        connect_args: Dict[str, Any] = {}
        engine_kwargs: Dict[str, Any] = {
            "echo": config.database.echo,
            "pool_pre_ping": True,
        }

        if "sqlite" in db_url:
            # Enable foreign keys, timeout, and WAL mode in SQLite for concurrency
            connect_args = {"check_same_thread": False, "timeout": 30.0}
            engine_kwargs["connect_args"] = connect_args
        else:
            # Production connection pooling for PostgreSQL / MySQL
            engine_kwargs["pool_size"] = 20
            engine_kwargs["max_overflow"] = 10
            engine_kwargs["pool_timeout"] = 30.0
            engine_kwargs["pool_recycle"] = 1800

        self.engine = create_async_engine(db_url, **engine_kwargs)

        if "sqlite" in db_url:
            @event.listens_for(self.engine.sync_engine, "connect")
            def _set_sqlite_pragmas(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.execute("PRAGMA busy_timeout=30000")
                finally:
                    cursor.close()

        self.session_factory = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

        # Ensure all models are registered with Base.metadata
        import zeronexus.models  # noqa: F401
        _ = zeronexus.models

        # Create all declared tables if not existing and auto-migrate missing columns
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(self._auto_migrate_schema)

        self._is_initialized = True
        log.info("✅ 資料庫初始化完成，資料表綱要結構同步完畢。")

    @staticmethod
    def _auto_migrate_schema(connection) -> None:
        """Inspects existing tables and automatically adds any missing columns from ORM models."""
        import re
        from sqlalchemy import inspect
        inspector = inspect(connection)
        existing_tables = set(inspector.get_table_names())

        for table_name, table_obj in Base.metadata.tables.items():
            if table_name not in existing_tables:
                continue
            # Validate table name identifier to prevent SQL injection
            if not re.match(r"^[a-zA-Z0-9_]+$", table_name):
                continue

            existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
            for col in table_obj.columns:
                if col.name not in existing_cols:
                    # Validate column name identifier
                    if not re.match(r"^[a-zA-Z0-9_]+$", col.name):
                        continue

                    col_type = col.type.compile(dialect=connection.dialect)
                    default_clause = ""
                    if col.default is not None and hasattr(col.default, "arg"):
                        val = col.default.arg
                        if isinstance(val, str):
                            escaped_val = val.replace("'", "''")
                            default_clause = f" DEFAULT '{escaped_val}'"
                        elif isinstance(val, (int, float)):
                            default_clause = f" DEFAULT {val}"
                        elif isinstance(val, bool):
                            default_clause = f" DEFAULT {1 if val else 0}"
                    elif col.nullable:
                        default_clause = " DEFAULT NULL"
                    else:
                        default_clause = " DEFAULT 0"

                    alter_sql = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{default_clause}"
                    try:
                        connection.execute(text(alter_sql))
                        log.info(f"Database auto-migrated missing column: {table_name}.{col.name} ({col_type})")
                    except Exception as ex:
                        log.warning(f"Could not auto-migrate column {table_name}.{col.name}: {ex}")

    async def close(self) -> None:
        """Disposes of the connection pool and resets state."""
        if self.engine:
            try:
                disp_task = asyncio.create_task(self.engine.dispose())
                try:
                    await asyncio.shield(disp_task)
                except asyncio.CancelledError:
                    await disp_task
            except Exception as e:
                log.warning(f"Error disposing database engine: {e}")
            self.engine = None
            self.session_factory = None
            self._is_initialized = False
            log.info("Database connection pool disposed.")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Async context manager providing a safe transactional database session with leak prevention."""
        if not self.session_factory:
            raise RuntimeError("DatabaseManager is not initialized. Call await db.initialize() first.")

        session: AsyncSession = self.session_factory()
        try:
            yield session
            if session.in_nested_transaction():
                log.warning("Uncommitted nested savepoint detected upon session exit; rolling back savepoint.")
                await session.rollback()
            if session.in_transaction():
                await session.commit()
        except BaseException:
            if session.is_active:
                async def _safe_rollback() -> None:
                    try:
                        await session.rollback()
                    except Exception as rb_err:
                        log.warning(f"Failed to rollback database session: {rb_err}")

                try:
                    rb_task = asyncio.create_task(_safe_rollback())
                    try:
                        await asyncio.shield(rb_task)
                    except asyncio.CancelledError:
                        await asyncio.shield(rb_task)
                except Exception as rb_outer_err:
                    log.warning(f"Error shielding database rollback: {rb_outer_err}")
                except asyncio.CancelledError:
                    pass
            raise
        finally:
            async def _safe_close() -> None:
                try:
                    await session.close()
                except Exception as cl_err:
                    log.warning(f"Failed to close database session: {cl_err}")

            try:
                cl_task = asyncio.create_task(_safe_close())
                try:
                    await asyncio.shield(cl_task)
                except asyncio.CancelledError:
                    await asyncio.shield(cl_task)
            except Exception as cl_outer_err:
                log.warning(f"Error shielding database session close: {cl_outer_err}")
            except asyncio.CancelledError:
                pass

    # Alias for compatibility
    async_session = session

    @asynccontextmanager
    async def begin(self) -> AsyncGenerator[AsyncSession, None]:
        """Async context manager providing a transactional database session (alias for auto commit/rollback session)."""
        async with self.session() as session:
            yield session

    @asynccontextmanager
    async def savepoint(self, session: AsyncSession) -> AsyncGenerator[AsyncSession, None]:
        """Async context manager providing nested savepoint transaction isolation.

        Ensures that operations within the block can be rolled back to the savepoint
        without aborting the surrounding outer transaction.
        """
        async with session.begin_nested():
            yield session

    async def health_check(self) -> Dict[str, Any]:
        """Runs a diagnostic ping against the database."""
        if not self.engine or not self._is_initialized:
            return {
                "status": "RED",
                "healthy": False,
                "latency_ms": -1,
                "error": "Database not initialized",
            }

        start_time = time.perf_counter()
        try:
            async with self.session() as s:
                await s.execute(text("SELECT 1"))
            latency = (time.perf_counter() - start_time) * 1000
            return {
                "status": "GREEN",
                "healthy": True,
                "latency_ms": round(latency, 2),
                "driver": self.engine.dialect.name,
                "url": self._mask_db_url(config.database.url),
            }
        except Exception as e:
            from zeronexus.security.sanitizer import redact_secrets
            return {
                "status": "RED",
                "healthy": False,
                "latency_ms": round((time.perf_counter() - start_time) * 1000, 2),
                "error": redact_secrets(str(e)),
            }

    @staticmethod
    def _mask_db_url(url: str) -> str:
        """Masks database passwords in connection URLs."""
        if "@" in url and "://" in url:
            prefix, rest = url.split("://", 1)
            auth, host_part = rest.split("@", 1)
            if ":" in auth:
                user, pwd = auth.split(":", 1)
                from zeronexus.core.config import mask_secret
                masked_pwd = mask_secret(pwd, prefix_len=4, suffix_len=4)
                return f"{prefix}://{user}:{masked_pwd}@{host_part}"
        return url



# Singleton database instance
db = DatabaseManager()
database = db
