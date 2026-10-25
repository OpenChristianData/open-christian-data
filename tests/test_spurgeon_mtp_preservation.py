"""Independent preservation checks for the bounded Spurgeon MTP evidence slice."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pytest
from lxml import html


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/spurgeon_mtp"
MEMBER_INVENTORY = FIXTURE_ROOT / "retained-member-inventory-v1.tsv"
OBSERVATIONS = FIXTURE_ROOT / "proof-selection-observations-v1.json"

EXPECTED_INVENTORY_SHA256 = "1e11bebdad45995675c1a03e5aef18792a2c7fcac3e4fc64e4e1fb6edc3a09fe"
EXPECTED_OBSERVATIONS_SHA256 = "6060e625d2a233b4f0f2a96688703cf7b561576c612558f0a0c42f416190d437"
EXPECTED_MEMBER_COUNT = 3_551
EXPECTED_MEMBER_BYTES = 143_873_038
EXPECTED_ABSENT_PRIMARY = [8, 40, 42, 62, 67, 82, 142, 155, 269, 270, 298, 332, 390, 708, 1698, 3032]
EXPECTED_SELECTED = {
    1: (
        "raw/spurgeon_sermons/html/1.html",
        41_601,
        "39a99f4d95ebe439d6fb232dd9d3b226039848a97fa14792d6dbf8f5698f0699",
        "The Immutability Of God",
    ),
    15: (
        "raw/spurgeon_sermons/html/15.html",
        42_689,
        "67d27cc11b0e10b937f519a40a79fd4fd405e6b2e5c6e1311384b800f3d5b068",
        "The Bible",
    ),
    317: (
        "raw/spurgeon_sermons/html/317.html",
        49_156,
        "c2e34e15ef0faf41326e067c64b49690670522edd294e43955e0151bbf03e0a4",
        "Characteristics Of Faith",
    ),
}
EXPECTED_STRUCTURE = {
    "article": 3,
    "blockquote": 13,
    "br": 31,
    "em": 0,
    "h1": 3,
    "li": 5,
    "ol": 5,
    "p": 209,
    "span": 3,
    "strong": 0,
    "code": 0,
}
EXPECTED_REFERENCES = ["Malachi 3:6", "Hosea 8:12", "John 4:48"]
EXPECTED_STRUCTURE_SHA256 = {
    1: "2c5b703da8176e080b706ee9c34eab469d08b9f993a265f00a56af9ee9bddbd1",
    15: "52830b16c7cf4489bf7f559e998df270facda4504e8b17a16a8dfcfcdfd05465",
    317: "4cbf298cc0ec189a6182cceae31a542978108c751f508f022730f377699fb5af",
}
EXPECTED_ATTACHMENT_SHA256 = {
    1: "792d337b64bf6dfad3fabc5a6442788ce23565ef89467d883be5b525ae613266",
    15: "b74cfe8aa27d59d76d53a004f450772b46ec10e34defd5a893b6c01754b7011a",
    317: "53bd318bfeb4d5570d9a9b566188c4007f9a748ef9aff2c69371a87790ff882c",
}
EXPECTED_ATTRIBUTION = [
    {
        "affiliation": "SpurgeonGems (spurgeongems.org)",
        "name": "Emmett O'Donnell",
        "role": "manuscript editor",
        "url": "http://www.spurgeongems.org/",
    },
    {
        "affiliation": "The Kingdom Collective",
        "name": "Benry Yip",
        "role": "designer",
        "url": "https://thekingdomcollective.com/spurgeon/",
    },
]


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_fixture_text(content: bytes) -> bytes:
    assert not content.startswith(b"\xef\xbb\xbf"), "fixture must not contain a UTF-8 BOM"
    if b"\r" in content:
        assert b"\r\n" in content, "fixture contains a lone CR"
        content_without_crlf = content.replace(b"\r\n", b"")
        assert b"\r" not in content_without_crlf, "fixture contains a lone CR"
        assert b"\n" not in content_without_crlf, "fixture mixes LF and CRLF"
        content = content.replace(b"\r\n", b"\n")
    assert content.endswith(b"\n"), "fixture must have exactly its canonical final newline"
    content.decode("utf-8", errors="strict")
    return content


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _article_tree(source: bytes) -> dict[str, Any]:
    document = html.document_fromstring(source)
    articles = document.xpath("//article")
    assert len(articles) == 1

    def capture(element: Any) -> dict[str, Any]:
        return {
            "tag": str(element.tag),
            "attributes": [[str(key), str(value)] for key, value in sorted(element.attrib.items())],
            "text": element.text,
            "children": [
                {"node": capture(child), "tail": child.tail} for child in element
            ],
        }

    return capture(articles[0])


def _walk(tree: dict[str, Any]):
    yield tree
    for child in tree["children"]:
        yield from _walk(child["node"])


def _node_text(tree: dict[str, Any]) -> str:
    parts = [tree["text"] or ""]
    for child in tree["children"]:
        parts.append(_node_text(child["node"]))
        parts.append(child["tail"] or "")
    return "".join(parts)


def _structure_only(tree: dict[str, Any]) -> dict[str, Any]:
    return {
        "attributes": tree["attributes"],
        "children": [_structure_only(child["node"]) for child in tree["children"]],
        "tag": tree["tag"],
    }


def _text_attachments(tree: dict[str, Any]) -> list[list[Any]]:
    attachments: list[list[Any]] = []

    def visit(node: dict[str, Any], path: str) -> None:
        attachments.append([path, "text", node["text"]])
        sibling_counts: Counter[str] = Counter()
        for child in node["children"]:
            tag = child["node"]["tag"]
            sibling_counts[tag] += 1
            child_path = f"{path}/{tag}[{sibling_counts[tag]}]"
            visit(child["node"], child_path)
            attachments.append([child_path, "tail", child["tail"]])

    visit(tree, "article[1]")
    return attachments


def _inventory_sort_key(path: str) -> tuple[int, int]:
    primary = re.fullmatch(r"raw/spurgeon_sermons/html/(\d+)\.html", path)
    if primary:
        return (0, int(primary.group(1)))
    supplemental = re.fullmatch(r"raw/spurgeon_sermons/missing/(\d+)\.html", path)
    if supplemental:
        return (1, int(supplemental.group(1)))
    if path == "raw/spurgeon_sermons/request_log.csv":
        return (2, 0)
    raise AssertionError(f"unexpected retained member path: {path}")


def _parse_inventory(content: bytes) -> list[tuple[str, int, str]]:
    canonical = _canonical_fixture_text(content)
    assert _sha(canonical) == EXPECTED_INVENTORY_SHA256
    lines = canonical.decode("utf-8").splitlines()
    assert lines[0] == "logical_path\tbyte_count\tsha256"
    rows: list[tuple[str, int, str]] = []
    for line in lines[1:]:
        fields = line.split("\t")
        assert len(fields) == 3
        path, byte_count, digest = fields
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        rows.append((path, int(byte_count), digest))
    assert len(rows) == EXPECTED_MEMBER_COUNT
    assert len({path for path, _, _ in rows}) == EXPECTED_MEMBER_COUNT
    assert sum(size for _, size, _ in rows) == EXPECTED_MEMBER_BYTES
    assert rows == sorted(rows, key=lambda row: _inventory_sort_key(row[0]))
    assert sum(path.startswith("raw/spurgeon_sermons/html/") for path, _, _ in rows) == 3_547
    assert sum(path.startswith("raw/spurgeon_sermons/missing/") for path, _, _ in rows) == 3
    assert rows[-1][0] == "raw/spurgeon_sermons/request_log.csv"
    return rows


def _validate_observations(document: dict[str, Any]) -> None:
    assert document["contract"] == "spurgeon-mtp-proof-selection-observations-v1"
    assert document["retained_authority"] == {
        "inventory": "tests/fixtures/spurgeon_mtp/retained-member-inventory-v1.tsv",
        "inventory_sha256": EXPECTED_INVENTORY_SHA256,
        "member_count": EXPECTED_MEMBER_COUNT,
        "primary_absent_sermon_numbers": EXPECTED_ABSENT_PRIMARY,
        "primary_member_count": 3_547,
        "supplemental_sermon_numbers": [708, 1698, 3032],
        "total_bytes": EXPECTED_MEMBER_BYTES,
    }
    assert document["source_identity"] == {
        "collection_id": "spurgeon-metropolitan-tabernacle-pulpit",
        "resource_id": "spurgeon-mtp",
        "config_byte_count": 1_855,
        "config_logical_path": "sources/sermons/spurgeon-mtp/config.json",
        "config_sha256": "9908ce5a0477b9929038db470c52148d31bbc2667a522954dffd135623465ffa",
        "source_format": "HTML",
        "source_url": "https://thekingdomcollective.com/spurgeon/",
    }
    assert document["acquisition_identity"] == {
        "byte_count": 369_195,
        "logical_path": "raw/spurgeon_sermons/request_log.csv",
        "sha256": "ffaa9fdcf1de9f75312f6a822b7e07c88de7a8e0ef684d4b686051905dfd2076",
    }
    assert document["selection_identity"] == {
        "selection_rule": (
            "lowest-numbered sermon with at least two direct article lists; "
            "lowest-numbered sermon with a nested list; and lowest-numbered "
            "sermon with no article ol/ul, deduplicated and sorted"
        ),
        "selection_sha256": "9a1cc61a2d7d119f33b08325708ca3264d759ff52e3440a0bf41c2ebbc2579a3",
        "sermon_numbers": [1, 15, 317],
    }
    assert document["attribution"] == EXPECTED_ATTRIBUTION
    assert document["rights_and_upstream"] == {
        "underlying_spurgeon_text": "public-domain",
        "transcription_digitization_formatting_rights": "unresolved",
        "upstream_repository": "unavailable",
        "claims_full_family_fidelity": False,
    }

    selected = document["selected_sermons"]
    assert [record["sermon_number"] for record in selected] == [1, 15, 317]
    counts: Counter[str] = Counter()
    references: list[str] = []
    nested_lists = 0
    for record in selected:
        expected = EXPECTED_SELECTED[record["sermon_number"]]
        assert (
            record["logical_path"],
            record["byte_count"],
            record["source_sha256"],
            record["title"],
        ) == expected, "selected identity mismatch"
        tree = record["article_tree"]
        assert _sha(_canonical(tree)) == record["article_tree_sha256"]
        sermon_number = record["sermon_number"]
        assert (
            _sha(_canonical(_structure_only(tree))) == EXPECTED_STRUCTURE_SHA256[sermon_number]
        ), "structure digest mismatch"
        assert (
            _sha(_canonical(_text_attachments(tree))) == EXPECTED_ATTACHMENT_SHA256[sermon_number]
        ), "attachment digest mismatch"
        nodes = list(_walk(tree))
        counts.update(node["tag"] for node in nodes)
        assert next(node for node in nodes if node["tag"] == "h1")
        assert _node_text(next(node for node in nodes if node["tag"] == "h1")) == record["title"]
        for node in nodes:
            if node["tag"] == "span" and ["class", "reference"] in node["attributes"]:
                references.append(_node_text(node))
            if node["tag"] == "ol":
                nested_lists += sum(
                    descendant["tag"] == "ol" for descendant in list(_walk(node))[1:]
                )
    observed_structure = {tag: counts[tag] for tag in EXPECTED_STRUCTURE}
    assert observed_structure == EXPECTED_STRUCTURE
    assert references == EXPECTED_REFERENCES
    assert nested_lists == 1
    assert document["selected_structure"] == {
        **EXPECTED_STRUCTURE,
        "nested_lists": 1,
        "scripture_references": 3,
    }
    assert document["selected_inline_carriers"] == {
        "code": 0,
        "em": 0,
        "strong": 0,
        "coverage_claim": "none",
    }


def _parse_observations(content: bytes) -> dict[str, Any]:
    canonical = _canonical_fixture_text(content)
    assert _sha(canonical) == EXPECTED_OBSERVATIONS_SHA256
    document = json.loads(canonical.decode("utf-8"))
    _validate_observations(document)
    return document


def _load_observations() -> dict[str, Any]:
    return _parse_observations(OBSERVATIONS.read_bytes())


def _verify_source_config_binding(document: dict[str, Any]) -> None:
    identity = document["source_identity"]
    content = (ROOT / identity["config_logical_path"]).read_bytes()
    assert len(content) == identity["config_byte_count"]
    assert _sha(content) == identity["config_sha256"]
    config = json.loads(content)
    assert config["collection_id"] == identity["collection_id"]
    assert config["resource_id"] == identity["resource_id"]
    assert config["source_format"] == identity["source_format"]
    assert config["source_url"] == identity["source_url"]
    assert config["contributors"] == document["attribution"]
    assert config["license"] == "public-domain"
    assert document["rights_and_upstream"]["transcription_digitization_formatting_rights"] == "unresolved"


def test_portable_preservation_fixtures_are_complete_and_internally_bound() -> None:
    rows = _parse_inventory(MEMBER_INVENTORY.read_bytes())
    document = _load_observations()
    primary_ids = {
        int(Path(path).stem)
        for path, _, _ in rows
        if path.startswith("raw/spurgeon_sermons/html/")
    }
    assert sorted(set(range(1, 3_564)) - primary_ids) == document["retained_authority"][
        "primary_absent_sermon_numbers"
    ]
    _verify_source_config_binding(document)


@pytest.mark.parametrize(
    ("path", "parser"),
    [(MEMBER_INVENTORY, _parse_inventory), (OBSERVATIONS, _parse_observations)],
    ids=["inventory", "observations"],
)
def test_fixture_hashes_accept_uniform_lf_or_crlf(
    path: Path, parser: Callable[[bytes], Any]
) -> None:
    lf_content = _canonical_fixture_text(path.read_bytes())
    assert b"\r" not in lf_content
    assert parser(lf_content) == parser(lf_content.replace(b"\n", b"\r\n"))


def _mixed_line_endings(content: bytes) -> bytes:
    return content.replace(b"\n", b"\r\n", 1)


def _lone_cr(content: bytes) -> bytes:
    return content.replace(b"\n", b"\r", 1)


@pytest.mark.parametrize(
    ("path", "parser"),
    [(MEMBER_INVENTORY, _parse_inventory), (OBSERVATIONS, _parse_observations)],
    ids=["inventory", "observations"],
)
@pytest.mark.parametrize(
    "mutator",
    [
        _mixed_line_endings,
        _lone_cr,
        lambda content: b"\xef\xbb\xbf" + content,
        lambda content: content.removesuffix(b"\n"),
        lambda content: content + b"\n",
        lambda content: content.removesuffix(b"\n") + b" \n",
        lambda content: content.replace(b"a", b"b", 1),
    ],
    ids=[
        "mixed-endings",
        "lone-cr",
        "bom",
        "missing-final-newline",
        "extra-final-newline",
        "whitespace-drift",
        "content-drift",
    ],
)
def test_fixture_text_mutations_fail_closed(
    path: Path, parser: Callable[[bytes], Any], mutator: Callable[[bytes], bytes]
) -> None:
    with pytest.raises(AssertionError):
        parser(mutator(_canonical_fixture_text(path.read_bytes())))


def test_retained_sources_match_every_inventory_member_when_available() -> None:
    rows = _parse_inventory(MEMBER_INVENTORY.read_bytes())
    existing = [(ROOT / path).exists() for path, _, _ in rows]
    if not any(existing):
        pytest.skip("ignored retained Spurgeon source is unavailable")
    assert all(existing), "retained Spurgeon authority is only partially available"
    for logical_path, expected_bytes, expected_sha in rows:
        content = (ROOT / logical_path).read_bytes()
        assert len(content) == expected_bytes, logical_path
        assert _sha(content) == expected_sha, logical_path


def test_selected_observations_match_raw_articles_when_available() -> None:
    document = _load_observations()
    paths = [ROOT / record["logical_path"] for record in document["selected_sermons"]]
    if not any(path.exists() for path in paths):
        pytest.skip("ignored retained Spurgeon source is unavailable")
    assert all(path.exists() for path in paths)
    for record, path in zip(document["selected_sermons"], paths, strict=True):
        source = path.read_bytes()
        assert len(source) == record["byte_count"]
        assert _sha(source) == record["source_sha256"]
        assert _article_tree(source) == record["article_tree"]


def _mutate_order(document: dict[str, Any]) -> None:
    children = document["selected_sermons"][0]["article_tree"]["children"]
    children[1], children[2] = children[2], children[1]


def _mutate_omission(document: dict[str, Any]) -> None:
    document["selected_sermons"][0]["article_tree"]["children"].pop()


def _mutate_invention(document: dict[str, Any]) -> None:
    document["selected_sermons"][0]["article_tree"]["children"].append(
        {"node": {"tag": "p", "attributes": [], "text": "invented", "children": []}, "tail": None}
    )


def _mutate_first_tag(document: dict[str, Any], tag: str) -> None:
    for record in document["selected_sermons"]:
        for node in _walk(record["article_tree"]):
            if node["tag"] == tag:
                node["tag"] = "mutated"
                return
    raise AssertionError(f"missing mutation target {tag}")


def _mutate_reference(document: dict[str, Any]) -> None:
    for node in _walk(document["selected_sermons"][0]["article_tree"]):
        if node["tag"] == "span":
            node["text"] = "Malachi 3:7"
            return
    raise AssertionError("missing reference mutation target")


def _mutate_attachment(document: dict[str, Any]) -> None:
    tree = document["selected_sermons"][0]["article_tree"]
    for child in tree["children"]:
        if child["tail"]:
            tree["text"] = (tree["text"] or "") + child["tail"]
            child["tail"] = None
            return
    raise AssertionError("missing attachment mutation target")


def _mutate_substitution(document: dict[str, Any]) -> None:
    document["selected_sermons"][0]["logical_path"] = document["selected_sermons"][1]["logical_path"]


def _reseal_article_tree_hashes(document: dict[str, Any]) -> None:
    for record in document["selected_sermons"]:
        record["article_tree_sha256"] = _sha(_canonical(record["article_tree"]))


@pytest.mark.parametrize(
    ("mutator", "expected_detector"),
    [
        (_mutate_order, "structure digest mismatch"),
        (_mutate_omission, "structure digest mismatch"),
        (_mutate_invention, "structure digest mismatch"),
        (lambda document: _mutate_first_tag(document, "ol"), "structure digest mismatch"),
        (_mutate_reference, "attachment digest mismatch"),
        (lambda document: _mutate_first_tag(document, "br"), "structure digest mismatch"),
        (_mutate_attachment, "attachment digest mismatch"),
        (_mutate_substitution, "selected identity mismatch"),
    ],
    ids=["order", "omission", "invention", "nesting", "reference", "break", "attachment", "substitution"],
)
def test_observation_mutations_fail_closed(
    mutator: Callable[[dict[str, Any]], None], expected_detector: str
) -> None:
    document = _load_observations()
    mutated = copy.deepcopy(document)
    mutator(mutated)
    _reseal_article_tree_hashes(mutated)
    for record in mutated["selected_sermons"]:
        assert _sha(_canonical(record["article_tree"])) == record["article_tree_sha256"]
    with pytest.raises(AssertionError, match=expected_detector):
        _validate_observations(mutated)


def test_member_substitution_fails_closed() -> None:
    content = _canonical_fixture_text(MEMBER_INVENTORY.read_bytes())
    marker = b"39a99f4d95ebe439d6fb232dd9d3b226039848a97fa14792d6dbf8f5698f0699"
    assert content.count(marker) == 1
    mutated = content.replace(marker, b"0" * 64)
    with pytest.raises(AssertionError):
        _parse_inventory(mutated)
