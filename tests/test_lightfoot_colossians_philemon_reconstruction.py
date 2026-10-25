"""Focused tests for the isolated Lightfoot source-structured successor."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

import pytest
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/reconstruction-runtime/lightfoot-colossians-philemon.source-manifest.json"
SOURCE_PATH = ROOT / "raw/gutenberg/commentary/lightfoot-colossians-philemon/pg50857.txt"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def modules():
    producer = _load("lightfoot_test_producer", ROOT / "build/tei/lightfoot_colossians_philemon_reconstruction.py")
    oracle = _load("lightfoot_test_oracle", ROOT / "build/tei/lightfoot_colossians_philemon_oracle.py")
    return producer, oracle


@pytest.fixture(scope="module")
def prepared(tmp_path_factory: pytest.TempPathFactory, modules):
    producer, oracle = modules
    source_manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    candidate = reconstruct(source_manifest, tmp_path_factory.mktemp("lightfoot-source") / "candidate", producer._convert)
    report = validate(source_manifest, candidate, oracle._oracle)
    return source_manifest, candidate, report, producer, oracle


def test_reconstruction_and_oracle_are_deterministic(tmp_path: Path, modules) -> None:
    producer, oracle = modules
    source_manifest = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    first = reconstruct(source_manifest, tmp_path / "first", producer._convert)
    second = reconstruct(source_manifest, tmp_path / "second", producer._convert)
    assert first.sha256 == second.sha256
    for name in first.member_names:
        assert first.member_bytes(name) == second.member_bytes(name)
    assert validate(source_manifest, first, oracle._oracle).status == "pass"


def test_source_native_feature_coverage(prepared) -> None:
    _, candidate, report, _, _ = prepared
    assert report.status == "pass"
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    counts = account["feature_counts"]
    assert counts == {
        "source_regions": 17,
        "structural_units": 4583,
        "paragraphs": 3393,
        "range_occurrences": 120,
        "colossians_range_occurrences": 106,
        "philemon_range_occurrences": 14,
        "dash_separators": 136,
        "footnote_heads": 759,
        "footnote_body_lines": 5788,
        "sidenote_markers": 677,
        "sidenote_start_lines": 453,
        "sidenote_inline_lines": 224,
        "sidenote_cross_line_markers": 150,
        "greek_lines": 231,
        "paraphrase_lines": 188,
        "lemma_lines": 87,
        "apparatus_lines": 11,
        "commentary_lines": 6552,
        "mixed_source_lines": 1,
        "footnote_references": 761,
        "illustration_placeholders": 1,
        "gutenberg_start_markers": 1,
        "gutenberg_end_markers": 1,
    }
    source_bytes = SOURCE_PATH.read_bytes()
    assert source_bytes.startswith(b"\xef\xbb\xbf")
    crosswalk = account["crosswalk"]
    assert len(crosswalk) == 26_185
    offset = 0
    for number, item in enumerate(crosswalk, 1):
        assert item["line"] == number
        assert item["byte_start"] == offset
        raw = source_bytes[item["byte_start"] : item["byte_end"]]
        assert item["byte_end"] == offset + len(raw)
        assert item["source_sha256"] == hashlib.sha256(raw).hexdigest()
        payload = raw[:-1] if raw.endswith(b"\n") else raw
        if payload.endswith(b"\r"):
            payload = payload[:-1]
        assert item["text"] == payload.decode("utf-8-sig" if number == 1 else "utf-8")
        assert item["tei_id"] == f"lightfoot-line-{number:06d}"
        offset = item["byte_end"]
    assert offset == len(source_bytes)
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert "\ufeff" not in "".join(root.itertext())
    ns = {"t": TEI}
    assert len(root.xpath(".//t:seg[@type='source-line'] | .//t:head[@type='source-line']", namespaces=ns)) == 26_185
    assert len(root.xpath(".//t:ab[@type='source-line']", namespaces=ns)) == 0
    assert len(root.xpath(".//t:div[@type='source-line-container']", namespaces=ns)) == 0
    assert len(root.xpath(".//t:p[@xml:id]", namespaces={"t": TEI, "xml": XML})) == 3_393
    assert len(root.xpath(".//t:head[@type='source-line']", namespaces=ns)) == 176
    assert all("type" not in node.attrib for node in root.xpath(".//t:p[@xml:id]", namespaces={"t": TEI, "xml": XML}))
    assert len(root.xpath(".//t:div[@type='range-occurrence']", namespaces=ns)) == 120
    assert len(root.xpath(".//t:note[@type='footnote']", namespaces=ns)) == 759
    assert len(root.xpath(".//t:table[@type='parallel-reading-table']", namespaces=ns)) == 2
    assert len(root.xpath(".//t:row", namespaces=ns)) == 6
    assert len(root.xpath(".//t:cell", namespaces=ns)) == 6
    assert len(root.xpath(".//t:seg[@type='sidenote']", namespaces=ns)) == 677
    assert len(root.xpath(".//t:ref[@type='footnote-reference']", namespaces=ns)) == 761
    assert len(root.xpath(".//t:seg[@type='mixed-source-line-part']", namespaces=ns)) == 2
    assert "\ufeff" not in "".join(root.itertext())
    typography = root.xpath(".//t:hi", namespaces=ns)
    assert typography
    ids = {node.get(f"{{{XML}}}id") for node in root.iter()}
    assert all(node.get("corresp", "#")[1:] in ids for node in typography if node.get("corresp"))
    for span in account["typography"]["spans"]:
        assert span["id"] in ids
    first_range = root.xpath(".//t:div[@xml:id='lightfoot-colossians-range-0001']", namespaces={"t": TEI, "xml": XML})[0]
    assert first_range[0].tag == f"{{{TEI}}}head"
    first_note = root.xpath(".//t:note[@xml:id='lightfoot-footnote-0001']", namespaces={"t": TEI, "xml": XML})[0]
    assert first_note[0].tag == f"{{{TEI}}}label"
    assert root.xpath(".//t:div[@xml:id='lightfoot-region-colossians-apparatus']", namespaces={"t": TEI, "xml": XML})
    assert root.xpath(".//t:div[@xml:id='lightfoot-region-philemon-commentary']", namespaces={"t": TEI, "xml": XML})
    assert root.xpath(".//t:div[@xml:id='lightfoot-region-index']", namespaces={"t": TEI, "xml": XML})


def test_independent_source_greek_paraphrase_lemma_census(prepared) -> None:
    """Corroborate source roles from direct text and fixed source loci.

    This census does not call either module's Greek/paraphrase classifier.  It
    derives range spans from the retained headings, counts Greek-bearing source
    lines directly, and checks the known source-layout exceptions by coordinate.
    """
    _, candidate, _, _, _ = prepared
    source_bytes = SOURCE_PATH.read_bytes()
    source = source_bytes.decode("utf-8").splitlines()
    assert len(source) == 26_185
    assert hashlib.sha256(source_bytes).hexdigest() == "a97cb49964906a2c158a0444cfdc3b0daf13261620c919a90f1333a98ac0b913"
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    units = account["structural_units"]
    roles: dict[int, str] = {}
    for unit in units:
        if unit["type"] in {"scripture-text", "paraphrase", "lemma", "apparatus", "commentary", "mixed-source-line"}:
            for line in range(unit["start_line"], unit["end_line"] + 1):
                roles[line] = unit["type"]

    def greek_bearing(value: str) -> bool:
        return sum(0x0370 <= ord(char) <= 0x03FF or 0x1F00 <= ord(char) <= 0x1FFF for char in value) >= 2

    all_greek_lines = [line for line, value in enumerate(source, 1) if value.strip() and greek_bearing(value)]
    colossians_heads = [
        line
        for line, value in enumerate(source, 1)
        if 10_860 <= line <= 18_352 and re.fullmatch(r"^[IVX]+\.\s*[\d,\s–—\-]+\]$", value)
    ]
    philemon_heads = [
        line
        for line, value in enumerate(source, 1)
        if 23_616 <= line <= 24_498 and re.fullmatch(r"^[\d,\s–—\-]+\]$", value)
    ]
    assert len(colossians_heads) == 106
    assert len(philemon_heads) == 14

    def source_spans(heads: list[int], region_end: int) -> list[tuple[int, int]]:
        return [
            (start, heads[index + 1] - 1 if index + 1 < len(heads) else region_end)
            for index, start in enumerate(heads)
        ]

    range_spans = source_spans(colossians_heads, 18_352) + source_spans(philemon_heads, 24_498)
    range_greek_lines = [
        line for start, end in range_spans for line in range(start + 1, end + 1)
        if source[line - 1].strip() and greek_bearing(source[line - 1])
    ]
    assert len(all_greek_lines) == 5246
    assert len(range_greek_lines) == 3514
    assert len(set(range_greek_lines)) == 3514
    assert {role: sum(roles[line] == role for line in range_greek_lines) for role in ("scripture-text", "mixed-source-line", "paraphrase", "lemma", "apparatus", "commentary")} == {
        "scripture-text": 230,
        "mixed-source-line": 1,
        "paraphrase": 2,
        "lemma": 57,
        "apparatus": 11,
        "commentary": 3213,
    }

    # Source-first role facts from the reviewed counterexamples.  Each span is
    # blank-separated in the retained witness and must map to one role unit.
    lemma_spans = (
        (12_432, 12_455, "17."),
        (13_462, 13_466, "29."),
        (13_720, 13_725, "4."),
        (14_492, 14_498, "14."),
        (15_954, 15_962, "2."),
        (17_241, 17_246, "24."),
        (18_214, 18_220, "16."),
        (24_149, 24_171, "13."),
    )
    for start, end, prefix in lemma_spans:
        assert source[start - 1].startswith(prefix)
        assert not source[start - 2].strip() and not source[end].strip()
        assert {roles[line] for line in range(start, end + 1)} == {"lemma"}
    paraphrase_spans = (
        (12_679, 12_687, "20. The false teachers aimed at effecting a partial reconciliation"),
        (17_721, 17_723, "10. The salutations to Philemon are sent from the same persons as to the"),
    )
    for start, end, prefix in paraphrase_spans:
        assert source[start - 1].startswith(prefix)
        assert not source[start - 2].strip() and not source[end].strip()
        assert {roles[line] for line in range(start, end + 1)} == {"paraphrase"}
    apparatus_lines = (11_455, 11_631, 12_786, 13_876, 14_362, 14_815, 14_916, 15_986, 17_177, 23_824, 23_872)
    for line in apparatus_lines:
        assert source[line - 1].strip() and not source[line - 2].strip() and not source[line].strip()
        assert roles[line] == "apparatus"

    mixed_line = 13_183
    assert source[mixed_line - 1] == "τοῦ σώματος αὐτοῦ An antithesis of the Apostle’s own flesh and Christ’s"
    assert roles[mixed_line] == "mixed-source-line"
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"t": TEI, "xml": XML}
    mixed_leaf = tei.xpath(".//t:seg[@xml:id='lightfoot-line-013183']", namespaces=ns)[0]
    assert [(child.get("ana"), "".join(child.itertext())) for child in mixed_leaf] == [
        ("#scripture-text", "τοῦ σώματος αὐτοῦ"),
        ("#commentary", " An antithesis of the Apostle’s own flesh and Christ’s"),
    ]

    # Verify the complete local note join graph independently from the
    # producer's constants: source numeric brackets resolve by displayed
    # number to one source definition, while [1550] remains literal.
    footnote_heads = [
        (line, int(match.group(1)))
        for line, value in enumerate(source, 1)
        if (match := re.fullmatch(r"Footnote (\d+):", value))
    ]
    assert len(footnote_heads) == 759
    by_number = {number: ordinal for ordinal, (_, number) in enumerate(footnote_heads, 1)}
    source_refs = [
        (line, match.start(), match.end(), int(match.group(1)), match.group(0))
        for line, value in enumerate(source, 1)
        for match in re.finditer(r"\[([0-9]+)\]", value)
    ]
    assert len(source_refs) == 763
    exceptions = {
        (3_804, 32, 38, 1_550, "[1550]"),
        (18_346, 14, 18, 24, "[24]"),
    }
    assert exceptions.issubset(set(source_refs))
    # A note reference is attached to the preceding source word.  A bracket
    # preceded by whitespace or a comma is a citation/verse-list boundary and
    # stays literal unless its exact source context is explicitly reviewed.
    for line, start, _, _, token in source_refs:
        if (line, start, start + len(token), int(token[1:-1]), token) in exceptions:
            continue
        assert start > 0
        assert source[line - 1][start - 1] not in {" ", ","}, (line, start, token)
    resolvable = [item for item in source_refs if item not in exceptions]
    assert len(resolvable) == 761
    refs_by_line = {}
    for line, start, end, number, token in resolvable:
        assert number in by_number
        refs_by_line.setdefault(line, []).append((start, end, number, token, by_number[number]))
    observed_refs = {}
    for node in tei.xpath(".//t:seg[@type='source-line'] | .//t:head[@type='source-line']", namespaces=ns):
        line = int(node.get("n"))
        for ref in node.xpath("./t:ref[@type='footnote-reference']", namespaces=ns):
            observed_refs.setdefault(line, []).append((ref.get(f"{{{XML}}}id"), ref.get("target"), "".join(ref.itertext())))
    assert sum(len(values) for values in observed_refs.values()) == 761
    for line, expected in refs_by_line.items():
        assert [
            (f"lightfoot-footnote-ref-{number}-line-{line:06d}", f"#lightfoot-footnote-{ordinal:04d}", token)
            for _, _, number, token, ordinal in expected
        ] == observed_refs[line]
    for line, _, _, _, token in sorted(exceptions):
        exception_leaf = tei.xpath(f".//*[@xml:id='lightfoot-line-{line:06d}']", namespaces=ns)[0]
        assert token in "".join(exception_leaf.itertext())
        assert not any(token == "".join(ref.itertext()) for ref in exception_leaf.xpath("./t:ref", namespaces=ns))

    # These are the source-native page continuation lines after I. 3]; the
    # next Greek line is a new marked verse carrier, so no join is inferred.
    assert roles[10920] == roles[10921] == roles[10923] == "scripture-text"
    assert source[10917] == "I. 3]"
    assert "^3" in source[10922]
    assert roles[13487] == "scripture-text" and "II. ^1" in source[13486]


def test_source_toc_and_native_essay_boundaries_are_independently_correlated(prepared) -> None:
    """Cross-check body essays against the printed contents page and source lines."""

    _, candidate, _, _, _ = prepared
    source = SOURCE_PATH.read_bytes().decode("utf-8").splitlines()

    def title_from_toc(value: str) -> str:
        match = re.search(r"_(.+?)_(?=\s+\d)", value)
        assert match is not None
        return match.group(1)

    def title_from_body(value: str) -> str:
        return re.sub(r"\[\d+\]", "", value.replace("_", "")).strip(" .")

    toc = {
        246: title_from_toc(source[245]),
        248: title_from_toc(source[247]),
        250: title_from_toc(source[249]),
    }
    heading_lines = (18_354, 19_108, 20_277)
    body_titles = {line: title_from_body(source[line - 1]) for line in heading_lines}
    assert [body_titles[line] for line in heading_lines] == [toc[246], toc[248], toc[250]]
    assert not source[heading_lines[0] - 2].strip()
    philemon_heading = next(
        line
        for line, value in enumerate(source, 1)
        if line > heading_lines[-1]
        if value.strip() == "EPISTLE TO PHILEMON."
    )
    assert philemon_heading == 22_121

    starts = (heading_lines[0] - 1, heading_lines[1], heading_lines[2])
    ends = (heading_lines[1] - 1, heading_lines[2] - 1, philemon_heading - 1)
    essay_specs = (
        ("lightfoot-various-readings", starts[0], ends[0], heading_lines[0], toc[246]),
        ("lightfoot-meaning-of-pleroma", starts[1], ends[1], heading_lines[1], toc[248]),
        ("lightfoot-epistle-from-laodicea", starts[2], ends[2], heading_lines[2], toc[250]),
    )
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    ns = {"t": TEI, "xml": XML}
    for ident, start, end, heading, title in essay_specs:
        node = tei.xpath(f".//t:div[@xml:id='{ident}']", namespaces=ns)
        assert len(node) == 1
        essay = node[0]
        assert essay.get("type") == "dissertation"
        assert essay.getparent().get(f"{{{XML}}}id") == "lightfoot-region-colossians-apparatus"
        leaves = essay.xpath(".//*[@type='source-line']", namespaces=ns)
        assert [int(leaf.get("n")) for leaf in leaves] == list(range(start, end + 1))
        native_head = essay.xpath(
            f".//t:head[@type='source-line' and @n='{heading}']",
            namespaces=ns,
        )
        assert len(native_head) == 1
        assert "".join(native_head[0].itertext()) == source[heading - 1]
        assert title in "".join(native_head[0].itertext()).replace("_", "")

    laodicea = tei.xpath(
        ".//t:div[@xml:id='lightfoot-epistle-from-laodicea']",
        namespaces=ns,
    )[0]
    for ident in (
        "lightfoot-laodiceans-mss-capitula",
        "lightfoot-laodiceans-text-apparatus",
        "lightfoot-laodiceans-notes-history",
    ):
        child = tei.xpath(f".//t:div[@xml:id='{ident}']", namespaces=ns)[0]
        assert child.getparent() is laodicea

    structural_tags = {
        f"{{{TEI}}}div",
        f"{{{TEI}}}note",
        f"{{{TEI}}}table",
        f"{{{TEI}}}p",
    }
    structural_nodes = [
        node
        for node in tei.iter()
        if node.tag in structural_tags
        and node.get(f"{{{XML}}}id")
        and not node.get(f"{{{XML}}}id").startswith("lightfoot-line-")
    ]
    assert len(structural_nodes) == 4_583
    assert len(tei.xpath(".//t:p[@xml:id]", namespaces=ns)) == 3_393
    assert len(tei.xpath(".//t:head[@type='source-line']", namespaces=ns)) == 176


def _refresh_member_manifest(candidate_path: Path) -> None:
    manifest_path = candidate_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    import hashlib

    for member in manifest["members"]:
        content = (candidate_path / member["name"]).read_bytes()
        member["bytes"] = len(content)
        member["sha256"] = hashlib.sha256(content).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _replace_element_tag(node: etree._Element, tag: str) -> etree._Element:
    replacement = etree.Element(f"{{{TEI}}}{tag}", nsmap=node.nsmap)
    replacement.attrib.update(node.attrib)
    replacement.text = node.text
    replacement.tail = node.tail
    for child in list(node):
        replacement.append(child)
    parent = node.getparent()
    if parent is None:
        raise AssertionError("cannot replace the XML root")
    parent.replace(node, replacement)
    return replacement


def _source_line_map(root: etree._Element) -> dict[int, str]:
    return {
        int(node.get("n")): "".join(node.itertext())
        for node in root.xpath(".//*[@type='source-line']")
    }


def _mutated_candidate(prepared, tmp_path: Path, operation: str) -> CandidatePackage:
    source_manifest, candidate, _, _, _ = prepared
    path = tmp_path / operation
    shutil.copytree(candidate.path, path)
    root = etree.parse(str(path / "content.tei.xml"))
    ns = {"t": TEI, "xml": XML}
    if operation == "inject-file-bom-into-readable-line":
        leaf = root.xpath(".//*[@xml:id='lightfoot-line-000001']", namespaces=ns)[0]
        leaf.text = "\ufeff" + (leaf.text or "")
    elif operation == "wrong-typography-role":
        root.xpath(".//t:hi", namespaces=ns)[0].set("rend", "invented-font")
    elif operation == "dangling-typography-link":
        root.xpath(".//t:hi[@corresp]", namespaces=ns)[0].set("corresp", "#absent-font-span")
    elif operation == "missing-typography":
        etree.strip_tags(root, f"{{{TEI}}}hi")
    elif operation == "flatten-range":
        range_node = root.xpath(".//t:div[@xml:id='lightfoot-colossians-range-0001']", namespaces=ns)[0]
        parent = range_node.getparent()
        index = parent.index(range_node)
        children = list(range_node)
        parent.remove(range_node)
        for offset, child in enumerate(children):
            parent.insert(index + offset, child)
    elif operation == "move-range":
        range_node = root.xpath(".//t:div[@xml:id='lightfoot-colossians-range-0001']", namespaces=ns)[0]
        destination = root.xpath(".//t:div[@xml:id='lightfoot-envelope']", namespaces=ns)[0]
        range_node.getparent().remove(range_node)
        destination.append(range_node)
    elif operation == "swap-ranges":
        parent = root.xpath(".//t:div[@xml:id='lightfoot-region-colossians-commentary']", namespaces=ns)[0]
        first = root.xpath(".//t:div[@xml:id='lightfoot-colossians-range-0001']", namespaces=ns)[0]
        second = root.xpath(".//t:div[@xml:id='lightfoot-colossians-range-0002']", namespaces=ns)[0]
        i, j = parent.index(first), parent.index(second)
        parent.remove(first)
        parent.remove(second)
        parent.insert(i, second)
        parent.insert(j, first)
    elif operation == "remove-line":
        leaf = root.xpath(".//*[@xml:id='lightfoot-line-010918']", namespaces=ns)[0]
        leaf.getparent().remove(leaf)
    elif operation == "duplicate-line":
        leaf = root.xpath(".//*[@xml:id='lightfoot-line-010918']", namespaces=ns)[0]
        leaf.getparent().insert(leaf.getparent().index(leaf), etree.fromstring(etree.tostring(leaf)))
    elif operation == "invent-text":
        leaf = root.xpath(".//*[@xml:id='lightfoot-line-000001']", namespaces=ns)[0]
        leaf.text = "invented source text"
    elif operation == "retype-paragraph":
        paragraph = root.xpath(".//t:div[@type='scripture-text']//t:p[@xml:id]", namespaces=ns)[0]
        _replace_element_tag(paragraph, "div")
    elif operation == "move-footnote":
        note = root.xpath(".//t:note[@type='footnote']", namespaces=ns)[0]
        destination = root.xpath(".//t:div[@xml:id='lightfoot-envelope']", namespaces=ns)[0]
        note.getparent().remove(note)
        destination.append(note)
    elif operation == "flatten-table":
        table = root.xpath(".//t:table[@type='parallel-reading-table']", namespaces=ns)[0]
        parent = table.getparent()
        index = parent.index(table)
        children = list(table)
        parent.remove(table)
        for offset, child in enumerate(children):
            parent.insert(index + offset, child)
    elif operation == "move-role-line":
        leaf = root.xpath(".//*[@xml:id='lightfoot-line-011455']", namespaces=ns)[0]
        destination = root.xpath(".//t:div[@type='commentary']", namespaces=ns)[0]
        leaf.getparent().remove(leaf)
        destination.append(leaf)
    elif operation == "wrong-heading-tag":
        heading = root.xpath(".//t:head[@xml:id='lightfoot-line-010860']", namespaces=ns)[0]
        _replace_element_tag(heading, "seg")
    elif operation == "shift-footnote-reference-prefix":
        line = root.xpath(".//*[@xml:id='lightfoot-line-000434']", namespaces=ns)[0]
        ref = line.xpath("./t:ref[@type='footnote-reference']", namespaces=ns)[0]
        assert "".join(ref.itertext()) == "[13]"
        assert (line.text or "").endswith("ed")
        line.text = (line.text or "")[:-2]
        ref.text = "ed[13]"
    elif operation == "shift-footnote-reference-to-much":
        line = root.xpath(".//*[@xml:id='lightfoot-line-000434']", namespaces=ns)[0]
        ref = line.xpath("./t:ref[@type='footnote-reference']", namespaces=ns)[0]
        old_text = line.text or ""
        position = old_text.index("much")
        assert "".join(ref.itertext()) == "[13]"
        line.text = old_text[:position]
        ref.text = "much"
        ref.tail = old_text[position + len("much") :] + "[13]" + (ref.tail or "")
    elif operation == "move-laodiceans-ancestry":
        child = root.xpath(
            ".//t:div[@xml:id='lightfoot-laodiceans-text-apparatus']",
            namespaces=ns,
        )[0]
        destination = root.xpath(
            ".//t:div[@xml:id='lightfoot-various-readings']",
            namespaces=ns,
        )[0]
        child.getparent().remove(child)
        destination.append(child)
    elif operation == "move-essay-heading":
        heading = root.xpath(
            ".//t:head[@type='source-line' and @n='20277']",
            namespaces=ns,
        )[0]
        movable = heading.getparent()
        if movable.get("type") not in {"source-heading-fragment", "source-content-fragment"}:
            movable = heading
        destination = root.xpath(
            ".//t:div[@xml:id='lightfoot-various-readings']",
            namespaces=ns,
        )[0]
        movable.getparent().remove(movable)
        destination.append(movable)
    elif operation == "merge-essay-boundaries":
        various = root.xpath(
            ".//t:div[@xml:id='lightfoot-various-readings']",
            namespaces=ns,
        )[0]
        pleroma = root.xpath(
            ".//t:div[@xml:id='lightfoot-meaning-of-pleroma']",
            namespaces=ns,
        )[0]
        for child in list(pleroma):
            pleroma.remove(child)
            various.append(child)
    else:
        raise AssertionError(operation)
    (path / "content.tei.xml").write_bytes(etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    _refresh_member_manifest(path)
    return CandidatePackage.load(path)


def test_file_initial_bom_is_accounted_but_not_readable(prepared) -> None:
    _, candidate, report, _, _ = prepared
    assert report.status == "pass"
    source_bytes = SOURCE_PATH.read_bytes()
    assert source_bytes.startswith(b"\xef\xbb\xbf")
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    first = account["crosswalk"][0]
    first_raw = source_bytes[first["byte_start"] : first["byte_end"]]
    assert first["byte_start"] == 0
    assert first_raw.startswith(b"\xef\xbb\xbf")
    assert first["source_sha256"] == hashlib.sha256(first_raw).hexdigest()
    assert first["text"] == first_raw.decode("utf-8-sig").rstrip("\r\n")
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert "\ufeff" not in "".join(root.itertext())
    first_tei = root.xpath(".//*[@xml:id='lightfoot-line-000001']", namespaces={"t": TEI, "xml": XML})[0]
    assert "".join(first_tei.itertext()) == first["text"]


def test_file_initial_bom_in_readable_tei_is_rejected(prepared, tmp_path: Path) -> None:
    source_manifest, _, _, _, oracle = prepared
    candidate = _mutated_candidate(prepared, tmp_path, "inject-file-bom-into-readable-line")
    with pytest.raises(ValueError):
        validate(source_manifest, candidate, oracle._oracle)


@pytest.mark.parametrize(
    "operation",
    [
        "wrong-typography-role",
        "dangling-typography-link",
        "missing-typography",
        "flatten-range",
        "move-range",
        "swap-ranges",
        "remove-line",
        "duplicate-line",
        "invent-text",
        "retype-paragraph",
        "move-footnote",
        "flatten-table",
        "move-role-line",
        "wrong-heading-tag",
    ],
)
def test_source_and_tree_mutations_fail_closed(prepared, tmp_path: Path, operation: str) -> None:
    source_manifest, _, _, _, oracle = prepared
    candidate = _mutated_candidate(prepared, tmp_path, operation)
    with pytest.raises(ValueError):
        validate(source_manifest, candidate, oracle._oracle)


@pytest.mark.parametrize(
    ("operation", "wrong_ref_text"),
    [
        ("shift-footnote-reference-prefix", "ed[13]"),
        ("shift-footnote-reference-to-much", "much"),
    ],
)
def test_text_preserving_reference_shifts_fail_for_attachment_reason(
    prepared,
    tmp_path: Path,
    operation: str,
    wrong_ref_text: str,
) -> None:
    source_manifest, original_candidate, _, _, oracle = prepared
    original_root = etree.fromstring(original_candidate.member_bytes("content.tei.xml"))
    candidate = _mutated_candidate(prepared, tmp_path, operation)
    mutated_root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert _source_line_map(mutated_root) == _source_line_map(original_root)
    mutated_line = mutated_root.xpath(
        ".//*[@xml:id='lightfoot-line-000434']",
        namespaces={"t": TEI, "xml": XML},
    )[0]
    assert "".join(mutated_line.xpath("./t:ref", namespaces={"t": TEI})[0].itertext()) == wrong_ref_text
    with pytest.raises(ValueError, match=r"Lightfoot source reference (?:text|offset) drifted at line 434"):
        validate(source_manifest, candidate, oracle._oracle)


@pytest.mark.parametrize(
    "operation",
    [
        "move-laodiceans-ancestry",
        "move-essay-heading",
        "merge-essay-boundaries",
    ],
)
def test_text_preserving_essay_structure_mutations_fail_closed(
    prepared,
    tmp_path: Path,
    operation: str,
) -> None:
    source_manifest, original_candidate, _, _, oracle = prepared
    original_root = etree.fromstring(original_candidate.member_bytes("content.tei.xml"))
    candidate = _mutated_candidate(prepared, tmp_path, operation)
    mutated_root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    assert _source_line_map(mutated_root) == _source_line_map(original_root)
    with pytest.raises(ValueError):
        validate(source_manifest, candidate, oracle._oracle)

