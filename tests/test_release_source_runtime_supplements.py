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


def test_joshua_current_runtime_rejects_dependency_and_supplement_mutations(monkeypatch, tmp_path):
    from ocd_kernel.projection.categories import calvin_joshua_source_native as route

    profile = next((ROOT / "library/works/calvin-commentary-on-joshua").glob("forms/*/editions/*/projection/*/profile.json"))
    historical = ROOT / route.CURRENT_RUNTIME_SUPPLEMENT
    raw = historical.read_bytes()
    assert sha256(raw).hexdigest() == route.CURRENT_RUNTIME_SUPPLEMENT_SHA
    with pytest.raises(PipelineError, match="dependency changed: ocd_kernel/lib/storage_topology.py"):
        route._current_runtime({"root": ROOT}, profile)
    retained = json.loads(raw)
    current = deepcopy(retained)
    storage = "ocd_kernel/lib/storage_topology.py"
    runtime_paths = (storage, "ocd_kernel/tei/acceptance.py")
    for logical in runtime_paths:
        current["runtime_and_schema_sha256"][logical] = route._sha(ROOT / logical)
    restored = deepcopy(current)
    for logical in runtime_paths:
        restored["runtime_and_schema_sha256"][logical] = retained["runtime_and_schema_sha256"][logical]
    assert restored == retained
    for logical, expected in retained["preserved_sha256"].items():
        assert route._sha(ROOT / logical) == expected
    runtime_bytes = {}
    for logical, expected in current["runtime_and_schema_sha256"].items():
        content = (ROOT / logical).read_bytes()
        if logical == "schemas/v2/categories/commentary.schema.json" and sha256(content).hexdigest() != expected:
            # The frozen proof binds this schema's CRLF bytes, not new schema content.
            content = content.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            assert json.loads(content) == json.loads((ROOT / logical).read_bytes())
        assert sha256(content).hexdigest() == expected, logical
        runtime_bytes[logical] = content
    for logical in {*current["preserved_sha256"], *current["runtime_and_schema_sha256"], profile.relative_to(ROOT).as_posix()}:
        destination = tmp_path / logical
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(runtime_bytes[logical] if logical in runtime_bytes else (ROOT / logical).read_bytes())
    supplement_path = tmp_path / route.CURRENT_RUNTIME_SUPPLEMENT
    supplement_path.parent.mkdir(parents=True, exist_ok=True)
    supplement_path.write_bytes((json.dumps(current, sort_keys=True, separators=(",", ":")) + "\n").encode())
    monkeypatch.setattr(route, "CURRENT_RUNTIME_SUPPLEMENT_SHA", route._sha(supplement_path))
    profile = tmp_path / profile.relative_to(ROOT)
    metadata = {"root": tmp_path}
    assert set(route._current_runtime(metadata, profile)) == route.DEPENDENCIES
    original = route._sha
    dependency = (tmp_path / storage).resolve()
    monkeypatch.setattr(route, "_sha", lambda path: "0" * 64 if path == dependency else original(path))
    with pytest.raises(PipelineError, match="dependency changed: ocd_kernel/lib/storage_topology.py"):
        route._current_runtime(metadata, profile)
    supplement = supplement_path.resolve()
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
