from __future__ import annotations

import math
import os
import re
from typing import Any

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

load_dotenv()

DEFAULT_TOP_K = 6
_TOKEN = re.compile(r"[a-záéíóúüñ0-9]+", re.IGNORECASE)


class KtagRetriever:
    """Embeddings + cosine top-k. Cache por ktag; fallback léxico si falla el embedding."""

    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}
        self._embeddings: OpenAIEmbeddings | None = None

    def invalidate(self) -> None:
        self._vectors.clear()

    def retrieve(
        self,
        query: str,
        ktags: list[dict[str, str]],
        k: int = DEFAULT_TOP_K,
    ) -> list[dict[str, Any]]:
        if not ktags or not (query or "").strip():
            return []
        scored = self._score_embeddings(query, ktags)
        if scored is None:
            scored = self._score_lexical(query, ktags)
        scored.sort(key=lambda item: item["score"], reverse=True)
        return [item for item in scored[:k] if item["score"] > 0]

    def _embedder(self) -> OpenAIEmbeddings:
        if self._embeddings is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("Falta OPENAI_API_KEY")
            self._embeddings = OpenAIEmbeddings(
                model="text-embedding-3-small",
                api_key=api_key,
            )
        return self._embeddings

    def _score_embeddings(
        self, query: str, ktags: list[dict[str, str]]
    ) -> list[dict[str, Any]] | None:
        try:
            embedder = self._embedder()
            missing: list[tuple[str, str]] = []
            keys: list[str] = []
            for ktag in ktags:
                key = _cache_key(ktag)
                keys.append(key)
                if key not in self._vectors:
                    missing.append((key, _ktag_text(ktag)))
            if missing:
                vectors = embedder.embed_documents([text for _, text in missing])
                for (key, _), vector in zip(missing, vectors):
                    self._vectors[key] = vector
            query_vector = embedder.embed_query(query)
            results: list[dict[str, Any]] = []
            for ktag, key in zip(ktags, keys):
                score = _cosine(query_vector, self._vectors[key])
                results.append({**ktag, "score": round(float(score), 4)})
            return results
        except Exception:
            return None

    def _score_lexical(self, query: str, ktags: list[dict[str, str]]) -> list[dict[str, Any]]:
        q_tokens = set(_TOKEN.findall(query.lower()))
        results: list[dict[str, Any]] = []
        for ktag in ktags:
            tokens = set(_TOKEN.findall(_ktag_text(ktag).lower()))
            if not q_tokens or not tokens:
                score = 0.0
            else:
                score = len(q_tokens & tokens) / len(q_tokens)
            results.append({**ktag, "score": round(score, 4)})
        return results


def _ktag_text(ktag: dict[str, str]) -> str:
    return f"{ktag.get('name', '')}\n{ktag.get('value', '')}"


def _cache_key(ktag: dict[str, str]) -> str:
    return f"{ktag.get('id', '')}:{hash(_ktag_text(ktag))}"


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


retriever = KtagRetriever()
