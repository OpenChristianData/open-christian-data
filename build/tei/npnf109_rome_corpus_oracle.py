"""Independent retained-XML check of the four-letter NPNF109 Rome corpus."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from lxml import etree

from build.tei import npnf109_chrysostom_oracle as source_rules
from build.tei.npnf109_work_oracle import _check_node
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _io_path


ORACLE_ID = "ocd-npnf109-rome-four-letter-source-oracle"
ORACLE_VERSION = "1"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_ORDER = ("xviii.i", "xviii.ii", "xviii.iii", "xviii.iv", "xviii.v", "xviii.vi")
SHARED = ("i", "ii", "iii", "xx", "xxi")
AUTHOR_ORDER = ("John Chrysostom", "John Chrysostom", "Innocent, Bishop of Rome", "Innocent, Bishop of Rome")


def _sha(value: bytes) -> str:
    return sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _source_match(source_node: etree._Element, tei_node: etree._Element,
                  ordinal: int) -> None:
    checked = deepcopy(tei_node)
    checked.tail = source_node.tail
    final = _check_node(source_node, checked, ordinal, root=False, work_id="")
    expected = sum(1 for node in source_node.iter() if isinstance(node.tag, str))
    if final != ordinal + expected - 1:
        raise ValueError("Rome source feature traversal incomplete")


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    manifest.verify()
    candidate.verify_integrity()
    binding_bytes = manifest.authority_path("rome-binding").read_bytes()
    binding = json.loads(binding_bytes)
    policy_bytes = manifest.authority_path("rome-policy").read_bytes()
    policy = json.loads(policy_bytes)
    if (binding.get("contract") != "ocd-npnf109-rome-corpus-binding-v1"
            or policy.get("contract") != "ocd-npnf109-rome-corpus-policy-v1"
            or policy.get("source_sha256") != binding["source_sha256"]
            or policy.get("publication") != "not_ready"
            or set(policy.get("required_member_names", [])) != set(candidate.member_names)):
        raise ValueError("Rome corpus binding or policy changed")
    source_bytes = manifest.authority_path("retained-thml").read_bytes()
    if _sha(source_bytes) != source_rules.SOURCE_HASH or len(source_bytes) != source_rules.SOURCE_BYTES:
        raise ValueError("retained Rome source bytes changed")
    source = etree.fromstring(source_bytes, etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True,
    ))
    body = source.find("ThML.body")
    if body is None:
        raise ValueError("retained source body absent")
    roots = list(body)
    if [node.get("id") for node in roots] != ["i", "ii", "iii", *[row[0] for row in source_rules.ASSIGNED], "xx", "xxi"]:
        raise ValueError("retained volume root order changed")
    selected = next(node for node in roots if node.get("id") == "xviii")
    children = list(selected)
    if (selected.get("title") != binding["source_title"]
            or [node.get("id") for node in children] != list(SOURCE_ORDER)
            or _sha(etree.tostring(selected, method="c14n")) != binding["source_root_c14n_sha256"]):
        raise ValueError("Rome collection root, title, or order changed")
    for child in children:
        if _sha(etree.tostring(child, method="c14n")) != binding["children"][child.get("id")]:
            raise ValueError(f"Rome child source hash changed: {child.get('id')}")
    intro_text = " ".join(" ".join(children[1].itertext()).split())
    if not all(fragment in intro_text for fragment in (
        "The first letter of St. Chrysostom", "The second was written",
        "To Chrysostom Innocent writes", "In his letter to the Church of Constantinople",
    )):
        raise ValueError("source sender attribution changed")
    if [row["author"] for row in binding["letters"]] != list(AUTHOR_ORDER):
        raise ValueError("Rome mixed-sender attribution changed")
    for name in ("work_path", "acquisition_path"):
        relative = Path(binding[name])
        if not relative.is_relative_to(Path("library/works") / binding["work_id"]):
            raise ValueError(f"Rome {name} escapes work home")
        content = Path(_io_path(manifest.repository_root / relative)).read_bytes()
        if _sha(content) != binding[name.replace("_path", "_sha256")]:
            raise ValueError(f"Rome {name} sidecar changed")
    work = json.loads(Path(_io_path(manifest.repository_root / binding["work_path"])).read_bytes())
    acquisition = json.loads(Path(_io_path(manifest.repository_root / binding["acquisition_path"])).read_bytes())
    edition_matches = [edition for form in work["textual_forms"] for edition in form["editions"]
                       if form["textual_form_id"] == binding["textual_form_id"]
                       and edition["edition_id"] == binding["edition_id"]]
    retained = acquisition.get("retained_files", [])
    if (work["work_id"] != binding["work_id"] or len(edition_matches) != 1
            or edition_matches[0]["containing_source"]["locator"] != f"{binding['source_path']}#xviii"
            or binding["acquisition_id"] not in edition_matches[0]["acquisition_ids"]
            or acquisition["url"] != binding["source_url"] or len(retained) != 1
            or retained[0]["path"] != binding["source_path"]
            or retained[0]["sha256"] != binding["source_sha256"]
            or retained[0]["bytes"] != len(source_bytes)):
        raise ValueError("Rome live work, edition, or acquisition binding changed")

    tei_bytes = candidate.member_bytes("content.tei.xml")
    tree = etree.ElementTree(etree.fromstring(tei_bytes, etree.XMLParser(
        resolve_entities=False, no_network=True, huge_tree=True,
    )))
    xsd = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
    if not xsd.validate(tree):
        raise ValueError(f"Rome TEI corpus P5 XSD failure: {xsd.error_log.last_error}")
    corpus = tree.getroot()
    if (corpus.tag != f"{{{TEI}}}teiCorpus" or corpus.get(XML_ID) != "npnf109-rome-correspondence-electronic"
            or [node.tag for node in corpus] != [f"{{{TEI}}}teiHeader", *[f"{{{TEI}}}TEI"] * 4]):
        raise ValueError("candidate is not one four-member TEI corpus")
    outer_title = corpus.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}titleStmt/{{{TEI}}}title")
    outer_url = corpus.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}sourceDesc/{{{TEI}}}bibl/{{{TEI}}}ptr")
    outer_hash = corpus.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}sourceDesc/{{{TEI}}}bibl/{{{TEI}}}idno[@type='SHA-256']")
    if (outer_title is None or outer_title.text != binding["source_title"]
            or outer_url is None or outer_url.get("target") != binding["source_url"]
            or outer_hash is None or outer_hash.text != binding["source_sha256"]):
        raise ValueError("Rome collection TEI header source binding changed")
    seen_ids = [node.get(XML_ID) for node in corpus.iter() if node.get(XML_ID)]
    if len(seen_ids) != len(set(seen_ids)):
        raise ValueError("Rome TEI corpus duplicates xml:id values")
    numbered = [node for root in roots[3:-2] for node in root.iter() if isinstance(node.tag, str)]
    ordinal = {id(node): number for number, node in enumerate(numbered, 1)}
    members = list(corpus)[1:]
    expected_context = children[:2]
    first_text = members[0].find(f"{{{TEI}}}text")
    if first_text is None or [node.tag for node in first_text] != [f"{{{TEI}}}front", f"{{{TEI}}}body"]:
        raise ValueError("first Rome member lacks collection front and letter body")
    front = first_text[0]
    if (len(front) != 3 or front[2].tag != f"{{{TEI}}}div"
            or front[2].attrib != {"type": "collection-context", XML_ID: "npnf109-xviii-first-letter-banner"}
            or len(front[2]) != 2 or (front[2].text or "").strip()):
        raise ValueError("Rome collection title, introduction, or banner changed")
    for source_node, target_node in zip(expected_context, list(front)[:2], strict=True):
        _source_match(source_node, target_node, ordinal[id(source_node)])
    first_source = children[2]
    for source_node, target_node in zip(list(first_source)[:2], list(front[2]), strict=True):
        _source_match(source_node, target_node, ordinal[id(source_node)])
    for index, (source_letter, member, detail) in enumerate(zip(children[2:], members, binding["letters"], strict=True)):
        if (member.tag != f"{{{TEI}}}TEI" or member.get(XML_ID) != f"npnf109-{detail['source_id']}-letter"
                or detail["source_id"] != source_letter.get("id")
                or detail["title"] != source_letter.get("title")
                or detail["author"] != AUTHOR_ORDER[index]):
            raise ValueError("Rome member identity, source title, or author changed")
        if not xsd.validate(etree.ElementTree(deepcopy(member))):
            raise ValueError(f"Rome member P5 XSD failure: {xsd.error_log.last_error}")
        title = member.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}titleStmt/{{{TEI}}}title")
        author = member.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}titleStmt/{{{TEI}}}author")
        url = member.find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}sourceDesc/{{{TEI}}}bibl/{{{TEI}}}ptr")
        if (title is None or title.text != detail["title"] or author is None or author.text != detail["author"]
                or url is None or url.get("target") != binding["source_url"]):
            raise ValueError("Rome member header differs from retained attribution")
        member_text = member.find(f"{{{TEI}}}text")
        if member_text is None or [node.tag for node in member_text] != ([f"{{{TEI}}}front", f"{{{TEI}}}body"] if index == 0 else [f"{{{TEI}}}body"]):
            raise ValueError("Rome member front/body sequence changed")
        body_node = member_text.find(f"{{{TEI}}}body")
        if body_node is None or len(body_node) != 1 or body_node[0].get(XML_ID) != f"npnf109-{detail['source_id']}":
            raise ValueError("Rome member must contain exactly one source letter division")
        letter = deepcopy(body_node[0])
        notes = letter.findall(f"{{{TEI}}}note[@type='source-attribution']")
        if (len(notes) != 1 or notes[0] is not letter[-1] or len(notes[0]) != 1
                or notes[0][0].tag != f"{{{TEI}}}seg" or notes[0][0].get("type") != "attribution-note"
                or notes[0][0].text != detail["attribution_note"]):
            raise ValueError("Rome letter attribution note changed")
        letter.remove(notes[0])
        if index == 0:
            for offset, banner_part in enumerate(front[2], 1):
                letter.insert(offset, deepcopy(banner_part))
        _source_match(source_letter, letter, ordinal[id(source_letter)])

    shared = []
    for identifier in SHARED:
        node = next(item for item in roots if item.get("id") == identifier)
        shared.append({"source_root_id": identifier, "source_title": node.get("title"),
                       "source_c14n_sha256": _sha(etree.tostring(node, method="c14n")),
                       "disposition": "retained-volume-matter-outside-child-body"})
    if shared != binding["shared_volume_roots"]:
        raise ValueError("Rome shared volume context changed")
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    if (accounting.get("contract") != "ocd-npnf109-rome-corpus-accounting-v1"
            or accounting.get("work_id") != binding["work_id"]
            or accounting.get("source_path") != binding["source_path"]
            or accounting.get("source_sha256") != binding["source_sha256"]
            or accounting.get("source_root_id") != "xviii"
            or accounting.get("source_root_c14n_sha256") != binding["source_root_c14n_sha256"]
            or accounting.get("source_element_count") != sum(1 for node in selected.iter() if isinstance(node.tag, str))
            or accounting.get("source_attribute_count") != sum(len(node.attrib) for node in selected.iter() if isinstance(node.tag, str))
            or accounting.get("source_order") != list(SOURCE_ORDER)
            or accounting.get("shared_volume_roots") != shared
            or [item.get("source_id") for item in accounting.get("letters", [])] != list(SOURCE_ORDER[2:])
            or [item.get("member_id") for item in accounting["letters"]] != [item.get(XML_ID) for item in members]
            or accounting.get("edition_context_ownership") != "First member front, not authorial body; source order retained exactly once."):
        raise ValueError("Rome source accounting differs")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if (provenance.get("contract") != "ocd-npnf109-rome-corpus-provenance-v1"
            or provenance.get("status") != "nonaccepted"
            or provenance.get("work_id") != binding["work_id"]
            or provenance.get("edition_id") != binding["edition_id"]
            or provenance.get("member_count") != 4
            or provenance.get("canonical_ir_written") is not False
            or provenance.get("publication") != "not_ready"):
        raise ValueError("Rome candidate provenance changed")
    if (b"Sourced via CCEL.org" not in candidate.member_bytes("README.source.md")
            or not candidate.member_bytes("unresolved.jsonl").strip()):
        raise ValueError("Rome source attribution or unresolved evidence absent")
    result = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": manifest.record["validator"]["import_closure_sha256"],
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256, "candidate_sha256": candidate.sha256,
        "source_sha256": _sha(source_bytes), "profile_sha256": _sha(binding_bytes),
        "package_schema_sha256": _sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        "xsd_sha256": _sha(manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes), "findings": [],
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
