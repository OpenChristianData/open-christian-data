"""Independent source/TEI checks for the exact 37c-048 ThML member."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from lxml import etree

from ocd_kernel.library.acquisitions import validate_acquisition
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.source_selection import verify_source_selection
from ocd_kernel.reconstruction.contract import (
    _canonical,
    _runtime_binding,
    _validation_authority_bindings,
)
from ocd_kernel.tei.validate import compiled_schema

NS = {"t": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
TAGS = {
    "div1": "div", "div2": "div", "div3": "div", "p": "p",
    "h1": "head", "h2": "head", "span": "seg", "i": "hi", "em": "hi",
    "note": "note", "pb": "pb", "scripRef": "ref", "br": "lb",
}
CLOSURE = (
    "build/tei/augustine_on_christian_doctrine_oracle.py",
    "ocd_kernel/library/acquisitions.py",
    "ocd_kernel/library/identities.py",
    "ocd_kernel/library/source_selection.py",
    "ocd_kernel/library/_common.py",
    "ocd_kernel/lib/storage_topology.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/tei/validate.py",
    "schemas/v2/acquisition.schema.json",
    "schemas/v2/work.schema.json",
)


def _closure_digest(root: Path) -> str:
    records = [
        {"path": name, "sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()}
        for name in CLOSURE
    ]
    return hashlib.sha256(_canonical(records)).hexdigest()


def _css_rules(source):
    rules = []
    for style in source.xpath('/ThML/ThML.head/style[@type="text/css"]'):
        css = style.text or ""
        if re.sub(r"[^{}]+\{[^{}]*\}", "", css).strip():
            raise ValueError("37c-048 source CSS has an unsupported rule")
        for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            rules.append((selector.strip(), declarations))
    return rules


def _oracle(manifest, candidate):
    manifest.verify()
    root = manifest.repository_root
    acquisition = validate_acquisition(manifest.authority_path("acquisition"), root=root)
    work = load_work(manifest.authority_path("work"))
    verified = verify_source_selection(acquisition, work, root=root)
    if verified is None:
        raise ValueError("37c-048 source selection is missing")
    raw = manifest.authority_path("retained-source").read_bytes()
    source_tree = etree.fromstring(raw, etree.XMLParser(resolve_entities=False, no_network=True))
    selected = source_tree.xpath('/ThML/ThML.body/div1[@id="v"]')
    if len(selected) != 1:
        raise ValueError("37c-048 source work root is missing or ambiguous")
    source_nodes = [node for node in selected[0].iter() if isinstance(node.tag, str)]
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    schema = compiled_schema()
    if not schema.validate(tei):
        raise ValueError(f"37c-048 TEI schema validation failed: {schema.error_log}")
    for key, value in {
        "work_id": work["work_id"], "textual_form_id": work["textual_forms"][0]["textual_form_id"],
        "edition_id": acquisition["edition_id"], "acquisition_id": acquisition["acquisition_id"],
        "source_sha256": acquisition["source_sha256"], "source_bytes": str(len(raw)),
        "source_selection_sha256": verified["selection_sha256"],
    }.items():
        observed = tei.xpath("/t:TEI/t:teiHeader//t:idno[@type=$kind]/text()", kind=key, namespaces=NS)
        if observed != [value]:
            raise ValueError(f"37c-048 candidate source binding differs: {key}")

    body_roots = tei.xpath("/t:TEI/t:text/t:body/*", namespaces=NS)
    if len(body_roots) != 1:
        raise ValueError("37c-048 candidate body does not contain exactly one work root")
    source_ids = {
        node.get("id"): f"src-{index}"
        for index, node in enumerate(source_nodes, 1)
        if node.get("id")
    }
    css_rules = _css_rules(source_tree)
    observed_renditions = tei.xpath("/t:TEI/t:teiHeader/t:encodingDesc/t:tagsDecl/t:rendition", namespaces=NS)
    if [(node.get("selector"), node.text) for node in observed_renditions] != css_rules:
        raise ValueError("37c-048 source stylesheet rendition differs")

    checked = 0

    def compare(source, output):
        nonlocal checked
        if not isinstance(source.tag, str):
            if not isinstance(source, etree._Comment) or not isinstance(output, etree._Comment):
                raise ValueError("37c-048 source comment was lost")
            if (source.text, source.tail) != (output.text, output.tail):
                raise ValueError("37c-048 source comment attachment differs")
            return
        if source.tag not in TAGS or output.tag != f"{{{NS['t']}}}{TAGS[source.tag]}":
            raise ValueError(f"37c-048 source element mapping differs: {source.tag}")
        checked += 1
        if output.get(XML_ID) != f"src-{checked}":
            raise ValueError("37c-048 selected source order or feature identity differs")
        if (source.text, source.tail) != (output.text, output.tail):
            raise ValueError(f"37c-048 source text/tail differs at {source.get('id')}")
        expected = {XML_ID: f"src-{checked}"}
        for source_key, target_key in (("n", "n"), ("class", "rend"), ("style", "style"), ("lang", XML_LANG)):
            if source.get(source_key):
                expected[target_key] = source.get(source_key)
        if source.tag in ("i", "em"):
            expected["rend"] = "italic"
        matching_styles = [
            f"#source-style-{index}" for index, (selector, _) in enumerate(css_rules, 1)
            if selector.split(".")[-1] in source.get("class", "").split()
            and (selector.startswith(".") or selector.split(".")[0] == source.tag)
        ]
        if matching_styles:
            expected["rendition"] = " ".join(matching_styles)
        if source.tag.startswith("div"):
            if source.get("type"):
                expected["type"] = source.get("type")
            for relation in ("prev", "next"):
                native_id = source.get(relation)
                if native_id:
                    expected[relation] = f"#{source_ids[native_id]}" if native_id in source_ids else f"{acquisition['url']}#{native_id}"
        if source.tag == "note" and source.get("place"):
            expected["place"] = source.get("place")
        if source.tag == "pb" and source.get("href"):
            expected["facs"] = source.get("href")
        if source.tag == "scripRef":
            if source.get("passage"):
                expected["cRef"] = source.get("passage")
            if source.get("osisRef"):
                expected["target"] = source.get("osisRef")
            if source.get("version"):
                expected["source"] = source.get("version")
        if output.attrib != expected:
            raise ValueError(f"37c-048 mapped source attributes differ at {source.get('id')}")

        output_children = list(output)
        # The retained XML children, not division navigation attributes or
        # producer accounting, define the complete ordered visible carriers.
        if len(source) != len(output_children):
            raise ValueError("37c-048 source hierarchy or child attachment differs")
        for original_child, tei_child in zip(source, output_children):
            compare(original_child, tei_child)

    compare(selected[0], body_roots[0])
    if checked != len(source_nodes):
        raise ValueError("37c-048 selected feature accounting is incomplete")

    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    expected_features = [
        {"source_path": source_tree.getroottree().getpath(node), "native_id": node.get("id"),
         "source_tag": node.tag, "attributes": dict(node.attrib), "tei_id": f"src-{index}"}
        for index, node in enumerate(source_nodes, 1)
    ]
    if accounting.get("selected_features") != expected_features:
        raise ValueError("37c-048 retained-source feature accountability differs")
    expected_carriers = []
    for position, node in enumerate(source_tree.find("ThML.body")):
        if not isinstance(node.tag, str):
            raise ValueError("37c-048 has an unaccounted non-element body carrier")
        expected_carriers.append({
            "native_id": node.get("id"), "position": position, "title": node.get("title"),
            "disposition": "selected-work" if node is selected[0] else "outside-assigned-work",
        })
    if accounting.get("body_carriers") != expected_carriers:
        raise ValueError("37c-048 complete body-carrier accounting differs")
    docinfo = source_tree.getroottree().docinfo
    expected_shell = {
        "xml_version": docinfo.xml_version, "encoding": docinfo.encoding, "doctype": docinfo.doctype,
        "public_id": docinfo.public_id, "system_url": docinfo.system_url,
        "pre_root_comments": [node.text for node in source_tree.getroottree().getroot().itersiblings(preceding=True)],
        "root_text": source_tree.text, "post_root_nodes": [],
        "head_xml": etree.tostring(source_tree.find("ThML.head"), encoding="unicode"),
    }
    if accounting.get("document_shell") != expected_shell:
        raise ValueError("37c-048 XML declaration, doctype, comments, head, or root-text accounting differs")
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines()]
    if {item.get("scope") for item in unresolved} != {"constituent-edition-date", "rights-and-publication", "human-acceptance"}:
        raise ValueError("37c-048 unresolved decision inventory is incomplete")
    readme = candidate.member_bytes("README.source.md").decode("utf-8")
    if accounting["document_shell"]["head_xml"] not in readme:
        raise ValueError("37c-048 human-readable source header is missing")

    attestation = {
        "status": "pass", "oracle_id": _oracle.oracle_id, "oracle_version": _oracle.oracle_version,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "import_closure_sha256": _closure_digest(root), "runtime": _runtime_binding(),
        "source_manifest_sha256": manifest.sha256, "candidate_sha256": candidate.sha256,
        **_validation_authority_bindings(manifest),
        "findings": [
            f"Independently compared {checked} selected source elements, including exact text, order, hierarchy, mapped attributes, original title paragraphs, notes, page breaks, and scripture references.",
            "Accounted for all seven direct ThML.body carriers and the bound complete-document shell/header.",
            "Candidate remains nonaccepted; edition-date, rights, human-acceptance, release, and publication questions remain unresolved.",
        ],
    }
    attestation["result_sha256"] = hashlib.sha256(_canonical(attestation)).hexdigest()
    return attestation


_oracle.oracle_id = "ocd-37c-048-augustine-on-christian-doctrine-independent-check"
_oracle.oracle_version = "2"
