from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from build.lib.text_lint import lint_file


def scan(tmp_path, text, **kwargs):
    path = tmp_path / "witness.txt"
    path.write_bytes(text.encode("utf-8"))
    return lint_file(path, **kwargs)


def test_zwingli_observation_is_not_an_editorial_verdict(tmp_path):
    text = "the spirite of of the sonne of God"
    report = scan(tmp_path, text, language="en")
    finding, = report["observations"]
    assert finding["rule"] == "adjacent_repetition"
    assert finding["text"] == "of of"
    assert finding["editorial_assessment"] == "not_determined"
    assert finding["review_status"] == "unreviewed"
    assert report["text_correctness"] == "not_assessed"
    assert not {"correction", "replacement", "confidence", "severity"} & finding.keys()
    assert text[finding["start"]:finding["end"]] == "of of"


@pytest.mark.parametrize("text", ["that that confession", "For for this cause", "had had enough", "Holy holy"])
def test_grammatical_or_rhetorical_repetition_never_asserts_error(tmp_path, text):
    report = scan(tmp_path, text, language="en")
    assert report["observations"]
    assert all(f["editorial_assessment"] == "not_determined" for f in report["observations"])


@pytest.mark.parametrize("text", ["seperate recieve vnderstanded ſonne", "sons sons’ wives", "sons sons' wives", "ſin sin", "BISHOPS\n\nBishops", "BISHOPS\r\n \r\nBishops", "word—word", "word, word", "word-word word", "père père"])
def test_historical_forms_and_token_boundaries(tmp_path, text):
    assert not scan(tmp_path, text, language="en")["observations"]


def test_wrapped_line_repetition_is_located_without_normalizing_source(tmp_path):
    report = scan(tmp_path, "préface\r\nthe\r\nthe church", language="en")
    finding, = report["observations"]
    assert finding["text"] == "the\r\nthe"
    assert finding["line"] == 2
    assert finding["start"] == 9


@pytest.mark.parametrize("language", [None, "la", "el", "he", "mul", "enochian"])
def test_english_rules_require_explicit_supported_language(tmp_path, language):
    report = scan(tmp_path, "of of thankfu1ly", language=language)
    assert not report["observations"]
    assert "adjacent_repetition" in report["rules_not_run"]


@pytest.mark.parametrize("word", ["thankfu1ly", "Se1fdetermination", "Thessa1onians"])
def test_character_substitution_candidates_are_observations(tmp_path, word):
    finding, = scan(tmp_path, word, language="en")["observations"]
    assert finding["rule"] == "latin_digit_inside_word"
    assert finding["editorial_assessment"] == "not_determined"


def test_replacement_character_is_found_without_inventing_lost_reading(tmp_path):
    finding, = scan(tmp_path, "λόγος �", language="el")["observations"]
    assert finding["rule"] == "replacement_character_present"
    assert finding["text"] == "�"
    assert finding["editorial_assessment"] == "not_determined"


@pytest.mark.parametrize("text,marker", [("PhÅ“nicia", "Å“"), ("QuÃ&brvbrst", "Ã&brvbr")])
def test_retained_ligature_and_literal_entity_artifacts_are_located(tmp_path, text, marker):
    finding, = scan(tmp_path, text)["observations"]
    assert finding["rule"] == "encoding_sequence_present"
    assert finding["text"] == marker
    assert finding["editorial_assessment"] == "not_determined"


def test_word_joiner_profile_is_context_limited(tmp_path):
    report = scan(tmp_path, "life\u2060—today x\u2060y", profile="standard-ebooks")
    finding, = report["observations"]
    assert finding["start"] == 13
    assert report["expected_typography"] == [{"rule": "word_joiner_before_em_dash", "count": 1}]


def test_feff_is_not_called_encoding_corruption(tmp_path):
    finding, = scan(tmp_path, "his \ufeffsun")["observations"]
    assert finding["rule"] == "invisible_character_present"
    assert "word-joining" in finding["explanation"].lower()


def test_explicit_json_field_and_blank_line_scope(tmp_path):
    path = tmp_path / "source.json"
    data = {"Metadata": {"Title": "teh the the"}, "Data": [{"Content": "BISHOPS\n\nBishops"}, {"Content": "of of"}]}
    path.write_text(json.dumps(data), encoding="utf-8")
    report = lint_file(path, pointers=("/Data/1/Content",), language="en")
    assert len(report["observations"]) == 1
    assert report["observations"][0]["locator"] == "/Data/1/Content"
    assert report["coverage"]["scope"] == "explicit_json_string_fields_only"
    assert report["coverage"]["units"] == 1


