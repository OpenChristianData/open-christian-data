from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import shutil

import pytest

from build.tools import verify_whole_library_ticket_maps as verifier


PLAN_ROOT = Path(__file__).resolve().parents[1] / "plans" / "2026-08-26-whole-library-faithful-tei-completion"


@pytest.fixture(scope="module")
def actual_catalog():
    # Map mutations change only copied Markdown; verify the real library once.
    return verifier.collect_work_catalog(verifier.DEFAULT_DATA_ROOT)


@pytest.fixture(autouse=True)
def isolated_catalog(actual_catalog, monkeypatch):
    def unchanged_library(data_root):
        assert Path(data_root).resolve() == verifier.DEFAULT_DATA_ROOT.resolve()
        return deepcopy(actual_catalog)

    monkeypatch.setattr(verifier, "collect_work_catalog", unchanged_library)


@pytest.fixture
def map_paths(tmp_path: Path) -> dict[str, Path]:
    paths = {}
    for name in ("work", "source", "ledger"):
        source_name = {
            "work": "02-work-ticket-map.md",
            "source": "05-source-ticket-map.md",
            "ledger": "03-ticket-ledger.md",
        }[name]
        destination = tmp_path / source_name
        shutil.copy2(PLAN_ROOT / source_name, destination)
        paths[name] = destination
    return paths


def _replace_source_cell(
    path: Path,
    row: dict[str, object],
    *,
    source_hash: str | None = None,
    ticket: str | None = None,
    status: str | None = None,
) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    target = f"| `{row['work_id']}` |"
    for index, line in enumerate(lines):
        if not line.startswith(target) or f"`sha256:{row['digest']}`" not in line:
            continue
        newline = "\n" if line.endswith("\n") else ""
        cells = line.rstrip("\r\n").split("|")
        if source_hash is not None:
            cells[2] = f" `{source_hash}` "
        if ticket is not None:
            cells[3] = f" {ticket} "
        if status is not None:
            cells[4] = f" {status} "
        lines[index] = "|".join(cells) + newline
        path.write_text("".join(lines), encoding="utf-8", newline="")
        return
    raise AssertionError(f"source row not found for {row['work_id']}")


