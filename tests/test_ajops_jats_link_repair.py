"""Contrasting retained articles prove the repaired readable link mapping."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import subprocess
import sys
import xml.etree.ElementTree as ET

from lxml import etree
import pytest

from build.tei.ajops_jats_oracle_v3 import _check_readable_links
from build.tei.durham_import_closure import digest as closure_digest
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "sources/manifest-acquisitions/ajops-vol1-2024-link-repair"

RUNTIME_CASES = {'a11': ('sources/manifest-acquisitions/ajops-vol1-2024-link-repair/a11-nyaa-motlhanka-wa-jehofa-stop-it-man-of-god-an-ubuntu-pentecostal-response-to-gender-based/source-manifest.json', '0d507aed11efe6d777d85a2caa9235e3c81b9c0c1ad2809972756e2778112eb6', 'tests/fixtures/reconstruction-runtime/ajops-v1-a11.source-manifest.json'), 'a2': ('sources/manifest-acquisitions/ajops-vol1-2024-link-repair/a2-a-new-baby-is-born/source-manifest.json', 'fc6adab880677da3d892e5ce3dd325c63f452e54de285a0f0c6c9daa4160f4f6', 'tests/fixtures/reconstruction-runtime/ajops-v1-a2.source-manifest.json'), 'a18': ('sources/manifest-acquisitions/ajops-vol1-2024-link-repair/a18-experiences-of-divorced-people-in-pentecostal-churches-in-botswana/source-manifest.json', '93e751d8ec4aa28a09b40075cf5b6827a055ffaf17138aa3b79be1393122f594', 'tests/fixtures/reconstruction-runtime/ajops-v1-a18.source-manifest.json'), 'a22': ('sources/manifest-acquisitions/ajops-vol1-2024-link-repair/a22-bring-the-whole-tithe-into-the-storehouse-the-tithe-and-sustainable-development-in-ghanaia/source-manifest.json', '0c171283a209b363c019b7d93b68992fe1466c9805180b1c5103cf5b208aa049', 'tests/fixtures/reconstruction-runtime/ajops-v1-a22.source-manifest.json')}


def _runtime_manifest(article):
    original_relative, original_sha256, runtime_relative = RUNTIME_CASES[article]
    original_raw = (ROOT / original_relative).read_bytes()
    assert sha256(original_raw).hexdigest() == original_sha256
    original = json.loads(original_raw)
    runtime_path = ROOT / runtime_relative
    runtime = json.loads(runtime_path.read_bytes())
    restored = deepcopy(runtime)
    restored["validator"]["import_closure_sha256"] = original["validator"]["import_closure_sha256"]
    assert restored == original
    assert closure_digest(ROOT, ROOT / runtime["converter"]["implementation_path"]) == runtime["producer_import_closure_sha256"]
    assert closure_digest(ROOT, ROOT / runtime["validator"]["implementation_path"]) == runtime["validator"]["import_closure_sha256"]
    return runtime_path


@pytest.mark.parametrize("article", ["a11", "a2", "a18", "a22"])
def test_retained_article_reproduction_and_readable_targets(article, tmp_path):
    manifest = _runtime_manifest(article)
    source = SourceManifest.load(manifest, repository_root=ROOT)
    source.verify()
    packages = []
    for name in ("first", "second"):
        destination = tmp_path / name
        subprocess.run([
            sys.executable, "-m", "build.tools.reconstruct_candidate",
            "--manifest", manifest.relative_to(ROOT).as_posix(),
            "--destination", str(destination), "--repository-root", str(ROOT),
        ], cwd=ROOT, check=True, capture_output=True, text=True)
        report = json.loads((destination / "validation.json").read_bytes())
        assert report["status"] == "pass"
        packages.append(CandidatePackage.load(destination / "package"))
    assert packages[0].sha256 == packages[1].sha256
    content = packages[0].member_bytes("content.tei.xml")
    original = ET.fromstring(source.authority_path("publisher-xml").read_bytes())
    tei = etree.fromstring(content)
    assert _check_readable_links(original, tei)["status"] == "pass"
    identity = tei.xpath("//*[@xml:id]")[0]
    del identity.attrib["{http://www.w3.org/XML/1998/namespace}id"]
    with pytest.raises(ValueError, match="readable source ID"):
        _check_readable_links(original, tei)
    tei = etree.fromstring(content)
    ref = tei.xpath("//*[@target]")[0]
    ref.set("target", "#" + tei.xpath("//@xml:id")[-1])
    with pytest.raises(ValueError, match="readable link destination"):
        _check_readable_links(original, tei)
    if article == "a11":
        historical = Path("D:/Library/Open Christian Data/candidate-reviews/ajops-v1-a11-nonaccepted-v2b/package/content.tei.xml")
        with pytest.raises(ValueError, match="readable source ID"):
            _check_readable_links(original, etree.fromstring(historical.read_bytes()))
        unresolved = [json.loads(line) for line in packages[0].member_bytes("unresolved.jsonl").splitlines()]
        assert any(item["category"] == "media" and item["status"] == "open" for item in unresolved)


@pytest.mark.parametrize("article", ["a11", "a2", "a18", "a22"])
def test_runtime_manifest_preserves_complete_original_source_record(article):
    runtime = _runtime_manifest(article)
    original_relative, _, _ = RUNTIME_CASES[article]
    SourceManifest.load(ROOT / original_relative, repository_root=ROOT).verify()
    SourceManifest.load(runtime, repository_root=ROOT).verify()
