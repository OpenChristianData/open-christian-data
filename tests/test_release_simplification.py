"""Small end-to-end release sequence and accepted-identity label contracts."""
import json

import pytest

from build.scripts.export_huggingface import main as export_main
from build.tools import check_release_reader as reader
from ocd_kernel.library._common import PipelineError, canonical_bytes
from ocd_kernel.release import verify
from tests.test_release_assembly_v2 import _item, _selection


@pytest.mark.parametrize("category", ["prose", "reference_entries"])
def test_export_then_default_reader_produces_two_complete_checks(tmp_path, monkeypatch, capsys, category):
    from ocd_kernel.tei.acceptance import promote_accepted_master
    if category == "prose":
        from tests.test_tei_acceptance import _fixture_root, _write_valid_acceptance
        source = _fixture_root(tmp_path / "f")
        pending, _ = _write_valid_acceptance(source)
    else:
        from tests.test_release_accepted_structured import accepted_fixture
        source, pending = accepted_fixture(tmp_path / "f", category)
    promoted = promote_accepted_master(source, acceptance_path=pending, destination=tmp_path / "p")
    root, acceptance = promoted.destination_root, promoted.acceptance_path
    selection = _selection(_item(root, "friendly-label", category, acceptance))
    selected = tmp_path / "selection.json"
    selected.write_bytes(canonical_bytes(selection))
    calls = []
    original = verify.verify_release_v2

    def checked(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(verify, "verify_release_v2", checked)
    monkeypatch.setattr(reader, "verify_release_v2", checked)
    release = tmp_path / "out"
    assert export_main(["--root", str(root), "--selection", str(selected), "--output", str(release)]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["assembly"] == exported["verification"] == "pass"
    assert len(calls) == 1
    proof = reader.check_reader(root, release, selection)
    assert proof["status"] == proof["verification"]["status"] == "pass"
    assert all(config["normal_and_streaming"] == "pass" for config in proof["configurations"])
    assert len(calls) == 2
    report = json.loads((release / "internal/release-report.json").read_text())
    path = release / report["configurations"][0]["path"]
    path.write_bytes(path.read_bytes().replace(b'"text":', b'"tampered_text":', 1))
    with pytest.raises(PipelineError, match="verification failed"):
        reader.check_reader(root, release, selection)
