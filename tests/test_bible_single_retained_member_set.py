"""Single-TEI accounting support must not weaken retained corpus bindings."""
from __future__ import annotations

import copy
import importlib.util
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from lxml import etree
from ocd_kernel.library._common import PipelineError

candidate_path = os.environ.get("OCD_BIBLE_MEMBER_CANDIDATE")
if candidate_path:
    spec = importlib.util.spec_from_file_location("bible_member_candidate", candidate_path)
    bible = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bible)
else:
    from ocd_kernel.projection.categories import bible

NS = "{" + bible.TEI_NS + "}"


def fixture():
    root = ET.Element(NS + "TEI")
    ET.SubElement(ET.SubElement(root, NS + "text"), NS + "body")
    members = [{"path": "raw/a/001.json", "position": 1, "bytes": 10, "sha256": "a" * 64},
               {"path": "raw/b/001.json", "position": 2, "bytes": 20, "sha256": "b" * 64}]
    source = {"source_kind": "retained-member-set", "missing_members": [], "unknown_members": []}
    scope = {"included_members": members, "expected_members": [{"path": m["path"], "position": m["position"]} for m in members], "excluded_members": []}
    acquired = [{k: m[k] for k in ("path", "bytes", "sha256")} for m in members]
    metadata = {"acceptance": {"source": source, "scope": scope}, "acquisition": {"source_kind": "retained-member-set", "retained_files": acquired}}
    return root, {"source_url": "https://example.test/?id=eng-rv"}, metadata


def check(root, header, metadata, observer):
    if observer:
        bible._checker_validate_accepted_member_set(etree.fromstring(ET.tostring(root)), header, metadata)
    else:
        bible._validate_accepted_member_set(root, header, metadata)


@pytest.mark.parametrize("observer", [False, True])
def test_complete_single_tei_permits_distinct_paths_with_same_basename(observer):
    check(*fixture(), observer)


@pytest.mark.parametrize("observer", [False, True])
@pytest.mark.parametrize("mutation", ["missing", "unknown", "excluded", "missing-expected", "missing-included", "missing-acquired", "duplicate-path", "case-duplicate", "expected-path", "acquired-path", "digest-mismatch", "size-mismatch", "invalid-digest", "boolean-size", "boolean-position", "expected-position", "acquired-order", "unsafe-path", "member-not-object", "bad-acquisition-kind", "two-bodies", "wrong-root"])
def test_single_tei_rejects_incomplete_or_mismatched_accounting(observer, mutation):
    root, header, metadata = fixture()
    scope, source = metadata["acceptance"]["scope"], metadata["acceptance"]["source"]
    present, wanted, acquired = scope["included_members"], scope["expected_members"], metadata["acquisition"]["retained_files"]
    if mutation == "missing": source["missing_members"] = [present[0]["path"]]
    elif mutation == "unknown": source["unknown_members"] = [present[0]["path"]]
    elif mutation == "excluded": scope["excluded_members"] = [copy.deepcopy(present[0])]
    elif mutation == "missing-expected": wanted.pop()
    elif mutation == "missing-included": present.pop()
    elif mutation == "missing-acquired": acquired.pop()
    elif mutation in {"duplicate-path", "case-duplicate"}:
        path = present[0]["path"] if mutation == "duplicate-path" else present[0]["path"].upper()
        for item in (present[1], wanted[1], acquired[1]): item["path"] = path
    elif mutation == "expected-path": wanted[1]["path"] = "raw/other.json"
    elif mutation == "acquired-path": acquired[1]["path"] = "raw/other.json"
    elif mutation == "digest-mismatch": present[1]["sha256"] = "c" * 64
    elif mutation == "size-mismatch": present[1]["bytes"] += 1
    elif mutation == "invalid-digest": present[1]["sha256"] = "broken"
    elif mutation == "boolean-size": present[1]["bytes"] = True
    elif mutation == "boolean-position": present[0]["position"] = True
    elif mutation == "expected-position": wanted[1]["position"] = 1
    elif mutation == "acquired-order": acquired.reverse()
    elif mutation == "unsafe-path":
        for item in (present[0], wanted[0], acquired[0]): item["path"] = "../outside.json"
    elif mutation == "member-not-object": present[1] = None
    elif mutation == "bad-acquisition-kind": metadata["acquisition"]["source_kind"] = "zip"
    elif mutation == "two-bodies": ET.SubElement(root.find(NS + "text"), NS + "body")
    elif mutation == "wrong-root": root.tag = NS + "other"
    with pytest.raises(PipelineError):
        check(root, header, metadata, observer)


def corpus_fixture():
    _, header, metadata = fixture()
    root = ET.Element(NS + "teiCorpus")
    for index, member in enumerate(metadata["acceptance"]["scope"]["included_members"], 1):
        name = f"book{index}.usfm"
        member["path"] = "raw/" + name
        metadata["acceptance"]["scope"]["expected_members"][index - 1]["path"] = member["path"]
        doc = ET.SubElement(root, NS + "TEI")
        body = ET.SubElement(ET.SubElement(doc, NS + "text"), NS + "body")
        ET.SubElement(body, NS + "div", {"type": "book", "corresp": f"source-usfm:eng-rv/{name}#line=1"})
    return root, header, metadata


@pytest.mark.parametrize("observer", [False, True])
def test_existing_corpus_route_still_requires_member_to_document_correspondence(observer):
    root, header, metadata = corpus_fixture()
    check(root, header, metadata, observer)
    root[0].find(".//" + NS + "div").set("corresp", "source-usfm:eng-rv/book2.usfm#line=1")
    with pytest.raises(PipelineError, match="does not identify"):
        check(root, header, metadata, observer)


@pytest.mark.parametrize("observer", [False, True])
@pytest.mark.parametrize("mutation", ["document-count", "member-order", "missing", "unknown", "excluded", "duplicate-name"])
def test_existing_corpus_safeguards_remain_closed(observer, mutation):
    root, header, metadata = corpus_fixture()
    scope, source = metadata["acceptance"]["scope"], metadata["acceptance"]["source"]
    if mutation == "document-count": root.remove(root[-1])
    elif mutation == "member-order": scope["included_members"].reverse()
    elif mutation == "missing": source["missing_members"] = ["raw/book1.usfm"]
    elif mutation == "unknown": source["unknown_members"] = ["raw/book1.usfm"]
    elif mutation == "excluded": scope["excluded_members"] = [scope["included_members"][0]]
    elif mutation == "duplicate-name":
        scope["included_members"][1]["path"] = scope["included_members"][0]["path"]
        scope["expected_members"][1]["path"] = scope["included_members"][0]["path"]
    with pytest.raises(PipelineError):
        check(root, header, metadata, observer)


def test_single_tei_observer_does_not_call_producer_accounting(monkeypatch):
    def producer(*args, **kwargs):
        raise AssertionError("Producer accounting called")
    monkeypatch.setattr(bible, "_validate_accepted_member_set", producer)
    check(*fixture(), True)
