"""build/lib/nsh_leaf_model.py
The shared accessor for NSH source manifests (the P0.5 foundation).

Every consumer of an NSH ``vol_NN.manifest.json`` reads through this module
instead of touching ``manifest["pages"]`` / ``manifest["unnumbered_leaves"]``
directly. Each accessor derives from the new unified ``leaves[]`` shape when
present and FALLS BACK to the legacy two-list shape when absent. This is the
mechanism that lets every consumer move to one API now -- while the manifests
on disk are still legacy-shaped -- and keep passing, so the later P2 migration
is invisible to them (design docs/DESIGN_nsh_leaf_sequence_manifest.md SS3).

A "leaf record" returned by these functions is always normalized to the v4
shape: ``leaf_num``, ``page_num``, ``kind``, ``image_state`` plus any image /
provenance fields. The legacy fallback synthesizes those four keys from the
``pages[]`` + ``unnumbered_leaves[]`` entries and de-overlaps the leading-run
double-record (design SS4.3) so the view is already correct on legacy input.

NOTE on ``leaf_num`` in the legacy fallback (R-mixed-source, design SS1.2):
``leaf_num`` is the PRIMARY-scan coordinate. For a primary body page it is
``int(ia_leaf_id)``; for an alternate-sourced body page (haucgoog hole) the
``ia_leaf_id`` belongs to the alternate item, so ``leaf_num`` is reconstructed
as ``page_num + front_offset`` where the offset is taken from the primary
pages. Volumes with a mid-body plate (vols 10/11) have a non-constant offset;
they are not in the legacy-validating set and are migrated in P2, where the
authoritative ``leaves[]`` carries the verified per-leaf coordinate.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

# The kinds the OCR pipeline may consume. Body is the only default (design Q6);
# front/back matter is real text and an explicit later opt-in. Plates are
# illustrations and discarded leaves are duplicates/blanks -- NEVER OCR'd.
_OCR_DEFAULT_KINDS = frozenset({"body"})
_OCR_FRONT_BACK_KINDS = frozenset({"front_matter", "back_matter"})
_LEAF_NATIVE_ID = re.compile(r"^leaf_0*(\d+)$")
_PAGE_NATIVE_ID = re.compile(r"^page_0*(\d+)$")

# Image-bearing provenance fields carried verbatim from a legacy entry onto the
# normalized leaf record (so consumers reading e.g. local_path keep working).
_CARRIED_IMAGE_FIELDS = (
    "local_path",
    "ia_leaf_id",
    "ia_filename",
    "ia_item_id",
    "sha256",
    "fetched_at",
    "image_mode",
    "image_size",
    "provenance",
    "source_note",
)


def derive_kind(leaf: dict, first_body: int, last_body: int) -> str:
    """Pure classification of a leaf by position (design SS1.5).

    ``first_body`` / ``last_body`` are the min / max ``leaf_num`` over leaves
    that carry a printed ``page_num``. No human or OCR guess enters this.
    """
    if leaf.get("discard_reason") is not None:
        return "discarded"
    if leaf.get("page_num") is not None:
        return "body"
    if leaf["leaf_num"] < first_body:
        return "front_matter"
    if leaf["leaf_num"] > last_body:
        return "back_matter"
    return "plate"


def _is_v4(manifest: dict) -> bool:
    return "leaves" in manifest


def _sort_key(leaf: dict) -> tuple[int, int]:
    leaf_num = leaf.get("leaf_num")
    if isinstance(leaf_num, int):
        return (0, leaf_num)
    return (1, 0)


def _legacy_offset(pages: list[dict]) -> int:
    """Front offset = (lowest primary body leaf) - (lowest primary body page).

    Derived from primary pages only (``provenance`` absent), so alternate-source
    leaf ids never pollute the offset (design SS1.2 / R-mixed-source).
    """
    pairs = []
    for page in pages:
        if page.get("provenance") is not None:
            continue
        page_num = page.get("page_num")
        leaf_id = page.get("ia_leaf_id")
        if isinstance(page_num, int) and isinstance(leaf_id, str) and leaf_id.isdigit():
            pairs.append((int(leaf_id), page_num))
    if not pairs:
        return 0
    first = min(pairs, key=lambda pair: pair[1])
    return first[0] - first[1]


def _legacy_body_leaf_num(page: dict, offset: int) -> int | None:
    """Primary-scan leaf coordinate for a legacy body page."""
    leaf_id = page.get("ia_leaf_id")
    page_num = page.get("page_num")
    # Primary page: ia_leaf_id IS the primary coordinate.
    if page.get("provenance") is None and isinstance(leaf_id, str) and leaf_id.isdigit():
        return int(leaf_id)
    # Alternate-sourced page: reconstruct from the printed page + front offset.
    if isinstance(page_num, int):
        return page_num + offset
    return None


def _carry(dst: dict, src: dict) -> None:
    for field in _CARRIED_IMAGE_FIELDS:
        if field in src:
            dst[field] = src[field]


def _legacy_leaves(manifest: dict) -> list[dict]:
    pages = list(manifest.get("pages", []))
    unnumbered = list(manifest.get("unnumbered_leaves", []))
    offset = _legacy_offset(pages)

    body: list[dict] = []
    for page in pages:
        page_num = page.get("page_num")
        leaf_num = _legacy_body_leaf_num(page, offset)
        record: dict[str, Any] = {
            "leaf_num": leaf_num,
            "page_num": page_num,
            "kind": "body",
            "image_state": "present" if page.get("local_path") else "unresolved",
        }
        _carry(record, page)
        body.append(record)

    body_leaf_nums = [r["leaf_num"] for r in body if isinstance(r["leaf_num"], int)]
    if body_leaf_nums:
        first_body = min(body_leaf_nums)
        last_body = max(body_leaf_nums)
    else:
        first_body = 0
        last_body = 0

    extra: list[dict] = []
    for leaf in unnumbered:
        leaf_num = leaf.get("leaf_num")
        # De-overlap the leading-run double-record (design SS4.3): any
        # unnumbered leaf inside the body span is the second copy of a body
        # leaf and is dropped -- the body record above is its single home.
        if isinstance(leaf_num, int) and first_body <= leaf_num <= last_body:
            continue
        record = {
            "leaf_num": leaf_num,
            "page_num": None,
            "kind": derive_kind({"leaf_num": leaf_num, "page_num": None}, first_body, last_body),
            "image_state": "present" if leaf.get("local_path") else "pending",
        }
        _carry(record, leaf)
        extra.append(record)

    return sorted(body + extra, key=_sort_key)


def leaves_view(manifest: dict) -> list[dict]:
    """One normalized leaf record per physical leaf, sorted by ``leaf_num``.

    From the v4 ``leaves[]`` array when present; otherwise reconstructed from
    the legacy ``pages[]`` + ``unnumbered_leaves[]`` shape, de-overlapped.
    """
    if _is_v4(manifest):
        return sorted((dict(leaf) for leaf in manifest.get("leaves", [])), key=_sort_key)
    return _legacy_leaves(manifest)


def _by_kind(manifest: dict, kind: str) -> list[dict]:
    return [leaf for leaf in leaves_view(manifest) if leaf.get("kind") == kind]


def body_pages(manifest: dict) -> list[dict]:
    """Numbered body leaves (``kind == "body"``), in physical order."""
    return _by_kind(manifest, "body")


def front_matter(manifest: dict) -> list[dict]:
    return _by_kind(manifest, "front_matter")


def back_matter(manifest: dict) -> list[dict]:
    return _by_kind(manifest, "back_matter")


def plates(manifest: dict) -> list[dict]:
    return _by_kind(manifest, "plate")


def discarded(manifest: dict) -> list[dict]:
    return _by_kind(manifest, "discarded")


def ocr_input(manifest: dict, *, include_front_back: bool = False) -> list[dict]:
    """The leaves whose images feed the OCR engines.

    Body only by default (design Q6 -- preserves today's body-only behavior).
    ``include_front_back=True`` is the explicit opt-in for front/back matter.
    Plates and discarded leaves are NEVER returned.
    """
    kinds = set(_OCR_DEFAULT_KINDS)
    if include_front_back:
        kinds |= _OCR_FRONT_BACK_KINDS
    return [leaf for leaf in leaves_view(manifest) if leaf.get("kind") in kinds]


def leaf_by_sha(manifest: dict) -> dict[str, list[dict]]:
    """Index all sha-bearing leaves by content hash."""
    by_sha: dict[str, list[dict]] = {}
    for leaf in leaves_view(manifest):
        sha = leaf.get("sha256")
        if isinstance(sha, str):
            by_sha.setdefault(sha, []).append(leaf)
    return by_sha


def gap_by_sha(manifest: dict) -> dict[str, dict]:
    """Index the recovered-gap records (``gaps[]``) by content sha.

    The P2 recovered-gap model (schema 4.1.0; commit 0df0e3ac) records a printed
    body page the primary scan skipped -- typically recovered from an alternate
    scan -- as a ``gap_record`` in a top-level ``gaps[]`` array. A
    recovered gap is a real body page with NO spine leaf, so it never appears in
    ``leaves[]`` and ``leaf_by_sha`` / ``resolve_leaf`` cannot see it. This index
    lets a consumer recognize a gap-page image (which still has a sha + an OCR
    sidecar) instead of treating its sha as unresolvable. Only gap records that
    carry a ``sha256`` are indexable; later (>1) duplicates of a sha are ignored.
    """
    by_sha: dict[str, dict] = {}
    for gap in manifest.get("gaps", []):
        if not isinstance(gap, dict):
            continue
        sha = gap.get("sha256")
        if isinstance(sha, str) and sha not in by_sha:
            by_sha[sha] = gap
    return by_sha


def ocr_input_in_order(manifest: dict) -> list[dict]:
    """OCR-input body leaves with their current expected filename stem."""
    ordered: list[dict] = []
    for leaf in ocr_input(manifest):
        image_name = expected_image_name(leaf)
        record = dict(leaf)
        record["current_stem"] = Path(image_name).stem if image_name is not None else None
        ordered.append(record)
    return ordered


def resolve_leaf(manifest: dict, sha: str) -> tuple[int, int | None, str]:
    """Resolve a content sha to ``(leaf_num, page_num, current_stem)``."""
    matches = leaf_by_sha(manifest).get(sha, [])
    if len(matches) != 1:
        raise ValueError(f"sha {sha} resolved to {len(matches)} leaves")

    leaf = matches[0]
    image_name = expected_image_name(leaf)
    if image_name is None:
        raise ValueError(f"sha {sha} resolves to a leaf with no expected image name")

    return leaf["leaf_num"], leaf.get("page_num"), Path(image_name).stem


def body_leaf_sha_duplicates(manifest: dict) -> dict[str, list[dict]]:
    """Duplicate sha groups among body leaves only."""
    by_sha: dict[str, list[dict]] = {}
    for leaf in body_pages(manifest):
        sha = leaf.get("sha256")
        if isinstance(sha, str):
            by_sha.setdefault(sha, []).append(leaf)
    return {sha: leaves for sha, leaves in by_sha.items() if len(leaves) > 1}


def canonical_leaf_id(page_native_id: str, manifest: dict) -> int | None:
    """Resolve a sidecar native page id to the primary-scan ``leaf_num``."""
    leaf_match = _LEAF_NATIVE_ID.fullmatch(page_native_id)
    if leaf_match:
        leaf_num = int(leaf_match.group(1))
        known_leaf_nums = {
            leaf["leaf_num"]
            for leaf in leaves_view(manifest)
            if isinstance(leaf.get("leaf_num"), int)
        }
        if leaf_num in known_leaf_nums:
            return leaf_num
        return None

    page_match = _PAGE_NATIVE_ID.fullmatch(page_native_id)
    if page_match:
        page_num = int(page_match.group(1))
        page_to_leaf = {
            leaf["page_num"]: leaf["leaf_num"]
            for leaf in body_pages(manifest)
            if isinstance(leaf.get("page_num"), int) and isinstance(leaf.get("leaf_num"), int)
        }
        return page_to_leaf.get(page_num)

    return None


def set_leaf_or_exempt(record: dict, leaf_id: int | None) -> dict:
    """Stamp the canonical leaf identity on a per-page record for the R5
    leaf-required schemas. A body page carries ``canonical_leaf_id`` (int); a
    non-body / unmappable page carries ``clid_exempt: true``. Exactly one is
    always present, satisfying the ``oneOf`` constraint the four leaf-keyed
    schemas enforce (sidecar-page-v1, sidecar-manifest-v1 page_ref,
    rendering-v1 rendered_page, word-confusion-table-v1). Mutates and returns
    ``record`` so emit sites can call it inline.

    Single source of truth for the marker (CC-ARCH-05): producers must not set
    ``canonical_leaf_id`` / ``clid_exempt`` directly, so the keyed-XOR-exempt
    invariant is impossible to violate one field at a time.
    """
    record.pop("canonical_leaf_id", None)
    record.pop("clid_exempt", None)
    if leaf_id is None:
        record["clid_exempt"] = True
    else:
        record["canonical_leaf_id"] = int(leaf_id)
    return record


def expected_image_name(leaf: dict) -> str | None:
    """The on-disk image filename for a leaf, or None when no image is expected.

    body -> ``page_NNNN.jpg`` (keyed by page_num); front/back -> ``leaf_NNNN.jpg``
    (keyed by leaf_num); plate -> its ``local_path`` basename (the plate_* name);
    discarded -> None (pixels quarantined). When a front/back leaf already has a
    ``local_path`` its basename wins (handles non-default names).
    """
    kind = leaf.get("kind")
    if kind == "body":
        page_num = leaf.get("page_num")
        if isinstance(page_num, int):
            return f"page_{page_num:04d}.jpg"
        return None
    if kind in ("front_matter", "back_matter"):
        local_path = leaf.get("local_path")
        if isinstance(local_path, str) and local_path:
            return Path(local_path).name
        leaf_num = leaf.get("leaf_num")
        if isinstance(leaf_num, int):
            return f"leaf_{leaf_num:04d}.jpg"
        return None
    if kind == "plate":
        local_path = leaf.get("local_path")
        if isinstance(local_path, str) and local_path:
            return Path(local_path).name
        return None
    return None
