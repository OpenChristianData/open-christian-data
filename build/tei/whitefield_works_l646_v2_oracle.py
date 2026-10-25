"""Independent HTML5, archive-member, image, id, text, and P5 oracle for L646."""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import sys
from pathlib import Path, PurePosixPath
from typing import Mapping
from zipfile import ZipFile

from html5lib import parse
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest

ORACLE_ID = "ocd-whitefield-l646-independent-html5-media-oracle"
ORACLE_VERSION = "2"
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


def _normalized(value: str) -> str:
    return " ".join(value.split())


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


def _archive_members(
    manifest: SourceManifest, ebook_id: str
) -> tuple[dict[str, bytes], list[dict[str, object]]]:
    archive_path = manifest.authority_path(f"pg{ebook_id}-zip")
    inventory_path = manifest.authority_path(f"pg{ebook_id}-inventory")
    receipt_path = manifest.authority_path(f"pg{ebook_id}-receipt")
    expected: dict[str, tuple[int, str, str]] = {}
    for line_number, line in enumerate(
        inventory_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        fields = line.split("\t")
        if len(fields) != 4:
            raise ValueError(f"invalid source inventory row PG{ebook_id}:{line_number}")
        name, size, crc32, digest = fields
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or name in expected:
            raise ValueError(
                f"unsafe or duplicate source archive member PG{ebook_id}/{name}"
            )
        expected[name] = (int(size), crc32.casefold(), digest)

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    authorities = {item["name"]: item for item in manifest.record["authorities"]}
    if receipt["package"]["sha256"] != authorities[f"pg{ebook_id}-zip"]["sha256"]:
        raise ValueError(f"acquisition receipt ZIP digest differs for PG{ebook_id}")
    html_authority = authorities[f"pg{ebook_id}-html"]
    if (
        receipt["html"]["sha256"] != html_authority["sha256"]
        or receipt["html"]["bytes"] != html_authority["bytes"]
    ):
        raise ValueError(f"acquisition receipt HTML binding differs for PG{ebook_id}")

    members: dict[str, bytes] = {}
    records: list[dict[str, object]] = []
    with ZipFile(archive_path) as archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        if len(infos) != receipt["verification"]["member_count"]:
            raise ValueError(
                f"acquisition receipt member count differs for PG{ebook_id}"
            )
        if len({item.filename for item in infos}) != len(infos):
            raise ValueError(f"duplicate ZIP entry name for PG{ebook_id}")
        if {item.filename for item in infos} != set(expected):
            raise ValueError(f"ZIP and current inventory sets differ for PG{ebook_id}")
        archive_authority = authorities[f"pg{ebook_id}-zip"]
        for info in infos:
            data = archive.read(info)
            size, crc32, digest = expected[info.filename]
            observed_crc = f"{info.CRC:08x}"
            if (
                len(data) != size
                or info.file_size != size
                or observed_crc != crc32
                or _sha(data) != digest
            ):
                raise ValueError(
                    f"retained ZIP member hash mismatch PG{ebook_id}/{info.filename}"
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


def _visible_tei_text(root: etree._Element) -> str:
    parts: list[str] = []

    def visit(element: etree._Element) -> None:
        if _local(element) == "binaryobject":
            return
        if element.text:
            parts.append(element.text)
        for child in element:
            visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(root)
    return "".join(parts)


def _oracle(
    manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    tei_bytes = candidate.member_bytes("content.tei.xml")
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    tei = etree.fromstring(tei_bytes)
    findings: list[str] = []
    if tei.tag != _qname("TEI"):
        raise ValueError("candidate root is not one TEI document")
    ns = {"t": TEI, "xml": XML}
    volume_divs = tei.xpath(
        "./t:text/t:body/t:div[@type='source-volume']", namespaces=ns
    )
    if [element.get("n") for element in volume_divs] != ["I", "II", "III"]:
        raise ValueError("one-TEI ordered volume boundary failed")

    accountability = json.loads(accountability_bytes.decode("utf-8"))
    if (
        accountability.get("contract") != "ocd-whitefield-l646-source-accountability-v2"
        or accountability.get("source_manifest_sha256") != manifest.sha256
        or accountability.get("candidate_tei_sha256") != _sha(tei_bytes)
        or accountability.get("candidate_unit_count") != 1
        or accountability.get("candidate_tei_count") != 1
    ):
        raise ValueError("candidate source-accountability binding differs")

    authorities = {item["name"]: item for item in manifest.record["authorities"]}
    expected_authorities = [
        {
            "name": item["name"],
            "path": item["path"],
            "role": item["role"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in manifest.record["authorities"]
    ]
    if accountability.get("source_authorities") != expected_authorities:
        raise ValueError("source authority accounting differs from manifest")

    xml_ids = [
        element.get(f"{{{XML}}}id")
        for element in tei.iter()
        if element.get(f"{{{XML}}}id")
    ]
    if len(xml_ids) != len(set(xml_ids)):
        raise ValueError("candidate TEI has duplicate xml:id values")
    xml_id_map = {
        element.get(f"{{{XML}}}id"): element
        for element in tei.iter()
        if element.get(f"{{{XML}}}id")
    }

    expected_archives: list[dict[str, object]] = []
    expected_text: list[dict[str, object]] = []
    expected_ids: list[dict[str, object]] = []
    expected_media: list[dict[str, object]] = []
    expected_links: list[dict[str, object]] = []

    for index, ((ebook_id, roman), volume) in enumerate(
        zip(VOLUMES, volume_divs), start=1
    ):
        html_authority = authorities[f"pg{ebook_id}-html"]
        html_doc, html_head, html_body = _source_html(
            manifest.authority_path(f"pg{ebook_id}-html")
        )
        source_text = _normalized("".join(html_body.itertext()))
        candidate_text = _normalized(_visible_tei_text(volume))
        if candidate_text != source_text:
            raise ValueError(f"source body text mismatch for PG{ebook_id}")

        source_headings = [
            _normalized("".join(element.itertext()))
            for element in html_body.iter()
            if _local(element) == "h3"
        ]
        candidate_headings = [
            _normalized("".join(element.itertext()))
            for element in volume.xpath(".//t:head[@rend='source-h3']", namespaces=ns)
        ]
        if candidate_headings != source_headings:
            raise ValueError(f"source h3 heading sequence mismatch for PG{ebook_id}")
        expected_text.append(
            {
                "ebook_id": ebook_id,
                "volume": roman,
                "source_html": html_authority["path"],
                "source_html_sha256": html_authority["sha256"],
                "normalized_visible_body_characters": len(source_text),
                "normalized_visible_body_sha256": _sha(source_text.encode("utf-8")),
                "source_h3_count": len(source_headings),
                "normalized_source_h3_sequence_sha256": _sha(
                    _canonical(source_headings)
                ),
            }
        )

        images, archive_records = _archive_members(manifest, ebook_id)
        expected_archives.extend(archive_records)
        source_images = [
            element for element in html_body.iter() if _local(element) == "img"
        ]
        binaries = volume.xpath(".//t:binaryObject", namespaces=ns)
        if volume.xpath(".//t:graphic", namespaces=ns):
            raise ValueError(
                f"candidate retains unresolved graphic URI in PG{ebook_id}"
            )
        if len(source_images) != len(binaries):
            raise ValueError(f"source image occurrence count mismatch for PG{ebook_id}")
        candidate_media_ids: dict[str, str] = {}
        for occurrence, (source_image, binary) in enumerate(
            zip(source_images, binaries), start=1
        ):
            src = source_image.get("src")
            candidate_id = binary.get(f"{{{XML}}}id")
            source_image_id = source_image.get("id")
            expected_candidate_id = f"v{index}-{source_image_id}"
            if not src or src not in images or candidate_id != expected_candidate_id:
                raise ValueError(
                    "source image identity/order mismatch for "
                    f"PG{ebook_id}/{occurrence}"
                )
            media = images[src]
            extension = PurePosixPath(src).suffix.casefold()
            expected_mime = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
            }.get(extension)
            if (
                binary.get("encoding") != "base64"
                or binary.get("mimeType") != expected_mime
                or (binary.get("n") or "") != (source_image.get("alt") or "")
            ):
                raise ValueError(
                    f"source image metadata mismatch for PG{ebook_id}/{occurrence}"
                )
            try:
                observed_media = base64.b64decode(
                    "".join(binary.itertext()), validate=True
                )
            except (ValueError, TypeError) as error:
                raise ValueError(
                    f"invalid embedded image encoding for PG{ebook_id}/{occurrence}"
                ) from error
            if observed_media != media:
                raise ValueError(
                    f"source image bytes/hash mismatch for PG{ebook_id}/{occurrence}"
                )
            candidate_media_ids[src] = candidate_id
            expected_media.append(
                {
                    "ebook_id": ebook_id,
                    "volume": roman,
                    "occurrence": occurrence,
                    "source_html": html_authority["path"],
                    "source_html_sha256": html_authority["sha256"],
                    "source_element": "img",
                    "source_src": src,
                    "source_alt": source_image.get("alt"),
                    "source_archive": authorities[f"pg{ebook_id}-zip"]["path"],
                    "source_zip_member": src,
                    "member_bytes": len(media),
                    "member_sha256": _sha(media),
                    "candidate_element": "binaryObject",
                    "candidate_xml_id": candidate_id,
                    "candidate_encoding": "base64",
                    "candidate_mime_type": expected_mime,
                }
            )

            source_anchor = source_image.getparent()
            while source_anchor is not None and _local(source_anchor) != "a":
                source_anchor = source_anchor.getparent()
            if source_anchor is not None and source_anchor.get("href"):
                source_href = source_anchor.get("href")
                if source_href != src:
                    raise ValueError(
                        f"source image link target mismatch for PG{ebook_id}/{src}"
                    )
                candidate_ref = binary.getparent()
                while candidate_ref is not None and _local(candidate_ref) != "ref":
                    candidate_ref = candidate_ref.getparent()
                target = f"#{candidate_id}"
                if candidate_ref is None or candidate_ref.get("target") != target:
                    raise ValueError(
                        f"unresolved source image link for PG{ebook_id}/{src}"
                    )
                expected_links.append(
                    {
                        "ebook_id": ebook_id,
                        "volume": roman,
                        "source_anchor_id": source_anchor.get("id"),
                        "source_href": source_href,
                        "candidate_ref_target": target,
                        "candidate_target_xml_id": candidate_id,
                    }
                )

        if any(
            "images/" in element.get(attribute, "")
            for element in volume.iter()
            for attribute in ("url", "target", "href")
        ):
            raise ValueError(f"unresolved relative image URI remains in PG{ebook_id}")

        head_icons = [
            element
            for element in html_head.iter()
            if _local(element) == "link" and element.get("rel", "").casefold() == "icon"
        ]
        if len(head_icons) != 1:
            raise ValueError(f"source head icon count mismatch for PG{ebook_id}")
        head_icon = head_icons[0]
        head_id = head_icon.get("id")
        image_id = candidate_media_ids.get(head_icon.get("href", ""))
        pointer_id = f"v{index}-{head_id}"
        pointer = xml_id_map.get(pointer_id)
        if (
            not head_id
            or not image_id
            or pointer is None
            or _local(pointer) != "ptr"
            or pointer.get("type") != "source-html-head-link"
            or pointer.get("target") != f"#{image_id}"
        ):
            raise ValueError(
                f"source head icon id/target mapping mismatch for PG{ebook_id}"
            )

        head_elements = set(html_head.iter())
        source_id_elements = [
            element for element in html_doc.iter() if element.get("id")
        ]
        source_ids = [element.get("id") for element in source_id_elements]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError(f"source HTML ids are not unique for PG{ebook_id}")
        footer = volume.xpath(
            ".//t:div[@xml:id=$x]", namespaces=ns, x=f"v{index}-pg-footer"
        )
        if len(footer) != 1:
            raise ValueError(
                f"candidate provider-license wrapper missing for PG{ebook_id}"
            )
        for source_id_element in source_id_elements:
            source_id = source_id_element.get("id")
            candidate_id = f"v{index}-{source_id}"
            mapped = xml_id_map.get(candidate_id)
            in_head = source_id_element in head_elements
            if mapped is None:
                raise ValueError(
                    f"source id mapping mismatch for PG{ebook_id}/{source_id}"
                )
            if in_head:
                if mapped is not pointer:
                    raise ValueError(
                        f"source head id does not map to its image pointer PG{ebook_id}"
                    )
            elif not any(mapped is member for member in volume.iter()):
                raise ValueError(
                    f"source body id escaped its volume PG{ebook_id}/{source_id}"
                )
            if source_id in FOOTER_ANCHORS and (
                _local(mapped) != "anchor"
                or not any(mapped is member for member in footer[0].iter())
            ):
                raise ValueError(
                    f"source footer anchor was not preserved PG{ebook_id}/{source_id}"
                )
            expected_ids.append(
                {
                    "ebook_id": ebook_id,
                    "volume": roman,
                    "source_id": source_id,
                    "source_tag": _local(source_id_element),
                    "source_zone": "head" if in_head else "body",
                    "source_href": source_id_element.get("href"),
                    "candidate_xml_id": candidate_id,
                    "candidate_element": _local(mapped),
                    "candidate_zone": "teiHeader" if in_head else "source-volume",
                    "candidate_target": mapped.get("target"),
                }
            )

        findings.append(
            f"PG{ebook_id}: exact normalized visible body text "
            f"({len(source_text)} characters), "
            f"{len(source_headings)} exact ordered h3 headings, "
            f"{len(source_ids)} mapped source ids, "
            f"{len(source_images)} byte-identical embedded image occurrences."
        )

    if accountability.get("archive_members") != expected_archives:
        raise ValueError(
            "complete ZIP member accounting differs from retained inventory/receipts"
        )
    if accountability.get("visible_body_text") != expected_text:
        raise ValueError(
            "candidate visible-body text accounting differs from source oracle"
        )
    if accountability.get("source_id_mappings") != expected_ids:
        raise ValueError("candidate source-id mapping ledger differs from HTML5 oracle")
    if accountability.get("media_occurrences") != expected_media:
        raise ValueError(
            "candidate media ledger differs from retained HTML5/ZIP evidence"
        )
    if accountability.get("source_image_links") != expected_links:
        raise ValueError(
            "candidate image-link ledger differs from retained HTML5 evidence"
        )

    xsd_path = manifest.authority_path("tei-p5-xsd")
    schema = etree.XMLSchema(etree.parse(str(xsd_path)))
    if not schema.validate(etree.ElementTree(tei)):
        raise ValueError(f"TEI P5 failed: {schema.error_log.last_error}")
    findings.append(
        "TEI P5 XSD passed; one collected work is represented by one TEI with ordered "
        "volume divisions I-III, and volumes IV-VI are excluded."
    )

    primary_sources = [
        {
            "name": item["name"],
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in manifest.record["authorities"]
        if item["role"] == "primary-source"
    ]
    source_sha256 = _sha(
        _canonical(
            {
                "contract": "ocd-source-member-set-v1",
                "members": sorted(
                    primary_sources, key=lambda item: (item["path"], item["name"])
                ),
            }
        )
    )
    validator = manifest.record["validator"]
    profile_authority = next(
        item
        for item in manifest.record["authorities"]
        if item["role"] == "complete-source-feature-profile"
    )
    package_authority = next(
        item
        for item in manifest.record["authorities"]
        if item["role"] == "candidate-package-schema"
    )
    schema_authority = next(
        item
        for item in manifest.record["authorities"]
        if item["role"] == "tei-validation-schema"
    )
    policy_authority = next(
        item
        for item in manifest.record["authorities"]
        if item["role"] == "independent-validation-policy"
    )
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": validator["implementation_sha256"],
        "import_closure_sha256": validator["import_closure_sha256"],
        "runtime": (
            f"{platform.python_implementation()} {platform.python_version()} "
            f"({Path(sys.executable).resolve()})"
        ),
        "source_manifest_sha256": manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": profile_authority["sha256"],
        "package_schema_sha256": package_authority["sha256"],
        "source_sha256": source_sha256,
        "xsd_sha256": schema_authority["sha256"],
        "policy_sha256": policy_authority["sha256"],
        "findings": findings,
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
