"""
Adapter for any self-hosted or third-party model exposed behind an
OpenAI-compatible API (e.g. vLLM, text-generation-inference, LiteLLM proxy).

This is the integration point for open-weight or self-hosted models --
point it at your own inference server's base_url. Because it reuses the
OpenAI wire format, you get one adapter instead of one per self-hosted model.
"""

from __future__ import annotations

import openai

from ..base import (
    GenerationRequest,
    GenerationResponse,
    LLMAdapter,
    Provider,
    ProviderError,
)


class GenericOpenAICompatAdapter(LLMAdapter):
    provider = Provider.GENERIC

    def __init__(
        self,
        base_url: str,
        api_key: str,
        default_model: str,
        timeout_s: float = 120.0,  # self-hosted infra can be slower
    ):
        self._client = openai.AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout_s
        )
        self.default_model = default_model

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        start = self._timer()
        model = request.model or self.default_model

        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        try:
            response = await self._client.chat.completions.create(
                model=model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                messages=messages,
            )
        except openai.RateLimitError as e:
            raise ProviderError(self.provider, str(e), retryable=True) from e
        except openai.AuthenticationError as e:
            raise ProviderError(self.provider, str(e), retryable=False) from e
        except (openai.APIStatusError, openai.APIConnectionError) as e:
            raise ProviderError(self.provider, str(e), retryable=True) from e

        choice = response.choices[0]
        usage = response.usage

        return GenerationResponse(
            content=choice.message.content or "",
            provider=self.provider,
            model=model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            latency_ms=self._elapsed_ms(start),
            request_id=request.request_id,
            raw=response,
        )
