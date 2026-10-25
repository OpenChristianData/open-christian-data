"""Focused mutations and normalization checks for the isolated LIB-068 oracle."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

from lxml import etree
import pytest


ROOT = Path(__file__).resolve().parents[1]
TEI = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["newman-apologia-pro-vita-sua", "donne-devotions-upon-emergent-occasions"])
def prepared(request):
    producer = _load(ROOT / "build/tei/lib068_source_local.py", f"block_oracle_source_{request.param}")
    blocks = _load(ROOT / "build/tei/lib068_literary_blocks.py", f"block_oracle_producer_{request.param}")
    letters = _load(ROOT / "build/tei/lib068_source_letters_oracle.py", f"block_oracle_letters_{request.param}")
    oracle = _load(ROOT / "build/tei/lib068_literary_blocks_oracle.py", f"block_oracle_oracle_{request.param}")
    work_id = request.param
    profile = json.loads(
        (ROOT / "sources/structured-text" / work_id / "LIB-068.reconstruction-profile.json").read_bytes()
    )
    spec = producer._SPECS[work_id]
    lines = producer._source_lines((ROOT / spec.path).read_bytes(), spec)
    root = etree.fromstring(producer._tei(work_id, spec, profile, lines))
    scope = root.xpath('./t:text/t:body/t:div[@type="retained-source"]', namespaces=NS)[0]
    if not scope.xpath('.//t:quote|.//t:table|.//t:list[@type="chronology-entries" or @type="devotional-components" or @type="station-contents"]', namespaces=NS):
        blocks.apply_blocks(scope, work_id, lines, profile)
    normalized_letters = letters.verify_and_normalize_letters(scope, work_id, lines, profile)
    return oracle, normalized_letters, work_id, lines, profile


@pytest.mark.parametrize("start,end,count", [(12510,12516,16), (12521,12525,13), (12534,12537,7)])
def test_complete_retained_bibliography_enumerators(prepared, start, end, count):
    oracle, scope, work_id, lines, profile = prepared
    if work_id != "newman-apologia-pro-vita-sua":
        pytest.skip("Newman bibliography")
    listing = scope.xpath(
        f'.//t:list[@xml:id="{work_id}-bibliography-subitems-{start}"]',
        namespaces={**NS, "xml": "http://www.w3.org/XML/1998/namespace"},
    )[0]
    # The source gives complete, consecutive numbered titles in these entries.
    # This expectation is independent of both marker-discovery algorithms.
    assert [int(item.get("n")) for item in listing] == list(range(1, count + 1))
    assert [int(marker) for marker, _ in oracle._bibliography_markers(range(start, end + 1), lines)] == list(range(1, count + 1))
    victim = next(item for item in listing if lines[int(item.get("corresp").rsplit("-", 1)[1]) - 1].endswith(item.get("n") + "."))
    listing.remove(victim)
    with pytest.raises(ValueError, match="LIB-068"):
        oracle.verify_and_normalize_blocks(scope, work_id, lines, profile)


@pytest.mark.parametrize("line", [10960, 11191, 11201, 11210, 12502])
def test_physical_line_separators_are_checked_before_normalization(prepared, line):
    oracle, scope, work_id, lines, profile = prepared
    if work_id != "newman-apologia-pro-vita-sua":
        pytest.skip("Newman source-located continuation")
    leaf = next(node for node in scope.xpath(f'.//t:seg[@n="{line}"]', namespaces=NS) if node.getnext() is not None and node.getnext().get("n") == str(line + 1))
    assert leaf.tail == "\n"
    assert "".join(leaf.itertext()) + leaf.tail + "".join(leaf.getnext().itertext()) in "".join(leaf.getparent().itertext())
    leaf.tail = None
    with pytest.raises(ValueError, match="source physical-line separator drifted"):
        oracle.verify_and_normalize_blocks(scope, work_id, lines, profile)


def test_actual_special_tree_normalizes_to_source_floor(prepared):
    oracle, scope, work_id, lines, profile = prepared
    before = etree.tostring(scope, encoding="UTF-8")
    normalized = oracle.verify_and_normalize_blocks(scope, work_id, lines, profile)

    assert etree.tostring(scope, encoding="UTF-8") == before
    assert not normalized.xpath('.//t:quote|.//t:table|.//t:list|.//t:figure', namespaces=NS)
    leaves = normalized.xpath('.//t:seg', namespaces=NS)
    assert len(leaves) == len(lines)
    assert [leaf.get("n") for leaf in leaves] == [str(number) for number in range(1, len(lines) + 1)]
    assert all(dict(leaf.attrib) == {"type": "source-line", "n": leaf.get("n")} for leaf in leaves)
    assert ["".join(leaf.itertext()) for leaf in leaves] == lines


def test_mixed_inline_children_survive_fragment_merge(prepared):
    oracle, scope, work_id, lines, profile = prepared
    if work_id != "newman-apologia-pro-vita-sua":
        pytest.skip("Newman calendar supplies the split inline control")
    fragment = next(
        node
        for node in scope.xpath('.//t:seg[@type="source-line-fragment"]', namespaces=NS)
        if node.xpath('./t:hi|./t:ref', namespaces=NS)
    )
    number = int(fragment.get("n"))
    expected_inline = etree.tostring(fragment[0], encoding="unicode")
    normalized = oracle.verify_and_normalize_blocks(scope, work_id, lines, profile)
    leaf = normalized.xpath(f'.//t:seg[@n="{number}"]', namespaces=NS)[0]
    assert etree.tostring(leaf[0], encoding="unicode") == expected_inline
    assert "".join(leaf.itertext()) == lines[number - 1]


@pytest.mark.parametrize("mutation", ["drop-row", "change-range", "move-verse-line", "change-station-page"])
def test_independent_special_structure_mutations_fail_closed(prepared, mutation):
    oracle, original, work_id, lines, profile = prepared
    scope = deepcopy(original)
    if mutation == "drop-row":
        if work_id != "newman-apologia-pro-vita-sua":
            pytest.skip("Newman table control")
        table = scope.xpath('.//t:table[@type="calendar"]', namespaces=NS)[0]
        table[0].getparent().remove(table[0])
    elif mutation == "change-range":
        if work_id != "newman-apologia-pro-vita-sua":
            pytest.skip("Newman fragment control")
        fragment = scope.xpath('.//t:seg[@type="source-line-fragment"]', namespaces=NS)[0]
        function = fragment.get("function")
        assert function is not None
        fragment.set("function", function.rsplit("-", 1)[0] + "-3")
    elif mutation == "move-verse-line":
        quote = scope.xpath('.//t:quote[@type="source-verse"]', namespaces=NS)[0]
        stanza = quote.find("t:lg", NS)
        assert stanza is not None
        stanza[0], stanza[1] = stanza[1], stanza[0]
    elif mutation == "change-station-page":
        if work_id != "donne-devotions-upon-emergent-occasions":
            pytest.skip("Donne station control")
        scope.xpath('.//t:list[@type="station-contents"]/t:item/t:label', namespaces=NS)[0].set("n", "999")
    with pytest.raises(ValueError, match="LIB-068"):
        oracle.verify_and_normalize_blocks(scope, work_id, lines, profile)


def test_chronology_brace_group_relationship_is_checked(prepared):
    oracle, original, work_id, lines, profile = prepared
    if work_id != "newman-apologia-pro-vita-sua":
        pytest.skip("Newman chronology control")
    scope = deepcopy(original)
    group = scope.xpath('.//t:item[@ana="brace-group"]', namespaces=NS)[0]
    group.set("n", "unrelated-source-range")
    with pytest.raises(ValueError, match="LIB-068"):
        oracle.verify_and_normalize_blocks(scope, work_id, lines, profile)


def test_source_brace_membership_and_nesting(prepared):
    oracle, scope, work_id, lines, profile = prepared
    if work_id != "newman-apologia-pro-vita-sua":
        pytest.skip("Newman chronology")
    expected = [(11231, 11235), (11337, 11341), (11345, 11347), (11390, 11394), (11390, 11398), (11399, 11408)]
    assert oracle._source_brace_groups(lines) == expected
    groups = {node.get("n"): node for node in scope.xpath('.//t:item[@ana="brace-group"]', namespaces=NS)}
    assert set(groups) == {f"{a}-{b}" for a, b in expected}
    for a, b in expected:
        numbers = [int(node.get("n")) for node in groups[f"{a}-{b}"].xpath('.//t:seg[@type="source-line"]', namespaces=NS) if lines[int(node.get("n")) - 1].strip()]
        assert numbers == list(range(a, b + 1))
    inner = groups["11390-11394"]
    assert inner.getparent().getparent() is groups["11390-11398"]
    for number in (11342, 11343, 11344, 11348):
        leaf = scope.xpath(f'.//t:seg[@type="source-line" and @n="{number}"]', namespaces=NS)[0]
        assert not leaf.xpath('ancestor::t:item[@ana="brace-group"]', namespaces=NS)


@pytest.mark.parametrize("mutation", ["include-unbraced", "flatten-inner", "merge-outers"])
def test_source_brace_relationship_mutations_preserve_words_but_fail(prepared, mutation):
    oracle, scope, work_id, lines, profile = prepared
    if work_id != "newman-apologia-pro-vita-sua":
        pytest.skip("Newman chronology")
    before = "".join(scope.itertext())
    groups = {node.get("n"): node for node in scope.xpath('.//t:item[@ana="brace-group"]', namespaces=NS)}
    if mutation == "include-unbraced":
        unbraced = scope.xpath('.//t:item[@ana="chronology-entry" and @n="11342"]', namespaces=NS)[0]
        groups["11337-11341"][0].append(unbraced)
    elif mutation == "flatten-inner":
        inner = groups["11390-11394"]
        parent = inner.getparent()
        offset = parent.index(inner)
        for child in list(inner[0]):
            parent.insert(offset, child)
            offset += 1
        parent.remove(inner)
    else:
        later = groups["11399-11408"]
        for child in list(later[0]):
            groups["11390-11398"][0].append(child)
        later.getparent().remove(later)
    assert "".join(scope.itertext()) == before
    with pytest.raises(ValueError, match="LIB-068 chronology brace"):
        oracle.verify_and_normalize_blocks(scope, work_id, lines, profile)


def test_declared_brace_inventory_cannot_override_source_marks(prepared, monkeypatch):
    oracle, scope, work_id, lines, profile = prepared
    if work_id != "newman-apologia-pro-vita-sua":
        pytest.skip("Newman chronology")
    monkeypatch.setitem(oracle.SPECIAL_SOURCE_INVENTORY[work_id]["chronology"], "brace_groups", [(11231,11235),(11337,11348),(11390,11408)])
    with pytest.raises(ValueError, match="declared brace groups disagree with source marks and labels"):
        oracle._verify_chronology(scope, work_id, lines, oracle._profile_rows(profile), oracle._Carriers(scope, lines, work_id), set())


def test_figure_placeholder_must_remain_at_its_source_position(prepared):
    oracle, original, work_id, lines, profile = prepared
    if work_id != "donne-devotions-upon-emergent-occasions":
        pytest.skip("Donne illustration control")
    scope = deepcopy(original)
    figure = scope.xpath('.//t:quote[@type="source-verse"]/t:figure', namespaces=NS)[0]
    figure.getparent().remove(figure)
    scope.append(figure)
    with pytest.raises(ValueError, match="LIB-068"):
        oracle.verify_and_normalize_blocks(scope, work_id, lines, profile)
