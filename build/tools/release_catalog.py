"""Render the selected release's catalog from its bound, curated work records."""
from __future__ import annotations

import csv
from collections import Counter
import html
import io
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from ocd_kernel.library._common import PipelineError, canonical_bytes, inspection_read_phase, read_input_bytes, sha256_file
from ocd_kernel.library.identities import validate_record
from ocd_kernel.library.labels import work_labels
from ocd_kernel.release.public_allowlist import _scan

CATALOG_FILES = {"WORK_CATALOG.md", "WORK_CATALOG.csv", "WORK_CATALOG.mods.xml"}
MODS = "http://www.loc.gov/mods/v3"


def selected_records(root: Path, release: Path, selection: dict) -> list[dict]:
    """Join only included edition identities; fail if owning descriptions drifted."""
    with inspection_read_phase():
        return _selected_records(root, release, selection)


def _selected_records(root: Path, release: Path, selection: dict) -> list[dict]:
    import hashlib

    report = json.loads(read_input_bytes(release / "internal/release-report.json"))
    build = json.loads(read_input_bytes(release / "internal/build-manifest.json"))
    digest = hashlib.sha256(canonical_bytes(selection)).hexdigest()
    if report.get("status") != "pass" or any(r.get("selection_sha256") != digest for r in (report, build)):
        raise PipelineError("catalog requires the exact passing release selection")
    included = {r["item_id"]: r for r in report["items"] if r["status"] in ("included", "warned")}
    requested = {r["item_id"]: r for r in selection["items"] if "exclude_reason" not in r}
    if (not included or len({r['item_id'] for r in selection['items']}) != len(selection['items'])
            or len({r['item_id'] for r in report['items']}) != len(report['items'])
            or set(included) != set(requested)):
        raise PipelineError("catalog selection/report identities differ")
    counts = Counter()
    for row in included.values():
        counts[row["category"]] += row["row_count"]
    if dict(counts) != {r["category"]: r["row_count"] for r in report["configurations"]}:
        raise PipelineError("catalog item counts differ from published configuration totals")
    bindings = {r["work_id"]: {f["path"]: f["sha256"] for f in r["files"]}
                for r in build["inputs"]["work_bindings"]}
    item_bindings = {r["item_id"]: {f["path"]: f["sha256"] for f in r["files"]}
                     for r in build["inputs"]["item_bindings"]}
    profile_path = "schemas/v2/metadata-labels.json"
    profile_digest = next((r["sha256"] for r in build["inputs"]["shared"] if r["path"] == profile_path), None)
    if profile_digest is None or sha256_file(root / profile_path) != profile_digest:
        raise PipelineError("catalog label profile differs from the release")
    vocabulary = validate_record("metadata-labels", json.loads(read_input_bytes(root / profile_path)))
    works, result, identities, source_headers = {}, [], set(), {}
    for item_id, item in sorted(requested.items()):
        work_id = item["work_id"]
        if work_id not in works:
            relative = f"library/works/{work_id}/work.json"
            raw = read_input_bytes(root / relative)
            if hashlib.sha256(raw).hexdigest() != bindings.get(work_id, {}).get(relative):
                raise PipelineError(f"catalog work metadata differs from release: {work_id}")
            work = validate_record("work", json.loads(raw), context=relative)
            works[work_id] = work_labels(work, vocabulary)
        work = works[work_id]
        entry = included[item_id]
        acceptance_bytes = read_input_bytes(root / item["acceptance_path"])
        acceptance_sha = hashlib.sha256(acceptance_bytes).hexdigest()
        if acceptance_sha != item_bindings.get(item_id, {}).get(item["acceptance_path"]):
            raise PipelineError(f"catalog acceptance differs from release: {item_id}")
        accepted = json.loads(acceptance_bytes)["identity"]
        identity = {key: accepted[key] for key in ("work_id", "textual_form_id", "edition_id")}
        if identity["work_id"] != work_id or identity["edition_id"] + "--" + work_id in identities:
            raise PipelineError("catalog has a conflicting or duplicate edition identity")
        identities.add(identity["edition_id"] + "--" + work_id)
        edition = next((e for e in work["editions"] if e["edition_id"] == identity["edition_id"]
                        and e["textual_form_id"] == identity["textual_form_id"]), None)
        # The verified report counts published rows, after source-specific filtering.
        if edition is None or item["category"] != entry["category"]:
            raise PipelineError(f"catalog edition/count/category differs: {item_id}")
        credits = []
        for creator in work["creators"]:
            scope = creator["scope"]
            # A translator/editor of another edition must not become this copy's credit.
            if scope and scope["kind"] in ("edition", "textual-form", "textual_form"):
                if scope["id"] not in (identity["edition_id"], identity["textual_form_id"]):
                    continue
            credits.append({k: creator[k] for k in ("name", "role", "scope")})
        from build.tools.release_information import edition_information

        description = edition_information(root, json.loads(acceptance_bytes), item_bindings[item_id], source_headers)
        known_publication = description.get("publication", {})
        if not any(known_publication.get(key) for key in ("statement", "publisher", "date")):
            from build.tools.release_information import publication_from_notice

            for notice in item.get("public_notices", []):
                content = read_input_bytes(root / notice["notice_path"])
                previous = content
                if work_id.startswith("baxter-"):
                    from build.tools.prepare_hf_publication_docs import BAXTER_CLAUSE, BAXTER_MARKER, BAXTER_WORKS

                    if work_id in BAXTER_WORKS and BAXTER_CLAUSE.encode() not in content:
                        previous = content.replace(BAXTER_MARKER.encode(), (BAXTER_CLAUSE + BAXTER_MARKER).encode())
                if hashlib.sha256(previous).hexdigest() != notice["notice_sha256"]:
                    raise PipelineError(f"catalog publication notice changed: {notice['notice_path']}")
                publication = publication_from_notice(content.decode("utf-8"), containing=bool(edition["containing_source"]))
                if publication:
                    description["publication"] = {**publication, **known_publication}
                    break
        result.append({"work_id": work_id, "title": work["description"]["title"],
                       "textual_form_id": identity["textual_form_id"], "edition_id": identity["edition_id"],
                       "edition_title": edition["title"], "form_title": edition["form_title"],
                       "containing_source": {"title": edition["containing_source"]["title"]}
                                            if edition["containing_source"] else None, "creators": credits,
                       "language": edition["language"]["value"] or edition["language"]["raw"],
                       "category": item["category"], "records": entry["row_count"], "license": item["license"], **description})
    errors = _scan(result, "release catalog")
    if errors:
        raise PipelineError("; ".join(errors))
    return sorted(result, key=lambda r: (r["category"], r["title"].casefold(), r["work_id"], r["edition_id"]))


