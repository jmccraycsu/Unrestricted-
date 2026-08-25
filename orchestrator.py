"""
LLMOrchestrator ties adapters, fallback chains, retries, and moderation
hooks together. This is the only object the rest of the app talks to --
it never exposes provider-specific details upward.

Moderation is enforced here, not left to callers to remember: every
generate() call runs pre-hooks before touching a provider and post-hooks
before returning content. A hook raising ModerationBlocked always wins,
even if a caller forgets to check anything downstream.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from .base import (
    GenerationRequest,
    GenerationResponse,
    LLMAdapter,
    ModerationBlocked,
    Provider,
    ProviderError,
)

logger = logging.getLogger("llm_orchestrator")

# Hooks are plain async callables so moderation logic lives in its own
# module/service and can be swapped or unit tested independently.
PreGenerateHook = Callable[[GenerationRequest], Awaitable[None]]
PostGenerateHook = Callable[[GenerationRequest, GenerationResponse], Awaitable[None]]


class LLMOrchestrator:
    def __init__(
        self,
        adapters: dict[Provider, LLMAdapter],
        default_provider: Provider,
        fallback_chain: Optional[list[Provider]] = None,
        max_retries_per_provider: int = 2,
        retry_backoff_s: float = 1.5,
    ):
        self._adapters = adapters
        self._default_provider = default_provider
        # order matters: tried in sequence if the primary provider fails
        self._fallback_chain = fallback_chain or []
        self._max_retries = max_retries_per_provider
        self._retry_backoff_s = retry_backoff_s

        self._pre_hooks: list[PreGenerateHook] = []
        self._post_hooks: list[PostGenerateHook] = []

    def register_pre_generate_hook(self, hook: PreGenerateHook) -> None:
        """e.g. input moderation classifier -- runs before any provider call."""
        self._pre_hooks.append(hook)

    def register_post_generate_hook(self, hook: PostGenerateHook) -> None:
        """e.g. output moderation classifier -- runs before content is returned."""
        self._post_hooks.append(hook)

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        # 1. Pre-generation moderation. Any hook may raise ModerationBlocked;
        #    we do not catch it -- it must propagate to the caller/API layer
        #    so the request is rejected and logged, not silently retried.
        for hook in self._pre_hooks:
            await hook(request)

        # 2. Build the provider attempt order: requested provider first
        #    (if given), then the default, then the fallback chain --
        #    de-duplicated, preserving order.
        order = self._build_attempt_order(request.provider)

        last_error: Optional[Exception] = None
        for provider in order:
            adapter = self._adapters.get(provider)
            if adapter is None:
                continue
            try:
                response = await self._call_with_retries(adapter, request)
                break
            except ProviderError as e:
                logger.warning(
                    "provider_failed",
                    extra={
                        "provider": provider.value,
                        "retryable": e.retryable,
                        "request_id": request.request_id,
                    },
                )
                last_error = e
                continue
        else:
            # every provider in the chain failed
            raise last_error or ProviderError(
                self._default_provider, "no adapters available", retryable=False
            )

        # 3. Post-generation moderation. Same rule: a block must propagate,
        #    never get swallowed by a broad except somewhere upstream.
        for hook in self._post_hooks:
            await hook(request, response)

        return response

    def _build_attempt_order(self, requested: Optional[Provider]) -> list[Provider]:
        order: list[Provider] = []
        if requested:
            order.append(requested)
        if self._default_provider not in order:
            order.append(self._default_provider)
        for p in self._fallback_chain:
            if p not in order:
                order.append(p)
        return order

    async def _call_with_retries(
        self, adapter: LLMAdapter, request: GenerationRequest
    ) -> GenerationResponse:
        attempt = 0
        while True:
            try:
                return await adapter.generate(request)
            except ProviderError as e:
                attempt += 1
                if not e.retryable or attempt > self._max_retries:
                    raise
                backoff = self._retry_backoff_s * (2 ** (attempt - 1))
                logger.info(
                    "retrying_provider_call",
                    extra={
                        "provider": adapter.provider.value,
                        "attempt": attempt,
                        "backoff_s": backoff,
                    },
                )
                await asyncio.sleep(backoff)
