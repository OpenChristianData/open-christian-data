"""Exact source-label and parent/order checks for two held LIB-062 catechisms."""

from __future__ import annotations

from pathlib import Path

from lxml import etree
import pytest

from build.tei.lib062_numeric_subquestion_crosswalk import crosswalk


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = Path("D:/Library/Open Christian Data/candidate-reviews")
CASES = (
    ("exposition-of-the-assemblies-catechism", "exposition_of_the_assemblies_catechism.json",
     "creeds-lib062-six-20260926", 125, 1244, 23),
    ("shorter-catechism-explained", "shorter_catechism_explained.json",
     "creeds-catechism-preflight-20260926", 107, 3831, 0),
)
NS = {"t": "http://www.tei-c.org/ns/1.0"}


def _contents(case: tuple) -> tuple[bytes, bytes]:
    work, filename, cohort, *_ = case
    source = (ROOT / "raw/Creeds.json/creeds" / filename).read_bytes()
    tei = (LIBRARY / cohort / work / "package/content.tei.xml").read_bytes()
    return source, tei


@pytest.mark.parametrize("case", CASES, ids=lambda case: case[0])
def test_every_retained_label_and_qa_matches_its_tei_position(case: tuple) -> None:
    source, tei = _contents(case)
    result = crosswalk(case[0], source, tei)
    assert len(result["rows"]) == case[3]
    assert result["subquestion_count"] == case[4]
    assert result["main_question_mark_count"] == case[5]
    assert [row["source_position"] for row in result["rows"]] == list(range(1, case[3] + 1))
    if case[0] == "exposition-of-the-assemblies-catechism":
        assert result["spaced_labels"] == [("41", 2, "2 "), ("45", 4, "4 ")]
    else:
        assert result["spaced_labels"] == []


@pytest.mark.parametrize("mutation", ("main-label", "nested-label", "nested-answer", "nested-parent"))
def test_crosswalk_rejects_raw_label_text_or_parent_drift(mutation: str) -> None:
    case = CASES[0]
    source, tei = _contents(case)
    root = etree.fromstring(tei)
    units = root.xpath("./t:text/t:body/t:div[@type='catechism']/t:div[@type='question-unit']", namespaces=NS)
    if mutation == "main-label":
        units[4].set("n", "5")
    elif mutation == "nested-label":
        item = units[61].xpath("./t:list[@type='subquestions']/t:item", namespaces=NS)[1]
        item.set("n", "2")  # the source has an exact trailing space
    elif mutation == "nested-answer":
        answer = units[0].xpath("./t:list[@type='subquestions']/t:item[1]/t:p[@ana='#subquestion-answer']", namespaces=NS)[0]
        answer.text = (answer.text or "") + " changed"
    else:
        source_list = units[0].xpath("./t:list[@type='subquestions']", namespaces=NS)[0]
        target_list = units[1].xpath("./t:list[@type='subquestions']", namespaces=NS)[0]
        target_list.append(source_list[0])
    changed = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    with pytest.raises(ValueError):
        crosswalk(case[0], source, changed)


def test_crosswalk_rejects_mutated_retained_json_bytes() -> None:
    source, tei = _contents(CASES[1])
    with pytest.raises(ValueError, match="retained JSON authority differs"):
        crosswalk(CASES[1][0], source.replace(b'"Number": "1"', b'"Number": "9"', 1), tei)
