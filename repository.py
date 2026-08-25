"""Implements the `audit_log` duck-typed interface that
moderation_hooks.py's build_pre_generate_hook/build_post_generate_hook
expect: record_moderation_event(...) and enqueue_human_review(...)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import HumanReviewItem, ModerationEvent


class AuditLogRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def record_moderation_event(
        self,
        *,
        stage: str,
        request_id: str,
        user_id: str | None,
        allowed: bool,
        reason: str = "",
        needs_human_review: bool = False,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                ModerationEvent(
                    request_id=request_id,
                    user_id=user_id,
                    stage=stage,
                    allowed=allowed,
                    reason=reason,
                    needs_human_review=needs_human_review,
                )
            )
            await session.commit()

    async def enqueue_human_review(self, request_id: str) -> None:
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(HumanReviewItem).where(HumanReviewItem.request_id == request_id)
            )
            if existing is not None:
                return
            session.add(HumanReviewItem(request_id=request_id, status="pending"))
            await session.commit()

    async def resolve_review(self, request_id: str, reviewer_id: str, approved: bool) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(HumanReviewItem)
                .where(HumanReviewItem.request_id == request_id)
                .values(
                    status="approved" if approved else "rejected",
                    reviewer_id=reviewer_id,
                    resolved_at=dt.datetime.now(dt.timezone.utc),
                )
            )
            await session.commit()

    async def list_pending_reviews(self, limit: int = 50) -> list[HumanReviewItem]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(HumanReviewItem)
                .where(HumanReviewItem.status == "pending")
                .order_by(HumanReviewItem.created_at.asc())
                .limit(limit)
            )
            return list(result.all())
