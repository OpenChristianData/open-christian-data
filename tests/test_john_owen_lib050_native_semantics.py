"""Independent native semantic checks for the assigned Owen Communion work.

This module deliberately does not import the LIB-050 producer or oracle. It
derives source feature identities from a fresh source walk, then checks the
native TEI projection and feature-specific mutations.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit

from lxml import etree
import pytest

from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path


pytestmark = [pytest.mark.slow, pytest.mark.requires_local_artifacts]

ROOT = Path(__file__).resolve().parents[1]
SOURCE_RELATIVE_PATH = "raw/ccel/owen/communion.xml"
CANDIDATE_ENV = "OCD_LIB050_CANDIDATE"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI = {"tei": TEI_NS}


@dataclass
class CommunionPair:
    source_tree: etree._ElementTree
    source_body: etree._Element
    candidate_tree: etree._ElementTree
    readable: etree._Element
    source_nodes: tuple[etree._Element, ...]
    ordinals: dict[int, int]
    targets: dict[str, etree._Element]
    candidate_path: Path


def _xml_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        remove_comments=False,
        remove_pis=False,
        huge_tree=True,
    )


def _document_order(tree: etree._ElementTree) -> tuple[etree._Element, ...]:
    """Walk source nodes independently, including document-level nodes."""

    root = tree.getroot()
    before: list[etree._Element] = []
    node = root.getprevious()
    while node is not None:
        before.append(node)
        node = node.getprevious()

    ordered = list(reversed(before))

    def visit(current: etree._Element) -> None:
        ordered.append(current)
        for child in current:
            visit(child)

    visit(root)
    node = root.getnext()
    while node is not None:
        ordered.append(node)
        node = node.getnext()
    return tuple(ordered)


def _content_path(root: Path) -> Path | None:
    candidates = (
        root,
        root / "content.tei.xml",
        root / "package" / "content.tei.xml",
    )
    for candidate in candidates:
        try:
            if candidate.is_file() and (
                candidate.name == "content.tei.xml"
                or candidate.name.endswith(".tei.xml")
            ):
                return candidate
        except OSError:
            continue
    return None


def _candidate_path() -> Path:
    configured = os.environ.get(CANDIDATE_ENV)
    if not configured:
        pytest.skip(
            f"{CANDIDATE_ENV} is unset; set it to the external LIB-050 candidate "
            "root or content.tei.xml to run native semantic checks"
        )
    configured_root = Path(configured).expanduser()
    path = _content_path(configured_root)
    if path is None:
        pytest.fail(
            f"{CANDIDATE_ENV}={configured!r} does not name an accessible LIB-050 "
            "candidate root or TEI content file"
        )
    return path


def _source_path() -> Path:
    try:
        source_path = resolve_repo_path(ROOT, SOURCE_RELATIVE_PATH)
    except StorageTopologyError as exc:
        pytest.fail(
            f"retained source route {SOURCE_RELATIVE_PATH!r} is unavailable: {exc}"
        )
    if not source_path.is_file():
        pytest.skip(
            f"retained Communion source is not present at logical route "
            f"{SOURCE_RELATIVE_PATH}: {source_path}"
        )
    return source_path


def _feature_key(ordinals: dict[int, int], node: etree._Element) -> str:
    return f"#communion-node-{ordinals[id(node)]:06d}"


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


@pytest.fixture(scope="module")
def communion_pair() -> CommunionPair:
    source_path = _source_path()
    candidate_path = _candidate_path()
    source_tree = etree.parse(str(source_path), _xml_parser())
    candidate_tree = etree.parse(str(candidate_path), _xml_parser())
    source_bodies = source_tree.xpath("/ThML/ThML.body")
    if len(source_bodies) != 1:
        pytest.fail(f"expected one retained ThML.body, found {len(source_bodies)}")
    communion = candidate_tree.xpath(
        "/tei:teiCorpus/tei:TEI[@xml:id='john-owen-communion']",
        namespaces=TEI,
    )
    if len(communion) != 1:
        pytest.fail("candidate does not contain exactly one Communion TEI member")
    divisions = communion[0].xpath(
        "./tei:text/tei:body/tei:div[@type='retained-source-member']",
        namespaces=TEI,
    )
    if len(divisions) != 1:
        pytest.fail("candidate does not contain one retained-source-member division")
    readable = divisions[0].xpath(
        "./tei:div[@type='readable-transcription']", namespaces=TEI
    )
    if len(readable) != 1:
        pytest.fail(
            "candidate has no native readable-transcription; use a repaired native package"
        )

    source_nodes = tuple(source_bodies[0].iter())
    ordinals = {
        id(node): ordinal
        for ordinal, node in enumerate(_document_order(source_tree), start=1)
    }
    targets: dict[str, etree._Element] = {}
    for target in readable[0].iter():
        corresp = target.get("corresp")
        if corresp is None:
            continue
        if corresp in targets:
            pytest.fail(f"duplicate native correspondence pointer: {corresp}")
        targets[corresp] = target
    return CommunionPair(
        source_tree=source_tree,
        source_body=source_bodies[0],
        candidate_tree=candidate_tree,
        readable=readable[0],
        source_nodes=source_nodes,
        ordinals=ordinals,
        targets=targets,
        candidate_path=candidate_path,
    )


def _target_for(pair: CommunionPair, source_node: etree._Element) -> etree._Element | None:
    return pair.targets.get(_feature_key(pair.ordinals, source_node))


def _link_errors(pair: CommunionPair) -> list[str]:
    source_ids: dict[str, list[etree._Element]] = defaultdict(list)
    for node in pair.source_nodes:
        if isinstance(node.tag, str) and node.get("id"):
            source_ids[str(node.get("id"))].append(node)

    errors: list[str] = []
    referenced_fragments: set[str] = set()
    for link in pair.source_body.iter("a"):
        href = link.get("href")
        if not href:
            errors.append("link-source-href: source a has no href")
            continue
        fragment = urlsplit(href).fragment
        if not fragment:
            continue
        referenced_fragments.add(fragment)
        destinations = source_ids.get(fragment, [])
        if len(destinations) != 1:
            errors.append(
                f"link-source-fragment: {fragment!r} resolves to {len(destinations)} source IDs"
            )
            continue
        source_destination = destinations[0]
        source_ref = _target_for(pair, link)
        destination = _target_for(pair, source_destination)
        if source_ref is None:
            errors.append(f"link-carrier: missing carrier for {href!r}")
            continue
        if destination is None:
            errors.append(f"link-destination-carrier: missing carrier for #{fragment}")
            continue
        if _local(source_ref) != "ref":
            errors.append(
                f"link-carrier-tag: {href!r} became {_local(source_ref)!r}"
            )
        destination_id = destination.get(XML_ID)
        if not destination_id:
            errors.append(f"link-native-id: #{fragment} has no native xml:id")
            continue
        candidate_target = source_ref.get("target")
        parsed_target = urlsplit(candidate_target or "")
        candidate_fragment = parsed_target.fragment
        if (
            parsed_target.scheme
            or parsed_target.netloc
            or parsed_target.path
            or candidate_fragment != destination_id
        ):
            errors.append(
                f"link-target: source #{fragment} points to {candidate_fragment!r}, "
                f"expected local native id {destination_id!r}"
            )

    if not referenced_fragments:
        errors.append("link-census: Communion contains no local source fragments")
    return errors


def _stanza_errors(pair: CommunionPair) -> list[str]:
    verses = [
        node
        for node in pair.source_body.iter()
        if isinstance(node.tag, str)
        and node.tag == "verse"
        and node.get("type") == "stanza"
    ]
    errors: list[str] = []
    if len(verses) != 15:
        errors.append(f"stanza-census: expected 15 verse[type=stanza], found {len(verses)}")

    for verse in verses:
        target = _target_for(pair, verse)
        source_key = _feature_key(pair.ordinals, verse)
        if target is None:
            errors.append(f"stanza-carrier: missing carrier for {source_key}")
            continue
        if _local(target) != "lg":
            errors.append(f"stanza-tag: {source_key} became {_local(target)!r}")
        if target.get("type") != "stanza":
            errors.append(
                f"stanza-type: {source_key} has native type {target.get('type')!r}"
            )
        source_parent = verse.getparent()
        expected_parent = _target_for(pair, source_parent) if source_parent is not None else None
        if expected_parent is not None and target.getparent() is not expected_parent:
            errors.append(f"stanza-parent: {source_key} has the wrong native parent")
        expected_children = [
            _target_for(pair, child)
            for child in verse
            if isinstance(child.tag, str)
        ]
        if any(child is None for child in expected_children):
            errors.append(f"stanza-line-carrier: {source_key} has an unmapped source line")
            continue
        if list(target) != expected_children:
            errors.append(f"stanza-lines: {source_key} line order or attachment drifted")
        for child, target_child in zip(verse, target, strict=False):
            if not isinstance(child.tag, str):
                continue
            if child.tag != "l" or _local(target_child) != "l":
                errors.append(f"stanza-line-tag: {source_key} has a non-l line carrier")
    return errors


def _assert_clean(pair: CommunionPair) -> None:
    errors = _link_errors(pair) + _stanza_errors(pair)
    assert not errors, (
        f"native Communion semantic baseline is not clean for {pair.candidate_path}; "
        + "; ".join(errors[:12])
    )


def test_communion_source_local_fragments_resolve_to_native_ids(
    communion_pair: CommunionPair,
) -> None:
    errors = _link_errors(communion_pair)
    assert not errors, "; ".join(errors[:20])


def test_communion_source_stanzas_use_native_lg_and_ordered_lines(
    communion_pair: CommunionPair,
) -> None:
    errors = _stanza_errors(communion_pair)
    assert not errors, "; ".join(errors[:20])


def test_communion_native_link_and_stanza_mutations_are_rejected(
    communion_pair: CommunionPair,
) -> None:
    """Feature mutations must fail for source-derived reasons after repair."""

    _assert_clean(communion_pair)
    links = [
        node
        for node in communion_pair.source_body.iter("a")
        if urlsplit(node.get("href") or "").fragment
    ]
    assert links
    link_target = _target_for(communion_pair, links[0])
    assert link_target is not None
    old_link_target = link_target.get("target")
    link_target.set("target", "#invented-local-target")
    try:
        errors = _link_errors(communion_pair)
        assert any(error.startswith("link-target:") for error in errors), errors
    finally:
        if old_link_target is None:
            link_target.attrib.pop("target", None)
        else:
            link_target.set("target", old_link_target)

    native_link_target = link_target.get("target")
    native_parts = urlsplit(native_link_target or "")
    assert (
        native_link_target
        and not native_parts.scheme
        and not native_parts.netloc
        and not native_parts.path
        and native_parts.fragment
    )
    link_target.set("target", f"https://example.invalid/#{native_parts.fragment}")
    try:
        errors = _link_errors(communion_pair)
        assert any(error.startswith("link-target:") for error in errors), errors
    finally:
        link_target.set("target", native_link_target)

    verses = [
        node
        for node in communion_pair.source_body.iter()
        if isinstance(node.tag, str)
        and node.tag == "verse"
        and node.get("type") == "stanza"
    ]
    assert verses
    stanza_target = _target_for(communion_pair, verses[0])
    assert stanza_target is not None
    old_type = stanza_target.get("type")
    stanza_target.set("type", "verse")
    try:
        errors = _stanza_errors(communion_pair)
        assert any(error.startswith("stanza-type:") for error in errors), errors
    finally:
        if old_type is None:
            stanza_target.attrib.pop("type", None)
        else:
            stanza_target.set("type", old_type)

    other_target = next(
        _target_for(communion_pair, verse)
        for verse in verses[1:]
        if _target_for(communion_pair, verse) is not None
        and _target_for(communion_pair, verse).getparent()
        is not stanza_target.getparent()
    )
    original_parent = stanza_target.getparent()
    assert original_parent is not None
    original_index = list(original_parent).index(stanza_target)
    wrong_parent = other_target.getparent()
    assert wrong_parent is not None
    original_parent.remove(stanza_target)
    wrong_parent.insert(0, stanza_target)
    try:
        errors = _stanza_errors(communion_pair)
        assert any(error.startswith("stanza-parent:") for error in errors), errors
    finally:
        wrong_parent.remove(stanza_target)
        original_parent.insert(original_index, stanza_target)
