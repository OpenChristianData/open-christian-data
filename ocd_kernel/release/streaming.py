"""Bounded release file hashing and strict LF-framed JSONL reading."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterator

from ocd_kernel.library._common import PipelineError, canonical_bytes

MAX_JSONL_ROW_BYTES = 64 * 1024 * 1024


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_object(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise PipelineError(f"duplicate public row key: {key}")
        value[key] = child
    return value


def iter_jsonl(path: Path, *, canonical: bool = False) -> Iterator[dict]:
    """Split only on LF; Unicode line separators inside strings are content."""
    with Path(path).open("rb") as source:
        for line in iter(lambda: source.readline(MAX_JSONL_ROW_BYTES + 1), b""):
            if len(line) > MAX_JSONL_ROW_BYTES:
                raise PipelineError(f"JSONL row exceeds {MAX_JSONL_ROW_BYTES} bytes")
            if not line.endswith(b"\n") or b"\r" in line:
                raise PipelineError("configuration is not canonical JSONL")
            row = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object)
            if not isinstance(row, dict):
                raise PipelineError("configuration requires nonempty object rows")
            if canonical and canonical_bytes(row) != line:
                raise PipelineError("configuration is not canonical JSONL")
            yield row
