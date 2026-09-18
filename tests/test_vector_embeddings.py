import pytest
import numpy as np
from app.finance.vector.embeddings import FastEmbeddingProvider


def test_fast_embedding_dimension_and_normalization():
    provider = FastEmbeddingProvider(dimension=64)

    texts = ["Cloud server hosting", "Database backup storage"]
    embeddings = provider.embed_texts(texts)

    assert embeddings.shape == (2, 64)
    # Ensure L2 normalized (norm should be ~1.0)
    for vec in embeddings:
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 1e-4


def test_fast_embedding_similarity():
    provider = FastEmbeddingProvider(dimension=128)

    q = provider.embed_query("GPU cloud compute")
    doc_match = provider.embed_query("High performance GPU cluster compute instance")
    doc_unrelated = provider.embed_query("Annual catering services and lunch boxes")

    sim_match = float(np.dot(q, doc_match))
    sim_unrelated = float(np.dot(q, doc_unrelated))

    assert sim_match > sim_unrelated
    assert sim_match > 0.3
