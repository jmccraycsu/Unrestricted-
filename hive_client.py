"""
Hive AI text moderation client (https://docs.thehive.ai/docs/text-moderation-api).

Sync endpoint: POST https://api.thehive.ai/api/v2/task/sync
Auth: `Authorization: Token {api_key}` header, text sent as `text_data` form field.

Hive's multilevel classes score 0 (benign) to 3 (most severe) per class head
(sexual, hate, violence, bullying, etc.), configured per-project in the Hive
dashboard. Verify your project's exact class set before wiring thresholds --
class names and severity mappings are configured there, not fixed globally.
"""

from __future__ import annotations

import httpx


class HiveTextModerationClient:
    ENDPOINT = "https://api.thehive.ai/api/v2/task/sync"

    def __init__(self, api_key: str, timeout_s: float = 10.0):
        self._api_key = api_key
        self._timeout_s = timeout_s

    async def moderate_text(self, text: str) -> dict:
        headers = {"Authorization": f"Token {self._api_key}"}
        data = {"text_data": text}
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            response = await client.post(self.ENDPOINT, headers=headers, data=data)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def extract_class_scores(raw_response: dict) -> dict[str, float]:
        """Pulls {class_name: score} out of Hive's v2 sync envelope.

        The exact nesting (status[0].response.output[0].classes) matches
        Hive's documented visual/text response shape as of integration time --
        confirm against a live response for your project before relying on
        this in production, since Hive versions response envelopes per API
        generation (v2/v3).
        """
        try:
            statuses = raw_response.get("status", [])
            output = statuses[0]["response"]["output"][0]
            classes = output.get("classes", [])
            return {c["class"]: c["score"] for c in classes}
        except (KeyError, IndexError, TypeError):
            return {}
