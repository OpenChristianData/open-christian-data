"""Acquire the four exact pinned CC BY-SA PTA TEI members selected for L813."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "ef861ab391ea35c5d85b41dd8d7ba2bf65530b21"
REPOSITORY = "https://github.com/PatristicTextArchive/pta_data"
API = "https://api.github.com/repos/PatristicTextArchive/pta_data/contents/"
LICENSE = "https://creativecommons.org/licenses/by-sa/4.0/"
TEI = "http://www.tei-c.org/ns/1.0"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCES = (
    {
        "source_id": "pta-l813-amphilochius-epistula-synodalis-ef861ab3",
        "work_id": "amphilochius-epistula-synodalis",
        "edition_id": "pta-ef861ab3-amphilochius-epistula-synodalis",
        "path": "data/pta0013/pta003/pta0013.pta003.pta-grc1.xml",
        "blob_sha1": "07012026f7509e091dd83f431e2a3c348199bf06",
        "sha256": "dc2bbf61c403d8f502193e3566230cb7d542f61a79d7ec3315cdde2d67c57f1d",
        "bytes": 52048,
        "cts": "urn:cts:pta:pta0013.pta003.pta-grc1",
        "title": "Epistula synodalis",
        "author": "Amphilochius",
        "scope": "The complete exact pinned PTA Greek TEI member titled Epistula synodalis; the sourceDesc lists its manuscript witnesses and prior editions.",
    },
    {
        "source_id": "pta-l813-severian-de-fide-ef861ab3",
        "work_id": "severian-de-fide-et-lege-naturae",
        "edition_id": "pta-ef861ab3-severian-de-fide-et-lege-naturae",
        "path": "data/pta0001/pta001/pta0001.pta001.pta-grcBibex.xml",
        "blob_sha1": "334e48080be8901da7e09e42d56390985e45ede9",
        "sha256": "ceb7a7ed8c1a46be5c0a78d3bb00e39de656cdbf99d30c2d58ebe88778214cd1",
        "bytes": 224655,
        "cts": "urn:cts:pta:pta0001.pta001.pta-grcBibex",
        "title": "De fide et lege naturae",
        "author": "Severian of Gabala",
        "scope": "The complete exact pinned PTA Greek TEI member titled De fide et lege naturae; its sourceDesc records the edition and manuscript tradition.",
    },
    {
        "source_id": "pta-l813-hesychius-commentarius-magnus-ef861ab3",
        "work_id": "hesychius-commentarius-magnus-in-psalmos",
        "edition_id": "pta-ef861ab3-hesychius-commentarius-magnus-in-psalmos",
        "path": "data/pta0006/pta001/pta0006.pta001.pta-grc1.xml",
        "blob_sha1": "3b73410add136ff3e7a538e26c8736dd2728eaa6",
        "sha256": "5cd7b0db08aeaa2dc0193092bf0f091af2a75987da547c2396e05562ffd0faf4",
        "bytes": 971635,
        "cts": "urn:cts:pta:pta0006.pta001.pta-grc1",
        "title": "Commentarius magnus in Psalmos",
        "author": "Hesychius of Jerusalem",
        "scope": "The complete exact pinned PTA Greek TEI member titled Commentarius magnus in Psalmos; preserve its sourceDesc, embedded Greek edition, and editorial apparatus exactly as supplied.",
    },
    {
        "source_id": "pta-l813-vita-sancti-cononis-bidanae-ef861ab3",
        "work_id": "anonymous-vita-sancti-cononis-bidanae",
        "edition_id": "pta-ef861ab3-vita-sancti-cononis-bidanae-grc1",
        "path": "data/pta0041/pta001/pta0041.pta001.pta-grc1.xml",
        "blob_sha1": "6123ffe58cce467f7eda4cd0053ee51232c9b4bd",
        "sha256": "d17be373873c35f44e6e454a33987fa09f3eff39270ddcb0d482b696b610565e",
        "bytes": 223472,
        "cts": "urn:cts:pta:pta0041.pta001.pta-grc1",
        "title": "Vita sancti Cononis Bidanae",
        "author": "Anonymous",
        "scope": "The complete exact pinned PTA Greek critical edition titled Vita sancti Cononis Bidanae (grc1), edited by Philipp Pilhofer; the distinct pta-Mss manuscript transcription is CC BY-NC-SA 3.0 and is excluded.",
    },
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def parse_and_check(spec: dict[str, object], payload: bytes) -> dict[str, object]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, recover=False, huge_tree=False)
    root = etree.fromstring(payload, parser=parser)
    ns = {"tei": TEI}
    if etree.QName(root).localname != "TEI" or etree.QName(root).namespace != TEI:
        raise ValueError(f"PTA payload is not a TEI P5 root: {spec['source_id']}")
    if len(root.xpath("//tei:TEI", namespaces=ns)) != 1:
        raise ValueError(f"PTA payload must contain exactly one TEI root: {spec['source_id']}")
    titles = root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=ns)
    if len(titles) != 1 or " ".join("".join(titles[0].itertext()).split()) != spec["title"]:
        raise ValueError(f"PTA exact title mismatch for {spec['source_id']}")
    licenses = root.xpath("./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability/tei:licence", namespaces=ns)
    if len(licenses) != 1 or licenses[0].get("target") != LICENSE or "Attribution ShareAlike 4.0" not in " ".join("".join(licenses[0].itertext()).replace("-", " ").split()):
        raise ValueError(f"PTA file-level license mismatch for {spec['source_id']}")
    source_desc_nodes = root.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc", namespaces=ns)
    if len(source_desc_nodes) != 1:
        raise ValueError(f"PTA sourceDesc is missing or ambiguous for {spec['source_id']}")
    edition_divs = root.xpath("./tei:text/tei:body/tei:div[@type='edition']", namespaces=ns)
    edition_languages = [node.get(XML_LANG) for node in edition_divs]
    if "grc" not in edition_languages:
        raise ValueError(f"PTA Greek edition language is not explicit for {spec['source_id']}: {edition_languages!r}")
    contributors = []
    for resp_stmt in root.xpath("./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt", namespaces=ns):
        names = [" ".join("".join(node.itertext()).split()) for node in resp_stmt.xpath("./tei:persName|./tei:name", namespaces=ns)]
        roles = [" ".join("".join(node.itertext()).split()) for node in resp_stmt.xpath("./tei:resp", namespaces=ns)]
        contributors.append({"names": names, "responsibilities": roles})
    return {
        "source_title": " ".join("".join(titles[0].itertext()).split()),
        "root_xml_id": root.get(XML_ID),
        "tei_root_count": len(root.xpath("//tei:TEI", namespaces=ns)),
        "tei_element_count": len(root.xpath("//*")),
        "root_xml_lang": root.get(XML_LANG),
        "edition_languages": edition_languages,
        "license_url": licenses[0].get("target"),
        "license_statement": " ".join("".join(licenses[0].itertext()).split()),
        "header_contributors": contributors,
        "source_desc": " ".join("".join(source_desc_nodes[0].itertext()).split()),
    }


def fetch_once(spec: dict[str, object]) -> dict[str, object]:
    url = f"{API}{quote(str(spec['path']), safe='/')}?ref={COMMIT}"
    if urlparse(url).hostname != "api.github.com":
        raise ValueError("unexpected pinned PTA API host")
    request = Request(url, headers={"User-Agent": "OpenChristianData-source-retention/1.0", "Accept": "application/vnd.github+json"})
    with urlopen(request, timeout=90) as response:
        if response.status != 200 or urlparse(response.geturl()).hostname != "api.github.com":
            raise ValueError(f"PTA API returned unexpected status/redirect: {response.status} {response.geturl()}")
        payload_json = json.loads(response.read())
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
    if payload_json.get("sha") != spec["blob_sha1"] or payload_json.get("size") != spec["bytes"]:
        raise ValueError(f"pinned PTA API metadata mismatch for {spec['source_id']}")
    if payload_json.get("encoding") != "base64" or not payload_json.get("content"):
        raise ValueError(f"pinned PTA API did not return base64 content for {spec['source_id']}")
    payload = base64.b64decode("".join(str(payload_json["content"]).split()), validate=True)
    if len(payload) != spec["bytes"] or sha(payload) != spec["sha256"] or git_blob_sha1(payload) != spec["blob_sha1"]:
        raise ValueError(f"pinned PTA source bytes differ for {spec['source_id']}")
    header = parse_and_check(spec, payload)
    return {"payload": payload, "url": url, "final_url": final_url, "content_type": content_type, "header": header}


def main() -> None:
    raw_root = resolve_repo_path(ROOT, "raw").resolve(strict=True)
    prepared = []
    for spec in SOURCES:
        logical_dir = f"raw/pta/{COMMIT}/{spec['source_id']}"
        directory = resolve_repo_path(ROOT, logical_dir)
        physical_dir = directory.resolve(strict=False)
        if not physical_dir.is_relative_to(raw_root):
            raise ValueError(f"source destination escaped durable raw root: {physical_dir}")
        if directory.exists():
            raise FileExistsError(f"Refusing duplicate or overwrite at retained-source path: {directory}")
        filename = str(spec["path"]).rsplit("/", 1)[1]
        prepared.append((spec, logical_dir, directory, directory / filename, filename))
    if len({str(item[2]) for item in prepared}) != len(prepared):
        raise ValueError("duplicate PTA destination directory")

    # Fetch and verify all four exact members before writing any of them.
    fetched = [(spec, logical_dir, directory, source_path, filename, fetch_once(spec))
               for spec, logical_dir, directory, source_path, filename in prepared]
    acquired_at = datetime.now(timezone.utc).isoformat()
    for spec, logical_dir, directory, source_path, filename, result in fetched:
        directory.mkdir(parents=True, exist_ok=False)
        payload = result["payload"]
        header = result["header"]
        source_record = {
            "contract": "ocd-pta-source-acquisition-v1",
            "source_id": spec["source_id"], "manifest_row": "L813",
            "work_id": spec["work_id"], "edition_id": spec["edition_id"],
            "provider": "Patristic Text Archive (Berlin-Brandenburg Academy of Sciences and Humanities)",
            "repository_url": REPOSITORY, "pinned_commit": COMMIT,
            "source_url": result["url"], "final_url": result["final_url"],
            "cts_urn": spec["cts"], "upstream_git_blob_sha1": spec["blob_sha1"],
            "http_status": 200, "content_type": result["content_type"], "acquired_at_utc": acquired_at,
            "retained_file": {"path": f"{logical_dir}/{filename}", "bytes": len(payload), "sha256": sha(payload), "media_type": "application/tei+xml"},
            "file_identity": {"author": spec["author"], "title": header["source_title"], "scope": spec["scope"], "cts_urn": spec["cts"], "root_xml_id": header["root_xml_id"], "tei_root_count": header["tei_root_count"], "root_xml_lang": header["root_xml_lang"], "edition_languages": header["edition_languages"]},
            "file_level_license": {"target": header["license_url"], "statement": header["license_statement"]},
            "header_contributors": header["header_contributors"], "source_desc": header["source_desc"],
            "excluded_witness": ({"member": "pta-Mss", "license": "CC BY-NC-SA 3.0", "disposition": "not acquired; outside this CC BY-SA Greek critical-edition route"} if spec["work_id"] == "anonymous-vita-sancti-cononis-bidanae" else None),
            "human_acceptance": "not recorded", "rights_clearance": "unchanged; file-level CC BY-SA 4.0 is preserved for human review", "publication": "not authorized",
        }
        readme = (
            f"# Retained PTA TEI source: {header['source_title']}\n\n"
            f"**Canonical manifest row:** L813\n\n"
            f"**Author:** {spec['author']}\n\n"
            f"**Scope:** {spec['scope']}\n\n"
            f"**Patristic Text Archive locator:** `{spec['cts']}`\n\n"
            f"**Pinned official source:** {result['url']}\n\n"
            f"**Repository release:** `{COMMIT}`.\n\n"
            f"**Upstream Git blob SHA-1:** `{spec['blob_sha1']}`.\n\n"
            f"**Retained TEI SHA-256:** `{sha(payload)}` ({len(payload)} bytes).\n\n"
            f"**File-level license:** [CC BY-SA 4.0]({LICENSE}), as stated in the exact TEI header. Preserve PTA attribution and share-alike terms.\n\n"
            + ("The separately identified `pta-Mss` manuscript transcription is CC BY-NC-SA 3.0 and is excluded. This route covers only the Greek `pta-grc1` critical edition.\n\n" if spec["work_id"] == "anonymous-vita-sancti-cononis-bidanae" else "")
            + "This retained source and any reconstruction candidate remain nonaccepted. This receipt does not establish broader rights clearance, human acceptance, or publication authorization.\n"
        )
        with source_path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
        (directory / "acquisition-receipt.json").write_bytes(canonical(source_record))
        (directory / "README.source.md").write_text(readme, encoding="utf-8", newline="\n")
        print(json.dumps({"source_id": spec["source_id"], "path": str(source_path), "bytes": len(payload), "sha256": sha(payload), "git_blob_sha1": spec["blob_sha1"], "cts_urn": spec["cts"], "title": header["source_title"], "license": header["license_url"]}, ensure_ascii=False, sort_keys=True))
    if not raw_root.exists():
        raise RuntimeError("resolved durable raw root disappeared after PTA acquisition")


if __name__ == "__main__":
    main()
