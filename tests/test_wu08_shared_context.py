"""Bounded WU-08 proof for shared source-credit correction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree

from build.tei.selected_thml import _convert
from ocd_kernel.tei.selected_thml_check import check_selected_thml
from ocd_kernel.library._common import PipelineError
from tests.test_selected_thml_lifecycle import _fixture


def _candidate_from_manifest(manifest, destination: Path) -> Path:
    produced = _convert(manifest)
    candidate = destination / "candidate.xml"
    candidate.parent.mkdir()
    tree = etree.fromstring(produced["content.tei.xml"])
    header = tree[0]
    from ocd_kernel.tei.writer import tei_el

    header.find(
        ".//{http://www.tei-c.org/ns/1.0}bibl"
    ).append(tei_el("idno", {"type": "representation_revision"}, text="wu08-v2"))
    candidate.write_bytes(etree.tostring(tree, encoding="utf-8", xml_declaration=True))
    return candidate


def test_shared_credit_correction_revalidates_dependent_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    root, _, acquisition, work, candidate = _fixture(tmp_path, "anthology", monkeypatch)
    previous_candidate = candidate.read_bytes()
    previous_source = acquisition["source_sha256"]

    source = root / acquisition["source_path"]
    corrected = source.read_bytes().replace(b"Fixture shared credit.", b"Corrected shared credit.")
    source.write_bytes(corrected)
    acquisition["source_bytes"] = len(corrected)
    acquisition["source_sha256"] = hashlib.sha256(corrected).hexdigest()
    acquisition["retained_files"][0].update(
        bytes=len(corrected), sha256=acquisition["source_sha256"]
    )
    dependency = acquisition["source_selection"]["dependencies"][0]
    dependency["text_sha256"] = hashlib.sha256(
        b"Corrected shared credit."
    ).hexdigest()

    # The old selection digest and source binding are now stale, so the owning
    # checker rejects it before any acceptance or publication operation.
    try:
        check_selected_thml(root, acquisition, work, candidate)
    except PipelineError:
        pass
    else:
        raise AssertionError("stale dependent candidate was accepted")

    (root / "library/works/first/forms/english/editions/edition/acquisitions/acquired.json").write_text(
        json.dumps(acquisition, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = type(
        "FixtureManifest",
        (),
        {"repository_root": root, "verify": lambda self: None,
         "authority_path": lambda self, name: {
            "retained-source": source,
            "work": root / "library/works/first/work.json",
            "acquisition": root / "library/works/first/forms/english/editions/edition/acquisitions/acquired.json",
        }[name]},
    )()
    refreshed = _candidate_from_manifest(manifest, tmp_path / "refreshed")
    assert check_selected_thml(root, acquisition, work, refreshed)["status"] == "pass"
    assert refreshed.read_bytes() != previous_candidate
    assert candidate.read_bytes() == previous_candidate
    assert acquisition["source_sha256"] != previous_source
    assert b"Corrected shared credit." in refreshed.read_bytes()
