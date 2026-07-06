"""build/lib/page_order.py
Manifest-aware page ordering for Internet Archive Schaff-Herzog volumes.

vol_01 has a page_order.json manifest (52 leaf_*.jpg + 491 page_*.jpg);
vols 02-13 have only page_*.jpg and no manifest. All helpers fall back to
the previous glob-based behaviour when no manifest is present, so nothing
changes for vols 02-13.

Three public helpers:
  volume_image_paths(vol_dir, include_front_back=False) -- for OCR runners
  volume_sidecar_files(vol_dir, sfx)  -- for normalizers (Azure, ABBYY)
  volume_assembly_records(vol_dir, sfx) -- for assemble_volume_json
"""
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from build.lib.nsh_leaf_model import expected_image_name, ocr_input  # noqa: E402


def _load_manifest(vol_dir: Path) -> list[dict] | None:
    p = vol_dir / "page_order.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        pages = data["pages"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"Malformed page_order.json at {p}: {exc}") from exc
    return pages


def _source_manifest_path(vol_dir: Path) -> Path:
    """The vol_NN.manifest.json sitting beside the vol_NN/ image dir."""
    return vol_dir.parent / f"{vol_dir.name}.manifest.json"


def _front_back_image_paths(vol_dir: Path, manifest: dict) -> list[Path]:
    result: list[Path] = []
    for leaf in ocr_input(manifest, include_front_back=True):
        if leaf.get("kind") not in {"front_matter", "back_matter"}:
            continue
        if leaf.get("image_state") != "present":
            continue
        if leaf.get("blank") is True:
            continue
        name = expected_image_name(leaf)
        if not name:
            continue
        path = vol_dir / name
        if path.exists():
            result.append(path)
    return sorted(result)


def volume_image_paths(vol_dir: Path, *, include_front_back: bool = False) -> list[Path]:
    """Return the OCR-input JPEG paths in canonical physical order.

    Selection by kind, not by a broad glob (R-ocr-glob, design SS3): body leaves
    feed the OCR engines by default. Kept front/back leaves are appended only
    when ``include_front_back=True`` so non-NSH and hermetic callers keep their
    body-only behavior. Three body sources, in priority order:

    1. page_order.json when present (vol_01-style): body/front entries by file,
       duplicate-role excluded. Unchanged; P2 regenerates it from leaves[].
    2. The source manifest (vol_NN.manifest.json): ``ocr_input(manifest)`` ->
       body leaves only, mapped to their page_NNNN.jpg and filtered to disk.
       Works on both manifest shapes via the accessor's legacy fallback.
    3. Last-resort (neither file present, e.g. hermetic dirs): the body namespace
       page_*.jpg / page_*.jpeg -- NEVER leaf_* / plate_*.
    """
    manifest_path = _source_manifest_path(vol_dir)

    pages = _load_manifest(vol_dir)
    if pages is not None:
        result = []
        for entry in pages:
            if entry.get("corpus_role") == "duplicate":
                continue
            if not entry.get("file"):  # null for unresolved/front/back-matter
                continue
            p = vol_dir / entry["file"]
            if p.exists():
                result.append(p)
        if not include_front_back or not manifest_path.exists():
            return result
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return result + _front_back_image_paths(vol_dir, manifest)

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        result = []
        for leaf in ocr_input(manifest):
            name = expected_image_name(leaf)
            if name:
                p = vol_dir / name
                if p.exists():
                    result.append(p)
        body = sorted(result)
        if not include_front_back:
            return body
        return body + _front_back_image_paths(vol_dir, manifest)

    return sorted([*vol_dir.glob("page_*.jpg"), *vol_dir.glob("page_*.jpeg")])


