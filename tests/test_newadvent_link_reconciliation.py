"""Exact failed-href repairs retain their spelling and require source evidence."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from build.tei.newadvent_reconstruction import _bound_reconciled_links, project_page
from build.tei.newadvent_oracle import _verified_link_reconciliation, verify_page
from build.tools.prepare_newadvent_reconstruction import validate_link_reconciliation_policy
from tests.test_newadvent_reconstruction import page, validate, NS

BASE = "https://www.newadvent.org/cathen/"
SOURCE, TARGET, INDEX, ORIGIN, UNMAPPED = [BASE + name for name in ("13548b.htm", "13554b.htm", "s.htm", "01036b.htm", "01300a.htm")]


def test_lib025_policy_keeps_exact_six_repairs_and_two_unmapped_urls():
    policy = json.loads((Path(__file__).resolve().parents[1] / "sources/reference/catholic-encyclopedia/current-web-20260911/link-reconciliation-policy.json").read_bytes())
    validate_link_reconciliation_policy(policy)
    assert {row["source_url"]: row["target_url"] for row in policy["mappings"]} == {
        BASE + source + ".htm": BASE + target + ".htm"
        for source, target in (("13548b", "13554b"), ("11327b", "11527b"), ("04735b", "04375b"), ("01202d", "01212d"), ("06188a", "01688a"), ("02580b", "02480b"))
    }
    assert len(policy["mappings"]) == 6
    assert {row["source_url"] for row in policy["unmapped"]} == {BASE + "01300a.htm", BASE + "14580x.htm"}


def test_existing_oracle_traversal_occurrences_avoid_a_second_corpus_scan(evidence, monkeypatch):
    _, manifest, profile, _, _ = evidence
    from build.tei import newadvent_oracle
    original = newadvent_oracle._read_document
    calls = []
    def tracked(payload):
        calls.append(payload)
        return original(payload)
    monkeypatch.setattr(newadvent_oracle, "_read_document", tracked)
    assert _verified_link_reconciliation(manifest, profile, {SOURCE: [(ORIGIN, "schools")]}) == {SOURCE: "target"}
    assert len(calls) == 1  # Only the declared index requires a fresh parse.
    with pytest.raises(ValueError, match="occurrence evidence"):
        _verified_link_reconciliation(manifest, profile, {SOURCE: []})


@pytest.fixture
def evidence(tmp_path):
    policy = {"contract": "ocd-lib025-newadvent-link-reconciliation-v1", "work_id": "catholic-encyclopedia-vol01", "mappings": [{"source_url": SOURCE, "target_url": TARGET, "index_url": INDEX, "index_title": "Schools", "source_occurrences": [{"page_url": ORIGIN, "label": "schools"}], "rationale": "Retained alphabetical index identifies the target."}], "unmapped": [{"source_url": UNMAPPED, "rationale": "No supported target."}]}
    payloads = {"origin": page('<p>See <a href="13548b.htm">schools</a>.</p>'), "target": page("<p>Schools article.</p>"), "index": page('<p><a href="13554b.htm">Schools</a></p>')}
    paths = {name: tmp_path / (name + ".html") for name in payloads}
    for name, payload in payloads.items():
        paths[name].write_bytes(payload)
    paths["policy"] = tmp_path / "policy.json"
    paths["policy"].write_text(json.dumps(policy), encoding="utf-8")
    manifest = SimpleNamespace(record={"authorities": [{"name": "policy", "role": "source-link-reconciliation-policy"}]}, authority_path=lambda name: paths[name])
    profile = {"link_reconciliation_policy_authority": "policy", "html_members": [{"url": url, "authority": name, "tei_id": name} for url, name in ((ORIGIN, "origin"), (TARGET, "target"), (INDEX, "index"))], "failed_acquisitions": [{"url": url, "kind": "html"} for url in (SOURCE, UNMAPPED)]}
    return policy, manifest, profile, paths, payloads


def test_bound_repair_preserves_exact_href_and_unmapped_routes(evidence):
    policy, manifest, profile, paths, payloads = evidence
    validate_link_reconciliation_policy(policy)
    actual = _bound_reconciled_links(manifest, profile)
    expected = _verified_link_reconciliation(manifest, profile)
    assert actual == expected == {SOURCE: "target"}
    source = page('<p><a href="13548b.htm">schools</a> <a href="13548b.htm#part">fragment</a> <a href="01300a.htm">unmapped</a></p>')
    links = {SOURCE: "missing", UNMAPPED: "unmapped"}
    candidate, _ = project_page(source, ORIGIN, "origin", link_targets=links, reconciled_links=actual)
    assert verify_page(source, ORIGIN, "origin", candidate, link_targets=links, reconciled_links=expected)["status"] == "pass"
    refs = candidate.xpath('.//t:ref', namespaces=NS)
    assert [node.get("target") for node in refs] == ["#target", SOURCE + "#part", "#unmapped"]
    assert [node.get("type") for node in refs] == ["source-href-reconciled", None, None]
    assert refs[0].get("corresp") == SOURCE
    validate(candidate)


@pytest.mark.parametrize("attribute,value", [("target", "#wrong-retained-member"), ("corresp", None), ("type", None)])
def test_oracle_rejects_repaired_ref_mutations(evidence, attribute, value):
    _, manifest, profile, _, payloads = evidence
    expected = _verified_link_reconciliation(manifest, profile)
    candidate, _ = project_page(payloads["origin"], ORIGIN, "origin", reconciled_links=_bound_reconciled_links(manifest, profile))
    assert verify_page(payloads["origin"], ORIGIN, "origin", candidate, reconciled_links=expected)["status"] == "pass"
    reference = candidate.xpath('.//t:ref', namespaces=NS)[0]
    if value is None:
        del reference.attrib[attribute]
    else:
        reference.set(attribute, value)
    with pytest.raises(ValueError):
        verify_page(payloads["origin"], ORIGIN, "origin", candidate, reconciled_links=expected)


@pytest.mark.parametrize("mutation", ["wrong_target", "wrong_title", "missing_occurrence", "extra_occurrence", "changed_anchor", "extra_anchor", "not_failed", "image_failure", "mapped_unmapped", "unbound"])
def test_oracle_rejects_policy_or_source_evidence_mutations(evidence, mutation):
    policy, manifest, profile, paths, _ = evidence
    row = policy["mappings"][0]
    if mutation == "wrong_target":
        row["target_url"] = ORIGIN
    elif mutation == "wrong_title":
        row["index_title"] = "School"
    elif mutation == "missing_occurrence":
        row["source_occurrences"] = []
    elif mutation == "extra_occurrence":
        row["source_occurrences"].append({"page_url": TARGET, "label": "schools"})
    elif mutation == "changed_anchor":
        paths["origin"].write_bytes(page('<p><a href="13548b.htm">different label</a></p>'))
    elif mutation == "extra_anchor":
        paths["target"].write_bytes(page('<p><a href="13548b.htm">schools</a></p>'))
    elif mutation == "not_failed":
        profile["failed_acquisitions"] = []
    elif mutation == "image_failure":
        profile["failed_acquisitions"][0]["kind"] = "image"
    elif mutation == "mapped_unmapped":
        policy["unmapped"][0]["source_url"] = SOURCE
    else:
        manifest.record["authorities"] = []
    paths["policy"].write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(ValueError, match="[Ll]ink reconciliation|unmapped"):
        _verified_link_reconciliation(manifest, profile)


@pytest.mark.parametrize("mutation", ["contract", "work_id", "path", "missing_key", "duplicate", "occurrence", "extra_key"])
def test_preparer_rejects_invalid_policy_schema(evidence, mutation):
    policy = deepcopy(evidence[0])
    if mutation in {"contract", "work_id"}:
        policy[mutation] = "wrong"
    elif mutation == "path":
        policy["mappings"][0]["target_url"] = "../unbound.html"
    elif mutation == "missing_key":
        del policy["mappings"][0]["rationale"]
    elif mutation == "duplicate":
        policy["unmapped"].append({"source_url": SOURCE, "rationale": "Overlapping source."})
    elif mutation == "occurrence":
        policy["mappings"][0]["source_occurrences"] = []
    else:
        policy["untrusted_path"] = "file.json"
    with pytest.raises(ValueError, match="link reconciliation"):
        validate_link_reconciliation_policy(policy)
