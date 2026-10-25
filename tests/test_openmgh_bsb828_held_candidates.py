"""Source-bound checks for the eight nonaccepted bsb00000828 work candidates."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tei.openmgh_bsb828_held_oracle import _oracle
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, validate


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "plans/2026-09-22-source-preflight/openmgh-bsb828-held-candidates-20260926.json"
TEI = "{http://www.tei-c.org/ns/1.0}"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entries() -> list[dict]:
    batch = json.loads(BATCH.read_bytes())
    assert batch["contract"] == "ocd-openmgh-bsb828-held-candidate-batch-v1"
    assert batch["identity_count"] == batch["validated_candidate_count"] == 8
    return batch["works"]


def test_all_eight_exact_packages_pass_independent_source_oracle(historical_root: Path) -> None:
    oracle_path = historical_root / 'build/tei/openmgh_bsb828_held_oracle.py'
    spec = importlib.util.spec_from_file_location('build.tei._held_historical_oracle', oracle_path)
    assert spec is not None and spec.loader is not None
    historical_oracle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(historical_oracle)
    for entry in _entries():
        manifest = SourceManifest.load(historical_root / entry["manifest_path"], repository_root=historical_root)
        package = CandidatePackage.load(Path(entry["candidate_root"]) / "package")
        assert manifest.sha256 == entry["manifest_sha256"]
        assert package.sha256 == entry["candidate_sha256"]
        assert _sha(Path(entry["candidate_root"]) / "package/content.tei.xml") == entry["candidate_tei_sha256"]
        assert validate(manifest, package, historical_oracle._oracle).status == "pass"
        assert entry["acceptance_status"] == "nonaccepted"


@pytest.mark.parametrize(
    ("work_id", "mutate"),
    [
        ("manegold-to-gebhard", "omit-part"),
        ("osnabruck-t-letter-presenting-wido-excerpts", "invent-line"),
        ("peter-damian-liber-gratissimus", "change-word"),
    ],
)
def test_oracle_rejects_source_body_mutations(work_id: str, mutate: str, historical_root: Path) -> None:
    entry = next(item for item in _entries() if item["work_id"] == work_id)
    manifest = SourceManifest.load(historical_root / entry["manifest_path"], repository_root=historical_root)
    package = CandidatePackage.load(Path(entry["candidate_root"]) / "package")
    tree = etree.fromstring(package.member_bytes("content.tei.xml"))
    body = tree.find(f"{TEI}text/{TEI}body/{TEI}div")
    assert body is not None
    if mutate == "omit-part":
        assert len(body) == 1
        body.remove(body[0])
    elif mutate == "invent-line":
        ab = body.find(f"{TEI}ab")
        assert ab is not None
        etree.SubElement(ab, f"{TEI}lb", n="invented")
    else:
        ab = body.find(f"{TEI}ab")
        assert ab is not None
        ab[0].tail = "Invented replacement wording.\n"
    changed = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    assert changed != package.member_bytes("content.tei.xml")

    class MutatedPackage:
        sha256 = package.sha256

        @staticmethod
        def verify_integrity() -> None:
            pass

        @staticmethod
        def member_bytes(name: str) -> bytes:
            return changed if name == "content.tei.xml" else package.member_bytes(name)

    with pytest.raises(ValueError, match="candidate readable body differs"):
        _oracle(manifest, MutatedPackage())


@pytest.fixture(scope="module")
def historical_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("held-candidate-historical")
    # This original accepted stage contains the exact shared code/source closure
    # used when the eight original candidate records were produced.
    stage = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb828-held-stages-20260926/manegold-to-gebhard")
    from ocd_kernel.tei.install_accepted import _files, _io_path
    for relative in _files(stage):
        if relative.startswith("library/works/"):
            continue
        payload = _io_path(stage / relative).read_bytes()
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    fixture_home = ROOT / "tests/fixtures/openmgh-historical-sidecars"
    for entry in _entries():
        work_id = entry["work_id"]
        prior = fixture_home / work_id
        manifest_raw = ((prior / "manifest-before.json").read_bytes() if prior.is_dir()
                        else (ROOT / entry["manifest_path"]).read_bytes())
        assert hashlib.sha256(manifest_raw).hexdigest() == entry["manifest_sha256"]
        record = json.loads(manifest_raw)
        manifest_path = root / entry["manifest_path"]
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(manifest_raw)
        profile = None
        for authority in record["authorities"]:
            logical = Path(authority["path"])
            if authority["name"] == "work-sidecar":
                payload = ((prior / "work/work.json").read_bytes() if prior.is_dir()
                           else (ROOT / logical).read_bytes())
                if hashlib.sha256(payload).hexdigest() != authority["sha256"]:
                    work = json.loads(payload)
                    edition = work["textual_forms"][0]["editions"][0]
                    assert edition.pop("category") == "prose"
                    assert edition.pop("language") == "la"
                    payload = (json.dumps(work, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
            elif authority["name"] == "reconstruction-profile":
                payload = ((prior / "profile-before.json").read_bytes() if prior.is_dir()
                           else (ROOT / logical).read_bytes())
                profile = json.loads(payload)
            else:
                current = root / logical
                payload = current.read_bytes() if current.is_file() and _sha(current) == authority["sha256"] else (ROOT / logical).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == authority["sha256"]
            assert len(payload) == authority["bytes"]
            target = root / logical
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        assert profile is not None
        logical = Path(profile["acquisition_path"])
        relative = logical.relative_to(Path("library/works") / work_id)
        payload = ((prior / "work" / relative).read_bytes() if prior.is_dir()
                   else (ROOT / logical).read_bytes())
        assert hashlib.sha256(payload).hexdigest() == profile["acquisition_sha256"]
        target = root / logical
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        SourceManifest.load(manifest_path, repository_root=root)
    return root


def test_historical_work_authority_still_rejects_mutation(historical_root: Path) -> None:
    entry = _entries()[0]
    manifest_path = historical_root / entry["manifest_path"]
    record = json.loads(manifest_path.read_bytes())
    authority = next(a for a in record["authorities"] if a["name"] == "work-sidecar")
    work = historical_root / authority["path"]
    original = work.read_bytes()
    try:
        work.write_bytes(original + b" ")
        with pytest.raises(ValueError, match="work-sidecar authority"):
            SourceManifest.load(manifest_path, repository_root=historical_root)
    finally:
        work.write_bytes(original)
