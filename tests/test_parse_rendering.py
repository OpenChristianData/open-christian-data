from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_parse_rendering_runs_per_format_parser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rendering_id = "test-thml-rendering"
    work_handle = "reference/test-work/2000"
    raw_dir = tmp_path / "data" / rendering_id / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "test-thml-rendering.thml").write_bytes(
        b"<ThML><body><div1><p>Parsed source text.</p></div1></body></ThML>"
    )
    (raw_dir / "manifest.json").write_text(
        json.dumps(
            {
                "rendering_id": rendering_id,
                "work_handle": work_handle,
                "format": "thml",
                "source": "fixture",
                "sha256": "sha256:" + "a" * 64,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    from build.tools.parse_rendering import main

    result = main([rendering_id])
    assert result in (0, None)

    parse_path = tmp_path / "data/reference/test-work/2000/parses/test-thml-rendering.json"
    parsed = json.loads(parse_path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    assert parsed["rendering_id"] == rendering_id
