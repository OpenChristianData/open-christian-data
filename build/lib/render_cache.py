"""Renderer cache manifest for review HTML.

Cache key = (record_sha256, sidecar_sha256, producer_registry_version,
renderer_version, schema_version, scans_manifest_checksum_sha256). Any
mismatch invalidates the cache entry for that resource. The manifest lives at
review/.render-cache/manifest.json (gitignored).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from build.lib.paths import REPO_ROOT

DEFAULT_CACHE_PATH = REPO_ROOT / "review" / ".render-cache" / "manifest.json"


@dataclass
class CacheKey:
    record_sha256: str
    sidecar_sha256: str
    producer_registry_version: str
    renderer_version: str
    schema_version: str
    scans_manifest_checksum_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}

    def stable_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass
class CacheManifest:
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | str = DEFAULT_CACHE_PATH) -> "CacheManifest":
        p = Path(path)
        if not p.exists():
            return cls()
        body = json.loads(p.read_text(encoding="utf-8"))
        return cls(entries=body.get("entries", {}))

    def save(self, path: Path | str = DEFAULT_CACHE_PATH) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps({"entries": self.entries}, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, p)

    def is_hit(self, resource_id: str, key: CacheKey) -> bool:
        existing = self.entries.get(resource_id)
        if existing is None:
            return False
        return existing.get("key_hash") == key.stable_hash()

    def record(self, resource_id: str, key: CacheKey, rendered_path: str) -> None:
        self.entries[resource_id] = {
            "key_hash": key.stable_hash(),
            "key": key.to_dict(),
            "rendered_path": rendered_path,
        }

    def invalidate(self, resource_id: str) -> None:
        self.entries.pop(resource_id, None)


def sha256_of_file(path: Path | str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def producer_registry_version() -> str:
    """Stable identifier for the producer registry. Bumped manually when
    producers are added/removed or any signature contract changes. Stored as a
    one-liner in build/lib/warning_producers/REGISTRY_VERSION when present;
    falls back to the package directory's mtime hash otherwise."""
    version_path = REPO_ROOT / "build" / "lib" / "warning_producers" / "REGISTRY_VERSION"
    if version_path.exists():
        return version_path.read_text(encoding="utf-8").strip()
    return "unversioned"


def renderer_version() -> str:
    """Bumped when render_review_html or strategy modules change in a way that
    invalidates cached output."""
    return "v1.0.0"
