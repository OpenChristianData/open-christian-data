"""Focused independent checks for the Lightfoot typography oracle."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import re
import sys

import pytest
from lxml import etree


EXECUTION = Path(__file__).resolve().parents[1]
SOURCE_PATH = (
    EXECUTION
    / "raw/gutenberg/commentary/lightfoot-colossians-philemon/pg50857.txt"
)
ORACLE_PATH = EXECUTION / "build/tei/lightfoot_typography_oracle.py"
PRODUCER_PATH = EXECUTION / "build/tei/lightfoot_typography.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def oracle():
    return _load("lightfoot_typography_oracle_test", ORACLE_PATH)


@pytest.fixture(scope="module")
def producer():
    return _load("lightfoot_typography_producer_test", PRODUCER_PATH)


@pytest.fixture(scope="module")
def lines() -> list[str]:
    return SOURCE_PATH.read_bytes().decode("utf-8-sig").splitlines()


def _tree(oracle, lines: list[str]) -> etree._Element:
    root = etree.Element(f"{{{oracle.TEI}}}TEI", nsmap={None: oracle.TEI})
    body = etree.SubElement(root, f"{{{oracle.TEI}}}body")
    for number, value in enumerate(lines, 1):
        carrier = etree.SubElement(
            body,
            f"{{{oracle.TEI}}}seg",
            n=str(number),
            type=oracle.SOURCE_LINE_TYPE,
        )
        if number == 1:
            # Keep a non-typographic ref with text on both sides of the child;
            # this exercises the oracle's ref/seg preservation contract.
            carrier.text = value[:7]
            ref = etree.SubElement(
                carrier,
                f"{{{oracle.TEI}}}ref",
                type="source-probe",
                target="#source-probe",
            )
            ref.text = value[7:15]
            ref.tail = value[15:]
        else:
            carrier.text = value
    return root


@pytest.fixture(scope="module")
def marked_tree(oracle, producer, lines: list[str]) -> etree._Element:
    root = _tree(oracle, lines)
    producer.apply_typography(root, lines)
    return root


def _his(oracle, root: etree._Element) -> list[etree._Element]:
    return list(root.iter(f"{{{oracle.TEI}}}hi"))


def _xml_id(oracle, node: etree._Element) -> str:
    value = node.get(f"{{{oracle.XML}}}id")
    assert value
    return value


def test_source_inventory_is_independently_pinned(oracle, lines: list[str]) -> None:
    census = oracle.source_census(lines)
    assert census["source_sha256"] == oracle.SOURCE_SHA256
    assert census["source_bytes"] == oracle.SOURCE_BYTES == 1_511_463
    assert census["line_count"] == oracle.SOURCE_LINE_COUNT == 26_185
    assert census["span_count"] == 4_192
    assert census["part_count"] == 4_488
    assert census["cross_line_span_count"] == 284
    assert census["counts"] == {
        "blackletter": 1,
        "emphasis": 2,
        "italic": 3_408,
        "letter-spaced": 261,
        "source-underscore-emphasis": 3,
        "subscript": 150,
        "superscript": 272,
        "uncial": 95,
    }
    assert census["underscore_role_counts"] == {
        "italic": 3_408,
        "letter-spaced": 261,
        "source-underscore-emphasis": 3,
    }
    assert census["literal_counts"] == {
        "bare_manuscript_subscripts": 39,
        "literal_caret_kinds": {"greek-letter": 3},
        "literal_nonnumeric_carets": 3,
        "nonnumeric_caret_kinds": {
            "ascii-letter": 69,
            "braced-nonnumeric": 15,
            "greek-letter": 3,
            "star": 21,
        },
        "nonnumeric_caret_rendered": 105,
        "nonnumeric_carets": 108,
        "numeric_caret_tokens": 167,
        "quoted_underscore_mentions": 2,
        "standalone_equals": 11,
        "total_caret_tokens": 275,
    }

    spans = oracle.discover_source_spans(lines)
    by_location = {
        (
            span["start_line"],
            span["start_char"],
            span["end_line"],
            span["end_char"],
        ): span
        for span in spans
    }
    assert by_location[(37, 64, 38, 8)]["rend"] == "letter-spaced"
    assert by_location[(37, 64, 38, 8)]["text"] == "_μου\nγίνεσθε_"
    blackletter = by_location[(54, 49, 55, 5)]
    assert blackletter["rend"] == "blackletter"
    assert blackletter["text"] == "=blackletter\ntext="
    uncial = by_location[(20_655, 3, 20_655, 65)]
    assert uncial["rend"] == "uncial"
    assert uncial["text"].count("\\") == 12
    assert by_location[(248, 10, 248, 37)]["rend"] == "source-underscore-emphasis"
    assert by_location[(19108, 22, 19108, 50)]["rend"] == "source-underscore-emphasis"
    assert by_location[(19188, 61, 19189, 31)]["rend"] == "source-underscore-emphasis"

    literal_carets = census["literals"]["literal_carets"]
    assert len(literal_carets) == 3
    assert [item["category"] for item in literal_carets] == [
        "greek-letter",
        "greek-letter",
        "greek-letter",
    ]


def test_oracle_accepts_current_producer_and_normalizes_private_clone(
    oracle,
    marked_tree: etree._Element,
    lines: list[str],
) -> None:
    before = etree.tostring(marked_tree, encoding="utf-8")
    normalized = oracle.verify_and_normalize_typography(marked_tree, lines)

    assert normalized is not marked_tree
    assert etree.tostring(marked_tree, encoding="utf-8") == before
    assert len(_his(oracle, marked_tree)) == 4_488
    assert not _his(oracle, normalized)

    original_carriers = marked_tree.xpath('.//*[@type="source-line"]')
    normalized_carriers = normalized.xpath('.//*[@type="source-line"]')
    assert len(original_carriers) == len(normalized_carriers) == 26_185
    assert ["".join(node.itertext()) for node in normalized_carriers] == lines

    original_ref = marked_tree.xpath(
        ".//t:ref", namespaces={"t": oracle.TEI}
    )[0]
    normalized_ref = normalized.xpath(
        ".//t:ref", namespaces={"t": oracle.TEI}
    )[0]
    assert normalized_ref.attrib == original_ref.attrib
    assert "".join(normalized_ref.itertext()) == "".join(original_ref.itertext())
    assert normalized_ref.getparent().get("n") == "1"


def _first_hi_with(oracle, root: etree._Element, predicate):
    for node in _his(oracle, root):
        if predicate(node):
            return node
    raise AssertionError("no matching native hi")


@pytest.mark.parametrize(
    "mutation",
    ["missing", "offset", "role", "wrong-link", "orphan-base", "carrier"],
)
def test_oracle_rejects_structural_and_source_mutations(
    oracle,
    marked_tree: etree._Element,
    lines: list[str],
    mutation: str,
) -> None:
    root = deepcopy(marked_tree)
    his = _his(oracle, root)
    if mutation == "missing":
        node = his[0]
        node.getparent().remove(node)
    elif mutation == "offset":
        node = his[0]
        match = re.fullmatch(r"(\d+):(\d+)-(\d+)", node.get("n", ""))
        assert match
        line, start, end = (int(value) for value in match.groups())
        node.set("n", f"{line}:{start + 1}-{end}")
    elif mutation == "role":
        node = _first_hi_with(
            oracle,
            root,
            lambda candidate: candidate.get("n") == "37:64-68",
        )
        node.set("rend", "italic")
    elif mutation == "wrong-link":
        node = _first_hi_with(
            oracle,
            root,
            lambda candidate: candidate.get("corresp") is not None,
        )
        own_target = node.get("corresp")[1:]
        wrong_target = (
            "lightfoot-typography-000001"
            if own_target != "lightfoot-typography-000001"
            else "lightfoot-typography-000002"
        )
        node.set("corresp", f"#{wrong_target}")
    elif mutation == "orphan-base":
        node = _first_hi_with(
            oracle,
            root,
            lambda candidate: candidate.get("corresp") is None
            and any(
                other.get("corresp")
                == f"#{candidate.get(f'{{{oracle.XML}}}id')}"
                for other in _his(oracle, root)
            ),
        )
        original_target = _xml_id(oracle, node)
        node.set(f"{{{oracle.XML}}}id", "lightfoot-typography-999999")
        node.set("corresp", f"#{original_target}")
    elif mutation == "carrier":
        carrier = root.xpath('.//*[@type="source-line"]')[0]
        carrier.text = (carrier.text or "") + "x"
    else:
        raise AssertionError(mutation)

    with pytest.raises(ValueError):
        oracle.verify_and_normalize_typography(root, lines)


def test_oracle_allows_valid_alternate_fragmentation(
    oracle,
    marked_tree: etree._Element,
    lines: list[str],
) -> None:
    root = deepcopy(marked_tree)
    node = _first_hi_with(
        oracle,
        root,
        lambda candidate: candidate.get("corresp") is None
        and len(candidate) == 0
        and len(candidate.text or "") >= 4,
    )
    raw_n = node.get("n")
    assert raw_n
    match = re.fullmatch(r"(\d+):(\d+)-(\d+)", raw_n)
    assert match
    line, start, end = (int(value) for value in match.groups())
    midpoint = start + len(node.text or "") // 2
    assert start < midpoint < end
    original_tail = node.tail
    node.text, node.tail = (node.text or "")[: midpoint - start], None
    node.set("n", f"{line}:{start}-{midpoint}")
    continuation = etree.Element(node.tag)
    continuation.set(f"{{{oracle.XML}}}id", _xml_id(oracle, node) + "-alternate")
    continuation.set("rend", node.get("rend"))
    continuation.set("corresp", "#" + _xml_id(oracle, node))
    continuation.set("n", f"{line}:{midpoint}-{end}")
    # Restore the second half from the retained source interval.
    source_value = lines[line - 1]
    continuation.text = source_value[midpoint:end]
    continuation.tail = original_tail
    node.addnext(continuation)

    normalized = oracle.verify_and_normalize_typography(root, lines)
    assert not _his(oracle, normalized)
    assert ["".join(item.itertext()) for item in normalized.xpath('.//*[@type="source-line"]')] == lines
