from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.newman_development_christian_doctrine import (
    ConversionError,
    SOURCE_LOGICAL_PATH,
    TEI_RNG_PATH,
    convert_source,
    validate_tei,
)


ROOT = Path(__file__).resolve().parents[1]
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = {"t": TEI}
XML_ID = f"{{{XML}}}id"
XML_LANG = f"{{{XML}}}lang"


def _tree(path: Path) -> etree._ElementTree:
    return etree.parse(str(path))


def test_newman_route_reconstructs_the_retained_source_with_accounting(tmp_path: Path) -> None:
    output = tmp_path / "newman.tei.xml"
    result = convert_source(SOURCE_LOGICAL_PATH, output, repository_root=ROOT)

    assert output.is_file()
    assert result.accounting["archive_sha256"] == (
        "8335ab4ef21bc0c17169eb8562d3271f49595ce851948476a32ce9ae8d7c22f6"
    )
    assert result.accounting["printed_page_anchor_count"] == 458
    assert result.accounting["note_reference_count"] == 401
    assert result.accounting["note_body_count"] == 400
    assert result.accounting["greek_span_count"] == 26
    assert result.accounting["source_ins_greek_count"] == 26
    assert result.accounting["source_visible_text_sha256"] == result.accounting[
        "tei_visible_text_sha256"
    ]
    assert result.accounting["included_source_paragraph_count"] == 1560
    assert result.accounting["source_empty_layout_paragraph_count"] == 5
    assert result.accounting["source_page_only_paragraph_count"] == 31
    assert result.accounting["text_paragraph_count"] == 1524
    assert result.accounting["extra_reference_condition"] == {
        "source_target": "Footnote_315_3_296",
        "reference_count": 2,
        "unique_note_body_count": 1,
    }

    tree = _tree(output)
    relaxng = etree.RelaxNG(etree.parse(str(TEI_RNG_PATH)))
    assert relaxng.validate(tree), str(relaxng.error_log)
    validated = validate_tei(tree)
    assert validated["printed_page_anchor_count"] == 458
    assert validated["note_reference_count"] == 401
    assert validated["note_body_count"] == 400
    assert validated["greek_span_count"] == 26
    assert tree.xpath("count(/t:TEI/t:text/t:front/t:div[@type='dedication'])", namespaces=NS) == 1
    assert tree.xpath("count(/t:TEI/t:text/t:front/t:div[@type='preface'])", namespaces=NS) == 1
    assert tree.xpath("count(/t:TEI/t:text/t:front/t:div[@type='advertisement'])", namespaces=NS) == 1
    assert tree.xpath("count(/t:TEI/t:text/t:front/t:div[@type='contents'])", namespaces=NS) == 1
    assert tree.xpath("count(/t:TEI/t:text/t:body/t:div[@type='part'])", namespaces=NS) == 2
    assert tree.xpath("count(/t:TEI/t:text/t:body//t:div[@type='chapter'])", namespaces=NS) == 12
    assert tree.xpath("count(/t:TEI/t:text/t:body//t:div[@type='section'])", namespaces=NS) == 29
    assert tree.xpath("count(/t:TEI/t:text/t:body//t:div[@type='subsection'])", namespaces=NS) == 21
    assert tree.xpath("count(/t:TEI/t:text/t:front//t:table[@type='contents'])", namespaces=NS) == 1
    assert tree.xpath("count(/t:TEI/t:text//t:quote)", namespaces=NS) >= 3
    assert tree.xpath("count(/t:TEI/t:text//t:list)", namespaces=NS) >= 0

    assert len(tree.xpath("//t:pb", namespaces=NS)) == 458
    refs = tree.xpath("//t:ref[@type='note']", namespaces=NS)
    notes = tree.xpath("//t:note[@place='end']", namespaces=NS)
    assert len(refs) == 401
    assert len(notes) == 400
    assert len({node.get(XML_ID) for node in notes}) == 400
    target_counts = Counter(node.get("target", "").removeprefix("#") for node in refs)
    duplicate_targets = [target for target, count in target_counts.items() if count == 2]
    assert len(duplicate_targets) == 1
    duplicate_note = next(note for note in notes if note.get("n") == "[315:3]")
    assert duplicate_targets == [duplicate_note.get(XML_ID)]

    greek = tree.xpath(
        "//t:foreign[@xml:lang='grc' and @ana='urn:ocd:greek-transliteration']",
        namespaces=NS,
    )
    assert len(greek) == 26
    assert all(node.get("n") for node in greek)
    assert len(tree.xpath("//t:hi[@rend='italic']", namespaces=NS)) == 380
    assert len(tree.xpath("//t:hi[@rend='smallcaps']", namespaces=NS)) == 13

    all_ids = tree.xpath("//@xml:id", namespaces=NS)
    assert len(all_ids) == len(set(all_ids))
    assert all(target.removeprefix("#") in set(all_ids) for target in tree.xpath("//t:ref/@target", namespaces=NS))


def test_newman_route_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.tei.xml"
    second = tmp_path / "second.tei.xml"
    first_result = convert_source(SOURCE_LOGICAL_PATH, first, repository_root=ROOT)
    second_result = convert_source(SOURCE_LOGICAL_PATH, second, repository_root=ROOT)

    assert first.read_bytes() == second.read_bytes()
    assert first_result.accounting == second_result.accounting


def test_newman_cli_accepts_logical_source_path_and_emits_compact_accounting(tmp_path: Path) -> None:
    output = tmp_path / "cli.tei.xml"
    accounting_output = tmp_path / "accounting.json"
    completed = subprocess.run(
        [
            sys.executable,
            "build/tei/newman_development_christian_doctrine.py",
            SOURCE_LOGICAL_PATH,
            str(output),
            "--accounting",
            "--accounting-output",
            str(accounting_output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    accounting = json.loads(completed.stdout)
    assert output.is_file()
    assert accounting["note_reference_count"] == 401
    assert accounting["note_body_count"] == 400
    assert accounting["printed_page_anchor_count"] == 458
    assert accounting["tei_p5_relaxng_valid"] is True
    assert json.loads(accounting_output.read_text(encoding="utf-8")) == accounting


def test_newman_validator_rejects_a_synthetic_link_target_failure() -> None:
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    text = etree.SubElement(root, f"{{{TEI}}}text")
    body = etree.SubElement(text, f"{{{TEI}}}body")
    etree.SubElement(body, f"{{{TEI}}}ref", type="note", target="#missing")

    with pytest.raises(ConversionError, match="TEI root|TEI header|note reference count|unresolved"):
        validate_tei(etree.ElementTree(root))
