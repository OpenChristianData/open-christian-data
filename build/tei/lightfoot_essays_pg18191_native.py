"""Source-specific native-safe heading rendition of Lightfoot PG18191."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import zipfile

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("raw/clean-ready-acquisition-to-tei/master-4/28/lightfoot-essays-supernatural-religion-1893/pg18191-images.html")
RAW = SOURCE.parent
SOURCE_SHA256 = "a3fdcb0d069bad8a6ee5855dfb25ccec9a5536668cf2af7c23675d3e0c9855b6"
PACKAGE_SHA256 = {
    "18191-8.zip": "9a22d7b93927a4c801be12bb401f728a9459decbe268ade307a2658b72d2abf1",
    "18191.zip": "07a16f96381a6f1bbe6320d5b7221464073c6f3ffa7988ee43f9ff2c6d697ae1",
    "pg18191-h.zip": "0ac44cd475db3a395a6152e42568be7f620cda2a3e057ea90c7a7df5f0d921ac",
}
ALT_TEXT_SHA256 = {
    "18191-8.txt": "445679673dbe4b67b518e4dfe79678fa6243b0d9a1b5f8fc353204107db860f0",
    "18191.txt": "1ed59682fd843a17eefb60a69c810b475c6ab884461109b3a9711d9271476c12",
}
COVER_MEMBER_SHA256 = "02399ab360764c798a299b549950ca32a935fcaf0db91a7d6742bd639ec43fbc"
TEI = "{http://www.tei-c.org/ns/1.0}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def source_bindings() -> list[dict]:
    result = []
    for path, digest, media_type, scope in (
        (SOURCE, SOURCE_SHA256, "text/html", "Complete real extracted HTML text authority."),
        *((RAW / name, expected, "application/zip", "Retained package, not text authority.")
          for name, expected in PACKAGE_SHA256.items()),
    ):
        content = resolve_repo_path(ROOT, path.as_posix()).read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError(f"PG18191 retained member changed: {path}")
        result.append(dict(path=path.as_posix(), bytes=len(content), sha256=digest,
                           media_type=media_type, scope=scope))
    for name, expected in ALT_TEXT_SHA256.items():
        if sha256(resolve_repo_path(ROOT, (RAW / name).as_posix()).read_bytes()).hexdigest() != expected:
            raise ValueError(f"PG18191 alternate real TXT changed: {name}")
    for archive_name, member_name in (("18191-8.zip", "18191-8.txt"),
                                      ("18191.zip", "18191.txt"),
                                      ("pg18191-h.zip", SOURCE.name)):
        with zipfile.ZipFile(resolve_repo_path(ROOT, (RAW / archive_name).as_posix())) as archive:
            expected_members = [member_name, "18191-cover.png"] if archive_name == "pg18191-h.zip" else [member_name]
            if archive.namelist() != expected_members:
                raise ValueError(f"PG18191 package members changed: {archive_name}")
            if archive.read(member_name) != resolve_repo_path(ROOT, (RAW / member_name).as_posix()).read_bytes():
                raise ValueError(f"PG18191 package member differs from real file: {archive_name}")
            if archive_name == "pg18191-h.zip" and sha256(archive.read("18191-cover.png")).hexdigest() != COVER_MEMBER_SHA256:
                raise ValueError("PG18191 package-only cover member changed")
    return result


def adapt(original: bytes) -> bytes:
    root = etree.fromstring(original)
    text = root.find(TEI + "text")
    if root.get(XML_LANG) != "en" or text is None or text.get(XML_LANG) is not None:
        raise ValueError("PG18191 language envelope differs")
    before = " ".join("".join(text.itertext()).split())
    del root.attrib[XML_LANG]
    text.set(XML_LANG, "en")
    headings = [node for node in root.iter(TEI + "ab") if (node.get("type") or "").startswith("source_h")]
    if len(headings) != 22:
        raise ValueError("PG18191 source heading count differs")
    for node in headings:
        source_type = node.get("type")
        if source_type not in {"source_h1", "source_h2", "source_h4", "source_h5"}:
            raise ValueError("PG18191 source heading level differs")
        node.set("type", source_type.replace("_", "-"))
    if " ".join("".join(text.itertext()).split()) != before:
        raise ValueError("PG18191 native heading rendition changed source text")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)
