"""Focused source-bound challenges for the complete retained Moody PG 61883 book."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree
import pytest

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from build.tei.moody_prevailing_prayer_61883_v3_reconstruction import _oracle


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "sources/manifest-acquisitions/moody-prevailing-prayer-pg61883-v3/source-manifest.json"
CANDIDATE = Path(
    r"D:\Library\Open Christian Data\candidate-reviews\moody-prevailing-prayer-pg61883-v3-candidate-20261003\package\package"
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


def _rewrite_xml(original: CandidatePackage, tmp_path: Path, name: str, change) -> CandidatePackage:
    changed_dir = _copy_candidate(original.path, tmp_path / name)
    tree = etree.fromstring((changed_dir / "content.tei.xml").read_bytes())
    change(tree)
    return _rewrite_member(
        changed_dir,
        "content.tei.xml",
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False),
    )


def _remove_rend_token(element: etree._Element, token: str) -> None:
    values = (element.get("rend") or "").split()
    assert token in values
    element.set("rend", " ".join(value for value in values if value != token))


@pytest.fixture(scope="module")
def authorities() -> tuple[SourceManifest, CandidatePackage]:
    source = SourceManifest.load(SOURCE, repository_root=ROOT)
    return source, CandidatePackage.load(CANDIDATE)


def test_baseline_oracle_passes(authorities: tuple[SourceManifest, CandidatePackage]) -> None:
    source, candidate = authorities
    assert _oracle(source, candidate)["status"] == "pass"


@pytest.mark.parametrize(
    ("name", "change", "message"),
    [
        (
            "empty-alt-omitted",
            lambda tree: _remove_rend_token(tree.xpath(".//tei:graphic[@n='3.1']", namespaces={"tei": TEI})[0], "source-alt-empty"),
            "candidate text differs",
        ),
        (
            "empty-alt-attached-to-wrong-image",
            lambda tree: (
                _remove_rend_token(tree.xpath(".//tei:graphic[@n='3.1']", namespaces={"tei": TEI})[0], "source-alt-empty"),
                tree.xpath(".//tei:seg[@n='1.2']", namespaces={"tei": TEI})[0].set("rend", "source-alt-empty"),
            ),
            "candidate text differs",
        ),
        (
            "dimension-wrong-value",
            lambda tree: tree.xpath(".//tei:graphic[@n='364.1']", namespaces={"tei": TEI})[0].set("width", "26px"),
            "candidate text differs",
        ),
        (
            "dimension-wrong-image",
            lambda tree: (
                tree.xpath(".//tei:graphic[@n='364.1']", namespaces={"tei": TEI})[0].attrib.pop("width"),
                tree.xpath(".//tei:graphic[@n='364.1']", namespaces={"tei": TEI})[0].attrib.pop("height"),
                tree.xpath(".//tei:graphic[@n='357.2.1']", namespaces={"tei": TEI})[0].set("width", "25px"),
                tree.xpath(".//tei:graphic[@n='357.2.1']", namespaces={"tei": TEI})[0].set("height", "15px"),
            ),
            "candidate text differs",
        ),
        (
            "table-summary-omitted",
            lambda tree: _remove_rend_token(tree.xpath(".//tei:table[@n='21']", namespaces={"tei": TEI})[0], "source-data-summary:table"),
            "candidate text differs",
        ),
        (
            "empty-title-attached-to-wrong-node",
            lambda tree: (
                _remove_rend_token(tree.xpath(".//*[@xml:id='pg-header-heading']", namespaces={"xml": XML})[0], "source-title-empty"),
                tree.xpath(".//tei:seg[@n='1.2']", namespaces={"tei": TEI})[0].set("rend", "source-title-empty"),
            ),
            "candidate text differs",
        ),
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
def test_rejects_body_or_identity_mutations_after_reseal(
    authorities: tuple[SourceManifest, CandidatePackage], tmp_path: Path,
    name: str, change, message: str,
) -> None:
    source, original = authorities
    candidate = _rewrite_xml(original, tmp_path, name, change)
    with pytest.raises(ValueError, match=message):
        _oracle(source, candidate)


@pytest.mark.parametrize(
    ("name", "selector", "replacement", "message"),
    [
        ("wrong-dcterms-modified", ".//tei:sourceDesc//*[@type='dcterms.modified']", "2024-10-17", "source bibliographic metadata is missing or altered: dcterms.modified"),
        ("wrong-source-creator", ".//tei:sourceDesc//*[@type='dc.creator']", "Moody, Dwight Lyman", "source bibliographic metadata is missing or altered: dc.creator"),
    ],
)
def test_rejects_altered_source_head_assertions_after_reseal(
    authorities: tuple[SourceManifest, CandidatePackage], tmp_path: Path,
    name: str, selector: str, replacement: str, message: str,
) -> None:
    source, original = authorities

    def change(tree) -> None:
        node = tree.xpath(selector, namespaces={"tei": TEI})[0]
        node.text = replacement

    candidate = _rewrite_xml(original, tmp_path, name, change)
    with pytest.raises(ValueError, match=message):
        _oracle(source, candidate)


def test_rejects_missing_source_subject_after_reseal(
    authorities: tuple[SourceManifest, CandidatePackage], tmp_path: Path,
) -> None:
    source, original = authorities

    def change(tree) -> None:
        term = tree.xpath(".//tei:keywords[@scheme='source-metadata']/tei:term", namespaces={"tei": TEI})[0]
        term.getparent().remove(term)

    candidate = _rewrite_xml(original, tmp_path, "missing-source-subject", change)
    with pytest.raises(ValueError, match="source subjects are not retained"):
        _oracle(source, candidate)


def test_rejects_changed_source_rights_role_after_reseal(
    authorities: tuple[SourceManifest, CandidatePackage], tmp_path: Path,
) -> None:
    source, original = authorities

    def change(tree) -> None:
        node = tree.xpath(".//tei:seg[@type='source-dc.rights']", namespaces={"tei": TEI})[0]
        node.text = "Public domain."

    candidate = _rewrite_xml(original, tmp_path, "wrong-source-rights", change)
    with pytest.raises(ValueError, match="source-supplied rights claim"):
        _oracle(source, candidate)


def test_rejects_head_inventory_omission_after_reseal(
    authorities: tuple[SourceManifest, CandidatePackage], tmp_path: Path,
) -> None:
    source, original = authorities
    changed_dir = _copy_candidate(original.path, tmp_path / "head-inventory-omission")
    accountability = json.loads((changed_dir / "source-accountability.json").read_bytes())
    accountability["source_html_head_inventory"].pop()
    candidate = _rewrite_member(
        changed_dir,
        "source-accountability.json",
        (json.dumps(accountability, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )
    with pytest.raises(ValueError, match="source-accountability does not bind complete archive and candidate"):
        _oracle(source, candidate)


@pytest.mark.parametrize(
    ("name", "change"),
    [
        ("archive-member-omitted", lambda accountability: accountability["archive_members"].pop()),
        ("body-attribute-map-omitted", lambda accountability: accountability["source_body_attribute_mappings"].pop()),
        ("candidate-tei-hash-altered", lambda accountability: accountability.__setitem__("candidate_tei_sha256", "0" * 64)),
    ],
)
def test_rejects_incomplete_source_accountability_after_reseal(
    authorities: tuple[SourceManifest, CandidatePackage], tmp_path: Path,
    name: str, change,
) -> None:
    source, original = authorities
    changed_dir = _copy_candidate(original.path, tmp_path / name)
    accountability = json.loads((changed_dir / "source-accountability.json").read_bytes())
    change(accountability)
    candidate = _rewrite_member(
        changed_dir,
        "source-accountability.json",
        (json.dumps(accountability, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )
    with pytest.raises(ValueError, match="source-accountability does not bind complete archive and candidate"):
        _oracle(source, candidate)


def test_rejects_wrong_work_linkage_after_reseal(
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
