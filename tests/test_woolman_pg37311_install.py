"""Focused acceptance and projection checks for the retained PG 37311 volume."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from build.tei.woolman_37311_oracle import _oracle
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.native_documents import project_document
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.acceptance import _validate_acceptance_for_work


ROOT = Path(__file__).resolve().parents[1]
WORK_ID = "john-woolman-journal-other-writings"
WORK = ROOT / "library/works" / WORK_ID
EDITION = WORK / "forms/english/editions/everyman-402-1910-electronic"
RETAINED_MANIFEST = Path("sources/manifest-acquisitions/gutenberg-pg37311-woolman-v5/source-manifest.json")
MANIFEST = Path("tests/fixtures/reconstruction-runtime/woolman_37311_oracle.source-manifest.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_woolman_acceptance_binds_fresh_oracle_and_requires_scoped_projection_route(tmp_path) -> None:
    from tests.runtime_candidate_baselines import current_runtime_baseline

    acceptance = _validate_acceptance_for_work(
        EDITION / "acceptance.json", root=ROOT, work_id=WORK_ID
    )
    validate_state(WORK / "state.json", root=ROOT)
    assert _sha(EDITION / "master.tei.xml") == "03d1cad51281dd3271b0f32139de2b6aa9265bde39a66a3cbb0a7a42c1f1dc3e"
    assert _sha(EDITION / "acceptance.json") == "af870ac063be83343508aa1ccf7ee4f16c32c469bdbcd5081556e5f95f41b5c0"

    retained = CandidatePackage.load(WORK / "integration/pg37311-html-v1/candidate/package")
    assert retained.sha256 == "6e550033ed5b36e2dd27dc771b52c5488393090204a1794322368d5998116590"
    source, package = current_runtime_baseline(
        root=ROOT, original_manifest=RETAINED_MANIFEST, runtime_manifest=MANIFEST,
        retained_package=retained.path, retained_sha256=retained.sha256,
        destination=tmp_path / "current-runtime",
    )
    report = validate(source, package, _oracle)
    assert report.status == "pass" and not report.findings
    changed = tmp_path / "changed-credit"
    shutil.copytree(package.path, changed)
    notice = changed / "README.source.md"
    notice.write_bytes(notice.read_bytes() + b"\nINVENTED SOURCE CREDIT\n")
    record = json.loads((changed / "manifest.json").read_bytes())
    member = next(item for item in record["members"] if item["name"] == notice.name)
    member.update(bytes=notice.stat().st_size, sha256=_sha(notice))
    (changed / "manifest.json").write_bytes((json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    with pytest.raises(ValueError, match="source attribution/scope notice differs"):
        validate(source, CandidatePackage.load(changed), _oracle)

    work = json.loads((WORK / "work.json").read_bytes())
    edition = work["textual_forms"][0]["editions"][0]
    with pytest.raises(ValueError, match="Woolman source-native route requires its exact accepted master"):
        project_document(
            EDITION / "master.tei.xml",
            identity={key: acceptance["identity"][key] for key in ("work_id", "textual_form_id", "edition_id")},
            language="en",
            representation_revision=acceptance["representation_revision"]["id"],
            edition_title=edition["title"],
            category="prose",
            _allow_acceptance_metadata=True,
        )

    receipt = json.loads((WORK / "integration/pg37311-html-v1/publication-v1/projection-receipt.json").read_bytes())
    assert receipt["status"] == "blocked"
    assert receipt["error"] == "unsupported native source block type"
    assert receipt["rows"] == 0
