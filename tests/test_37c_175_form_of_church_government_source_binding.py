"""Work-specific source-envelope and route-binding checks for ticket 37c-175."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree, html

from ocd_kernel.reconstruction.contract import SourceManifest
from build.tei.lib089_form_church_comments_reconstruction import _producer_closure
from build.tei.lib089_form_church_comments_oracle import _closure


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    ROOT / 'tests/fixtures/reconstruction-runtime/lib089_form_church_comments_oracle.source-manifest.json'
)
SOURCE_SHA256 = "d5b31994e9ce43e7828ff65f3ac758e8974b0396d6ba03f991c785b8d92a3ac4"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalized_text(node: etree._Element) -> str:
    return " ".join(" ".join(node.itertext()).split())


def _independent_carriers(document: etree._ElementTree) -> list[etree._Element]:
    selected: dict[str, etree._Element] = {}
    for node in document.iter("div"):
        if "wpb_text_column" not in set((node.get("class") or "").split()):
            continue
        carrier = node
        for ancestor in node.iterancestors("div"):
            if "toggle" in set((ancestor.get("class") or "").split()):
                carrier = ancestor
                break
        selected[document.getpath(carrier)] = carrier
    return list(selected.values())


def test_manifest_binds_the_exact_source_profile_and_current_lib089_route() -> None:
    source = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    source.verify()

    source_bytes = source.authority_path("retained-html").read_bytes()
    assert len(source_bytes) == 92_499
    assert _sha(source_bytes) == SOURCE_SHA256
    assert source.record["ticket_id"] == "LIB-089"
    assert source.record["work_id"] == "form-of-church-government"
    assert source.record["retained_source_path"] == (
        "raw/westminster-standard-org/form-of-church-government.html"
    )
    assert source.record["producer_import_closure_sha256"] == _producer_closure(ROOT)

    validator = source.record["validator"]
    assert validator["import_closure_sha256"] == _closure(ROOT)

    profile = json.loads(
        source.authority_path("reconstruction-profile").read_text(encoding="utf-8")
    )
    assert profile["source_envelope"]["sha256"] == SOURCE_SHA256
    assert profile["identity"]["title"] == "Form of Presbyterial Church-Government"
    assert profile["identity"]["catalog_display_title"] == (
        "The Form of Presbyterial Church-Government"
    )
    assert profile["identity"]["edition_status"] == "unresolved"
    assert profile["identity"]["work_boundary_status"] == "unresolved"
    assert profile["rights"]["status"] == "unresolved"


def test_profile_accounts_all_carriers_headings_and_selected_comments() -> None:
    source = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    profile = json.loads(
        source.authority_path("reconstruction-profile").read_text(encoding="utf-8")
    )
    policy = json.loads(
        source.authority_path("validation-policy").read_text(encoding="utf-8")
    )
    source_bytes = source.authority_path("retained-html").read_bytes()
    document = html.document_fromstring(source_bytes).getroottree()
    carriers = _independent_carriers(document)

    assert len(list(document.iter())) == 570
    assert sum(1 for node in document.iter() if isinstance(node.tag, str)) == 546
    assert len(document.xpath("//comment()")) == 24
    assert len(document.xpath("//processing-instruction()")) == 0
    assert len(carriers) == 3
    assert [document.getpath(node) for node in carriers] == policy[
        "ordered_carrier_paths"
    ]

    observed_census = []
    for index, carrier in enumerate(carriers, 1):
        text = _normalized_text(carrier)
        row = profile["html_block_census"][index - 1]
        observed_census.append(
            {
                "index": index,
                "disposition": row["disposition"],
                "subtree_sha256": _sha(
                    etree.tostring(carrier, encoding="utf-8", with_tail=False)
                ),
                "normalized_text_sha256": _sha(text.encode("utf-8")),
                "word_count": len(text.split()),
                "element_count": sum(
                    1 for node in carrier.iter() if isinstance(node.tag, str)
                ),
            }
        )
    assert observed_census == profile["html_block_census"]
    assert sum(row["element_count"] for row in observed_census) == 293
    assert sum(row["word_count"] for row in observed_census) == 5_932
    assert _sha(
        "\n".join(_normalized_text(node) for node in carriers).encode("utf-8")
    ) == profile["source_envelope"]["selected_text_sha256"]

    headings = [
        _normalized_text(node) for node in document.xpath("//h1|//h2|//h3")
    ]
    assert headings == policy["ordered_document_headings"]
    assert len(headings) == 23

    selected_comments = []
    for comment in document.xpath("//comment()"):
        parent = comment.getparent()
        carrier = parent
        while carrier is not None and carrier not in carriers:
            carrier = carrier.getparent()
        if carrier is not None:
            selected_comments.append(comment)

    dispositions = profile["comment_policy"]
    assert len(selected_comments) == dispositions["selected_comment_count"] == 2
    policy_comment_disposition = policy["comment_disposition"]
    assert policy_comment_disposition["source_comment_count"] == 24
    assert policy_comment_disposition["selected_carrier_comment_count"] == 2
    assert dispositions["selected_comment_disposition"] == "preserve-as-tei-note"
    assert policy_comment_disposition["required_candidate_mapping"] == (
        dispositions["selected_comment_disposition"]
    )
    assert policy_comment_disposition["required_source_accountability"]
    assert "preserve" in policy_comment_disposition["current_route_status"]
    outside_comment_count = len(document.xpath("//comment()")) - len(
        selected_comments
    )
    assert outside_comment_count == 22
    assert outside_comment_count == dispositions["outside_selected_comment_count"]
    assert outside_comment_count == profile["source_envelope"][
        "outside_selected_carrier_comment_count"
    ]
    declared = dispositions["selected_comments"]
    assert [document.getpath(node) for node in selected_comments] == [
        row["source_xpath"] for row in declared
    ]
    for comment, row in zip(selected_comments, declared):
        parent = comment.getparent()
        assert comment.text == row["source_text"] == " .entry-content "
        assert _sha(comment.text.encode("utf-8")) == row["source_text_sha256"]
        assert document.getpath(parent) == row["parent_xpath"]
        assert parent.tag == row["parent_tag"] == "p"
        assert parent.text == row["parent_direct_text"] is None
        parent_element_child_count = sum(
            1 for child in parent if isinstance(child.tag, str)
        )
        assert row["parent_element_child_count"] == 0
        assert parent_element_child_count == row["parent_element_child_count"]
        assert comment.tail == row["comment_tail"] is None
        assert _sha((comment.tail or "").encode("utf-8")) == row[
            "comment_tail_sha256"
        ]
        assert row["disposition"] == "preserve-as-tei-note"
