"""The letter checker preserves the candidate it inspects and its actual carriers."""

import importlib.util
import json
from pathlib import Path
import sys

from lxml import etree
import pytest


ROOT = Path(__file__).resolve().parents[1]
NS = {"t": "http://www.tei-c.org/ns/1.0"}


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "build/tei" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("work", ["newman-apologia-pro-vita-sua", "donne-devotions-upon-emergent-occasions"])
def test_letter_normalization_is_nonmutating_and_preserves_actual_carriers(work):
    producer = _load("lib068_source_local")
    checker = _load("lib068_source_letters_oracle")
    profile = json.loads((ROOT / "sources/structured-text" / work / "LIB-068.reconstruction-profile.json").read_bytes())
    spec = producer._SPECS[work]
    lines = producer._source_lines((ROOT / spec.path).read_bytes(), spec)
    tree = etree.fromstring(producer._tei(work, spec, profile, lines))
    scope = tree.xpath('./t:text/t:body/t:div[@type="retained-source"]', namespaces=NS)[0]
    assert scope.xpath('.//t:floatingText', namespaces=NS)
    original = etree.tostring(scope)

    def carriers(node):
        return [(leaf.get("type"), leaf.get("n"), "".join(leaf.itertext())) for leaf in node.xpath('.//t:seg[@type="source-line" or @type="source-line-fragment"]', namespaces=NS)]

    actual = carriers(scope)
    normalized = checker.verify_and_normalize_letters(scope, work, lines, profile)
    assert etree.tostring(scope) == original
    assert normalized is not scope
    assert not normalized.xpath('.//t:floatingText', namespaces=NS)
    assert carriers(normalized) == actual


def _newman():
    work = "newman-apologia-pro-vita-sua"
    producer = _load("lib068_source_local")
    checker = _load("lib068_source_letters_oracle")
    profile = json.loads((ROOT / "sources/structured-text" / work / "LIB-068.reconstruction-profile.json").read_bytes())
    spec = producer._SPECS[work]
    lines = producer._source_lines((ROOT / spec.path).read_bytes(), spec)
    tree = etree.fromstring(producer._tei(work, spec, profile, lines))
    scope = tree.xpath('./t:text/t:body/t:div[@type="retained-source"]', namespaces=NS)[0]
    return work, checker, profile, lines, scope


@pytest.mark.parametrize("line", [12895, 13040, 13124, 13128])
def test_closing_prose_is_neutral_and_relabeling_is_rejected(line):
    work, checker, profile, lines, scope = _newman()
    carrier = scope.xpath(f'.//t:seg[@type="source-line" and @n="{line}"]', namespaces=NS)[0]
    paragraph = carrier.getparent()
    assert paragraph.tag == "{http://www.tei-c.org/ns/1.0}seg"
    assert paragraph.get("type") == "source-letter-prose"
    assert paragraph.getparent().tag == "{http://www.tei-c.org/ns/1.0}closer"
    wording = "".join(scope.itertext())
    paragraph.tag = "{http://www.tei-c.org/ns/1.0}salute"
    paragraph.attrib.clear()
    assert "".join(scope.itertext()) == wording
    with pytest.raises(ValueError, match="letter field role drift"):
        checker.verify_and_normalize_letters(scope, work, lines, profile)


def test_profile_cannot_reclassify_a_prayer_as_a_salutation():
    work, checker, profile, lines, scope = _newman()
    letter = next(row for row in profile["literary_letters"] if row["first"] == 12856)
    letter["fields"].append({"tag": "salute", "first": 12895, "last": 12897})
    with pytest.raises(ValueError, match="salutation lacks a source closing or greeting formula"):
        checker.verify_and_normalize_letters(scope, work, lines, profile)
