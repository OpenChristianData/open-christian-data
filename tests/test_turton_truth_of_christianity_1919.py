"""Focused contracts for Turton's ninth-edition Gutenberg candidate."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from build.tei.turton_truth_of_christianity_1919 import EXPECTED_SOURCE_SHA256,EXPECTED_SOURCE_TEXT_SHA256,SourceMismatchError,audit_source,build_candidate,resolve_source_path,write_determinism_report
ROOT=Path(__file__).resolve().parents[1];CONFIG=ROOT/"sources/structured-text/turton-truth-of-christianity-1919/config.json"
def test_config_binds_ninth_edition()->None:
    c=json.loads(CONFIG.read_text(encoding="utf-8"));assert c["gutenberg_id"]==42460 and c["original_publication_year"]==1919 and c["source_hash"]==f"sha256:{EXPECTED_SOURCE_SHA256}" and "Ninth edition" in c["source_edition"]
def test_package_and_container_exact()->None:
    a=audit_source(resolve_source_path(ROOT),repository_root=ROOT);assert len(a["package_hashes"])==8 and a["archive_member_hashes"]["pg42460-images.html"]==a["package_hashes"]["pg42460-images.html"] and len(a["archive_members"])==3
def test_source_census_structure_notes_and_terminal_matter()->None:
    a=audit_source(resolve_source_path(ROOT),repository_root=ROOT);assert a["source_text_characters"]==799259 and a["source_text_sha256"]==EXPECTED_SOURCE_TEXT_SHA256;assert a["chapters"]==25 and a["footnotes"]==490 and a["footnote_references"]==490 and a["page_markers"]==514;assert a["tables"]==65 and a["rows"]==1043 and a["cells"]==3244;assert a["source_ids"]==1526 and a["internal_targets"]==3424 and not a["unresolved_internal_targets"];assert len(a["transcribers_notes"])==2 and "PRINTED IN GREAT BRITAIN" in a["printer_line"] and a["project_gutenberg_end_marker"]=="*** END OF THE PROJECT GUTENBERG EBOOK 42460 ***"
def test_candidate_valid_complete_deterministic(tmp_path:Path,monkeypatch:pytest.MonkeyPatch)->None:
    s=resolve_source_path(ROOT);a=tmp_path/"a/c.xml";av=tmp_path/"a/v.json";b=tmp_path/"b/c.xml";bv=tmp_path/"b/v.json";ra=build_candidate(s,a,av,repository_root=ROOT);rb=build_candidate(s,b,bv,repository_root=ROOT);assert ra==rb and a.read_bytes()==b.read_bytes() and av.read_bytes()==bv.read_bytes();assert ra["tei_p5_relaxng_valid"] and ra["source_candidate_text_match"] and ra["candidate_text_sha256"]==EXPECTED_SOURCE_TEXT_SHA256;assert ra["part_divisions"]==3 and ra["chapter_divisions"]==25 and ra["candidate_tag_counts"]["note"]==490 and not ra["unresolved_internal_targets"];monkeypatch.chdir(tmp_path);d=write_determinism_report(a,av,b,bv,tmp_path/"d.json",repository_root=ROOT);assert d["candidate_bytes_equal"] and d["validation_bytes_equal"] and d["different_working_directory"]
def test_mutation_rejected_before_write(tmp_path:Path)->None:
    s=resolve_source_path(ROOT);m=tmp_path/"m.htm";m.write_bytes(s.read_bytes().replace(b"NINTH EDITION",b"NINTH EDITION!",1));c=tmp_path/"c.xml";v=tmp_path/"v.json"
    with pytest.raises(SourceMismatchError,match="source SHA-256"):build_candidate(m,c,v,repository_root=ROOT)
    assert not c.exists() and not v.exists()