def credit_text(creator: dict) -> str:
    role = creator["role"]["raw"] or creator["role"]["value"] or "role unspecified"
    scope = creator["scope"]
    detail = f"; {scope['kind']}: {scope['id']}" if scope and scope["kind"] != "work" else ""
    return f"{creator['name']} ({role}{detail})"


def _md(value: str) -> str:
    return html.escape(value, quote=False).replace("|", "\\|").replace("\n", " ")


def edition_display(title: str) -> str:
    """Remove storage vocabulary from display; CSV/MODS preserve the exact label."""
    title = re.sub(r"\s*\(per retained ASV config\)", "", title)
    title = re.sub(r"\b(?:retained|pinned)\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:ThML|JSON|XML|USFM|HTML)(?:\s+ZIP)?\s+(?:electronic\s+)?witness\b",
                   "digital text", title)
    title = re.sub(r"\b(?:electronic(?: text)?|digital) witness\b", "digital text", title, flags=re.IGNORECASE)
    title = re.sub(r"\bwitnesses\b", "copies", title, flags=re.IGNORECASE)
    return re.sub(r"\bwitness\b", "copy", title, flags=re.IGNORECASE).strip()


def display_credit(creator: dict) -> str:
    role = creator["role"]["raw"] or creator["role"]["value"] or "contributor"
    scope = creator["scope"]
    if scope and scope["kind"] in ("component", "series"):
        return f"{creator['name']} ({role}, {scope['kind']}: {scope['id']})"
    return creator["name"] if role.casefold() == "author" else f"{creator['name']} ({role})"


