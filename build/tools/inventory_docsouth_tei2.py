"""Inventory the exact retained DocSouth TEI.2 source envelope for 27 works."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from lxml import etree

from ocd_kernel.tei.install_accepted import _io_path


ROOT = Path(__file__).resolve().parents[2]
BATCH = ROOT / "plans/2026-09-22-source-preflight/docsouth-sidecar-batch-20260925.json"
CONTRACT = "ocd-docsouth-tei2-exact-source-shapes-v1"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _read(path: Path) -> bytes:
    return _io_path(path).read_bytes()


def inventory() -> dict:
    batch_bytes = _read(BATCH)
    batch = json.loads(batch_bytes)
    entries = batch.get("entries", [])
    if batch.get("contract") != "ocd-library-sidecar-batch-v1" or len(entries) != 27:
        raise ValueError("DocSouth fixed cohort sidecar batch must contain exactly 27 entries")
    observed = []
    for entry in sorted(entries, key=lambda item: item["work_id"]):
        work_id = entry["work_id"]
        member = entry["primary_source"]
        source_path = Path(member["path"])
        source_bytes = _read(ROOT / source_path)
        if len(source_bytes) != member["bytes"] or _sha(source_bytes) != member["sha256"]:
            raise ValueError(f"DocSouth retained XML changed: {work_id}")
        receipt_pin = entry["acquisition_receipt"]
        if _sha(_read(ROOT / receipt_pin["path"])) != receipt_pin["sha256"]:
            raise ValueError(f"DocSouth acquisition receipt changed: {work_id}")
        current_work_sha = _sha(_read(ROOT / entry["work"]["path"]))
        current_state_sha = _sha(_read(ROOT / entry["state"]["path"]))
        work = json.loads(_read(ROOT / entry["work"]["path"]))
        if (work.get("work_id") != work_id or len(work.get("textual_forms", [])) != 1
                or len(work["textual_forms"][0].get("editions", [])) != 1):
            raise ValueError(f"DocSouth work/edition identity changed: {work_id}")
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        if (form["textual_form_id"] != entry["textual_form_id"]
                or edition["edition_id"] != entry["edition_id"]
                or edition["acquisition_ids"] != [entry["acquisition_id"]]):
            raise ValueError(f"DocSouth acquisition identity changed: {work_id}")
        master = (ROOT / "library/works" / work_id / "forms" / form["textual_form_id"]
                  / "editions" / edition["edition_id"] / "master.tei.xml")
        parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True)
        source = etree.fromstring(source_bytes, parser)
        if source.tag != "TEI.2" or source.nsmap.get(None) is not None:
            raise ValueError(f"DocSouth source is not namespace-free TEI.2: {work_id}")
        texts = source.findall("text")
        if len(texts) != 1 or len(texts[0].findall("body")) != 1:
            raise ValueError(f"DocSouth source text/body envelope differs: {work_id}")
        text, body = texts[0], texts[0].find("body")
        counts = Counter(node.tag for node in source.iter() if isinstance(node.tag, str))
        dtd = source.getroottree().docinfo.internalDTD
        entities = [] if dtd is None else [
            dict(name=item.name, system_url=item.system_url, content=item.content)
            for item in dtd.iterentities()
        ]
        rights = source.find("teiHeader/fileDesc/publicationStmt/availability")
        if rights is None:
            raise ValueError(f"DocSouth electronic rights statement missing: {work_id}")
        rights_text = "".join(rights.itertext())
        image_refs = [
            dict(tag=node.tag, attribute=key, value=value)
            for figure in source.findall(".//figure")
            for node in figure.iter()
            if isinstance(node.tag, str)
            for key, value in node.attrib.items()
            if key == "entity"
        ]
        observed.append(dict(
            work_id=work_id, source_path=source_path.as_posix(), source_sha256=_sha(source_bytes),
            source_bytes=len(source_bytes), acquisition_receipt_path=entry["acquisition_receipt"]["path"],
            acquisition_receipt_sha256=entry["acquisition_receipt"]["sha256"],
            work_path=entry["work"]["path"], work_sha256=current_work_sha,
            work_dated_batch_sha256=entry["work"]["sha256"],
            work_dated_batch_pin_matches=current_work_sha == entry["work"]["sha256"],
            state_path=entry["state"]["path"], state_sha256=current_state_sha,
            state_dated_batch_sha256=entry["state"]["sha256"],
            state_dated_batch_pin_matches=current_state_sha == entry["state"]["sha256"],
            textual_form_id=form["textual_form_id"], edition_id=edition["edition_id"],
            acquisition_id=entry["acquisition_id"], accepted_master_present=_io_path(master).exists(),
            doctype=source.getroottree().docinfo.doctype, top_text_count=1,
            text_child_tags=[node.tag for node in text if isinstance(node.tag, str)],
            body_child_tags=[node.tag for node in body if isinstance(node.tag, str)],
            body_nested_text_count=len(body.findall(".//text")),
            front_count=len(text.findall("front")), back_count=len(text.findall("back")),
            element_counts=dict(sorted(counts.items())), entity_declarations=entities,
            figure_entity_references=image_refs, rights_text_sha256=_sha(rights_text.encode("utf-8")),
            rights_text=rights_text,
            body_text_sha256=_sha("".join(body.itertext()).encode("utf-8")),
            status="source-shape-only; no reconstruction or acceptance claim",
        ))
    if len({item["work_id"] for item in observed}) != 27:
        raise ValueError("DocSouth work identity repeated")
    return dict(contract=CONTRACT, status="read-only-source-shape-inventory", cohort_work_count=27,
                sidecar_batch_path=BATCH.relative_to(ROOT).as_posix(),
                sidecar_batch_sha256=_sha(batch_bytes), works=observed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output
    if _io_path(output).exists():
        raise ValueError("DocSouth inventory output must be a fresh path")
    result = inventory()
    content = (json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    _io_path(output).write_bytes(content)
    print(json.dumps(dict(works=len(result["works"]), output=output.as_posix(), sha256=_sha(content)), sort_keys=True))


if __name__ == "__main__":
    main()
