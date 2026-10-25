"""Focused challenges for the retained Moody PG 61883 reconstruction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree
from tests.historical_authority_mirrors import bound_callable, prepare_historical_mirror
import pytest

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from build.tei.moody_prevailing_prayer_61883_reconstruction import _oracle


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sources/manifest-acquisitions/moody-prevailing-prayer-pg61883-v2/source-manifest.json"
CANDIDATE = Path(
    r"D:\Library\Open Christian Data\candidate-reviews\moody-prevailing-prayer-pg61883-v2-candidate-v2-20261003\package"
)
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _copy_candidate(source: Path, destination: Path) -> Path:
    destination.mkdir()
    for path in source.iterdir():
        if path.is_file():
            (destination / path.name).write_bytes(path.read_bytes())
    return destination


def _rewrite_member(path: Path, name: str, raw: bytes) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member["bytes"] = len(raw)
    member["sha256"] = _sha(raw)
    (path / name).write_bytes(raw)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return CandidatePackage.load(path)


@pytest.fixture(scope="module")
def authorities(tmp_path_factory):
    mirror, path = prepare_historical_mirror(ROOT, tmp_path_factory.mktemp("moody-authorities") / "root", "moody-v2")
    source = SourceManifest.load(path, repository_root=mirror)
    oracle = bound_callable(mirror, source.record["validator"], "validator")
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(globals(), "_oracle", oracle)
        yield source, CandidatePackage.load(CANDIDATE)


def test_baseline_oracle_passes(authorities: tuple[SourceManifest, CandidatePackage]) -> None:
    source, candidate = authorities
    assert _oracle(source, candidate)["status"] == "pass"


@pytest.mark.parametrize(
    ("name", "change", "message"),
    [
        (
            "wrong-title",
            lambda tree: setattr(tree.find(f".//{{{TEI}}}titleStmt/{{{TEI}}}title"), "text", "A Short Method of Prayer"),
            "title, author, or English language linkage",
        ),
        (
            "wrong-author",
            lambda tree: setattr(tree.find(f".//{{{TEI}}}titleStmt/{{{TEI}}}author"), "text", "Jeanne Guyon"),
            "title, author, or English language linkage",
        ),
        (
            "wrong-language",
            lambda tree: tree.set(f"{{{XML}}}lang", "tl"),
            "title, author, or English language linkage",
        ),
        (
            "wrong-source-limit",
            lambda tree: setattr(tree.find(f".//{{{TEI}}}sourceDesc/{{{TEI}}}p"), "text", "1887 Tagalog translation; Spanish-language source unknown."),
            "candidate source scope or identity metadata",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_rejects_contradicted_identity_metadata(
    authorities: tuple[SourceManifest, CandidatePackage], tmp_path: Path,
    name: str, change, message: str,
) -> None:
    source, original = authorities
    changed_dir = _copy_candidate(original.path, tmp_path / name)
    tree = etree.fromstring((changed_dir / "content.tei.xml").read_bytes())
    change(tree)
    candidate = _rewrite_member(
        changed_dir,
        "content.tei.xml",
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False),
    )
    with pytest.raises(ValueError, match=message):
        _oracle(source, candidate)


def test_rejects_wrong_work_linkage(
    authorities: tuple[SourceManifest, CandidatePackage], tmp_path: Path,
) -> None:
    source, original = authorities
    changed_dir = _copy_candidate(original.path, tmp_path / "wrong-work-linkage")
    provenance = json.loads((changed_dir / "provenance.json").read_bytes())
    provenance["work_id"] = "unrelated-work"
    candidate = _rewrite_member(
        changed_dir,
        "provenance.json",
        (json.dumps(provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )
    with pytest.raises(ValueError, match="candidate linkage metadata mismatch: work_id"):
        _oracle(source, candidate)


def test_rejects_body_change_despite_resealed_package(
    authorities: tuple[SourceManifest, CandidatePackage], tmp_path: Path,
) -> None:
    source, original = authorities
    changed_dir = _copy_candidate(original.path, tmp_path / "changed-body")
    tree = etree.fromstring((changed_dir / "content.tei.xml").read_bytes())
    body = tree.find(f"{{{TEI}}}text/{{{TEI}}}body")
    assert body is not None and len(body)
    body[0].text = (body[0].text or "") + " unauthorized mutation"
    candidate = _rewrite_member(
        changed_dir,
        "content.tei.xml",
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False),
    )
    with pytest.raises(ValueError, match="candidate text differs"):
        _oracle(source, candidate)
