"""Focused exact-source paired-section and independent-checker mutations."""
import copy
from pathlib import Path

import pytest

from ocd_kernel.projection.categories import chinook_hymns as adapter

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / ".tmp_audit/chinook-acceptance-20261002-v1"
EDITION = Path("library/works/l744-pg33105-chinook-hymns/forms/pg33105-complete-text/editions/pg33105-second-edition-1889-revised-enlarged")

@pytest.fixture(scope="module")
def package():
    master = STAGE / EDITION / "master.tei.xml"
    if not master.is_file():
        master = ROOT / EDITION / "master.tei.xml"
    metadata = dict(retained_path=ROOT / "raw/gutenberg/33105/html/pg33105-images.html",
        identity=dict(work_id=adapter.WORK_ID,textual_form_id="pg33105-complete-text",edition_id=EDITION.name),
        language="mul",representation_revision="pg33105-retained-complete-technical-v1",
        edition_title="Second edition. Revised and Enlarged. (1889)")
    return master, metadata, adapter.project_chinook_document(master, **metadata)

def test_actual_master_has_twenty_paired_sections_and_full_source_verse_count(package):
    master, metadata, result = package
    assert len(result["rows"]) == 20
    assert sum(len(row["stanzas"]) for row in result["rows"]) == 195
    assert all(len(row["sections"]) == 2 and row["sections"][1]["label"] == "TRANSLATION." for row in result["rows"])
    assert adapter.verify_chinook_document(master,result["rows"],result["receipt"],**metadata) == []

def test_independent_observer_runs_when_producer_traversal_is_disabled(package, monkeypatch):
    master, metadata, result = package
    def forbidden(*args, **kwargs):
        raise AssertionError("Producer invoked by checker")
    monkeypatch.setattr(adapter,"_rows_master",forbidden)
    monkeypatch.setattr(adapter,"_master_section",forbidden)
    assert adapter.verify_chinook_document(master,result["rows"],result["receipt"],**metadata) == []

@pytest.mark.parametrize("mutation",["lyric","translation","section-label","order","stanza-number","tune","first-line","omit","invent"])
def test_independent_source_observer_rejects_changed_relationship_or_wording(package,mutation):
    master,metadata,result = package
    rows = copy.deepcopy(result["rows"])
    if mutation == "lyric": rows[0]["sections"][0]["stanzas"][0]["lines"][0] += " changed"
    elif mutation == "translation": rows[0]["sections"][1]["stanzas"][0]["lines"][0] += " changed"
    elif mutation == "section-label": rows[0]["sections"][1]["label"] = "ORIGINAL."
    elif mutation == "order": rows[0],rows[1] = rows[1],rows[0]
    elif mutation == "stanza-number": rows[0]["stanzas"][0]["number"] += 1
    elif mutation == "tune": rows[0]["tune"] = "Invented tune"
    elif mutation == "first-line": rows[0]["first_line"] += " changed"
    elif mutation == "omit": rows.pop()
    else: rows.append(copy.deepcopy(rows[-1]))
    errors = adapter.verify_chinook_document(master,rows,result["receipt"],**metadata)
    assert any("independently observed HTML" in error for error in errors)

def test_changed_master_body_rejected_even_when_projected_rows_are_unchanged(package,monkeypatch):
    master,metadata,result = package
    raw = master.read_bytes().replace(b"Jesus chako",b"Jesus changed",1)
    original_read = Path.read_bytes
    monkeypatch.setattr(Path,"read_bytes",lambda self: raw if self == master else original_read(self))
    errors = adapter.verify_chinook_document(master,result["rows"],result["receipt"],**metadata)
    assert any("whole reconstructed body differs" in error for error in errors)

def test_changed_retained_source_is_rejected(package,monkeypatch):
    master,metadata,result = package
    source = metadata["retained_path"]
    raw = source.read_bytes()+b" "
    original_read = Path.read_bytes
    monkeypatch.setattr(Path,"read_bytes",lambda self: raw if self == source else original_read(self))
    errors = adapter.verify_chinook_document(master,result["rows"],result["receipt"],**metadata)
    assert any("retained HTML bytes differ" in error for error in errors)
