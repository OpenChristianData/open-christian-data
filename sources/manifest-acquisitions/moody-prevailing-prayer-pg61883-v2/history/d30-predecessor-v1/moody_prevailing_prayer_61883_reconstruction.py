"""Corrected source-bound successor for Project Gutenberg 61883."""

from __future__ import annotations

import hashlib
import json
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
    tree.set(f"{{{XML}}}lang", "en")

    content = etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    archive = source.authority_path("retained-archive")
    members = profile["archive_members"]
    accountability = {
        "contract": "ocd-moody-pg61883-source-accountability-v1",
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
        "boundary": "One complete titled English book, Prevailing Prayer: What Hinders It? (1884 source statement); not the author's complete writings.",
        "preservation": "The source-bound predecessor text subtree is preserved exactly; only TEI header source description and English language metadata are corrected from the retained title page and front matter.",
    }
    provenance = {key: source.record[key] for key in ("work_id", "edition_id", "acquisition_id", "source_id")}
    provenance.update({"source_manifest_sha256": source.sha256, "status": "nonaccepted"})
    readme = (
        "# Prevailing Prayer: What Hinders It?\n\n"
        "D. L. Moody's complete titled book as represented by the retained Project Gutenberg 61883 English electronic witness: title page, prefatory note, contents, eleven numbered chapters, images, and the witness's license material. This does not claim to cover all Moody writings.\n\n"
        "The retained source archive and all 19 members, including 18 image files, are hash-accounted in `source-accountability.json`. Project Gutenberg states that its ebooks are public domain in the United States; this is not a worldwide rights determination. Human acceptance, rights review, and publication remain separate.\n"
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

    predecessor, prior_tree = _candidate(source, profile)
    validation_bytes = Path(str(profile["predecessor_validation_path"])).read_bytes()
    validation = json.loads(validation_bytes)
    if _sha(validation_bytes) != profile["predecessor_validation_sha256"] or validation.get("candidate_sha256") != predecessor.sha256 or validation.get("status") != "pass" or validation.get("findings") != []:
        raise ValueError("PG 61883 validated predecessor proof drifted")
    content = candidate.member_bytes("content.tei.xml")
    tree = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    if tree.tag != f"{{{TEI}}}TEI" or tree.get(f"{{{XML}}}id") != "pg61883-bounded-witness":
        raise ValueError("candidate must be one direct TEI for the identified complete title")
    if etree.tostring(tree.find(f"{{{TEI}}}text"), method="c14n") != etree.tostring(prior_tree.find(f"{{{TEI}}}text"), method="c14n"):
        raise ValueError("candidate text differs from the validated source-bound predecessor")
    title = tree.findtext(f".//{{{TEI}}}titleStmt/{{{TEI}}}title")
    author = tree.findtext(f".//{{{TEI}}}titleStmt/{{{TEI}}}author")
    lang = tree.get(f"{{{XML}}}lang")
    lang_elem = tree.find(f".//{{{TEI}}}profileDesc/{{{TEI}}}langUsage/{{{TEI}}}language")
    source_desc = tree.findtext(f".//{{{TEI}}}sourceDesc/{{{TEI}}}p") or ""
    if (title, author, lang, None if lang_elem is None else lang_elem.get("ident")) != ("Prevailing Prayer: What Hinders It?", "D. L. Moody", "en", "en"):
        raise ValueError("candidate title, author, or English language linkage is wrong")
    if "1887 Tagalog" in source_desc or "Spanish-language" in source_desc or "A Short Method of Prayer" in source_desc or "not Moody's complete writings" not in source_desc:
        raise ValueError("candidate source scope or identity metadata is contradicted")
    if "*** END OF THE PROJECT GUTENBERG EBOOK PREVAILING PRAYER" not in "".join(tree.find(f"{{{TEI}}}text/{{{TEI}}}body").itertext()):
        raise ValueError("candidate omits the Project Gutenberg license/end matter")
    image_urls = tree.xpath(".//tei:graphic/@url", namespaces={"tei": TEI})
    expected_images = sorted(profile["image_references"])
    if sorted(image_urls) != expected_images or len(image_urls) != 18:
        raise ValueError("candidate does not preserve all 18 source image carriers")
    schema = etree.XMLSchema(etree.parse(str(source.authority_path("tei-p5-xsd"))))
    if not schema.validate(tree):
        raise ValueError(f"candidate fails TEI P5: {schema.error_log.last_error}")
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    if accountability.get("retained_archive_sha256") != profile["archive_sha256"] or accountability.get("archive_members") != profile["archive_members"] or accountability.get("candidate_tei_sha256") != _sha(content):
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
_convert.converter_id = "ocd-moody-prevailing-prayer-pg61883-current"
_convert.converter_version = "1"
_oracle.oracle_id = "ocd-moody-prevailing-prayer-pg61883-independent"
_oracle.oracle_version = "1"
