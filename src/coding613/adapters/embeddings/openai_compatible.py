"""Single-call OpenAI-compatible embedding adapter."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from coding613.adapters.llm.openai_compatible import (
    ProviderHTTPError,
    ProviderResponseError,
    ProviderTimeoutError,
)


class OpenAICompatibleEmbedding:
    def __init__(self, base_url: str, model: str, http_client: httpx.Client) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._http_client = http_client

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = list(texts)
        try:
            response = self._http_client.post(
                f"{self._base_url}/embeddings",
                json={"input": inputs, "model": self._model},
            )
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError("embedding request timed out") from error
        except httpx.HTTPError as error:
            raise ProviderHTTPError("embedding transport failed") from error
        if response.is_error:
            raise ProviderHTTPError(f"embedding provider returned HTTP {response.status_code}")
        try:
            rows = sorted(response.json()["data"], key=lambda row: row["index"])
            vectors = [[float(value) for value in row["embedding"]] for row in rows]
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderResponseError("invalid embedding response") from error
        if len(vectors) != len(inputs) or any(not vector for vector in vectors):
            raise ProviderResponseError("embedding response count or dimension mismatch")
        return vectors
