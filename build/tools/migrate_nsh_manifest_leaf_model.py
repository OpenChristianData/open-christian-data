"""Migrate an NSH ``vol_NN.manifest.json`` from the legacy two-list shape
(``pages[]`` + ``unnumbered_leaves[]``) to the v4 unified leaf-sequence model
(``leaves[]``), per design docs/DESIGN_nsh_leaf_sequence_manifest.md (Phase P2).

Authority split (the load-bearing decision):
  - The leaf SPINE -- which physical leaves exist, the total count, and which
    leaves are numbered vs unnumbered -- comes from IA SCANDATA (the primary
    physical-leaf enumeration).
  - page_num VALUES come from the EXISTING MANIFEST's ``pages[]`` (the running-
    header-verified printed numbers; scandata's ``pageNumber`` was found wrong
    before -- PIPE-29 / the phantom-page incident). A scandata/manifest page_num
    disagreement is recorded as a ``manifest_warning`` and the manifest wins.
  - ``kind`` is derived purely from position (design SS1.5) via the shared
    accessor's ``derive_kind`` -- no OCR/human guess enters it.

This is manifest-only-in-place (P2): the body images are already on disk and
correctly named; nothing is re-downloaded and ``swap_nsh_rebuild.py`` is NOT
run. The tool rewrites the manifest JSON only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.ia_fetch import find_jp2_zip  # noqa: E402
from build.lib.nsh_leaf_model import (  # noqa: E402
    _CARRIED_IMAGE_FIELDS,
    derive_kind,
)


_SCANDATA_NS = "http://www.archive.org/scandata"


def parse_scandata_rows(scandata_xml: str) -> list[tuple[int, int | None]]:
    """Parse scandata XML into ``[(leaf_num, pageNumber-or-None), ...]`` in
    document order -- the complete primary leaf spine. Mirrors the probe tool's
    ``_ordered_leaf_pages`` so the two stay consistent."""
    root = ET.fromstring(scandata_xml)
    pages = (
        root.findall(f".//{{{_SCANDATA_NS}}}page")
        or root.findall(".//page")
    )
    rows: list[tuple[int, int | None]] = []
    for page in pages:
        leaf_str = page.get("leafNum", "")
        if not leaf_str.isdigit():
            continue
        pnum_el = page.find(f"{{{_SCANDATA_NS}}}pageNumber") or page.find("pageNumber")
        pnum = (pnum_el.text or "").strip() if pnum_el is not None else ""
        rows.append((int(leaf_str), int(pnum) if pnum.isdigit() else None))
    return rows


def _body_leaf_map(
    manifest: dict, scandata_page_to_leaf: dict[int, int],
) -> tuple[dict[int, dict], list[int], list[str]]:
    """Map ``leaf_num`` (primary-scan coordinate) -> the legacy page record.

    Returns ``(body_map, holes, warnings)``.

    The leaf coordinate is the PRIMARY-scan leafNum (design SS1.2; P2b decision):
      - Primary-namespace pages key on the SCANDATA ``leafNum`` for their printed
        page -- the physical-leaf coordinate. ``ia_leaf_id`` is NOT the coordinate:
        it can be inflated by an alternate insert (vol_10 +8) and, used as a key,
        collide with a cross-namespace recovery; it is retained in the image block
        as the source-download reference, and a divergence is warned. When scandata
        does not number the page (the reconstructed leading run, before scandata's
        numbering begins), it falls back to ``int(ia_leaf_id)`` -- the verified
        pre-numbering coordinate (no inflation there). A page is primary-namespace
        when it has no ``provenance`` OR its provenance is a SAME-item recovery
        (both ``ia_item_id`` and ``provenance.source_item_id`` are this volume's
        primary item -- e.g. vol_13 front matter).
      - Cross-namespace pages (haucgoog/other-item recoveries -- ``ia_item_id``
        or ``source_item_id`` is an alternate item) carry the alternate item's
        leaf id, so the PRIMARY leaf is taken from scandata's page->leaf map. A
        printed page absent from the primary scan has NO integer leaf coordinate
        -> recorded as a ``hole`` (never collided onto another page's leaf via a
        stale global offset -- R-variable-offset).
    """
    pages = list(manifest.get("pages", []))  # nsh-legacy-read: migration write path
    primary_item_id = manifest.get("ia_item_id")
    out: dict[int, dict] = {}
    holes: list[int] = []
    warnings: list[str] = []
    for page in pages:
        page_num = page.get("page_num")
        leaf_id = page.get("ia_leaf_id")
        # A page's own ia_leaf_id is the PRIMARY-scan coordinate when the page sits
        # in the primary item's namespace -- either a legacy primary page (no
        # provenance) OR a page with a provenance block whose ia_item_id is this
        # volume's primary item (e.g. vol_13 front matter recovered from the same
        # item, scandata-unnumbered leaves 18-24). Only a CROSS-namespace recovery
        # (alternate item id) carries a colliding foreign leaf index, so for those
        # the primary leaf must come from scandata, and a printed page the primary
        # scan never captured (Scenario A) becomes a hole.
        prov = page.get("provenance")
        in_primary_namespace = (
            prov is None
            # A provenance block whose ia_item_id AND source_item_id are both the
            # primary item is a same-item recovery (vol_13 front matter) -- its
            # ia_leaf_id is a real primary coordinate. A record claiming the primary
            # ia_item_id but pointing at an ALTERNATE source_item_id is genuinely
            # cross-namespace (its ia_leaf_id is the alternate's) -- never place it
            # at that foreign id (Codex review A).
            or (page.get("ia_item_id") == primary_item_id
                and prov.get("source_item_id") == primary_item_id)
        )
        if in_primary_namespace and isinstance(leaf_id, str) and leaf_id.isdigit():
            # Primary page: the leaf coordinate is the SCANDATA physical leafNum
            # (design SS1.2; P2b decision 2026-06-11). scandata's leafNum is a
            # structural count, not the OCR pageNumber PIPE-29 distrusts -- so taking
            # it as the coordinate is sound while page_num still comes from the
            # manifest. The manifest's ia_leaf_id can be inflated relative to the true
            # leaf (vol_10's +8 back-matter bookkeeping, from an alternate insert) and,
            # used as a coordinate, COLLIDES with a cross-namespace recovery placed at
            # the same scandata leaf -- dropping a page. So the scandata leaf wins;
            # ia_leaf_id is retained in the image block as the source-download
            # reference (SS1.3 permits it to differ from leaf_num).
            scan_leaf = scandata_page_to_leaf.get(page_num)
            if scan_leaf is not None:
                leaf_num = scan_leaf
                if scan_leaf != int(leaf_id):
                    warnings.append(
                        f"page {page_num}: manifest ia_leaf_id {int(leaf_id)} != "
                        f"scandata leaf {scan_leaf}; using scandata leaf {scan_leaf} as "
                        f"the coordinate (ia_leaf_id retained in image block)"
                    )
            else:
                # scandata does not number this page: the reconstructed leading run
                # (printed pages before scandata begins numbering). There ia_leaf_id is
                # the verified physical coordinate -- it predates any alternate insert,
                # so no inflation -- and scandata offers no leaf for it.
                leaf_num = int(leaf_id)
            out[leaf_num] = page
        else:
            # Alternate-sourced page: the primary leaf comes from scandata.
            scan_leaf = scandata_page_to_leaf.get(page_num)
            if scan_leaf is None:
                holes.append(page_num)
            else:
                out[scan_leaf] = page
    return out, holes, warnings


def _body_record(leaf_num: int, page: dict, default_item_id: str | None) -> dict:
    rec: dict = {
        "leaf_num": leaf_num,
        "page_num": page.get("page_num"),
        "kind": "body",
        "image_state": "present" if page.get("local_path") else "unresolved",
    }
    for field in _CARRIED_IMAGE_FIELDS:
        if field in page:
            rec[field] = page[field]
    # Legacy primary pages omit per-page ia_item_id (top-level only); the v4 leaf
    # schema requires it when an image is present. Alternate-source pages carry
    # their own ia_item_id and keep it.
    if rec.get("local_path") and "ia_item_id" not in rec and default_item_id:
        rec["ia_item_id"] = default_item_id
    return rec


def build_v4_leaves(
    scandata_rows: list[tuple[int, int | None]],
    manifest: dict,
    *,
    leaf_image_provenance: dict[int, dict] | None = None,
) -> tuple[list[dict], list[int], list[str]]:
    """Build the v4 ``leaves[]`` array for one volume.

    ``scandata_rows`` is ``[(leaf_num, scandata_pageNumber-or-None), ...]`` in
    document order (the complete primary spine). ``manifest`` is the legacy
    two-list manifest. ``leaf_image_provenance`` maps a front/back/plate
    leaf_num to a full image-provenance dict (``local_path`` + the 7 required
    image fields) when that leaf's image already exists on disk -- e.g. vol_01's
    52 mapped orphan ``leaf_*.jpg`` (design SS4.5).

    Returns ``(leaves, holes, warnings)``. ``holes`` is the list of printed
    pages present in the manifest but absent from the primary scan (recovered
    from an alternate source with no primary leaf coordinate) -- these cannot be
    placed by an integer leaf_num and are surfaced for a human decision, never
    silently dropped or collided onto another leaf.
    """
    warnings: list[str] = []
    leaf_image_provenance = leaf_image_provenance or {}
    default_item_id = manifest.get("ia_item_id")
    scandata_page_to_leaf = {p: leaf for leaf, p in scandata_rows if p is not None}
    body_map, holes, map_warnings = _body_leaf_map(manifest, scandata_page_to_leaf)
    warnings.extend(map_warnings)
    body_leaf_nums = sorted(body_map)
    first_body = body_leaf_nums[0]
    last_body = body_leaf_nums[-1]

    leaves: list[dict] = []
    last_body_page: int | None = None  # most recent body page_num, for plate.after_page_num
    for leaf_num, scandata_pnum in sorted(scandata_rows):
        if leaf_num in body_map:
            page = body_map[leaf_num]
            # PIPE-29: the manifest's page_num is authoritative (running-header
            # verified); scandata's pageNumber was found wrong before. Keep the
            # manifest value and flag any disagreement for a human.
            mf_pnum = page.get("page_num")
            if (isinstance(scandata_pnum, int) and isinstance(mf_pnum, int)
                    and scandata_pnum != mf_pnum):
                warnings.append(
                    f"leaf {leaf_num}: scandata pageNumber {scandata_pnum} "
                    f"disagrees with manifest page_num {mf_pnum}; kept manifest value"
                )
            leaves.append(_body_record(leaf_num, page, default_item_id))
            if isinstance(mf_pnum, int):
                last_body_page = mf_pnum
            continue
        # Unnumbered leaf: classify by position (front/back/plate).
        kind = derive_kind({"leaf_num": leaf_num, "page_num": None}, first_body, last_body)
        rec = {
            "leaf_num": leaf_num,
            "page_num": None,
            "kind": kind,
            "image_state": "pending",
        }
        prov = leaf_image_provenance.get(leaf_num)
        if prov is not None:
            rec["image_state"] = "present"
            for field in _CARRIED_IMAGE_FIELDS:
                if field in prov:
                    rec[field] = prov[field]
        if kind == "plate":
            # The printed page this plate follows = the last numbered body leaf
            # seen walking the spine in leaf order (design SS1.3 / SS2).
            if last_body_page is not None:
                rec["after_page_num"] = last_body_page
            warnings.append(
                f"leaf {leaf_num}: interior unnumbered leaf classified as plate "
                f"(after printed page {last_body_page}); confirm against pixels"
            )
        leaves.append(rec)

    leaves.sort(key=lambda r: r["leaf_num"])
    if holes:
        warnings.append(
            f"{len(holes)} printed page(s) absent from the primary scan (recovered "
            f"from an alternate source, no primary leaf coordinate): {sorted(holes)}"
        )
    # Soft guard on the scandata-leaf rule (PIPE-29): body leaf_num must rise with
    # page_num. Because the primary coordinate now comes from scandata's pageNumber
    # map, a single mis-OCR'd pageNumber could place a page on an out-of-order leaf
    # without colliding (so the uniqueness invariant would not catch it). A break in
    # monotonicity is that tell -- surfaced as a warning (not a hard failure: the
    # model legitimately allows non-monotone volumes, e.g. vol_11's mid-body plates).
    body_by_page = sorted(
        (lf["page_num"], lf["leaf_num"]) for lf in leaves if lf["page_num"] is not None
    )
    for (p_prev, lf_prev), (p_cur, lf_cur) in zip(body_by_page, body_by_page[1:]):
        if lf_cur <= lf_prev:
            warnings.append(
                f"page {p_cur} (leaf {lf_cur}) is not monotonic after page {p_prev} "
                f"(leaf {lf_prev}); body leaf_num should rise with page_num -- "
                f"verify the scandata leaf assignment against pixels"
            )
    return leaves, holes, warnings


def assert_migration_invariants(
    leaves: list[dict],
    scandata_rows: list[tuple[int, int | None]],
    manifest: dict,
    holes: list[int] | tuple[int, ...] = (),
) -> None:
    """Fail-fast positional invariants the schema cannot express (design SS1.7).

    Raises ``AssertionError`` on any of: leaf-count != scandata count (a drop),
    duplicate leaf_num (an overlap), page coverage != the prior manifest's
    numbered pages, or a stored ``kind`` that disagrees with ``derive_kind``.

    ``holes`` are the no-primary-leaf recoveries routed to ``gaps[]`` (Scenario A);
    they are not spine leaves, so coverage is checked as ``leaf page_nums ∪ holes``.
    """
    scandata_leaves = {leaf for leaf, _ in scandata_rows}
    leaf_nums = [lf["leaf_num"] for lf in leaves]

    assert len(leaf_nums) == len(scandata_leaves), (
        f"leaf count {len(leaf_nums)} != scandata leaf count {len(scandata_leaves)} (drop)"
    )
    assert len(set(leaf_nums)) == len(leaf_nums), "duplicate leaf_num (coordinate overlap)"
    assert set(leaf_nums) == scandata_leaves, "leaf_num set != scandata leaf set"

    prior_pages = {
        p["page_num"]
        for p in manifest.get("pages", [])  # nsh-legacy-read: migration invariant check
        if isinstance(p.get("page_num"), int)
    }
    leaf_pages = {lf["page_num"] for lf in leaves if lf["page_num"] is not None}
    both = leaf_pages & set(holes)
    assert not both, f"page(s) both placed as a leaf and routed as a hole: {sorted(both)}"
    new_pages = leaf_pages | set(holes)
    assert new_pages == prior_pages, (
        f"page coverage changed: missing {prior_pages - new_pages}, "
        f"added {new_pages - prior_pages}"
    )

    body_leaf_nums = [lf["leaf_num"] for lf in leaves if lf.get("page_num") is not None]
    first_body, last_body = min(body_leaf_nums), max(body_leaf_nums)
    for lf in leaves:
        expected = derive_kind(lf, first_body, last_body)
        assert lf["kind"] == expected, (
            f"leaf {lf['leaf_num']}: stored kind {lf['kind']} != derived {expected}"
        )


# Top-level manifest fields copied verbatim from the legacy manifest.
_CARRIED_MANIFEST_FIELDS = ("ia_item_id", "ia_derivative_type", "volume", "created_at")

# trailing leaf index in an IA jp2 filename, e.g. "..._0522.jp2"
_JP2_LEAF_RE = re.compile(r"_(\d+)\.jp2$")


class HolesRequireDecision(ValueError):
    """Raised when a manifest has a printed page with no primary-scan leaf AND no
    on-disk image -- it cannot be placed in the leaf spine (no coordinate) nor
    recorded as a recovered gap (no image to reference), so the migration refuses
    to produce an incomplete manifest. ``self.holes`` lists the affected pages.

    The common Scenario-A case (alternate-recovered page, image present) is NOT
    raised: it is routed to an enriched ``gaps[]`` entry (design Q1 / Option C)."""

    def __init__(self, holes: list[int]):
        self.holes = sorted(holes)
        super().__init__(
            f"{len(self.holes)} printed page(s) have no primary-scan leaf and no "
            f"on-disk image: {self.holes}. Cannot place in leaves[] (no coordinate) "
            "or record as a recovered gap (no image); refusing to write an "
            "incomplete manifest."
        )


# Image/provenance fields lifted from a recovered page's legacy pages[] record
# onto its gaps[] entry (the page has no spine leaf, so this is where its image
# audit trail lives). gap_record (schema 4.1.0) makes these optional.
_RECOVERED_IMAGE_FIELDS = (
    "local_path", "ia_leaf_id", "ia_filename", "ia_item_id",
    "sha256", "fetched_at", "image_mode", "image_size", "provenance",
)


def _recovered_gap_entry(existing: dict | None, page: dict) -> dict:
    """Build (or enrich) the gaps[] entry for a no-primary-leaf recovery, carrying
    its image provenance from the legacy ``pages[]`` record. Preserves an existing
    entry's status / investigation_note / resolved_from; merges in the image
    fields. A fresh entry is stamped ``status: resolved`` with a synthesized note."""
    item_id = page.get("ia_item_id")
    gap = dict(existing) if existing else {
        "page_num": page.get("page_num"),
        "status": "resolved",
        "investigation_note": (
            f"recovered from alternate item {item_id}; no primary-scan leaf "
            "(printed page absent from the primary scan), image carried on this gap"
        ),
    }
    if "resolved_from" not in gap and isinstance(item_id, str):
        gap["resolved_from"] = item_id
    for field in _RECOVERED_IMAGE_FIELDS:
        if field in page:
            gap[field] = page[field]
    # An on-disk image means the page is recovered, not missing: a carried-over
    # status like permanently_missing would be self-contradictory (Codex review B).
    gap["status"] = "resolved"
    return gap


def build_v4_manifest(
    scandata_rows: list[tuple[int, int | None]],
    manifest: dict,
    *,
    leaf_image_provenance: dict[int, dict] | None = None,
) -> dict:
    """Assemble the full v4 manifest dict (leaves[] shape) for one volume.

    Carries ``gaps[]`` verbatim (design Q1). A no-primary-leaf recovery (Scenario A
    -- a printed page the primary scan skipped, recovered from an alternate item)
    has no spine coordinate; its image provenance is folded into its ``gaps[]``
    entry (Option C / path (a)) rather than dropped. Merges any existing
    ``manifest_warnings`` with the ones surfaced by the migration. Runs the
    positional invariants before returning (fail-fast, REL-02). Raises
    ``HolesRequireDecision`` only for a hole with no on-disk image to record."""
    leaves, holes, warnings = build_v4_leaves(
        scandata_rows, manifest, leaf_image_provenance=leaf_image_provenance
    )
    pages_by_num = {
        p.get("page_num"): p
        for p in manifest.get("pages", [])  # nsh-legacy-read: migration write path
    }
    unrecoverable = [h for h in holes if not pages_by_num.get(h, {}).get("local_path")]
    if unrecoverable:
        raise HolesRequireDecision(unrecoverable)

    gaps = [dict(g) for g in manifest.get("gaps", [])]
    gap_by_num = {g.get("page_num"): g for g in gaps}
    for h in sorted(holes):
        existing = gap_by_num.get(h)
        prior_status = existing.get("status") if existing else None
        enriched = _recovered_gap_entry(existing, pages_by_num[h])
        if existing is not None:
            gaps[gaps.index(existing)] = enriched
        else:
            gaps.append(enriched)
        warnings.append(
            f"page {h}: no primary-scan leaf; recovered image recorded in gaps[] "
            f"(no spine leaf_num -- Scenario A)"
        )
        if prior_status and prior_status != "resolved":
            warnings.append(
                f"page {h}: gap status {prior_status!r} overridden to 'resolved' "
                f"(on-disk image present)"
            )

    assert_migration_invariants(leaves, scandata_rows, manifest, holes)

    out: dict = {field: manifest[field] for field in _CARRIED_MANIFEST_FIELDS}
    # page_count is the printed body-page count (the book's page range), carried
    # verbatim from the legacy manifest. It is NOT the body-LEAF count: a page
    # recovered from an alternate scan (Scenario A, routed to gaps[]) is a real
    # body page with no spine leaf, so recomputing from leaves[] would undercount
    # it -- and the same for a permanently-missing body page (a hole with no image).
    # `or` (not get-default) so an explicit null/0 page_count also falls back: the
    # true body-page count is the body leaves plus the no-leaf recovered holes
    # (Codex review C).
    out["page_count"] = manifest.get("page_count") or (
        sum(1 for lf in leaves if lf["kind"] == "body") + len(holes)
    )
    out["leaves"] = leaves
    out["gaps"] = gaps
    merged_warnings = list(manifest.get("manifest_warnings", [])) + warnings
    if merged_warnings:
        out["manifest_warnings"] = merged_warnings
    return out


def _img_facts(jpg: Path) -> tuple[str, str, list[int]]:
    """(sha256, PIL mode, [w, h]) read from disk -- the image is primary."""
    from PIL import Image

    data = jpg.read_bytes()
    sha = "sha256:" + hashlib.sha256(data).hexdigest()
    with Image.open(jpg) as im:
        return sha, im.mode, [im.width, im.height]


def _ia_filename_for_leaf(manifest: dict, leaf_num: int) -> str | None:
    """Derive the jp2 ia_filename for ``leaf_num`` from a primary page's
    filename pattern (substitute the trailing ``_NNNN.jp2`` index)."""
    for page in manifest.get("pages", []):  # nsh-legacy-read: migration write path
        if page.get("provenance") is not None:
            continue  # skip alternate-source filenames (different item naming)
        ia_filename = page.get("ia_filename")
        if isinstance(ia_filename, str) and _JP2_LEAF_RE.search(ia_filename):
            return _JP2_LEAF_RE.sub(f"_{leaf_num:04d}.jp2", ia_filename)
    return None


def _rel_to_repo(path: Path, repo_root: Path) -> str:
    """Repo-root-relative POSIX path (OUT-03); falls back to the path's own
    posix form for tmp dirs outside the repo (test contexts)."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def discover_leaf_images(
    vdir: Path,
    body_leaf_nums: set[int],
    manifest: dict,
    repo_root: Path,
) -> tuple[dict[int, dict], list[int]]:
    """Scan ``vdir`` for ``leaf_NNNN.jpg`` files (front/back images already on
    disk, e.g. vol_01's 52 orphans). Returns ``(provenance_map, superseded)``:

      - ``provenance_map``: leaf_num -> full image-provenance dict, for leaves
        that are NOT body pages (real front/back images to reference).
      - ``superseded``: leaf_nums whose ``leaf_*.jpg`` duplicates a body page
        (already imaged as ``page_*.jpg``) -- not referenced; quarantined by the
        caller (design SS4.5, vol_01 leaves 37-45).
    """
    default_item_id = manifest.get("ia_item_id")
    fetched_at = datetime.now(timezone.utc).isoformat()
    provenance: dict[int, dict] = {}
    superseded: list[int] = []
    for jpg in sorted(vdir.glob("leaf_[0-9][0-9][0-9][0-9].jpg")):
        leaf_num = int(jpg.stem.split("_")[1])
        if leaf_num in body_leaf_nums:
            superseded.append(leaf_num)
            continue
        sha, mode, size = _img_facts(jpg)
        provenance[leaf_num] = {
            "local_path": _rel_to_repo(jpg, repo_root),
            "ia_leaf_id": f"{leaf_num:04d}",
            "ia_filename": _ia_filename_for_leaf(manifest, leaf_num),
            "ia_item_id": default_item_id,
            "sha256": sha,
            "fetched_at": fetched_at,
            "image_mode": mode,
            "image_size": size,
        }
    return provenance, sorted(superseded)