def terms_display(terms: str) -> str:
    from build.tools.release_information import READING_COPY

    if terms in READING_COPY["terms"]:
        return READING_COPY["terms"][terms]
    # Only exact simple labels are expanded; qualified terms remain verbatim.
    return {"unlicense": "Public-domain dedication (Unlicense)",
            "cc0-1.0": "Public-domain dedication (CC0 1.0)",
            "public-domain": "Public domain", "public domain": "Public domain",
            "public domain (united states); identified historical text and apparatus only":
                "Historical text and editorial material: public domain in the United States"}.get(terms.casefold(), terms)


def render_catalog(records: list[dict]) -> dict[str, bytes]:
    """Display a bibliography; preserve exact labels and IDs in CSV/MODS records."""
    works = len({r["work_id"] for r in records})
    lines = ["# Collection catalogue — Open Christian Data v1.0.0", "",
             f"**{works:,} works · {len(records):,} selected editions · {sum(r['records'] for r in records):,} records**", "",
             "Every work and copy included in this release is listed below. A work can be a collection; "
             "its individual sermons, hymns, or letters are not necessarily separate catalog entries.", "",
             "[Download the edition list (CSV)](WORK_CATALOG.csv) · "
             "[MODS bibliography (XML)](WORK_CATALOG.mods.xml) · [Catalog fields and limits](CATALOG_GUIDE.md)", "",
             "Browse by title within each download group. Authors and other contributors are listed where "
             "known, with publication details and links to the digital sources. "
             "The CSV and XML downloads preserve the full recorded descriptions and identifiers.", "",
             "## Download groups", "", "| Group | Works | Editions | Records |", "|---|---:|---:|---:|"]
    categories = sorted({r["category"] for r in records})
    for category in categories:
        rows = [r for r in records if r["category"] == category]
        lines.append(f"| [{category}](#{category.replace('_', '-')}) | {len({r['work_id'] for r in rows}):,} | "
                     f"{len(rows):,} | {sum(r['records'] for r in rows):,} |")
    for category in categories:
        lines += ["", f"## {category.replace('_', ' ').capitalize()}", "",
                  f"[JSONL](data/{category}/train.jsonl) · [Arrow](data/{category}/train.arrow)", ""]
        previous = None
        for row in (r for r in records if r["category"] == category):
            if row["work_id"] != previous:
                lines += [f"### {_md(row['title'])}", ""]
                previous = row["work_id"]
            if row["creators"]:
                lines += [_md('; '.join(map(display_credit, row['creators']))) + ".", ""]
            language = {"en": "English", "la": "Latin", "grc": "Ancient Greek", "syc": "Classical Syriac",
                        "pt": "Portuguese", "nl": "Dutch", "mul": "Multiple languages"}.get(row["language"], row["language"])
            if not row.get("publication") and re.search(r"\b(?:\d{4}|abridged|revision|revised|translation|volumes?)\b", row["edition_title"], re.I):
                lines.append(f"- **Edition:** {_md(edition_display(row['edition_title']))}")
            lines.append(f"- **Language:** {_md(language)}")
            if row.get("publication"):
                from build.tools.release_information import publication_text

                lines.append(f"- **Publication:** {_md(publication_text(row['publication']))}")
                if row["publication"].get("editors"):
                    lines.append(f"- **Source volume editors:** {_md('; '.join(row['publication']['editors']))}")
            if row.get("digital_source"):
                source = row["digital_source"]
                provider = _md(edition_display(source.get("provider", "Source")))
                lines.append(f"- **Digital source:** " + (f"[{provider}]({source['url']})" if source.get("url", "").startswith(("http:", "https:")) else provider))
            if row["containing_source"]:
                lines.append(f"- **Appears in:** {_md(row['containing_source']['title'])}")
            lines += [f"- **Reuse:** {_md(terms_display(row['license']))}. [Full terms and source credits](HUGGINGFACE_SOURCE_NOTICES.md).",
                      f"- **Dataset IDs:** `work_id={row['work_id']}`; `edition_id={row['edition_id']}` "
                      f"({row['records']:,} {'record' if row['records'] == 1 else 'records'}).", ""]
    table = io.StringIO(newline="")
    fields = ["work_id", "title", "textual_form_id", "edition_id", "edition_title", "form_title",
              "containing_source", "creators", "language", "category", "records", "license", "publication", "digital_source", "source_credits"]
    writer = csv.DictWriter(table, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in records:
        writer.writerow({k: json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v
                         for k, v in row.items()})
    ET.register_namespace("mods", MODS)
    collection = ET.Element(f"{{{MODS}}}modsCollection")

    def add(parent, tag, text=None, **attributes):
        element = ET.SubElement(parent, f"{{{MODS}}}{tag}", attributes)
        element.text = text
        return element

    for row in records:
        record = add(collection, "mods", version="3.8")
        add(add(record, "titleInfo"), "title", row["title"])
        for creator in row["creators"]:
            if creator["name"].casefold() in ("anonymous", "unknown"):
                add(record, "note", credit_text(creator), type="statement of responsibility")
                continue
            name = add(record, "name")
            add(name, "namePart", creator["name"])
            role = add(name, "role")
            if creator["role"]["value"]:
                add(role, "roleTerm", creator["role"]["value"], type="code", authority="marcrelator")
            else:
                add(role, "roleTerm", creator["role"]["raw"] or "role unspecified", type="text")
            if creator["scope"]:
                add(name, "description", f"Responsibility scope: {creator['scope']['kind']}: {creator['scope']['id']}")
        add(record, "typeOfResource", "text")
        add(record, "note", row["edition_title"], type="edition description")
        add(record, "note", row["language"], type="supplied language label")
        add(record, "note", f"Download group: {row['category']}; {row['records']} records.")
        host = None
        if row["containing_source"]:
            host = add(record, "relatedItem", type="host")
            add(add(host, "titleInfo"), "title", row["containing_source"]["title"])
        if row.get("publication"):
            from build.tools.release_information import publication_text

            publication = row["publication"]
            target = record
            if publication.get("scope") == "source-volume":
                target = host if host is not None else add(record, "relatedItem", type="host")
                if host is None and publication.get("title"):
                    add(add(target, "titleInfo"), "title", "; ".join(publication["title"]))
            if any(publication.get(key) for key in ("place", "publisher", "date")):
                origin = add(target, "originInfo")
                for value in publication.get("place", []):
                    add(add(origin, "place"), "placeTerm", value, type="text")
                for value in publication.get("publisher", []):
                    add(origin, "publisher", value)
                for value in publication.get("date", []):
                    add(origin, "dateIssued", value)
            add(target, "note", publication_text(publication), type="source publication")
            for editor in publication.get("editors", []):
                name = add(target, "name")
                add(name, "namePart", editor)
                add(add(name, "role"), "roleTerm", "edt", type="code", authority="marcrelator")
        if row.get("digital_source", {}).get("url", "").startswith(("https:", "http:")):
            add(add(record, "location"), "url", row["digital_source"]["url"], displayLabel="Digital source")
        if row.get("digital_source", {}).get("provider"):
            add(record, "note", row["digital_source"]["provider"], type="digital source")
        if row.get("source_credits"):
            add(record, "note", "; ".join(f"{c['name']} ({c['role']})" for c in row["source_credits"]), type="source credits")
        for key in ("work_id", "textual_form_id", "edition_id"):
            add(record, "identifier", row[key], type=f"ocd-{key.replace('_', '-')}")
        add(add(record, "location"), "url",
            f"https://huggingface.co/datasets/OpenChristianDataOrg/open-christian-data/resolve/v1.0.0/data/{row['category']}/train.jsonl")
        add(record, "accessCondition", row["license"], type="use and reproduction")
    ET.indent(collection)
    return {"WORK_CATALOG.md": ("\n".join(lines) + "\n").encode("utf-8"),
            "WORK_CATALOG.csv": table.getvalue().encode("utf-8"),
            "WORK_CATALOG.mods.xml": ET.tostring(collection, encoding="utf-8", xml_declaration=True) + b"\n"}


def catalog_documents(root: Path, release: Path, selection: dict) -> dict[str, bytes]:
    return render_catalog(selected_records(root, release, selection))
