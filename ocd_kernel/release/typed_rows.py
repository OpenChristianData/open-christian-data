"""Typed Arrow companions for lossless standard dataset loading.

JSON readers may infer timestamps before applying a declared string schema.
Construct Arrow from decoded JSON values and the complete configuration schema
instead. JSONL remains the independently checked public projection.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa

from ocd_kernel.library._common import PipelineError
from .streaming import MAX_JSONL_ROW_BYTES

LEGACY_ENCODING = "arrow-ipc-1024-v1"
BOUNDED_ENCODING = "arrow-ipc-bounded-v1"
_BATCH_BYTES = 8 * 1024 * 1024
_MAX_ROW_BYTES = MAX_JSONL_ROW_BYTES


def _batches(rows: Iterable[dict[str, Any]], encoding: str):
    from ocd_kernel.library._common import canonical_bytes

    if encoding not in {LEGACY_ENCODING, BOUNDED_ENCODING}:
        raise PipelineError(f"unsupported typed encoding: {encoding}")
    batch, size = [], 0
    for row in rows:
        row_size = len(canonical_bytes(row)) if encoding == BOUNDED_ENCODING else 0
        if row_size > _MAX_ROW_BYTES:
            raise PipelineError(f"typed row exceeds {_MAX_ROW_BYTES} canonical JSON bytes")
        if batch and (len(batch) == 1024 or size + row_size > _BATCH_BYTES):
            yield batch
            batch, size = [], 0
        batch.append(row)
        size += row_size
    if batch:
        yield batch


def _write_rows(sink, rows: Iterable[dict[str, Any]], features, encoding: str) -> None:
    schema = arrow_schema(features)
    with pa.ipc.new_stream(sink, schema) as writer:
        for batch in _batches(rows, encoding):
            table = pa.Table.from_pylist(batch, schema=schema)
            compare_rows(batch, table.to_pylist())
            writer.write_table(table, max_chunksize=1024)


def write_rows(path: Path, rows: Iterable[dict[str, Any]], features,
               *, encoding: str = BOUNDED_ENCODING) -> None:
    """Write bounded IPC; retain full-table encoding for historical callers."""
    if encoding == LEGACY_ENCODING:
        # Historical full-table slices have a different IPC buffer layout.
        Path(path).write_bytes(encode_rows(list(rows), features))
        return
    with Path(path).open("wb") as sink:
        _write_rows(sink, rows, features, encoding)


class _DigestSink(io.RawIOBase):
    def __init__(self):
        super().__init__()
        self.digest = hashlib.sha256()
        self.length = 0

    def writable(self):
        return True

    def tell(self):
        return self.length

    def write(self, content):
        self.digest.update(content)
        self.length += len(content)
        return len(content)


def check_rows_file(path: Path, rows: Iterable[dict[str, Any]], features,
                    *, encoding: str = LEGACY_ENCODING) -> None:
    """Compare exact canonical IPC, including schema metadata and trailing bytes."""
    from .streaming import file_sha256

    if encoding == LEGACY_ENCODING:
        # Preserve the historical byte contract; new releases use bounded IPC.
        check_rows(Path(path).read_bytes(), list(rows), features)
        return
    try:
        sink = _DigestSink()
        with Path(path).open("rb") as source:
            with pa.ipc.open_stream(source) as reader:
                if not reader.schema.equals(arrow_schema(features), check_metadata=True):
                    raise PipelineError("typed companion schema differs")

                def actual_rows():
                    for batch in reader:
                        if batch.num_rows > 1024 or batch.nbytes > _MAX_ROW_BYTES:
                            raise PipelineError("typed companion batch exceeds bounded encoding limits")
                        yield from batch.to_pylist()

                actual = actual_rows()

                def checked_rows():
                    for index, row in enumerate(rows):
                        loaded = next(actual, None)
                        if loaded is None:
                            raise PipelineError("typed reader omitted rows")
                        compare_rows(row, loaded, f"rows/{index}")
                        yield row
                    if next(actual, None) is not None:
                        raise PipelineError("typed reader added rows")

                _write_rows(sink, checked_rows(), features, encoding)
        if Path(path).stat().st_size != sink.length or file_sha256(path) != sink.digest.hexdigest():
            raise PipelineError("typed companion is not canonical")
    except pa.ArrowException as exc:
        raise PipelineError(f"invalid typed companion: {exc}") from exc


def arrow_schema(features: list[dict[str, Any]]) -> pa.Schema:
    def value_type(feature):
        if "struct" in feature:
            return pa.struct(fields(feature["struct"]))
        if "list" in feature:
            child = feature["list"]
            if isinstance(child, list):
                return pa.list_(pa.struct(fields(child)))
            return pa.list_(value_type(child if isinstance(child, dict) else {"dtype": child}))
        return pa.type_for_alias(feature["dtype"])

    def fields(values):
        return [pa.field(value["name"], value_type(value)) for value in values]

    return pa.schema(fields(features))


def compare_rows(original: Any, loaded: Any, location: str = "rows") -> None:
    """Permit only absent optional fields becoming null in a tabular reader."""
    if isinstance(original, dict):
        if not isinstance(loaded, dict) or not original.keys() <= loaded.keys():
            raise PipelineError(f"typed reader changed object fields at {location}")
        for key, value in original.items():
            compare_rows(value, loaded[key], f"{location}/{key}")
        if any(loaded[key] is not None for key in loaded.keys() - original.keys()):
            raise PipelineError(f"typed reader invented a value at {location}")
    elif isinstance(original, list):
        if not isinstance(loaded, list) or len(original) != len(loaded):
            raise PipelineError(f"typed reader changed list length at {location}")
        for index, (before, after) in enumerate(zip(original, loaded, strict=True)):
            compare_rows(before, after, f"{location}/{index}")
    elif type(original) is not type(loaded) or original != loaded:
        raise PipelineError(f"typed reader changed value at {location}")


def encode_rows(rows: list[dict[str, Any]], features: list[dict[str, Any]]) -> bytes:
    schema = arrow_schema(features)
    table = pa.Table.from_pylist(rows, schema=schema)
    compare_rows(rows, table.to_pylist())
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, schema) as writer:
        writer.write_table(table, max_chunksize=1024)
    return sink.getvalue().to_pybytes()


def check_rows(content: bytes, rows: list[dict[str, Any]], features: list[dict[str, Any]]) -> None:
    """Read actual companion values; also reject metadata and unused byte payloads."""
    try:
        with pa.ipc.open_stream(content) as reader:
            table = reader.read_all()
        if not table.schema.equals(arrow_schema(features), check_metadata=True):
            raise PipelineError("typed companion schema differs")
        compare_rows(rows, table.to_pylist())
        if content != encode_rows(rows, features):
            raise PipelineError("typed companion is not canonical")
    except pa.ArrowException as exc:
        raise PipelineError(f"invalid typed companion: {exc}") from exc
