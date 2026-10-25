import io
import json
import zipfile

import pytest

from build.tools.lint_tei_tree import is_tei, scan_roots


@pytest.mark.parametrize("raw,expected", [(b'<TEI xmlns="http://www.tei-c.org/ns/1.0"/>', True), (b'<TEI.2/>', True), (b'<teiCorpus/>', True), (b'<other/>', False)])
def test_actual_root_identifies_tei_without_filename_assumptions(raw, expected):
    assert is_tei(io.BytesIO(raw)) is expected


@pytest.mark.parametrize("encoding", ["utf-32", "utf-32-be", "utf-16", "shift_jis", "windows-1252"])
def test_root_classifier_handles_declared_encodings(encoding):
    raw = f'<?xml version="1.0" encoding="{encoding}"?><TEI><p>text</p></TEI>'.encode(encoding)
    assert is_tei(io.BytesIO(raw))


def test_classifier_stops_at_root_and_bounds_prolog():
    stream = io.BytesIO(b'<TEI>' + b'not parsed' * 20000)
    assert is_tei(stream)
    assert stream.tell() == 16384
    with pytest.raises(ValueError, match="inspection limit"):
        is_tei(io.BytesIO(b'<!--' + b'x' * (1024 * 1024) + b'--><TEI/>'))


def test_classifier_does_not_retrieve_external_subset():
    assert is_tei(io.BytesIO(b'<!DOCTYPE TEI SYSTEM "file:///does-not-exist.dtd"><TEI/>'))


def test_tree_and_zip_duplicates_keep_all_paths_without_double_counting(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    raw = '<TEI><text><body><p>bad \ufffd</p></body></text></TEI>'.encode()
    (root / "unknown.XML").write_bytes(raw)
    (root / "duplicate.tei.xml").write_bytes(raw)
    (root / "not-tei.xml").write_bytes(b'<other/>')
    with zipfile.ZipFile(root / "retained.zip", "w") as archive:
        archive.writestr("../unsafe-name.xml", raw)
        archive.writestr("other.xml", '<other/>')
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    summary = scan_roots([root, root], tmp_path / "report")
    assert summary["status"] == "completed"
    assert summary["tei_paths"] == 3
    assert summary["unique_screened"] == 1
    assert sum(summary["observation_counts_unique_content"].values()) == 1
    rows = json.loads((tmp_path / "report/files.json").read_bytes())
    assert sum(r["status"] == "duplicate" for r in rows) == 2
    assert any("#entry=0" in r["path"] for r in rows)
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    assert not (tmp_path / "unsafe-name.xml").exists()


def test_unsupported_dtd_archives_and_unknown_xml_are_explicit_gaps(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "witness.xml").write_bytes(b'<!DOCTYPE TEI [<!ENTITY e SYSTEM "https://invalid.invalid/no-fetch">]><TEI>&e;</TEI>')
    (root / "broken.xml").write_bytes(b'not XML')
    (root / "old.tar").write_bytes(b'archive')
    summary = scan_roots([root, tmp_path / "absent"], tmp_path / "report")
    assert summary["status"] == "partial"
    assert summary["unique_not_screened"] == 1
    assert len(summary["gaps"]) == 3


def test_dependency_exclusions_are_reported(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "node_modules").mkdir()
    (root / "node_modules/fixture.xml").write_text('<TEI/>')
    summary = scan_roots([root], tmp_path / "report")
    assert summary["tei_paths"] == 0
    assert summary["excluded"][0]["reason"] == "development dependency or Git metadata"