# --- IO / network layer ----------------------------------------------------

logger = logging.getLogger("migrate_nsh_manifest_to_v4")

BASE_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
SCANDATA_CACHE_DIR = BASE_DIR / "scandata_cache"
IA_ITEM_ID = "NewSchaffHerzogEncyclopediaOfReligious"
_USER_AGENT = "open-christian-data/nsh-migration (contact via project repo)"
_MAX_RETRY_AFTER = 300   # abort fetch if Retry-After exceeds this (API-04)


def _http_get_bytes(url: str, *, timeout: int = 60) -> bytes:
    """GET with API-04 retry: 429 honours Retry-After (<= cap); 5xx/timeout get
    exponential backoff (2/4/8s, 3 tries); other 4xx are not retried."""
    delays = [2, 4, 8]
    attempt = 0
    while True:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry_after = int((exc.hdrs.get("Retry-After", "60") if exc.hdrs else "60"))
                if retry_after > _MAX_RETRY_AFTER:
                    raise RuntimeError(
                        f"IA Retry-After {retry_after}s exceeds cap {_MAX_RETRY_AFTER}s "
                        f"for {url}; aborting (fall back per API-04)"
                    ) from exc
                logger.warning("HTTP 429 for %s -- waiting Retry-After %ds", url, retry_after)
                time.sleep(retry_after)
                continue
            if exc.code >= 500 and attempt < len(delays):
                wait = delays[attempt]
                attempt += 1
                logger.warning("HTTP %d for %s -- backoff %ds (attempt %d/%d)",
                               exc.code, url, wait, attempt, len(delays))
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < len(delays):
                wait = delays[attempt]
                attempt += 1
                logger.warning("network error for %s (%s) -- backoff %ds (attempt %d/%d)",
                               url, exc, wait, attempt, len(delays))
                time.sleep(wait)
                continue
            raise


