import hashlib
import importlib.util
import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest
from PIL import Image

from build.tools import prepare_newadvent_reconstruction as preparation
from build.tools.retain_newadvent_sources import retain
from ocd_kernel.reconstruction.contract import SourceManifest, reconstruct
from tests.test_retain_newadvent_sources import Response


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.newadvent.org/cathen/"


def test_manifest_paths_use_the_configured_storage_boundary(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    library = tmp_path / "library"
    repository.mkdir()
    (library / "raw").mkdir(parents=True)
    (library / "data").mkdir()
    (repository / ".ocd-storage.json").write_text(json.dumps({"library_root": str(library)}), encoding="utf-8")
    source = library / "raw/source.html"
    source.write_bytes(b"source")
    outside_data = library / "data/generated.json"
    outside_data.write_bytes(b"{}")
    monkeypatch.setattr(preparation, "ROOT", repository)
    assert preparation.logical(source) == "raw/source.html"
    with pytest.raises(ValueError, match="storage route"):
        preparation.logical(outside_data)


def test_partial_profile_requires_exact_failure_evidence_and_never_includes_missing_members(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    for relative in ["build/__init__.py", "build/tei/__init__.py", "build/tei/newadvent_source_tree.py", "build/tei/newadvent_css.py", "build/tei/newadvent_css_oracle.py", "ocd_kernel/__init__.py", "ocd_kernel/reconstruction/__init__.py", "ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/verifier.py", "build/tei/newadvent_reconstruction.py", "build/tei/newadvent_oracle.py", "sources/reference/catholic-encyclopedia/LIB-025.blocked-source-evidence.json", "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd", "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd", "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"]:
        target = repository / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    monkeypatch.setattr(preparation, "ROOT", repository)
    missing = BASE + "01002a.htm"
    raw = b'<html><head><title>Retained page</title></head><body><div id="springfield2"><h1>The Catholic Encyclopedia</h1><p>Only retained wording.</p><a href="01002a.htm">Missing article</a></div><div id="ogdenville"><p>Credits</p></div></body></html>'
    class Transport:
        def open(self, request, timeout):
            if request.full_url == missing:
                raise HTTPError(missing, 404, "Not Found", {}, BytesIO(b"Exact failed response"))
            response = Response(raw)
            response.geturl = lambda: request.full_url
            return response
    cohort = repository / "raw/retained"
    retain([BASE], cohort, opener=Transport(), sleeper=lambda _: None)
    failure = repository / "raw/failure"
    retain([missing], failure, opener=Transport(), sleeper=lambda _: None)
    graph = repository / "raw/graph.json"
    graph.write_text(json.dumps({"contract": "ocd-newadvent-link-census-v1", "missing_linked_indexes": [], "members": [{"url": BASE, "path": str(cohort / "000001.html"), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}], "article_urls_in_first_occurrence_order": [missing]}), encoding="utf-8")
    output = repository / "sources/current"
    output.mkdir(parents=True)
    (output / "README.source.md").write_text("Explicit partial retained cohort.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="HTML envelope is incomplete"):
        preparation.prepare(graph, [cohort], [], output, failure_cohorts=[failure])
    with pytest.raises(ValueError, match="exact failure-response evidence"):
        preparation.prepare(graph, [cohort], [], output, allow_partial_source=True)
    link_policy = output / "link-policy.json"
    link_policy.write_bytes(preparation.canonical({"contract": "ocd-lib025-newadvent-link-reconciliation-v1", "work_id": "catholic-encyclopedia-vol01", "mappings": [], "unmapped": [{"source_url": missing, "rationale": "No retained index evidence supports a repair."}]}))
    result = preparation.prepare(graph, [cohort], [], output, allow_partial_source=True, failure_cohorts=[failure], link_reconciliation_policy=link_policy)
    manifest = json.loads(Path(result["manifest"]).read_bytes())
    profile = json.loads((output / "reconstruction-profile.json").read_bytes())
    assert profile["link_reconciliation_policy_authority"] == "source-link-reconciliation-policy"
    bound_link_policy = next(row for row in manifest["authorities"] if row["name"] == profile["link_reconciliation_policy_authority"])
    assert bound_link_policy["role"] == "source-link-reconciliation-policy"
    assert bound_link_policy["sha256"] == hashlib.sha256(link_policy.read_bytes()).hexdigest()
    assert json.loads((output / "validation-policy.json").read_bytes())["profile_sha256"] == hashlib.sha256((output / "reconstruction-profile.json").read_bytes()).hexdigest()
    assert profile["expression_scope"]["status"] == "partial"
    assert profile["expression_scope"]["whole_work_complete"] is False
    assert profile["declared_envelope_retained"] is False
    assert profile["expression_scope"]["included_html_urls"] == [BASE]
    assert profile["expression_scope"]["unavailable_urls"] == [missing]
    assert [row["url"] for row in profile["html_members"]] == [BASE]
    assert manifest["failed_acquisitions"] == profile["failed_acquisitions"]
    assert len([row for row in manifest["authorities"] if row["role"] == "primary-source"]) == 1
    def load(relative, name):
        spec = importlib.util.spec_from_file_location(name, repository / relative)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    producer = load("build/tei/newadvent_reconstruction.py", "newadvent_partial_producer")
    oracle = load("build/tei/newadvent_oracle.py", "newadvent_partial_oracle")
    source_manifest = SourceManifest.load(result["manifest"], repository_root=repository)
    candidate = reconstruct(source_manifest, tmp_path / "partial-candidate", producer._convert)
    assert oracle._oracle(source_manifest, candidate)["status"] == "pass"
    assert b"Unavailable source members" in candidate.member_bytes("content.tei.xml")
    assert b'whole_work_complete":false' in candidate.member_bytes("provenance.json")
    helper = repository / "build/tei/newadvent_css.py"
    helper.write_bytes(helper.read_bytes() + b"\n# changed imported helper\n")
    refreshed = preparation.refresh_import_closures(Path(result["manifest"]))
    refreshed_record = json.loads(Path(result["manifest"]).read_bytes())
    assert refreshed["source_authorities_unchanged"] is True
    assert refreshed["manifest_sha256"] != refreshed["previous_manifest_sha256"]
    assert refreshed_record["authorities"] == manifest["authorities"]
    assert refreshed_record["expression_scope"] == manifest["expression_scope"]
    assert refreshed_record["producer_import_closure_sha256"] == preparation._producer_closure(repository)
    response_path = failure / "000001.http-error.html"
    response_path.write_bytes(b"Changed response")
    with pytest.raises(ValueError, match="authority bytes drifted"):
        preparation.refresh_import_closures(Path(result["manifest"]))
    with pytest.raises(ValueError, match="error response byte mismatch"):
        preparation.prepare(graph, [cohort], [], output, allow_partial_source=True, failure_cohorts=[failure])


@pytest.mark.parametrize("mixed_assets", [False, True])
def test_complete_package_route_binds_sources_and_rejects_missing_member(tmp_path, monkeypatch, mixed_assets):
    repository = tmp_path / "repository"
    paths = ["build/__init__.py", "build/tei/__init__.py", "build/tei/newadvent_reconstruction.py", "build/tei/newadvent_oracle.py", "build/tei/newadvent_source_tree.py", "build/tei/newadvent_css.py", "build/tei/newadvent_css_oracle.py", "ocd_kernel/__init__.py", "ocd_kernel/reconstruction/__init__.py", "ocd_kernel/reconstruction/contract.py", "ocd_kernel/reconstruction/verifier.py", "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd", "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd", "sources/reference/catholic-encyclopedia/LIB-025.blocked-source-evidence.json"]
    for relative in paths:
        target = repository / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    monkeypatch.setattr(preparation, "ROOT", repository)
    pages = {
        BASE: b'<html><head><title>Collection</title><link rel="stylesheet" href="../utility/fixture.css"></head><body><div id="springfield2"><h1>The Catholic Encyclopedia</h1><p>Original preface.</p><a href="01001a.htm">Article</a></div><div id="ogdenville"><p>Publisher credits</p></div></body></html>',
        BASE + "01001a.htm": b'<html><head><title>Article</title></head><body><div id="springfield2"><h1>Article</h1><p>Source wording &#151; retained.</p><p><img src="../images/fixture.png" alt="Fixture diagram"></p></div><div id="ogdenville"><p>Transcriber credits</p></div></body></html>',
    }
    image_url = "https://www.newadvent.org/images/fixture.png"
    stylesheet_url = "https://www.newadvent.org/utility/fixture.css"
    image_stream = BytesIO()
    Image.new("RGB", (2, 2), "white").save(image_stream, format="PNG")
    class Transport:
        def open(self, request, timeout):
            payload = image_stream.getvalue() if request.full_url == image_url else b"" if request.full_url == stylesheet_url else pages[request.full_url]
            response = Response(payload)
            response.geturl = lambda: request.full_url
            return response
    cohort = repository / "raw/cohort"
    retain(list(pages), cohort, opener=Transport(), sleeper=lambda _: None)
    image_cohort = repository / "raw/images"
    retain([image_url], image_cohort, opener=Transport(), sleeper=lambda _: None, allow_images=True)
    stylesheet_cohort = repository / "raw/stylesheets"
    retain([stylesheet_url], stylesheet_cohort, opener=Transport(), sleeper=lambda _: None, allow_stylesheets=True)
    graph = repository / "raw/graph.json"
    graph.write_text(json.dumps({"contract": "ocd-newadvent-link-census-v1", "missing_linked_indexes": [], "members": [{"url": BASE, "path": str(cohort / "000001.html"), "bytes": len(pages[BASE]), "sha256": hashlib.sha256(pages[BASE]).hexdigest()}], "article_urls_in_first_occurrence_order": [BASE + "01001a.htm"]}), encoding="utf-8")
    output = repository / "sources/current"
    output.mkdir(parents=True)
    (output / "README.source.md").write_text("Synthetic source attribution fixture.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stylesheet envelope"):
        preparation.prepare(graph, [cohort], [image_cohort], output)
    assert not (output / "catholic-encyclopedia.source-manifest.json").exists()
    if mixed_assets:
        mixed = repository / "raw/mixed-assets"
        retain([image_url, stylesheet_url], mixed, opener=Transport(), sleeper=lambda _: None, allow_images=True, allow_stylesheets=True)
        with pytest.raises(ValueError, match="Duplicate acquisition cohort"):
            preparation.prepare(graph, [cohort], [], output, asset_cohorts=[mixed, mixed])
        with pytest.raises(ValueError, match="Duplicate retained asset"):
            preparation.prepare(graph, [cohort], [image_cohort], output, asset_cohorts=[mixed])
        html_asset = repository / "raw/not-an-asset"
        retain([BASE], html_asset, opener=Transport(), sleeper=lambda _: None)
        with pytest.raises(ValueError, match="non-asset URL"):
            preparation.prepare(graph, [cohort], [], output, asset_cohorts=[mixed, html_asset])
        image_path = mixed / "000001.png"
        image_path.write_bytes(b"mutated")
        with pytest.raises(ValueError, match="Source byte mismatch"):
            preparation.prepare(graph, [cohort], [], output, asset_cohorts=[mixed])
        image_path.write_bytes(image_stream.getvalue())
        receipt_path = mixed / "acquisition.json"
        original_receipt = receipt_path.read_bytes()
        extra = json.loads(original_receipt)
        extra["members"][1].update(url="https://www.newadvent.org/utility/extra.css", final_url="https://www.newadvent.org/utility/extra.css")
        receipt_path.write_text(json.dumps(extra), encoding="utf-8")
        with pytest.raises(ValueError, match="undeclared request URL"):
            preparation.prepare(graph, [cohort], [], output, asset_cohorts=[mixed])
        receipt_path.write_bytes(original_receipt)
        # An earlier stopped batch may declare this CSS URL without attempting
        # it; its later retained witness completes the same declared envelope.
        partial = json.loads(original_receipt)
        partial["status"] = "partial"
        partial["members"][1] = {"url": stylesheet_url, "status": "not-attempted"}
        receipt_path.write_text(json.dumps(partial), encoding="utf-8")
        with pytest.raises(ValueError, match="stylesheet envelope"):
            preparation.prepare(graph, [cohort], [], output, asset_cohorts=[mixed])
        result = preparation.prepare(graph, [cohort], [], output, asset_cohorts=[mixed, stylesheet_cohort])
    else:
        result = preparation.prepare(graph, [cohort], [image_cohort], output, [stylesheet_cohort])
    manifest = SourceManifest.load(result["manifest"], repository_root=repository)
    receipt_authorities = [row for row in manifest.record["authorities"] if row["role"] == "acquisition-receipt"]
    assert len(receipt_authorities) == 3
    def load(relative, name):
        spec = importlib.util.spec_from_file_location(name, repository / relative)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    producer = load("build/tei/newadvent_reconstruction.py", "newadvent_fixture_producer")
    oracle = load("build/tei/newadvent_oracle.py", "newadvent_fixture_oracle")
    candidate = reconstruct(manifest, tmp_path / "candidate", producer._convert)
    assert oracle._oracle(manifest, candidate)["status"] == "pass"
    assert b"data:image/png;base64," in candidate.member_bytes("content.tei.xml")
    initializer = repository / "build/__init__.py"
    original_initializer = initializer.read_bytes()
    initializer.write_bytes(original_initializer + b"\n# changed package initializer\n")
    with pytest.raises(ValueError, match="validator binding/closure"):
        oracle._oracle(manifest, candidate)
    initializer.write_bytes(original_initializer)
    (cohort / "000002.html").unlink()
    with pytest.raises(FileNotFoundError):
        preparation.prepare(graph, [cohort], [image_cohort], output, [stylesheet_cohort])
