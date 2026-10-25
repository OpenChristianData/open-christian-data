"""Bind the existing Revised Version corpus candidate to its accepted scope.

This changes only corpus-level workflow metadata. It preserves each retained
member body byte-for-byte and does not reconstruct or acquire source text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping
from xml.sax.saxutils import escape, quoteattr

from lxml import etree


WORK_ID = "revised-version-with-apocrypha"
FORM_ID = "revised-version-with-apocrypha-retained-en"
EDITION_ID = "revised-version-with-apocrypha-electronic"
ACQUISITION_ID = "revised-version-with-apocrypha-acquired"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "http://www.w3.org/XML/1998/namespace"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACQUISITION_PATH = (
    Path("library/works") / WORK_ID / "forms" / FORM_ID / "editions" / EDITION_ID
    / "acquisitions" / f"{ACQUISITION_ID}.json"
)
REVISION = {
    "id": "revised-version-with-apocrypha-accepted-electronic-v1",
    "date": "2026-10-02",
    "note": (
        "Bound the retained 80-member ENGRV5 electronic witness to its work, "
        "edition, acquisition, source member set, and accepted scope; preserved "
        "the original corpus and member text bytes."
    ),
}
OLD_PUBLISHER = "Nonaccepted ticket-21 source-faithful candidate; not publication."
ACCEPTED_PUBLISHER = "Accepted private library master; no publication is claimed."


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def bind_accepted_corpus_header(
    original: bytes,
    *,
    expected_sha256: str,
    identity: Mapping[str, str],
    source: Mapping[str, object],
    source_url: str,
    declared_scope: str,
    revision: Mapping[str, str] = REVISION,
) -> tuple[bytes, dict[str, object]]:
    """Add the canonical acceptance binding to one corpus TEI header.

    Corpus members retain their own source headers. The bound work identity and
    source scope therefore belong in the single outer teiCorpus header. The
    exact inverse below proves that no other bytes changed.
    """

    if _sha(original) != expected_sha256:
        raise ValueError("candidate bytes do not match the expected source candidate")
    required_identity = {"work_id", "textual_form_id", "edition_id", "acquisition_id"}
    if set(identity) != required_identity:
        raise ValueError("acceptance binding requires the four declared identity fields")
    required_source = {"source_path", "source_sha256", "source_bytes", "source_kind"}
    if not required_source <= set(source) or not all(
        isinstance(source[key], (str, int)) for key in required_source
    ):
        raise ValueError("acceptance binding source facts are incomplete")
    if not source_url or not declared_scope:
        raise ValueError("source URL and declared scope are required")

    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(original, parser)
    ns = {"t": TEI_NS}
    if root.tag != f"{{{TEI_NS}}}teiCorpus" or root.getroottree().docinfo.doctype:
        raise ValueError("candidate must be a TEI P5 corpus without a doctype")
    children = list(root)
    if (
        len(children) != 81
        or children[0].tag != f"{{{TEI_NS}}}teiHeader"
        or any(child.tag != f"{{{TEI_NS}}}TEI" for child in children[1:])
    ):
        raise ValueError("candidate must contain one corpus header and 80 ordered TEI members")
    for member in children[1:]:
        if [node.tag for node in member] != [f"{{{TEI_NS}}}teiHeader", f"{{{TEI_NS}}}text"]:
            raise ValueError("a corpus member lacks its retained header/text pair")

    header = children[0]
    source_desc = header.xpath("./t:fileDesc/t:sourceDesc", namespaces=ns)
    revision_desc = header.xpath("./t:revisionDesc", namespaces=ns)
    if len(source_desc) != 1 or len(revision_desc) != 1:
        raise ValueError("corpus header must have one sourceDesc and one revisionDesc")
    if header.xpath("./t:fileDesc/t:sourceDesc/t:bibl[@type='ocd-acceptance-binding']", namespaces=ns):
        raise ValueError("corpus header already has an acceptance binding")
    if root.xpath("//*[@xml:id=$value]", namespaces={"xml": XML_ID}, value=revision["id"]):
        raise ValueError("candidate already has the selected acceptance revision id")

    publishers = root.xpath(".//t:teiHeader/t:fileDesc/t:publicationStmt/t:publisher", namespaces=ns)
    if len(publishers) != 81 or any("".join(node.itertext()).strip() != OLD_PUBLISHER for node in publishers):
        raise ValueError("candidate publisher metadata differs from the known nonaccepted placeholder")
    member_roots = children[1:]
    if sum(member.get("ana") == "#nonaccepted-candidate" for member in member_roots) != 80:
        raise ValueError("candidate member status markers differ from the expected nonaccepted form")
    if any(member.get("ana") != "#nonaccepted-candidate" for member in member_roots):
        raise ValueError("candidate contains a competing member status marker")
    existing_ids = header.xpath(".//t:idno/@type", namespaces=ns)
    bound_types = set(identity) | {"source_sha256", "source_bytes", "source_kind", "representation_revision", "sha256"}
    if bound_types & set(existing_ids):
        raise ValueError("corpus header already carries one or more acceptance identity bindings")

    facts = dict(identity) | {
        "source_sha256": str(source["source_sha256"]),
        "source_bytes": str(source["source_bytes"]),
        "source_kind": str(source["source_kind"]),
        "representation_revision": revision["id"],
        "sha256": str(source["source_sha256"]),
    }
    binding = '<bibl xmlns="' + TEI_NS + '" type="ocd-acceptance-binding">'
    binding += "<ptr target=" + quoteattr(source_url) + "/>"
    for key, value in facts.items():
        binding += "<idno type=" + quoteattr(key) + ">" + escape(value) + "</idno>"
    for key, value in (("source-location", source["source_path"]), ("source-scope", declared_scope)):
        binding += "<note type=" + quoteattr(key) + ">" + escape(str(value)) + "</note>"
    binding += "</bibl>"
    change = (
        '<change xmlns="' + TEI_NS + '" xml:id=' + quoteattr(revision["id"])
        + " when=" + quoteattr(revision["date"]) + ">" + escape(revision["note"])
        + "</change>"
    )

    source_close = b"</sourceDesc>"
    revision_close = b"</revisionDesc>"
    source_at = original.find(source_close)
    revision_at = original.find(revision_close)
    if source_at < 0 or revision_at < 0 or revision_at <= source_at:
        raise ValueError("outer corpus header boundaries are not in the expected order")

    member_tag_pattern = re.compile(rb"<TEI\b[^>]*>")
    original_member_tags = [match.group(0) for match in member_tag_pattern.finditer(original)]
    if len(original_member_tags) != 80 or any(
        b' ana="#nonaccepted-candidate"' not in tag for tag in original_member_tags
    ):
        raise ValueError("candidate member opening tags differ from the expected corpus form")
    result = original.replace(OLD_PUBLISHER.encode("utf-8"), ACCEPTED_PUBLISHER.encode("utf-8"))
    if result.count(b' ana="#nonaccepted-candidate"') != 80:
        raise ValueError("candidate member status marker count changed unexpectedly")
    result = result.replace(b' ana="#nonaccepted-candidate"', b"")
    source_at = result.find(source_close)
    revision_at = result.find(revision_close)
    result = result[:source_at] + binding.encode("utf-8") + result[source_at:]
    revision_at = result.find(revision_close)
    result = result[:revision_at] + change.encode("utf-8") + result[revision_at:]
    etree.fromstring(result, parser)

    restored = result.replace(binding.encode("utf-8"), b"", 1)
    restored = restored.replace(change.encode("utf-8"), b"", 1)
    restored = restored.replace(ACCEPTED_PUBLISHER.encode("utf-8"), OLD_PUBLISHER.encode("utf-8"))
    restored_member_tags = [match.group(0) for match in member_tag_pattern.finditer(restored)]
    if len(restored_member_tags) != len(original_member_tags):
        raise ValueError("candidate member opening-tag count changed during inverse restoration")
    for match, old_tag in reversed(
        list(zip(member_tag_pattern.finditer(restored), original_member_tags))
    ):
        restored = restored[: match.start()] + old_tag + restored[match.end() :]
    if restored != original:
        raise ValueError("accepted-header repair changed bytes outside the declared metadata edits")

    return result, {
        "contract": "ocd-revised-version-accepted-corpus-header-v1",
        "source_candidate_sha256": expected_sha256,
        "source_candidate_bytes": len(original),
        "accepted_candidate_sha256": _sha(result),
        "accepted_candidate_bytes": len(result),
        "corpus_members": 80,
        "publisher_status_updates": len(publishers),
        "removed_nonaccepted_member_markers": 80,
        "added_acceptance_binding": True,
        "added_representation_revision": revision["id"],
        "inverse_restoration_sha256": _sha(restored),
        "inverse_restoration_matches_input": restored == original,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()

    root = args.root.resolve(strict=True)
    acquisition_path = root / ACQUISITION_PATH
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    identity = {
        "work_id": WORK_ID,
        "textual_form_id": FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
    }
    source = {
        "source_path": acquisition["source_path"],
        "source_sha256": acquisition["source_sha256"],
        "source_bytes": acquisition["source_bytes"],
        "source_kind": acquisition["source_kind"],
    }
    result, receipt = bind_accepted_corpus_header(
        args.input.read_bytes(),
        expected_sha256=args.expected_sha256,
        identity=identity,
        source=source,
        source_url=acquisition["url"],
        declared_scope=acquisition["source_scope"],
    )
    output = args.output.resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"refusing to replace an existing acceptance candidate: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result)
    receipt["output_path"] = output.as_posix()
    print(_canonical(receipt).decode("utf-8"), end="")


if __name__ == "__main__":
    main()
