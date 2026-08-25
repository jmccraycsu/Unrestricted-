"""
Sightengine image moderation client (https://sightengine.com/docs/reference).

GET https://api.sightengine.com/1.0/check.json with `url`, `models`,
`api_user`, `api_secret` query params. Response fields depend on which
models were requested (e.g. nudity-2.1, gore-2.0, offensive).

Note: this is general content-policy moderation (gore, weapons, offensive
imagery) -- it is NOT a CSAM detector and general nudity scores should
never be treated as one. CSAM detection needs a purpose-built classifier
(e.g. Hive's dedicated CSAM model, Thorn's Safer) and/or hash-matching
against known-CSAM hash databases, wired as its own hard-block path with
mandatory legal reporting -- see moderation/service.py.
"""

from __future__ import annotations

import httpx


class SightengineImageModerationClient:
    ENDPOINT = "https://api.sightengine.com/1.0/check.json"

    def __init__(
        self,
        api_user: str,
        api_secret: str,
        models: tuple[str, ...] = ("nudity-2.1", "gore-2.0", "offensive", "weapon"),
        timeout_s: float = 10.0,
    ):
        self._api_user = api_user
        self._api_secret = api_secret
        self._models = ",".join(models)
        self._timeout_s = timeout_s

    async def moderate_image_url(self, image_url: str) -> dict:
        params = {
            "url": image_url,
            "models": self._models,
            "api_user": self._api_user,
            "api_secret": self._api_secret,
        }
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            response = await client.get(self.ENDPOINT, params=params)
            response.raise_for_status()
            return response.json()
