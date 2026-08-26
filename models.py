"""SQLAlchemy 2.0 async models for moderation audit logging and the
human-review queue. Every moderation decision -- allow -- gets a
row here; this is what you show a payment processor, regulator, or your
own investigators when something needs explaining."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ModerationEvent(Base):
    """Immutable append-only record of every moderation decision. Never
    updated or deleted in application code -- if you need retention limits,
    handle that via a scheduled job with its own audit trail, not ad hoc
    deletes."""

    __tablename__ = "moderation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(32))  # "pre_generate" | "post_generate"
    allowed: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text, default="")
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HumanReviewItem(Base):
    """Queue of content flagged for human review. `resolve_review` in the
    repository is the only place status changes after creation."""

    __tablename__ = "human_review_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True, unique=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|approved|rejected
    reviewer_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
