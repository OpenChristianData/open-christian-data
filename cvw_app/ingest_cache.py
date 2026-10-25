"""Bounded per-session projection cache; no durable registry or input writes."""

from __future__ import annotations
from collections import OrderedDict
import gc
import sys
import threading
from typing import Any

MAX_CACHE_RETAINED_BYTES = 256 * 1024 * 1024
CACHE_MAX_ENTRIES = 8


def estimate_retained_bytes(value: object) -> int:
    """Count the retained payload graph, excluding shared class definitions."""
    seen: set[int] = set()
    stack = [value]
    total = 0
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        total += sys.getsizeof(obj)
        # Container subclasses reference their type, whose methods lead into
        # module globals and unrelated loaded runtime state. That shared class
        # graph is not per-entry payload. Instance data and nested containers
        # still participate in the recursive, cycle-safe size calculation.
        stack.extend(ref for ref in gc.get_referents(obj) if not isinstance(ref, type))
    return total


class VerifiedIngestCache:
    """Mutex-serialized LRU over verified ingests bounded by entries and retained bytes.

    A single ingest whose estimated retained size exceeds the whole budget is not
    cached at all (it re-renders per request, disclosed as ``cache_resident`` false)
    rather than evicting everything else.
    """

    def __init__(
        self,
        max_entries: int = CACHE_MAX_ENTRIES,
        max_retained_bytes: int = MAX_CACHE_RETAINED_BYTES,
    ) -> None:
        self._max_entries = max_entries
        self._max_retained_bytes = max_retained_bytes
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple[str, ...], Any] = OrderedDict()
        self._sizes: dict[tuple[str, ...], int] = {}
        self._total = 0

    def get(self, key: tuple[str, ...]) -> Any | None:
        with self._lock:
            if key not in self._entries:
                return None
            self._entries.move_to_end(key)
            return self._entries[key]

    def admit(self, key: tuple[str, ...], value: Any) -> None:
        # Estimate the immutable projection outside the mutex; installation and
        # eviction remain atomic, keeping unrelated cache hits responsive.
        size = estimate_retained_bytes(value)
        if size > self._max_retained_bytes:
            return
        with self._lock:
            if key in self._entries:
                # Another admission may have installed this key during estimation.
                self._entries.move_to_end(key)
                return
            while self._entries and (
                len(self._entries) >= self._max_entries
                or self._total + size > self._max_retained_bytes
            ):
                evicted, _ = self._entries.popitem(last=False)
                self._total -= self._sizes.pop(evicted, 0)
            self._entries[key] = value
            self._sizes[key] = size
            self._total += size

    def snapshot(self) -> dict[tuple[str, ...], Any]:
        with self._lock:
            return dict(self._entries)


class PackedPages:
    """Decode only the requested already-validated page; compressed bytes stay bounded by LRU."""

    def __init__(self, pages):
        import json
        import zlib

        self._pages = tuple(
            zlib.compress(
                json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                ),
                1,
            )
            for page in pages
        )

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, index):
        import json
        import zlib

        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        return json.loads(zlib.decompress(self._pages[index]))


class PackedValues:
    """Independent bounded blocks preserve order without retaining decoded values."""

    BLOCK_SIZE = 64

    def __init__(self, values):
        import json
        import zlib

        self._length = len(values)
        self._blocks = tuple(
            zlib.compress(
                json.dumps(
                    values[start:start + self.BLOCK_SIZE],
                    ensure_ascii=False, separators=(",", ":"),
                ).encode("utf-8"),
                6,
            )
            for start in range(0, len(values), self.BLOCK_SIZE)
        )

    def __len__(self):
        return self._length

    def __iter__(self):
        import json
        import zlib

        for block in self._blocks:
            yield from json.loads(zlib.decompress(block))

    def __getitem__(self, index):
        import json
        import zlib

        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        block = json.loads(zlib.decompress(self._blocks[index // self.BLOCK_SIZE]))
        return block[index % self.BLOCK_SIZE]


class PackedOutline(PackedValues):
    def __init__(self, values):
        import json

        super().__init__(values)
        # Match serialized_payload_size's default JSON separators exactly.
        self.serialized_bytes = len(json.dumps(values, ensure_ascii=False).encode("utf-8"))


class PackedContexts:
    def __init__(self, contexts):
        self._indices = {key: index for index, key in enumerate(contexts)}
        self._values = PackedValues(list(contexts.values()))

    def __getitem__(self, key):
        return self._values[self._indices[key]]

    def get(self, key, default=None):
        return self[key] if key in self._indices else default


def compact_projection(rendered, threshold=16 * 1024 * 1024):
    """Preserve exact validated page/context values without retaining the full node graph.

    Cold parsing is still whole-artifact. Warm page requests decode one bounded
    page; selected contexts decode at most 64 context values. Outline iteration
    decodes one block at a time. No disk cache or second content authority exists.
    """
    if estimate_retained_bytes(rendered) <= threshold:
        return rendered
    compact = dict(rendered)
    compact["_pages"] = PackedPages(rendered["_pages"])
    compact["contexts"] = PackedContexts(rendered["contexts"])
    compact["outline"] = PackedOutline(rendered["outline"])
    compact[
        "nodes"
    ] = []  # Public documents are always populated from the requested pages.
    compact["_packed_projection"] = True
    return compact
