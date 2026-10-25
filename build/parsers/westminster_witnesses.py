"""One-pass parsing of the retained Westminster Shorter Catechism witness.

This module is the builder-side source seam.  It parses each HTML document
once, deriving the question/answer reading and the emphasized proof witnesses
together.  The independent reconstruction verifier intentionally does not
import this module or its citation vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import re

from bs4 import BeautifulSoup


log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WscWitnessRow:
    number: int
    question: str
    answer: str
    proof_text: str
    proofs: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class WscWitnessDocument:
    rows: tuple[WscWitnessRow, ...]
    parse_errors: dict[int, tuple[str, ...]]
    questions_without_proofs: tuple[int, ...]

    @property
    def proofs_by_index(self) -> dict[int, list[dict[str, object]]]:
        return {row.number: list(row.proofs) for row in self.rows}


def _normalise_citation(citation: str) -> str:
    s = citation.strip().rstrip(".")
    s = re.sub(r"\s+with\s+", "; ", s)
    fixed_parts: list[str] = []
    for segment in s.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        comma_parts = [part.strip() for part in segment.split(",")]
        if len(comma_parts) <= 1:
            fixed_parts.append(segment)
            continue
        accumulated = comma_parts[0]
        for part in comma_parts[1:]:
            if _starts_with_book(part):
                fixed_parts.append(accumulated)
                accumulated = part
            else:
                accumulated = accumulated + ", " + part
        fixed_parts.append(accumulated)
    return "; ".join(
        re.sub(r"\s+title\b", "", part, flags=re.IGNORECASE).strip()
        for part in fixed_parts
    )


def _starts_with_book(token: str) -> bool:
    from build.lib.citation_parser import lookup_book

    tokens = token.strip().split()
    if not tokens:
        return False
    if lookup_book(tokens[0].rstrip(".")) is not None:
        return True
    return (
        len(tokens) >= 2
        and tokens[0].isdigit()
        and lookup_book(tokens[0] + " " + tokens[1].rstrip(".")) is not None
    )


def _parse_single_with_book_tracking(ref: str) -> dict[str, object]:
    from build.lib.citation_parser import (
        _extract_book_and_remainder,
        parse_single_reference,
    )

    raw = ref.strip()
    book_code, _ = _extract_book_and_remainder(raw)
    return {"result": parse_single_reference(raw), "book": book_code}


def _parse_citation_with_continuation(
    citation: str,
) -> tuple[list[dict[str, object]], list[str]]:
    from build.lib.citation_parser import _build_osis_entries

    parts = [part.strip() for part in _normalise_citation(citation).split(";")]
    results: list[dict[str, object]] = []
    errors: list[str] = []
    last_book_osis: str | None = None
    for part in parts:
        if not part:
            continue
        if re.match(r"^\d+:", part) and last_book_osis is not None:
            chapter, verse_portion = part.split(":", 1)
            results.append(
                {
                    "raw": part,
                    "osis": _build_osis_entries(
                        last_book_osis, chapter.strip(), verse_portion.strip()
                    ),
                }
            )
            continue
        try:
            parsed = _parse_single_with_book_tracking(part)
        except Exception as error:
            errors.append(part)
            last_book_osis = None
            log.warning("Could not parse reference %r: %s", part, error)
        else:
            results.append(parsed["result"])
            last_book_osis = parsed["book"]
    return results, errors


def parse_wsc_witness_document(html_path: Path) -> WscWitnessDocument:
    """Parse Q/A readings and emphasized proof references in one HTML pass."""

    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    qa_paragraphs = [
        paragraph
        for paragraph in soup.find_all("p")
        if paragraph.find("b")
        and paragraph.find("b").get_text(strip=True).startswith("Q.")
    ]
    rows: list[WscWitnessRow] = []
    parse_errors: dict[int, tuple[str, ...]] = {}
    without_proofs: list[int] = []
    for index, qa_paragraph in enumerate(qa_paragraphs, start=1):
        value = " ".join(qa_paragraph.get_text(" ", strip=True).split())
        match = re.match(r"^Q\.\s*(\d+)\.\s*(.*?)\s+A\.\s*(.*)$", value)
        if match is None or int(match.group(1)) != index:
            raise ValueError("WSC question labels are missing, duplicated, or out of order")
        sibling = qa_paragraph.find_next_sibling("p")
        proof_text = (
            " ".join(sibling.get_text(" ", strip=True).split())
            if sibling is not None
            else ""
        )
        emphasis = [] if sibling is None else sibling.find_all("em")
        if not emphasis:
            without_proofs.append(index)
            refs: list[dict[str, object]] = []
        else:
            citation_text = " ".join(
                fragment.get_text(" ", strip=True) for fragment in emphasis
            )
            if not citation_text:
                without_proofs.append(index)
                refs = []
            else:
                refs, errors = _parse_citation_with_continuation(citation_text)
                if errors:
                    parse_errors[index] = tuple(errors)
        rows.append(
            WscWitnessRow(
                number=index,
                question=match.group(2),
                answer=match.group(3),
                proof_text=proof_text,
                proofs=tuple(refs),
            )
        )
    return WscWitnessDocument(
        rows=tuple(rows),
        parse_errors=parse_errors,
        questions_without_proofs=tuple(without_proofs),
    )
