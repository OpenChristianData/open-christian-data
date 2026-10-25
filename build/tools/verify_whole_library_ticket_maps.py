"""Verify the frozen whole-library work and source-ticket maps exactly."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Any

from build.tools.count_dataset_records import collect_work_catalog


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_ROOT = REPO_ROOT / "plans" / "2026-08-26-whole-library-faithful-tei-completion"
DEFAULT_WORK_MAP = PLAN_ROOT / "02-work-ticket-map.md"
DEFAULT_SOURCE_MAP = PLAN_ROOT / "05-source-ticket-map.md"
DEFAULT_LEDGER = PLAN_ROOT / "03-ticket-ledger.md"
DEFAULT_DATA_ROOT = REPO_ROOT / "data"

EXPECTED_WORKS = 402
EXPECTED_LINKS = 1045
EXPECTED_DISTINCT_CLAIMS = 914
PLACEHOLDER_HASH = "0" * 64
PLACEHOLDER_WORKS = frozenset(
    {"luther-lenker-sermons", "newman-parochial-sermons"}
)
DELIVERY_TICKETS = frozenset(
    {"LIB-002", *(f"LIB-{number:03d}" for number in range(4, 90))}
)
UNASSIGNED_TICKETS = frozenset({"LIB-001", "LIB-003", "LIB-090"})
ALL_LIBRARY_TICKETS = DELIVERY_TICKETS | UNASSIGNED_TICKETS
_TICKET_RE = re.compile(r"^LIB-[0-9]{3}$")
_HASH_RE = re.compile(r"^sha256:([0-9a-f]{64})$")


class MapVerificationError(ValueError):
    """Raised when a frozen coverage map violates the library contract."""


def _cell(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == "`" and text[-1] == "`":
        return text[1:-1]
    return text


def _table_rows(
    path: Path,
    columns: int,
    label: str,
    *,
    stop_prefix: str | None = None,
) -> list[list[str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MapVerificationError(f"{label} is unavailable: {path}") from exc
    rows: list[list[str]] = []
    for line_number, line in enumerate(lines, start=1):
        if stop_prefix is not None and line.startswith(stop_prefix):
            break
        if not line.lstrip().startswith("|"):
            continue
        values = line.strip().strip("|").split("|")
        if values and all(set(value.strip()) <= {"-", ":"} for value in values):
            continue
        cells = [_cell(value) for value in values]
        if not cells:
            continue
        if cells[0] in {"Work ID", "Ticket", "Work ID | Source hash claim"}:
            continue
        if len(cells) != columns:
            raise MapVerificationError(
                f"{label} row {line_number} has {len(cells)} columns; expected {columns}"
            )
        rows.append(cells)
    return rows


def parse_work_ticket_map(path: str | Path = DEFAULT_WORK_MAP) -> list[dict[str, Any]]:
    """Parse work assignments from the frozen Markdown map."""

    rows = _table_rows(Path(path), 5, "work-ticket map")
    parsed: list[dict[str, Any]] = []
    for index, (work_id, title, ticket, claims, scope) in enumerate(rows, start=1):
        if not work_id:
            raise MapVerificationError(f"work-ticket map row {index} has an empty work ID")
        if not _TICKET_RE.fullmatch(ticket):
            raise MapVerificationError(f"work-ticket map row {index} has invalid ticket {ticket!r}")
        if ticket not in ALL_LIBRARY_TICKETS:
            raise MapVerificationError(f"work-ticket map row {index} has unknown ticket {ticket}")
        try:
            claim_count = int(claims)
        except ValueError as exc:
            raise MapVerificationError(
                f"work-ticket map row {index} has invalid hash-claim count {claims!r}"
            ) from exc
        if claim_count < 0:
            raise MapVerificationError(f"work-ticket map row {index} has a negative hash-claim count")
        parsed.append(
            {
                "work_id": work_id,
                "title": title,
                "ticket": ticket,
                "hash_claims": claim_count,
                "scope": scope,
            }
        )
    return parsed


def parse_source_ticket_map(path: str | Path = DEFAULT_SOURCE_MAP) -> list[dict[str, Any]]:
    """Parse work-source links from the frozen Markdown map."""

    rows = _table_rows(Path(path), 4, "source-ticket map")
    parsed: list[dict[str, Any]] = []
    for index, (work_id, source_hash, ticket, status) in enumerate(rows, start=1):
        match = _HASH_RE.fullmatch(source_hash)
        if match is None:
            raise MapVerificationError(
                f"source-ticket map row {index} has invalid source hash {source_hash!r}"
            )
        if not _TICKET_RE.fullmatch(ticket):
            raise MapVerificationError(f"source-ticket map row {index} has invalid ticket {ticket!r}")
        if ticket not in ALL_LIBRARY_TICKETS:
            raise MapVerificationError(f"source-ticket map row {index} has unknown ticket {ticket}")
        if status not in {"current-claim", "placeholder-repair-required"}:
            raise MapVerificationError(
                f"source-ticket map row {index} has invalid status {status!r}"
            )
        digest = match.group(1)
        if digest == PLACEHOLDER_HASH and status != "placeholder-repair-required":
            raise MapVerificationError(
                f"source-ticket map row {index} uses the placeholder hash as a current claim"
            )
        if digest != PLACEHOLDER_HASH and status != "current-claim":
            raise MapVerificationError(
                f"source-ticket map row {index} marks a non-placeholder hash for repair"
            )
        parsed.append(
            {
                "work_id": work_id,
                "source_hash": source_hash,
                "digest": digest,
                "ticket": ticket,
                "status": status,
            }
        )
    return parsed


def parse_ticket_ledger(path: str | Path = DEFAULT_LEDGER) -> dict[str, dict[str, Any]]:
    """Parse library ticket counts from the ticket ledger table."""

    rows = _table_rows(Path(path), 6, "ticket ledger", stop_prefix="## CVW")
    ledger: dict[str, dict[str, Any]] = {}
    for index, (ticket, objective, works, claims, dependencies, definition) in enumerate(
        rows, start=1
    ):
        if not _TICKET_RE.fullmatch(ticket):
            continue
        if ticket in ledger:
            raise MapVerificationError(f"ticket ledger repeats {ticket}")
        try:
            work_count = int(works)
            claim_count = int(claims)
        except ValueError as exc:
            raise MapVerificationError(
                f"ticket ledger row {index} has invalid numeric counts"
            ) from exc
        ledger[ticket] = {
            "objective": objective,
            "works": work_count,
            "claims": claim_count,
            "dependencies": dependencies,
            "definition": definition,
        }
    return ledger


def verify_ticket_maps(
    work_map_path: str | Path = DEFAULT_WORK_MAP,
    source_map_path: str | Path = DEFAULT_SOURCE_MAP,
    ledger_path: str | Path = DEFAULT_LEDGER,
    data_root: str | Path = DEFAULT_DATA_ROOT,
) -> dict[str, Any]:
    """Verify exact work/link assignment and ledger consistency."""

    work_rows = parse_work_ticket_map(work_map_path)
    source_rows = parse_source_ticket_map(source_map_path)
    ledger = parse_ticket_ledger(ledger_path)
    if len(work_rows) != EXPECTED_WORKS:
        raise MapVerificationError(
            f"work-ticket map has {len(work_rows)} rows; expected {EXPECTED_WORKS}"
        )
    if len(source_rows) != EXPECTED_LINKS:
        raise MapVerificationError(
            f"source-ticket map has {len(source_rows)} rows; expected {EXPECTED_LINKS}"
        )
    work_ids = [row["work_id"] for row in work_rows]
    duplicate_work_ids = sorted(
        work_id for work_id, count in Counter(work_ids).items() if count != 1
    )
    if duplicate_work_ids:
        raise MapVerificationError(
            f"work-ticket map has duplicate work assignments: {', '.join(duplicate_work_ids)}"
        )
    assignments = {row["work_id"]: row for row in work_rows}
    source_keys = [(row["work_id"], row["digest"]) for row in source_rows]
    duplicate_links = sorted(
        f"{work_id}:{digest}"
        for (work_id, digest), count in Counter(source_keys).items()
        if count != 1
    )
    if duplicate_links:
        raise MapVerificationError(
            "source-ticket map has duplicate links: " + ", ".join(duplicate_links[:5])
        )
    unknown_source_works = sorted(
        {row["work_id"] for row in source_rows if row["work_id"] not in assignments}
    )
    if unknown_source_works:
        raise MapVerificationError(
            "source-ticket map has unknown work IDs: " + ", ".join(unknown_source_works)
        )
    source_by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in source_rows:
        source_by_work[row["work_id"]].append(row)
        expected_ticket = assignments[row["work_id"]]["ticket"]
        if row["ticket"] != expected_ticket:
            raise MapVerificationError(
                f"source-ticket map ticket mismatch for {row['work_id']}: "
                f"{row['ticket']} != {expected_ticket}"
            )
    missing_source_works = sorted(set(assignments) - set(source_by_work))
    if missing_source_works:
        raise MapVerificationError(
            "source-ticket map is missing work IDs: " + ", ".join(missing_source_works)
        )
    for work_id, assignment in assignments.items():
        observed = len(source_by_work[work_id])
        if observed != assignment["hash_claims"]:
            raise MapVerificationError(
                f"hash-claim count mismatch for {work_id}: {observed} != {assignment['hash_claims']}"
            )
    hash_tickets: dict[str, set[str]] = defaultdict(set)
    for row in source_rows:
        hash_tickets[row["digest"]].add(row["ticket"])
    split_hashes = sorted(
        digest
        for digest, tickets in hash_tickets.items()
        if digest != PLACEHOLDER_HASH and len(tickets) != 1
    )
    if split_hashes:
        raise MapVerificationError(
            "non-placeholder source hashes cross ticket boundaries: "
            + ", ".join(split_hashes[:5])
        )
    placeholder_rows = [row for row in source_rows if row["digest"] == PLACEHOLDER_HASH]
    if {row["work_id"] for row in placeholder_rows} != set(PLACEHOLDER_WORKS):
        raise MapVerificationError(
            "placeholder hash must be limited to the reviewed Luther and Newman links"
        )
    if {row["ticket"] for row in placeholder_rows} != {"LIB-018", "LIB-019"}:
        raise MapVerificationError("placeholder hash ticket assignment is inconsistent")
    if len({row["digest"] for row in source_rows}) != EXPECTED_DISTINCT_CLAIMS:
        raise MapVerificationError(
            "source-ticket map distinct claim count is inconsistent: "
            f"{len({row['digest'] for row in source_rows})} != {EXPECTED_DISTINCT_CLAIMS}"
        )
    if sum(row["hash_claims"] for row in work_rows) != EXPECTED_LINKS:
        raise MapVerificationError("work-ticket map claim totals do not equal source-link rows")
    if set(ledger) != ALL_LIBRARY_TICKETS:
        missing = sorted(ALL_LIBRARY_TICKETS - set(ledger))
        extra = sorted(set(ledger) - ALL_LIBRARY_TICKETS)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unknown " + ", ".join(extra))
        raise MapVerificationError("ticket ledger ticket set mismatch: " + "; ".join(detail))
    work_counts = Counter(row["ticket"] for row in work_rows)
    link_counts = Counter(row["ticket"] for row in source_rows)
    claim_counts = Counter()
    for ticket in ALL_LIBRARY_TICKETS:
        claim_counts[ticket] = len(
            {row["digest"] for row in source_rows if row["ticket"] == ticket}
        )
    for ticket in ALL_LIBRARY_TICKETS:
        expected = ledger[ticket]
        if expected["works"] != work_counts[ticket]:
            raise MapVerificationError(
                f"ledger work count mismatch for {ticket}: {work_counts[ticket]} != {expected['works']}"
            )
        if expected["claims"] != claim_counts[ticket]:
            raise MapVerificationError(
                f"ledger distinct-claim count mismatch for {ticket}: "
                f"{claim_counts[ticket]} != {expected['claims']}"
            )
        if link_counts[ticket] != sum(
            row["hash_claims"] for row in work_rows if row["ticket"] == ticket
        ):
            raise MapVerificationError(f"work/source link totals disagree for {ticket}")
    if any(work_counts[ticket] or link_counts[ticket] for ticket in UNASSIGNED_TICKETS):
        raise MapVerificationError("foundation/integration tickets must have no work assignments")
    catalog = collect_work_catalog(Path(data_root))
    catalog_work_ids = {str(work["work_id"]) for work in catalog.works}
    if catalog_work_ids != set(assignments):
        missing = sorted(catalog_work_ids - set(assignments))
        extra = sorted(set(assignments) - catalog_work_ids)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing[:5]))
        if extra:
            detail.append("unknown " + ", ".join(extra[:5]))
        raise MapVerificationError("work-ticket map does not match WorkCatalog: " + "; ".join(detail))
    catalog_links: set[tuple[str, str]] = set()
    for work in catalog.works:
        for value in work.get("metadata_fields", {}).get("provenance.source_hash", []):
            text = str(value).casefold()
            match = _HASH_RE.fullmatch(text)
            if match is not None:
                catalog_links.add((str(work["work_id"]), match.group(1)))
    source_links = {(str(row["work_id"]), str(row["digest"])) for row in source_rows}
    if catalog_links != source_links:
        missing = sorted(catalog_links - source_links)
        extra = sorted(source_links - catalog_links)
        detail = []
        if missing:
            detail.append(
                "missing " + ", ".join(f"{work_id}:{digest}" for work_id, digest in missing[:3])
            )
        if extra:
            detail.append(
                "unexpected " + ", ".join(f"{work_id}:{digest}" for work_id, digest in extra[:3])
            )
        raise MapVerificationError(
            "source-ticket map does not match WorkCatalog link set: " + "; ".join(detail)
        )
    return {
        "work_rows": len(work_rows),
        "source_link_rows": len(source_rows),
        "distinct_claims": len({row["digest"] for row in source_rows}),
        "non_placeholder_claims": len(
            {row["digest"] for row in source_rows if row["digest"] != PLACEHOLDER_HASH}
        ),
        "placeholder_links": len(placeholder_rows),
        "delivery_tickets": sorted(DELIVERY_TICKETS),
        "unassigned_tickets": sorted(UNASSIGNED_TICKETS),
        "ledger_consistent": True,
        "work_catalog_consistent": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-map", type=Path, default=DEFAULT_WORK_MAP)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args(argv)
    try:
        result = verify_ticket_maps(args.work_map, args.source_map, args.ledger)
    except MapVerificationError as exc:
        print(f"MAP VERIFICATION FAILED: {exc}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
