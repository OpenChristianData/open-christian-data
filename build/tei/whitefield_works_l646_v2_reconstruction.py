"""Rebind the retained L646 seed to complete HTML and media evidence."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Mapping
from zipfile import ZipFile

from html5lib import parse
from lxml import etree

from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
)

CONVERTER_ID = "ocd-whitefield-l646-inline-media-repackager"
CONVERTER_VERSION = "2"
SEED_SHA256 = "a51808a840f0975e7ddba24d1f0bfe4660e0395b0cd3e251fda14ab896dbc9f6"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
VOLUMES = (("68976", "I"), ("71140", "II"), ("73012", "III"))
FOOTER_ANCHORS = {
    "pg-end-separator": "*** END OF THE PROJECT GUTENBERG EBOOK",
    "project-gutenberg-license": "START: FULL LICENSE",
    "pg-footer-heading": "THE FULL PROJECT GUTENBERG™ LICENSE",
}


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _text_hash(value: str) -> str:
    return _sha(" ".join(value.split()).encode("utf-8"))


def _local(element: etree._Element) -> str:
    return etree.QName(element).localname.casefold()


def _qname(name: str) -> str:
    return f"{{{TEI}}}{name}"


def _source_html(path: Path) -> tuple[etree._Element, etree._Element, etree._Element]:
    document = parse(
        path.read_bytes(), treebuilder="lxml", namespaceHTMLElements=False
    ).getroot()
    head = next(
        (element for element in document.iter() if _local(element) == "head"), None
    )
    body = next(
        (element for element in document.iter() if _local(element) == "body"), None
    )
    if head is None or body is None:
        raise ValueError(f"source HTML has no head/body: {path}")
    return document, head, body


def _archive_evidence(
    manifest: SourceManifest, ebook_id: str
) -> tuple[dict[str, bytes], list[dict[str, object]]]:
    archive_path = manifest.authority_path(f"pg{ebook_id}-zip")
    inventory_path = manifest.authority_path(f"pg{ebook_id}-inventory")
    receipt_path = manifest.authority_path(f"pg{ebook_id}-receipt")
    archive_authority = next(
        item
        for item in manifest.record["authorities"]
        if item["name"] == f"pg{ebook_id}-zip"
    )
    expected: dict[str, tuple[int, str, str]] = {}
    for line_number, line in enumerate(
        inventory_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        columns = line.split("\t")
        if len(columns) != 4:
            raise ValueError(f"invalid member inventory row {ebook_id}:{line_number}")
        member, size, crc32, digest = columns
        relative = PurePosixPath(member)
        if relative.is_absolute() or ".." in relative.parts or member in expected:
            raise ValueError(f"unsafe or duplicate archive member {ebook_id}:{member}")
        if len(digest) != 64 or len(crc32) != 8:
            raise ValueError(f"invalid inventory digest {ebook_id}:{member}")
        expected[member] = (int(size), crc32.casefold(), digest)

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    archive_authority = next(
        item
        for item in manifest.record["authorities"]
        if item["name"] == f"pg{ebook_id}-zip"
    )
    html_authority = next(
        item
        for item in manifest.record["authorities"]
        if item["name"] == f"pg{ebook_id}-html"
    )
    if receipt["package"]["sha256"] != archive_authority["sha256"]:
        raise ValueError(f"acquisition receipt package binding drifted: PG{ebook_id}")
    if (
        receipt["html"]["sha256"] != html_authority["sha256"]
        or receipt["html"]["bytes"] != html_authority["bytes"]
    ):
        raise ValueError(f"acquisition receipt HTML binding drifted: PG{ebook_id}")

    members: dict[str, bytes] = {}
    records: list[dict[str, object]] = []
    with ZipFile(archive_path) as archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        if len(infos) != receipt["verification"]["member_count"]:
            raise ValueError(f"acquisition receipt member count drifted: PG{ebook_id}")
        if len({item.filename for item in infos}) != len(infos):
            raise ValueError(f"duplicate ZIP member name: PG{ebook_id}")
        if {item.filename for item in infos} != set(expected):
            raise ValueError(
                f"ZIP and retained inventory member sets differ: PG{ebook_id}"
            )
        for info in infos:
            data = archive.read(info)
            digest = _sha(data)
            expected_size, expected_crc, expected_digest = expected[info.filename]
            observed_crc = f"{info.CRC:08x}"
            if (
                len(data) != expected_size
                or info.file_size != expected_size
                or observed_crc != expected_crc
                or digest != expected_digest
            ):
                raise ValueError(
                    f"ZIP member differs from retained inventory: "
                    f"PG{ebook_id}/{info.filename}"
                )
            members[info.filename] = data
            records.append(
                {
                    "archive_path": archive_authority["path"],
                    "archive_sha256": archive_authority["sha256"],
                    "member": info.filename,
                    "bytes": len(data),
                    "crc32": observed_crc,
                    "sha256": digest,
                }
            )
    return members, records


def _insert_anchor_before(container: etree._Element, phrase: str, xml_id: str) -> None:
    """Insert a zero-width TEI anchor at the exact start of a retained phrase."""
    matches = 0
    for node in container.iter():
        if node.text and phrase in node.text:
            before, remainder = node.text.split(phrase, 1)
            anchor = etree.Element(_qname("anchor"))
            anchor.set(f"{{{XML}}}id", xml_id)
            anchor.tail = phrase + remainder
            node.text = before
            node.insert(0, anchor)
            matches += 1
            break
        if node.tail and phrase in node.tail:
            before, remainder = node.tail.split(phrase, 1)
            anchor = etree.Element(_qname("anchor"))
            anchor.set(f"{{{XML}}}id", xml_id)
            anchor.tail = phrase + remainder
            node.tail = before
            parent = node.getparent()
            if parent is None:
                raise ValueError(f"source phrase is detached: {phrase}")
            parent.insert(parent.index(node) + 1, anchor)
            matches += 1
            break
    if matches != 1:
        raise ValueError(f"cannot place source anchor {xml_id}: {phrase}")


def _converter(manifest: SourceManifest) -> Mapping[str, bytes]:
    seed_path = manifest.authority_path("preserved-candidate-tei")
    seed = seed_path.read_bytes()
    if _sha(seed) != SEED_SHA256:
        raise ValueError("preserved L646 TEI seed drifted")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    tree = etree.parse(str(seed_path), parser)
    tei = tree.getroot()
    if tei.tag != _qname("TEI"):
        raise ValueError("retained seed has a non-TEI root")
    ns = {"t": TEI, "xml": XML}
    volume_divs = tei.xpath(
        "./t:text/t:body/t:div[@type='source-volume']", namespaces=ns
    )
    if [element.get("n") for element in volume_divs] != ["I", "II", "III"]:
        raise ValueError("retained seed volume scope is not I-III in source order")

    source_authorities = {
        item["name"]: item
        for item in manifest.record["authorities"]
        if item["role"] == "primary-source"
    }
    all_archive_members: list[dict[str, object]] = []
    all_source_records = [
        {
            "name": item["name"],
            "path": item["path"],
            "role": item["role"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in manifest.record["authorities"]
    ]
    text_records: list[dict[str, object]] = []
    media_records: list[dict[str, object]] = []
    link_records: list[dict[str, object]] = []
    id_records: list[dict[str, object]] = []

    for index, ((ebook_id, roman), volume) in enumerate(
        zip(VOLUMES, volume_divs), start=1
    ):
        html_authority = source_authorities[f"pg{ebook_id}-html"]
        html_path = manifest.authority_path(f"pg{ebook_id}-html")
        html_doc, html_head, html_body = _source_html(html_path)
        image_members, member_records = _archive_evidence(manifest, ebook_id)
        all_archive_members.extend(member_records)
        source_text = " ".join("".join(html_body.itertext()).split())
        tei_text = " ".join("".join(volume.itertext()).split())
        if source_text != tei_text:
            raise ValueError(f"retained seed body text is not exact for PG{ebook_id}")
        source_headings = [
            " ".join("".join(element.itertext()).split())
            for element in html_body.iter()
            if _local(element) == "h3"
        ]
        tei_headings = [
            " ".join("".join(element.itertext()).split())
            for element in volume.xpath(".//t:head[@rend='source-h3']", namespaces=ns)
        ]
        if source_headings != tei_headings:
            raise ValueError(f"source h3 heading sequence differs for PG{ebook_id}")
        text_records.append(
            {
                "ebook_id": ebook_id,
                "volume": roman,
                "source_html": html_authority["path"],
                "source_html_sha256": html_authority["sha256"],
                "normalized_visible_body_characters": len(source_text),
                "normalized_visible_body_sha256": _text_hash(source_text),
                "source_h3_count": len(source_headings),
                "normalized_source_h3_sequence_sha256": _sha(
                    _canonical(source_headings)
                ),
            }
        )

        image_elements = [
            element for element in html_body.iter() if _local(element) == "img"
        ]
        graphics = volume.xpath(".//t:graphic", namespaces=ns)
        if len(image_elements) != len(graphics):
            raise ValueError(
                f"source image and seed graphic counts differ for PG{ebook_id}"
            )
        candidate_media_ids: dict[str, str] = {}
        for occurrence, (source_image, graphic) in enumerate(
            zip(image_elements, graphics), start=1
        ):
            source_uri = source_image.get("src")
            if not source_uri or source_uri not in image_members:
                raise ValueError(
                    f"retained ZIP lacks referenced image PG{ebook_id}/{source_uri}"
                )
            if graphic.get("url") != source_uri:
                raise ValueError(
                    f"seed image order/path differs for PG{ebook_id}/{occurrence}"
                )
            image_bytes = image_members[source_uri]
            extension = PurePosixPath(source_uri).suffix.casefold()
            mime_type = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
            }.get(extension)
            if mime_type is None:
                raise ValueError(f"unsupported retained image type: {source_uri}")
            candidate_id = graphic.get(f"{{{XML}}}id")
            if not candidate_id:
                raise ValueError(
                    f"seed image has no stable TEI id for PG{ebook_id}/{occurrence}"
                )
            source_alt = source_image.get("alt")
            if (graphic.get("n") or "") != (source_alt or ""):
                raise ValueError(
                    f"seed image alt mapping differs for PG{ebook_id}/{occurrence}"
                )
            binary = etree.Element(_qname("binaryObject"))
            for name, value in graphic.attrib.items():
                if name != "url":
                    binary.set(name, value)
            binary.set("encoding", "base64")
            binary.set("mimeType", mime_type)
            binary.text = base64.b64encode(image_bytes).decode("ascii")
            binary.tail = graphic.tail
            parent = graphic.getparent()
            if parent is None:
                raise ValueError("detached TEI graphic")
            parent.replace(graphic, binary)
            candidate_media_ids[source_uri] = candidate_id
            media_records.append(
                {
                    "ebook_id": ebook_id,
                    "volume": roman,
                    "occurrence": occurrence,
                    "source_html": html_authority["path"],
                    "source_html_sha256": html_authority["sha256"],
                    "source_element": "img",
                    "source_src": source_uri,
                    "source_alt": source_alt,
                    "source_archive": f"raw/gutenberg/{ebook_id}/pg{ebook_id}-h.zip",
                    "source_zip_member": source_uri,
                    "member_bytes": len(image_bytes),
                    "member_sha256": _sha(image_bytes),
                    "candidate_element": "binaryObject",
                    "candidate_xml_id": candidate_id,
                    "candidate_encoding": "base64",
                    "candidate_mime_type": mime_type,
                }
            )

            anchor = source_image.getparent()
            while anchor is not None and _local(anchor) != "a":
                anchor = anchor.getparent()
            if anchor is not None and anchor.get("href"):
                source_href = anchor.get("href")
                if source_href != source_uri:
                    raise ValueError(
                        "source image link does not target its image: "
                        f"PG{ebook_id}/{source_uri}"
                    )
                ref = parent
                while ref is not None and _local(ref) != "ref":
                    ref = ref.getparent()
                if ref is None or ref.get("target") != source_href:
                    raise ValueError(
                        "seed image link differs from retained HTML: "
                        f"PG{ebook_id}/{source_href}"
                    )
                ref.set("target", f"#{candidate_id}")
                link_records.append(
                    {
                        "ebook_id": ebook_id,
                        "volume": roman,
                        "source_anchor_id": anchor.get("id"),
                        "source_href": source_href,
                        "candidate_ref_target": f"#{candidate_id}",
                        "candidate_target_xml_id": candidate_id,
                    }
                )

        head_links = [
            element
            for element in html_head.iter()
            if _local(element) == "link" and element.get("rel", "").casefold() == "icon"
        ]
        if len(head_links) != 1:
            raise ValueError(f"source head icon link count differs for PG{ebook_id}")
        head_link = head_links[0]
        head_id = head_link.get("id")
        head_href = head_link.get("href")
        target_id = candidate_media_ids.get(head_href or "")
        if not head_id or not target_id:
            raise ValueError(
                "source head icon does not bind to an embedded body image "
                f"for PG{ebook_id}"
            )
        file_desc = tei.find(f"{_qname('teiHeader')}/{_qname('fileDesc')}")
        if file_desc is None:
            raise ValueError("TEI fileDesc is missing")
        encoding_desc = tei.find(f"{_qname('teiHeader')}/{_qname('encodingDesc')}")
        if encoding_desc is None:
            encoding_desc = etree.Element(_qname("encodingDesc"))
            tei_header = tei.find(_qname("teiHeader"))
            if tei_header is None:
                raise ValueError("TEI header is missing")
            tei_header.insert(tei_header.index(file_desc) + 1, encoding_desc)
        project_desc = encoding_desc.find(_qname("projectDesc"))
        if project_desc is None:
            project_desc = etree.SubElement(encoding_desc, _qname("projectDesc"))
        pointer_paragraph = project_desc.find(_qname("p"))
        if pointer_paragraph is None:
            pointer_paragraph = etree.SubElement(project_desc, _qname("p"))
        pointer = etree.SubElement(pointer_paragraph, _qname("ptr"))
        pointer.set("type", "source-html-head-link")
        pointer.set(f"{{{XML}}}id", f"v{index}-{head_id}")
        pointer.set("target", f"#{target_id}")

        source_id_elements = [
            element for element in html_doc.iter() if element.get("id")
        ]
        source_ids = [element.get("id") for element in source_id_elements]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError(f"source HTML contains duplicate ids for PG{ebook_id}")
        for element in source_id_elements:
            source_id = element.get("id")
            candidate_id = f"v{index}-{source_id}"
            if tei.xpath(".//*[@xml:id=$x]", namespaces=ns, x=candidate_id):
                continue
            if source_id in FOOTER_ANCHORS:
                footer = volume.xpath(
                    ".//t:div[@xml:id=$x]/t:ab[@type='source-license-wrapper']",
                    namespaces=ns,
                    x=f"v{index}-pg-footer",
                )
                if len(footer) != 1:
                    raise ValueError(
                        f"source provider-license wrapper missing for PG{ebook_id}"
                    )
                _insert_anchor_before(
                    footer[0], FOOTER_ANCHORS[source_id], candidate_id
                )
            elif element is not head_link:
                raise ValueError(
                    f"source HTML id has no TEI carrier for PG{ebook_id}: {source_id}"
                )

        for element in source_id_elements:
            source_id = element.get("id")
            candidate_id = f"v{index}-{source_id}"
            matches = tei.xpath(".//*[@xml:id=$x]", namespaces=ns, x=candidate_id)
            if len(matches) != 1:
                raise ValueError(
                    "source id mapping is missing or duplicated: "
                    f"PG{ebook_id}/{source_id}"
                )
            candidate_element = matches[0]
            in_head = element in set(html_head.iter())
            if in_head:
                if (
                    _local(candidate_element) != "ptr"
                    or candidate_element.get("type") != "source-html-head-link"
                    or candidate_element.get("target") != f"#{target_id}"
                ):
                    raise ValueError(
                        f"source head id pointer is invalid: PG{ebook_id}/{source_id}"
                    )
            elif not any(candidate_element is member for member in volume.iter()):
                raise ValueError(
                    f"source body id escaped its volume: PG{ebook_id}/{source_id}"
                )
            id_records.append(
                {
                    "ebook_id": ebook_id,
                    "volume": roman,
                    "source_id": source_id,
                    "source_tag": _local(element),
                    "source_zone": "head" if in_head else "body",
                    "source_href": element.get("href"),
                    "candidate_xml_id": candidate_id,
                    "candidate_element": _local(candidate_element),
                    "candidate_zone": "teiHeader" if in_head else "source-volume",
                    "candidate_target": candidate_element.get("target"),
                }
            )

    output = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    unresolved = [
        {
            "id": "editor-attribution",
            "status": "open",
            "question": (
                "The Worklist names John Gillies as editor, but inspected "
                "title-page evidence does not establish that attribution."
            ),
        },
        {
            "id": "human-visual-editorial-review",
            "status": "open",
            "question": "Human visual and editorial review remains outstanding.",
        },
        {
            "id": "rights-clearance",
            "status": "open",
            "question": (
                "No rights clearance or jurisdictional determination is made "
                "by this technical candidate."
            ),
        },
        {
            "id": "viewer-rendering",
            "status": "open",
            "question": (
                "The exact retained image bytes are embedded and linked in TEI; "
                "rendering in the downstream reader remains unverified."
            ),
        },
    ]
    provenance = {
        "candidate_status": "nonaccepted",
        "work_id": "george-whitefield-works",
        "title": "The Works of the Reverend George Whitefield, M.A., volumes I-III",
        "source_id": manifest.record["source_id"],
        "source_manifest_sha256": manifest.sha256,
        "human_acceptance": "not recorded",
        "rights": "not cleared",
        "publication": "not authorized",
        "conversion_basis": (
            "The preserved TEI seed is rebound to the exact retained HTML and "
            "ZIP members. Each source image occurrence is embedded as TEI "
            "binaryObject; source-local image links and flattened HTML ids "
            "receive explicit TEI targets or anchors."
        ),
        "historical_producer": (
            "not available; this candidate does not claim historical "
            "converter recreation"
        ),
        "scope": "one collected title, Project Gutenberg volumes I-III of six, one TEI",
        "known_limitations": [
            (
                "The retained seed is not a recreation of the absent historical "
                "producer, and the oracle does not claim complete HTML-node "
                "equivalence."
            ),
            (
                "Human visual/editorial review, rights clearance, acceptance, "
                "publication authorization, and downstream media rendering are "
                "separate and remain open."
            ),
        ],
    }
    accountability = {
        "contract": "ocd-whitefield-l646-source-accountability-v2",
        "work_id": "george-whitefield-works",
        "source_id": manifest.record["source_id"],
        "source_manifest_sha256": manifest.sha256,
        "scope": (
            "One collected title, Project Gutenberg volumes I-III of six; "
            "volumes IV-VI excluded."
        ),
        "candidate_unit_count": 1,
        "candidate_tei_count": 1,
        "candidate_tei_sha256": _sha(output),
        "seed_tei_sha256": SEED_SHA256,
        "source_authorities": all_source_records,
        "archive_members": all_archive_members,
        "visible_body_text": text_records,
        "source_id_mappings": id_records,
        "media_occurrences": media_records,
        "source_image_links": link_records,
        "preservation": {
            "html_visible_body_text": "exact after whitespace normalization per volume",
            "source_h3_heading_sequence": "exact per volume",
            "source_ids": (
                "every retained HTML id has one prefixed TEI xml:id carrier; "
                "head icon IDs point to their embedded volume-cover object"
            ),
            "source_image_occurrences": (
                "every retained HTML img occurrence maps to one embedded TEI "
                "binaryObject in source order, including each repeated brace image"
            ),
            "candidate_image_targets": (
                "all source-local image links target their corresponding embedded "
                "binaryObject; no relative images/ URI remains in TEI"
            ),
            "work_boundary": (
                "one collected title and one TEI with ordered source-volume "
                "divisions I, II, III"
            ),
        },
    }
    readme = manifest.authority_path("source-readme-v2").read_bytes()
    return {
        "content.tei.xml": output,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_converter.converter_id = CONVERTER_ID
_converter.converter_version = CONVERTER_VERSION


def build_candidate(manifest: SourceManifest, output: str | Path) -> CandidatePackage:
    return reconstruct(manifest, output, _converter)
