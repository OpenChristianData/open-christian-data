"""Focused exact-source and guard checks for Practical Mysticism."""

from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import json
import sys

from lxml import etree
import pytest

from build.tools import install_practical_mysticism_current as installer
from build.tools.stage_practical_mysticism_current import DIRECT_SHA256, PACKAGE_SHA256, ROOT, source_check
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import project_document, verify_document
from ocd_kernel.tei.validate import compiled_schema
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from tests.practical_mysticism_runtime_fixture import runtime_context, ORIGINAL_STAGE, ORIGINAL_PACKAGE, MANIFEST, MANIFEST_SHA, PACKAGE_SHA



@pytest.fixture(autouse=True)
def current_runtime(tmp_path, monkeypatch):
    return runtime_context(tmp_path, monkeypatch, sys.modules[__name__])


def test_current_opf_spine_support_oracle_p5_and_native(tmp_path: Path) -> None:
    direct, source, oracle = source_check()
    assert oracle["validation_status"] == "pass"
    assert oracle["candidate_package_sha256"] == PACKAGE_SHA256
    assert oracle["direct_tei_sha256"] == DIRECT_SHA256
    assert len(source["ordered_text_members"]) == 18
    assert len(source["support_members"]) == 15
    assert source["opf"]["path"].endswith("src/epub/content.opf")
    assert {member["path"] for member in source["ordered_text_members"]}.isdisjoint(
        member["path"] for member in source["support_members"])
    assert compiled_schema().validate(etree.fromstring(direct))
    path = tmp_path / "practical-mysticism.tei.xml"
    path.write_bytes(direct)
    arguments = dict(identity={"work_id": "practical-mysticism",
                               "textual_form_id": "practical-mysticism-standard-ebooks-en",
                               "edition_id": "practical-mysticism-standard-ebooks-retained"},
                     language="en", representation_revision="1",
                     edition_title="Practical Mysticism (Standard Ebooks retained electronic witness)",
                     category="prose", _allow_acceptance_metadata=True)
    projected = project_document(path, **arguments)
    assert len(projected["rows"]) == 18
    assert verify_document(path, projected["rows"], projected["receipt"], **arguments) == []


def test_guard_is_read_only_and_receipt_mutation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    result = installer.preflight()
    assert result["status"] == "ready-for-review"
    assert result["installation"] == "not-performed"
    assert (result["text_members"], result["support_members"], result["native_rows"]) == (18, 15, 18)
    assert not (ROOT / "library/works/practical-mysticism/forms/practical-mysticism-standard-ebooks-en/editions/practical-mysticism-standard-ebooks-retained/master.tei.xml").exists()
    monkeypatch.setattr(installer, "RECEIPT_SHA256", "0" * 64)
    with pytest.raises(PipelineError, match="frozen stage path or receipt differs"):
        installer.preflight()


def test_runtime_context_preserves_original_source_package_and_stage(current_runtime):
    from build.tei.se_candidate_oracle import _oracle
    from ocd_kernel.tei.install_accepted import _files

    context = current_runtime
    assert _files(ORIGINAL_STAGE) == context["inventory"]["files"]
    original = context["original_root"] / MANIFEST
    assert sha256(original.read_bytes()).hexdigest() == MANIFEST_SHA
    retained = CandidatePackage.load(ORIGINAL_PACKAGE)
    assert retained.sha256 == PACKAGE_SHA
    original_manifest = SourceManifest.load(original, repository_root=context["original_root"])
    with pytest.raises(ValueError, match="oracle import-closure binding mismatch"):
        validate(original_manifest, retained, _oracle)
    assert context["manifest"].sha256 != MANIFEST_SHA
    assert context["package"].member_bytes("content.tei.xml") == retained.member_bytes("content.tei.xml")


def test_historical_stage_still_rejects_changed_runtime(current_runtime, monkeypatch):
    context = current_runtime
    with monkeypatch.context() as patch:
        patch.setattr(installer, "STAGE", ORIGINAL_STAGE)
        patch.setattr(installer, "STAGE_PARENT", ORIGINAL_STAGE.parent)
        patch.setattr(installer, "RECEIPT_SHA256", context["inventory"]["receipt_sha256"])
        patch.setattr(installer, "MANIFEST_SHA256", MANIFEST_SHA)
        patch.setattr(installer, "PACKAGE_SHA256", PACKAGE_SHA)
        with pytest.raises(PipelineError, match="frozen dependency changed"):
            installer.preflight()


def test_already_accepted_live_generation_is_not_acquired_preimage(current_runtime, monkeypatch):
    context = current_runtime
    work = context["original_root"] / "library/works/practical-mysticism"
    before = {p: (work / p).read_bytes() for p in ("work.json", "state.json")}
    with monkeypatch.context() as patch:
        patch.setattr(installer, "ROOT", context["original_root"])
        with pytest.raises(PipelineError, match="acquired preimage or staged generation differs"):
            installer.preflight()
    assert all((work / p).read_bytes() == b for p, b in before.items())


def test_real_current_oracle_rejects_resealed_source_text_change(current_runtime):
    context = current_runtime
    package = context["package"]
    content_path = package.path / "content.tei.xml"
    tree = etree.parse(str(content_path))
    paragraph = tree.xpath("//tei:text//tei:p", namespaces={"tei": "http://www.tei-c.org/ns/1.0"})[0]
    paragraph.text = (paragraph.text or "") + " invented wording"
    changed = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    content_path.write_bytes(changed)
    record_path = package.path / "manifest.json"
    record = json.loads(record_path.read_bytes())
    member = next(row for row in record["members"] if row["name"] == "content.tei.xml")
    member.update(bytes=len(changed), sha256=sha256(changed).hexdigest())
    record_path.write_bytes((json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    with pytest.raises(ValueError, match="SE oracle:"):
        validate(context["manifest"], CandidatePackage.load(package.path), context["oracle"])
