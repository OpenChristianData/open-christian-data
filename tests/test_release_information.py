"""Publication events and real license conditions survive the reading templates."""
import hashlib
from pathlib import Path

import pytest

from build.tools.release_information import READING_COPY, compact_source_sections, edition_information, publication_from_header, publication_from_notice, publication_text, reader_paragraphs
from ocd_kernel.library._common import PipelineError


def test_print_publication_is_not_the_electronic_creation_date():
    source = b'<ThML><ThML.head><printSourceInfo><published>York: Publisher, 1795</published></printSourceInfo><electronicEdInfo><DC.Date>2005</DC.Date></electronicEdInfo></ThML.head></ThML>'
    result = publication_from_header(source)
    assert result["date"] == ["1795"] and result["publisher"] == ["Publisher"]
    assert "2005" not in str(result)


def test_source_volume_publication_and_editors_keep_their_scope():
    source = b'<TEI><teiHeader><fileDesc><publicationStmt><date>2016</date></publicationStmt><sourceDesc><biblFull><titleStmt><title>Source volume</title><editor>A. Editor</editor></titleStmt><publicationStmt><pubPlace>Weimar</pubPlace><publisher>Boehlau</publisher><date>1955</date></publicationStmt></biblFull></sourceDesc></fileDesc></teiHeader></TEI>'
    result = publication_from_header(source)
    assert result["scope"] == "source-volume"
    assert result["date"] == ["1955"] and result["editors"] == ["A. Editor"]
    assert publication_text(result) == "Weimar: Boehlau, 1955"


def test_declared_header_encoding_is_preserved():
    source = '<?xml version="1.0" encoding="ISO-8859-1"?><ThML><printSourceInfo><published>M\u00fcnchen: Publisher, 1900</published></printSourceInfo></ThML>'.encode('latin-1')
    assert publication_from_header(source)["place"] == ["M\u00fcnchen"]


@pytest.mark.parametrize("wrapper", ["```text\n{terms}\n```", "START: FULL LICENSE\n\n{terms}"])
def test_license_text_is_verbatim_and_actual_conditions_are_preserved(wrapper):
    terms = "This retained license does not grant other publication rights.\nNo CC0 dedication is made."
    block = wrapper.format(terms=terms)
    original = "# Work\n\nCredit A. Translator.\n\nHuman acceptance, rights clearance, and publication remain separate.\n\nDo not sell CCEL files or derivatives of their formatting.\n\n" + block + "\n"
    sections, audit = reader_paragraphs(original)
    assert sections["License text"] == [block]
    assert "Do not sell CCEL files or derivatives of their formatting." in sections["Reuse"]
    assert any("A. Translator" in p for p in sections["Credits"])
    assert not any("Human acceptance" in p for values in sections.values() for p in values)
    assert any(a["action"] == "verbatim-license" for a in audit)


def test_primary_source_change_fails(tmp_path):
    raw = b'<ThML><printSourceInfo><published>1795</published></printSourceInfo></ThML>'
    (tmp_path / "source.xml").write_bytes(raw)
    accepted = {"source": {"source_path": "source.xml", "source_sha256": hashlib.sha256(raw).hexdigest()}}
    assert edition_information(tmp_path, accepted, {}, {})["publication"]["statement"] == "1795"
    (tmp_path / "source.xml").write_bytes(b"changed")
    with pytest.raises(PipelineError, match="primary source changed"):
        edition_information(tmp_path, accepted, {}, {})


def test_editorial_addendum_after_license_is_not_mistaken_for_license_text():
    text = "START: FULL LICENSE\n\nKeep this license exactly.\n\n## Later preparation\n\nHuman acceptance, rights clearance, and publication remain separate.\n"
    sections, _ = reader_paragraphs(text)
    assert sections["License text"] == ["START: FULL LICENSE\n\nKeep this license exactly."]
    assert not sections["Notes about this copy"]


def test_full_license_marker_inside_fence_does_not_split_the_fence():
    block = "```text\nSTART: FULL LICENSE\n\nKeep these terms unchanged.\n```"
    sections, _ = reader_paragraphs("# Work\n\n" + block + "\n\nA copy note.\n")
    assert sections["License text"] == [block]
    assert sections["Notes about this copy"] == ["A copy note."]


def test_existing_imprint_statement_is_carried_without_guessing_a_printing_year():
    text = "Printed source: A source volume, Publisher, 1910. This derivative selects one letter.\n"
    result = publication_from_notice(text, containing=True)
    assert result == {"scope": "source-volume", "statement": "A source volume, Publisher, 1910."}
    assert publication_from_notice("First composed in 1650; download created in 2026.", containing=False) == {}


def test_provider_template_keeps_material_omissions_and_actual_reuse_conditions():
    row = {"work_id": "boethius", "license": "Public domain (United States)",
           "digital_source": {"provider": "Christian Classics Ethereal Library"}, "source_credits": [{"name": "A. Person", "role": "Markup"}]}
    sections, _ = reader_paragraphs("# Boethius\n\nThe companion Consolation is not included in this copy.\n\nHuman acceptance, rights clearance, and publication remain separate.\n")
    result = compact_source_sections(row, sections)
    assert any("not included" in p for p in result["Notes about this copy"])
    assert any("A. Person" in p for p in result["Credits"])
    assert "Do not sell CCEL files or derivatives of their formatting." in result["Reuse"][0]


def test_internal_selection_prefix_is_removed_without_losing_publication_facts():
    sections, _ = reader_paragraphs("The private offline text selection is a three-volume biography, published in New York in 1872.\n")
    assert sections["Notes about this copy"] == ["This edition is a three-volume biography, published in New York in 1872."]


def test_reviewed_copy_edits_remove_stale_status_without_touching_quoted_terms():
    stale = "This snapshot has not been published."
    literal = "```text\n" + stale + "\nKeep this credit.\n```"
    sections, audit = reader_paragraphs(stale + "\n\n" + literal)
    assert not sections["Notes about this copy"]
    assert sections["License text"] == [literal]
    assert {"action": "edit-public-copy", "before": stale, "after": ""} in audit


def test_reviewed_copy_edits_keep_named_credits_omissions_and_sharealike():
    def edited(fragment):
        original = next(text for text in READING_COPY["paragraphs"] if text.startswith(fragment))
        sections, _ = reader_paragraphs(original)
        return " ".join(text for values in sections.values() for text in values)

    text = edited("The historical Spurgeon sermon text")
    assert all(name in text for name in ("Emmett O'Donnell", "Benry Yip", "Spurgeon Archive"))
    text = edited("This private offline text selection contains 3,548")
    assert "708 and 3032" in text and "written permission" in text
    text = edited("Historical edition text and Wikisource contributor")
    assert "CC BY-SA 4.0" in text and "ShareAlike" in text


def test_contributor_tables_keep_rows_and_source_revision_links():
    table = "| Source | Contributor |\n|---|---|\n| [Page](https://example.org/?oldid=123) | A. Person |"
    sections, _ = reader_paragraphs(table)
    assert sections["Credits"] == [table]


def test_bibliography_display_tightens_punctuation_without_changing_metadata():
    publication = {"statement": "Chicago:: Publisher,, 1893."}
    assert publication_text(publication) == "Chicago: Publisher, 1893."
    assert publication["statement"] == "Chicago:: Publisher,, 1893."
    assert publication_text({"statement": "Boston: :: Publisher,, 1789."}) == "Boston: Publisher, 1789."
    assert publication_text({"statement": "New-Haven; :: Publisher,, 1772."}) == "New-Haven: Publisher, 1772."
