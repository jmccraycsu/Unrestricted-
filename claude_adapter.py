"""Adapter for Anthropic's Claude models."""

from __future__ import annotations

import anthropic

from ..base import (
    GenerationRequest,
    GenerationResponse,
    LLMAdapter,
    Provider,
    ProviderError,
)


class ClaudeAdapter(LLMAdapter):
    provider = Provider.CLAUDE
    default_model = "claude-sonnet-4-6"

    def __init__(self, api_key: str, timeout_s: float = 60.0):
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_s)

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        start = self._timer()
        model = request.model or self.default_model

        try:
            response = await self._client.messages.create(
                model=model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system=request.system_prompt or anthropic.NOT_GIVEN,
                messages=[{"role": "user", "content": request.prompt}],
            )
        except anthropic.RateLimitError as e:
            raise ProviderError(self.provider, str(e), retryable=True) from e
        except anthropic.AuthenticationError as e:
            raise ProviderError(self.provider, str(e), retryable=False) from e
        except anthropic.APIStatusError as e:
            # 5xx = retryable, 4xx (other than above) = not
            retryable = e.status_code >= 500
            raise ProviderError(self.provider, str(e), retryable=retryable) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError(self.provider, str(e), retryable=True) from e

        text = "".join(
            block.text for block in response.content if block.type == "text"
        )

        return GenerationResponse(
            content=text,
            provider=self.provider,
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=self._elapsed_ms(start),
            request_id=request.request_id,
            raw=response,
        )
