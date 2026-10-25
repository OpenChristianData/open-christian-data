from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest
from lxml import etree

import ocd_kernel.reconstruction.contract as contract_module
from ocd_kernel.reconstruction.contract import SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/lightfoot-colossians-philemon.source-manifest.json"
EXPECTED_SHA256 = "a97cb49964906a2c158a0444cfdc3b0daf13261620c919a90f1333a98ac0b913"
EXTERNAL_SOURCE = Path(
    "D:/Library/Open Christian Data/raw/gutenberg/commentary/"
    "lightfoot-colossians-philemon/pg50857.txt"
)

GOVERNED_LF_PATHS = (
    "sources/commentaries/lightfoot-colossians-philemon/lightfoot-colossians-philemon.source-manifest.json",
    "sources/commentaries/lightfoot-colossians-philemon/lightfoot-colossians-philemon.reconstruction-profile.json",
    "sources/commentaries/lightfoot-colossians-philemon/lightfoot-colossians-philemon.validation-policy.json",
    "sources/commentaries/lightfoot-colossians-philemon/lightfoot-colossians-philemon.source-accountability.schema.json",
    "sources/commentaries/lightfoot-colossians-philemon/README.source.md",
    "build/tei/lightfoot_colossians_philemon_reconstruction.py",
    "build/tei/lightfoot_colossians_philemon_oracle.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/reconstruction/__init__.py",
)


def test_lightfoot_manifest_authorities_materialize_as_canonical_lf() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    manifest = json.loads(MANIFEST.read_bytes())
    authority_bindings = {
        item["path"]: (item["bytes"], item["sha256"])
        for item in manifest["authorities"]
    }
    implementation_bindings = {
        manifest["converter"]["implementation_path"]: manifest["converter"][
            "implementation_sha256"
        ],
        manifest["validator"]["implementation_path"]: manifest["validator"][
            "implementation_sha256"
        ],
    }

    for relative in GOVERNED_LF_PATHS:
        assert f"{relative} text eol=lf" in attributes
        payload = (ROOT / relative).read_bytes()
        assert b"\r\n" not in payload
        if relative in authority_bindings:
            expected_bytes, expected_sha256 = authority_bindings[relative]
            assert len(payload) == expected_bytes
            assert hashlib.sha256(payload).hexdigest() == expected_sha256
        if relative in implementation_bindings:
            assert hashlib.sha256(payload).hexdigest() == implementation_bindings[relative]


def _disposable_source_mirror(tmp_path: Path) -> Path:
    mirror = tmp_path / "external-library" / "raw/gutenberg/commentary/lightfoot-colossians-philemon/pg50857.txt"
    mirror.parent.mkdir(parents=True)
    shutil.copyfile(EXTERNAL_SOURCE, mirror)
    return mirror


def _bind_disposable_source(mirror: Path):
    original = contract_module._contained

    def contained(root: Path, lexical: object, label: str) -> Path:
        if lexical == "raw/gutenberg/commentary/lightfoot-colossians-philemon/pg50857.txt":
            return mirror
        return original(root, lexical, label)

    return patch.object(contract_module, "_contained", contained)


def test_lightfoot_manifest_binds_the_pinned_witness(tmp_path: Path) -> None:
    mirror = _disposable_source_mirror(tmp_path)
    with _bind_disposable_source(mirror):
        source = SourceManifest.load(MANIFEST, repository_root=ROOT)
        authority = source.authority_path("retained-lightfoot-text")
        assert source.record["authorities"][0]["path"] == "raw/gutenberg/commentary/lightfoot-colossians-philemon/pg50857.txt"
        assert authority.read_bytes().__len__() == 1_511_463
        assert hashlib.sha256(authority.read_bytes()).hexdigest() == EXPECTED_SHA256
        assert source.record["work_id"] == "lightfoot-colossians-philemon"


def test_lightfoot_public_reconstruction_contract_is_available(tmp_path: Path) -> None:
    from build.tei.lightfoot_colossians_philemon_oracle import _oracle
    from build.tei.lightfoot_colossians_philemon_reconstruction import _convert

    mirror = _disposable_source_mirror(tmp_path)
    with _bind_disposable_source(mirror):
        source = SourceManifest.load(MANIFEST, repository_root=ROOT)
        candidate = reconstruct(source, tmp_path / "candidate", _convert)
        report = validate(source, candidate, _oracle)
    assert report.status == "pass"
    assert candidate.manifest["status"] == "nonaccepted"


