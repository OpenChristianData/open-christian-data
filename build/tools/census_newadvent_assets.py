"""Inventory source-located New Advent images without fetching site navigation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from lxml import html

from build.tools.acquire_newadvent_envelope import verified_members
from build.tools.retain_newadvent_sources import checked_url, retain


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".tif", ".tiff"}


def inventory(cohorts: list[Path]) -> dict:
    occurrences = []
    selected = {}
    stylesheets = {}
    stylesheet_occurrences = []
    sources = []
    for cohort in cohorts:
        for url, member in verified_members(cohort).items():
            path = cohort / member["path"]
            payload = path.read_bytes()
            document = html.document_fromstring(payload.decode("utf-8"))
            for link in document.xpath("//link[@href]"):
                if "stylesheet" in link.get("rel", "").lower().split():
                    target = urljoin(url, link.get("href"))
                    disposition = "requires-stylesheet-route-review"
                    try:
                        checked_url(target, allow_stylesheets=True)
                    except ValueError:
                        pass
                    else:
                        if urlsplit(target).path.startswith("/utility/"):
                            disposition = "retain-source-stylesheet"
                            stylesheets.setdefault(target, None)
                    stylesheet_occurrences.append({"source_url": url, "source_xpath": link.getroottree().getpath(link), "raw": link.get("href"), "resolved_url": target, "disposition": disposition})
            sources.append({"url": url, "path": str(path.resolve()), "sha256": member["sha256"]})
            for element in document.iter():
                if not isinstance(element.tag, str):
                    continue
                meaningful_region = any(parent.get("id") in {"springfield2", "ogdenville"} for parent in [element, *element.iterancestors()])
                references = []
                if element.tag == "img" and element.get("src") is not None:
                    references.append(("src", element.get("src"), "embedded-image"))
                if element.tag == "a" and element.get("href") and Path(urlsplit(element.get("href")).path).suffix.lower() in IMAGE_SUFFIXES:
                    references.append(("href", element.get("href"), "linked-image"))
                if element.get("srcset"):
                    # Keep this branch explicit until actual source syntax is
                    # inventoried; a naive comma split would corrupt data URLs.
                    references.append(("srcset", element.get("srcset"), "unparsed-image-set"))
                for match in re.finditer(r"url\((.*?)\)", element.get("style", ""), flags=re.IGNORECASE):
                    references.append(("style", match.group(1).strip().strip("\"'"), "css-image"))
                for attribute, raw, kind in references:
                    target = urljoin(url, raw)
                    disposition = "excluded-site-navigation-image"
                    if meaningful_region:
                        disposition = "requires-image-route-review"
                        if kind != "unparsed-image-set":
                            try:
                                checked_url(target, allow_images=True)
                            except ValueError:
                                pass
                            else:
                                if urlsplit(target).path.startswith("/images/"):
                                    disposition = "retain-source-image"
                                    selected.setdefault(target, None)
                    occurrences.append({"source_url": url, "source_xpath": element.getroottree().getpath(element), "source_attribute": attribute, "raw": raw, "resolved_url": target, "kind": kind, "disposition": disposition})
    return {"contract": "ocd-newadvent-image-census-v1", "source_members": sources, "occurrences": occurrences, "image_urls": list(selected), "stylesheet_urls": list(stylesheets), "stylesheet_occurrences": stylesheet_occurrences, "unresolved": [item for item in [*occurrences, *stylesheet_occurrences] if item["disposition"].startswith("requires-")], "scope": "main-and-publisher-footer-image-references and source stylesheets; navigation images explicitly excluded", "work_completeness_established": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, action="append", required=True)
    parser.add_argument("--acquisition-run", type=Path, help="Include completed immutable article cohorts")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--destination", type=Path, help="Explicit new image acquisition destination; omit for census only")
    args = parser.parse_args()
    if args.acquisition_run:
        args.cohort.extend(path for path in sorted(args.acquisition_run.glob("batch-[0-9][0-9][0-9][0-9]")) if (path / "acquisition.json").is_file())
    record = inventory(args.cohort)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    outcome = None
    if args.destination and record["image_urls"]:
        outcome = retain(record["image_urls"], args.destination, allow_images=True)
    print(json.dumps({"source_members": len(record["source_members"]), "image_urls": len(record["image_urls"]), "unresolved_occurrences": len(record["unresolved"]), "acquisition_status": outcome["status"] if outcome else "not-requested"}))
    return 1 if outcome and outcome["status"] != "declared-urls-retained" else 0


if __name__ == "__main__":
    raise SystemExit(main())
