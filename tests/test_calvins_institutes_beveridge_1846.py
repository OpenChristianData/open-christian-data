from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from lxml import etree
import pytest

from build.tei import calvins_institutes_beveridge_1846 as calvin


NS = {"t": calvin.TEI_NS}


@pytest.fixture(scope="module")
def converted(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, object], etree._ElementTree]:
    output = tmp_path_factory.mktemp("calvin-beveridge") / "candidate.tei.xml"
    result = calvin.convert_source(calvin.SOURCE_LOGICAL_PATH, output)
    return output, result.accounting, etree.parse(str(output))


def test_exact_retained_sources_and_complete_epub_accounting(
    converted: tuple[Path, dict[str, object], etree._ElementTree],
) -> None:
    output, accounting, tree = converted

    assert hashlib.sha256(output.read_bytes()).hexdigest() == accounting["document_sha256"]
    assert accounting["source_sha256"] == calvin.SOURCE_SHA256
    assert accounting["source_html_sha256"] == calvin.SOURCE_HTML_SHA256
    assert accounting["ebook_pdf_sha256"] == calvin.EBOOK_PDF_SHA256
    assert accounting["facsimile_sha256"] == calvin.FACSIMILE_SHA256
    assert accounting["chapter_count"] == 80
    assert accounting["argument_count"] == 4
    assert accounting["section_div_count"] == 2822
    assert accounting["note_count"] == accounting["note_reference_count"] == 660
    assert accounting["internal_target_count"] == 3865
    assert accounting["tei_p5_relaxng_valid"] is True
    assert calvin.validate_tei(tree)["facsimile_surface_count"] == 14


def test_structure_title_matter_books_indexes_and_terminal_matter_are_retained(
    converted: tuple[Path, dict[str, object], etree._ElementTree],
) -> None:
    _, _, tree = converted
    visible = " ".join(" ".join(tree.getroot().itertext()).split())

    assert "THE INSTITUTES OF THE CHRISTIAN RELIGION" in visible
    assert "INSTITUTES of THE CHRISTIAN RELIGION By JOHN CALVIN Translated by HENRY BEVERIDGE" in visible
    assert "WM. B. EERDMANS PUBLISHING COMPANY Grand Rapids, Michigan" in visible
    assert "Edinburgh: Calvin Translation Society, 1846; two volumes in one; OLL electronic edition" in visible
    assert "PREFATORY ADDRESS" in visible and "FRANCIS" in visible
    assert "Introduction By The Rev. John Murray" in visible
    assert "TABLE I.: OF PASSAGES FROM THE HOLY SCRIPTURES, AND FROM THE APOCRYPHA" in visible
    assert "ONE HUNDRED APHORISMS" in visible
    assert "The One Hundred Aphorisms" in visible
    assert "have been kindly furnished by the Rev. William Pringle of Auchterarder" in visible

    books = tree.xpath(
        "//t:head[starts-with(normalize-space(.), 'BOOK FIRST') or "
        "starts-with(normalize-space(.), 'BOOK SECOND') or "
        "starts-with(normalize-space(.), 'BOOK THIRD') or "
        "starts-with(normalize-space(.), 'BOOK FOURTH')]",
        namespaces=NS,
    )
    chapters = tree.xpath("//t:div[@type='chapter']", namespaces=NS)
    chapter_arguments = tree.xpath("//t:div[@type='chapter']/t:argument", namespaces=NS)
    assert len(books) == 4
    assert len(chapters) == 80
    assert len(chapter_arguments) == 71
    assert len(tree.xpath("//t:table", namespaces=NS)) == 67
    assert len(tree.xpath("//t:div[@type='endnote']", namespaces=NS)) == 660


def test_epub_and_facsimile_layers_have_independent_lossless_digests(
    converted: tuple[Path, dict[str, object], etree._ElementTree],
) -> None:
    _, accounting, tree = converted

    assert accounting["epub_visible_text_sha256"] == accounting["tei_epub_visible_text_sha256"]
    assert accounting["facsimile_index_extracted_text_sha256"] == accounting["tei_facsimile_index_text_sha256"]
    assert accounting["facsimile_index_printed_pages"] == list(range(691, 705))
    assert accounting["facsimile_index_pdf_pages"] == list(range(1298, 1312))
    assert accounting["electronic_source_omission"] == "General Index, facsimile printed pp. 691-704"

    index = tree.xpath("//t:div[@xml:id='facsimile-general-index-transcription']", namespaces=NS)[0]
    assert index.get("subtype") == "facsimile-searchable-text-extraction"
    assert index.xpath("./t:ab/@cert", namespaces=NS) == ["low"] * 14
    assert index.xpath("./t:pb/@n", namespaces=NS) == [str(page) for page in range(691, 705)]
    assert index.xpath("./t:pb/@facs", namespaces=NS)[-1] == "#facsimile-index-p704"
    provenance = " ".join(index.xpath("string(./t:note[@type='provenance'])", namespaces=NS).split())
    assert "uncorrected embedded searchable-text extraction" in provenance
    assert "not an exact human transcription" in provenance


def test_output_is_byte_deterministic_from_a_different_cwd(
    tmp_path: Path,
    converted: tuple[Path, dict[str, object], etree._ElementTree],
) -> None:
    first, first_accounting, _ = converted
    second = tmp_path / "second.tei.xml"
    accounting_path = tmp_path / "accounting.json"
    script = Path(calvin.__file__).resolve()

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            calvin.SOURCE_LOGICAL_PATH,
            str(second),
            "--accounting-output",
            str(accounting_path),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout == ""
    assert first.read_bytes() == second.read_bytes()
    assert json.loads(accounting_path.read_text(encoding="utf-8")) == first_accounting


def test_route_rejects_a_different_expression(tmp_path: Path) -> None:
    with pytest.raises(calvin.ConversionError, match="accepts only"):
        calvin.convert_source("raw/project-gutenberg/45001.txt", tmp_path / "wrong.xml")
