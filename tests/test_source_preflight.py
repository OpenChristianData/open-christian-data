"""Behavior tests for pre-conversion discovery across independent formats."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from build.lib.source_preflight import preflight
from build.tools.preflight_source import main


def source(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def declared(report):
    return [dict(kind=f["kind"], name=f["name"], disposition="mapped",
                 reason="fixture mapping to be verified separately") for f in report["features"]]


def test_json_preserves_empty_null_false_zero_and_repeated_values(tmp_path):
    p = source(tmp_path, "source.json", '{"v":["","",null,false,0,[],{},1e9999]}')
    report = preflight(p)
    assert report["status"] == "inventoried"
    assert report["inventory_complete"] is True
    values = [o for o in report["occurrences"] if o["kind"] == "json-value"]
    assert [(o["name"], o["value"]) for o in values] == [
        ("object", 1), ("array", 8), ("string", ""), ("string", ""),
        ("null", None), ("boolean", False), ("number", "0"), ("array", 0),
        ("object", 0), ("number", "1e9999")]
    assert len({o["location"] for o in values}) == len(values)
    assert report["members"][0]["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()


def test_duplicate_json_keys_are_retained_and_blocked(tmp_path):
    p = source(tmp_path, "source.json", '{"x":1,"x":2,"nest":{"x":3}}')
    report = preflight(p)
    assert report["status"] == "blocked"
    assert report["inventory_complete"] is True
    assert [o["value"] for o in report["occurrences"] if o["name"] == "number"] == ["1", "2", "3"]
    assert report["diagnostics"][0]["code"] == "duplicate-json-key"
    assert report["diagnostics"][0]["location"] == "$/member[2]"


def test_xml_shell_mixed_content_attributes_and_semantic_tokens(tmp_path):
    p = source(tmp_path, "source.xhtml",
        '<?xml version="1.0" encoding="UTF-8"?><!--before--><?style sample?>'
        '<r xmlns:e="http://www.idpf.org/2007/ops"><p e:type="a b" class="one two">'
        'left<i>inside</i>right</p><p/><!--after--></r>')
    report = preflight(p)
    assert report["status"] == "inventoried"
    assert report["inventory_complete"]
    rows = report["occurrences"]
    assert [r["value"] for r in rows if r["kind"] == "xml-comment"] == ["before", "after"]
    assert [r["value"] for r in rows if r["kind"] == "xml-text"] == ["left", "inside", "right"]
    assert [r["value"] for r in rows if r["kind"] == "xml-token"] == ["a", "b", "one", "two"]
    assert sum(r["kind"] == "xml-element" and r["name"] == "p" for r in rows) == 2
    assert all("line" in r and "column" in r for r in rows)


@pytest.mark.parametrize("name,baseline,mutated,expected", [
    ("a.xml", '<r><p/></r>', '<r new="x"><p unfamiliar="y"/></r>',
     [("xml-attribute", "new"), ("xml-attribute", "unfamiliar")]),
    ("a.json", '{"a":[{"text":""}]}', '{"a":[{"text":"","new":1}],"extra":false}',
     [("json-field", "new"), ("json-field", "extra")]),
])
def test_new_acquisition_features_all_reported_against_baseline_policy(
        tmp_path, name, baseline, mutated, expected):
    p = source(tmp_path, name, baseline)
    rules = declared(preflight(p))
    assert preflight(p, rules=rules)["status"] == "declared"
    p.write_text(mutated, encoding="utf-8")
    report = preflight(p, rules=rules)
    assert report["status"] == "needs-disposition"
    found = {(o["kind"], o["name"]) for o in report["unresolved_occurrences"]}
    assert set(expected) <= found
    assert all(o["location"] for o in report["unresolved_occurrences"])
    assert report["source_fidelity"] == "not-assessed"


def test_exclusion_is_explicit_and_unsupported_stays_unresolved(tmp_path):
    p = source(tmp_path, "a.xml", '<r x="a"/>')
    rules = declared(preflight(p))
    attr = next(r for r in rules if r["kind"] == "xml-attribute")
    attr.update(disposition="excluded", reason="source navigation only")
    assert preflight(p, rules=rules)["status"] == "declared"
    attr["disposition"] = "unsupported"
    report = preflight(p, rules=rules)
    assert report["status"] == "needs-disposition"
    assert len(report["unresolved_occurrences"]) == 1


@pytest.mark.parametrize("name,content,code", [
    ("bad.json", b'{"x":"\xff"}', "decode-error"),
    ("bad.xml", b'<r>\xff</r>', "decode-error"),
    ("bad.json", b'{"x":NaN}', "parse-error"),
    ("bad.xml", b'<r><p></r>', "parse-error"),
    ("bad.xml", b'<!DOCTYPE r SYSTEM "file:///never-read"><r/>', "parse-error"),
    ("archive.zip", b'not parsed', "unsupported-format"),
])
def test_incomplete_sources_fail_without_recovery(tmp_path, name, content, code):
    report = preflight(source(tmp_path, name, content))
    assert report["status"] == "blocked"
    assert not report["inventory_complete"]
    assert report["diagnostics"][0]["code"] == code


def test_explicit_encoding_and_declaration_mismatch(tmp_path):
    p = source(tmp_path, "a.xml", b'<?xml version="1.0" encoding="windows-1252"?><r>caf\xe9</r>')
    report = preflight(p, encoding="cp1252")
    assert report["status"] == "inventoried"
    assert any(o["value"] == "café" for o in report["occurrences"])
    p.write_bytes(b'<?xml version="1.0" encoding="windows-1252"?><r>ascii</r>')
    assert preflight(p)["diagnostics"][0]["code"] == "encoding-declaration-mismatch"


def test_directory_does_not_omit_unsupported_or_oversize_members(tmp_path):
    source(tmp_path, "a.json", '{}')
    source(tmp_path, "b.bin", b'abc')
    source(tmp_path, "c.xml", '<root/>')
    report = preflight(tmp_path, max_bytes=5)
    assert [m["path"] for m in report["members"]] == ["a.json", "b.bin", "c.xml"]
    assert {d["code"] for d in report["diagnostics"]} == {"unsupported-format", "size-limit"}
    assert not report["inventory_complete"]


def test_empty_missing_and_linked_input_are_not_success(tmp_path, monkeypatch):
    assert preflight(tmp_path)["status"] == "blocked"
    assert preflight(tmp_path / "absent.json")["status"] == "blocked"
    p = source(tmp_path, "linked.json", '{}')
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == p or original(self))
    report = preflight(p)
    assert report["diagnostics"][0]["code"] == "linked-path"
    assert report["members"][0]["status"] == "not-read"


@pytest.mark.parametrize("rules", [dict(), [{}], [dict(kind="x", name="a", disposition="mapped", reason="")],
    [dict(kind="x", name="a", disposition="mapped", reason="why")] * 2])
def test_ambiguous_policy_rejected(tmp_path, rules):
    with pytest.raises(ValueError):
        preflight(source(tmp_path, "a.json", '{}'), rules=rules)


def test_cli_exit_codes_and_no_source_writes(tmp_path, capsys):
    p = source(tmp_path, "a.json", '{}')
    before = p.read_bytes()
    assert main([str(p)]) == 0
    report = json.loads(capsys.readouterr().out)
    policy = source(tmp_path, "policy.json", '[]')
    assert main([str(p), "--policy", str(policy)]) == 1
    capsys.readouterr()
    assert main([str(p), "--encoding", "not-a-codec"]) == 2
    assert p.read_bytes() == before
    assert report["acquisition_completeness"] == "not-assessed"


def test_cli_deterministic_in_fresh_process_and_other_cwd(tmp_path):
    p = source(tmp_path, "a.xml", '<r><p>a<i>b</i>c</p><!--end--></r>')
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1")
    args = [sys.executable, "-m", "build.tools.preflight_source", str(p)]
    first = subprocess.run(args, cwd=root, env=env, capture_output=True, check=True)
    second = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, check=True)
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["status"] == "inventoried"


def test_namespace_inventory_attaches_to_declaring_element(tmp_path):
    report = preflight(source(tmp_path, "a.xml", '<r><p xmlns:x="urn:test"/></r>'))
    occurrence = next(o for o in report["occurrences"] if o["kind"] == "xml-namespace")
    assert occurrence["location"].startswith("/document/element[1]/element[1]/event[")


def test_cli_rejects_ambiguous_policy_json(tmp_path, capsys):
    p = source(tmp_path, "a.json", '{}')
    policy = source(tmp_path, "policy.json",
                    '[{"kind":"json-value","kind":"xml-element","name":"object",'
                    '"disposition":"mapped","reason":"fixture"}]')
    assert main([str(p), "--policy", str(policy)]) == 2
    assert "duplicate policy key" in capsys.readouterr().err


def test_bad_member_does_not_hide_later_members(tmp_path):
    source(tmp_path, "a.xml", '<r>')
    source(tmp_path, "b.json", '{"still_seen": "yes"}')
    report = preflight(tmp_path)
    assert report["status"] == "blocked"
    assert not report["inventory_complete"]
    assert any(o["name"] == "still_seen" for o in report["occurrences"])


def test_new_semantic_token_is_not_covered_by_known_attribute(tmp_path):
    p = source(tmp_path, "a.xhtml", '<r xmlns:e="http://www.idpf.org/2007/ops" e:type="known"/>')
    rules = declared(preflight(p))
    p.write_text('<r xmlns:e="http://www.idpf.org/2007/ops" e:type="known new1 new2"/>', encoding="utf-8")
    report = preflight(p, rules=rules)
    assert report["status"] == "needs-disposition"
    assert [o["value"] for o in report["unresolved_occurrences"]] == ["new1", "new2"]


def test_xml_duplicate_attributes_are_not_silently_collapsed(tmp_path):
    report = preflight(source(tmp_path, "a.xml", '<r a="1" a="2"/>'))
    assert report["status"] == "blocked"
    assert not report["inventory_complete"]
    assert report["diagnostics"][0]["code"] == "parse-error"
