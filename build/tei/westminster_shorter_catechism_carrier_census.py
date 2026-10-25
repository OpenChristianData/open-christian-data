"""Read-only outer-carrier census for the retained Westminster Standard HTML."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Mapping

from lxml import etree, html


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _display(value: str | None) -> str:
    return " ".join((value or "").split())


def html_carrier_census(content: bytes) -> dict[str, object]:
    """Classify every parsed HTML carrier without selecting an edition reading."""

    document = html.fromstring(content)
    paragraphs = document.xpath("//p")
    assigned: set[etree._Element] = set()
    question_count = 0
    proof_count = 0
    for paragraph in paragraphs:
        bold = paragraph.xpath("./b")
        if not bold or not _display("".join(bold[0].itertext())).startswith("Q."):
            continue
        question_count += 1
        assigned.add(paragraph)
        proof = paragraph.getnext()
        if proof is None or etree.QName(proof).localname != "p":
            raise ValueError(
                f"Westminster outer census found no proof paragraph for Q{question_count}"
            )
        proof_count += 1
        assigned.add(proof)
    if question_count != 107 or proof_count != 107:
        raise ValueError(
            "Westminster outer census did not recover 107 question/proof pairs"
        )

    def disposition(node: etree._Element) -> str:
        if node in assigned or any(
            ancestor in assigned for ancestor in node.iterancestors()
        ):
            return "assigned-content"
        return "outer-evidence-only"

    element_records: list[dict[str, object]] = []
    attribute_records: list[dict[str, object]] = []
    text_records: list[dict[str, object]] = []
    comment_records: list[dict[str, object]] = []
    element_ordinals: dict[etree._Element, int] = {}
    tag_counts: Counter[str] = Counter()
    disposition_counts: Counter[str] = Counter()
    attribute_dispositions: Counter[str] = Counter()
    text_dispositions: Counter[str] = Counter()
    comment_dispositions: Counter[str] = Counter()

    for node in document.iter():
        if isinstance(node, etree._Comment):
            node_disposition = disposition(node)
            comment_dispositions[node_disposition] += 1
            comment_records.append(
                {
                    "ordinal": len(comment_records) + 1,
                    "disposition": node_disposition,
                    "value": node.text or "",
                }
            )
            continue
        if not isinstance(node.tag, str):
            continue
        ordinal = len(element_records) + 1
        element_ordinals[node] = ordinal
        tag = etree.QName(node).localname
        node_disposition = disposition(node)
        tag_counts[tag] += 1
        disposition_counts[node_disposition] += 1
        element_records.append(
            {
                "ordinal": ordinal,
                "tag": tag,
                "disposition": node_disposition,
            }
        )
        for name, value in sorted(node.attrib.items()):
            attribute_dispositions[node_disposition] += 1
            attribute_records.append(
                {
                    "owner": ordinal,
                    "name": name,
                    "value": value,
                    "disposition": node_disposition,
                }
            )
        if _display(node.text):
            text_dispositions[node_disposition] += 1
            text_records.append(
                {
                    "owner": ordinal,
                    "slot": "text",
                    "value": node.text,
                    "disposition": node_disposition,
                }
            )
        if _display(node.tail):
            parent = node.getparent()
            tail_disposition = (
                disposition(parent) if parent is not None else "outer-evidence-only"
            )
            text_dispositions[tail_disposition] += 1
            text_records.append(
                {
                    "owner": ordinal,
                    "slot": "tail",
                    "value": node.tail,
                    "disposition": tail_disposition,
                }
            )

    if len(element_ordinals) != len(element_records):
        raise ValueError("Westminster outer census element identity drifted")
    return {
        "parser": "lxml.html.fromstring",
        "paragraph_classes": {
            "assigned_questions": question_count,
            "assigned_proof_groups": proof_count,
            "outer_evidence_only": len(paragraphs) - len(assigned),
        },
        "elements": {
            "total": len(element_records),
            "by_disposition": dict(sorted(disposition_counts.items())),
            "by_tag": dict(sorted(tag_counts.items())),
            "stream_sha256": _digest(element_records),
        },
        "attributes": {
            "total": len(attribute_records),
            "by_disposition": dict(sorted(attribute_dispositions.items())),
            "stream_sha256": _digest(attribute_records),
        },
        "nonempty_text_carriers": {
            "total": len(text_records),
            "by_disposition": dict(sorted(text_dispositions.items())),
            "stream_sha256": _digest(text_records),
        },
        "comments": {
            "total": len(comment_records),
            "by_disposition": dict(sorted(comment_dispositions.items())),
            "stream_sha256": _digest(comment_records),
        },
    }


def verify_html_carrier_census(
    content: bytes,
    expected: Mapping[str, object],
) -> dict[str, object]:
    """Fail closed unless the exact parsed carrier census matches its receipt."""

    observed = html_carrier_census(content)
    if observed != expected:
        raise ValueError("Westminster retained HTML outer-carrier census drifted")
    return observed


__all__ = ["html_carrier_census", "verify_html_carrier_census"]
