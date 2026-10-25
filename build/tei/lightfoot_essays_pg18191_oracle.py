"""Independent full-body and package oracle for Lightfoot's PG18191 HTML."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import zipfile

from lxml import etree, html

from build.tei.lightfoot_essays_pg18191_native import (
    ALT_TEXT_SHA256, COVER_MEMBER_SHA256, PACKAGE_SHA256, RAW, ROOT,
    SOURCE, SOURCE_SHA256,
)
from ocd_kernel.lib.storage_topology import resolve_repo_path


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
VISIBLE_SHA256 = "267d9e684e13c4dde33690e59ff3d426b0449caa4b61f1bc728129fe2a59fa81"
TITLE = "Essays on the Work Entitled Supernatural Religion"
SECTION_HEADS = (
    "SUPERNATURAL RELIGION.", "II. THE SILENCE OF EUSEBIUS.",
    "III. THE IGNATIAN EPISTLES.", "IV. POLYCARP OF SMYRNA.",
    "V. PAPIAS OF HIERAPOLIS.", "VI. PAPIAS OF HIERAPOLIS.",
    "VII. THE LATER SCHOOL OF ST JOHN.", "VIII. THE CHURCHES OF GAUL.",
    "IX. TATIAN'S DIATESSARON [272:1].",
    "DISCOVERIES ILLUSTRATING THE ACTS OF THE APOSTLES.",
)
SOURCE_SPANS = ((0, 1), (1, 4), (4, 10), (10, 18), (18, 21),
                (21, 77), (77, 174), (174, 248), (248, 372),
                (372, 448), (448, 542), (542, 609), (609, 647),
                (647, 691), (691, 708), (708, 1417), (1417, 1871),
                (1871, 1872))
GROUP_TYPES = ("project_gutenberg_header", "production_and_transcribers_note",
               "title_page", "preface", "contents", *("essay" for _ in range(9)),
               "appendix", "relocated_footnotes", "indices",
               "project_gutenberg_footer")


def _norm(value: str) -> str:
    return " ".join(value.split())


def check(candidate: bytes, *, source_root: Path = ROOT) -> dict:
    raw = resolve_repo_path(source_root, SOURCE.as_posix()).read_bytes()
    if sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("PG18191 real extracted HTML hash differs")
    for package_name, digest in PACKAGE_SHA256.items():
        archive_path = resolve_repo_path(source_root, (RAW / package_name).as_posix())
        if sha256(archive_path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"PG18191 package hash differs: {package_name}")
        real_name = SOURCE.name if package_name == "pg18191-h.zip" else package_name.removesuffix(".zip") + ".txt"
        real_path = resolve_repo_path(source_root, (RAW / real_name).as_posix())
        real = real_path.read_bytes()
        if package_name != "pg18191-h.zip" and sha256(real).hexdigest() != ALT_TEXT_SHA256[real_name]:
            raise ValueError(f"PG18191 alternate real TXT differs: {real_name}")
        with zipfile.ZipFile(archive_path) as archive:
            members = [real_name, "18191-cover.png"] if package_name == "pg18191-h.zip" else [real_name]
            if archive.namelist() != members or archive.read(real_name) != real:
                raise ValueError(f"PG18191 ZIP/real member bytes differ: {package_name}")
            if package_name == "pg18191-h.zip" and sha256(archive.read("18191-cover.png")).hexdigest() != COVER_MEMBER_SHA256:
                raise ValueError("PG18191 package-only cover differs")
    body_nodes = html.fromstring(raw.decode("utf-8")).xpath("//body")
    if len(body_nodes) != 1:
        raise ValueError("PG18191 HTML body count differs")
    body = body_nodes[0]
    direct = [node for node in body if isinstance(node.tag, str)]
    if len(direct) != 1872 or direct[0].get("id") != "pg-header" or direct[-1].get("id") != "pg-footer":
        raise ValueError("PG18191 complete body/wrapper boundary differs")
    if [i for i, node in enumerate(direct) if _norm(node.text_content()) in SECTION_HEADS] != [21, 77, 174, 248, 372, 448, 542, 609, 647, 693]:
        raise ValueError("PG18191 essay/appendix source headings differ")
    visible = _norm(body.text_content())
    if sha256(visible.encode()).hexdigest() != VISIBLE_SHA256:
        raise ValueError("PG18191 complete source visible text differs")
    tree = etree.fromstring(candidate)
    ns = {"tei": TEI_NS}
    text_nodes = tree.xpath("/tei:TEI/tei:text", namespaces=ns)
    if len(text_nodes) != 1 or _norm("".join(text_nodes[0].itertext())) != visible:
        raise ValueError("PG18191 complete ordered HTML/TEI text differs")
    if tree.xpath("string(/tei:TEI/tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title)", namespaces=ns) != TITLE:
        raise ValueError("PG18191 electronic title differs")
    groups = [unit for part in text_nodes[0] for unit in part if unit.tag == f"{{{TEI_NS}}}div"]
    if len(groups) != len(SOURCE_SPANS) or tuple(unit.get("type") for unit in groups) != GROUP_TYPES:
        raise ValueError("PG18191 source group type/order differs")
    for position, ((start, stop), unit) in enumerate(zip(SOURCE_SPANS, groups), 1):
        source_text = " ".join(_norm(node.text_content()) for node in direct[start:stop] if _norm(node.text_content()))
        rendered_text = _norm("".join(unit.itertext()))
        if source_text != rendered_text:
            raise ValueError(f"PG18191 direct-child span {position} differs")
    source_ids = [node.get("id") for node in body.iter() if isinstance(node.tag, str) and node.get("id")]
    tei_ids = [node.get(XML_ID) for node in tree.iter() if isinstance(node.tag, str) and node.get(XML_ID)]
    if len(source_ids) != 1880 or len(set(source_ids)) != 1880 or set(source_ids) != set(tei_ids):
        raise ValueError("PG18191 source ID accounting differs")
    notes = tree.xpath("//tei:note[@place='end']", namespaces=ns)
    if len(notes) != 708 or len(direct[708:1417]) != 709:
        raise ValueError("PG18191 relocated note span differs")
    if "Footnotes have been relocated" not in _norm(direct[3].text_content()):
        raise ValueError("PG18191 transcriber intervention notice differs")
    if not _norm(direct[-1].text_content()).startswith("*** END OF THE PROJECT GUTENBERG EBOOK"):
        raise ValueError("PG18191 provider footer/license differs")
    return dict(contract="ocd-pg18191-independent-complete-html-oracle-v1",
                source_sha256=SOURCE_SHA256, visible_sha256=VISIBLE_SHA256,
                selected_direct_children=len(direct), source_ids=len(source_ids),
                source_groups=len(groups), essay_sections=9, appendix_sections=1,
                relocated_notes=len(notes), package_count=3,
                cover_member_sha256=COVER_MEMBER_SHA256,
                provider_header_footer_included=True, title=TITLE)
