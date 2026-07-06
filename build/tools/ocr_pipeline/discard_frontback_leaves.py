"""Discard operator-classified NSH front/back junk leaves.

Dry-run is the default. ``--apply`` updates v4 source manifests, recycles
discarded images, and removes matching S1 ``leaf_NNNN.json`` sidecars.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from build.lib.nsh_leaf_model import back_matter, body_pages, expected_image_name, front_matter


DISCARD = {
    1: (range(0, 9), range(535, 541)),
    2: (range(0, 3), range(523, 529)),
    3: (range(0, 6), range(525, 531)),
    4: (range(0, 2), range(522, 523)),
    5: (range(0, 2), range(0, 0)),
    6: (range(1, 3), range(533, 535)),
    7: (range(0, 3), range(531, 533)),
    8: (range(0, 3), range(522, 523)),
    9: (range(0, 3), range(530, 534)),
    10: (range(0, 2), range(522, 529)),
    11: (range(0, 5), range(544, 545)),
    12: (range(0, 3), range(643, 645)),
    13: (range(0, 3), range(239, 241)),
}

MANIFEST_ROOT = Path("raw") / "internet-archive" / "schaff-herzog-pages"
SCHEMA_PATH = Path("schemas") / "v1" / "source_manifest.schema.json"
DISCARD_REASON = "non-content-frontback"


class BodyDiscardError(RuntimeError):
    """Raised when the discard config overlaps a body leaf."""


@dataclass(frozen=True)
class VolumeResult:
    volume: int
    discards: int = 0
    record_blanks: int = 0
    body_raises: int = 0
    already_discarded_skips: int = 0
    sidecars_removed: int = 0


def _discard_leaf_nums(volume: int) -> set[int]:
    front_range, back_range = DISCARD[volume]
    return set(front_range) | set(back_range)


def _manifest_path(repo_root: Path, volume: int) -> Path:
    return repo_root / MANIFEST_ROOT / f"vol_{volume:02d}.manifest.json"


def _volume_dir(repo_root: Path, volume: int) -> Path:
    return repo_root / MANIFEST_ROOT / f"vol_{volume:02d}"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_schema(repo_root: Path) -> dict:
    path = repo_root / SCHEMA_PATH
    if not path.exists():
        path = Path(__file__).resolve().parents[3] / SCHEMA_PATH
    return _load_json(path)


def _write_manifest_atomic(path: Path, manifest: dict, schema: dict) -> None:
    jsonschema.validate(instance=manifest, schema=schema)
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    try:
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _default_recycle(path: Path) -> None:
    helper = Path.home() / ".claude" / "hooks" / "recycle.py"
    subprocess.run(["py", "-3", str(helper), str(path.resolve())], check=True)


def _image_path(repo_root: Path, volume: int, leaf: dict) -> Path:
    local_path = leaf.get("local_path")
    if isinstance(local_path, str) and local_path:
        return repo_root / local_path
    image_name = expected_image_name(leaf)
    if image_name is None:
        raise ValueError(f"vol_{volume:02d} leaf {leaf.get('leaf_num')} has no expected image name")
    return _volume_dir(repo_root, volume) / image_name


def _matching_sidecars(repo_root: Path, volume: int, leaf_num: int) -> list[Path]:
    sidecar_root = repo_root / "reports" / "s1-sidecars"
    if not sidecar_root.exists():
        return []
    names = {f"leaf_{leaf_num}.json", f"leaf_{leaf_num:04d}.json"}
    matches: list[Path] = []
    for path in sidecar_root.glob(f"*/vol_{volume:02d}/pages/leaf_*.json"):
        if path.name in names:
            matches.append(path)
    return sorted(matches)


def _body_leaf_range(manifest: dict) -> set[int]:
    nums = [
        leaf["leaf_num"]
        for leaf in body_pages(manifest)
        if isinstance(leaf.get("leaf_num"), int)
    ]
    if not nums:
        return set()
    return set(range(min(nums), max(nums) + 1))


def _front_back_leaf_nums(manifest: dict) -> set[int]:
    return {
        leaf["leaf_num"]
        for leaf in front_matter(manifest) + back_matter(manifest)
        if isinstance(leaf.get("leaf_num"), int)
    }


def process_volume(
    repo_root: Path,
    volume: int,
    *,
    apply: bool,
    recycle_func: Callable[[Path], None] = _default_recycle,
    schema: dict | None = None,
) -> VolumeResult:
    repo_root = repo_root.resolve()
    manifest_path = _manifest_path(repo_root, volume)
    manifest = _load_json(manifest_path)
    if "leaves" not in manifest:
        raise ValueError(f"{manifest_path} is not a v4 leaves[] manifest")

    discard_nums = _discard_leaf_nums(volume)
    body_overlap = sorted(discard_nums & _body_leaf_range(manifest))
    if body_overlap:
        raise BodyDiscardError(
            f"vol_{volume:02d} discard list overlaps body leaf range: {body_overlap}"
        )

    front_back_nums = _front_back_leaf_nums(manifest)
    discards = 0
    record_blanks = 0
    already_discarded_skips = 0
    sidecars_removed = 0
    recycle_paths: list[Path] = []
    sidecars_to_remove: list[Path] = []
    changed = False

    for leaf in manifest["leaves"]:
        leaf_num = leaf.get("leaf_num")
        if not isinstance(leaf_num, int):
            continue
        if leaf.get("kind") == "discarded":
            already_discarded_skips += 1
            continue
        if leaf_num in front_back_nums and leaf.get("image_state") != "present":
            if leaf.get("blank") is not True:
                leaf["blank"] = True
                changed = True
            record_blanks += 1
            continue
        if leaf_num not in discard_nums or leaf_num not in front_back_nums:
            continue
        if leaf.get("image_state") != "present":
            if leaf.get("blank") is not True:
                leaf["blank"] = True
                changed = True
            record_blanks += 1
            continue

        image_path = _image_path(repo_root, volume, leaf)
        matching_sidecars = _matching_sidecars(repo_root, volume, leaf_num)
        recycle_paths.append(image_path)
        sidecars_to_remove.extend(matching_sidecars)
        discards += 1
        sidecars_removed += len(matching_sidecars)
        if apply:
            leaf["kind"] = "discarded"
            leaf["discard_reason"] = DISCARD_REASON
            leaf["image_state"] = "discarded"
            leaf.pop("local_path", None)
            changed = True

    if apply:
        for path in recycle_paths:
            recycle_func(path)
        for sidecar in sidecars_to_remove:
            sidecar.unlink()
        if changed:
            _write_manifest_atomic(manifest_path, manifest, schema or _load_schema(repo_root))

    return VolumeResult(
        volume=volume,
        discards=discards,
        record_blanks=record_blanks,
        already_discarded_skips=already_discarded_skips,
        sidecars_removed=sidecars_removed,
    )


def process_volumes(
    repo_root: Path,
    *,
    volumes: Iterable[int] | None = None,
    apply: bool = False,
    recycle_func: Callable[[Path], None] = _default_recycle,
) -> list[VolumeResult]:
    selected = list(volumes) if volumes is not None else sorted(DISCARD)
    schema = _load_schema(repo_root.resolve())
    return [
        process_volume(
            repo_root,
            volume,
            apply=apply,
            recycle_func=recycle_func,
            schema=schema,
        )
        for volume in selected
    ]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="plan only; default")
    mode.add_argument("--apply", action="store_true", help="write manifests and recycle files")
    parser.add_argument(
        "--volume",
        type=int,
        action="append",
        choices=sorted(DISCARD),
        help="limit to one volume; repeatable",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    apply_changes = bool(args.apply)
    results = process_volumes(Path.cwd(), volumes=args.volume, apply=apply_changes)
    mode = "APPLY" if apply_changes else "DRY RUN"
    print(f"{mode}: NSH front/back discard + record-blank")
    for result in results:
        print(
            f"vol_{result.volume:02d}: "
            f"discards={result.discards} "
            f"record_blanks={result.record_blanks} "
            f"body_raises={result.body_raises} "
            f"already_discarded_skips={result.already_discarded_skips} "
            f"sidecars_removed={result.sidecars_removed}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
