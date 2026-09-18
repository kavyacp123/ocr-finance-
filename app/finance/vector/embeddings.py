from abc import ABC, abstractmethod
import hashlib
import math
from typing import List
import numpy as np

from app.config import settings
from app.utils.logging import logger


class BaseEmbeddingProvider(ABC):
    """
    Abstract interface for text embedding providers.
    """

    @abstractmethod
    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """
        Embeds a list of texts into a 2D numpy float32 array of shape (N, D).
        """
        pass

    @abstractmethod
    def embed_query(self, query: str) -> np.ndarray:
        """
        Embeds a single query into a 1D numpy float32 array of shape (D,).
        """
        pass


class FastEmbeddingProvider(BaseEmbeddingProvider):
    """
    Deterministic sub-millisecond local embedding engine.
    Uses token + character n-gram hash projection with L2 normalization in pure NumPy.
    Requires no external model downloads or network calls.
    """

    def __init__(self, dimension: int = settings.VECTOR_DIMENSION):
        self.dimension = dimension

    def _hash_token(self, token: str) -> int:
        h = hashlib.md5(token.encode("utf-8")).hexdigest()
        return int(h, 16) % self.dimension

    def _embed_single(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dimension, dtype=np.float32)
        if not text:
            return vec

        cleaned = text.lower().strip()
        tokens = cleaned.split()

        # 1. Word token hashing with frequency weighting
        for tok in tokens:
            idx = self._hash_token(tok)
            vec[idx] += 1.0

            # Subword character 3-grams for typo & morphology tolerance
            if len(tok) >= 3:
                for i in range(len(tok) - 2):
                    ngram = tok[i : i + 3]
                    n_idx = self._hash_token(ngram)
                    vec[n_idx] += 0.35

        # 2. L2 Normalization
        norm = np.linalg.norm(vec)
        if norm > 1e-9:
            vec = vec / norm

        return vec

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        matrix = np.array([self._embed_single(t) for t in texts], dtype=np.float32)
        return matrix

    def embed_query(self, query: str) -> np.ndarray:
        return self._embed_single(query)


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """
    OpenAI-compatible HTTP embedding provider (e.g. vLLM or OpenAI /v1/embeddings).
    """

    def __init__(self, model_name: str = "text-embedding-3-small", base_url: str = "http://localhost:8000/v1"):
        self.model_name = model_name
        self.base_url = base_url

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        import httpx
        try:
            with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
                res = client.post("/embeddings", json={"input": texts, "model": self.model_name})
                if res.status_code == 200:
                    data = res.json()["data"]
                    return np.array([item["embedding"] for item in data], dtype=np.float32)
        except Exception as e:
            logger.warning(f"OpenAIEmbeddingProvider failed: {e}. Falling back to FastEmbeddingProvider.")
        return FastEmbeddingProvider().embed_texts(texts)

    def embed_query(self, query: str) -> np.ndarray:
        matrix = self.embed_texts([query])
        return matrix[0] if len(matrix) > 0 else np.zeros(settings.VECTOR_DIMENSION, dtype=np.float32)


def get_embedding_provider() -> BaseEmbeddingProvider:
    """
    Factory creating the configured embedding engine.
    """
    if settings.VECTOR_EMBEDDING_PROVIDER.lower() == "openai":
        return OpenAIEmbeddingProvider()
    return FastEmbeddingProvider(dimension=settings.VECTOR_DIMENSION)
