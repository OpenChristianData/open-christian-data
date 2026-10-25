"""Census retained New Advent links and acquire an explicit bounded article batch.

This establishes a source-linked acquisition frontier, not a complete work or
printed-volume claim. Index HTML is traversed independently of the legacy
Catholic Encyclopedia parser. Every anchor occurrence remains in the census.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit

from build.tools.retain_newadvent_sources import checked_url, retain


ARTICLE = re.compile(r"/cathen/[0-9]{5}[a-z]\.htm\Z")
INDEX = re.compile(r"/cathen/(?:[a-z](?:-ce)?\.htm)?\Z")


class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self.canonical_links: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag == "base":
            raise ValueError("HTML base element needs an explicit acquisition policy")
        if tag == "link" and sum(name == "rel" for name, _ in attrs) > 1:
            raise ValueError("Duplicate rel attributes require an explicit canonical-link policy")
        canonical = tag == "link" and any(name == "rel" and "canonical" in (value or "").lower().split() for name, value in attrs)
        if tag != "a" and not canonical:
            return
        hrefs = [value for name, value in attrs if name == "href"]
        if len(hrefs) > 1:
            raise ValueError("Duplicate href attributes are ambiguous")
        collection = self.canonical_links if canonical else self.links
        collection.append({
            "canonical_ordinal" if canonical else "anchor_ordinal": len(collection) + 1,
            "line": self.getpos()[0], "column": self.getpos()[1],
            "href": hrefs[0] if hrefs else None,
        })


def census(cohorts: list[Path]) -> dict:
    members = []
    occurrences = []
    canonical_occurrences = []
    articles: dict[str, None] = {}
    indexes: dict[str, None] = {}
    receipts = []
    unresolved_members = []
    seen_urls = set()
    for cohort in cohorts:
        receipt_path = cohort / "acquisition.json"
        raw_receipt = receipt_path.read_bytes()
        receipt = json.loads(raw_receipt)
        if receipt.get("contract") != "ocd-newadvent-retained-cohort-v1":
            raise ValueError(f"Wrong acquisition receipt: {receipt_path}")
        receipts.append({"path": str(receipt_path.resolve()), "sha256": hashlib.sha256(raw_receipt).hexdigest()})
        for member in receipt["members"]:
            if member["status"] != "retained":
                unresolved_members.append({"receipt": str(receipt_path.resolve()), **member})
                continue
            url = checked_url(member["url"])
            if url in seen_urls:
                raise ValueError(f"Duplicate retained URL requires explicit witness selection: {url}")
            seen_urls.add(url)
            if member.get("final_url") != url or member.get("http_status") != 200:
                raise ValueError(f"Redirect or unsuccessful response needs explicit identity policy: {url}")
            name = member["path"]
            if not re.fullmatch(r"[0-9]{6}\.html", name):
                raise ValueError(f"Unsafe retained member path: {name}")
            path = cohort / name
            if path.is_symlink() or path.resolve().parent != cohort.resolve():
                raise ValueError(f"Retained member escapes cohort: {path}")
            payload = path.read_bytes()
            if len(payload) != member["bytes"] or hashlib.sha256(payload).hexdigest() != member["sha256"]:
                raise ValueError(f"Retained source byte binding failed: {path}")
            # The current source declares UTF-8. Never silently replace invalid bytes.
            source = payload.decode("utf-8", errors="strict")
            parser = Links()
            parser.feed(source)
            parser.close()
            members.append({"url": url, "path": str(path.resolve()), "sha256": member["sha256"], "bytes": len(payload), "anchor_count": len(parser.links)})
            for anchor in [*parser.links, *parser.canonical_links]:
                target = urljoin(url, anchor["href"]) if anchor["href"] is not None else None
                canonical, fragment = urldefrag(target) if target is not None else (None, "")
                kind = "anchor-without-href"
                if canonical is not None:
                    parts = urlsplit(canonical)
                    if parts.scheme == "https" and parts.netloc == "www.newadvent.org" and not parts.query:
                        if ARTICLE.fullmatch(parts.path):
                            kind = "article"
                            articles.setdefault(canonical, None)
                        elif INDEX.fullmatch(parts.path):
                            kind = "index"
                            indexes.setdefault(canonical, None)
                        else:
                            kind = "other-provider-link"
                    else:
                        kind = "external-or-query-link"
                destination = canonical_occurrences if "canonical_ordinal" in anchor else occurrences
                destination.append({"source_url": url, **anchor, "resolved_url": canonical, "fragment": fragment, "kind": kind})
    return {
        "contract": "ocd-newadvent-link-census-v1",
        "scope": "all-anchor-and-canonical-link-occurrences-in-declared-retained-members",
        "source_receipts": receipts, "members": members, "links": occurrences,
        "canonical_links": canonical_occurrences,
        "frontier_order": "member-order; anchors-before-canonical-links-within-each-member",
        "unretained_declared_members": unresolved_members,
        "article_urls_in_first_occurrence_order": list(articles),
        "index_urls_in_first_occurrence_order": list(indexes),
        "missing_linked_indexes": [url for url in indexes if url not in seen_urls],
        "unretained_article_urls": [url for url in articles if url not in seen_urls],
        "printed_volume_membership_established": False,
        "work_completeness_established": False,
        "historical_source_claims_reconciled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", action="append", type=Path, required=True)
    parser.add_argument("--acquisition-run", type=Path, help="Include a snapshot of completed immutable article batches")
    parser.add_argument("--output", type=Path, required=True, help="New census JSON path")
    parser.add_argument("--acquire-count", type=int, default=0, help="Explicit number of missing article URLs to request")
    parser.add_argument("--start", type=int, default=0, help="Zero-based offset in missing article URL order")
    parser.add_argument("--destination", type=Path, help="New raw acquisition directory")
    args = parser.parse_args()
    if args.acquisition_run:
        args.cohort.extend(path for path in sorted(args.acquisition_run.glob("batch-[0-9][0-9][0-9][0-9]")) if (path / "acquisition.json").is_file())
    if args.start < 0 or args.acquire_count < 0:
        parser.error("start and acquire-count cannot be negative")
    if bool(args.acquire_count) != bool(args.destination):
        parser.error("acquire-count and destination must be supplied together")
    result = census(args.cohort)
    if args.acquire_count and result["missing_linked_indexes"]:
        parser.error("Retain the missing linked indexes before acquiring articles")
    selected = result["unretained_article_urls"][args.start:args.start + args.acquire_count]
    if args.acquire_count and len(selected) != args.acquire_count:
        parser.error("Requested batch extends past the declared article frontier")
    result["selected_acquisition_urls"] = selected
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    acquisition = retain(selected, args.destination) if selected else None
    print(json.dumps({
        "census": str(args.output), "retained_members": len(result["members"]),
        "anchor_occurrences": len(result["links"]),
        "article_targets": len(result["article_urls_in_first_occurrence_order"]),
        "missing_indexes": result["missing_linked_indexes"],
        "selected_articles": len(selected),
        "acquisition_status": acquisition["status"] if acquisition else "not-requested",
    }, indent=2))
    return 1 if acquisition and acquisition["status"] != "declared-urls-retained" else 0


if __name__ == "__main__":
    raise SystemExit(main())
