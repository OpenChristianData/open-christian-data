"""S0 ingest helpers for Schaff-Herzog page/leaf integrity checks."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from build.lib.nsh_leaf_model import expected_image_name, leaves_view


INTEGRITY_FLAG_KINDS = (
    "missing_leaf",
    "duplicate_leaf",
    "page_gap",
    "image_without_manifest_entry",
    "manifest_entry_without_image",
)


@dataclass(frozen=True)
class IntegrityFlag:
    volume: int
    kind: str
    detail: str

    def __post_init__(self) -> None:
        if self.kind not in INTEGRITY_FLAG_KINDS:
            raise ValueError(f"unknown integrity flag kind: {self.kind}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_volume_manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _page_sort_key(page_num: Any) -> tuple[int, int | str]:
    if isinstance(page_num, int):
        return (0, page_num)
    return (1, "" if page_num is None else str(page_num))


def build_page_leaf_bijection(manifest: dict) -> dict:
    # This is the manifest INTEGRITY checker -- it detects duplicate / missing
    # ia_leaf_id collisions. For the LEGACY shape it inspects raw pages[]/
    # unnumbered_leaves[] directly (the accessor de-overlaps and would HIDE the
    # anomalies this exists to flag). For the v4 leaf-sequence shape (P2), the
    # leaf spine is already de-overlapped and collision-free by construction, so
    # the body/unnumbered split is synthesized from leaves[] and fed through the
    # same collision logic (which then confirms uniqueness rather than finding it).
    if "leaves" in manifest:
        pages = []
        unnumbered_leaves = []
        for lf in manifest["leaves"]:
            # Key on leaf_num -- the unique primary-scan coordinate. An alternate-
            # sourced body leaf (Scenario B: bad primary image replaced from
            # haucgoog) carries the ALTERNATE item's ia_leaf_id, which numerically
            # collides with a primary leaf id; leaf_num never does (migration pins
            # it unique). Recovered no-leaf pages live in gaps[], never here.
            key = f"{lf['leaf_num']:04d}"
            if lf.get("kind") == "body" and isinstance(lf.get("page_num"), int):
                pages.append({"page_num": lf["page_num"], "ia_leaf_id": key})
            else:
                unnumbered_leaves.append({"leaf_num": lf["leaf_num"], "ia_leaf_id": key})
    else:
        pages = list(manifest.get("pages", []))  # nsh-legacy-read: integrity detector
        unnumbered_leaves = list(manifest.get("unnumbered_leaves", []))  # nsh-legacy-read: integrity detector
    leaf_entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    page_num_to_leaf_id: dict[str, str] = {}
    leaf_to_page_nums: dict[str, list[int | None]] = defaultdict(list)
    entries_missing_leaf_id: list[dict[str, Any]] = []

    for page in pages:
        page_num = page.get("page_num")
        # Skip alternate-sourced pages: their leaf IDs are in the alternate item's
        # namespace and collide with primary-scan leaf IDs by coincidence of numbering.
        if page.get("provenance") is not None:
            continue
        leaf_id = page.get("ia_leaf_id")
        if leaf_id is None:
            entries_missing_leaf_id.append({"entry_type": "page", "page_num": page_num})
            continue
        leaf_id = str(leaf_id)
        leaf_entries[leaf_id].append({"entry_type": "page", "entry": page})
        leaf_to_page_nums[leaf_id].append(page_num)
        if page_num is not None:
            page_num_to_leaf_id[str(page_num)] = leaf_id

    for leaf in unnumbered_leaves:
        leaf_id = leaf.get("ia_leaf_id")
        if leaf_id is None:
            entries_missing_leaf_id.append(
                {"entry_type": "unnumbered_leaf", "leaf_num": leaf.get("leaf_num")}
            )
            continue
        leaf_id = str(leaf_id)
        leaf_entries[leaf_id].append({"entry_type": "unnumbered_leaf", "entry": leaf})
        leaf_to_page_nums[leaf_id].append(None)

    duplicate_leaf_ids = sorted(
        leaf_id for leaf_id, entries in leaf_entries.items() if len(entries) > 1
    )

    page_nums = sorted(
        page["page_num"]
        for page in pages
        if isinstance(page.get("page_num"), int)
    )
    # A gap carrying an on-disk image (local_path) is a RECOVERED body page
    # (Scenario A: the primary scan skipped it, so it has no spine leaf -- schema
    # 4.1.0). It is present, not missing: drop it from the gap-set and count it as
    # present so the range-fill below does not re-flag it. (Note: gaps WITHOUT an
    # image -- unresolved / permanently_missing -- stay missing, including a page
    # that also has a thin resolved-gap entry; that pre-existing behaviour is
    # unchanged.)
    recovered_pages = {
        gap["page_num"]
        for gap in manifest.get("gaps", [])
        if isinstance(gap.get("page_num"), int) and gap.get("local_path")
    }
    missing_pages = {
        gap["page_num"]
        for gap in manifest.get("gaps", [])
        if isinstance(gap.get("page_num"), int)
    } - recovered_pages
    if page_nums:
        present = set(page_nums) | recovered_pages
        missing_pages.update(
            page_num
            for page_num in range(min(page_nums), max(page_nums) + 1)
            if page_num not in present
        )

    return {
        "volume": manifest.get("volume"),
        "leaves": {
            leaf_id: {
                "entry_count": len(entries),
                "page_nums": sorted(
                    leaf_to_page_nums[leaf_id],
                    key=_page_sort_key,
                ),
            }
            for leaf_id, entries in sorted(leaf_entries.items())
        },
        "leaf_to_page_nums": {
            leaf_id: sorted(page_nums, key=_page_sort_key)
            for leaf_id, page_nums in sorted(leaf_to_page_nums.items())
        },
        "page_num_to_leaf_id": dict(sorted(page_num_to_leaf_id.items(), key=lambda item: int(item[0]))),
        "duplicate_leaf_ids": duplicate_leaf_ids,
        "missing_pages": sorted(missing_pages),
        "manifest_warnings": list(manifest.get("manifest_warnings", [])),
        "entries_missing_leaf_id": entries_missing_leaf_id,
        "numbered_page_count": len(pages),
        "unnumbered_leaf_count": len(unnumbered_leaves),
        "total_leaf_count": len(pages) + len(unnumbered_leaves),
    }


def _raw_base(repo_root: Path) -> Path:
    return repo_root / "raw" / "internet-archive" / "schaff-herzog-pages"


def _volume_manifest_path(volume: int, repo_root: Path) -> Path:
    return _raw_base(repo_root) / f"vol_{volume:02d}.manifest.json"


def _volume_dir(volume: int, repo_root: Path) -> Path:
    return _raw_base(repo_root) / f"vol_{volume:02d}"


def _page_identifier(value: Any) -> str | None:
    if isinstance(value, int):
        return f"page_{value:04d}"
    if isinstance(value, str):
        stem = Path(value).stem
        if stem.startswith("page_"):
            return stem
        if value.isdigit():
            return f"page_{int(value):04d}"
    return None


def _lineage_has_data(payload: Any) -> bool:
    if payload is None:
        return False
    if isinstance(payload, dict):
        if "pages" in payload:
            return bool(payload["pages"])
        if "pages_with_data" in payload:
            value = payload["pages_with_data"]
            if isinstance(value, int):
                return value > 0
            return bool(value)
    if isinstance(payload, list):
        return bool(payload)
    return True


def _assembled_page_has_data(page: dict[str, Any]) -> bool:
    if "text" in page:
        return bool(page["text"])
    return any(
        value
        for key, value in page.items()
        if key not in {"page", "page_num", "page_id"}
    )


def available_engines_for_volume(volume: int, repo_root: Path) -> dict[str, list[str]]:
    available: dict[str, set[str]] = defaultdict(set)
    volume_dir = _volume_dir(volume, repo_root)

    if volume_dir.exists():
        for sidecar in sorted(volume_dir.glob("page_*.json")):
            parts = sidecar.name.split(".")
            if len(parts) < 3:
                continue
            page_id = parts[0]
            lineage = ".".join(parts[1:-1])
            if lineage:
                available[page_id].add(lineage)

    reference_root = (
        repo_root / "data" / "reference" / "schaff" / "encyclopedia" / "1908-1914"
    )
    if reference_root.exists():
        for lineage_dir in sorted(path for path in reference_root.iterdir() if path.is_dir()):
            assembled = lineage_dir / f"vol_{volume:02d}.json"
            if not assembled.exists():
                continue
            payload = json.loads(assembled.read_text(encoding="utf-8"))
            if not _lineage_has_data(payload):
                continue
            lineage = lineage_dir.name
            pages_with_data = (
                payload.get("pages_with_data", []) if isinstance(payload, dict) else []
            )
            if isinstance(pages_with_data, (list, tuple, set)):
                for page_value in pages_with_data:
                    page_id = _page_identifier(page_value)
                    if page_id is not None:
                        available[page_id].add(lineage)
            pages = payload.get("pages", []) if isinstance(payload, dict) else []
            for page in pages:
                if not isinstance(page, dict):
                    continue
                if not _assembled_page_has_data(page):
                    continue
                page_id = (
                    _page_identifier(page.get("page_id"))
                    or _page_identifier(page.get("page_num"))
                    or _page_identifier(page.get("page"))
                )
                if page_id is not None:
                    available[page_id].add(lineage)

    return {
        page_id: sorted(lineages)
        for page_id, lineages in sorted(available.items())
        if lineages
    }


def _expected_image_names(manifest: dict) -> set[str]:
    # Derive every expected image filename from the unified leaf view: body ->
    # page_NNNN.jpg, front/back -> leaf_NNNN.jpg (or local_path basename),
    # plate -> plate_*.jpg, discarded -> none. Works on both manifest shapes via
    # the accessor's legacy fallback (which de-overlaps the leading-run double-
    # record, so a reconstructed leading leaf is no longer also expected as a
    # leaf_*.jpg front-matter image).
    expected: set[str] = set()
    for leaf in leaves_view(manifest):
        name = expected_image_name(leaf)
        if name:
            expected.add(name)
    # Recovered no-leaf body pages (gaps[] with local_path, schema 4.1.0) have a
    # page_NNNN.jpg on disk but no leaf record, so leaves_view never yields them.
    # Add them so the on-disk orphan check does not false-flag a real recovery.
    for gap in manifest.get("gaps", []):
        if gap.get("local_path") and isinstance(gap.get("page_num"), int):
            expected.add(f"page_{gap['page_num']:04d}.jpg")
    return expected


def s0_integrity_check(volume: int, repo_root: Path) -> list[IntegrityFlag]:
    manifest = load_volume_manifest(_volume_manifest_path(volume, repo_root))
    bijection = build_page_leaf_bijection(manifest)
    flags: list[IntegrityFlag] = []

    for leaf_id in bijection["duplicate_leaf_ids"]:
        flags.append(
            IntegrityFlag(
                volume=volume,
                kind="duplicate_leaf",
                detail=f"ia_leaf_id {leaf_id} appears more than once",
            )
        )

    for page_num in bijection["missing_pages"]:
        flags.append(
            IntegrityFlag(
                volume=volume,
                kind="page_gap",
                detail=f"page_num {page_num} is listed as missing or absent from the run",
            )
        )

    for entry in bijection["entries_missing_leaf_id"]:
        flags.append(
            IntegrityFlag(
                volume=volume,
                kind="missing_leaf",
                detail=f"{entry['entry_type']} entry lacks ia_leaf_id: {entry}",
            )
        )

    volume_dir = _volume_dir(volume, repo_root)
    actual_images = {
        path.name
        for pattern in ("page_*.jpg", "leaf_*.jpg")
        for path in volume_dir.glob(pattern)
    } if volume_dir.exists() else set()
    expected_images = _expected_image_names(manifest)

    for image_name in sorted(expected_images - actual_images):
        flags.append(
            IntegrityFlag(
                volume=volume,
                kind="manifest_entry_without_image",
                detail=f"{image_name} is listed by manifest but not present on disk",
            )
        )

    for image_name in sorted(actual_images - expected_images):
        flags.append(
            IntegrityFlag(
                volume=volume,
                kind="image_without_manifest_entry",
                detail=f"{image_name} is present on disk but absent from manifest",
            )
        )

    return flags


def _volume_from_manifest_path(path: Path) -> int:
    stem = path.name.removesuffix(".manifest.json")
    return int(stem.removeprefix("vol_"))


def _manifest_paths(repo_root: Path) -> list[Path]:
    return sorted(_raw_base(repo_root).glob("vol_*.manifest.json"))


def corpus_page_count(repo_root: Path) -> dict:
    per_volume: dict[str, int] = {}
    corpus_numbered_page_count = 0
    corpus_total_leaf_count = 0

    for manifest_path in _manifest_paths(repo_root):
        manifest = load_volume_manifest(manifest_path)
        volume = manifest.get("volume")
        if not isinstance(volume, int):
            volume = _volume_from_manifest_path(manifest_path)
        bijection = build_page_leaf_bijection(manifest)
        numbered_count = bijection["numbered_page_count"]
        total_leaf_count = bijection["total_leaf_count"]
        per_volume[str(volume)] = numbered_count
        corpus_numbered_page_count += numbered_count
        corpus_total_leaf_count += total_leaf_count

    return {
        "per_volume": dict(sorted(per_volume.items(), key=lambda item: int(item[0]))),
        "corpus_numbered_page_count": corpus_numbered_page_count,
        "corpus_total_leaf_count": corpus_total_leaf_count,
    }


def integrity_flags_to_dicts(flags: list[IntegrityFlag]) -> list[dict[str, Any]]:
    return [flag.to_dict() for flag in flags]
