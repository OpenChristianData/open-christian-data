"""Compare local OCR text outputs and flag disagreement zones."""

from __future__ import annotations

import argparse
import json
import re
import string
import sys
from html import escape
from pathlib import Path
from typing import Any


_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.text_alignment import align_tokens  # noqa: E402
from build.lib.ocr_coordinates import lookup_bbox, read_hocr  # noqa: E402

PUNCTUATION_TRANSLATION = str.maketrans("", "", string.punctuation)


def compare_ocr_files(
    ocr_paths: list[Path],
    labels: list[str] | None = None,
    output_html: Path | None = None,
    output_json: Path | None = None,
    coords_path: Path | None = None,
    coords_page: int | None = None,
) -> dict[str, Any]:
    """Compare two or more local OCR text files."""
    paths = [Path(path) for path in ocr_paths]
    if len(paths) < 2:
        raise ValueError("At least two OCR text files are required.")
    source_labels = labels or [path.stem for path in paths]
    if len(source_labels) != len(paths):
        raise ValueError("The number of labels must match the number of OCR files.")

    labelled_texts = [(label, path.read_text(encoding="utf-8")) for label, path in zip(source_labels, paths, strict=True)]
    result = compare_ocr_texts(labelled_texts)

    if coords_path is not None and coords_page is not None:
        coords = read_hocr(coords_path)
        for record in result["disagreement_records"]:
            sources = record.get("sources", {})
            canonical = next(iter(sources.values()), "") if sources else ""
            bbox = lookup_bbox(coords, page=coords_page, text_snippet=canonical)
            if bbox is not None:
                record["bbox"] = {"x": bbox[0], "y": bbox[1], "w": bbox[2], "h": bbox[3]}

    if output_json is not None:
        output_json = Path(output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_html is not None:
        output_html = Path(output_html)
        output_html.parent.mkdir(parents=True, exist_ok=True)
        output_html.write_text(render_html_report(result), encoding="utf-8")
    return result


def compare_ocr_texts(labelled_texts: list[tuple[str, str]]) -> dict[str, Any]:
    """Compare OCR texts and return JSON-serialisable disagreement records."""
    if len(labelled_texts) < 2:
        raise ValueError("At least two OCR texts are required.")

    labels = [label for label, _text in labelled_texts]
    texts = [text for _label, text in labelled_texts]
    records = _whole_text_disagreement(labelled_texts)
    if records is None:
        records = _token_disagreements(labelled_texts)

    return {
        "labels": labels,
        "counts": {
            "source_count": len(labelled_texts),
            "total_disagreements": len(records),
            "by_classification": _counts_by_classification(records),
        },
        "source_lengths": {label: len(text) for label, text in labelled_texts},
        "disagreement_records": records,
    }


def render_html_report(result: dict[str, Any]) -> str:
    records = result["disagreement_records"]
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            "<title>OCR ensemble comparison</title>",
            "<style>",
            _stylesheet(),
            "</style>",
            "</head>",
            "<body>",
            "<main>",
            "<h1>OCR ensemble comparison</h1>",
            f"<p>Sources: {escape(', '.join(result['labels']))}</p>",
            f"<p>Total disagreements: {result['counts']['total_disagreements']}</p>",
            _render_records(records),
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _whole_text_disagreement(labelled_texts: list[tuple[str, str]]) -> list[dict[str, Any]] | None:
    texts = [text for _label, text in labelled_texts]
    if all(text == texts[0] for text in texts):
        return []
    classification = _classify_texts(texts)
    if classification in {"whitespace-only", "case-only", "punctuation-only"}:
        return [
            {
                "index": 0,
                "classification": classification,
                "sources": {label: _truncate(text) for label, text in labelled_texts},
            }
        ]
    return None


def _token_disagreements(labelled_texts: list[tuple[str, str]]) -> list[dict[str, Any]]:
    token_lists = [(label, _tokens(text)) for label, text in labelled_texts]
    all_labels = [label for label, _tokens_for_label in token_lists]
    canonical_label, canonical_tokens = token_lists[0]
    records: list[dict[str, Any]] = []
    for witness_label, witness_tokens in token_lists[1:]:
        for op in align_tokens(canonical_tokens, witness_tokens):
            if op.tag == "equal":
                continue
            values = dict.fromkeys(all_labels, "")
            values[canonical_label] = " ".join(op.canonical_text)
            values[witness_label] = " ".join(op.witness_text)
            classification = _classify_texts(list(values.values()))
            records.append(
                {
                    "index": op.canonical_range[0],
                    "classification": classification,
                    "sources": values,
                }
            )
    return records


def _classify_texts(texts: list[str]) -> str:
    if _all_equal(_normalise_whitespace(text) for text in texts):
        return "whitespace-only"
    if _all_equal(text.lower() for text in texts):
        return "case-only"
    if _all_equal(_normalise_punctuation(text) for text in texts):
        return "punctuation-only"
    if _looks_like_ocr_confusion(texts):
        return "likely OCR character confusion"
    return "content disagreement"


def _looks_like_ocr_confusion(texts: list[str]) -> bool:
    skeletons = [_ocr_skeleton(text) for text in texts]
    return _all_equal(skeletons) and not _all_equal(texts)


def _ocr_skeleton(text: str) -> str:
    lowered = text.lower()
    for source, target in {
        "rn": "m",
        "1": "l",
        "0": "o",
        "5": "s",
        "8": "b",
        "vv": "w",
    }.items():
        lowered = lowered.replace(source, target)
    return lowered


def _counts_by_classification(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        classification = str(record["classification"])
        counts[classification] = counts.get(classification, 0) + 1
    return counts


def _render_records(records: list[dict[str, Any]]) -> str:
    if not records:
        return '<p class="empty-state">No disagreement records.</p>'
    return "\n".join(_render_record(record) for record in records)


def _render_record(record: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>"
        for label, value in record["sources"].items()
    )
    return "\n".join(
        [
            '<article class="record">',
            f"<h2>{escape(record['classification'])}</h2>",
            f"<p>Index {record['index']}</p>",
            f"<table>{rows}</table>",
            "</article>",
        ]
    )


def _tokens(text: str) -> list[str]:
    return _normalise_line_endings(text).split()


def _normalise_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalise_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalise_punctuation(text: str) -> str:
    return _normalise_whitespace(text).lower().translate(PUNCTUATION_TRANSLATION)


def _all_equal(values: Any) -> bool:
    values = list(values)
    return bool(values) and all(value == values[0] for value in values)


def _truncate(text: str, limit: int = 240) -> str:
    cleaned = _normalise_whitespace(text)
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 3]}..."