@pytest.mark.parametrize("pointer", ["/missing", "/Data", "/Data/01", "/bad~2escape", "Data/0"])
def test_bad_or_nontext_pointers_fail_closed(tmp_path, pointer):
    path = tmp_path / "source.json"
    path.write_text('{"Data": ["text"]}', encoding="utf-8")
    with pytest.raises(ValueError):
        lint_file(path, pointers=(pointer,))


def test_json_requires_selection_and_rejects_duplicate_keys(tmp_path):
    path = tmp_path / "source.json"
    path.write_text('{"text":"one","text":"two"}', encoding="utf-8")
    with pytest.raises(ValueError):
        lint_file(path)
    with pytest.raises(ValueError, match="duplicate"):
        lint_file(path, pointers=("/text",))


def test_json_pointer_escaping_and_empty_string_coverage(tmp_path):
    path = tmp_path / "source.json"
    path.write_text('{"a/b~c":""}', encoding="utf-8")
    report = lint_file(path, pointers=("/a~1b~0c",))
    assert report["coverage"]["empty_units"] == 1
    assert report["text_correctness"] == "not_assessed"


@pytest.mark.parametrize("suffix", [".xml", ".html", ".csv"])
def test_unsupported_formats_do_not_receive_a_clean_result(tmp_path, suffix):
    path = tmp_path / ("source" + suffix)
    path.write_text("of of", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        lint_file(path, language="en")


def test_repeatability_source_preservation_and_hash_binding(tmp_path):
    path = tmp_path / "source.txt"
    original = b"\xef\xbb\xbfHeading\r\n\r\nthankfu1ly of of"
    path.write_bytes(original)
    a = lint_file(path, language="en")
    assert a == lint_file(path, language="en")
    assert path.read_bytes() == original
    assert a["source_sha256"] == hashlib.sha256(original).hexdigest()
    path.write_bytes(original + b".")
    b = lint_file(path, language="en")
    assert a["observations"][0]["id"] != b["observations"][0]["id"]


def test_reject_invalid_utf8_and_unknown_profile(tmp_path):
    path = tmp_path / "source.txt"
    path.write_bytes(b"\xff")
    with pytest.raises(ValueError):
        lint_file(path)
    path.write_text("text", encoding="utf-8")
    with pytest.raises(ValueError):
        lint_file(path, profile="guess")


def test_cli_observations_exit_zero_and_bad_input_fails(tmp_path):
    root = Path(__file__).resolve().parents[1]
    path = tmp_path / "source.txt"
    path.write_text("of of", encoding="utf-8")
    command = [sys.executable, "-m", "build.tools.lint_text", str(path), "--language", "en"]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(result.stdout)["observations"]
    result = subprocess.run(command + ["--pointer", "/text"], cwd=root, capture_output=True, text=True, encoding="utf-8", check=False)
    assert result.returncode == 2
    assert "cannot select JSON" in result.stderr


@pytest.mark.parametrize("text", ["cafe cafe\u0301", "cafe cafe\u1ab0", "of\r\nof", "of\rof"])
def test_combining_marks_and_single_line_boundaries(tmp_path, text):
    observations = scan(tmp_path, text, language="en")["observations"]
    assert bool(observations) == text.startswith("of")


def test_duplicate_selection_rejected_and_selection_order_canonical(tmp_path):
    path = tmp_path / "source.json"
    path.write_text('{"a":"of of","b":"thankfu1ly"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON pointers"):
        lint_file(path, pointers=("/a", "/a"))
    assert lint_file(path, pointers=("/b", "/a"), language="en") == lint_file(path, pointers=("/a", "/b"), language="en")


def test_source_change_during_read_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "source.txt"
    path.write_bytes(b"of of")
    original = Path.read_bytes
    calls = []
    def changing_read(p):
        if p == path.resolve():
            calls.append(p)
            return b"of of" if len(calls) == 1 else b"of"
        return original(p)
    monkeypatch.setattr(Path, "read_bytes", changing_read)
    with pytest.raises(ValueError, match="source changed"):
        lint_file(path, language="en")


@pytest.mark.parametrize("separator", ["\u2029", "\f", "\v"])
def test_paragraph_and_page_separators_prevent_repetition_bridging(tmp_path, separator):
    assert not scan(tmp_path, "word" + separator + "word", language="en")["observations"]


def test_nonstandard_json_constant_fails_closed(tmp_path):
    path = tmp_path / "source.json"
    path.write_text('{"text":"of of","value":NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="nonfinite"):
        lint_file(path, pointers=("/text",))
