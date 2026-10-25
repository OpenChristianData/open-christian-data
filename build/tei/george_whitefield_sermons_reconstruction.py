"""Source-bound provisional TEI route for the LIB-060 Whitefield cohort."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-lib060-george-whitefield-retained-cohort-to-tei"
CONVERTER_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SERMON_HEADING = re.compile(r"SERMON\s+([IVXLCDM]+)\.")
_BLOCK_SOURCE_TAGS = frozenset(
    {"div", "div1", "div2", "p", "h1", "h2", "h3", "h4", "scripCom", "insertIndex"}
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _producer_closure(root: Path) -> str:
    paths = (
        Path(__file__).resolve(strict=True),
        (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True),
        (root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True),
    )
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix())
    ]
    return _sha(_canonical(records))


def _profile(source_manifest: SourceManifest) -> dict[str, object]:
    return json.loads(
        source_manifest.authority_path("reconstruction-profile").read_text(
            encoding="utf-8"
        )
    )


def _authority(source_manifest: SourceManifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _source_set_sha256(source_manifest: SourceManifest) -> str:
    authorities = source_manifest.record["authorities"]
    members = [
        {
            key: authority[key]
            for key in ("name", "path", "bytes", "sha256")
        }
        for authority in authorities
        if authority["role"] == "primary-source"
    ]
    members.sort(key=lambda item: (str(item["path"]), str(item["name"])))
    if len(members) == 1:
        return str(members[0]["sha256"])
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _source_events(node: etree._Element) -> list[list[object]]:
    events: list[list[object]] = []

    def visit(current: etree._Element) -> None:
        if isinstance(current, etree._Comment):
            events.append(["comment", current.text or ""])
        elif isinstance(current, etree._ProcessingInstruction):
            events.append(["pi", current.target, current.text or ""])
        else:
            events.append(
                ["start", str(current.tag), [[key, value] for key, value in current.attrib.items()]]
            )
            if current.text is not None:
                events.append(["text", current.text])
            for child in current:
                visit(child)
                if child.tail is not None:
                    events.append(["tail", child.tail])
            events.append(["end", str(current.tag)])

    visit(node)
    return events


def _source_contains_block(source: etree._Element) -> bool:
    if isinstance(source, (etree._Comment, etree._ProcessingInstruction)):
        return False
    if str(source.tag) in _BLOCK_SOURCE_TAGS:
        return True
    return any(_source_contains_block(child) for child in source)


def _tei_name(local: str, source: etree._Element) -> str:
    if local in {"div", "div1", "div2"}:
        return "div"
    if local in {"h1", "h2", "h3", "h4"}:
        return "ab"
    if local == "p":
        return "p"
    if local in {"a", "scripRef"}:
        return "ref"
    if local in {"i", "b"}:
        return "hi"
    if local == "note":
        return "note"
    if local == "br":
        return "lb"
    if local in {"scripCom", "insertIndex"}:
        return "ab"
    if any(_source_contains_block(child) for child in source):
        return "div"
    return "seg"


def _map_source_element(
    source: etree._Element,
    *,
    carrier_id: str | None = None,
) -> etree._Element:
    if isinstance(source, etree._Comment):
        result = etree.Comment(source.text or "")
        result.tail = source.tail
        return result
    if isinstance(source, etree._ProcessingInstruction):
        result = etree.ProcessingInstruction(source.target, source.text or "")
        result.tail = source.tail
        return result
    local = str(source.tag)
    result = etree.Element(f"{{{_TEI}}}{_tei_name(local, source)}")
    result.set(
        "n",
        json.dumps(
            {
                "source_tag": local,
                "source_attributes": [[key, value] for key, value in source.attrib.items()],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    if local == "i":
        result.set("rend", "italic")
    elif local == "b":
        result.set("rend", "bold")
    if carrier_id is not None:
        result.set(_XML_ID, f"ccel-div1-{carrier_id}")
    result.text = source.text
    for child in source:
        mapped = _map_source_element(child)
        mapped.tail = child.tail
        result.append(mapped)
    return result


def _line_records(data: bytes) -> tuple[list[dict[str, object]], list[str]]:
    chunks = data.splitlines(keepends=True)
    records: list[dict[str, object]] = []
    texts: list[str] = []
    offset = 0
    for number, chunk in enumerate(chunks, 1):
        if chunk.endswith(b"\r\n"):
            body, ending = chunk[:-2], "CRLF"
        elif chunk.endswith(b"\n"):
            body, ending = chunk[:-1], "LF"
        elif chunk.endswith(b"\r"):
            body, ending = chunk[:-1], "CR"
        else:
            body, ending = chunk, "none"
        text = body.decode("utf-8", errors="strict")
        if number == 1 and text.startswith("\ufeff"):
            text = text[1:]
        texts.append(text)
        records.append(
            {
                "line": number,
                "byte_start": offset,
                "byte_end": offset + len(body),
                "terminator": ending,
                "record_sha256": _sha(body),
            }
        )
        offset += len(chunk)
    if offset != len(data):
        raise ValueError("Project Gutenberg line inventory does not span its exact bytes")
    return records, texts


def _pg_observation(
    data: bytes, member: Mapping[str, object]
) -> tuple[list[dict[str, object]], list[str], list[dict[str, object]], list[int]]:
    records, texts = _line_records(data)
    start = [
        index
        for index, line in enumerate(texts)
        if line.startswith("*** START OF THE PROJECT GUTENBERG EBOOK ")
    ]
    finish = [
        index
        for index, line in enumerate(texts)
        if line.startswith("*** END OF THE PROJECT GUTENBERG EBOOK ")
    ]
    if len(start) != 1 or len(finish) != 1 or start[0] >= finish[0]:
        raise ValueError("Project Gutenberg source envelope markers are missing or ambiguous")
    headings: list[tuple[int, str]] = []
    for index in range(start[0] + 1, finish[0]):
        match = _SERMON_HEADING.fullmatch(texts[index].strip())
        if match:
            headings.append((index, match.group(1)))
    expected_labels = member["expected_source_sermon_labels"]
    if [label for _, label in headings] != expected_labels:
        raise ValueError("Project Gutenberg source-native sermon sequence changed")
    finis = [
        index
        for index in range(headings[-1][0] + 1, finish[0])
        if texts[index].strip() == "FINIS."
    ]
    if len(finis) != 1:
        raise ValueError("Project Gutenberg closing FINIS marker is missing or ambiguous")

    sermon_rows: list[dict[str, object]] = []
    intervals: list[int] = [-1] * len(texts)
    selected_labels = set(member["selected_source_sermon_labels"])
    for position, (line_index, label) in enumerate(headings):
        end_index = headings[position + 1][0] if position + 1 < len(headings) else finis[0]
        selected = label in selected_labels
        disposition = (
            "represented-source-native-carrier"
            if selected
            else "not-selected-by-current-work-specific-config"
        )
        for line_no in range(line_index, end_index):
            intervals[line_no] = position
        title_index = next(
            (
                index
                for index in range(line_index + 1, end_index)
                if texts[index].strip()
            ),
            None,
        )
        start_byte = int(records[line_index]["byte_start"])
        end_byte = int(records[end_index - 1]["byte_end"])
        sermon_rows.append(
            {
                "source_label": label,
                "start_line": line_index + 1,
                "end_line_inclusive": end_index,
                "title_line": title_index + 1 if title_index is not None else None,
                "title_observation": texts[title_index] if title_index is not None else "",
                "block_sha256": _sha(data[start_byte:end_byte]),
                "disposition": disposition,
                "candidate_xml_id": f"pg77041-sermon-{label.lower()}" if selected else None,
                "exclusion_reason": None
                if selected
                else "The work-specific config names two supplementary titles, not this carrier; relation to the catalog work remains unresolved.",
            }
        )
    for index, record in enumerate(records):
        if intervals[index] >= 0:
            sermon = sermon_rows[intervals[index]]
            record["disposition"] = sermon["disposition"]
            record["carrier"] = sermon["source_label"]
        else:
            record["disposition"] = "provider-or-nonsermon-envelope-not-in-tei-body"
            record["carrier"] = None
    return records, texts, sermon_rows, [index + 1 for index, _ in headings]


def _xml_observation(
    tree: etree._ElementTree,
    root: etree._Element,
    body: etree._Element,
    member: Mapping[str, object],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, int],
    list[dict[str, str]],
    list[dict[str, str]],
]:
    divs = body.findall("div1")
    ids = [node.get("id") for node in divs]
    if ids != member["expected_direct_div1_ids"]:
        raise ValueError("CCEL direct div1 carrier order or identity changed")
    rows = []
    for index, node in enumerate(divs, 1):
        title = next(
            (" ".join("".join(child.itertext()).split()) for child in node if child.tag in {"h1", "h2", "h3", "h4"}),
            "",
        )
        rows.append(
            {
                "index": index,
                "source_id": node.get("id"),
                "source_tag": "div1",
                "source_title_observation": title,
                "event_sha256": _sha(_canonical(_source_events(node))),
                "disposition": "represented-complete-source-carrier",
                "candidate_xml_id": f"ccel-div1-{node.get('id')}",
            }
        )
    before_root = []
    node = root.getprevious()
    while node is not None:
        before_root.append(node)
        node = node.getprevious()
    before_root.reverse()
    after_root = []
    node = root.getnext()
    while node is not None:
        after_root.append(node)
        node = node.getnext()

    comments = []
    prolog_events = []
    for node in before_root:
        if isinstance(node, etree._Comment):
            comment = node.text or ""
            comments.append(
                {
                    "document_order": len(comments) + 1,
                    "parent_tag": None,
                    "text_sha256": _sha(comment.encode("utf-8")),
                    "text": comment,
                }
            )
            prolog_events.append({"kind": "comment", "text": comment})
        elif isinstance(node, etree._ProcessingInstruction):
            prolog_events.append(
                {"kind": "processing-instruction", "target": node.target, "data": node.text or ""}
            )
    in_root_comments = []
    for node in root.iter():
        if isinstance(node, etree._Comment):
            row = {
                "document_order": len(comments) + 1,
                "parent_tag": str(node.getparent().tag) if node.getparent() is not None else None,
                "text_sha256": _sha((node.text or "").encode("utf-8")),
                "text": node.text or "",
            }
            comments.append(row)
            in_root_comments.append(row)
    post_root_comments = []
    for node in after_root:
        if isinstance(node, etree._Comment):
            comment = node.text or ""
            row = {
                "document_order": len(comments) + 1,
                "parent_tag": None,
                "text_sha256": _sha(comment.encode("utf-8")),
                "text": comment,
            }
            comments.append(row)
            post_root_comments.append(row)
    counts: dict[str, int] = {}
    for node in root.iter():
        if isinstance(node.tag, str):
            counts[node.tag] = counts.get(node.tag, 0) + 1
    pis = [
        {"target": node.target, "data": node.text or ""}
        for node in before_root
        if isinstance(node, etree._ProcessingInstruction)
    ]
    pis.extend(
        {"target": node.target, "data": node.text or ""}
        for node in root.xpath(".//processing-instruction()")
    )
    pis.extend(
        {"target": node.target, "data": node.text or ""}
        for node in after_root
        if isinstance(node, etree._ProcessingInstruction)
    )
    if len(pis) != member["expected_processing_instruction_count"]:
        raise ValueError("CCEL source processing-instruction census changed")
    if len(comments) != member["expected_xml_comment_count"]:
        raise ValueError("CCEL XML comment census changed")
    if sum(isinstance(node, etree._Comment) for node in before_root) != member[
        "expected_pre_root_xml_comment_count"
    ]:
        raise ValueError("CCEL pre-root XML comment census changed")
    if sum(event["kind"] == "processing-instruction" for event in prolog_events) != member[
        "expected_pre_root_processing_instruction_count"
    ]:
        raise ValueError("CCEL pre-root processing-instruction census changed")
    if len(in_root_comments) != member["expected_in_root_xml_comment_count"]:
        raise ValueError("CCEL in-root XML comment census changed")
    if len(post_root_comments) != member["expected_post_root_xml_comment_count"]:
        raise ValueError("CCEL post-root XML comment census changed")
    return rows, comments, counts, pis, prolog_events


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    record = source_manifest.record
    if record.get("ticket_id") != "LIB-060" or record.get("work_id") != "george-whitefield-sermons":
        raise ValueError("George Whitefield manifest identity mismatch")
    if _producer_closure(source_manifest.repository_root) != record.get(
        "producer_import_closure_sha256"
    ):
        raise ValueError("George Whitefield producer import closure drifted")

    profile_bytes = _authority(source_manifest, "reconstruction-profile")
    policy_bytes = _authority(source_manifest, "validation-policy")
    profile = json.loads(profile_bytes)
    policy = json.loads(policy_bytes)
    if (
        profile.get("contract") != "ocd-george-whitefield-reconstruction-profile-v1"
        or policy.get("contract") != "ocd-george-whitefield-validation-policy-v1"
        or policy.get("source_envelope", {}).get("ccel_sha256")
        != profile["members"][0]["sha256"]
        or policy.get("source_envelope", {}).get("gutenberg_sha256")
        != profile["members"][1]["sha256"]
    ):
        raise ValueError("George Whitefield profile and validation policy disagree")
    route = json.loads(_authority(source_manifest, "legacy-route-observation"))
    if (
        route.get("collection_id") != record.get("work_id")
        or route.get("title") != profile.get("catalog_title_observation")
        or route.get("source_hash") != f"sha256:{profile['members'][0]['sha256']}"
        or route.get("supplementary_source", {}).get("source_hash")
        != f"sha256:{profile['members'][1]['sha256']}"
    ):
        raise ValueError("Legacy route observation no longer binds the declared raw members")

    ccel_member, pg_member = profile["members"]
    ccel_bytes = _authority(source_manifest, "retained-ccel-xml")
    pg_bytes = _authority(source_manifest, "retained-project-gutenberg-text")
    if len(ccel_bytes) != ccel_member["bytes"] or _sha(ccel_bytes) != ccel_member["sha256"]:
        raise ValueError("Retained CCEL source bytes drifted")
    if len(pg_bytes) != pg_member["bytes"] or _sha(pg_bytes) != pg_member["sha256"]:
        raise ValueError("Retained Project Gutenberg source bytes drifted")

    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        remove_blank_text=False,
        strip_cdata=False,
    )
    ccel_tree = etree.parse(str(source_manifest.authority_path("retained-ccel-xml")), parser)
    ccel_root = ccel_tree.getroot()
    ccel_body = ccel_root.find("ThML.body")
    ccel_head = ccel_root.find("ThML.head")
    if (
        ccel_root.tag != ccel_member["expected_root"]
        or ccel_body is None
        or ccel_head is None
        or ccel_tree.docinfo.doctype != ccel_member["expected_doctype"]
    ):
        raise ValueError("CCEL source document shell changed or is unsupported")
    carrier_rows, comments, element_counts, processing_instructions, prolog_events = _xml_observation(
        ccel_tree, ccel_root, ccel_body, ccel_member
    )
    if [row["source_id"] for row in carrier_rows if row["source_id"] in ccel_member["expected_sermon_div1_ids"]] != ccel_member["expected_sermon_div1_ids"]:
        raise ValueError("CCEL sermon carrier identity/order mismatch")

    line_inventory, pg_lines, pg_sermons, heading_indexes = _pg_observation(pg_bytes, pg_member)
    if len(line_inventory) != pg_member["expected_physical_line_count"]:
        raise ValueError("Project Gutenberg physical line count changed")
    selected_labels = set(pg_member["selected_source_sermon_labels"])
    selected_sermons = [row for row in pg_sermons if row["source_label"] in selected_labels]
    if [row["source_label"] for row in selected_sermons] != pg_member["selected_source_sermon_labels"]:
        raise ValueError("Selected Project Gutenberg source carriers are missing or reordered")

    root = etree.Element(f"{{{_TEI}}}TEI", nsmap={None: _TEI})
    root.set(_XML_ID, "george-whitefield-sermons-lib060-candidate")
    header = etree.SubElement(root, f"{{{_TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_TEI}}}titleStmt")
    ccel_title = ccel_head.findtext("title")
    if ccel_title != profile["catalog_title_observation"]:
        raise ValueError("CCEL source title does not match the catalog display-title observation")
    etree.SubElement(title_stmt, f"{{{_TEI}}}title").text = ccel_title
    publication = etree.SubElement(file_desc, f"{{{_TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{_TEI}}}publisher").text = "Open Christian Data"
    availability = etree.SubElement(publication, f"{{{_TEI}}}availability", status="unknown")
    etree.SubElement(availability, f"{{{_TEI}}}p").text = (
        "Nonaccepted candidate. Rights review was not performed; this record is not rights clearance."
    )
    notes = etree.SubElement(file_desc, f"{{{_TEI}}}notesStmt")
    etree.SubElement(notes, f"{{{_TEI}}}note", type="scope-boundary").text = (
        "The retained source members are grouped for this provisional candidate only. "
        "No common collection, edition, part boundary, or cross-witness sermon numbering is asserted."
    )
    for event in prolog_events:
        if event["kind"] == "processing-instruction":
            etree.SubElement(
                notes,
                f"{{{_TEI}}}note",
                type="source-processing-instruction",
                n=json.dumps(
                    {"target": event["target"], "data": event["data"]},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        elif event["kind"] == "comment":
            etree.SubElement(
                notes, f"{{{_TEI}}}note", type="source-prolog-comment"
            ).text = str(event["text"])
        else:
            raise ValueError("Unsupported CCEL prolog event")
    head_projection = etree.SubElement(
        notes, f"{{{_TEI}}}note", type="source-header-event-ledger"
    )
    head_projection.text = _canonical(_source_events(ccel_head)).decode("utf-8").rstrip("\n")
    source_desc = etree.SubElement(file_desc, f"{{{_TEI}}}sourceDesc")
    list_bibl = etree.SubElement(source_desc, f"{{{_TEI}}}listBibl")
    ccel_bibl = etree.SubElement(list_bibl, f"{{{_TEI}}}bibl", type="retained-source-member", n="CCEL")
    etree.SubElement(ccel_bibl, f"{{{_TEI}}}title").text = ccel_title
    etree.SubElement(ccel_bibl, f"{{{_TEI}}}idno", type="sha256").text = ccel_member["sha256"]
    etree.SubElement(ccel_bibl, f"{{{_TEI}}}note", type="retained-path").text = ccel_member["path"]
    pg_bibl = etree.SubElement(list_bibl, f"{{{_TEI}}}bibl", type="retained-source-member", n="Project Gutenberg")
    pg_title = next(
        (line.partition(":")[2].strip() for line in pg_lines if line.strip().startswith("Title:")),
        "",
    )
    pg_author = next(
        (line.partition(":")[2].strip() for line in pg_lines if line.strip().startswith("Author:")),
        "",
    )
    if not pg_title or not pg_author:
        raise ValueError("Project Gutenberg source title/author header observations are missing")
    etree.SubElement(pg_bibl, f"{{{_TEI}}}title").text = pg_title
    etree.SubElement(pg_bibl, f"{{{_TEI}}}author").text = pg_author
    etree.SubElement(pg_bibl, f"{{{_TEI}}}idno", type="project-gutenberg-ebook").text = "77041"
    etree.SubElement(pg_bibl, f"{{{_TEI}}}idno", type="sha256").text = pg_member["sha256"]
    etree.SubElement(pg_bibl, f"{{{_TEI}}}note", type="retained-path").text = pg_member["path"]
    etree.SubElement(pg_bibl, f"{{{_TEI}}}note", type="source-subtitle").text = next(
        (line.strip() for line in pg_lines if "Containing all his sermons and tracts" in line),
        "",
    )
    etree.SubElement(header, f"{{{_TEI}}}encodingDesc").append(
        etree.Element(f"{{{_TEI}}}p")
    )
    header.find(f"{{{_TEI}}}encodingDesc/{{{_TEI}}}p").text = (
        "CCEL source elements retain their source tag and ordered attributes in TEI "
        "annotations; text, tails, order, comments, and source processing-instruction data "
        "are checked independently. Project Gutenberg lines retain source-native line text; "
        "physical byte and line accounting is in source-accountability.json."
    )
    revision = etree.SubElement(header, f"{{{_TEI}}}revisionDesc", status="candidate")
    etree.SubElement(revision, f"{{{_TEI}}}change", when="2026-09-18").text = (
        "Generated as a nonaccepted, source-bound technical candidate; identity and rights questions remain open."
    )

    text_node = etree.SubElement(root, f"{{{_TEI}}}text")
    body = etree.SubElement(text_node, f"{{{_TEI}}}body")
    ccel_projection = etree.Element(f"{{{_TEI}}}div")
    ccel_projection.set("type", "source-ThML.body")
    ccel_projection.set("subtype", "retained-member")
    ccel_projection.set(
        "n",
        json.dumps(
            {
                "source_tag": str(ccel_body.tag),
                "source_attributes": [[key, value] for key, value in ccel_body.attrib.items()],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    ccel_projection.set(_XML_ID, "member-ccel-whitefield")
    ccel_projection.text = ccel_body.text
    for source_child in ccel_body:
        mapped = _map_source_element(
            source_child,
            carrier_id=source_child.get("id") if source_child.tag == "div1" else None,
        )
        mapped.tail = source_child.tail
        ccel_projection.append(mapped)
    body.append(ccel_projection)

    pg_projection = etree.SubElement(
        body,
        f"{{{_TEI}}}div",
        type="source-project-gutenberg-member",
        subtype="selected-carriers-only",
    )
    pg_projection.set(_XML_ID, "member-project-gutenberg-77041")
    by_label = {row["source_label"]: row for row in pg_sermons}
    for label in pg_member["selected_source_sermon_labels"]:
        source_row = by_label[label]
        section = etree.SubElement(
            pg_projection,
            f"{{{_TEI}}}div",
            type="source-gutenberg-sermon",
            n=str(label),
        )
        section.set(_XML_ID, str(source_row["candidate_xml_id"]))
        first_line = int(source_row["start_line"])
        last_line = int(source_row["end_line_inclusive"])
        for line_number in range(first_line, last_line + 1):
            line = etree.SubElement(
                section,
                f"{{{_TEI}}}ab",
                type="source-physical-line",
                n=str(line_number),
            )
            line_text = pg_lines[line_number - 1]
            line.text = line_text if line_text else None

    xml_bytes = etree.tostring(
        etree.ElementTree(root),
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    )

    source_set_sha256 = _source_set_sha256(source_manifest)
    pg_inventory_sha256 = _sha(_canonical(line_inventory))
    source_accountability: dict[str, object] = {
        "contract": "ocd-george-whitefield-source-accountability-v1",
        "work_id": record["work_id"],
        "ticket_id": record["ticket_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "source_set_sha256": source_set_sha256,
        "ccel": {
            "path": ccel_member["path"],
            "bytes": len(ccel_bytes),
            "sha256": _sha(ccel_bytes),
            "source_root": str(ccel_root.tag),
            "source_title_observation": ccel_title,
            "xml_version": ccel_tree.docinfo.xml_version,
            "encoding": ccel_tree.docinfo.encoding,
            "doctype": ccel_tree.docinfo.doctype,
            "ordered_carriers": carrier_rows,
            "processing_instructions": processing_instructions,
            "prolog_events": prolog_events,
            "comments": comments,
            "element_counts": dict(sorted(element_counts.items())),
            "head_event_sha256": _sha(_canonical(_source_events(ccel_head))),
            "body_event_sha256": _sha(_canonical(_source_events(ccel_body))),
        },
        "project_gutenberg": {
            "path": pg_member["path"],
            "bytes": len(pg_bytes),
            "sha256": _sha(pg_bytes),
            "physical_line_count": len(line_inventory),
            "line_inventory_sha256": pg_inventory_sha256,
            "line_inventory": line_inventory,
            "sermon_carriers": pg_sermons,
            "selected_source_labels": pg_member["selected_source_sermon_labels"],
            "start_marker_line": next(
                index + 1
                for index, line in enumerate(pg_lines)
                if line.startswith("*** START OF THE PROJECT GUTENBERG EBOOK ")
            ),
            "end_marker_line": next(
                index + 1
                for index, line in enumerate(pg_lines)
                if line.startswith("*** END OF THE PROJECT GUTENBERG EBOOK ")
            ),
        },
        "candidate_scope": {
            "status": "provisional; collection and cross-witness relationship unresolved",
            "included": [
                "All 62 ordered CCEL direct div1 carriers, including title-page, contents, 59 sermon, and indexes carriers.",
                "Project Gutenberg source-native sermon carriers LVIII and LIX, preserved separately with their source labels.",
            ],
            "excluded": [
                {
                    "member": "retained-project-gutenberg-text",
                    "source_carrier_count": 26,
                    "reason": "The current source-local config names two supplementary titles only. These remaining carriers are explicitly not selected, but are not declared outside the larger work or corpus.",
                },
                {
                    "member": "retained-project-gutenberg-text",
                    "source_carrier": "provider/header/contents/license/closing matter and all physical lines outside the two selected sermon intervals",
                    "reason": "The complete physical member and all such lines are inventoried; this matter is not projected as sermon body text.",
                },
            ],
            "unknowns": [
                "Whether the two source members belong to one collection, edition, or part sequence.",
                "Whether Project Gutenberg source-native labels LVIII and LIX correspond to any shared catalog ordinals.",
                "Whether the 26 not-selected Project Gutenberg sermon carriers fall inside the catalog work boundary.",
                "Rights review, human textual acceptance, release selection, and publication authorization.",
            ],
        },
    }
    unresolved = [
        {
            "id": "george-whitefield-collection-edition-part-boundary",
            "status": "unresolved",
            "kind": "identity",
            "detail": "The CCEL member identifies a 59-sermon selected collection while Project Gutenberg identifies Volume 6 (of 6) and source-native Sermons LVIII and LIX. The retained evidence does not establish a shared collection, edition, or part boundary.",
        },
        {
            "id": "george-whitefield-cross-witness-numbering",
            "status": "unresolved",
            "kind": "scope",
            "detail": "CCEL div1 ids lviii and lix identify different title carriers from Project Gutenberg's source-native LVIII and LIX. Legacy shared records 60 and 61 are not adopted; no global sermon ordinal is assigned.",
        },
        {
            "id": "george-whitefield-project-gutenberg-other-sermons",
            "status": "unresolved",
            "kind": "scope",
            "detail": "The other 26 Project Gutenberg sermon carriers are fully inventoried but not selected because the current work-specific config names only two supplementary titles. Their relation to the catalog work remains undecided.",
        },
        {
            "id": "george-whitefield-rights-review",
            "status": "unresolved",
            "kind": "rights",
            "detail": "No rights inquiry or clearance was performed. This nonaccepted candidate does not authorize release or publication.",
        },
        {
            "id": "george-whitefield-human-acceptance-and-visual-review",
            "status": "unresolved",
            "kind": "acceptance",
            "detail": "No human textual acceptance or CVW visual review is represented by the mechanical candidate route.",
        },
    ]
    authorities = {
        str(item["name"]): {
            key: item[key]
            for key in ("path", "bytes", "sha256", "role")
        }
        for item in record["authorities"]
    }
    provenance = {
        "contract": "ocd-george-whitefield-candidate-provenance-v1",
        "status": "nonaccepted",
        "work_id": record["work_id"],
        "ticket_id": record["ticket_id"],
        "source_id": record["source_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "source_set_sha256": source_set_sha256,
        "authorities": authorities,
        "identity_status": {
            "collection_boundary": "unresolved",
            "edition_relationship": "unresolved",
            "part_relationship": "unresolved",
            "cross_witness_numbering": "unresolved; source-native labels only",
        },
        "rights_status": "not-reviewed",
        "acceptance_status": "not-accepted",
        "release_status": "not-selected",
        "publication_status": "not-authorized",
        "canonical_data_or_ir_written": False,
    }
    return {
        "README.source.md": _authority(source_manifest, "source-attribution-readme"),
        "content.tei.xml": xml_bytes,
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(source_accountability),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
