"""Classify NSH recovered-gap pages from disk truth.

The classifier reads page images and S1 sidecars under reports/ to decide page
classes. Manifest gap status strings are intentionally ignored; gaps[] only
defines expected recovered-gap page numbers and whether a stale gap record still
exists for a keyed page.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.nsh_leaf_model import body_pages  # noqa: E402
from build.lib.ocr_store_paths import s1_sidecars_root  # noqa: E402

PRIMARY_LINEAGES = (
    "tesseract-py314-v1",
    "kraken-py312-v1",
    "surya-py312-v1",
    "kraken-greek-py312-v1",
)

CLASS_KEYS = ("keyless_ocrd", "stale_gap_record", "image_not_ocrd", "true_hole")
PAGE_SIDECAR_RE = re.compile(r"^page_(\d{4})\.json$")


def classify_page(
    *,
    sidecar_present: bool,
    sidecar_clid: int | None,
    img_present: bool,
    gap_present: bool,
) -> str:
    """Classify one candidate page from disk-observed booleans."""
    if sidecar_present and sidecar_clid is None:
        return "keyless_ocrd"
    if sidecar_present and isinstance(sidecar_clid, int) and gap_present:
        return "stale_gap_record"
    if not sidecar_present and gap_present and img_present:
        return "image_not_ocrd"
    if not sidecar_present and gap_present and not img_present:
        return "true_hole"
    if sidecar_present and isinstance(sidecar_clid, int) and not gap_present:
        return "ok"
    return "ok"


def classify_volume(manifest: dict[str, Any], repo_root: Path = REPO_ROOT) -> dict[str, list[int]]:
    """Return headline defect buckets for one NSH volume."""
    buckets: dict[str, list[int]] = {key: [] for key in CLASS_KEYS}
    for detail in classify_volume_details(manifest, repo_root):
        page_class = detail["class"]
        if page_class in buckets:
            buckets[page_class].append(detail["page_num"])
    for pages in buckets.values():
        pages.sort()
    return buckets


def classify_volume_details(manifest: dict[str, Any], repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    """Return one disk-derived detail record per recovered-gap candidate."""
    repo_root = Path(repo_root)
    volume = _volume_number(manifest)
    gap_pages = _gap_pages(manifest)
    candidates = gap_pages | _page_sidecar_candidates(repo_root, volume)
    last_body_page = _last_body_page(manifest)

    details = []
    for page_num in sorted(candidates):
        native_id = f"page_{page_num:04d}"
        image_path = _image_path(repo_root, volume, page_num)
        img_present = image_path.exists()
        sidecar_records = _read_page_sidecars(repo_root, volume, page_num)
        sidecar_engines = [record["lineage"] for record in sidecar_records]
        sidecar_clid = _first_int_clid(sidecar_records)
        gap_present = page_num in gap_pages
        page_class = classify_page(
            sidecar_present=bool(sidecar_records),
            sidecar_clid=sidecar_clid,
            img_present=img_present,
            gap_present=gap_present,
        )
        details.append(
            {
                "volume": volume,
                "page_num": page_num,
                "page_native_id": native_id,
                "class": page_class,
                "img_present": img_present,
                "img_size": image_path.stat().st_size if img_present else None,
                "sidecar_present": bool(sidecar_records),
                "sidecar_engines": sidecar_engines,
                "sidecar_clid": sidecar_clid,
                "gap_present": gap_present,
                "last_body_page": last_body_page,
                "out_of_range": (
                    page_class == "true_hole"
                    and isinstance(last_body_page, int)
                    and page_num > last_body_page
                ),
            }
        )
    return details


def classify_all(repo_root: Path = REPO_ROOT, volumes: list[int] | None = None) -> dict[str, Any]:
    """Classify selected volumes from manifests on disk."""
    repo_root = Path(repo_root)
    selected = volumes if volumes is not None else list(range(1, 14))
    volume_reports = []
    totals = _empty_counts()
    ok_keyed = 0
    for volume in selected:
        manifest = load_manifest(repo_root, volume)
        details = classify_volume_details(manifest, repo_root)
        counts = _count_details(details)
        ok_keyed += counts["ok_keyed"]
        for key in CLASS_KEYS:
            totals[key] += counts[key]
        volume_reports.append({"volume": volume, "counts": counts, "details": details})
    return {"volumes": volume_reports, "totals": totals, "ok_keyed": ok_keyed}


def load_manifest(repo_root: Path, volume: int) -> dict[str, Any]:
    """Load one source manifest, failing clearly if absent or malformed."""
    path = (
        Path(repo_root)
        / "raw"
        / "internet-archive"
        / "schaff-herzog-pages"
        / f"vol_{volume:02d}.manifest.json"
    )
    if not path.exists():
        raise FileNotFoundError(f"missing NSH manifest: {path}")
    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest is not a JSON object: {path}")
    return manifest


def print_report(report: dict[str, Any]) -> None:
    """Print a compact ASCII report."""
    print("=== page-class reconciler ===")
    for volume_report in report["volumes"]:
        counts = volume_report["counts"]
        print(
            f"vol_{volume_report['volume']:02d}: "
            f"keyless_ocrd={counts['keyless_ocrd']} "
            f"stale_gap_record={counts['stale_gap_record']} "
            f"image_not_ocrd={counts['image_not_ocrd']} "
            f"true_hole={counts['true_hole']} "
            f"ok_keyed={counts['ok_keyed']}"
        )
        for detail in volume_report["details"]:
            if detail["class"] == "ok":
                continue
            suffix = " out_of_range=true" if detail["out_of_range"] else ""
            print(
                f"  {detail['page_native_id']}: {detail['class']} "
                f"image={_yes_no(detail['img_present'])} "
                f"sidecars={','.join(detail['sidecar_engines']) or '-'} "
                f"clid={detail['sidecar_clid']} "
                f"gap={_yes_no(detail['gap_present'])}{suffix}"
            )
    totals = report["totals"]
    print(
        "TOTAL: "
        f"keyless_ocrd={totals['keyless_ocrd']} "
        f"stale_gap_record={totals['stale_gap_record']} "
        f"image_not_ocrd={totals['image_not_ocrd']} "
        f"true_hole={totals['true_hole']} "
        f"ok_keyed={report['ok_keyed']}"
    )


def selftest() -> int:
    """Pure decision-tree selftest for CLI smoke checks."""
    cases = [
        ("keyless", "keyless_ocrd", dict(sidecar_present=True, sidecar_clid=None, img_present=True, gap_present=True)),
        ("stale", "stale_gap_record", dict(sidecar_present=True, sidecar_clid=1, img_present=True, gap_present=True)),
        ("image", "image_not_ocrd", dict(sidecar_present=False, sidecar_clid=None, img_present=True, gap_present=True)),
        ("hole", "true_hole", dict(sidecar_present=False, sidecar_clid=None, img_present=False, gap_present=True)),
        ("keyed-clean", "ok", dict(sidecar_present=True, sidecar_clid=1, img_present=True, gap_present=False)),
    ]
    ok = True
    for label, expected, kwargs in cases:
        got = classify_page(**kwargs)
        if got == expected:
            print(f"SELFTEST PASS: {label}")
        else:
            print(f"SELFTEST FAIL: {label} -> {got!r}, want {expected!r}")
            ok = False
    return 0 if ok else 1


def _volume_number(manifest: dict[str, Any]) -> int:
    volume = manifest.get("volume")
    if isinstance(volume, int):
        return volume
    if isinstance(volume, str) and volume.isdigit():
        return int(volume)
    raise ValueError("manifest must carry an integer volume field")


def _gap_pages(manifest: dict[str, Any]) -> set[int]:
    return {
        gap["page_num"]
        for gap in manifest.get("gaps", [])
        if isinstance(gap, dict) and isinstance(gap.get("page_num"), int)
    }


def _page_sidecar_candidates(repo_root: Path, volume: int) -> set[int]:
    candidates: set[int] = set()
    root = s1_sidecars_root(repo_root)
    for lineage in PRIMARY_LINEAGES:
        pages_dir = root / lineage / f"vol_{volume:02d}" / "pages"
        if not pages_dir.is_dir():
            continue
        for path in pages_dir.glob("page_*.json"):
            match = PAGE_SIDECAR_RE.fullmatch(path.name)
            if match:
                candidates.add(int(match.group(1)))
    return candidates


def _read_page_sidecars(repo_root: Path, volume: int, page_num: int) -> list[dict[str, Any]]:
    records = []
    root = s1_sidecars_root(repo_root)
    for lineage in PRIMARY_LINEAGES:
        path = root / lineage / f"vol_{volume:02d}" / "pages" / f"page_{page_num:04d}.json"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"sidecar is not a JSON object: {path}")
        records.append({"lineage": lineage, "path": path, "payload": payload})
    return records


def _first_int_clid(sidecar_records: list[dict[str, Any]]) -> int | None:
    for record in sidecar_records:
        clid = record["payload"].get("canonical_leaf_id")
        if isinstance(clid, int):
            return clid
    return None


def _last_body_page(manifest: dict[str, Any]) -> int | None:
    pages = [leaf.get("page_num") for leaf in body_pages(manifest)]
    ints = [page for page in pages if isinstance(page, int)]
    return max(ints) if ints else None


def _image_path(repo_root: Path, volume: int, page_num: int) -> Path:
    return (
        repo_root
        / "raw"
        / "internet-archive"
        / "schaff-herzog-pages"
        / f"vol_{volume:02d}"
        / f"page_{page_num:04d}.jpg"
    )


def _empty_counts() -> dict[str, int]:
    return {key: 0 for key in CLASS_KEYS}


def _count_details(details: list[dict[str, Any]]) -> dict[str, int]:
    counts = _empty_counts()
    ok_keyed = 0
    for detail in details:
        page_class = detail["class"]
        if page_class in counts:
            counts[page_class] += 1
        elif (
            page_class == "ok"
            and detail["sidecar_present"]
            and isinstance(detail["sidecar_clid"], int)
            and not detail["gap_present"]
        ):
            ok_keyed += 1
    counts["ok_keyed"] = ok_keyed
    return counts


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _parse_volume(raw: str) -> int:
    volume = int(raw)
    if not 1 <= volume <= 13:
        raise argparse.ArgumentTypeError("volume must be between 1 and 13")
    return volume


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile NSH recovered-gap page classes from disk truth.")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--volume", type=_parse_volume, help="Classify one volume number, 1..13.")
    scope.add_argument("--all", action="store_true", help="Classify all NSH volumes.")
    scope.add_argument("--selftest", action="store_true", help="Run pure decision-tree selftest.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    repo_root = Path(args.repo_root)
    if args.volume is not None:
        report = classify_all(repo_root, volumes=[args.volume])
    elif args.all:
        report = classify_all(repo_root)
    else:
        parser.error("choose --volume N, --all, or --selftest")
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