def _replace_work_id(path: Path, row: dict[str, object], value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    target = f"| `{row['work_id']}` |"
    for index, line in enumerate(lines):
        if not line.startswith(target):
            continue
        newline = "\n" if line.endswith("\n") else ""
        cells = line.rstrip("\r\n").split("|")
        cells[1] = f" `{value}` "
        lines[index] = "|".join(cells) + newline
        path.write_text("".join(lines), encoding="utf-8", newline="")
        return
    raise AssertionError(f"work row not found for {row['work_id']}")


def _replace_work_cell(path: Path, row: dict[str, object], value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    target = f"| `{row['work_id']}` |"
    for index, line in enumerate(lines):
        if not line.startswith(target):
            continue
        newline = "\n" if line.endswith("\n") else ""
        cells = line.rstrip("\r\n").split("|")
        cells[4] = f" {value} "
        lines[index] = "|".join(cells) + newline
        path.write_text("".join(lines), encoding="utf-8", newline="")
        return
    raise AssertionError(f"work row not found for {row['work_id']}")


def _replace_source_work_id(path: Path, original: str, value: str) -> None:
    text = path.read_text(encoding="utf-8")
    target = f"| `{original}` |"
    replacement = f"| `{value}` |"
    assert target in text
    path.write_text(text.replace(target, replacement), encoding="utf-8", newline="")


def _replace_ledger_work_count(path: Path, ticket: str, value: int) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    target = f"| {ticket} |"
    for index, line in enumerate(lines):
        if not line.startswith(target):
            continue
        newline = "\n" if line.endswith("\n") else ""
        cells = line.rstrip("\r\n").split("|")
        cells[3] = f" {value} "
        lines[index] = "|".join(cells) + newline
        path.write_text("".join(lines), encoding="utf-8", newline="")
        return
    raise AssertionError(f"ledger row not found for {ticket}")


def test_frozen_ticket_maps_pass_exact_accounting() -> None:
    result = verifier.verify_ticket_maps()

    assert result["work_rows"] == 402
    assert result["source_link_rows"] == 1045
    assert result["distinct_claims"] == 914
    assert result["non_placeholder_claims"] == 913
    assert result["placeholder_links"] == 2
    assert result["ledger_consistent"] is True
    assert result["work_catalog_consistent"] is True


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("duplicate_work", "duplicate work assignments"),
        ("phantom_work", "does not match WorkCatalog"),
        ("duplicate_link", "duplicate links"),
        ("ticket_mismatch", "ticket mismatch"),
        ("cross_ticket_hash", "cross ticket boundaries"),
        ("count_drift", "hash-claim count mismatch"),
        ("placeholder_scope", "placeholder hash must be limited"),
        ("ledger_mismatch", "ledger work count mismatch"),
        ("same_ticket_hash_swap", "does not match WorkCatalog link set"),
    ],
)
def test_frozen_ticket_maps_fail_closed_under_isolated_mutations(
    map_paths: dict[str, Path],
    mutation: str,
    expected: str,
) -> None:
    work_rows = verifier.parse_work_ticket_map(map_paths["work"])
    source_rows = verifier.parse_source_ticket_map(map_paths["source"])

    if mutation == "duplicate_work":
        _replace_work_id(map_paths["work"], work_rows[0], str(work_rows[1]["work_id"]))
    elif mutation == "phantom_work":
        original = str(work_rows[0]["work_id"])
        _replace_work_id(map_paths["work"], work_rows[0], "phantom-work")
        _replace_source_work_id(map_paths["source"], original, "phantom-work")
    elif mutation == "duplicate_link":
        first = next(
            row
            for row in source_rows
            if any(
                other["work_id"] == row["work_id"] and other["digest"] != row["digest"]
                for other in source_rows
            )
        )
        second = next(
            other
            for other in source_rows
            if other["work_id"] == first["work_id"]
            and other["digest"] != first["digest"]
        )
        _replace_source_cell(
            map_paths["source"],
            second,
            source_hash=f"sha256:{first['digest']}",
        )
    elif mutation == "ticket_mismatch":
        row = source_rows[0]
        alternate = "LIB-004" if row["ticket"] != "LIB-004" else "LIB-005"
        _replace_source_cell(map_paths["source"], row, ticket=alternate)
    elif mutation == "cross_ticket_hash":
        first = next(
            row
            for row in source_rows
            if row["digest"] != verifier.PLACEHOLDER_HASH
            and any(
                other["work_id"] != row["work_id"]
                and other["ticket"] != row["ticket"]
                and other["digest"] != verifier.PLACEHOLDER_HASH
                and all(
                    linked["digest"] != row["digest"]
                    for linked in source_rows
                    if linked["work_id"] == other["work_id"]
                )
                for other in source_rows
            )
        )
        second = next(
            other
            for other in source_rows
            if other["work_id"] != first["work_id"]
            and other["ticket"] != first["ticket"]
            and other["digest"] != verifier.PLACEHOLDER_HASH
            and all(
                linked["digest"] != first["digest"]
                for linked in source_rows
                if linked["work_id"] == other["work_id"]
            )
        )
        _replace_source_cell(
            map_paths["source"],
            second,
            source_hash=f"sha256:{first['digest']}",
        )
    elif mutation == "count_drift":
        row = next(row for row in work_rows if row["hash_claims"] > 0)
        _replace_work_cell(map_paths["work"], row, str(int(row["hash_claims"]) - 1))
    elif mutation == "placeholder_scope":
        row = next(row for row in source_rows if row["digest"] != verifier.PLACEHOLDER_HASH)
        _replace_source_cell(
            map_paths["source"],
            row,
            source_hash=f"sha256:{verifier.PLACEHOLDER_HASH}",
            status="placeholder-repair-required",
        )
    elif mutation == "ledger_mismatch":
        ledger = verifier.parse_ticket_ledger(map_paths["ledger"])
        _replace_ledger_work_count(
            map_paths["ledger"], "LIB-004", ledger["LIB-004"]["works"] + 1
        )
    else:
        first = next(
            row
            for row in source_rows
            if row["digest"] != verifier.PLACEHOLDER_HASH
            and any(
                other["ticket"] == row["ticket"]
                and other["work_id"] != row["work_id"]
                and other["digest"] != row["digest"]
                and all(
                    linked["digest"] != row["digest"]
                    for linked in source_rows
                    if linked["work_id"] == other["work_id"]
                )
                and all(
                    linked["digest"] != other["digest"]
                    for linked in source_rows
                    if linked["work_id"] == row["work_id"]
                )
                for other in source_rows
            )
        )
        second = next(
            other
            for other in source_rows
            if other["ticket"] == first["ticket"]
            and other["work_id"] != first["work_id"]
            and other["digest"] != first["digest"]
            and all(
                linked["digest"] != first["digest"]
                for linked in source_rows
                if linked["work_id"] == other["work_id"]
            )
            and all(
                linked["digest"] != other["digest"]
                for linked in source_rows
                if linked["work_id"] == first["work_id"]
            )
        )
        first_digest = str(first["digest"])
        second_digest = str(second["digest"])
        _replace_source_cell(
            map_paths["source"], first, source_hash=f"sha256:{second_digest}"
        )
        _replace_source_cell(
            map_paths["source"], second, source_hash=f"sha256:{first_digest}"
        )

    with pytest.raises(verifier.MapVerificationError, match=re.escape(expected)):
        verifier.verify_ticket_maps(
            map_paths["work"], map_paths["source"], map_paths["ledger"]
        )
