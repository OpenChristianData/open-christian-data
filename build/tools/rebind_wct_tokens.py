"""Measure WCT token stability and emit dry-run rebind/orphan events."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.wct_rebind import (  # noqa: E402
    compare_pages,
    corpus_summary,
    dry_run_events,
    load_page_num_by_sha,
)

OLD_WCT_DIR = REPO_ROOT / "reports" / "je-wct" / "vol_02"
NEW_WCT_DIR = REPO_ROOT / "reports" / "je-wct" / "vol_02-r2"
MANIFEST_PATH = REPO_ROOT / "raw" / "jewish-encyclopedia" / "ia-pages" / "vol_02.manifest.json"
REPORT_JSON = REPO_ROOT / "reports" / "measurement" / "wct-rebuild-stability-vol_02.json"
REPORT_MD = REPO_ROOT / "reports" / "measurement" / "wct-rebuild-stability-vol_02.md"
EVENTS_JSONL = REPO_ROOT / "reports" / "measurement" / "wct-rebuild-rebind-events-vol_02.jsonl"
ACCEPTANCE = 0.99


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _page_paths(old_dir: Path, new_dir: Path) -> list[tuple[Path, Path]]:
    old_pages = {path.name: path for path in old_dir.glob("page_*.json")}
    new_pages = {path.name: path for path in new_dir.glob("page_*.json")}
    missing_new = sorted(set(old_pages) - set(new_pages))
    extra_new = sorted(set(new_pages) - set(old_pages))
    if missing_new or extra_new:
        detail = []
        if missing_new:
            detail.append(f"missing in new: {', '.join(missing_new)}")
        if extra_new:
            detail.append(f"extra in new: {', '.join(extra_new)}")
        raise ValueError("; ".join(detail))
    return [(old_pages[name], new_pages[name]) for name in sorted(old_pages)]


def _spot_checks(page_results: list[dict], limit: int = 10) -> list[dict]:
    checks = []
    page_indexes = {page["page_id"]: 0 for page in page_results}
    while len(checks) < limit:
        added = False
        for page in page_results:
            index = page_indexes[page["page_id"]]
            while index < len(page["identical_samples"]) and not page["identical_samples"][index]["text_key"]:
                index += 1
            page_indexes[page["page_id"]] = index
            if index >= len(page["identical_samples"]):
                continue
            checks.append(_spot_check(page, page["identical_samples"][index]))
            page_indexes[page["page_id"]] += 1
            added = True
            if len(checks) >= limit:
                return checks
        if not added:
            return checks
    return checks


def _spot_check(page: dict, sample: dict) -> dict:
    source = page["source_image"]
    width, height = page["image_size"]
    bbox = sample["bbox"]
    in_bounds = (
        0 <= bbox["x"] <= width
        and 0 <= bbox["y"] <= height
        and bbox["w"] > 0
        and bbox["h"] > 0
        and bbox["x"] + bbox["w"] <= width
        and bbox["y"] + bbox["h"] <= height
    )
    return {
        "page_id": page["page_id"],
        "position_id": sample["from_position_id"],
        "source_image_path": source["path"],
        "source_image_exists": (REPO_ROOT / source["path"]).exists(),
        "bbox_within_image": in_bounds,
        "text_key": sample["text_key"],
    }


def _write_markdown(path: Path, report: dict) -> None:
    summary = report["summary"]
    lines = [
        "# JE vol_02 WCT rebuild stability",
        "",
        f"- Pages compared: {summary['pages']}",
        f"- Old tokens: {summary['old_token_count']}",
        f"- New tokens: {summary['new_token_count']}",
        f"- Identical canonical-token anchors: {summary['identical_count']}",
        f"- Rebound tokens: {summary['rebound_count']}",
        f"- Orphaned tokens: {summary['orphaned_count']}",
        f"- Additions in r2: {summary['addition_count']}",
        f"- Identity rate: {summary['identity_rate']:.6%}",
        f"- Acceptance threshold: {ACCEPTANCE:.2%}",
        f"- Acceptance result: {'PASS' if report['acceptance_pass'] else 'FAIL'}",
        "",
        "## Design note",
        "",
        (
            "JE r2 pages use `edition_page_key = body_edition_key(page_num)` and "
            "`canonical_leaf_id = page_num`. The page number comes from the IA pages "
            "manifest SHA map; this keeps the 34 body-page oracle panel schema-valid "
            "without mutating the frozen vol_02 WCT evidence."
        ),
        "",
        "## Spot checks",
        "",
    ]
    for check in report["spot_checks"]:
        lines.append(
            "- {page_id} {position_id}: image_exists={source_image_exists}, "
            "bbox_within_image={bbox_within_image}, text={text_key}".format(**check)
        )
    if not report["spot_checks"]:
        lines.append("- No spot checks available.")
    lines.extend(["", "## Exceptions", ""])
    if summary["rebound_count"] == 0 and summary["orphaned_count"] == 0:
        lines.append("- None.")
    else:
        for page in report["pages"]:
            if page["rebound_count"] or page["orphaned_count"]:
                lines.append(
                    f"- {page['page_id']}: rebound={page['rebound_count']}, "
                    f"orphaned={page['orphaned_count']}"
                )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-wct-dir", type=Path, default=OLD_WCT_DIR)
    parser.add_argument("--new-wct-dir", type=Path, default=NEW_WCT_DIR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--report-json", type=Path, default=REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=REPORT_MD)
    parser.add_argument("--events-jsonl", type=Path, default=EVENTS_JSONL)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    page_num_by_sha = load_page_num_by_sha(args.manifest)
    page_results = []
    events = []
    for old_path, new_path in _page_paths(args.old_wct_dir, args.new_wct_dir):
        old_page = _load(old_path)
        new_page = _load(new_path)
        page_result = compare_pages(old_page, new_page, page_num_by_sha=page_num_by_sha)
        page_result["source_image"] = new_page["source_image"]
        page_result["image_size"] = new_page["image_size"]
        for sample in page_result["identical_samples"]:
            new_position = next(
                position
                for position in new_page["positions"]
                if position["position_id"] == sample["to_position_id"]
            )
            sample["bbox"] = new_position["reference_bbox"]
        page_results.append(page_result)
        events.extend(dry_run_events(page_result, volume=2))

    summary = corpus_summary(page_results)
    report = {
        "schema_version": "wct-rebuild-stability-vol_02-v1",
        "old_wct_dir": _display_path(args.old_wct_dir),
        "new_wct_dir": _display_path(args.new_wct_dir),
        "acceptance_threshold": ACCEPTANCE,
        "acceptance_pass": summary["identity_rate"] >= ACCEPTANCE,
        "summary": summary,
        "spot_checks": _spot_checks(page_results),
        "pages": page_results,
    }
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(args.report_md, report)
    args.events_jsonl.write_text(
        "".join(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )
    print(
        f"identity_rate={summary['identity_rate']:.6%}; "
        f"identical={summary['identical_count']}; "
        f"rebound={summary['rebound_count']}; orphaned={summary['orphaned_count']}"
    )
    return 0 if report["acceptance_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
