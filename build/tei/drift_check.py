"""Check committed JE apparatus TEI against a fresh ledger+WCT materialization."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from lxml import etree

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.tei.materialize_je import (
    _events_by_page,
    _read_json,
    _read_jsonl,
    materialize_page_document,
    resolve_edition_page_key,
)


def _canonical_document(tree: etree._ElementTree) -> str:
    return etree.canonicalize(tree.getroot(), with_comments=True)


def _canonical_file(path: Path) -> str:
    parser = etree.XMLParser(remove_blank_text=True, remove_comments=False)
    return _canonical_document(etree.parse(str(path), parser))


def _first_difference(left: str, right: str) -> str:
    context_chars = 80
    rendered_limit = 180

    def ascii_snippet(value: str) -> str:
        rendered = ascii(value)
        if len(rendered) <= rendered_limit:
            return rendered
        return rendered[: rendered_limit - 3] + "..."

    for index, (left_char, right_char) in enumerate(zip(left, right)):
        if left_char == right_char:
            continue
        start = max(0, index - context_chars)
        left_end = min(len(left), index + context_chars + 1)
        right_end = min(len(right), index + context_chars + 1)
        return (
            f"first differing canonical char {index}: "
            f"committed[{start}:{left_end}]={ascii_snippet(left[start:left_end])} "
            f"rebuilt[{start}:{right_end}]={ascii_snippet(right[start:right_end])}"
        )

    if len(left) != len(right):
        index = min(len(left), len(right))
        if len(left) < len(right):
            tail = right[index : index + context_chars]
            return f"canonical length differs at char {index}: committed is prefix; rebuilt_tail={ascii_snippet(tail)}"
        tail = left[index : index + context_chars]
        return f"canonical length differs at char {index}: rebuilt is prefix; committed_tail={ascii_snippet(tail)}"

    return "canonical forms differ"


def page_drift(
    committed_tei_path: Path,
    wct_page: dict,
    events: list[dict],
    *,
    work_id: str,
    volume_id: str,
    edition_page_key: dict,
) -> list[str]:
    """Return drift differences between committed TEI and rebuilt ledger+WCT TEI."""
    page_id = str(wct_page["page_id"])
    if not committed_tei_path.exists():
        return [f"{page_id}: missing committed TEI at {committed_tei_path.as_posix()}"]

    rebuilt = materialize_page_document(
        wct_page,
        events,
        work_id=work_id,
        volume_id=volume_id,
        edition_page_key=edition_page_key,
    )
    committed_c14n = _canonical_file(committed_tei_path)
    rebuilt_c14n = _canonical_document(rebuilt)
    if committed_c14n == rebuilt_c14n:
        return []
    return [f"{page_id}: drift detected; {_first_difference(committed_c14n, rebuilt_c14n)}"]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--wct-dir", type=Path, required=True)
    parser.add_argument("--ia-manifest", type=Path, required=True)
    parser.add_argument("--tei-dir", type=Path, required=True)
    parser.add_argument("--work-id", default="jewish-encyclopedia.vol_02")
    parser.add_argument("--volume-id", default="vol_02")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    ledger_events = _read_jsonl(args.ledger)
    events_by_page = _events_by_page(ledger_events)
    ia_manifest = _read_json(args.ia_manifest)

    pages_checked = 0
    drift_free = 0
    drifted = 0
    missing = 0

    for page_id in sorted(events_by_page):
        wct_path = args.wct_dir / f"{page_id}.json"
        wct_page = _read_json(wct_path)
        edition_page_key = resolve_edition_page_key(wct_page, ia_manifest)
        committed_tei_path = args.tei_dir / f"{page_id}.tei.xml"
        try:
            differences = page_drift(
                committed_tei_path,
                wct_page,
                events_by_page[page_id],
                work_id=args.work_id,
                volume_id=args.volume_id,
                edition_page_key=edition_page_key,
            )
        except (ValueError, KeyError, OSError, etree.XMLSyntaxError) as error:
            differences = [
                f"{page_id}: page drift error: {type(error).__name__}: {ascii(str(error))}"
            ]
        pages_checked += 1
        if not differences:
            drift_free += 1
            print(f"PASS {page_id}")
            continue

        drifted += 1
        if any("missing committed TEI" in difference for difference in differences):
            missing += 1
        print(f"DRIFT {page_id}")
        for difference in differences:
            print(f"  {difference}")

    print(f"summary: pages_checked={pages_checked} drift_free={drift_free} drifted={drifted} missing={missing}")
    return 0 if drifted == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