def fetch_scandata_xml(volume: int, *, item_id: str = IA_ITEM_ID) -> str:
    """Fetch the raw scandata XML text for one volume (no parsing)."""
    files_url = f"https://archive.org/download/{item_id}/{item_id}_files.xml"
    files_root = ET.fromstring(_http_get_bytes(files_url))
    zip_name = find_jp2_zip(files_root, volume)
    prefix = zip_name.replace("_jp2.zip", "")
    scandata_url = f"https://archive.org/download/{item_id}/{prefix}_scandata.xml"
    return _http_get_bytes(scandata_url).decode("utf-8")


def cache_scandata(
    volumes: list[int], *, cache_dir: Path = SCANDATA_CACHE_DIR, item_id: str = IA_ITEM_ID,
) -> list[int]:
    """Fetch + cache scandata XML per volume; returns the volumes cached. Skips
    a volume whose cache already exists. Aborts cleanly on a rate-limit cap."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached: list[int] = []
    for vol in volumes:
        dest = cache_dir / f"vol_{vol:02d}_scandata.xml"
        if dest.exists():
            logger.info("vol_%02d scandata already cached", vol)
            cached.append(vol)
            continue
        logger.info("fetching scandata for vol_%02d", vol)
        xml_text = fetch_scandata_xml(vol, item_id=item_id)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_text(xml_text, encoding="utf-8")
        os.replace(tmp, dest)
        cached.append(vol)
        time.sleep(1)  # be gentle on IA between volumes
    return cached


def backfill_fetched_at_from_disk(manifest: dict, repo_root: Path) -> list[str]:
    """Repair legacy ``pages[]`` records that carry an on-disk image (``local_path``)
    but lost their ``fetched_at`` -- a pre-existing defect in vol_13 pages 1/5/9 that
    the migration surfaces because the v4 schema requires ``fetched_at`` with any
    image. The image file's mtime is a real observable proxy for the fetch time
    (recovered, not fabricated -- VER-01). Mutates the manifest in place; returns
    one warning per repair so the audit trail records it."""
    warnings: list[str] = []
    for page in manifest.get("pages", []):  # nsh-legacy-read: migration write path
        local_path = page.get("local_path")
        if not local_path or page.get("fetched_at"):
            continue
        img = repo_root / local_path
        if not img.exists():
            continue
        mtime = datetime.fromtimestamp(img.stat().st_mtime, tz=timezone.utc)
        page["fetched_at"] = mtime.isoformat()
        warnings.append(
            f"page {page.get('page_num')}: legacy record had local_path but no "
            f"fetched_at; backfilled from image mtime ({page['fetched_at']})"
        )
    return warnings


def _atomic_write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def summarize(volume: int, scandata_rows, out: dict, superseded: list[int]) -> dict:
    leaves = out["leaves"]
    kinds: dict[str, int] = {}
    for lf in leaves:
        kinds[lf["kind"]] = kinds.get(lf["kind"], 0) + 1
    return {
        "volume": volume,
        "scandata_leaves": len({leaf for leaf, _ in scandata_rows}),
        "migrated_leaves": len(leaves),
        "page_count": out["page_count"],
        "kinds": kinds,
        "superseded_leaf_images": superseded,
        "warnings": out.get("manifest_warnings", []),
    }


def migrate_volume(
    volume: int,
    *,
    repo_root: Path = REPO_ROOT,
    base_dir: Path = BASE_DIR,
    cache_dir: Path = SCANDATA_CACHE_DIR,
    apply: bool = False,
) -> dict:
    """Migrate one volume's manifest to v4. Returns a summary dict.

    Read-only unless ``apply`` is True; with ``apply`` it quarantines the old
    manifest (timestamped) + superseded leaf images, then atomically writes the
    new manifest in place (manifest-only-in-place -- no swap, no re-download).
    """
    DRY_RUN = not apply
    manifest_path = base_dir / f"vol_{volume:02d}.manifest.json"
    vdir = base_dir / f"vol_{volume:02d}"
    scandata_path = cache_dir / f"vol_{volume:02d}_scandata.xml"

    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    if not scandata_path.exists():
        raise FileNotFoundError(
            f"scandata cache not found: {scandata_path} -- run with --fetch-scandata first"
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "leaves" in manifest:
        raise ValueError(
            f"vol_{volume:02d} is already v4 (leaves[]); refusing to re-migrate. "
            "Use --verify-only to check it."
        )
    scandata_rows = parse_scandata_rows(scandata_path.read_text(encoding="utf-8"))

    for w in backfill_fetched_at_from_disk(manifest, repo_root):
        logger.warning("vol_%02d: %s", volume, w)
        manifest.setdefault("manifest_warnings", []).append(w)

    scandata_page_to_leaf = {p: leaf for leaf, p in scandata_rows if p is not None}
    body_map, _holes, _w = _body_leaf_map(manifest, scandata_page_to_leaf)
    body_leaf_nums = set(body_map)
    leaf_prov, superseded = discover_leaf_images(vdir, body_leaf_nums, manifest, repo_root)
    out = build_v4_manifest(scandata_rows, manifest, leaf_image_provenance=leaf_prov)

    result = summarize(volume, scandata_rows, out, superseded)

    if DRY_RUN:
        logger.info("[DRY RUN] vol_%02d: %s", volume, json.dumps(result["kinds"]))
        result["applied"] = False
        return result

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantine = manifest_path.with_name(f"vol_{volume:02d}.manifest.preP2_{ts}.json")
    os.replace(manifest_path, quarantine)
    _atomic_write_json(manifest_path, out)
    logger.info("vol_%02d: wrote v4 manifest; quarantined old -> %s", volume, quarantine.name)

    if superseded:
        sup_dir = vdir / "_superseded"
        sup_dir.mkdir(parents=True, exist_ok=True)
        for leaf in superseded:
            src = vdir / f"leaf_{leaf:04d}.jpg"
            if src.exists():
                os.replace(src, sup_dir / src.name)
        logger.info("vol_%02d: quarantined %d superseded leaf images -> %s",
                    volume, len(superseded), sup_dir.name)

    result["applied"] = True
    result["quarantined_manifest"] = quarantine.name
    return result


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--volume", type=int, action="append", dest="volumes",
                   help="volume number (repeatable); omit for all 12 P2 volumes")
    p.add_argument("--apply", action="store_true",
                   help="write changes (default is a dry run)")
    p.add_argument("--fetch-scandata", action="store_true",
                   help="fetch + cache scandata for the selected volumes first")
    return p


# The 12 P2 volumes (all except vol_11, shipped in P1).
_P2_VOLUMES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_arg_parser().parse_args(argv)
    volumes = args.volumes or _P2_VOLUMES

    if args.fetch_scandata:
        cached = cache_scandata(volumes)
        logger.info("scandata cached for volumes: %s", cached)

    results = []
    for vol in volumes:
        try:
            results.append(migrate_volume(vol, apply=args.apply))
        except HolesRequireDecision as exc:
            logger.error("vol_%02d BLOCKED: %s", vol, exc)
            results.append({"volume": vol, "blocked": "holes", "holes": exc.holes})
        except (FileNotFoundError, ValueError, AssertionError) as exc:
            logger.error("vol_%02d: %s", vol, exc)
            results.append({"volume": vol, "error": str(exc)})

    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
