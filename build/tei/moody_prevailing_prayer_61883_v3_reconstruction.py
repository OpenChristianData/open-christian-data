"""Corrected source-bound successor for Project Gutenberg 61883."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
import platform
import re
import sys
import zipfile
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _closure(root: Path) -> str:
    paths = [Path(__file__).resolve(strict=True), (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True),
             (root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True)]
    return _sha(_json([{"path": item.relative_to(root).as_posix(), "sha256": _sha(item.read_bytes())}
                       for item in sorted(paths, key=lambda path: path.relative_to(root).as_posix())]))


def _profile(source: SourceManifest) -> dict[str, object]:
    return json.loads(source.authority_path("work-profile").read_bytes())


def _append_rend(element: etree._Element, token: str) -> None:
    values = (element.get("rend") or "").split()
    if token not in values:
        values.append(token)
    element.set("rend", " ".join(values))


def _one_by_n(root: etree._Element, tag: str, selector: str) -> etree._Element:
    matches = root.xpath(f".//tei:{tag}[@n=$selector]", namespaces={"tei": TEI}, selector=selector)
    if len(matches) != 1:
        raise ValueError(f"expected one TEI {tag} at source selector {selector}")
    return matches[0]


def _candidate(source: SourceManifest, profile: Mapping[str, object]) -> tuple[CandidatePackage, etree._Element]:
    package = CandidatePackage.load(Path(str(profile["predecessor_candidate_path"])))
    if package.sha256 != profile["predecessor_candidate_manifest_sha256"]:
        raise ValueError("PG 61883 predecessor candidate changed")
    content = etree.fromstring(package.member_bytes("content.tei.xml"), etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if content.tag != f"{{{TEI}}}TEI" or content.get(f"{{{XML}}}id") != "pg61883-bounded-witness":
        raise ValueError("PG 61883 predecessor is not the identified single-work TEI")
    return package, content


def _convert(source: SourceManifest) -> dict[str, bytes]:
    profile = _profile(source)
    package, tree = _candidate(source, profile)
    title = tree.findtext(".//{http://www.tei-c.org/ns/1.0}titleStmt/{http://www.tei-c.org/ns/1.0}title")
    author = tree.findtext(".//{http://www.tei-c.org/ns/1.0}titleStmt/{http://www.tei-c.org/ns/1.0}author")
    if title != "Prevailing Prayer: What Hinders It?" or author != "D. L. Moody":
        raise ValueError("PG 61883 title-page identity differs from the source")

    text = tree.find(f"{{{TEI}}}text")
    if text is None:
        raise ValueError("PG 61883 candidate has no text")
    for row in profile["image_alt_attributes"]:
        graphic = _one_by_n(text, "graphic", row["source_n"])
        if row["value"] == "":
            _append_rend(graphic, "source-alt-empty")
        elif graphic.get("rend") != f"source-alt:{row['value']}":
            raise ValueError(f"PG 61883 nonempty image alt differs at {row['source_n']}")
    for row in profile["image_dimension_attributes"]:
        graphic = _one_by_n(text, "graphic", row["source_n"])
        graphic.set("width", row["tei_width"])
        graphic.set("height", row["tei_height"])
    for row in profile["table_summary_attributes"]:
        table = _one_by_n(text, "table", row["source_n"])
        _append_rend(table, f"source-data-summary:{row['value']}")
    for row in profile["empty_title_attributes"]:
        matches = text.xpath(".//*[@xml:id=$identifier]", namespaces={"xml": XML}, identifier=row["tei_xml_id"])
        if len(matches) != 1:
            raise ValueError("PG 61883 empty title attribute target is ambiguous")
        _append_rend(matches[0], "source-title-empty")

    header = tree.find(f"{{{TEI}}}teiHeader")
    if header is None:
        raise ValueError("PG 61883 candidate has no TEI header")
    source_desc = header.find(f"{{{TEI}}}fileDesc/{{{TEI}}}sourceDesc")
    if source_desc is None or len(source_desc) != 1 or source_desc[0].tag != f"{{{TEI}}}p":
        raise ValueError("PG 61883 source description has an unexpected structure")
    source_desc[0].text = (
        "Project Gutenberg ebook 61883, Prevailing Prayer: What Hinders It?, by D. L. Moody. "
        "The retained English electronic witness presents the complete titled book: title page, "
        "prefatory note, contents, eleven numbered chapters, and the Project Gutenberg license. "
        "This scope is one book, not Moody's complete writings."
    )
    for fact in profile["source_bibliographic_metadata"]:
        item = etree.SubElement(source_desc[0], f"{{{TEI}}}seg")
        item.set("type", fact["name"])
        item.text = fact["value"]
    profile_desc = header.find(f"{{{TEI}}}profileDesc")
    if profile_desc is None:
        profile_desc = etree.SubElement(header, f"{{{TEI}}}profileDesc")
    lang_usage = profile_desc.find(f"{{{TEI}}}langUsage")
    if lang_usage is None:
        lang_usage = etree.SubElement(profile_desc, f"{{{TEI}}}langUsage")
    for child in list(lang_usage):
        lang_usage.remove(child)
    language = etree.SubElement(lang_usage, f"{{{TEI}}}language")
    language.set("ident", "en")
    language.text = "English"
    text_class = profile_desc.find(f"{{{TEI}}}textClass")
    if text_class is None:
        text_class = etree.SubElement(profile_desc, f"{{{TEI}}}textClass")
    for child in list(text_class):
        text_class.remove(child)
    keywords = etree.SubElement(text_class, f"{{{TEI}}}keywords")
    keywords.set("scheme", "source-metadata")
    for subject in profile["source_subjects"]:
        term = etree.SubElement(keywords, f"{{{TEI}}}term")
        term.text = subject
    publication = header.find(f"{{{TEI}}}fileDesc/{{{TEI}}}publicationStmt")
    if publication is None:
        raise ValueError("PG 61883 publication statement is missing")
    publication_p = publication.find(f"{{{TEI}}}p")
    if publication_p is None:
        raise ValueError("PG 61883 publication statement has no prose target for source metadata")
    rights = etree.SubElement(publication_p, f"{{{TEI}}}seg")
    rights.set("type", "source-dc.rights")
    rights.text = profile["source_rights"]
    rights_status = etree.SubElement(publication_p, f"{{{TEI}}}seg")
    rights_status.set("type", "rights-clearance-status")
    rights_status.text = "This records the source's statement and does not establish rights clearance."
    tree.set(f"{{{XML}}}lang", "en")

    content = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    archive = source.authority_path("retained-archive")
    members = profile["archive_members"]
    accountability = {
        "contract": "ocd-moody-pg61883-source-accountability-v3",
        "work_id": source.record["work_id"],
        "edition_id": source.record["edition_id"],
        "acquisition_id": source.record["acquisition_id"],
        "source_id": source.record["source_id"],
        "retained_archive_path": "raw/gutenberg/61883/pg61883-h.zip",
        "retained_archive_sha256": _sha(archive.read_bytes()),
        "archive_members": members,
        "predecessor_candidate_manifest_sha256": package.sha256,
        "predecessor_validation_sha256": profile["predecessor_validation_sha256"],
        "predecessor_content_sha256": _sha(package.member_bytes("content.tei.xml")),
        "candidate_text_sha256": _sha(etree.tostring(tree.find(f"{{{TEI}}}text"), method="c14n")),
        "candidate_tei_sha256": _sha(content),
        "boundary": "One complete titled English book, Prevailing Prayer: What Hinders It?; source copyright is 1884, not an established publication date. This is not the author's complete writings.",
        "preservation": "The validated predecessor text subtree is preserved except for explicit source-attribute carriers listed in source_body_attribute_mappings; the TEI header records source title, author, language, bibliographic claims, subjects, and rights metadata with their source roles preserved.",
        "source_body_attribute_mappings": profile["source_body_attribute_mappings"],
        "source_html_head_inventory": profile["source_html_head_inventory"],
        "source_html_head_disposition": profile["source_html_head_disposition"],
    }
    provenance = {key: source.record[key] for key in ("work_id", "edition_id", "acquisition_id", "source_id")}
    provenance.update({"source_manifest_sha256": source.sha256, "status": "nonaccepted"})
    readme = (
        "# Prevailing Prayer: What Hinders It?\n\n"
        "D. L. Moody's complete titled book as represented by the retained Project Gutenberg 61883 English electronic witness: title page, prefatory note, contents, eleven numbered chapters, images, and the witness's license material. This does not claim to cover all Moody writings.\n\n"
        "Source attributes are explicitly carried: empty image alt attributes, two source image dimensions, the table summary, and the empty PG header title. Source-supplied title, creator, subjects, URLs, generator, electronic dates, and rights statement remain attributed as metadata; the remote OG image is not acquired. The copyright statement is not used as a publication date.\n\n"
        "The retained source archive and all 19 members, including 18 image files, are hash-accounted in `source-accountability.json`. The source's dc.rights value is ‘Public domain in the USA.’; it is not a worldwide rights determination. Human acceptance, rights review, and publication remain separate.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": content,
        "source-accountability.json": _json(accountability),
        "provenance.json": _json(provenance),
        "unresolved.jsonl": package.member_bytes("unresolved.jsonl"),
        "README.source.md": readme,
    }


def _oracle(source: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source.verify()
    candidate.verify_integrity()
    profile = _profile(source)
    archive_path = source.authority_path("retained-archive")
    archive_bytes = archive_path.read_bytes()
    if _sha(archive_bytes) != profile["archive_sha256"]:
        raise ValueError("PG 61883 retained archive hash differs")
    with zipfile.ZipFile(archive_path) as archive:
        expected_members = {item["path"]: item for item in profile["archive_members"]}
        if set(archive.namelist()) != set(expected_members):
            raise ValueError("PG 61883 archive member set differs")
        for name, record in expected_members.items():
            raw = archive.read(name)
            if len(raw) != record["bytes"] or _sha(raw) != record["sha256"]:
                raise ValueError(f"PG 61883 member drift: {name}")
        html = archive.read("pg61883-images.html")
    source_html = etree.HTML(html)
    title_text = " ".join((source_html.findtext(".//title") or "").split())
    first_heading = " ".join(source_html.xpath("string((//h2)[1])").split())
    if "Prevailing Prayer: What Hinders It?" not in title_text or "D. L. Moody" not in title_text or "Prevailing Prayer: What Hinders It?" not in first_heading:
        raise ValueError("PG 61883 printed title-page identity disagrees with profile")
    chapter_labels = [item.upper() for item in re.findall(r"CHAPTER\s+(XI|X|IX|VIII|VII|VI|V|IV|III|II|I)\s*\.", " ".join(" ".join(source_html.xpath("//h2//text()")).split()), flags=re.IGNORECASE)]
    if "PREFATORY NOTE." not in html.decode("utf-8", errors="replace").upper() or chapter_labels != ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI"]:
        raise ValueError("PG 61883 complete-book boundary evidence is incomplete")

    head = source_html.find(".//head")
    if head is None:
        raise ValueError("PG 61883 source HTML head is missing")
    observed_head_inventory = []
    for element in head:
        raw_text = (element.text or "").encode("utf-8")
        observed_head_inventory.append({
            "tag": element.tag,
            "attributes": dict(sorted(element.attrib.items())),
            "text": " ".join((element.text or "").split()) if element.tag in {"title", "meta", "link"} else None,
            "text_bytes": len(raw_text),
            "text_sha256": _sha(raw_text),
        })
    if observed_head_inventory != profile["source_html_head_inventory"]:
        raise ValueError("PG 61883 source HTML head metadata or transport inventory differs")
    source_images = source_html.xpath("//img")
    observed_alts = [
        {"url": image.get("src"), "attribute_present": "alt" in image.attrib, "value": image.get("alt")}
        for image in source_images
    ]
    profile_alts = [{key: row[key] for key in ("url", "attribute_present", "value")} for row in profile["image_alt_attributes"]]
    if observed_alts != profile_alts or len(observed_alts) != 18:
        raise ValueError("PG 61883 image ALT states differ from the retained source")
    observed_dimensions = []
    for image in source_images:
        if "width" in image.attrib or "height" in image.attrib:
            observed_dimensions.append({"url": image.get("src"), "width": image.get("width"), "height": image.get("height")})
    profile_dimensions = [{key: row[key] for key in ("url", "width", "height")} for row in profile["image_dimension_attributes"]]
    if observed_dimensions != profile_dimensions:
        raise ValueError("PG 61883 image dimensions differ from the retained source")
    source_summaries = [{"value": table.get("data-summary"), "id": table.get("id")} for table in source_html.xpath("//table[@data-summary]")]
    if source_summaries != [{"value": row["value"], "id": row["source_id"]} for row in profile["table_summary_attributes"]]:
        raise ValueError("PG 61883 table summary differs from the retained source")
    source_empty_titles = [{"id": heading.get("id"), "value": heading.get("title")} for heading in source_html.xpath("//h2[@title]")]
    if source_empty_titles != [{"id": row["source_id"], "value": row["value"]} for row in profile["empty_title_attributes"]]:
        raise ValueError("PG 61883 empty title attribute differs from the retained source")

    predecessor, prior_tree = _candidate(source, profile)
    predecessor_source_path = source.repository_root / str(profile["predecessor_source_manifest_path"])
    predecessor_source_bytes = predecessor_source_path.read_bytes()
    if _sha(predecessor_source_bytes) != profile["predecessor_source_manifest_sha256"]:
        raise ValueError("PG 61883 predecessor source manifest changed")
    validation_bytes = Path(str(profile["predecessor_validation_path"])).read_bytes()
    validation = json.loads(validation_bytes)
    if (_sha(validation_bytes) != profile["predecessor_validation_sha256"]
            or validation.get("candidate_sha256") != predecessor.sha256
            or validation.get("source_manifest_sha256") != profile["predecessor_source_manifest_sha256"]
            or validation.get("status") != "pass" or validation.get("findings") != []):
        raise ValueError("PG 61883 validated predecessor proof drifted")
    content = candidate.member_bytes("content.tei.xml")
    tree = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if tree.tag != f"{{{TEI}}}TEI" or tree.get(f"{{{XML}}}id") != "pg61883-bounded-witness":
        raise ValueError("candidate must be one direct TEI for the identified complete title")
    expected_tree = deepcopy(prior_tree)
    expected_text = expected_tree.find(f"{{{TEI}}}text")
    if expected_text is None:
        raise ValueError("validated predecessor has no TEI text")
    for row in profile["image_alt_attributes"]:
        graphic = _one_by_n(expected_text, "graphic", row["source_n"])
        if row["value"] == "":
            tokens = (graphic.get("rend") or "").split()
            if "source-alt-empty" not in tokens:
                tokens.append("source-alt-empty")
            graphic.set("rend", " ".join(tokens))
        elif graphic.get("rend") != f"source-alt:{row['value']}":
            raise ValueError("validated predecessor does not preserve the source's nonempty image alt")
    for row in profile["image_dimension_attributes"]:
        graphic = _one_by_n(expected_text, "graphic", row["source_n"])
        graphic.set("width", row["tei_width"])
        graphic.set("height", row["tei_height"])
    for row in profile["table_summary_attributes"]:
        table = _one_by_n(expected_text, "table", row["source_n"])
        tokens = (table.get("rend") or "").split()
        token = f"source-data-summary:{row['value']}"
        if token not in tokens:
            tokens.append(token)
        table.set("rend", " ".join(tokens))
    for row in profile["empty_title_attributes"]:
        matches = expected_text.xpath(".//*[@xml:id=$identifier]", namespaces={"xml": XML}, identifier=row["tei_xml_id"])
        if len(matches) != 1:
            raise ValueError("validated predecessor has no unique empty-title target")
        tokens = (matches[0].get("rend") or "").split()
        if "source-title-empty" not in tokens:
            tokens.append("source-title-empty")
        matches[0].set("rend", " ".join(tokens))
    if etree.tostring(tree.find(f"{{{TEI}}}text"), method="c14n") != etree.tostring(expected_text, method="c14n"):
        raise ValueError("candidate text differs beyond the exact source-attribute carrier transformations")
    title = tree.findtext(f".//{{{TEI}}}titleStmt/{{{TEI}}}title")
    author = tree.findtext(f".//{{{TEI}}}titleStmt/{{{TEI}}}author")
    lang = tree.get(f"{{{XML}}}lang")
    lang_elem = tree.find(f".//{{{TEI}}}profileDesc/{{{TEI}}}langUsage/{{{TEI}}}language")
    source_desc = tree.findtext(f".//{{{TEI}}}sourceDesc/{{{TEI}}}p") or ""
    if (title, author, lang, None if lang_elem is None else lang_elem.get("ident")) != ("Prevailing Prayer: What Hinders It?", "D. L. Moody", "en", "en"):
        raise ValueError("candidate title, author, or English language linkage is wrong")
    if "1887 Tagalog" in source_desc or "Spanish-language" in source_desc or "A Short Method of Prayer" in source_desc or "not Moody's complete writings" not in source_desc:
        raise ValueError("candidate source scope or identity metadata is contradicted")
    for fact in profile["source_bibliographic_metadata"]:
        matches = tree.xpath(".//tei:sourceDesc//*[@type=$name]", namespaces={"tei": TEI}, name=fact["name"])
        if len(matches) != 1 or "".join(matches[0].itertext()) != fact["value"]:
            raise ValueError(f"source bibliographic metadata is missing or altered: {fact['name']}")
    actual_subjects = tree.xpath(".//tei:textClass/tei:keywords[@scheme='source-metadata']/tei:term/text()", namespaces={"tei": TEI})
    if actual_subjects != profile["source_subjects"]:
        raise ValueError("source subjects are not retained with their source-metadata role")
    rights_text = tree.xpath("string(.//tei:publicationStmt/tei:p/tei:seg[@type='source-dc.rights'])", namespaces={"tei": TEI})
    rights_status = tree.xpath("string(.//tei:publicationStmt/tei:p/tei:seg[@type='rights-clearance-status'])", namespaces={"tei": TEI})
    if rights_text != profile["source_rights"] or "does not establish rights clearance" not in rights_status:
        raise ValueError("source-supplied rights claim is not distinguished from rights clearance")
    if "*** END OF THE PROJECT GUTENBERG EBOOK PREVAILING PRAYER" not in "".join(tree.find(f"{{{TEI}}}text/{{{TEI}}}body").itertext()):
        raise ValueError("candidate omits the Project Gutenberg license/end matter")
    image_urls = tree.xpath(".//tei:graphic/@url", namespaces={"tei": TEI})
    expected_images = sorted(profile["image_references"])
    if image_urls != profile["image_references"] or len(image_urls) != 18:
        raise ValueError("candidate does not preserve all 18 source image carriers")
    schema = etree.XMLSchema(etree.parse(str(source.authority_path("tei-p5-xsd"))))
    if not schema.validate(tree):
        raise ValueError(f"candidate fails TEI P5: {schema.error_log.last_error}")
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    if (accountability.get("retained_archive_sha256") != profile["archive_sha256"]
            or accountability.get("archive_members") != profile["archive_members"]
            or accountability.get("candidate_tei_sha256") != _sha(content)
            or accountability.get("source_body_attribute_mappings") != profile["source_body_attribute_mappings"]
            or accountability.get("source_html_head_inventory") != profile["source_html_head_inventory"]
            or accountability.get("source_html_head_disposition") != profile["source_html_head_disposition"]):
        raise ValueError("source-accountability does not bind complete archive and candidate")
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    for key in ("work_id", "edition_id", "acquisition_id", "source_id"):
        if provenance.get(key) != source.record[key]:
            raise ValueError(f"candidate linkage metadata mismatch: {key}")
    if provenance.get("source_manifest_sha256") != source.sha256:
        raise ValueError("candidate is linked to a different source manifest")
    authority_by_role = {item["role"]: item for item in source.record["authorities"]}
    result = {
        "status": "pass",
        "oracle_id": source.record["validator"]["id"],
        "oracle_version": source.record["validator"]["version"],
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _closure(source.repository_root),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": authority_by_role["complete-source-feature-profile"]["sha256"],
        "package_schema_sha256": authority_by_role["candidate-package-schema"]["sha256"],
        "source_sha256": profile["archive_sha256"],
        "xsd_sha256": authority_by_role["tei-validation-schema"]["sha256"],
        "policy_sha256": authority_by_role["independent-validation-policy"]["sha256"],
        "findings": [],
    }
    result["result_sha256"] = _sha(_json(result))
    return result
_convert.converter_id = "ocd-moody-prevailing-prayer-pg61883-v3"
_convert.converter_version = "1"
_oracle.oracle_id = "ocd-moody-prevailing-prayer-pg61883-independent-v3"
_oracle.oracle_version = "1"
