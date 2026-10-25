import hashlib
import json

import pytest

from build.lib.reconstruction_text_screen import _screen
from build.lib.text_lint import lint_json_strings


def test_collection_screen_resolves_bound_records_once_and_rejects_escaping_paths(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from build.lib import reconstruction_text_screen as screen

    source = tmp_path / "source.toml"
    source.write_text('quote="Retained text"', encoding="utf8")
    candidate = tmp_path / "content.tei.xml"
    candidate.write_text("<TEI/>", encoding="utf8")
    authorities = tuple(dict(name=f"source-{i}", path="source.toml", sha256="a" * 64, role="primary-source") for i in range(2000))
    seen = []
    verified = []
    manifest = SimpleNamespace(repository_root=tmp_path, record={"authorities": authorities}, sha256="b" * 64, verify=lambda: verified.append("manifest"))
    package = SimpleNamespace(path=tmp_path, sha256="c" * 64, member_bytes=lambda name: candidate.read_bytes(), verify_integrity=lambda: verified.append("candidate"))
    monkeypatch.setattr(screen, "_screen", lambda path, **binding: seen.append((path, binding)) or {"status": "screened"})
    result = screen.screen_reconstruction(manifest, package)
    assert len(seen) == 2001 and len(result["inputs"]) == 2001
    assert all(path == source for path, _ in seen[:-1])
    assert verified == ["manifest", "candidate"]
    manifest.record = {"authorities": (dict(authorities[0], path="../outside.toml"),)}
    with pytest.raises(ValueError, match="outside|escapes|relative"):
        screen.screen_reconstruction(manifest, package)


def test_all_json_strings_have_exact_escaped_pointers_and_preserve_bytes(tmp_path):
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"a/b~c": ["\ufffd", "", 4, None], "other": "text"}), encoding="utf-8")
    original = path.read_bytes()
    report = lint_json_strings(path)
    assert report["coverage"]["scope"] == "all_json_string_values"
    assert report["coverage"]["units"] == 3
    assert report["observations"][0]["locator"] == "/a~1b~0c/0"
    assert report["observations"][0]["text"] == "\ufffd"
    assert path.read_bytes() == original


@pytest.mark.parametrize("raw", ['{"a":"x","a":"y"}', '{"a":NaN}'])
def test_ambiguous_json_values_do_not_receive_complete_screen(tmp_path, raw):
    path = tmp_path / "source.json"
    path.write_text(raw)
    result = _screen(path, reference="source.json", expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), role="primary-source")
    assert result["status"] == "not_screened"
    assert result["reason"]


def test_source_dtd_needs_reader_but_candidate_screen_failure_blocks(tmp_path):
    path = tmp_path / "source.xml"
    path.write_text('<!DOCTYPE d [<!ENTITY e SYSTEM "file:///missing">]><d>&e;</d>')
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    assert _screen(path, reference="source.xml", expected_sha256=pin, role="primary-source")["status"] == "not_screened"
    with pytest.raises(ValueError, match="Candidate TEI character screening failed"):
        _screen(path, reference="package/content.tei.xml", expected_sha256=pin, role="candidate-tei")


def test_supported_text_drift_fails_instead_of_becoming_an_observation(tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("source")
    with pytest.raises(ValueError, match="differs from its binding"):
        _screen(path, reference="source.txt", expected_sha256="0" * 64, role="primary-source")
