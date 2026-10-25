"""Project the maintained library acquisition queue into public work guidance."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlencode, urlsplit

from ocd_kernel.library._common import PipelineError, canonical_bytes, sha256_bytes
from ocd_kernel.library.acquisitions import load_acquisition_leads
from ocd_kernel.library.views import library_browse_snapshot
from ocd_kernel.library.cataloging import FIELDS, load_note
from ocd_kernel.library.labels import public_value


ISSUES = "https://github.com/OpenChristianData/open-christian-data/issues/new"


def current_snapshot(root: Path) -> dict:
    """Use the library's record reader; publishing a work list needs no text audit."""
    browse = library_browse_snapshot(root)
    if browse['issues']:
        raise PipelineError(f"library records have {len(browse['issues'])} issues; resolve them before refreshing the public list")
    queue_path = root / 'library/acquisition-leads.jsonl'
    manifest_path = root / 'research/MANIFEST.md'
    leads = load_acquisition_leads(queue_path, root=root) if queue_path.is_file() else []
    if queue_path.is_file() != manifest_path.is_file():
        raise PipelineError('library acquisition queue and historical manifest evidence must be present together')
    for lead in leads:
        note = load_note(root, lead)
        if note is not None:
            lead['cataloging'] = note
    items = []
    for work in browse['works']:
        for edition in work['editions']:
            accepted = (edition['recorded_stage'] == 'accepted'
                        and edition['observed_master_presence'] and edition['observed_acceptance_presence'])
            items.append({'work_id': work['work_id'], 'edition_id': edition['edition_id'],
                          'edition_title': edition['title'], 'master_status': 'accepted' if accepted else 'not-recorded-accepted',
                          'state_stage': edition['recorded_stage'],
                          'source_url': ' '.join(source.get('url') or '' for source in edition['sources'])})
    return {'manifest': {'works': browse['works']}, 'queue': {
        'items': items, 'research_leads': leads, 'issues': [],
        'freshness': {'input_sha256': sha256_bytes(canonical_bytes({'browse': browse, 'leads': leads}))}}}


def _text(value: object) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", str(value or ""))
    return html.escape(" ".join(text.replace("\\|", "|").split())).replace("|", "&#124;")


def _links(value: str) -> list[str]:
    result = []
    for candidate in re.findall(r'https?://[^\s<>\[\]|`"]+', value):
        depth = 0
        for index, character in enumerate(candidate):
            if character == '(':
                depth += 1
            elif character == ')':
                if depth == 0:
                    candidate = candidate[:index]
                    break
                depth -= 1
        parsed = urlsplit(candidate)
        encoded = quote(candidate, safe=":/?#@!$&'+,;=%-._~")
        if parsed.hostname and not parsed.username and not parsed.password and encoded not in result:
            result.append(encoded)
    return result


