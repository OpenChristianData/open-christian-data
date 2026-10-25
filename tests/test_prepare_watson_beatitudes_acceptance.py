"""The original Watson Beatitudes stager remains a historical exact-closure route."""

from pathlib import Path
import re

import pytest

from build.tools import prepare_watson_beatitudes_acceptance as historical
from ocd_kernel.reconstruction.contract import SourceManifest


def test_historical_manifest_preserved_and_stager_fails_closed(tmp_path, monkeypatch):
    current_path = historical.ROOT / historical.MANIFEST
    current_before = current_path.read_bytes()
    monkeypatch.setattr(historical, "MANIFEST", Path("tests/fixtures/reconstruction-runtime/authorities/watson-beatitudes-original-source-manifest.json"))
    manifest = historical.ROOT / historical.MANIFEST
    original = manifest.read_bytes()
    assert historical._sha(original) == historical.MANIFEST_SHA
    with pytest.raises(ValueError, match="^work authority bytes drifted$"):
        SourceManifest.load(manifest, repository_root=historical.ROOT)
    stage = Path(tmp_path) / "historical-stage"
    expected = "Beatitudes evidence SHA-256 mismatch: " + str(historical.ROOT / "library/works/watson-beatitudes/work.json")
    with pytest.raises(ValueError, match=re.escape(expected) + "$"):
        historical.prepare(historical.ROOT, stage)
    assert not stage.exists()
    assert manifest.read_bytes() == original

    assert current_path.read_bytes() == current_before
