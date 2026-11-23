"""Local token counting for the approved overview model revision."""

from __future__ import annotations

import base64
import gzip
import hashlib
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from tiktoken import Encoding


_MODEL_REVISION = "41a558fc459a96edbf0500938edc7d3ddaceedde727d1e7faa8ec4fbc9eb8772"
_VOCAB_SHA256 = "9a7aba4547612861457d2b7709684fe39622a1fe6dcfba5bd0e5c620716bd1d8"
_VOCAB = Path(__file__).resolve().parents[1] / "resources" / "qwen35.tiktoken.gz"
# qwen35 pre-tokenization from llama.cpp 6c01da627, src/llama-vocab.cpp.
_PRETOKENIZER = (
    r"(?:'[sS]|'[tT]|'[rR][eE]|'[vV][eE]|'[mM]|'[lL][lL]|'[dD])"
    r"|[^\r\n\p{L}\p{N}]?[\p{L}\p{M}]+|\p{N}| ?[^\s\p{L}\p{M}\p{N}]+[\r\n]*"
    r"|\s*[\r\n]+|\s+(?!\S)|\s+"
)


@lru_cache(maxsize=1)
def _encoding() -> Encoding:
    compressed = _VOCAB.read_bytes()
    if hashlib.sha256(compressed).hexdigest() != _VOCAB_SHA256:
        raise ValueError("overview_tokenizer_digest_mismatch")
    ranks = {base64.b64decode(line, validate=True): rank for rank, line in enumerate(gzip.decompress(compressed).splitlines())}
    return Encoding(name="bidops-qwen35-overview", pat_str=_PRETOKENIZER, mergeable_ranks=ranks, special_tokens={})


def overview_token_counter(revision: str | None, api_dialect: str) -> Callable[[str], int] | None:
    if revision != _MODEL_REVISION or api_dialect != "litellm":
        return None
    try:
        encoding = _encoding()
    except (OSError, ValueError):
        # Keep the byte-bound check when the installed artifact cannot be verified.
        return None
    return lambda value: len(encoding.encode_ordinary(value))
