"""Complete exactly two already acquired Stokes CCEL electronic volume editions."""
from __future__ import annotations

import json
from pathlib import Path

from lxml import etree

from build.tei.stokes_retained_scope import ROOT, LOG, MEMBERS, WORK_ID, retained, parse, sha
from ocd_kernel.reconstruction import SourceManifest, reconstruct
from ocd_kernel.tei.writer import tei_el

SOURCE_DIR = Path("sources/commentaries/expositors-bible/stokes-existing-completion-20261003-v1")


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def administrative_account(source: etree._Element) -> list[dict[str, object]]:
    """Retain administration explicitly, separately from actual readable source body."""
    nodes = [x for x in source.iter() if isinstance(x.tag, str)]
    positions = {x: n for n, x in enumerate(nodes, 1)}
    body = source.find("ThML.body")
    rows = []
    for node in nodes:
        if node is body or body in node.iterancestors():
            continue
        parent = node.getparent()
        rows.append(dict(ordinal=positions[node], source_tag=node.tag, attributes=dict(node.attrib),
            text=node.text or "", tail=node.tail or "", parent_ordinal=positions.get(parent),
            child_index=list(parent).index(node) if parent is not None else 0,
            disposition="retained source administration; literal metadata summarized in header; CSS retained as rendering authority"))
    return rows


def convert(member_id: str) -> tuple[bytes, bytes]:
    # One emitter owner; frozen shared repair helper rather than duplicated parser.
    from build.tei.ccel_retained_native_emitter import emit_text
    spec = MEMBERS[member_id]
    raw = retained(member_id)
    source = parse(raw)
    text, account = emit_text(raw, member_id=member_id,
        front_ids=tuple(spec["front"]), back_ids=tuple(spec["back"]))
    header_source = source.find("ThML.head")
    title = header_source.findtext("electronicEdInfo/DC/DC.Title")
    author = header_source.findtext("electronicEdInfo/DC/DC.Creator[@sub='Author'][@scheme='short-form']")
    if not title or not author:
        raise ValueError(f"{member_id}: primary source title/author missing")
    tei = tei_el("TEI", {"xml:id": member_id})
    header = tei_el("teiHeader")
    desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", text=title))
    title_stmt.append(tei_el("author", text=author))
    for node in header_source.findall("electronicEdInfo/DC/DC.Creator[@sub='Editor'][@scheme='short-form']"):
        title_stmt.append(tei_el("editor", text=node.text))
    desc.append(title_stmt)
    publication = tei_el("publicationStmt")
    publication.append(tei_el("p", text="Agent-reviewed retained source reconstruction. Human review, print collation, CCEL formatting rights, and publication remain separate gates."))
    desc.append(publication)
    source_desc = tei_el("sourceDesc")
    source_desc.append(tei_el("p", text="Complete retained Christian Classics Ethereal Library electronic volume; SHA-256 " + spec["sha256"] + ". Literal print statement: " + (header_source.findtext("printSourceInfo/published") or "")))
    desc.append(source_desc)
    header.append(desc)
    tei.extend([header, text])
    account.update(contract="ocd-stokes-retained-readable-volume-accounting-v1", member_id=member_id,
        volume=spec["volume"], source=dict(path=spec["path"], bytes=len(raw), sha256=sha(raw)),
        retained_administration=administrative_account(source),
        original_candidate_route="existing LIB-034 ledger repair from its exact encoded retained witness" if spec["volume"] == 2 else "authorized completion of the already-acquired and started companion; no prior TEI found",
        acquired_work_scope="Both existing retained volume editions; this candidate contains exactly its one complete source volume")
    body = source.find('ThML.body')
    account['retained_nonbody_auxiliaries'] = [dict(node_kind='comment' if node.tag is etree.Comment else 'pi',
        target=node.target if node.tag is etree.PI else None, text=node.text, tail=node.tail,
        parent_selector=source.getroottree().getpath(node.getparent()), child_index=list(node.getparent()).index(node))
        for node in source.iter() if not isinstance(node.tag, str) and body not in node.iterancestors()]
    return etree.tostring(tei, encoding="UTF-8", xml_declaration=True), canonical(account)


def _convert(manifest: SourceManifest) -> dict[str, bytes]:
    manifest.verify()
    member_id = str(manifest.record["scope"]["member_id"])
    if member_id not in MEMBERS or manifest.record["work_id"] != WORK_ID:
        raise ValueError("Stokes candidate identity outside finite work")
    spec = MEMBERS[member_id]
    if manifest.authority_path("retained-thml").read_bytes() != retained(member_id):
        raise ValueError("Stokes candidate source authority differs")
    tei, account = convert(member_id)
    return {"content.tei.xml": tei, "source-accountability.json": account,
        "provenance.json": canonical(dict(status="nonaccepted", work_id=WORK_ID,
            member_id=member_id, source_id=manifest.record["source_id"],
            scope="complete retained electronic Volume " + str(spec["volume"]),
            acquisition="pre-existing; no download", human_acceptance="absent", rights="unresolved", publication="not_ready")),
        "unresolved.jsonl": canonical(dict(id=member_id + "-release", status="unresolved",
            detail="Human review, print collation, CCEL file and formatting rights, and publication are separate gates.")),
        "README.source.md": manifest.authority_path("source-local-attribution-readme").read_bytes()}


_convert.converter_id = "ocd-stokes-existing-retained-readable-completion"
_convert.converter_version = "1"
_convert.implementation_path = Path(__file__).resolve()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source-manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = SourceManifest.load(args.source_manifest, repository_root=ROOT)
    print(reconstruct(manifest, args.destination, _convert).sha256)


if __name__ == "__main__":
    main()
