"""Browse and count the declared library without WorkCatalog or regeneration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.views import library_browse_snapshot


def render_markdown(report: dict) -> str:
    def cell(value: object) -> str:
        return str(value if value is not None else "unknown").replace("|", "\\|").replace("\n", " ")

    lines = ["# Declared library", "", report["authority"], "",
             "Scope: validated identities below library/works; this is not the legacy corpus count.",
             report["legacy_coverage"], "",
             f"Works: {report['counts']['works']}; editions: {report['counts']['editions']}; "
             f"recorded accepted editions: {report['counts']['recorded_accepted_editions']}; "
             f"observed master files: {report['counts']['observed_master_files']}.", "",
             f"Showing {report['page']['returned']} of {report['page']['total']} matching works; next offset: {report['page']['next_offset']}.", "",
             "| Work | Title | Forms | Editions | Creators | Categories | Recorded stages | Identity | Lookup |", "|---|---|---:|---:|---|---|---|---|---|"]
    for work in report["works"]:
        lines.append("| " + " | ".join(cell(value) for value in (
            work["work_id"], work["title"], work["form_count"], work["edition_count"], "; ".join(item["name"] for item in work["creators"]) or None,
            ", ".join(work["categories"]) or None, ", ".join(work["recorded_stages"]) or None, work["identity_status"],
            f"`{work['lookup']}`" if work["lookup"] else None)) + " |")
    lines.extend(["", "## Issues", "", json.dumps(report["issues"], ensure_ascii=False, indent=2), ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--search", help="Accent-insensitive tokens in work ID, title or declared creator")
    parser.add_argument("--creator", help="Tokens in declared creator names; unknown creators remain unmatched")
    parser.add_argument("--category", help="Declared edition category")
    parser.add_argument("--stage", help="Recorded edition stage, not freshly verified acceptance")
    parser.add_argument('--language', help='Canonical language or an explicitly mapped alias')
    parser.add_argument('--provider', help='Canonical provider key or an explicitly mapped alias')
    from ocd_kernel.library.identities import schema_enum
    parser.add_argument('--rights', choices=schema_enum('rights-record', 'query_mode'))
    parser.add_argument('--rights-status', choices=schema_enum('rights-record', 'rights_status'))
    parser.add_argument('--jurisdiction', help='Country code; an unspecified provider territory never matches')
    parser.add_argument('--rights-scope', choices=schema_enum('rights-record', 'scope'))
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50, help="Maximum matching works (default: 50)")
    args = parser.parse_args(argv)
    try:
        report = library_browse_snapshot(args.root, search=args.search, creator=args.creator,
                                        category=args.category, stage=args.stage, offset=args.offset, limit=args.limit,
                                        language=args.language, provider=args.provider, rights_mode=args.rights,
                                        rights_status=args.rights_status, jurisdiction=args.jurisdiction, rights_scope=args.rights_scope)
    except (PipelineError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render_markdown(report))
    return 1 if report["counts"]["failed"] or any(
        issue.get("severity") == "error" for issue in report["issues"]
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