def _stylesheet() -> str:
    return """
body { margin: 0; background: #f8f6f1; color: #221f1a; font: 16px/1.5 Georgia, "Times New Roman", serif; }
main { max-width: 980px; margin: 0 auto; padding: 28px; }
.record { margin-top: 18px; padding: 16px; background: #fffdf8; border: 1px solid #d9d1c5; border-radius: 6px; }
h1 { margin: 0 0 8px; }
h2 { margin: 0 0 8px; font: 700 1rem Arial, Helvetica, sans-serif; }
table { width: 100%; border-collapse: collapse; }
th, td { border-top: 1px solid #d9d1c5; padding: 8px; text-align: left; vertical-align: top; }
th { width: 10rem; font-family: Arial, Helvetica, sans-serif; }
.empty-state { color: #6d655d; }
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ocr_files", type=Path, nargs="+", help="Two or more local OCR text files.")
    parser.add_argument("--label", action="append", dest="labels", help="Label for an OCR source. Repeat per file.")
    parser.add_argument("--output-html", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--coords-path", type=Path, help="Optional hOCR file to tag disagreements with bbox.")
    parser.add_argument("--coords-page", type=int, help="Page number within the hOCR to look up bboxes against.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    compare_ocr_files(
        ocr_paths=args.ocr_files,
        labels=args.labels,
        output_html=args.output_html,
        output_json=args.output_json,
        coords_path=args.coords_path,
        coords_page=args.coords_page,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
