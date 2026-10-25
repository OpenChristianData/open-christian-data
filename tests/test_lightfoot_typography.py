"""Focused tests for the isolated Lightfoot typography post-pass."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from collections import Counter

import pytest
from lxml import etree


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "raw/gutenberg/commentary/lightfoot-colossians-philemon/pg50857.txt"


def _load():
    path = ROOT / "build/tei/lightfoot_typography.py"
    spec = importlib.util.spec_from_file_location("lightfoot_typography_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def typography():
    return _load()


def _tree(module, lines: list[str]) -> etree._Element:
    root = etree.Element(f"{{{module.TEI}}}TEI", nsmap={None: module.TEI})
    body = etree.SubElement(root, f"{{{module.TEI}}}body")
    for number, value in enumerate(lines, 1):
        etree.SubElement(body, f"{{{module.TEI}}}seg", n=str(number), type="source-line").text = value
    return root


def test_full_source_typography_census_is_source_located(typography) -> None:
    lines = SOURCE_PATH.read_text(encoding="utf-8-sig").splitlines()
    spans = typography.discover_spans(lines)
    counts: dict[str, int] = {}
    for span in spans:
        counts[str(span["rend"])] = counts.get(str(span["rend"]), 0) + 1
    assert len(spans) == 4_192
    assert counts == {
        "blackletter": 1,
        "emphasis": 2,
        "italic": 3_408,
        "letter-spaced": 261,
        "subscript": 150,
        "superscript": 272,
        "source-underscore-emphasis": 3,
        "uncial": 95,
    }
    assert sum(len(span["parts"]) for span in spans) == 4_488
    assert sum(span["start_line"] != span["end_line"] for span in spans) == 284
    non_numeric = typography._non_numeric_caret_markers(lines)
    assert len(non_numeric) == 108
    assert Counter(item["category"] for item in non_numeric) == {
        "ascii-letter": 69,
        "braced-nonnumeric": 15,
        "greek-letter": 3,
        "star": 21,
    }
    assert sum(bool(item["rendered"]) for item in non_numeric) == 105
    assert [item["line"] for item in non_numeric if not item["rendered"]] == [5_473, 12_833, 14_801]

    by_location = {
        (span["start_line"], span["start_char"], span["end_line"], span["end_char"]): span
        for span in spans
    }
    crossline_letter_spaced = by_location[(37, 64, 38, 8)]
    assert crossline_letter_spaced["rend"] == "letter-spaced"
    assert [part["text"] for part in crossline_letter_spaced["parts"]] == ["_μου", "γίνεσθε_"]
    assert crossline_letter_spaced["parts"][0]["n"] == "37:64-68"
    assert crossline_letter_spaced["parts"][1]["n"] == "38:0-8"

    mixed = by_location[(248, 10, 248, 37)]
    assert mixed["rend"] == "source-underscore-emphasis"
    assert by_location[(377, 2, 377, 16)]["rend"] == "letter-spaced"

    blackletter = by_location[(54, 49, 55, 5)]
    assert blackletter["rend"] == "blackletter"
    assert blackletter["text"] == "=blackletter\ntext="

    uncial = by_location[(20_655, 3, 20_655, 65)]
    assert uncial["rend"] == "uncial"
    assert r"\ " in uncial["text"]
    assert not any(
        span["rend"] == "spaced" and span["start_line"] == 20_655
        for span in spans
    )

    assert by_location[(35, 14, 35, 16)]["rend"] == "superscript"
    assert by_location[(35, 23, 35, 27)]["rend"] == "subscript"
    assert by_location[(1176, 62, 1176, 64)]["rend"] == "superscript"
    assert by_location[(18528, 47, 18528, 52)]["rend"] == "superscript"
    assert by_location[(91, 26, 91, 38)]["rend"] == "emphasis"
    assert by_location[(121, 28, 121, 37)]["rend"] == "emphasis"


def test_apply_preserves_existing_carriers_and_splits_source_spans(typography) -> None:
    lines = ["_alpha [2]_", "==outer _inner_==", "_first", "second_"]
    root = _tree(typography, lines)
    first = root.xpath('.//*[@n="1"]')[0]
    first.text = "_alpha "
    ref = etree.SubElement(first, f"{{{typography.TEI}}}ref", type="footnote-reference", target="#note")
    ref.text = "[2]"
    ref.tail = "_"

    inventory = typography.apply_typography(root, lines)
    assert inventory["span_count"] == 4
    assert inventory["counts"] == {"italic": 3, "uncial": 1}
    assert inventory["part_count"] == 7

    assert "".join(first.itertext()) == lines[0]
    preserved_ref = first.xpath("./t:ref", namespaces={"t": typography.TEI})[0]
    assert preserved_ref.get("type") == "footnote-reference"
    assert preserved_ref.get("target") == "#note"
    assert "".join(preserved_ref.itertext()) == "[2]"
    ref_his = first.xpath(".//t:hi", namespaces={"t": typography.TEI})
    assert [hi.get("rend") for hi in ref_his] == ["italic", "italic", "italic"]
    first_id = ref_his[0].get(f"{{{typography.XML}}}id")
    assert first_id
    assert ref_his[0].get("corresp") is None
    assert [hi.get("corresp") for hi in ref_his[1:]] == [f"#{first_id}", f"#{first_id}"]
    all_ids = {hi.get(f"{{{typography.XML}}}id") for hi in root.xpath(".//t:hi", namespaces={"t": typography.TEI})}
    assert all(target[1:] in all_ids for target in [hi.get("corresp") for hi in ref_his[1:]])
    assert [hi.get("n") for hi in ref_his] == ["1:0-7", "1:7-10", "1:10-11"]

    nested = root.xpath('.//*[@n="2"]', namespaces={"t": typography.TEI})[0]
    outer = nested.xpath("./t:hi[@rend='uncial']", namespaces={"t": typography.TEI})[0]
    inner = outer.xpath("./t:hi[@rend='italic']", namespaces={"t": typography.TEI})[0]
    assert "".join(nested.itertext()) == lines[1]
    assert "".join(outer.itertext()) == lines[1]
    assert "".join(inner.itertext()) == "_inner_"
    assert outer.get("n") == "2:0-17"
    assert inner.get("n") == "2:8-15"

    crossline = [
        hi
        for hi in root.xpath(".//t:hi", namespaces={"t": typography.TEI})
        if hi.get("rend") == "italic" and hi.get("n", "").split(":", 1)[0] in {"3", "4"}
    ]
    assert any(hi.get("n") == "3:0-6" for hi in crossline)
    assert any(hi.get("n") == "4:0-7" for hi in crossline)
    crossline_first = next(hi for hi in crossline if hi.get("n") == "3:0-6")
    crossline_continuation = next(hi for hi in crossline if hi.get("n") == "4:0-7")
    assert crossline_first.get("corresp") is None
    assert crossline_continuation.get("corresp") == f"#{crossline_first.get(f'{{{typography.XML}}}id')}"
    assert "".join(root.xpath('.//*[@n="3"]', namespaces={"t": typography.TEI})[0].itertext()) == lines[2]
    assert "".join(root.xpath('.//*[@n="4"]', namespaces={"t": typography.TEI})[0].itertext()) == lines[3]


def test_nonnumeric_carets_render_source_labels_but_keep_greek_literal(typography) -> None:
    lines = ["A^* B^c 67^{**} a^{scr}", "εἰ^ναι"]
    root = _tree(typography, lines)

    inventory = typography.apply_typography(root, lines)
    assert inventory["span_count"] == 4
    assert inventory["counts"] == {"superscript": 4}
    assert inventory["non_numeric_caret_count"] == 5
    assert sum(bool(item["rendered"]) for item in inventory["non_numeric_caret_markers"]) == 4

    first = root.xpath('.//*[@n="1"]')[0]
    rendered_tokens = [
        "".join(node.itertext())
        for node in first.xpath("./t:hi", namespaces={"t": typography.TEI})
    ]
    assert rendered_tokens == ["^*", "^c", "^{**}", "^{scr}"]
    second = root.xpath('.//*[@n="2"]')[0]
    assert not second.xpath(".//t:hi", namespaces={"t": typography.TEI})
    assert "".join(second.itertext()) == lines[1]


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (["_unclosed"], "unbalanced"),
        (["plain", "_second"], "unbalanced"),
    ],
)
def test_discover_rejects_malformed_delimiters(typography, lines, message) -> None:
    with pytest.raises(ValueError, match=message):
        typography.discover_spans(lines)


def test_apply_rejects_missing_or_changed_source_carriers(typography) -> None:
    lines = ["_one_", "two"]
    missing = _tree(typography, lines[:1])
    with pytest.raises(ValueError, match="carrier census"):
        typography.apply_typography(missing, lines)

    changed = _tree(typography, lines)
    changed.xpath('.//*[@n="1"]')[0].text = "_changed_"
    with pytest.raises(ValueError, match="text drifted"):
        typography.apply_typography(changed, lines)


def test_apply_is_fail_closed_on_reapplication(typography) -> None:
    lines = ["_one_"]
    root = _tree(typography, lines)
    typography.apply_typography(root, lines)
    with pytest.raises(ValueError, match="already applied"):
        typography.apply_typography(root, lines)
