from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def test_fetch_rendering_downloads_and_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"<ThML><body><p>Cached source text.</p></body></ThML>"
    url = "https://example.test/source/test-rendering.thml"

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return body

    urlopen = Mock(return_value=Response())
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.chdir(tmp_path)

    from build.tools.fetch_rendering import main

    result = main([url])
    assert result in (0, None)

    raw_path = tmp_path / "data/test-rendering/raw/test-rendering.thml"
    manifest_path = raw_path.with_suffix(raw_path.suffix + ".manifest.json")
    assert raw_path.read_bytes() == body

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_url"] == url
    assert manifest["source"] == "example.test"
    assert manifest["format"] == "thml"
    assert manifest["sha256"] == _sha256(body)
    assert urlopen.call_count == 1
