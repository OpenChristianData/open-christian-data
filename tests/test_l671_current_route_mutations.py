from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.l671_l674_semantic_oracle import _oracle
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
from ocd_kernel.tei.validate import compiled_schema


ROOT = Path(__file__).resolve().parents[1]
RETAINED_SOURCE_MANIFEST = Path("sources/manifest-acquisitions/l671-pg39440-successor/source-manifest.v3.json")
SOURCE_MANIFEST = Path("tests/fixtures/reconstruction-runtime/l671_l674_semantic_oracle.source-manifest.json")
BOUND_CANDIDATE = Path(
    r"D:\Library\Open Christian Data\candidate-reviews"
    r"\cox-pg39440-l671-current-main-v3-20261002\baseline\package"
)
EXPECTED_SOURCE_MANIFEST_SHA256 = "62852e6fffbebd2f601c3fef9a6ce2271c7a4d80709b0a5ae374269fb0767f11"
EXPECTED_CANDIDATE_SHA256 = "97919e14018d84b83763344cda097e38fb9a702c8d2fa3af1db7035a5b6b00d2"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _reseal(path: Path) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    record = json.loads(manifest_path.read_bytes())
    for member in record["members"]:
        raw = (path / member["name"]).read_bytes()
        member.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest_path.write_bytes(
        (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )
    return CandidatePackage.load(path)


@pytest.fixture(scope="module")
def runtime_bound(tmp_path_factory) -> tuple[SourceManifest, CandidatePackage]:
    from tests.runtime_candidate_baselines import current_runtime_baseline

    assert hashlib.sha256((ROOT / RETAINED_SOURCE_MANIFEST).read_bytes()).hexdigest() == EXPECTED_SOURCE_MANIFEST_SHA256
    return current_runtime_baseline(
        root=ROOT, original_manifest=RETAINED_SOURCE_MANIFEST, runtime_manifest=SOURCE_MANIFEST,
        retained_package=BOUND_CANDIDATE, retained_sha256=EXPECTED_CANDIDATE_SHA256,
        destination=tmp_path_factory.mktemp("l671-runtime") / "candidate",
    )


def test_current_l671_route_explicitly_accounts_for_out_of_scope_html_head(runtime_bound) -> None:
    source, candidate = runtime_bound
    profile = json.loads(source.authority_path("profile").read_bytes())
    policy = json.loads(source.authority_path("policy").read_bytes())
    html_raw = source.authority_path("extracted-html").read_bytes()
    assert hashlib.sha256(html_raw).hexdigest() == profile["html_sha256"]
    document = etree.HTML(html_raw)
    head = document.find(".//head")
    assert head is not None
    disposition = profile["head_metadata_disposition"]
    assert disposition["source_html_sha256"] == profile["html_sha256"]
    assert disposition["head_direct_child_count"] == len(head)
    assert len(disposition["head_children"]) == len(head)
    assert disposition["head_direct_child_tag_counts"] == {
        "#comment": 1, "link": 4, "meta": 22, "style": 3, "title": 1
    }
    for expected, actual in zip(disposition["head_children"], head, strict=True):
        tag = actual.tag.lower() if isinstance(actual.tag, str) else "#comment"
        attributes = dict(sorted(actual.attrib.items())) if isinstance(actual.tag, str) else {}
        assert expected["tag"] == tag
        assert expected["attributes"] == attributes
        assert expected["text_chars"] == len(actual.text or "")
        assert expected["tail_chars"] == len(actual.tail or "")
        assert expected["disposition"]
    source_meta = [
        (position, dict(sorted(node.attrib.items())))
        for position, node in enumerate(head)
        if isinstance(node.tag, str) and node.tag.lower() == "meta"
    ]
    assert len(disposition["metadata_items"]) == len(source_meta) == 22
    for expected, (position, attributes) in zip(disposition["metadata_items"], source_meta, strict=True):
        field = attributes.get("name") or attributes.get("property") or ("charset" if "charset" in attributes else None)
        content = attributes.get("content") if "content" in attributes else attributes.get("charset")
        assert expected["position"] == position
        assert expected["field"] == field
        assert expected["content"] == content
        assert expected["attributes"] == attributes
    envelope_policy = policy["html_envelope_disposition"]
    assert "complete retained HTML body" in envelope_policy["included"]
    assert "All direct children" in envelope_policy["out_of_scope_but_accounted"]
    rights = [item for item in disposition["metadata_items"] if item["field"] == "dc.rights"]
    assert len(rights) == 1 and rights[0]["content"] == "Public domain in the USA."
    assert "no rights clearance is inferred" in envelope_policy["rights"]
    assert validate(source, candidate, _oracle).status == "pass"


@pytest.mark.parametrize(
    ("mutation", "expected_finding"),
    [
        ("text", "source wording, ordering, or text/tail content changed"),
        ("order", "readable source element hierarchy, role, attributes, or order changed"),
        ("identity", "one-work root identity mismatch"),
        ("omission", "readable source element hierarchy, role, attributes, or order changed"),
    ],
)
def test_current_l671_route_rejects_p5_valid_resealed_mutations(
    mutation: str, expected_finding: str, tmp_path: Path, runtime_bound
) -> None:
    source, candidate = runtime_bound
    assert validate(source, candidate, _oracle).status == "pass"

    changed_path = tmp_path / f"l671-{mutation}-mutation"
    shutil.copytree(candidate.path, changed_path)
    tei_path = changed_path / "content.tei.xml"
    tree = etree.fromstring(tei_path.read_bytes())
    body = tree.find(f"{{{TEI}}}text/{{{TEI}}}body")
    assert body is not None

    if mutation == "text":
        target = body.xpath("./tei:p[@n='body/1']", namespaces={"tei": TEI})[0]
        target.text = (target.text or "") + " [mutated]"
    elif mutation == "order":
        first = body.xpath("./tei:p[@n='body/3']", namespaces={"tei": TEI})[0]
        second = body.xpath("./tei:p[@n='body/4']", namespaces={"tei": TEI})[0]
        first_index = body.index(first)
        second_index = body.index(second)
        body.remove(first)
        body.insert(second_index, first)
        assert body.index(first) > body.index(second)
    elif mutation == "identity":
        tree.set(XML_ID, "pg39440-unrelated-work")
    elif mutation == "omission":
        target = body.xpath("./tei:p[@n='body/3']", namespaces={"tei": TEI})[0]
        body.remove(target)
    else:  # pragma: no cover - parametrization is exhaustive
        raise AssertionError(mutation)

    tei_path.write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True))
    assert compiled_schema().validate(etree.parse(str(tei_path))), compiled_schema().error_log[:1]
    resealed = _reseal(changed_path)
    with pytest.raises(ValueError, match=expected_finding):
        validate(source, resealed, _oracle)
