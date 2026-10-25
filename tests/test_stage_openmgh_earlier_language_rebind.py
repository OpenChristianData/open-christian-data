"""The three earlier openMGH language decisions remain source and hash bound."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tools import stage_openmgh_earlier_language_rebind as stage
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.acceptance import validate_acceptance


@pytest.mark.parametrize("work_id", stage.IDS)
def test_latin_decision_uses_selected_source_body(work_id: str) -> None:
    source_path, source_sha = stage.SOURCES[work_id]
    source_tree = etree.parse(
        str(stage._io_path(stage.ROOT / source_path)),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    _, _, _, boundary_path = stage._paths(work_id)
    evidence = stage._source_check(
        source_tree, work_id, stage._read(stage.ROOT / boundary_path)
    )
    assert evidence["language"] == "la"
    assert evidence["source_sha256"] == source_sha
    assert evidence["body_clause"] == stage.BODY_CLAUSES[work_id]


def test_other_work_boundary_cannot_support_language_decision() -> None:
    work_id = "bernald-avoiding-communion-with-excommunicates"
    source_path, _source_sha = stage.SOURCES[work_id]
    source_tree = etree.parse(
        str(stage._io_path(stage.ROOT / source_path)),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    _, _, _, boundary_path = stage._paths(work_id)
    _, _, _, other_boundary_path = stage._paths("anulus-et-baculus-verses")
    boundary = stage._read(stage.ROOT / boundary_path)
    boundary["end_xml_id"] = stage._read(stage.ROOT / other_boundary_path)["end_xml_id"]
    with pytest.raises(PipelineError, match="crosses a work boundary"):
        stage._source_check(source_tree, work_id, boundary)


def test_missing_body_clause_blocks_language_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_id = "actus-sancti-eremberti"
    source_path, _source_sha = stage.SOURCES[work_id]
    source_tree = etree.parse(
        str(stage._io_path(stage.ROOT / source_path)),
        etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True),
    )
    _, _, _, boundary_path = stage._paths(work_id)
    monkeypatch.setitem(stage.BODY_CLAUSES, work_id, "not in the retained selected body")
    with pytest.raises(PipelineError, match="Latin body clause differs"):
        stage._source_check(
            source_tree, work_id, stage._read(stage.ROOT / boundary_path)
        )


def test_staged_swap_rolls_back_exact_bytes_and_commits_with_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_name = os.environ.get("OCD_OPENMGH_EARLIER_LANGUAGE_REBIND_RECEIPT")
    if not receipt_name:
        pytest.skip("explicit local three-work language-rebind receipt is required")
    record = stage._read(Path(receipt_name).resolve(strict=True))
    work_id = "bernald-avoiding-communion-with-excommunicates"
    row = next(item for item in record["works"] if item["work_id"] == work_id)
    original_root = Path(record["canonical_root"])
    isolated_root = tmp_path / "isolated"
    isolated_root.mkdir()
    for relative in record["external_dependencies"]:
        target = stage._io_path(isolated_root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stage._io_path(original_root / relative), target)
    work, edition, manifest_rel, _boundary = stage._paths(work_id)
    profile_rel = manifest_rel.parent / "reconstruction-profile.json"
    shutil.copytree(
        stage._io_path(original_root / work), stage._io_path(isolated_root / work)
    )
    isolated_record = copy.deepcopy(record)
    isolated_record["canonical_root"] = isolated_root.as_posix()
    isolated_receipt = tmp_path / "receipt.json"
    isolated_receipt.write_text(json.dumps(isolated_record), encoding="utf-8")
    stage.preflight(isolated_receipt, work_id)

    durable_write = stage._write_json_durable
    injected = False

    def fail_after_profile(path: Path, payload: dict) -> None:
        nonlocal injected
        durable_write(path, payload)
        if payload.get("phase") == "new-profile-live" and not injected:
            injected = True
            raise RuntimeError("injected failure after profile swap")

    monkeypatch.setattr(stage, "_write_json_durable", fail_after_profile)
    with pytest.raises(RuntimeError, match="injected failure after profile swap"):
        stage.install(isolated_receipt, work_id)
    assert injected
    assert stage._files(isolated_root / work) == row["before"]
    for relative in (profile_rel, manifest_rel):
        assert stage._sha(isolated_root / relative) == record["external_dependencies"][relative.as_posix()]["before_sha256"]
    stage.preflight(isolated_receipt, work_id)

    monkeypatch.setattr(stage, "_write_json_durable", durable_write)
    result = stage.install(isolated_receipt, work_id)
    assert result["status"] == "installed-and-validated"
    assert stage._files(isolated_root / work) == row["after"]
    for relative in (profile_rel, manifest_rel):
        assert stage._sha(isolated_root / relative) == record["external_dependencies"][relative.as_posix()]["proposed_sha256"]
    SourceManifest.load(isolated_root / manifest_rel, repository_root=isolated_root)
    validate_acceptance(isolated_root / edition / "acceptance.json", root=isolated_root)
    validate_state(isolated_root / work / "state.json", root=isolated_root)
    assert stage._sha(isolated_root / edition / "master.tei.xml") == row["master_sha256"]
