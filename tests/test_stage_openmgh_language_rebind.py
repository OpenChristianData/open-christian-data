"""The four language decisions must stay bound to their own retained prose."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tools import stage_openmgh_language_rebind as stage
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.reconstruction.contract import SourceManifest
from ocd_kernel.tei.acceptance import validate_acceptance


@pytest.fixture(scope="module")
def retained_tree() -> etree._ElementTree:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    return etree.parse(str(stage.ROOT / stage.SOURCE), parser)


@pytest.mark.parametrize("work_id", stage.IDS)
def test_latin_decision_uses_selected_source_body(
    retained_tree: etree._ElementTree, work_id: str
) -> None:
    _, _, _, boundary = stage._paths(work_id)
    record = stage._source_check(retained_tree, work_id, stage._read(stage.ROOT / boundary))
    assert record["language"] == "la"
    assert record["source_sha256"] == stage.SOURCE_SHA
    assert record["body_clause"] == stage.PROSE_CLAUSES[work_id]


def test_other_work_boundary_cannot_support_language_decision(
    retained_tree: etree._ElementTree,
) -> None:
    _, _, _, target_boundary = stage._paths(stage.IDS[0])
    _, _, _, other_boundary = stage._paths(stage.IDS[1])
    record = stage._read(stage.ROOT / target_boundary)
    record["end_xml_id"] = stage._read(stage.ROOT / other_boundary)["end_xml_id"]
    with pytest.raises(PipelineError, match="crosses a work boundary"):
        stage._source_check(retained_tree, stage.IDS[0], record)


def test_missing_body_clause_blocks_language_decision(
    retained_tree: etree._ElementTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_id = stage.IDS[0]
    _, _, _, boundary = stage._paths(work_id)
    monkeypatch.setitem(stage.PROSE_CLAUSES, work_id, "not present in the retained text")
    with pytest.raises(PipelineError, match="Latin body clause differs"):
        stage._source_check(retained_tree, work_id, stage._read(stage.ROOT / boundary))


def test_staged_swap_rolls_back_exact_bytes_and_commits_with_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipt_name = os.environ.get("OCD_OPENMGH_LANGUAGE_REBIND_RECEIPT")
    if not receipt_name:
        pytest.skip("explicit local language-rebind stage receipt is required")
    source_receipt = Path(receipt_name).resolve(strict=True)
    record = stage._read(source_receipt)
    work_id = stage.IDS[0]
    row = next(item for item in record["works"] if item["work_id"] == work_id)
    original_root = Path(record["canonical_root"])
    stage_root = Path(record["stage_root"])
    isolated_root = tmp_path / "isolated"
    isolated_root.mkdir()
    for relative in record["external_dependencies"]:
        source = stage._io_path(original_root / relative)
        target = stage._io_path(isolated_root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    work, edition, manifest_rel, _boundary = stage._paths(work_id)
    profile_rel = manifest_rel.parent / "reconstruction-profile.json"
    shutil.copytree(stage._io_path(original_root / work), stage._io_path(isolated_root / work))
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
