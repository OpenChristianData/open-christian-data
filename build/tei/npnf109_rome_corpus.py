"""Reconstruct the four retained NPNF109 Rome letters as a TEI corpus."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Mapping

from lxml import etree

from build.tei.npnf109_work_reconstruction import _convert as convert_work
from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-npnf109-rome-four-letter-corpus"
CONVERTER_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
LETTER_IDS = ("xviii.iii", "xviii.iv", "xviii.v", "xviii.vi")
CONTEXT_IDS = ("xviii.i", "xviii.ii")


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _header(title: str, *, source_url: str, source_sha256: str, author: str | None,
            description: str, revision_id: str) -> etree._Element:
    header = etree.Element(f"{{{TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI}}}title").text = title
    if author is not None:
        etree.SubElement(title_stmt, f"{{{TEI}}}author").text = author
    etree.SubElement(etree.SubElement(file_desc, f"{{{TEI}}}publicationStmt"), f"{{{TEI}}}p").text = (
        "Nonaccepted electronic reconstruction; publication not authorized."
    )
    bibl = etree.SubElement(etree.SubElement(file_desc, f"{{{TEI}}}sourceDesc"), f"{{{TEI}}}bibl")
    etree.SubElement(bibl, f"{{{TEI}}}ptr", target=source_url)
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="SHA-256").text = source_sha256
    project = etree.SubElement(etree.SubElement(header, f"{{{TEI}}}encodingDesc"), f"{{{TEI}}}projectDesc")
    etree.SubElement(project, f"{{{TEI}}}p").text = description
    change = etree.SubElement(etree.SubElement(header, f"{{{TEI}}}revisionDesc"), f"{{{TEI}}}change", when="2026-09-27")
    change.set(XML_ID, revision_id)
    change.text = "Reconstructed from the exact retained electronic XML."
    return header


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    manifest.verify()
    binding = json.loads(manifest.authority_path("rome-binding").read_bytes())
    if binding.get("contract") != "ocd-npnf109-rome-corpus-binding-v1":
        raise ValueError("Rome corpus binding changed")
    source_bytes = manifest.authority_path("retained-thml").read_bytes()
    if _sha(source_bytes) != binding["source_sha256"]:
        raise ValueError("retained Rome source changed")
    source = etree.fromstring(source_bytes, etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True,
    ))
    source_roots = source.xpath("./ThML.body/div1[@id='xviii']")
    if (len(source_roots) != 1 or source_roots[0].get("title") != binding["source_title"]
            or _sha(etree.tostring(source_roots[0], method="c14n")) != binding["source_root_c14n_sha256"]
            or [node.get("id") for node in source_roots[0]] != [*CONTEXT_IDS, *LETTER_IDS]):
        raise ValueError("retained Rome collection boundary changed")
    old_manifest = SourceManifest.load(
        manifest.authority_path("old-work-manifest"), repository_root=manifest.repository_root,
    )
    old = convert_work(old_manifest)["content.tei.xml"]
    if _sha(old) != binding["old_work_tei_sha256"]:
        raise ValueError("previous verified whole-root candidate changed")
    old_tree = etree.fromstring(old, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    old_root = old_tree.xpath("./t:text/t:body/t:div", namespaces={"t": TEI})
    if len(old_root) != 1 or [node.get(XML_ID) for node in old_root[0][1:]] != [
        *(f"npnf109-{identifier}" for identifier in (*CONTEXT_IDS, *LETTER_IDS))
    ]:
        raise ValueError("mapped Rome child order changed")
    mapped = {node.get(XML_ID).removeprefix("npnf109-"): node for node in old_root[0][1:]}

    corpus = etree.Element(f"{{{TEI}}}teiCorpus", nsmap={None: TEI})
    corpus.set(XML_ID, "npnf109-rome-correspondence-electronic")
    corpus.append(_header(
        binding["source_title"], source_url=binding["source_url"],
        source_sha256=binding["source_sha256"], author=None,
        description="One ordered edition corpus with four separately validatable letters. The first member front retains collection-level title, introduction, and banner in source order.",
        revision_id="npnf109-rome-corpus-candidate-v1",
    ))
    for index, identifier in enumerate(LETTER_IDS, 1):
        detail = binding["letters"][index - 1]
        if detail["source_id"] != identifier:
            raise ValueError("Rome letter binding order changed")
        member = etree.SubElement(corpus, f"{{{TEI}}}TEI")
        member.set(XML_ID, f"npnf109-{identifier}-letter")
        member.append(_header(
            detail["title"], source_url=binding["source_url"],
            source_sha256=binding["source_sha256"], author=detail["author"],
            description=f"Complete source letter #{identifier}; collection front matter is not authorial letter text.",
            revision_id=f"npnf109-{identifier}-candidate-v1",
        ))
        text = etree.SubElement(member, f"{{{TEI}}}text")
        text.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
        if index == 1:
            front = etree.SubElement(text, f"{{{TEI}}}front")
            for context_id in CONTEXT_IDS:
                context = deepcopy(mapped[context_id])
                context.tail = None
                front.append(context)
            banner = etree.SubElement(front, f"{{{TEI}}}div", type="collection-context")
            banner.set(XML_ID, "npnf109-xviii-first-letter-banner")
            for paragraph in list(mapped[identifier])[1:3]:
                banner.append(deepcopy(paragraph))
        body = etree.SubElement(text, f"{{{TEI}}}body")
        letter = deepcopy(mapped[identifier])
        letter.tail = None
        if index == 1:
            for paragraph in list(letter)[1:3]:
                letter.remove(paragraph)
        note = etree.SubElement(letter, f"{{{TEI}}}note", type="source-attribution")
        etree.SubElement(note, f"{{{TEI}}}seg", type="attribution-note").text = detail["attribution_note"]
        body.append(letter)
    tei = etree.tostring(corpus, encoding="UTF-8", xml_declaration=True)
    accountability = {
        "contract": "ocd-npnf109-rome-corpus-accounting-v1",
        "work_id": binding["work_id"], "source_path": binding["source_path"],
        "source_sha256": binding["source_sha256"], "source_root_id": "xviii",
        "source_root_c14n_sha256": binding["source_root_c14n_sha256"],
        "source_element_count": sum(1 for node in source_roots[0].iter() if isinstance(node.tag, str)),
        "source_attribute_count": sum(len(node.attrib) for node in source_roots[0].iter() if isinstance(node.tag, str)),
        "source_order": [*CONTEXT_IDS, *LETTER_IDS],
        "context": [
            {"source_id": identifier, "source_c14n_sha256": binding["children"][identifier],
             "destination": "first-member-front"} for identifier in CONTEXT_IDS
        ] + [{"source_id": "xviii.iii-p1..p2", "destination": "first-member-front/collection-context"}],
        "letters": [
            {"source_id": item["source_id"], "source_c14n_sha256": binding["children"][item["source_id"]],
             "member_id": f"npnf109-{item['source_id']}-letter", "author": item["author"],
             "source_order": index} for index, item in enumerate(binding["letters"], 1)
        ],
        "shared_volume_roots": binding["shared_volume_roots"],
        "edition_context_ownership": "First member front, not authorial body; source order retained exactly once.",
        "root_title_destination": "edition teiCorpus header title",
        "root_tail_disposition": "excluded-selected-root-boundary",
    }
    provenance = {
        "contract": "ocd-npnf109-rome-corpus-provenance-v1", "status": "nonaccepted",
        "work_id": binding["work_id"], "textual_form_id": binding["textual_form_id"],
        "edition_id": binding["edition_id"], "acquisition_id": binding["acquisition_id"],
        "source_root_id": "xviii", "member_count": 4, "canonical_ir_written": False,
        "publication": "not_ready",
    }
    readme = (
        "# Correspondence of St. Chrysostom with the Bishop of Rome — retained electronic witness\n\n"
        "Four source-attested letters are independent TEI children of one ordered TEI corpus. "
        "The first member's front retains the collection title, introduction, and first-letter banner; "
        "letter body divisions carry source-attributed senders. Source: `raw/ccel/npnf1/npnf109.xml#xviii`.\n\n"
        "Sourced via CCEL.org. CCEL permits parsing ThML and asks for attribution; do not sell CCEL "
        "files or derivatives of CCEL formatting. The retained header states Public Domain. "
        "This electronic candidate is nonaccepted and publication is not ready.\n"
    ).encode("utf-8")
    unresolved = [
        {"status": "unresolved", "item": "Close visual review and print collation have not occurred."},
        {"status": "unresolved", "item": "Rights clearance and publication are separate decisions."},
    ]
    return {
        "content.tei.xml": tei, "source-accountability.json": _json(accountability),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