@pytest.fixture(scope="module")
def lightfoot_candidate(tmp_path_factory: pytest.TempPathFactory):
    from build.tei.lightfoot_colossians_philemon_oracle import _oracle
    from build.tei.lightfoot_colossians_philemon_reconstruction import _convert

    mirror = _disposable_source_mirror(tmp_path_factory.mktemp("external"))
    binding = _bind_disposable_source(mirror)
    binding.start()
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(source, tmp_path_factory.mktemp("lightfoot") / "candidate", _convert)
    return source, candidate, _oracle


def test_lightfoot_accounts_for_every_source_line_and_delimiter(lightfoot_candidate) -> None:
    source, candidate, _ = lightfoot_candidate
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    raw = source.authority_path("retained-lightfoot-text").read_bytes()
    assert account["line_count"] == len(raw.splitlines())
    assert account["represented_count"] == account["line_count"]
    assert account["omitted_count"] == account["duplicate_count"] == account["reordered_count"] == 0
    assert len(account["crosswalk"]) == account["line_count"]
    text = candidate.member_bytes("content.tei.xml").decode("utf-8")
    assert "Transcriber’s Note:" in text
    assert "_italic_" in text
    assert "*** END OF THE PROJECT GUTENBERG EBOOK" in text


def test_lightfoot_tei_validates_against_p5(lightfoot_candidate) -> None:
    source, candidate, _ = lightfoot_candidate
    schema = etree.XMLSchema(etree.parse(str(source.authority_path("tei-p5-xsd"))))
    schema.assertValid(etree.fromstring(candidate.member_bytes("content.tei.xml")))


def test_lightfoot_oracle_rejects_resealed_crosswalk_mutation(lightfoot_candidate, tmp_path: Path) -> None:
    source, candidate, oracle = lightfoot_candidate
    destination = tmp_path / "mutated"
    shutil.copytree(candidate.path, destination)
    account_path = destination / "source-accountability.json"
    account = json.loads(account_path.read_bytes())
    account["crosswalk"][0]["text"] = "invented source reading"
    changed = (json.dumps(account, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    account_path.write_bytes(changed)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for member in manifest["members"]:
        if member["name"] == "source-accountability.json":
            member["bytes"] = len(changed)
            member["sha256"] = hashlib.sha256(changed).hexdigest()
    manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
    from ocd_kernel.reconstruction.contract import CandidatePackage

    with pytest.raises(ValueError):
        oracle(source, CandidatePackage.load(destination))


def test_lightfoot_fresh_process_reconstruction_is_byte_deterministic(tmp_path: Path) -> None:
    destination = tmp_path / "deterministic"
    destination.mkdir()
    script = (
        "from pathlib import Path; from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct; "
        "from build.tei.lightfoot_colossians_philemon_reconstruction import _convert; "
        "import sys; mirror=Path(sys.argv[2]); import ocd_kernel.reconstruction.contract as c; original=c._contained; c._contained=lambda root,lexical,label: mirror if lexical=='raw/gutenberg/commentary/lightfoot-colossians-philemon/pg50857.txt' else original(root,lexical,label); "
        "r=Path.cwd(); m=SourceManifest.load(r/'tests/fixtures/reconstruction-runtime/lightfoot-colossians-philemon.source-manifest.json',repository_root=r); "
        "reconstruct(m, Path(sys.argv[1]), _convert)"
    )
    mirror = _disposable_source_mirror(tmp_path / "mirror")
    first = subprocess.run([sys.executable, "-c", script, str(destination / "one"), str(mirror)], cwd=ROOT, check=True)
    assert first.returncode == 0
    second = subprocess.run([sys.executable, "-c", script, str(destination / "two"), str(mirror)], cwd=ROOT, check=True)
    assert second.returncode == 0
    for path in sorted((destination / "one").iterdir()):
        assert path.read_bytes() == (destination / "two" / path.name).read_bytes()
