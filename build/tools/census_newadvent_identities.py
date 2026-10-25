"""Inventory literal page titles and citation fields without adopting metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from build.tei.newadvent_source_tree import parse_source
from build.tools.acquire_newadvent_envelope import verified_members
from build.tools.census_newadvent_sources import INDEX


FIELDS = ("mlaauthor", "mlaarticle", "mlawork", "mlavolume", "mlapublisher", "mlayear", "transcriber", "dedication", "nihil", "imprimatur", "contactus")


def inventory(cohorts: list[Path]) -> dict:
    pages = []
    seen = set()
    volumes = Counter()
    classes = Counter()
    readable_tags = Counter()
    presentation_values = {}
    for cohort in cohorts:
        for url, member in verified_members(cohort).items():
            if url in seen:
                raise ValueError("Duplicate retained page requires witness selection")
            seen.add(url)
            path = cohort / member["path"]
            payload = path.read_bytes()
            tree = parse_source(payload.decode("utf-8"), treebuilder="etree")
            nodes = list(tree.iter())
            regions = [node for node in nodes if node.get("id") in {"springfield2", "ogdenville"}]
            readable = {node for region in regions for node in region.iter() if isinstance(node.tag, str)}
            page_tags = Counter(node.tag for node in readable)
            readable_tags.update(page_tags)
            for node in readable:
                for name in ("color", "size", "lang", "class", "style"):
                    if name in node.attrib:
                        key = node.tag + "@" + name
                        presentation_values.setdefault(key, Counter())[node.get(name)] += 1
            fields = {name: [{"source_address": node.getroottree().getpath(node), "text": "".join(node.itertext())} for node in nodes if node.get("id") == name] for name in FIELDS}
            kind = "index-or-preface-page" if INDEX.fullmatch(urlsplit(url).path) else "article-shaped-page-with-citation" if fields["mlawork"] else "article-shaped-page-without-citation"
            classes[kind] += 1
            volumes.update(item["text"] for item in fields["mlavolume"])
            pages.append({"url": url, "path": str(path.resolve()), "sha256": member["sha256"], "bytes": member["bytes"], "source_shape": kind, "readable_region_count": len(regions), "readable_element_counts": dict(sorted(page_tags.items())), "h1_occurrences": [{"source_address": node.getroottree().getpath(node), "text": "".join(node.itertext())} for node in nodes if node.tag == "h1"], "citation_field_occurrences": fields, "duplicate_field_ids": [name for name, values in fields.items() if len(values) > 1]})
    return {"contract": "ocd-newadvent-literal-identity-census-v1", "scope": "literal retained page headings/citation spans plus readable-region tag and presentation-attribute census; not metadata adoption or original-volume reconciliation", "source_address_syntax": "percent-encoded HTML name and same-kind sibling ordinal; not XPath", "source_pages": pages, "source_shape_counts": dict(classes), "readable_element_counts": dict(sorted(readable_tags.items())), "readable_presentation_attribute_values": {key: dict(sorted(values.items())) for key, values in sorted(presentation_values.items())}, "literal_volume_statement_counts": dict(sorted(volumes.items())), "uncited_article_shaped_urls": [page["url"] for page in pages if page["source_shape"] == "article-shaped-page-without-citation"], "historical_source_claims_reconciled": False, "work_completeness_established": False, "metadata_adopted": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, action="append", required=True)
    parser.add_argument("--acquisition-run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.acquisition_run:
        args.cohort.extend(path for path in sorted(args.acquisition_run.glob("batch-[0-9][0-9][0-9][0-9]")) if (path / "acquisition.json").is_file())
    result = inventory(args.cohort)
    payload = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with args.output.open("xb") as stream:
        stream.write(payload)
    print(json.dumps({"output": str(args.output), "sha256": hashlib.sha256(payload).hexdigest(), "pages": len(result["source_pages"]), "source_shape_counts": result["source_shape_counts"], "uncited_article_shaped_urls": result["uncited_article_shaped_urls"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
