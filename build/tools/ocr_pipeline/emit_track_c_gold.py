"""Track-C gold emitter: completed worksheet -> harness-ready .gold.json files.

Reads a human-completed adjudication worksheet CSV and emits one
``<page_id>.gold.json`` file per page in the format consumed by
``measure_corrector.py --gold-dir``.

NON-CIRCULARITY: blank gold_text rows are OMITTED — never filled from the
engine_guesses_do_not_copy column. The harness skips positions absent from gold,
which is the correct behaviour for tokens the human could not confidently read.
"""
from __future__ import annotations

import csv
import json
import pathlib


def emit_gold_page(rows: list[dict]) -> dict:
    """Convert worksheet rows for one page to the gold.json dict.

    Blank or whitespace-only gold_text entries are OMITTED — the harness skips
    positions absent from the gold dict.

    Returns:
        {"positions": {position_id: {"gold_text": <human reading>}, ...}}
        Only positions with non-empty gold_text are included.
    """
    positions = {}
    for row in rows:
        gold_text = row.get("gold_text", "").strip()
        if not gold_text:
            continue  # omit; harness skips absent positions
        positions[row["position_id"]] = {"gold_text": gold_text}
    return {"positions": positions}


def validate_gold_file(path: pathlib.Path) -> None:
    """Verify a gold file matches the harness loader contract.

    Raises:
        KeyError:   if "positions" key is absent
        ValueError: if any included position has empty or missing gold_text
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if "positions" not in data:
        raise KeyError(f"Missing 'positions' key in {path}")
    for pid, entry in data["positions"].items():
        if "gold_text" not in entry:
            raise ValueError(f"Position {pid!r} missing 'gold_text' in {path}")
        if not str(entry["gold_text"]).strip():
            raise ValueError(f"Position {pid!r} has empty gold_text in {path}")


def emit_gold_corpus(rows: list[dict], gold_dir: pathlib.Path) -> list[pathlib.Path]:
    """Group worksheet rows by page_id and write one .gold.json per page.

    Pages where every entry is blank produce no output file (the harness simply
    sees no gold for that page and skips it).

    Returns:
        List of paths written.
    """
    gold_dir.mkdir(parents=True, exist_ok=True)

    pages: dict[str, list[dict]] = {}
    for row in rows:
        pages.setdefault(row["page_id"], []).append(row)

    written = []
    for page_id, page_rows in pages.items():
        gold = emit_gold_page(page_rows)
        if not gold["positions"]:
            continue  # all blank — no file
        out_path = gold_dir / f"{page_id}.gold.json"
        out_path.write_text(json.dumps(gold, indent=2, ensure_ascii=False), encoding="utf-8")
        validate_gold_file(out_path)
        written.append(out_path)

    return written


def load_worksheet(path: pathlib.Path) -> list[dict]:
    """Load a completed adjudication worksheet CSV."""
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Emit Track-C gold files from completed worksheet")
    parser.add_argument("--worksheet", type=pathlib.Path, required=True, help="Completed worksheet CSV")
    parser.add_argument("--gold-dir", type=pathlib.Path, required=True, help="Output directory for .gold.json files")
    args = parser.parse_args()

    rows = load_worksheet(args.worksheet)
    written = emit_gold_corpus(rows, args.gold_dir)

    filled = sum(1 for r in rows if r.get("gold_text", "").strip())
    blank = sum(1 for r in rows if not r.get("gold_text", "").strip())

    print(f"Worksheet rows: {len(rows)}")
    print(f"  Filled: {filled}")
    print(f"  Blank (omitted): {blank}")
    print(f"Gold files written: {len(written)}")
    for p in sorted(written):
        data = json.loads(p.read_text(encoding="utf-8"))
        print(f"  {p.name}: {len(data['positions'])} positions")
