"""Convert Book of Common Prayer HTML sources into TEI IR."""
from __future__ import annotations

import argparse
from pathlib import Path

from lxml import etree

from build.tei.bcp_source import BcpEdition, BcpEvent, load_bcp_edition, sha256
from ocd_kernel.tei.writer import TEI_NS, serialize, stamp_header, tei_el


class ConversionError(ValueError):
    """Raised when BCP source extraction cannot be represented in TEI."""


def _combined_sha(files: tuple[Path, ...]) -> str:
    h = sha256(files[0]) if len(files) == 1 else ""
    if h:
        return h
    import hashlib

    digest = hashlib.sha256()
    for path in files:
        if path.exists():
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(b"\n")
            digest.update(path.read_bytes())
            digest.update(b"\n")
    return digest.hexdigest()


def _header(edition: BcpEdition) -> etree._Element:
    header = stamp_header(
        title=edition.title,
        author=edition.author,
        contributors=[],
        source_url=edition.source_url,
        source_sha256=_combined_sha(edition.files),
        print_source=f"Book of Common Prayer, {edition.year} edition",
    )
    if edition.translator:
        title_stmt = header.find(f".//{{{TEI_NS}}}titleStmt")
        if title_stmt is None:
            raise ConversionError("Generated BCP header has no titleStmt")
        resp_stmt = tei_el("respStmt")
        resp_stmt.append(tei_el("resp", text="Translator"))
        resp_stmt.append(tei_el("name", text=edition.translator))
        title_stmt.append(resp_stmt)
    bibl = header.find(f".//{{{TEI_NS}}}sourceDesc/{{{TEI_NS}}}bibl")
    if bibl is None:
        raise ConversionError("Generated BCP header has no source bibliography")
    bibl.append(tei_el("note", {"type": "edition"}, text=edition.slug))
    return header


def _append_event(parent: etree._Element, event: BcpEvent) -> None:
    if event.feature == "labels":
        parent.append(tei_el("label", {"xml:id": event.xml_id}, text=event.text))
    elif event.feature == "rubrics":
        parent.append(tei_el("p", {"xml:id": event.xml_id, "rend": "rubric"}, text=event.text))
    elif event.feature == "speaker_units":
        sp = tei_el("sp", {"xml:id": event.xml_id})
        sp.append(tei_el("speaker", text=event.speaker))
        sp.append(tei_el("p", text=event.text))
        parent.append(sp)
    elif event.feature == "paragraphs":
        parent.append(tei_el("p", {"xml:id": event.xml_id}, text=event.text))
    else:
        raise ConversionError(f"Cannot append event feature {event.feature!r}")


def convert_bcp_to_tei(edition_slug: str, output_path: str | Path, *, raw_root: str | Path | None = None) -> Path:
    edition = load_bcp_edition(edition_slug, Path(raw_root) if raw_root is not None else None)
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    root.append(_header(edition))
    text = tei_el("text")
    body = tei_el("body")
    text.append(body)
    root.append(text)

    services: dict[str, etree._Element] = {}
    for event in edition.events:
        if event.feature == "services":
            service = tei_el("div", {"xml:id": event.xml_id, "type": "service"})
            service.append(tei_el("head", text=event.text))
            body.append(service)
            services[event.xml_id] = service
            continue
        try:
            target = services[event.service_id] if event.service_id else body
        except KeyError as exc:
            raise ConversionError(
                f"Event {event.xml_id!r} references unknown service {event.service_id!r}"
            ) from exc
        if event.feature == "collects":
            collect = tei_el("div", {"xml:id": event.xml_id, "type": "collect"})
            collect.append(
                tei_el(
                    "label",
                    {"xml:id": f"{event.xml_id}-label"},
                    text=event.label or "The Collect.",
                )
            )
            collect.append(tei_el("p", text=event.text))
            target.append(collect)
            continue
        _append_event(target, event)

    output = Path(output_path)
    serialize(etree.ElementTree(root), output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edition_slug")
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--raw-root", type=Path)
    args = parser.parse_args()
    output = convert_bcp_to_tei(args.edition_slug, args.output_path, raw_root=args.raw_root)
    print(f"Wrote {output.as_posix()}")


if __name__ == "__main__":
    main()
