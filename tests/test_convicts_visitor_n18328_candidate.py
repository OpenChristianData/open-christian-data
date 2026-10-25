"""Focused source-fidelity checks for the held N18328 TEI candidate."""

from __future__ import annotations

from copy import deepcopy
import subprocess
import sys

import pytest
from lxml import etree as ET

from build.tei.convicts_visitor_n18328_check import (
    CANDIDATE, NS, ROOT, SOURCE, check_candidate_bytes,
)
from ocd_kernel.tei.validate import validate_file


def _mutated_text(change) -> bytes:
    root = ET.fromstring(CANDIDATE.read_bytes())
    text = root.find(NS + "text")
    assert text is not None
    change(text)
    return ET.tostring(root, encoding="utf-8")


def test_complete_candidate_matches_retained_source_and_p5() -> None:
    result = check_candidate_bytes(SOURCE.read_bytes(), CANDIDATE.read_bytes())
    assert result["status"] == "pass"
    assert result["source_feature_counts"]["sp"] == 115
    assert result["source_feature_counts"]["pb"] == 89
    assert validate_file(CANDIDATE) == []


def test_fresh_process_reproduces_candidate() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "build.tei.convicts_visitor_n18328_candidate", "--check"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert '"status": "pass"' in completed.stdout


def test_changed_words_are_rejected() -> None:
    def change(text: ET.Element) -> None:
        paragraph = next(node for node in text.iter(NS + "p") if node.text and node.text.strip())
        paragraph.text = paragraph.text + " invented"

    with pytest.raises(ValueError, match="source text/order differs"):
        check_candidate_bytes(SOURCE.read_bytes(), _mutated_text(change))


def test_removed_page_marker_is_rejected() -> None:
    def change(text: ET.Element) -> None:
        marker = next(text.iter(NS + "pb"))
        parent = next(node for node in text.iter() if marker in node)
        parent.remove(marker)

    with pytest.raises(ValueError, match="source child count differs"):
        check_candidate_bytes(SOURCE.read_bytes(), _mutated_text(change))


def test_reordered_dialogue_is_rejected() -> None:
    def change(text: ET.Element) -> None:
        parent = next(node for node in text.iter() if sum(child.tag == NS + "sp" for child in node) >= 2)
        positions = [index for index, child in enumerate(parent) if child.tag == NS + "sp"]
        first, second = positions[:2]
        first_node, second_node = deepcopy(parent[first]), deepcopy(parent[second])
        parent[first], parent[second] = second_node, first_node

    with pytest.raises(ValueError, match="source (text/order|attributes|element) differs"):
        check_candidate_bytes(SOURCE.read_bytes(), _mutated_text(change))


def test_changed_glyph_reference_is_rejected() -> None:
    def change(text: ET.Element) -> None:
        next(text.iter(NS + "g")).set("ref", "char:invented")

    with pytest.raises(ValueError, match="source attributes differ"):
        check_candidate_bytes(SOURCE.read_bytes(), _mutated_text(change))


def test_moved_note_attachment_is_rejected() -> None:
    def change(text: ET.Element) -> None:
        note = next(text.iter(NS + "note"))
        old_parent = next(node for node in text.iter() if note in node)
        old_parent.remove(note)
        paragraphs = list(text.iter(NS + "p"))
        destination = next(paragraph for paragraph in paragraphs if paragraph is not old_parent)
        destination.append(note)

    with pytest.raises(ValueError, match="source child count differs"):
        check_candidate_bytes(SOURCE.read_bytes(), _mutated_text(change))
