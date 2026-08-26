"""
Example moderation hooks. These are illustrative wiring -- the actual
classifiers (Hive, Sightengine, a fine-tuned model, etc.) are a separate
service; this module shows the *contract* the orchestrator expects and
where decisions get logged for audit.

Swap `check_text_input` / `check_text_output` for real calls to your
moderation provider(s).
"""

from __future__ import annotations

import logging
from typing import Protocol

from .base import GenerationRequest, GenerationResponse

logger = logging.getLogger("moderation")


class ModerationClient(Protocol):
    async def check_text_input(self, text: str, user_id: str | None) -> "ModerationResult":
        ...

    async def check_text_output(self, text: str, user_id: str | None) -> "ModerationResult":
        ...


class ModerationResult:
    def __init__(self, allowed: bool, reason: str = "", needs_human_review: bool = False):
        self.allowed = allowed
        self.reason = reason
        self.needs_human_review = needs_human_review


def build_pre_generate_hook(moderation_client: ModerationClient, audit_log):
    async def pre_generate_hook(request: GenerationRequest) -> None:
        result = await moderation_client.check_text_input(
            request.prompt, request.user_id
        )
        await audit_log.record_moderation_event(
            stage="pre_generate",
            request_id=request.request_id,
            user_id=request.user_id,
            allowed=result.allowed,
            reason=result.reason,

    return pre_generate_hook


def build_post_generate_hook(moderation_client: ModerationClient, audit_log):
    async def post_generate_hook(
        request: GenerationRequest, response: GenerationResponse
    ) -> None:
        result = await moderation_client.check_text_output(
            response.content, request.user_id
        )
        await audit_log.record_moderation_event(
            stage="post_generate",
            request_id=request.request_id,
            user_id=request.user_id,
            allowed=result.allowed,
            reason=result.reason,
            needs_human_review=result.needs_human_review,
        )  
        if result.needs_human_review:
            await audit_log.enqueue_human_review(request.request_id)

    return post_generate_hook
