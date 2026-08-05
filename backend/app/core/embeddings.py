"""Turning text into vectors.

The default implementation is a deterministic, dependency-free "hashing"
embedder. It is *not* semantically smart -- it exists so the whole pipeline
(including pgvector similarity search) runs locally with no API keys and no
model download.

To use real embeddings, replace the body of `embed_text` with a call to your
provider, set EMBEDDING_DIMENSIONS in backend/.env to that model's dimension,
and recreate the `facts` table.
"""

import hashlib
import math
import re

from app.core.config import settings

_WORD_RE = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def embed_text(text: str) -> list[float]:
    """Return a unit-length vector of length settings.embedding_dimensions."""
    dimensions = settings.embedding_dimensions
    vector = [0.0] * dimensions

    tokens = _tokens(text)
    # Include word pairs so ordering carries a little signal.
    features = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]

    for feature in features:
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        # An empty/stopword-only string: return a valid zero-ish unit vector.
        vector[0] = 1.0
        return vector

    return [value / norm for value in vector]
