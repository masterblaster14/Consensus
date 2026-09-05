"""Async engine and session factory."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=20
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Commit on success, roll back on error."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency.

    FastAPI runs a yield-dependency's exit code after the response has been sent,
    so committing here would race a client's next request. `CommittingRoute`
    (used for every API router, see app.main) commits the request session right
    after the endpoint returns, before the response is sent. The commit below is
    only a safety net; rollback on error is the important part.
    """
    async with get_session_factory()() as session:
        request.state.db_session = session
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        except BaseException:
            await session.rollback()
            raise


class CommittingRoute(APIRoute):
    """Commit the request-scoped session before the response goes out."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            response = await original(request)
            session: AsyncSession | None = getattr(request.state, "db_session", None)
            if session is not None and session.in_transaction():
                await session.commit()
            return response

        return handler


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
