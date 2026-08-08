"""Deterministic local embeddings for offline tests."""

import hashlib
import math
from collections.abc import Sequence


class DeterministicEmbedding:
    def __init__(self, dimension: int = 8) -> None:
        if dimension < 1 or dimension > 32:
            raise ValueError("dimension must be between 1 and 32")
        self.dimension = dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        vector = [(digest[index] / 127.5) - 1.0 for index in range(self.dimension)]
        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]
