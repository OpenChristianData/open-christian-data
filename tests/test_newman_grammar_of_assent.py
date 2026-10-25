from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.newman_grammar_of_assent import (
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


def _tree(path: Path) -> etree._ElementTree:
    return etree.parse(str(path))


def test_grammar_route_reconstructs_retained_1874_witness(tmp_path: Path) -> None:
    output = tmp_path / "grammar.tei.xml"
    result = convert_source(SOURCE_LOGICAL_PATH, output, repository_root=ROOT)

    assert output.is_file()
    assert result.accounting["archive_sha256"] == (
        "27f6e1c54a0b5ac43b15b1ac26dabeff05a78aa27e2e2989f1633093200cedec"
    )
    assert result.accounting["html_sha256"] == (
        "798d867ac82ef0df1f2496cceaf06aea6fef8160f1c947dc95e4f7b2ae6def08"
    )
    assert result.accounting["source_visible_text_sha256"] == result.accounting[
        "tei_visible_text_sha256"
    ]
    assert result.accounting["printed_page_anchor_count"] == 491
    assert result.accounting["note_reference_count"] == 56
    assert result.accounting["note_body_count"] == 56
    assert result.accounting["source_paragraph_count"] == 794
    assert result.accounting["source_emphasis_count"] == 94
    assert result.accounting["source_style_italic_count"] == 312
    assert result.accounting["italic_mark_count"] == 406
    assert result.accounting["foreign_count"] == 135
    assert result.accounting["latin_count"] == 102
    assert result.accounting["greek_count"] == 6
    assert result.accounting["unmarked_foreign_count"] == 27
    assert result.accounting["inline_quote_count"] == 829
    assert result.accounting["block_quote_count"] == 7
    assert result.accounting["line_group_count"] == 5
    assert result.accounting["line_count"] == 13

    tree = _tree(output)
    relaxng = etree.RelaxNG(etree.parse(str(TEI_RNG_PATH)))
    assert relaxng.validate(tree), str(relaxng.error_log)
    validated = validate_tei(tree)
    assert validated["part_count"] == 2
    assert validated["chapter_count"] == 10
    assert validated["section_count"] == 20
    assert validated["contents_item_count"] == 35
    assert tree.xpath(
        "count(/t:TEI/t:text/t:front/t:div[@type='title-page'])", namespaces=NS
    ) == 1
    assert tree.xpath(
        "count(/t:TEI/t:text/t:front/t:div[@type='contents'])", namespaces=NS
    ) == 1
    assert tree.xpath(
        "count(/t:TEI/t:text/t:front/t:div[@type='dedication'])", namespaces=NS
    ) == 1
    assert tree.xpath(
        "count(/t:TEI/t:text/t:back/t:div[@type='terminal-note'])", namespaces=NS
    ) == 1
    assert tree.xpath(
        "count(/t:TEI/t:text/t:back/t:div[@type='footnotes'])", namespaces=NS
    ) == 1
    assert len(tree.xpath("//t:pb", namespaces=NS)) == 491
    assert len(tree.xpath("//t:ref[@type='note']", namespaces=NS)) == 56
    assert len(tree.xpath("//t:note[@place='end']", namespaces=NS)) == 56
    assert len(tree.xpath("//t:foreign[@xml:lang='el']", namespaces=NS)) == 6
    assert len(tree.xpath("//t:hi[contains(concat(' ', @rend, ' '), ' smallcaps ')]", namespaces=NS)) == 4
    assert len(tree.xpath("//t:milestone[@unit='source-horizontal-rule']", namespaces=NS)) == 13

    ids = tree.xpath("//@xml:id", namespaces=NS)
    assert len(ids) == len(set(ids))
    id_set = set(ids)
    assert all(
        target.removeprefix("#") in id_set
        for target in tree.xpath("//t:ref[starts-with(@target, '#')]/@target", namespaces=NS)
    )
    title_text = " ".join(
        tree.xpath("/t:TEI/t:text/t:front/t:div[@type='title-page']//text()", namespaces=NS)
    )
    assert "Burns, Oates, & Co." in title_text
    assert "1874" in title_text


def test_grammar_route_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.tei.xml"
    second = tmp_path / "second.tei.xml"
    first_result = convert_source(SOURCE_LOGICAL_PATH, first, repository_root=ROOT)
    second_result = convert_source(SOURCE_LOGICAL_PATH, second, repository_root=ROOT)

    assert first.read_bytes() == second.read_bytes()
    assert first_result.accounting == second_result.accounting


def test_grammar_cli_emits_deterministic_accounting_from_another_cwd(tmp_path: Path) -> None:
    output = tmp_path / "cli.tei.xml"
    accounting_output = tmp_path / "accounting.json"
    script = ROOT / "build" / "tei" / "newman_grammar_of_assent.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            SOURCE_LOGICAL_PATH,
            str(output),
            "--accounting",
            "--accounting-output",
            str(accounting_output),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    accounting = json.loads(completed.stdout)
    assert output.is_file()
    assert accounting["tei_p5_relaxng_valid"] is True
    assert accounting["printed_page_anchor_count"] == 491
    assert accounting["note_reference_count"] == 56
    assert accounting["document_sha256"] == result_hash(output)
    assert json.loads(accounting_output.read_text(encoding="utf-8")) == accounting


def result_hash(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_grammar_validator_rejects_a_synthetic_unresolved_link() -> None:
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    text = etree.SubElement(root, f"{{{TEI}}}text")
    body = etree.SubElement(text, f"{{{TEI}}}body")
    etree.SubElement(body, f"{{{TEI}}}ref", type="note", target="#missing")

    with pytest.raises(ConversionError, match="note reference count|unresolved|accounting"):
        validate_tei(etree.ElementTree(root))
