"""Independent Holy Images reader: HTML5 source versus readable TEI."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

import bs4
from bs4 import BeautifulSoup, Comment, Tag
import lxml
from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-pg49917-holy-images-independent-html5-oracle"
ORACLE_VERSION = "1"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
TEI = "http://www.tei-c.org/ns/1.0"
PART_IDS = (
    "part-i-nl-apologia-of-st-john-damascene-against-those-who-decry-holy-images",
    "part-ii",
    "part-iii-20",
)
NOTE_IDS = tuple(f"id{number}" for number in range(52, 81))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _text(value: object) -> str:
    if isinstance(value, Tag):
        raw = value.get_text()
    elif isinstance(value, etree._Element):
        raw = "".join(value.itertext())
    else:
        raise TypeError("unknown source or candidate text carrier")
    return " ".join(raw.split())


def _closure() -> str:
    contract_path = Path(sys.modules[SourceManifest.__module__].__file__).resolve(strict=True)
    storage_path = Path(sys.modules[resolve_repo_path.__module__].__file__).resolve(strict=True)
    return _sha(_json({
        "oracle_file_sha256": _sha(Path(__file__).read_bytes()),
        "contract_file_sha256": _sha(contract_path.read_bytes()),
        "storage_topology_file_sha256": _sha(storage_path.read_bytes()),
        "bs4_version": bs4.__version__,
        "lxml_version": lxml.__version__,
    }))


def _source(manifest: SourceManifest) -> tuple[BeautifulSoup, dict[str, object], bytes]:
    source_path = resolve_repo_path(manifest.repository_root, "raw/gutenberg/49917/html/pg49917-images.html")
    if not source_path.samefile(manifest.authority_path("retained-html")):
        raise ValueError("Holy Images logical source route differs from manifest authority")
    raw = source_path.read_bytes()
    if len(raw) != 361466 or _sha(raw) != "a517174360b8c13609b74c005965f1386e6a0cc0f97fd795d248ccb496944204":
        raise ValueError("Holy Images source bytes changed")
    soup = BeautifulSoup(raw, "html5lib")
    profile = json.loads(manifest.authority_path("work-profile").read_bytes())
    if profile.get("contract") != "ocd-pg49917-holy-images-profile-v1" or profile.get("source_sha256") != _sha(raw):
        raise ValueError("Holy Images source profile changed")
    return soup, profile, raw


def _profile_observations(soup: BeautifulSoup, raw: bytes) -> dict[str, object]:
    parts = [soup.find(id=name) for name in PART_IDS]
    notes = [soup.find(id=name) for name in NOTE_IDS]
    if any(not isinstance(item, Tag) for item in parts + notes):
        raise ValueError("source part or note ID is absent")
    if not all(item.name == "div" for item in parts) or not all(item.name == "table" for item in notes):
        raise ValueError("source part or note carrier changed")
    index = soup.find(id="index")
    if not isinstance(index, Tag) or any(index not in list(item.parents) for item in notes):
        raise ValueError("source note placement changed")
    forward = [link for part in parts for link in part.find_all("a", href=True) if link["href"].startswith("#")]
    if tuple(link["href"][1:] for link in forward) != NOTE_IDS:
        raise ValueError("Holy Images forward note sequence changed")
    returns = [link for note in notes for link in note.find_all("a", href=True) if link["href"].startswith("#")]
    if len(returns) != 29 or any(soup.find(id=link["href"][1:]) is None for link in returns):
        raise ValueError("Holy Images note return sequence changed")
    source_ids = [item.get("id") for parent in parts + notes for item in [parent, *parent.find_all(id=True)] if item.get("id")]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("source selected IDs are duplicated")
    return {
        "contract": "ocd-pg49917-holy-images-profile-v1",
        "source_sha256": _sha(raw),
        "part_ids": list(PART_IDS),
        "note_ids": list(NOTE_IDS),
        "part_text_sha256": [_sha(_text(item).encode("utf-8")) for item in parts],
        "note_text_sha256": [_sha(_text(item).encode("utf-8")) for item in notes],
        "part_paragraph_counts": [len(item.find_all("p")) for item in parts],
        "part_heading_counts": [len(item.find_all(["h2", "h3", "h4"])) for item in parts],
        "part_div_counts": [len(item.find_all("div")) for item in parts],
        "part_emphasis_counts": [len(item.find_all("em")) for item in parts],
        "part_page_marker_counts": [len(item.find_all("span", class_="pageno")) for item in parts],
        "selected_source_id_count": len(source_ids),
        "selected_source_ids_sha256": _sha(_json(source_ids)),
        "forward_targets": [link["href"] for link in forward],
        "forward_ids": [link.get("id") for link in forward],
        "return_targets": [link["href"] for link in returns],
        "source_comment_count": sum(isinstance(item, Comment) for parent in parts + notes for item in parent.descendants),
        "source_note_layout_col_count": sum(len(note.find_all("col")) for note in notes),
        "source_note_layout_colgroup_count": sum(len(note.find_all("colgroup")) for note in notes),
        "source_note_layout_tbody_count": sum(len(note.find_all("tbody")) for note in notes),
    }


def _oracle(manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    manifest.verify()
    candidate.verify_integrity()
    if manifest.record.get("work_id") != "pg49917-holy-images" or candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("Holy Images work or candidate status changed")
    soup, profile, raw = _source(manifest)
    expected_profile = _profile_observations(soup, raw)
    if profile != expected_profile or manifest.authority_path("work-profile").read_bytes() != _json(expected_profile):
        raise ValueError("Holy Images profile does not match independent source inventory")
    policy = json.loads(manifest.authority_path("validation-policy").read_bytes())
    if policy != {"contract": "ocd-pg49917-holy-images-policy-v1", "work_id": "pg49917-holy-images", "scope": "Parts I-III and 29 index-held note tables; all other source HTML remains retained outside this work"}:
        raise ValueError("Holy Images validation policy changed")
    xml = candidate.member_bytes("content.tei.xml")
    tree = etree.fromstring(xml)
    if tree.tag != f"{{{TEI}}}TEI" or tree.get(XML_ID) != "pg49917-holy-images-tei":
        raise ValueError("Holy Images TEI root identity changed")
    ns = {"t": TEI}
    body_parts = tree.xpath("./t:text/t:body/t:div/t:div", namespaces=ns)
    back_notes = tree.xpath("./t:text/t:back/t:div/t:table", namespaces=ns)
    if [item.get(XML_ID) for item in body_parts] != list(PART_IDS) or [item.get(XML_ID) for item in back_notes] != list(NOTE_IDS):
        raise ValueError("Holy Images body or note boundary changed")
    source_parts = [soup.find(id=name) for name in PART_IDS]
    source_notes = [soup.find(id=name) for name in NOTE_IDS]
    for index, (source_part, tei_part) in enumerate(zip(source_parts, body_parts, strict=True)):
        if _text(source_part) != _text(tei_part):
            raise ValueError(f"Holy Images Part {index + 1} text, omission, duplication, or order drift")
        checks = (("p", "p"), ("h2", "head"), ("h3", "head"), ("h4", "head"), ("div", "div"), ("em", "hi"))
        for source_tag, candidate_tag in checks:
            expected = len(source_part.find_all(source_tag))
            if candidate_tag == "head":
                observed = len(tei_part.xpath(f".//t:head[@type='{source_tag}']", namespaces=ns))
            elif candidate_tag == "hi":
                observed = len(tei_part.xpath(".//t:hi[@rend='emphasis']", namespaces=ns))
            elif candidate_tag == "div":
                observed = len(tei_part.xpath(".//t:div[@type='source-html-div']", namespaces=ns))
            else:
                observed = len(tei_part.xpath(f".//t:{candidate_tag}", namespaces=ns))
            if observed != expected:
                raise ValueError(f"Holy Images Part {index + 1} {source_tag} structure drift")
        markers = source_part.find_all("span", class_="pageno")
        if [(item.get("id"), item.get("title")) for item in markers] != [
            (item.get(XML_ID), item.get("n")) for item in tei_part.xpath(".//t:seg[contains(@rend,'pageno')]", namespaces=ns)
        ]:
            raise ValueError(f"Holy Images Part {index + 1} page markers drifted")
    for note_id, source_note, tei_note in zip(NOTE_IDS, source_notes, back_notes, strict=True):
        if _text(source_note) != _text(tei_note):
            raise ValueError(f"Holy Images {note_id} text drifted")
        if len(tei_note.xpath("./t:row/t:cell", namespaces=ns)) != 2:
            raise ValueError(f"Holy Images {note_id} table cells drifted")
        if note_id == "id64" and len(tei_note.xpath(".//t:quote/t:lg/t:l", namespaces=ns)) != 4:
            raise ValueError("Holy Images note 13 four-line quotation drifted")
    body_refs = tree.xpath("./t:text/t:body//t:ref", namespaces=ns)
    note_refs = tree.xpath("./t:text/t:back//t:ref", namespaces=ns)
    if [item.get("target") for item in body_refs] != expected_profile["forward_targets"] or [item.get(XML_ID) for item in body_refs] != expected_profile["forward_ids"]:
        raise ValueError("Holy Images forward footnote attachment drifted")
    if [item.get("target") for item in note_refs] != expected_profile["return_targets"]:
        raise ValueError("Holy Images note return attachment drifted")
    ids = [item.get(XML_ID) for item in tree.xpath(".//*[@xml:id]", namespaces=ns) if item.get(XML_ID)]
    if len(ids) != len(set(ids)):
        raise ValueError("Holy Images TEI IDs are duplicated")
    for source_id in [item.get("id") for parent in source_parts + source_notes for item in [parent, *parent.find_all(id=True)] if item.get("id")]:
        if source_id not in ids:
            raise ValueError(f"Holy Images source ID {source_id} was omitted")
    for target in [item.get("target") for item in body_refs + note_refs]:
        if not target or not target.startswith("#") or target[1:] not in ids:
            raise ValueError("Holy Images link closure failed")
    comments = expected_profile["source_comment_count"]
    if len(tree.xpath(".//t:milestone[@unit='source-html-comment']", namespaces=ns)) != comments:
        raise ValueError("Holy Images source comment accounting drifted")
    if candidate.member_bytes("README.source.md") != manifest.authority_path("source-credit").read_bytes():
        raise ValueError("Holy Images source credit drifted")
    account = json.loads(candidate.member_bytes("source-accountability.json"))
    if account.get("source_scope") != {"container_id": "st-john-damascene-on-holy-images", "text_child_start": 19, "text_child_end_exclusive": 22, "part_ids": list(PART_IDS)} or account.get("notes") != {"source_parent_id": "index", "source_parent_child": 25, "ids": list(NOTE_IDS), "count": 29, "forward_reference_count": 29, "return_reference_count": 29} or account.get("candidate_tei_sha256") != _sha(xml) or account.get("source_feature_profile_sha256") != _sha(manifest.authority_path("work-profile").read_bytes()):
        raise ValueError("Holy Images source accounting drifted")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    if provenance.get("status") != "nonaccepted" or provenance.get("work_id") != "pg49917-holy-images" or provenance.get("source_sha256") != _sha(raw) or provenance.get("source_manifest_sha256") != manifest.sha256:
        raise ValueError("Holy Images provenance drifted")
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").splitlines()]
    if unresolved != [{"id": name, "status": "open"} for name in ("visual-review", "rights-review", "acceptance-install", "public-projection")]:
        raise ValueError("Holy Images unresolved gates drifted")
    schema = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
    if not schema.validate(tree):
        raise ValueError(f"Holy Images TEI P5 failed: {schema.error_log}")
    result = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure(),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(manifest.authority_path("work-profile").read_bytes()),
        "package_schema_sha256": _sha(manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _sha(raw),
        "xsd_sha256": _sha(manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(manifest.authority_path("validation-policy").read_bytes()),
        "findings": [],
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
