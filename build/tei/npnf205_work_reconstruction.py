"""Reconstruct one exact Gregory NPNF2-05 ThML work root as readable TEI."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from build.tei import npnf2_lib047_reconstruction as mapper
from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.writer import tei_el


CONVERTER_ID = "ocd-npnf205-work-root-to-tei"
CONVERTER_VERSION = "1"
SOURCE_SHA = "43e87ed232457fd2d5862f72dd2d5d84fe1e8b69f4c3eec839bad04579327bf3"
SOURCE_URL = "https://www.ccel.org/ccel/schaff/npnf205.xml"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _convert(manifest: SourceManifest) -> Mapping[str, bytes]:
    manifest.verify()
    profile = json.loads(Path(_io_path(manifest.authority_path("reconstruction-profile"))).read_bytes())
    policy = json.loads(Path(_io_path(manifest.authority_path("validation-policy"))).read_bytes())
    if (profile.get("contract") != "ocd-npnf205-work-profile-v1"
            or policy.get("contract") != "ocd-npnf205-work-policy-v1"):
        raise ValueError("NPNF2-05 work profile or policy changed")
    source_bytes = Path(_io_path(manifest.authority_path("retained-thml"))).read_bytes()
    if _sha(source_bytes) != SOURCE_SHA:
        raise ValueError("retained NPNF2-05 source changed")
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             remove_comments=False, remove_pis=False, huge_tree=True)
    root = etree.fromstring(source_bytes, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("source DOCTYPE is forbidden")
    matches = root.xpath("//*[@id=$source_id]", source_id=profile["source_root_id"])
    if len(matches) != 1:
        raise ValueError("source root absent or repeated")
    selected = matches[0]
    parent = selected.getparent()
    if (selected.tag != profile["source_tag"] or parent is None
            or parent.get("id") != profile["source_parent_id"]
            or selected.get("title") != profile["source_title"]
            or _sha(etree.tostring(selected, method="c14n")) != profile["source_root_c14n_sha256"]
            or len(list(selected.iter())) != profile["element_count"]):
        raise ValueError("source work boundary changed")
    work = Path("library/works") / profile["work_id"] / "work.json"
    acquisition = Path(profile["acquisition_path"])
    if (_sha(Path(_io_path(manifest.repository_root / work)).read_bytes()) != profile["work_sha256"]
            or _sha(Path(_io_path(manifest.repository_root / acquisition)).read_bytes())
            != profile["acquisition_sha256"]):
        raise ValueError("work or acquisition authority changed")

    document = tei_el("TEI", {"xml:id": f"npnf205-{profile['work_id']}-electronic"})
    header = tei_el("teiHeader")
    file_desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", text=profile["source_title"]))
    file_desc.append(title_stmt)
    publication = tei_el("publicationStmt")
    publication.append(tei_el("p", text=(
        "The retained electronic header states Public Domain. CCEL source terms and "
        "release rights require separate review.")))
    file_desc.append(publication)
    source_desc = tei_el("sourceDesc")
    bibliography = tei_el("bibl")
    bibliography.append(tei_el("title", text="Retained CCEL NPNF2-05 XML electronic witness"))
    bibliography.append(tei_el("idno", {"type": "source-url"}, SOURCE_URL))
    bibliography.append(tei_el("idno", {"type": "sha256"}, SOURCE_SHA))
    source_desc.append(bibliography)
    file_desc.append(source_desc)
    header.append(file_desc)
    document.append(header)
    body = tei_el("body")
    rows: list[dict] = []
    exceptions = {(item["source_member"], item["source_root_id"], item["source_xml_id"]):
                  item["passage"] for item in policy["neutral_reference_exceptions"]}
    mapper._append(selected, body, "npnf205", rows, None, work_id=profile["work_id"],
                   reference_exceptions=exceptions, source_root_id=profile["source_root_id"])
    text = tei_el("text")
    text.append(body)
    document.append(text)
    for node in document.iter():
        if node.text == "":
            node.text = None
        if node.tail == "":
            node.tail = None
    content = etree.tostring(document, encoding="UTF-8", xml_declaration=True)
    accounting = {
        "contract": "ocd-npnf205-work-accounting-v1", "work_id": profile["work_id"],
        "source_path": profile["source_path"], "source_sha256": SOURCE_SHA,
        "source_root_id": profile["source_root_id"], "source_parent_id": profile["source_parent_id"],
        "source_title": profile["source_title"],
        "source_root_c14n_sha256": profile["source_root_c14n_sha256"],
        "element_count": len(rows),
        "source_xml_id_count": sum(bool(node.get("id")) for node in selected.iter()),
        "tei_work_c14n_sha256": _sha(etree.tostring(body[0], method="c14n")),
        "scope_note": profile["scope_note"],
        "shared_matter_disposition": profile["shared_matter_disposition"],
    }
    provenance = {
        "contract": "ocd-npnf205-work-provenance-v1", "status": "nonaccepted",
        "work_id": profile["work_id"], "edition_id": profile["edition_id"],
        "acquisition_id": profile["acquisition_id"], "source_root_id": profile["source_root_id"],
        "canonical_ir_written": False, "publication": "not-ready",
    }
    unresolved = [
        {"status": "unresolved", "item": "Close visual and human review have not occurred."},
        {"status": "unresolved", "item": "Print collation, CCEL rights, and publication require separate review."},
    ]
    if profile["work_id"] == "gregory-of-nyssa-on-the-holy-trinity":
        unresolved.append({"status": "unresolved", "item":
                           "The retained opening note reports manuscript attribution uncertainty."})
    readme = (
        f"# {profile['source_title']} — NPNF2-05 electronic witness\n\n"
        f"Source: `{profile['source_path']}` (SHA-256 `{SOURCE_SHA}`), exact native root "
        f"`{profile['source_root_id']}`. {profile['scope_note']}\n\n"
        "The retained volume title page and preface credit William Moore and Henry Austin Wilson "
        "as translators, with Philip Schaff and Henry Wace under editorial supervision. These "
        "are source-level credits; no unsupported work-specific allocation is inferred. "
        "The retained electronic header states Public Domain; separate CCEL permission evidence "
        "is in `docs/sources/ccel-permission.md`. This candidate is nonaccepted.\n"
    ).encode()
    return {"content.tei.xml": content, "source-accountability.json": _json(accounting),
            "provenance.json": _json(provenance),
            "unresolved.jsonl": b"".join(_json(item) for item in unresolved),
            "README.source.md": readme}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
