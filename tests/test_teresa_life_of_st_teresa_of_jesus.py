from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei.teresa_life_of_st_teresa_of_jesus import (
    ConversionError,
    SOURCE_LOGICAL_PATH,
    TEI_RNG_PATH,
    convert_source,
    validate_tei,
)


ROOT = Path(__file__).resolve().parents[1]
TEI = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI}


def _tree(path: Path) -> etree._ElementTree:
    return etree.parse(str(path))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_teresa_route_reconstructs_retained_1904_witness(tmp_path: Path) -> None:
    output = tmp_path / "teresa.tei.xml"
    result = convert_source(SOURCE_LOGICAL_PATH, output, repository_root=ROOT)

    assert output.is_file()
    accounting = result.accounting
    assert accounting["archive_sha256"] == (
        "92b3442c0b2c04c206152c41b698bd464899ac078c2660afa83c2c751b17d274"
    )
    assert accounting["html_sha256"] == (
        "9aeeb297ddcd83e801b9782fd7c376af845491e3fd2a941a85530b0214ad3e74"
    )
    assert accounting["source_visible_text_sha256"] == accounting[
        "tei_visible_text_sha256"
    ]
    assert accounting["paragraph_count"] == 2403
    assert accounting["life_chapter_count"] == 40
    assert accounting["relation_count"] == 11
    assert accounting["note_reference_count"] == 730
    assert accounting["note_body_count"] == 730
    assert accounting["internal_link_count"] == 2166
    assert accounting["language_mark_count"] == 300
    assert accounting["latin_count"] == 191
    assert accounting["spanish_count"] == 95
    assert accounting["french_count"] == 13
    assert accounting["hebrew_count"] == 1
    assert accounting["typographic_break_count"] == 112
    assert accounting["printed_page_milestone_count"] == 0

    tree = _tree(output)
    relaxng = etree.RelaxNG(etree.parse(str(TEI_RNG_PATH)))
    assert relaxng.validate(tree), str(relaxng.error_log)
    assert validate_tei(tree)["tei_visible_text_sha256"] == accounting[
        "source_visible_text_sha256"
    ]
    assert len(tree.xpath("/t:TEI/t:text/t:body//t:div[@type='chapter']", namespaces=NS)) == 40
    assert len(tree.xpath("/t:TEI/t:text/t:back//t:div[@type='relation']", namespaces=NS)) == 11
    assert len(tree.xpath("/t:TEI/t:text/t:back/t:div[@type='index']", namespaces=NS)) == 1
    assert len(tree.xpath("//t:note[@place='end']", namespaces=NS)) == 730
    assert len(tree.xpath("//t:ref[@type='note']", namespaces=NS)) == 730
    assert len(tree.xpath("//t:pb", namespaces=NS)) == 0

    ids = tree.xpath("//@xml:id", namespaces=NS)
    assert len(ids) == len(set(ids))
    id_set = set(ids)
    assert all(
        target[1:] in id_set
        for target in tree.xpath("//t:ref[starts-with(@target, '#')]/@target", namespaces=NS)
    )
    front_text = " ".join(tree.xpath("/t:TEI/t:text/t:front//text()", namespaces=NS))
    assert "Third Edition Enlarged" in front_text
    assert "Benedict Zimmerman" in front_text
    assert "MCMIV" in front_text


def test_teresa_route_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.tei.xml"
    second = tmp_path / "second.tei.xml"
    first_result = convert_source(SOURCE_LOGICAL_PATH, first, repository_root=ROOT)
    second_result = convert_source(SOURCE_LOGICAL_PATH, second, repository_root=ROOT)

    assert first.read_bytes() == second.read_bytes()
    assert first_result.accounting == second_result.accounting


def test_teresa_cli_emits_deterministic_accounting_from_another_cwd(
    tmp_path: Path,
) -> None:
    output = tmp_path / "cli.tei.xml"
    accounting_output = tmp_path / "accounting.json"
    script = ROOT / "build" / "tei" / "teresa_life_of_st_teresa_of_jesus.py"
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
    assert accounting["life_chapter_count"] == 40
    assert accounting["relation_count"] == 11
    assert accounting["printed_page_milestone_count"] == 0
    assert accounting["document_sha256"] == _sha256(output)
    assert json.loads(accounting_output.read_text(encoding="utf-8")) == accounting


def test_teresa_validator_rejects_a_synthetic_unresolved_link() -> None:
    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    text = etree.SubElement(root, f"{{{TEI}}}text")
    body = etree.SubElement(text, f"{{{TEI}}}body")
    etree.SubElement(body, f"{{{TEI}}}ref", type="note", target="#missing")

    with pytest.raises(ConversionError, match="note reference count|unresolved|accounting"):
        validate_tei(etree.ElementTree(root))
