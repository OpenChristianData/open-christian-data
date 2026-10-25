"""Public validation of the versioned Watson Beatitudes acceptance rebind."""

import hashlib
import json

import pytest

from tests.watson_public_runtime_fixture import current_installed_acceptance

from build.tools import prepare_watson_beatitudes_rebind as rebind
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei import acceptance as acceptance_module


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def current_acceptance():
    # Keep this lifetime separate from each original wrong-oracle test's undo().
    with pytest.MonkeyPatch.context() as patch:
        def mirror_acceptance(stage):
            acceptance = current_installed_acceptance(rebind, stage, patch)
            manifest = stage / rebind.CURRENT_MANIFEST
            original = manifest.read_bytes()
            assert original == (rebind.ROOT / rebind.CURRENT_MANIFEST).read_bytes()
            historical_lf = original.replace(b"\r\n", b"\n")
            assert _digest(historical_lf) == rebind.CURRENT_MANIFEST_SHA
            assert json.loads(historical_lf) == json.loads(original)
            manifest.write_bytes(historical_lf)
            return acceptance
        yield mirror_acceptance


def test_versioned_rebind_public_acceptance_and_mutations(tmp_path_factory, monkeypatch, current_acceptance):
    originals = {
        path: (rebind.ROOT / path).read_bytes()
        for path in (
            rebind.HISTORICAL_MANIFEST,
            rebind.CURRENT_MANIFEST,
            rebind.WORK / "work.json",
            rebind.ACQUISITION,
            rebind.EDITION / "acceptance.json",
            rebind.EDITION / "master.tei.xml",
        )
    }
    stage = tmp_path_factory.mktemp("b") / "s"
    acceptance = current_acceptance(stage)
    record = acceptance_module.validate_acceptance(acceptance, root=stage)
    assert record["promotion"]["status"] == "promoted"
    installed = json.loads(originals[rebind.EDITION / "acceptance.json"])
    assert record["promotion"] == installed["promotion"]
    assert record["decision"] == installed["decision"]
    assert record["promotion"]["master"]["sha256"] == rebind.INSTALLED_MASTER_SHA
    assert _digest((stage / rebind.EVIDENCE / "candidate.tei.xml").read_bytes()) == rebind.INSTALLED_MASTER_SHA
    assert _digest((stage / rebind.HISTORICAL_MANIFEST).read_bytes()) == rebind.historical.MANIFEST_SHA
    assert _digest((stage / rebind.CURRENT_MANIFEST).read_bytes()) == rebind.CURRENT_MANIFEST_SHA

    source = stage / rebind.SOURCE
    original_source = source.read_bytes()
    try:
        source.write_bytes(original_source + b"x")
        with pytest.raises(PipelineError):
            acceptance_module.validate_acceptance(acceptance, root=stage)
    finally:
        source.write_bytes(original_source)

    acquisition = stage / rebind.ACQUISITION
    original_acquisition = acquisition.read_bytes()
    try:
        changed = json.loads(original_acquisition)
        changed["source_selection"]["selection_id"] = "unbound-selection"
        acquisition.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(PipelineError):
            acceptance_module.validate_acceptance(acceptance, root=stage)
    finally:
        acquisition.write_bytes(original_acquisition)

    original_oracle = acceptance_module._beatitudes_oracle()

    def wrong_oracle(*args):
        return original_oracle(*args)

    wrong_oracle.oracle_id = "unbound-oracle"
    wrong_oracle.oracle_version = "1"
    monkeypatch.setattr(acceptance_module, "_beatitudes_oracle", lambda: wrong_oracle)
    with pytest.raises(PipelineError, match="independent oracle rejected"):
        acceptance_module.validate_acceptance(acceptance, root=stage)
    monkeypatch.undo()

    acceptance_module.validate_acceptance(acceptance, root=stage)
    for path, content in originals.items():
        assert (rebind.ROOT / path).read_bytes() == content


def test_historical_preparer_rejects_current_authorities_without_writes(tmp_path):
    paths = (rebind.HISTORICAL_MANIFEST, rebind.CURRENT_MANIFEST,
             rebind.WORK / "work.json", rebind.ACQUISITION,
             rebind.EDITION / "acceptance.json", rebind.EDITION / "master.tei.xml")
    originals = {path: (rebind.ROOT / path).read_bytes() for path in paths}
    stage = tmp_path / "obsolete-rebind"
    with pytest.raises(PipelineError, match="Beatitudes binding differs"):
        rebind.prepare(rebind.ROOT, stage)
    assert not stage.exists()
    assert all((rebind.ROOT / path).read_bytes() == raw for path, raw in originals.items())
