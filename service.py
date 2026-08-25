"""
Concrete moderation policy, backed by Hive (text) and Sightengine (image).

Two design decisions worth flagging explicitly:

1. This platform's product IS adult sexual content for verified adult
   users -- so general "sexual" class severity is deliberately NOT used
   as a block signal below. Moderation here targets illegal/harmful
   categories, not explicitness itself. What counts as in-policy within
   the adult category (e.g. how non-consent-themed fiction is handled)
   is a real content-policy decision that needs legal/trust-and-safety
   sign-off -- this module gives you the hook, not the policy.

2. Fail CLOSED. If no moderation provider is configured, or a provider
   call errors, content is blocked rather than allowed through. A
   moderation false-negative is a materially worse outcome than a
   false-positive that annoys a user for a retry.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from ..moderation_hooks import ModerationResult

if TYPE_CHECKING:
    from .hive_client import HiveTextModerationClient
    from .sightengine_client import SightengineImageModerationClient

logger = logging.getLogger("moderation.service")

# Any positive signal on these classes is an automatic, non-negotiable
# block -- never a review-queue item, never subject to a numeric
# threshold, and never something to relax based on false-positive rate.
# Confirm the exact class name(s) Hive assigns for this category on your
# project dashboard before deploying.
HARD_BLOCK_TEXT_CLASSES = ("child_exploitation",)

# Standard severity classes this platform actually thresholds on.
# "sexual" is intentionally excluded -- see module docstring.
THRESHOLD_TEXT_CLASSES = ("hate", "violence", "bullying", "self_harm")
REVIEW_THRESHOLD = 1   # Hive severity 1+: send to human review queue
BLOCK_THRESHOLD = 2    # Hive severity 2+: auto-block


class ModerationService:
    def __init__(
        self,
        text_client: Optional["HiveTextModerationClient"] = None,
        image_client: Optional["SightengineImageModerationClient"] = None,
    ):
        self._text_client = text_client
        self._image_client = image_client

    # --- interface expected by moderation_hooks.py's ModerationClient Protocol ---

    async def check_text_input(self, text: str, user_id: str | None) -> ModerationResult:
        return await self._check_text(text, user_id)

    async def check_text_output(self, text: str, user_id: str | None) -> ModerationResult:
        return await self._check_text(text, user_id)

    # --- internals ---

    async def _check_text(self, text: str, user_id: str | None) -> ModerationResult:
        if self._text_client is None:
            logger.error("moderation_not_configured", extra={"user_id": user_id})
            return ModerationResult(allowed=False, reason="moderation not configured")

        try:
            raw = await self._text_client.moderate_text(text)
        except Exception:
            logger.exception("moderation_provider_error", extra={"user_id": user_id})
            return ModerationResult(allowed=False, reason="moderation provider unavailable")

        scores = self._text_client.extract_class_scores(raw)

        for hard_block_class in HARD_BLOCK_TEXT_CLASSES:
            if scores.get(hard_block_class, 0) > 0:
                logger.critical(
                    "hard_block_triggered",
                    extra={"user_id": user_id, "class": hard_block_class},
                )
                # In production this must ALSO trigger your legal/compliance
                # reporting workflow -- in the US, reporting apparent CSAM to
                # NCMEC's CyberTipline is a legal obligation (18 U.S.C. S 2258A),
                # not an optional integration. Route this through counsel-
                # reviewed process, not an improvised call from here.
                return ModerationResult(allowed=False, reason="policy violation")

        relevant = {k: v for k, v in scores.items() if k in THRESHOLD_TEXT_CLASSES}
        max_score = max(relevant.values(), default=0)

        if max_score >= BLOCK_THRESHOLD:
            return ModerationResult(allowed=False, reason="content policy threshold exceeded")
        if max_score >= REVIEW_THRESHOLD:
            return ModerationResult(allowed=True, needs_human_review=True, reason="flagged for review")
        return ModerationResult(allowed=True)

    async def check_image(self, image_url: str) -> ModerationResult:
        """Extension point for an image/video generation pipeline -- not
        wired into the text orchestrator's hooks; attach to that
        pipeline's own pre/post hooks the same way moderation_hooks.py
        wires this service into LLMOrchestrator.

        Again: general nudity/offensiveness scoring is the wrong tool for
        CSAM detection. See module docstring and sightengine_client.py.
        """
        if self._image_client is None:
            return ModerationResult(allowed=False, reason="moderation not configured")
        try:
            raw = await self._image_client.moderate_image_url(image_url)
        except Exception:
            logger.exception("moderation_provider_error")
            return ModerationResult(allowed=False, reason="moderation provider unavailable")

        # Verify exact field names against your Sightengine model version --
        # these are illustrative, not a stable contract.
        offensive_prob = raw.get("offensive", {}).get("prob", 0)
        gore_prob = raw.get("gore", {}).get("prob", 0)
        if offensive_prob >= 0.9 or gore_prob >= 0.9:
            return ModerationResult(allowed=False, reason="content policy threshold exceeded")
        return ModerationResult(allowed=True)
