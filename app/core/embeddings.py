"""Embedding provider interface + implementations.

Everything that needs a vector goes through `EmbeddingProvider.embed`. Nothing
else in the codebase talks to an embedding API directly.

Providers:
  * OpenAIEmbeddingProvider  - text-embedding-3-small, 1536 dims (default)
  * HashingEmbeddingProvider - offline, deterministic bag-of-words hashed into
                               1536 dims and L2-normalised. Cosine similarity
                               then reflects token overlap. Used for tests and
                               network-free demos.
"""
from __future__ import annotations

import hashlib
import logging
import math
from typing import Protocol

from app.config import get_settings
from app.core.text import tokens

log = logging.getLogger(__name__)


class EmbeddingProvider(Protocol):
    dimensions: int

    async def embed(self, text: str) -> list[float]: ...

    async def embed_many(self, texts: list[str]) -> list[list[float]]: ...


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class OpenAIEmbeddingProvider:
    def __init__(self, model: str | None = None, dimensions: int | None = None, api_key: str | None = None) -> None:
        from openai import AsyncOpenAI

        settings = get_settings()
        self.model = model or settings.embedding_model
        self.dimensions = dimensions or settings.embedding_dimensions
        self._client = AsyncOpenAI(api_key=api_key or settings.openai_api_key, max_retries=2, timeout=30.0)

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = await self._client.embeddings.create(
            model=self.model, input=[t.replace("\n", " ") for t in texts], dimensions=self.dimensions
        )
        by_index = sorted(resp.data, key=lambda d: d.index)
        return [d.embedding for d in by_index]


class HashingEmbeddingProvider:
    """Deterministic hashed bag-of-words. Good enough to rank by lexical overlap."""

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions or get_settings().embedding_dimensions

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        toks = tokens(text)
        # unigrams + bigrams so word order contributes a little
        grams = list(toks) + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        for g in grams:
            h = hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "big") % self.dimensions
            sign = 1.0 if h[4] & 1 else -1.0
            weight = 1.0 if "_" not in g else 0.5
            vec[idx] += sign * weight
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]

    async def embed(self, text: str) -> list[float]:
        return self._vector(text)

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


def build_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.embedding_provider == "openai":
        if not settings.openai_api_key:
            log.warning("EMBEDDING_PROVIDER=openai but OPENAI_API_KEY is empty; falling back to hashing provider")
            return HashingEmbeddingProvider()
        return OpenAIEmbeddingProvider()
    return HashingEmbeddingProvider()
