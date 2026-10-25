"""Reader-facing publication facts and notices from the selected copy's evidence."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re

from lxml import etree

from ocd_kernel.library._common import PipelineError, read_input_bytes
from ocd_kernel.release.public_allowlist import _scan

# Exact editorial replacements; canonical source notices and row terms stay intact.
READING_COPY = json.loads(Path(__file__).with_name("release_notice_copy.json").read_text(encoding="utf-8"))


def plain(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def source_header(content: bytes) -> str:
    prefix = content[:2_000_000]
    end = re.search(rb"</(?:teiHeader|ThML\.head)>", prefix) or re.search(rb"</printSourceInfo>", prefix)
    if not end:
        return ""
    prefix = prefix[:end.end()]
    declared = re.search(rb'<\?xml[^>]*encoding=[\'"]([^\'"]+)', prefix[:300])
    encoding = declared[1].decode("ascii") if declared else "utf-8-sig"
    try:
        return prefix.decode(encoding)
    except (LookupError, UnicodeDecodeError) as exc:
        raise PipelineError("cannot decode the source bibliography header") from exc


def publication_from_header(content: bytes) -> dict:
    """Describe the printed source, never the digital file's creation date."""
    text = source_header(content)
    thml = re.search(r"<printSourceInfo\b[^>]*>(.*?)</printSourceInfo>", text, re.S)
    if thml:
        values = [plain(v) for v in re.findall(r"<published\b[^>]*>(.*?)</published>", thml[1], re.S)]
        if not any(values):
            return {}
        result = {"statement": "; ".join(v for v in values if v), "scope": "edition"}
        if len(values) == 1:
            imprint = re.fullmatch(r"([^:]+):\s*(.+?),\s*(\d{4}(?:[-–]\d{4})?)\.?", values[0])
            if imprint:
                result.update(place=[imprint[1]], publisher=[imprint[2]], date=[imprint[3]])
        return result
    header = re.search(r"<teiHeader\b[^>]*>.*?</teiHeader>", text, re.S)
    if not header:
        return {}
    try:
        tree = etree.fromstring(header[0].encode(), etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as exc:
        raise PipelineError("cannot read the source bibliography header") from exc
    bibliographies = tree.xpath(".//*[local-name()='sourceDesc']/*[local-name()='biblFull']")
    if len(bibliographies) != 1:
        return {}
    bibl = bibliographies[0]

    def values(path):
        return [" ".join(" ".join(e.itertext()).split()) for e in bibl.xpath(path) if "".join(e.itertext()).strip()]

    result = {"scope": "source-volume"}
    for key, path in {
        "title": "./*[local-name()='titleStmt']/*[local-name()='title']",
        "editors": "./*[local-name()='titleStmt']/*[local-name()='editor']",
        "publisher": "./*[local-name()='publicationStmt']/*[local-name()='publisher']",
        "place": "./*[local-name()='publicationStmt']/*[local-name()='pubPlace']",
        "date": "./*[local-name()='publicationStmt']/*[local-name()='date']",
    }.items():
        found = values(path)
        if found:
            result[key] = found
    return result if len(result) > 1 else {}


def edition_information(root: Path, acceptance: dict, bindings: dict, cache: dict) -> dict:
    """Reuse exact accepted sources; cache shared volumes within this generation."""
    source = acceptance.get("source", {})
    result = {}
    manifest = source.get("source_manifest", {})
    if manifest.get("path"):
        name = manifest["path"]
        content = read_input_bytes(root / name)
        if hashlib.sha256(content).hexdigest() != bindings.get(name, manifest.get("sha256")):
            raise PipelineError("catalog acquisition metadata changed")
        acquired = json.loads(content)
        result["digital_source"] = {key: acquired[key] for key in ("provider", "url") if acquired.get(key)}
        if _scan(result["digital_source"], "digital source"):
            result.pop("digital_source")
    path = source.get("source_path")
    if path and Path(path).suffix.lower() in (".xml", ".tei"):
        key = (path, source["source_sha256"])
        if key not in cache:
            content = read_input_bytes(root / path)
            if hashlib.sha256(content).hexdigest() != key[1]:
                raise PipelineError(f"catalog primary source changed: {path}")
            header = source_header(content)
            contributors = []
            for role, name in re.findall(r'<DC.Contributor\b[^>]*sub="([^"]+)"[^>]*>(.*?)</DC.Contributor>', header, re.S):
                if plain(name):
                    contributors.append({"name": plain(name), "role": role})
            cache[key] = {"publication": publication_from_header(content), "source_credits": contributors}
        result.update({key: value for key, value in cache[key].items() if value})
    if acceptance.get("identity", {}).get("work_id") == "baxter-saints-rest":
        # Its title page supplies no date; CCEL's 184? is a catalog estimate.
        result["publication"] = {"scope": "edition", "statement": "New York: American Tract Society, undated",
                                 "place": ["New York"], "publisher": ["American Tract Society"],
                                 "edition_statement": "Abridged by Benjamin Fawcett",
                                 "source_date_statement": "184?"}
    if acceptance.get("identity", {}).get("work_id") == "baxter-reformed-pastor":
        result.setdefault("publication", {"scope": "edition"})["edition_statement"] = "William Brown's revision and abridgment"
    return result


def publication_text(publication: dict) -> str:
    if publication.get("statement"):
        details = ". ".join(v for v in (publication.get("edition_statement"), publication["statement"]) if v)
    else:
        imprint = ": ".join(v for v in ("; ".join(publication.get("place", [])),
                                         "; ".join(publication.get("publisher", []))) if v)
        details = ", ".join(v for v in (imprint, "; ".join(publication.get("date", []))) if v)
        details = ". ".join(v for v in (publication.get("edition_statement"), details) if v)
    return re.sub(r",\s*,+", ",", re.sub(r"\s*[:;](?:\s*:)+\s*", ": ", details))


def publication_from_notice(text: str, *, containing: bool) -> dict:
    """Carry explicit existing imprint statements, without guessing their fields."""
    match = re.search(r"^(?:Printed source|Print edition|Historical edition|Retained print/reprint statements):\s*(.+)$", text, re.M)
    if not match:
        return {}
    statement = re.split(r"\s+(?:This derivative|A later reprint|This release|The selected text)\b", match[1], maxsplit=1)[0].strip()
    return {"scope": "source-volume" if containing else "edition", "statement": statement}


_PROCESS_STARTS = (
    "Human acceptance,", "Human/print review,", "Human review,", "Publication status:",
    "No public row license is assigned here.", "This private preparation reuses", "Current actual-master projection,",
    "This current provider-based disposition supersedes", "This item-specific disposition supersedes",
    "Exact retained source and master bindings", "Existing named and unnamed contributor roles",
    "Current actual-master projection", "Technical acceptance and", "Existing mechanical source checking",
    "No independently established worldwide", "The supported scope is the retained",
)
_PROCESS_SENTENCE = re.compile(
    r"(?:human acceptance|publication authorization|public deployment|public upload remains|"
    r"final (?:global selection|rights disposition|projected-byte checks)|"
    r"independently (?:certified|confirmed|verified|established)|"
    r"(?:does not|do not) establish (?:human acceptance|print collation|publication)|"
    r"does not establish independent rights clearance|human textual acceptance|"
    r"private offline preparation|private offline assembly|existing local configuration|"
    r"public upload|public publication|authorization for publication|does not authorize publication|"
    r"private release makes no claim|private offline release does not authorize|"
    r"no independent print collation|not independent (?:worldwide )?rights clearance|"
    r"legacy configuration|historical config|no contributor or print imprint is invented|"
    r"(?:JSON|source|acquisition).{0,60}has no (?:individual|independent|verified).{0,90}(?:translator|publisher|imprint)|"
    r"supplies no verified (?:contributor allocation|imprint)|"
    r"(?:transcriber|markup|digitizer|electronic.source|print.publication).*fields are empty|"
    r"no (?:named )?(?:translator|transcriber|digitizer) is (?:identified|recorded)|"
    r"(?:no|not a|no blanket) CC0|uncertain printing year remains uncertain|"
    r"print.edition collation has not|No print copy has been collated|"
    r"earlier preliminary statement|rights clearance.*remain)", re.I)


def reader_paragraphs(text: str) -> tuple[dict[str, list[str]], list[dict]]:
    """Keep source facts and conditions; remove identified internal status prose."""
    sections = {"Credits": [], "Reuse": [], "Notes about this copy": [], "License text": []}
    audit = []
    blocks = re.split(r"(^```[^\n]*\n.*?^```\s*$|^~~~[^\n]*\n.*?^~~~\s*$)", text, flags=re.M | re.S)
    for block in blocks:
        if block.startswith(("```", "~~~")):
            sections["License text"].append(block.strip())
            audit.append({"action": "verbatim-license", "sha256": hashlib.sha256(block.encode()).hexdigest()})
            continue
        # Extract unfenced licenses only after complete fenced blocks are removed.
        full = re.search(r"^(?:START: FULL LICENSE|THE FULL PROJECT GUTENBERG|GNU GENERAL PUBLIC LICENSE|Permission is hereby granted, free of charge)", block, re.M)
        if full:
            following_heading = re.search(r"^#{1,6}\s", block[full.end():], re.M)
            end = full.end() + following_heading.start() if following_heading else len(block)
            literal = block[full.start():end].strip()
            sections["License text"].append(literal)
            audit.append({"action": "verbatim-license", "sha256": hashlib.sha256(literal.encode()).hexdigest()})
            block = block[:full.start()] + "\n\n" + block[end:]
        for paragraph in re.split(r"\n\s*\n", block):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            if paragraph.startswith("#"):
                audit.append({"action": "replace-heading", "text": paragraph})
                continue
            if paragraph.startswith(_PROCESS_STARTS):
                audit.append({"action": "remove-process-status", "text": paragraph})
                continue
            if paragraph.startswith("|") and "\n" in paragraph:
                sections["Credits"].append(paragraph)
                audit.append({"action": "preserve", "section": "Credits", "text": paragraph})
                continue
            paragraph = paragraph.replace("The private offline text selection", "This edition")
            paragraph = paragraph.replace("This private offline snapshot represents", "This edition contains")
            paragraph = paragraph.replace("This private offline dataset is sourced from", "Digital source:")
            paragraph = paragraph.replace("This private offline release", "This release")
            paragraph = paragraph.replace("by a source-bound reversible transform", "when preparing the downloads")
            paragraph = paragraph.replace("does not automatically establish rights clearance for underlying Bible translations", "does not cover the underlying Bible translations")
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", " ".join(paragraph.split()))
            kept = []
            for sentence in sentences:
                if _PROCESS_SENTENCE.search(sentence):
                    audit.append({"action": "remove-process-sentence", "text": sentence})
                else:
                    kept.append(sentence)
            if not kept:
                continue
            paragraph = " ".join(kept)
            paragraph = re.sub(r"\bretained\s+", "", paragraph, flags=re.I)
            paragraph = re.sub(r"\b(?:accepted )?electronic witness(?:'s)?\b", "digital text", paragraph, flags=re.I)
            paragraph = re.sub(r"\bwitness\b", "copy", paragraph, flags=re.I)
            paragraph = paragraph.replace("Public row license:", "Reuse terms:").replace("Row license:", "Reuse terms:")
            paragraph = paragraph.replace("This private offline dataset is sourced from", "Digital source:")
            paragraph = paragraph.replace("accepted TEI", "structured text").replace("source-defined text rows", "records")
            if paragraph in READING_COPY["paragraphs"]:
                replacement = READING_COPY["paragraphs"][paragraph]
                audit.append({"action": "edit-public-copy", "before": paragraph, "after": replacement})
                paragraph = replacement
                if not paragraph:
                    continue
            if re.search(r"licen[cs]e|copyright|permission|do not sell|public.domain|Creative Commons|Gutenberg.*terms", paragraph, re.I):
                section = "Reuse"
            elif re.search(r"credit|acknowledg|translat|transcrib|markup|digitiz|editor|author", paragraph, re.I):
                section = "Credits"
            else:
                section = "Notes about this copy"
            sections[section].append(paragraph)
            audit.append({"action": "preserve", "section": section, "text": paragraph})
    return sections, audit


def compact_source_sections(row: dict, sections: dict) -> dict:
    """Shared provider notices state the actual grant and credit once per copy."""
    provider = row.get("digital_source", {}).get("provider", "").casefold()
    literal = sections["License text"]
    material_notes = []
    for paragraph in sections["Notes about this copy"] + sections["Credits"]:
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", paragraph):
            if (re.search(r"\b(?:omits|omissions|missing (?:text|pages|chapters|verses)|fragment|excerpt|not (?:present|included))\b", sentence, re.I)
                    and not _PROCESS_SENTENCE.search(sentence) and sentence not in material_notes):
                material_notes.append(sentence)
    material_notes = ["Includes the five theological tracts. The companion Consolation of Philosophy is not included."
                      if "Where applicable to Boethius" in sentence else sentence for sentence in material_notes]
    material_notes = [replacement for sentence in material_notes
                      if (replacement := READING_COPY["paragraphs"].get(sentence, sentence))]
    if row["work_id"] == "baxter-saints-rest":
        material_notes = []  # The edition statement already identifies the abridgment.
    if "openmgh" in provider or "monumenta germaniae" in provider:
        return {"Credits": ["Digital text and annotations: Monumenta Germaniae Historica (MGH) and the Bavarian State Library, Munich (BSB). The digital MGH project was funded by the German Research Foundation (DFG)."],
                "Reuse": ["Credit MGH and BSB when sharing the annotated text. [CC BY 4.0 terms](https://creativecommons.org/licenses/by/4.0/). Open Christian Data converted the source into structured text."],
                "Notes about this copy": material_notes, "License text": literal}
    if "creeds.json" in provider and row["license"].casefold() == "unlicense":
        return {"Credits": ["Please credit [NonlinearFruit / Creeds.json](https://github.com/NonlinearFruit/Creeds.json) and link to the source repository."],
                "Reuse": ["[Unlicense](https://unlicense.org/): you may copy, modify, redistribute, and use this text commercially. The source attribution is “Public Domain.”"],
                "Notes about this copy": material_notes, "License text": literal}
    if "christian classics ethereal" in provider or provider == "ccel":
        credits = [f"{c['name']} ({c['role'].lower()})" for c in row.get("source_credits", [])]
        return {"Credits": (["; ".join(credits) + "."] if credits else []) + ["Please credit [CCEL.org](https://www.ccel.org/) for making the digital text available."],
                "Reuse": ["Do not sell CCEL files or derivatives of their formatting. [CCEL policy](https://ccel.org/about/copyright.html) · [Permission record](https://github.com/OpenChristianData/open-christian-data/blob/main/docs/sources/ccel-permission.md)."],
                "Notes about this copy": material_notes, "License text": literal}
    if "hymnary" in provider:
        return {"Credits": ["[Hymnary.org](https://hymnary.org) at Calvin University supplied the collection. Please link to Hymnary.org when using it. Application developers are encouraged to [tell Hymnary about their projects](https://hymnary.org/contact)."],
                "Reuse": ["Hymnary designated this supplied collection as public domain. This designation applies to the supplied hymn texts; other Hymnary website resources, tunes, and images have their own terms."],
                "Notes about this copy": ["The collection contains 34,895 supplied records, selected as the oldest known public-domain hymnal instance of each text. Seven unusual quotation-mark sequences follow the source. Fifteen control characters are shown with labeled placeholders."],
                "License text": literal}
    return sections


def readable_notices(root: Path, release: Path, selection: dict, records: list[dict]) -> tuple[str, list[dict]]:
    from build.tools.prepare_hf_publication_docs import BAXTER_CLAUSE, BAXTER_MARKER, BAXTER_WORKS, source_notices
    from build.tools.release_catalog import display_credit, edition_display, terms_display

    indexed = {(r["work_id"], r["edition_id"]): r for r in records}
    result = ["# Sources, credits, and reuse terms", ""]
    audit, literal = [], {}
    for item in selection["items"]:
        if "exclude_reason" in item:
            continue
        accepted = json.loads(read_input_bytes(root / item["acceptance_path"]))
        row = indexed[(item["work_id"], accepted["identity"]["edition_id"])]
        result += [f"## {row['title']}", ""]
        description = publication_text(row.get("publication", {})) or edition_display(row["edition_title"])
        publication = row.get("publication", {})
        if publication.get("scope") == "source-volume":
            description = ". ".join(value for value in (
                "In " + "; ".join(publication["title"]) if publication.get("title") else "",
                "Edited by " + "; ".join(publication["editors"]) if publication.get("editors") else "",
                description) if value)
        if row.get("publication") or re.search(r"\b(?:\d{4}|abridged|revision|revised|translation|volumes?)\b", row["edition_title"], re.I):
            result += [f"**Text and edition.** {description.rstrip('.') }.", ""]
        source = row.get("digital_source", {})
        if source.get("provider"):
            provider = edition_display(source["provider"])
            result += [f"**Digital source.** " + (f"[{provider}]({source['url']})" if source.get("url", "").startswith(("http:", "https:")) else provider) + ".", ""]
        credits = "; ".join(map(display_credit, row["creators"]))
        sections = {"Credits": [], "Reuse": [], "Notes about this copy": [], "License text": []}
        for notice in item.get("public_notices", []):
            raw = read_input_bytes(root / notice["notice_path"])
            text = raw.decode("utf-8")
            previous = text
            if item["work_id"] in BAXTER_WORKS and BAXTER_CLAUSE not in text:
                previous = text.replace(BAXTER_MARKER, BAXTER_CLAUSE + BAXTER_MARKER)
            if hashlib.sha256(previous.encode()).hexdigest() != notice["notice_sha256"]:
                raise PipelineError(f"source notice changed: {notice['notice_path']}")
            cleaned, decisions = reader_paragraphs(text)
            for key, paragraphs in cleaned.items():
                sections[key].extend(p for p in paragraphs if p not in sections[key])
            audit.append({"item_id": item["item_id"], "notice": notice["notice_path"], "decisions": decisions})
        sections = compact_source_sections(row, sections)
        if credits:
            sections["Credits"].insert(0, credits + ".")
        # The selected term is the current disposition, rather than preliminary prose.
        terms = terms_display(row['license'])
        if row['license'] == "Public domain (United States); identified historical text and apparatus only":
            terms = "Historical text and editorial material are public domain in the United States"
        sections["Reuse"].insert(0, terms.rstrip('.') + ".")
        for section in ("Credits", "Reuse", "Notes about this copy"):
            if sections[section]:
                result += [f"**{section}.** " + "\n\n".join(sections[section]), ""]
        if sections["License text"]:
            links = []
            for block in sections["License text"]:
                digest = hashlib.sha256(block.encode()).hexdigest()[:20]
                literal[digest] = block
                links.append(f"[License text](#license-{digest})")
            result += [" · ".join(links), ""]
    for key, block in sorted(literal.items()):
        result += [f"## License {key}", "", block, ""]
    text = "\n".join(result)
    # Reuse the existing public-link fixes without editorial changes to literals.
    text = source_notices("## Source notices\n\n" + text).split("\n", 2)[2]
    if _scan(text, "readable source notices"):
        raise PipelineError("readable source notices violate the public boundary")
    return text, audit
