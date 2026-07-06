from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest


def _catalog() -> dict:
    return {
        "work_id": "reference/test-work",
        "edition": "2000",
        "modernisation_intent": "not_applicable",
        "pd_anchor_decision": {
            "chosen_rendering": "test-thml",
            "rationale": "Fixture anchor.",
            "decided_at": "2026-05-18T00:00:00+00:00",
            "alternates_considered": [],
        },
        "renderings": [
            {
                "rendering_id": "test-thml",
                "role": "pd_anchor",
                "source_url": "https://example.test/test-thml.thml",
                "source": "example",
                "format": "thml",
                "license": "public-domain",
            },
            {
                "rendering_id": "test-ocr",
                "role": "pending",
                "source_url": "https://archive.test/test-ocr.txt",
                "source": "internet-archive",
                "format": "ocr",
                "license": "public-domain",
                "engine": "tesseract@5.3.0",
            },
        ],
    }


def test_bootstrap_renderings_per_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work_dir = tmp_path / "data/reference/test-work/2000"
    work_dir.mkdir(parents=True)
    (work_dir / "catalog.json").write_text(json.dumps(_catalog(), indent=2) + "\n", encoding="utf-8")

    bodies = {
        "https://example.test/test-thml.thml": b"<ThML><body><p>Anchor.</p></body></ThML>",
        "https://archive.test/test-ocr.txt": b"OCR attestor text.",
    }

    class Response:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.body

    seen: list[str] = []

    def fake_urlopen(request: object, *args: object, **kwargs: object) -> Response:
        url = getattr(request, "full_url", request)
        seen.append(str(url))
        return Response(bodies[str(url)])

    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=fake_urlopen))
    monkeypatch.chdir(tmp_path)

    from build.tools.bootstrap_renderings import main

    result = main(["reference/test-work/2000"])
    assert result in (0, None)
    assert seen == ["https://example.test/test-thml.thml", "https://archive.test/test-ocr.txt"]
    assert (work_dir / "parses/test-thml.json").exists()
    assert (work_dir / "parses/test-ocr.json").exists()
