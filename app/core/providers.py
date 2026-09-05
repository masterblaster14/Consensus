"""Process-wide provider registry.

Built lazily from settings; tests override via `set_providers(...)`.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.embeddings import EmbeddingProvider, build_embedding_provider
from app.core.stance import StanceExtractor, build_stance_extractor


@dataclass
class Providers:
    stance: StanceExtractor
    embeddings: EmbeddingProvider


_providers: Providers | None = None


def get_providers() -> Providers:
    global _providers
    if _providers is None:
        _providers = Providers(stance=build_stance_extractor(), embeddings=build_embedding_provider())
    return _providers


def set_providers(providers: Providers | None) -> None:
    global _providers
    _providers = providers
