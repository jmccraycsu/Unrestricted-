"""Adapter for OpenAI's GPT models."""

from __future__ import annotations

import openai

from ..base import (
    GenerationRequest,
    GenerationResponse,
    LLMAdapter,
    Provider,
    ProviderError,
)


class OpenAIAdapter(LLMAdapter):
    provider = Provider.OPENAI
    default_model = "gpt-4o"

    def __init__(self, api_key: str, timeout_s: float = 60.0):
        self._client = openai.AsyncOpenAI(api_key=api_key, timeout=timeout_s)

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
        except openai.APIStatusError as e:
            retryable = e.status_code >= 500
            raise ProviderError(self.provider, str(e), retryable=retryable) from e
        except openai.APIConnectionError as e:
            raise ProviderError(self.provider, str(e), retryable=True) from e

        choice = response.choices[0]

        return GenerationResponse(
            content=choice.message.content or "",
            provider=self.provider,
            model=model,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            latency_ms=self._elapsed_ms(start),
            request_id=request.request_id,
            raw=response,
        )