def project(snapshot: dict, checked_at: str) -> dict:
    """Export explicit public fields; research observations never become open jobs."""
    queue = snapshot["queue"]
    titles = {work["work_id"]: work["title"] for work in snapshot["manifest"]["works"]}
    editions = []
    for item in queue["items"]:
        if item["master_status"] == "accepted":
            continue
        editions.append({
            "work_id": item["work_id"], "title": titles[item["work_id"]],
            "edition_id": item["edition_id"], "edition": item.get("edition_title"),
            "recorded_stage": item.get("state_stage"), "master_status": item["master_status"],
            "source_urls": _links(item.get("source_url") or ""),
            "coordination": "Confirm the exact edition and current assignment in an issue before starting.",
        })
    catalog_only = [{"work_id": work["work_id"], "title": work["title"]}
                    for work in snapshot["manifest"]["works"] if not work.get("editions")]
    leads = []
    seen = set()
    for lead in queue["research_leads"]:
        identifier = lead["lead_id"]
        if identifier in seen:
            raise PipelineError(f"duplicate public research lead: {identifier}")
        seen.add(identifier)
        headers = lead.get("columns", [])
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", lead["observed_claim"].strip().strip("|"))]
        title = None
        if not headers:
            named = re.search(r'^Title:[ \t]*(\S[^\n]*)', lead['observed_claim'], flags=re.MULTILINE)
            title = named.group(1).strip() if named else None
        if headers and len(cells) == len(headers):
            for index, header in enumerate(headers):
                if any(word in header.casefold() for word in ("work", "title", "collection", "acquisition unit", "research area")) or header == "Area":
                    title = cells[index]
                    break
        row = {"lead_id": identifier, "title": title,
                      "disposition": lead["disposition"], "work_id": lead.get("work_id"),
                      "recorded_public_links": _links(lead["observed_claim"])}
        if 'cataloging' in lead:
            row['cataloging'] = {key: (public_value(value) or '') if not re.search(r'https?://[^\s/]+@', value) else ''
                                 for key, value in lead['cataloging']['fields'].items()}
            title = row['cataloging']['title']
            row['title'] = title or row['cataloging']['work_scope'] or row['title']
            author = row['cataloging']['author']
            if title and author and author.casefold() not in title.casefold():
                row['title'] += ' — ' + author
        leads.append(row)
    return {"format": "ocd-public-acquisitions-v1", "checked_at": checked_at,
            "authority_sha256": queue["freshness"]["input_sha256"],
            "scope": "Recorded library work and validated research leads; not task availability, rights clearance or live source verification.",
            "editions_without_accepted_master": sorted(editions, key=lambda row: (row["work_id"], row["edition_id"])),
            "catalog_only_works": sorted(catalog_only, key=lambda row: row["work_id"]),
            "research_leads": sorted(leads, key=lambda row: row["lead_id"]),
            "source_issue_count": len(queue["issues"])}


def _issue(identifier: str) -> str:
    return ISSUES + "?" + urlencode({"template": "source-proposal.md", "title": "Text contribution: " + identifier})


