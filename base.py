"""
Core interfaces for the LLM orchestrator.

Every provider (Claude, OpenAI, self-hosted models) implements the same
LLMAdapter interface, so the orchestrator never needs to know provider-specific
details. Adding a new provider means writing one adapter class, not touching
the orchestrator or the API layer.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Provider(str, Enum):
    CLAUDE = "claude"
    OPENAI = "openai"
    GENERIC = "generic"  # any OpenAI-compatible self-hosted endpoint


@dataclass
class GenerationRequest:
    prompt: str
    system_prompt: Optional[str] = None
    provider: Optional[Provider] = None      # None = let orchestrator pick
    model: Optional[str] = None              # None = adapter's default
    max_tokens: int = 1024
    temperature: float = 0.7
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationResponse:
    content: str
    provider: Provider
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    request_id: Optional[str] = None
    raw: Any = None  # original provider response, for debugging/audit


class ProviderError(Exception):
    """Raised when a provider call fails. Caught by the orchestrator to
    decide whether to retry, fall back, or surface the error."""

    def __init__(self, provider: Provider, message: str, retryable: bool = True):
        self.provider = provider
        self.retryable = retryable
        super().__init__(f"[{provider.value}] {message}")


class ModerationBlocked(Exception):
    """Raised by a moderation hook to stop generation. Never silently
    swallowed — this must propagate to the caller and the audit log."""

    def __init__(self, stage: str, reason: str):
        self.stage = stage  # "pre_generate" or "post_generate"
        self.reason = reason
        super().__init__(f"Blocked at {stage}: {reason}")


class LLMAdapter(ABC):
    """Base class every provider adapter implements."""

    provider: Provider
    default_model: str

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Call the provider and return a normalized response.

        Implementations must:
        - measure latency
        - map provider-specific errors to ProviderError with retryable set
          correctly (e.g. rate limits = retryable, auth errors = not)
        - never log raw prompt/response content at INFO level (PII/content risk)
        """
        raise NotImplementedError

    def _timer(self) -> float:
        return time.perf_counter()

    def _elapsed_ms(self, start: float) -> float:
        return round((time.perf_counter() - start) * 1000, 2)
