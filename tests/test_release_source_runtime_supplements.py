"""Current proofs preserve exact accepted texts and reject stale or corrupt input."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei import acceptance

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("work_id", ["watson-beatitudes", "watson-divine-contentment"])
def test_watson_supplement_binds_unchanged_acceptance(work_id):
    path = next((ROOT / "library/works" / work_id).glob("forms/*/editions/*/acceptance.json"))
    record = json.loads(path.read_bytes())
    acceptance._check_runtime_supplement(record, ROOT, work_id)
    changed = deepcopy(record)
    changed["decision"]["source_local_disposition"] += " changed"
    with pytest.raises(PipelineError, match="binds another acceptance"):
        acceptance._check_runtime_supplement(changed, ROOT, work_id)


@pytest.mark.parametrize("work_id", ["watson-beatitudes", "watson-divine-contentment"])
def test_watson_unchanged_oracle_rejects_resealed_content(work_id, tmp_path, monkeypatch):
    from build.tools.reconstruct_candidate import _bound_callable
    from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate
    from lxml import etree

    from importlib import import_module
    from tests.watson_public_runtime_fixture import current_installed_acceptance
    route_name = "prepare_watson_beatitudes_rebind" if work_id == "watson-beatitudes" else "prepare_watson_divine_contentment_rebind"
    route = import_module("build.tools." + route_name)
    proof_root = tmp_path / "installed-proof"
    current_installed_acceptance(route, proof_root, monkeypatch)
    prefix = "BEATITUDES_ACCEPTANCE" if work_id == "watson-beatitudes" else "DIVINE_CONTENTMENT"
    manifest_path = proof_root / getattr(acceptance, prefix + "_MANIFEST")
    source = SourceManifest.load(manifest_path, repository_root=proof_root)
    original = proof_root / getattr(acceptance, prefix + "_EVIDENCE")
    package = tmp_path / "package"
    try:
        shutil.copytree(original, package)
        content = package / "content.tei.xml"
        tree = etree.fromstring(content.read_bytes())
        paragraph = tree.find("{http://www.tei-c.org/ns/1.0}text/.//{http://www.tei-c.org/ns/1.0}p")
        paragraph.text = (paragraph.text or "") + " INVENTED WORDS"
        content.write_bytes(etree.tostring(tree, encoding="utf-8", xml_declaration=True))
        package_manifest = package / "manifest.json"
        record = json.loads(package_manifest.read_bytes())
        member = next(item for item in record["members"] if item["name"] == "content.tei.xml")
        member.update(bytes=content.stat().st_size, sha256=sha256(content.read_bytes()).hexdigest())
        package_manifest.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        oracle = _bound_callable(proof_root, source.record["validator"], role="validator")
        with pytest.raises(ValueError) as failure:
            validate(source, CandidatePackage.load(package), oracle)
        assert "bytes drifted" not in str(failure.value)
    finally:
        if package.exists():
            shutil.rmtree(package)


def test_joshua_current_runtime_rejects_dependency_and_supplement_mutations(monkeypatch):
    from ocd_kernel.projection.categories import calvin_joshua_source_native as route

    profile = next((ROOT / "library/works/calvin-commentary-on-joshua").glob("forms/*/editions/*/projection/*/profile.json"))
    metadata = {"root": ROOT}
    assert set(route._current_runtime(metadata, profile)) == route.DEPENDENCIES
    original = route._sha
    dependency = (ROOT / "ocd_kernel/lib/storage_topology.py").resolve()
    monkeypatch.setattr(route, "_sha", lambda path: "0" * 64 if path == dependency else original(path))
    with pytest.raises(PipelineError, match="dependency changed: ocd_kernel/lib/storage_topology.py"):
        route._current_runtime(metadata, profile)
    supplement = (ROOT / route.CURRENT_RUNTIME_SUPPLEMENT).resolve()
    monkeypatch.setattr(route, "_sha", lambda path: "0" * 64 if path == supplement else original(path))
    with pytest.raises(PipelineError, match="current runtime supplement differs"):
        route._current_runtime(metadata, profile)


@pytest.mark.parametrize("language", ["en", "eng"])
def test_pg20476_english_aliases_preserve_rows_and_source_check(language):
    from ocd_kernel.projection.categories import pg20476_hymns as route

    work = ROOT / "library/works/hymns-for-christian-devotion"
    accepted_path = next(work.glob("forms/*/editions/*/acceptance.json"))
    accepted = json.loads(accepted_path.read_bytes())
    context = dict(retained_path=ROOT / route.SOURCE_PATH, identity=accepted["identity"], language=language,
                   representation_revision=accepted["representation_revision"]["id"], edition_title="Fixture")
    result = route.project_pg20476_document(accepted_path.parent / "master.tei.xml", **context)
    assert len(result["rows"]) == 1008
    assert {row["language"] for row in result["rows"]} == {"eng"}
    assert route.verify_pg20476_document(accepted_path.parent / "master.tei.xml", result["rows"], result["receipt"], **context) == []
    context["language"] = "fra"
    with pytest.raises(PipelineError, match="retained source identity differs"):
        route.project_pg20476_document(accepted_path.parent / "master.tei.xml", **context)