def render(record: dict) -> str:
    lines = ["# Texts to investigate and contribute", "",
             "Help us add faithful texts. This page is generated from the library acquisition queue and current work records.",
             f"Source records checked: **{record['checked_at']}**. This is a dated snapshot, not a live claim board.", "",
             "Before starting, search the release catalog and existing issues for the exact work and edition, then open or join its issue. A missing accepted master does not mean the work is unclaimed or ready to publish.",
             "Use the [text contribution workflow](TEXT_CONTRIBUTIONS.md). Other texts and ideas are welcome; [suggest one](" + ISSUES + "?template=source-proposal.md).", "",
             "Use the [queue cataloging template](examples/information-templates.md#acquisition-queue-cataloging) to record the work, edition, source copy and evidence.", "",
             "[Download the same list as JSON](ACQUISITIONS.json). Research observations below can overlap existing holdings; their inherited source claims are not fresh checks or acquisition approvals.", "",
             "## Recorded editions without an accepted master", "",
             "| Work and copy | Recorded stage | Source links | Coordinate |", "|---|---|---|---|"]
    for row in record["editions_without_accepted_master"]:
        links = " · ".join(f"[source {i+1}]({url})" for i, url in enumerate(row["source_urls"])) or "Source needs confirmation"
        lines.append(f"| {_text(row['title'])} — {_text(row['edition'] or row['edition_id'])} | {_text(row['recorded_stage'] or 'not recorded')} | {links} | [Discuss]({_issue(row['edition_id'])}) |")
    if not record["editions_without_accepted_master"]:
        lines.append("| No recorded editions in this scope | — | — | — |")
    lines += ["", "## Cataloged works needing source or edition research", "",
              "These works have an identity but no declared edition. Confirm what copy is wanted and where it can be obtained.", "",
              "| Work | Coordinate |", "|---|---|"]
    for row in record["catalog_only_works"]:
        lines.append(f"| {_text(row['title'])} | [Discuss]({_issue(row['work_id'])}) |")
    if not record["catalog_only_works"]:
        lines.append("| No catalog-only works in this scope | — |")
    lines += ["", "## Research leads", "",
              "These are recorded research observations, not a list of approved new jobs. Some are broad collections or research questions. Help confirm the exact text, identify an accessible copy, or reconcile it with existing holdings. A promoted lead already has a recorded work identity.", "",
              "| Lead | Recorded text or research topic | Disposition | Recorded links | Cataloging | Coordinate |", "|---|---|---|---|---|---|"]
    for row in record["research_leads"]:
        links = " · ".join(f"[link {i+1}]({url})" for i, url in enumerate(row["recorded_public_links"])) or "Needs source research"
        title = row["title"] or "Research note — exact work identity still needs recording"
        note = f"[Details](#cataloging-{row['lead_id']})" if 'cataloging' in row else ''
        lines.append(f"| `{row['lead_id']}` | {_text(title)} | {_text(row['disposition'])} | {links} | {note} | [Discuss]({_issue(row['lead_id'])}) |")
    cataloged = [row for row in record['research_leads'] if 'cataloging' in row]
    if cataloged:
        lines += ['', '## Cataloging notes', '',
                  'These entries organize the existing research. Blank fields were not settled by that research. Collections and research topics remain identified as such.', '']
        for row in cataloged:
            fields = row['cataloging']
            lines += [f'<details id="cataloging-{row["lead_id"]}">',
                      f'<summary>{_text(row["title"])} — {row["lead_id"]}</summary>', '',
                      '| Field | Recorded information |', '|---|---|',
                      *(f'| {_text(label)} | {_text(fields[key])} |' for key, label in FIELDS.items()),
                      '', '</details>', '']
    lines += ["", "## Keeping the list current", "",
              "Maintainers update `library/acquisition-leads.jsonl` through `build/tools/maintain_research_lead.py` and update the owning work/acquisition/state records, then regenerate this projection. Historical research documents preserve evidence; the library queue owns current lead disposition. Public issues are the place to coordinate.", "",
              "```powershell", "py -3 -m build.tools.build_public_acquisition_list --root . --output docs",
              "py -3 -m build.tools.build_public_acquisition_list --root . --output docs --check", "```", "",
              "Generation uses the maintained library browse reader and validated acquisition leads. It reports recorded acceptance and file presence; it does not re-audit text bytes. The check rejects changed records or edited output. Public-only checkouts do not contain the private library authority; propose changes through the linked issues.",
              f"The source snapshot reports {record['source_issue_count']} diagnostic issues. Consult the owning records before treating a row as ready work.", ""]
    return "\n".join(lines)


def write_or_check(snapshot: dict, output: Path, *, check: bool = False) -> dict:
    json_path, md_path = output / "ACQUISITIONS.json", output / "ACQUISITIONS.md"
    if check:
        if not json_path.is_file() or not md_path.is_file():
            raise PipelineError("public acquisition list is missing; regenerate it")
        previous = json.loads(json_path.read_text(encoding="utf-8"))
        checked_at = previous["checked_at"]
    else:
        checked_at = datetime.now(timezone.utc).isoformat()
    record = project(snapshot, checked_at)
    encoded = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    markdown = render(record)
    if check:
        if json_path.read_text(encoding="utf-8") != encoded or md_path.read_text(encoding="utf-8") != markdown:
            raise PipelineError("public acquisition list is stale or edited; regenerate it")
    else:
        output.mkdir(parents=True, exist_ok=True)
        json_path.write_text(encoded, encoding="utf-8", newline="\n")
        md_path.write_text(markdown, encoding="utf-8", newline="\n")
    return {"checked": check, "authority_sha256": record["authority_sha256"],
            "editions": len(record["editions_without_accepted_master"]),
            "catalog_only_works": len(record["catalog_only_works"]), "research_leads": len(record["research_leads"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = write_or_check(current_snapshot(args.root), args.output, check=args.check)
    except (PipelineError, OSError, ValueError, KeyError) as exc:
        print(f"public acquisition list: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
