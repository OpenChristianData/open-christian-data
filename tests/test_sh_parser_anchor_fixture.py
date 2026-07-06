from __future__ import annotations

import json
from pathlib import Path

from build.parsers import ccel_schaff_herzog, ia_schaff_herzog


FIXTURES = [
    (Path("build/parsers/ia_schaff_herzog.anchor_fixture.json"), ia_schaff_herzog.slugify),
    (Path("build/parsers/ccel_schaff_herzog.anchor_fixture.json"), ccel_schaff_herzog.slugify),
]


def test_sh_parser_anchor_fixtures_have_50_samples() -> None:
    for fixture_path, _slugify in FIXTURES:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert len(payload["samples"]) == 50


def test_sh_parser_anchor_fixtures_match_slug_algorithms() -> None:
    for fixture_path, slugify in FIXTURES:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        for sample in payload["samples"]:
            expected = f"schaff-herzog.{slugify(sample['input'])}"
            assert sample["expected_anchor"] == expected