def volume_sidecar_files(
    vol_dir: Path,
    suffix: str,
) -> list[tuple[int, str, Path]]:
    """Return (seq, page_native_id, sidecar_path) in canonical physical order.

    seq:            manifest seq number (1-based physical position) when
                    manifest is present; filename digit for fallback volumes.
    page_native_id: file stem, e.g. "leaf_0037" or "page_0010".
    sidecar_path:   path to the sidecar file.

    suffix: the extension portion after the stem, e.g. "azure.json" or
            "ia-abbyy.json" (the guard against sibling variants such as
            -haucgoog is enforced here, not by the caller).

    Only entries whose sidecar exists on disk are included.
    Duplicate-role entries are excluded.
    """
    pages = _load_manifest(vol_dir)
    if pages is not None:
        result: list[tuple[int, str, Path]] = []
        for entry in pages:
            if entry.get("corpus_role") == "duplicate":
                continue
            if not entry.get("file"):  # null for unresolved/front/back-matter
                continue
            stem = Path(entry["file"]).stem
            sidecar = vol_dir / f"{stem}.{suffix}"
            if not sidecar.exists():
                continue
            if not sidecar.name.endswith(f".{suffix}"):
                continue
            result.append((entry["seq"], stem, sidecar))
        return result

    # Fallback: glob page_*.{suffix} with guard against sibling variants
    results: list[tuple[int, str, Path]] = []
    for path in sorted(vol_dir.glob(f"page_*.{suffix}")):
        if not path.name.endswith(f".{suffix}"):
            continue
        stem = path.name[: -len(f".{suffix}")]
        m = re.fullmatch(r"page_(\d+)", stem)
        if not m:
            continue
        results.append((int(m.group(1)), stem, path))
    return results


def volume_assembly_records(
    vol_dir: Path,
    suffix: str,
) -> list[tuple[str, Path, int]]:
    """Return (page_native_id, sidecar_path, canonical_page_num) for assembly.

    canonical_page_num is the integer page number to use in the assembled
    volume JSON:
    - Manifest volumes (vol_01): only corpus_role='body' entries are
      returned; page_num = int(book_page) (Arabic numerals, 1-500).
      This avoids the collision between leaf_0037 (leaf digit 37) and
      page_0037 (printed page 37) that would arise from using the
      sidecar's own "page" field.
    - Non-manifest volumes (02-13): all page_*.{suffix} sidecars, page_num
      from the filename digit — identical to previous behaviour.

    Only entries whose sidecar exists on disk are returned.
    """
    pages = _load_manifest(vol_dir)
    if pages is not None:
        result: list[tuple[str, Path, int]] = []
        for entry in pages:
            if entry.get("corpus_role") != "body":
                continue
            if not entry.get("file"):  # null for unresolved body pages
                continue
            stem = Path(entry["file"]).stem
            sidecar = vol_dir / f"{stem}.{suffix}"
            if not sidecar.exists():
                continue
            book_page = entry.get("book_page")
            try:
                canonical_page = int(book_page)
            except (TypeError, ValueError):
                continue  # null or Roman-numeral book_page — not body
            result.append((stem, sidecar, canonical_page))
        return result

    # Fallback
    results: list[tuple[str, Path, int]] = []
    for path in sorted(vol_dir.glob(f"page_*.{suffix}")):
        if not path.name.endswith(f".{suffix}"):
            continue
        stem = path.name[: -len(f".{suffix}")]
        m = re.fullmatch(r"page_(\d+)", stem)
        if not m:
            continue
        results.append((stem, path, int(m.group(1))))
    return results


def volume_duplicate_stems(vol_dir: Path) -> frozenset[str]:
    """Return image file stems marked corpus_role='duplicate' in page_order.json.

    Used by reindex to skip orphaned sidecars for duplicate-role images that
    were produced before the page_order.json filtering was in place.
    Returns an empty frozenset for volumes without a page_order.json.
    """
    pages = _load_manifest(vol_dir)
    if pages is None:
        return frozenset()
    return frozenset(
        Path(entry["file"]).stem
        for entry in pages
        if entry.get("corpus_role") == "duplicate" and entry.get("file")
    )
