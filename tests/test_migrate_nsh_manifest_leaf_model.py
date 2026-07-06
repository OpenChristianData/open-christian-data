"""Tests for build/tools/migrate_nsh_manifest_leaf_model.py -- the P2 NSH manifest
migration tool (legacy two-list shape -> v4 unified leaf-sequence model).

The migration's core (`build_v4_leaves`) is a PURE function over parsed inputs
(scandata rows + the legacy manifest + which front/back/plate images exist on
disk), so it is tested offline with synthetic + fixture data, no network.

Authority decisions encoded here (design docs/DESIGN_nsh_leaf_sequence_manifest.md
+ prompt pitfalls):
  - The leaf SPINE (which physical leaves exist, total count, classification of
    numbered vs unnumbered) comes from SCANDATA.
  - page_num VALUES come from the EXISTING MANIFEST's pages[] (running-header-
    verified; scandata's pageNumber was found wrong before -- PIPE-29). A
    scandata/manifest disagreement is a manifest_warning, manifest wins.
  - kind is derived from position (front/back/plate/body) + the discard flag.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = REPO_ROOT / "build" / "tools" / "migrate_nsh_manifest_leaf_model.py"
SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "source_manifest.schema.json"


def _load_tool():
    spec = importlib.util.spec_from_file_location("migrate_nsh_manifest_leaf_model", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_tool()


# --- helpers ---------------------------------------------------------------


def _fake_sha() -> str:
    return "sha256:" + hashlib.sha256(b"x").hexdigest()


def _page(page_num: int, leaf_id: int, *, provenance: dict | None = None,
          alt_item: str | None = None) -> dict:
    """A legacy primary (or alternate-source) page record with valid provenance."""
    rec = {
        "page_num": page_num,
        "ia_leaf_id": f"{leaf_id:04d}",
        "ia_filename": f"99.Foo._jp2/99.Foo._{leaf_id:04d}.jp2",
        "local_path": f"raw/internet-archive/schaff-herzog-pages/vol_99/page_{page_num:04d}.jpg",
        "sha256": _fake_sha(),
        "fetched_at": "2026-06-06T00:00:00+00:00",
        "image_mode": "L",
        "image_size": [1648, 2516],
        "ia_item_id": alt_item or "newschaffherzo99macauoft",
    }
    if provenance is not None:
        rec["provenance"] = provenance
    return rec


def _validate(manifest: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=manifest, schema=schema)


# --- the first behaviour: old-form volume, double-record de-overlapped -----


def test_old_form_body_from_manifest_front_back_from_scandata_spine():
    """Body leaves come from the manifest (keyed by primary leaf coord); front/
    back are derived from scandata position; the leading-run double-record in
    unnumbered_leaves is dropped; every scandata leaf appears exactly once."""
    # scandata: 8 leaves. front 0-2; reconstructed leading pages 1,2 at leaves
    # 3,4 (scandata did NOT number them); scandata numbers pages 3,4 at leaves
    # 5,6; back leaf 7.
    scandata_rows = [
        (0, None), (1, None), (2, None), (3, None),
        (4, None), (5, 3), (6, 4), (7, None),
    ]
    manifest = {
        "ia_item_id": "newschaffherzo99macauoft",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99,
        "created_at": "2026-06-01T00:00:00+00:00",
        "page_count": 4,
        "pages": [_page(1, 3), _page(2, 4), _page(3, 5), _page(4, 6)],
        # old-form double-record: leaves 3,4 listed as front_matter too
        "unnumbered_leaves": [
            {"leaf_num": 0, "section": "front_matter"},
            {"leaf_num": 1, "section": "front_matter"},
            {"leaf_num": 2, "section": "front_matter"},
            {"leaf_num": 3, "section": "front_matter"},
            {"leaf_num": 4, "section": "front_matter"},
            {"leaf_num": 7, "section": "back_matter"},
        ],
        "gaps": [],
    }

    leaves, _holes, warnings = mod.build_v4_leaves(scandata_rows, manifest)

    # one record per physical leaf, ordered
    assert [lf["leaf_num"] for lf in leaves] == [0, 1, 2, 3, 4, 5, 6, 7]
    by_leaf = {lf["leaf_num"]: lf for lf in leaves}

    # front matter (positioned, unimaged)
    for n in (0, 1, 2):
        assert by_leaf[n]["kind"] == "front_matter"
        assert by_leaf[n]["page_num"] is None
        assert by_leaf[n]["image_state"] == "pending"
        assert "local_path" not in by_leaf[n]

    # body (page_num from the manifest, image present)
    assert by_leaf[3]["kind"] == "body" and by_leaf[3]["page_num"] == 1
    assert by_leaf[6]["kind"] == "body" and by_leaf[6]["page_num"] == 4
    assert by_leaf[3]["image_state"] == "present"
    assert by_leaf[3]["local_path"].endswith("page_0001.jpg")

    # back matter
    assert by_leaf[7]["kind"] == "back_matter"
    assert by_leaf[7]["page_num"] is None

    # page_num set preserved exactly
    assert {lf["page_num"] for lf in leaves if lf["page_num"] is not None} == {1, 2, 3, 4}


def test_body_leaf_inherits_top_level_ia_item_id_when_page_omits_it():
    """Legacy pages[] often omit per-page ia_item_id (it's top-level only); the
    v4 leaf schema requires it with local_path, so the migration injects it."""
    scandata_rows = [(0, None), (3, 1), (4, 2), (5, None)]
    page = _page(1, 3)
    del page["ia_item_id"]  # legacy primary pages omit this
    page2 = _page(2, 4)
    del page2["ia_item_id"]
    manifest = {
        "ia_item_id": "newschaffherzo99macauoft",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 2,
        "pages": [page, page2], "gaps": [], "unnumbered_leaves": [],
    }
    out = mod.build_v4_manifest(scandata_rows, manifest)
    _validate(out)  # would fail if ia_item_id missing on the body leaf
    body = {lf["leaf_num"]: lf for lf in out["leaves"] if lf["kind"] == "body"}
    assert body[3]["ia_item_id"] == "newschaffherzo99macauoft"


def test_alternate_source_body_leaf_uses_primary_coordinate():
    """A haucgoog-recovered page keeps the PRIMARY-scan leaf coordinate
    (page_num + offset), NOT the alternate item's leaf id; provenance carried."""
    # offset 2: page 1 = leaf 3. Page 3 (leaf 5) recovered from an alternate item
    # whose own leaf id is 900 -- that must NOT become leaf_num.
    scandata_rows = [(0, None), (1, None), (2, None),
                     (3, 1), (4, 2), (5, 3), (6, 4), (7, None)]
    alt_page = _page(3, 900, alt_item="newschaffherzogXXhaucgoog",
                     provenance={"source_item_id": "newschaffherzogXXhaucgoog",
                                 "source_leaf": 900, "derivation": "direct",
                                 "crop_box": None,
                                 "replacement_reason": "missing from primary scan",
                                 "validation_status": "visual_header_only",
                                 "dimension_variance": False})
    manifest = {
        "ia_item_id": "newschaffherzo99macauoft",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 4,
        "pages": [_page(1, 3), _page(2, 4), alt_page, _page(4, 6)],
        "gaps": [], "unnumbered_leaves": [],
    }

    leaves, _holes, _warnings = mod.build_v4_leaves(scandata_rows, manifest)
    by_leaf = {lf["leaf_num"]: lf for lf in leaves}

    # primary coordinate 5 (= scandata leaf for page 3), not the alt item's leaf 900
    assert 900 not in by_leaf
    assert by_leaf[5]["kind"] == "body" and by_leaf[5]["page_num"] == 3
    assert by_leaf[5]["provenance"]["source_leaf"] == 900


def test_alt_source_page_present_in_scan_uses_scandata_primary_leaf():
    """An alternate-source page whose printed page DOES exist in the primary scan
    takes the primary leaf from scandata (not its bogus haucgoog ia_leaf_id)."""
    # scandata: page 3 sits at primary leaf 5. The manifest's page-3 record is
    # alternate-sourced with a bogus ia_leaf_id (900 = the haucgoog leaf).
    scandata_rows = [(0, None), (3, 1), (4, 2), (5, 3), (6, 4), (7, None)]
    alt = _page(3, 900, alt_item="hg", provenance={"source_item_id": "hg",
                "source_leaf": 900, "derivation": "direct", "crop_box": None,
                "replacement_reason": "bad primary image",
                "validation_status": "visual_header_only", "dimension_variance": False})
    manifest = {
        "ia_item_id": "newschaffherzo99macauoft",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 4,
        "pages": [_page(1, 3), _page(2, 4), alt, _page(4, 6)],
        "gaps": [], "unnumbered_leaves": [],
    }
    leaves, holes, _w = mod.build_v4_leaves(scandata_rows, manifest)
    by_leaf = {lf["leaf_num"]: lf for lf in leaves}
    assert 900 not in by_leaf
    assert by_leaf[5]["page_num"] == 3 and by_leaf[5]["kind"] == "body"
    assert by_leaf[5]["provenance"]["source_leaf"] == 900
    assert holes == []


def test_true_hole_surfaced_when_page_absent_from_primary_scan():
    """A recovered page with NO primary-scan leaf (scandata skips it) cannot be
    placed by an integer leaf coordinate -- it is surfaced as a hole, never
    dropped silently and never collided onto another page's leaf."""
    # scandata skips page 3 entirely: leaf 5 = page 4 (not 3).
    scandata_rows = [(0, None), (3, 1), (4, 2), (5, 4), (6, 5), (7, None)]
    alt3 = _page(3, 128, alt_item="hg", provenance={"source_item_id": "hg",
                "source_leaf": 128, "derivation": "direct", "crop_box": None,
                "replacement_reason": "missing from primary scan",
                "validation_status": "visual_header_only", "dimension_variance": False})
    manifest = {
        "ia_item_id": "newschaffherzo99macauoft",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 4,
        "pages": [_page(1, 3), _page(2, 4), alt3, _page(4, 5), _page(5, 6)],
        "gaps": [], "unnumbered_leaves": [],
    }
    leaves, holes, _w = mod.build_v4_leaves(scandata_rows, manifest)
    # page 3 is not placed onto any leaf (no collision with page 4 at leaf 5)
    assert holes == [3]
    placed_pages = {lf["page_num"] for lf in leaves if lf["page_num"] is not None}
    assert 3 not in placed_pages
    assert {lf["leaf_num"] for lf in leaves} == {0, 3, 4, 5, 6, 7}  # every scan leaf once


def test_primary_item_provenance_page_places_at_own_leaf_not_hole():
    """A page that carries a provenance block but whose ia_item_id is the volume's
    PRIMARY item (e.g. vol_13 front matter recovered from the same item, leaves
    18-24) is in the primary namespace -- it places at its own ia_leaf_id as body,
    NOT a cross-namespace hole. scandata leaves these front leaves un-numbered
    (pageNumber=None), so without this rule the tool falsely holes the page and
    classifies its leaf as a plate."""
    # leaf 4 is page 2 per the manifest; scandata did NOT number leaf 4.
    scandata_rows = [(0, None), (1, None), (2, None),
                     (3, 1), (4, None), (5, 3), (6, None)]
    same_item = "newschaffherzo99macauoft"  # the manifest's primary item
    page2 = _page(2, 4, alt_item=same_item,
                  provenance={"source_item_id": same_item, "source_leaf": 4,
                              "derivation": "direct", "crop_box": None,
                              "replacement_reason": "missing from primary scan; "
                              "fetched from alternate Internet Archive item",
                              "validation_status": "bibliographic_matched",
                              "dimension_variance": False})
    manifest = {
        "ia_item_id": same_item,
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 3,
        "pages": [_page(1, 3), page2, _page(3, 5)],
        "gaps": [], "unnumbered_leaves": [],
    }

    leaves, holes, _w = mod.build_v4_leaves(scandata_rows, manifest)
    by_leaf = {lf["leaf_num"]: lf for lf in leaves}

    assert holes == []  # primary-namespace page is placed, never a hole
    assert by_leaf[4]["kind"] == "body" and by_leaf[4]["page_num"] == 2
    assert by_leaf[4]["provenance"]["source_item_id"] == same_item


def _cross_namespace_recovery_manifest(*, with_existing_gap=False, image=True):
    """A volume with one Scenario-A recovery: page 3 was skipped by the primary
    scan (scandata jumps leaf 4 = page 4) and recovered from an alternate item."""
    scandata_rows = [(0, None), (3, 1), (4, 2), (5, 4), (6, 5), (7, None)]
    alt3 = _page(3, 128, alt_item="newschaffherzogXXhaucgoog",
                 provenance={"source_item_id": "newschaffherzogXXhaucgoog",
                             "source_leaf": 128, "derivation": "direct",
                             "crop_box": None,
                             "replacement_reason": "missing from primary scan",
                             "validation_status": "visual_header_only",
                             "dimension_variance": False})
    if not image:
        for f in ("local_path", "sha256", "fetched_at", "image_mode", "image_size"):
            alt3.pop(f, None)
    gaps = []
    if with_existing_gap:
        gaps = [{"page_num": 3, "status": "resolved",
                 "investigation_note": "recovered from newschaffherzogXXhaucgoog leaf 128",
                 "resolved_from": "newschaffherzogXXhaucgoog"}]
    manifest = {
        "ia_item_id": "newschaffherzo99macauoft",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 5,
        "pages": [_page(1, 3), _page(2, 4), alt3, _page(4, 5), _page(5, 6)],
        "gaps": gaps, "unnumbered_leaves": [],
    }
    return scandata_rows, manifest


def test_cross_namespace_recovery_routed_to_enriched_gap_no_raise():
    """A recovered page with no primary-scan leaf is NOT placed in leaves[]; it is
    recorded in gaps[] with its full image provenance (local_path + sha256 +
    provenance + page_num). build_v4_manifest must NOT raise, and the result is
    schema-valid (path (a) / Option C, design Q1 keeps gaps[])."""
    scandata_rows, manifest = _cross_namespace_recovery_manifest()
    out = mod.build_v4_manifest(scandata_rows, manifest)  # must not raise
    _validate(out)

    placed = {lf["page_num"] for lf in out["leaves"] if lf["page_num"] is not None}
    assert 3 not in placed  # the recovery is not a spine leaf
    # page_count is the printed body-page count (5), NOT the body-leaf count (4):
    # the recovered page is a real body page even though it has no spine leaf.
    assert out["page_count"] == 5

    gap3 = [g for g in out["gaps"] if g["page_num"] == 3]
    assert len(gap3) == 1
    g = gap3[0]
    assert g["local_path"].endswith("page_0003.jpg")
    assert g["sha256"].startswith("sha256:")
    assert g["provenance"]["source_item_id"] == "newschaffherzogXXhaucgoog"
    assert g["ia_item_id"] == "newschaffherzogXXhaucgoog"


def test_recovered_gap_merges_with_existing_gap_entry_no_duplicate():
    """When the manifest already carries a gaps[] entry for the recovered page,
    the migration enriches that entry in place (adds the image fields) -- it does
    not create a second entry, and the prior status/investigation_note survive."""
    scandata_rows, manifest = _cross_namespace_recovery_manifest(with_existing_gap=True)
    out = mod.build_v4_manifest(scandata_rows, manifest)
    _validate(out)

    gap3 = [g for g in out["gaps"] if g["page_num"] == 3]
    assert len(gap3) == 1  # merged, not duplicated
    g = gap3[0]
    assert g["status"] == "resolved"
    assert "recovered from" in g["investigation_note"]  # prior note preserved
    assert g["resolved_from"] == "newschaffherzogXXhaucgoog"
    assert g["local_path"].endswith("page_0003.jpg")  # enriched


def test_primary_item_id_but_alternate_provenance_is_cross_namespace():
    """Codex review A: a record whose ia_item_id is the primary item but whose
    provenance.source_item_id is an ALTERNATE item is genuinely cross-namespace
    (its ia_leaf_id is the alternate's), so it must NOT place at its own leaf --
    it goes through scandata and becomes a hole if the primary scan skipped it."""
    scandata_rows = [(0, None), (3, 1), (4, 2), (5, 4), (6, 5), (7, None)]  # page 3 skipped
    primary = "newschaffherzo99macauoft"
    mixed = _page(3, 900, alt_item=primary,  # ia_item_id says primary...
                  provenance={"source_item_id": "newschaffherzogXXhaucgoog",  # ...prov says alt
                              "source_leaf": 900, "derivation": "direct", "crop_box": None,
                              "replacement_reason": "missing from primary scan",
                              "validation_status": "visual_header_only",
                              "dimension_variance": False})
    manifest = {
        "ia_item_id": primary,
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 4,
        "pages": [_page(1, 3), _page(2, 4), mixed, _page(4, 5), _page(5, 6)],
        "gaps": [], "unnumbered_leaves": [],
    }
    leaves, holes, _w = mod.build_v4_leaves(scandata_rows, manifest)
    assert holes == [3]               # not placed at its foreign ia_leaf_id 900
    assert 900 not in {lf["leaf_num"] for lf in leaves}


def test_recovered_gap_status_upgraded_when_image_added():
    """Codex review B: if an existing gap is permanently_missing but the page has
    an on-disk image (a recovery), enriching it must set status to resolved -- a
    gap cannot be both image-present and missing -- and warn about the override."""
    scandata_rows, manifest = _cross_namespace_recovery_manifest()
    manifest["gaps"] = [{"page_num": 3, "status": "permanently_missing",
                         "investigation_note": "was thought lost"}]
    out = mod.build_v4_manifest(scandata_rows, manifest)
    g3 = [g for g in out["gaps"] if g["page_num"] == 3][0]
    assert g3["status"] == "resolved"
    assert g3.get("local_path")
    assert any("status" in w and "3" in w for w in out.get("manifest_warnings", []))


def test_invariants_detect_page_both_leaf_and_hole():
    """Codex review D: a page that is BOTH a placed leaf and a hole is incoherent;
    the coverage union would hide it. Assert disjointness catches it."""
    scandata_rows, manifest = _old_form_manifest()
    leaves, _h, _w = mod.build_v4_leaves(scandata_rows, manifest)
    placed_page = next(lf["page_num"] for lf in leaves if lf["page_num"] is not None)
    with pytest.raises(AssertionError):
        mod.assert_migration_invariants(leaves, scandata_rows, manifest, holes=[placed_page])


def test_recovery_without_on_disk_image_still_raises():
    """The safety guard survives: a page with no primary-scan leaf AND no on-disk
    image cannot be placed anywhere (no spine slot, no image to record in gaps[]),
    so the migration refuses rather than write an incomplete manifest."""
    scandata_rows, manifest = _cross_namespace_recovery_manifest(image=False)
    with pytest.raises(mod.HolesRequireDecision):
        mod.build_v4_manifest(scandata_rows, manifest)


def test_primary_page_with_inflated_ia_leaf_id_uses_scandata_leaf_avoiding_collision():
    """P2b leaf-coordinate rule (the vol_10 fix): a primary page's leaf_num is the
    SCANDATA physical leafNum for its printed page, NOT int(ia_leaf_id) -- even when
    the manifest's ia_leaf_id is inflated (vol_10's +8 back-matter bookkeeping). The
    inflated ia_leaf_id is retained in the leaf's image block as the source-download
    reference; the divergence is warned (informational, not an error).

    The failure this prevents: under the old rule (leaf_num = int(ia_leaf_id)) the
    inflated primary leaf COLLIDES with a cross-namespace recovery placed at the same
    scandata leaf, silently dropping a page. Here page 3's ia_leaf_id (4) collides
    with the alternate-source recovery of page 4 (scandata leaf 4); the scandata-leaf
    rule places page 3 at its true leaf 3, so both survive."""
    # scandata: front leaf 0; body leaves 1..4 = pages 1..4; back leaf 5.
    scandata_rows = [(0, None), (1, 1), (2, 2), (3, 3), (4, 4), (5, None)]
    primary = "newschaffherzo99macauoft"
    # page 3's ia_leaf_id is INFLATED to 4 (scandata says page 3 is physical leaf 3).
    inflated = _page(3, 4)
    # page 4 recovered cross-namespace; its primary leaf (from scandata) is 4 -- the
    # exact leaf the old rule would have given page 3 via its inflated ia_leaf_id.
    recovered4 = _page(4, 700, alt_item="newschaffherzogXXhaucgoog",
                       provenance={"source_item_id": "newschaffherzogXXhaucgoog",
                                   "source_leaf": 700, "derivation": "direct",
                                   "crop_box": None,
                                   "replacement_reason": "bad primary image",
                                   "validation_status": "visual_header_only",
                                   "dimension_variance": False})
    manifest = {
        "ia_item_id": primary,
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 4,
        "pages": [_page(1, 1), _page(2, 2), inflated, recovered4],
        "gaps": [], "unnumbered_leaves": [],
    }

    leaves, holes, warnings = mod.build_v4_leaves(scandata_rows, manifest)
    by_leaf = {lf["leaf_num"]: lf for lf in leaves}

    # page 3 placed at its TRUE scandata leaf 3, NOT the inflated ia_leaf_id 4
    assert by_leaf[3]["kind"] == "body" and by_leaf[3]["page_num"] == 3
    # the cross-namespace recovery keeps scandata leaf 4 -- no collision, page survives
    assert by_leaf[4]["page_num"] == 4
    # the inflated ia_leaf_id is RETAINED in the image block (source-download ref)
    assert by_leaf[3]["ia_leaf_id"] == "0004"
    # the divergence is warned, naming the page and both coordinates
    assert any("ia_leaf_id" in w and "page 3" in w and "leaf 3" in w for w in warnings)
    # both pages survive; the invariants (which the OLD rule's collision would fail) pass
    assert {3, 4} <= {lf["page_num"] for lf in leaves if lf["page_num"] is not None}
    mod.assert_migration_invariants(leaves, scandata_rows, manifest, holes)


def test_leading_run_page_keeps_ia_leaf_id_when_scandata_unnumbered():
    """The leading run (printed pages before scandata starts numbering) has no
    scandata pageNumber, so leaf_num falls back to int(ia_leaf_id) -- the verified
    pre-numbering physical coordinate (no inflation there). No spurious divergence
    warning is emitted for the leading run."""
    # scandata numbers from leaf 5 (page 3); leaves 3,4 (pages 1,2) are unnumbered.
    scandata_rows = [(0, None), (1, None), (2, None),
                     (3, None), (4, None), (5, 3), (6, 4), (7, None)]
    manifest = {
        "ia_item_id": "newschaffherzo99macauoft",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 4,
        "pages": [_page(1, 3), _page(2, 4), _page(3, 5), _page(4, 6)],
        "gaps": [], "unnumbered_leaves": [],
    }
    leaves, _holes, warnings = mod.build_v4_leaves(scandata_rows, manifest)
    by_leaf = {lf["leaf_num"]: lf for lf in leaves}
    # leading-run pages 1,2 placed at their ia_leaf_id leaves 3,4
    assert by_leaf[3]["page_num"] == 1 and by_leaf[4]["page_num"] == 2
    # scandata-numbered pages 3,4 placed at scandata leaves 5,6 (== ia_leaf_id, no warn)
    assert by_leaf[5]["page_num"] == 3 and by_leaf[6]["page_num"] == 4
    assert not any("ia_leaf_id" in w for w in warnings)


def test_monotonicity_warning_fires_when_scandata_leaf_out_of_order():
    """Soft guard for the scandata-leaf rule (PIPE-29): if a scandata pageNumber is
    mis-OCR'd such that a page lands on a leaf out of page-order, body leaf_num is no
    longer monotonic in page_num. The migration must surface this as a warning (the
    method trusts scandata's leaf, so an out-of-order placement is the tell)."""
    # scandata claims page 2 sits at leaf 6 and page 3 at leaf 4 -- inverted order.
    scandata_rows = [(0, None), (3, 1), (6, 2), (4, 3), (7, 4), (8, None)]
    manifest = {
        "ia_item_id": "newschaffherzo99macauoft",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 4,
        "pages": [_page(1, 3), _page(2, 6), _page(3, 4), _page(4, 7)],
        "gaps": [], "unnumbered_leaves": [],
    }
    _leaves, _holes, warnings = mod.build_v4_leaves(scandata_rows, manifest)
    assert any("monotonic" in w.lower() for w in warnings)


def test_monotonic_volume_emits_no_monotonicity_warning():
    """True-negative for the soft guard: an in-order volume produces no monotonicity
    warning (so the rule change stays a no-op for the 11 already-migrated volumes)."""
    scandata_rows, manifest = _old_form_manifest()
    _leaves, _holes, warnings = mod.build_v4_leaves(scandata_rows, manifest)
    assert not any("monotonic" in w.lower() for w in warnings)


def test_scandata_page_num_disagreement_warns_manifest_wins():
    """When scandata's pageNumber for a leaf disagrees with the manifest's
    page_num, the manifest value is kept and a warning is recorded."""
    # leaf 5 is page 3 per the manifest, but scandata claims page 99 there.
    scandata_rows = [(0, None), (1, None), (2, None),
                     (3, None), (4, None), (5, 99), (6, 4), (7, None)]
    manifest = {
        "ia_item_id": "newschaffherzo99macauoft",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 4,
        "pages": [_page(1, 3), _page(2, 4), _page(3, 5), _page(4, 6)],
        "gaps": [], "unnumbered_leaves": [],
    }

    leaves, _holes, warnings = mod.build_v4_leaves(scandata_rows, manifest)
    by_leaf = {lf["leaf_num"]: lf for lf in leaves}

    assert by_leaf[5]["page_num"] == 3  # manifest wins
    assert any("99" in w and "5" in w for w in warnings)


def _old_form_manifest():
    scandata_rows = [(0, None), (1, None), (2, None), (3, None),
                     (4, None), (5, 3), (6, 4), (7, None)]
    manifest = {
        "ia_item_id": "newschaffherzo99macauoft",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 4,
        "pages": [_page(1, 3), _page(2, 4), _page(3, 5), _page(4, 6)],
        "unnumbered_leaves": [{"leaf_num": n, "section": "front_matter"} for n in range(5)]
        + [{"leaf_num": 7, "section": "back_matter"}],
        "gaps": [],
    }
    return scandata_rows, manifest


def test_invariants_pass_on_good_migration():
    scandata_rows, manifest = _old_form_manifest()
    leaves, _h, _w = mod.build_v4_leaves(scandata_rows, manifest)
    # must not raise
    mod.assert_migration_invariants(leaves, scandata_rows, manifest)


def test_invariants_detect_dropped_leaf():
    scandata_rows, manifest = _old_form_manifest()
    leaves, _h, _w = mod.build_v4_leaves(scandata_rows, manifest)
    with pytest.raises(AssertionError):
        mod.assert_migration_invariants(leaves[:-1], scandata_rows, manifest)


def test_invariants_detect_kind_mismatch():
    scandata_rows, manifest = _old_form_manifest()
    leaves, _h, _w = mod.build_v4_leaves(scandata_rows, manifest)
    leaves[0]["kind"] = "back_matter"  # leaf 0 is really front_matter
    with pytest.raises(AssertionError):
        mod.assert_migration_invariants(leaves, scandata_rows, manifest)


def test_plate_detected_for_interior_unnumbered_leaf():
    """A null-pageNumber leaf INSIDE the body span is a plate, tagged with the
    printed page it follows."""
    # leaf 6 is an interior unnumbered leaf between body pages 3 (leaf 5) and 4 (leaf 7)
    scandata_rows = [(0, None), (3, 1), (4, 2), (5, 3), (6, None), (7, 4), (8, None)]
    manifest = {
        "ia_item_id": "newschaffherzo99macauoft",
        "ia_derivative_type": "Single Page Processed JP2 ZIP",
        "volume": 99, "created_at": "2026-06-01T00:00:00+00:00", "page_count": 4,
        "pages": [_page(1, 3), _page(2, 4), _page(3, 5), _page(4, 7)],
        "gaps": [], "unnumbered_leaves": [],
    }
    leaves, _h, _w = mod.build_v4_leaves(scandata_rows, manifest)
    by_leaf = {lf["leaf_num"]: lf for lf in leaves}
    assert by_leaf[6]["kind"] == "plate"
    assert by_leaf[6]["after_page_num"] == 3


def test_full_manifest_is_schema_valid():
    scandata_rows, manifest = _old_form_manifest()
    out = mod.build_v4_manifest(scandata_rows, manifest)
    _validate(out)
    # v4 shape: leaves present, legacy arrays gone
    assert "leaves" in out and "pages" not in out and "unnumbered_leaves" not in out
    assert out["page_count"] == 4
    assert out["volume"] == 99
    # gaps carried verbatim
    assert out["gaps"] == manifest["gaps"]


def test_front_back_image_present_when_provenance_injected():
    """A front/back leaf with an on-disk image (vol_01 orphans) gets
    image_state=present + its provenance; leaves without an image stay pending."""
    scandata_rows, manifest = _old_form_manifest()
    leaf_prov = {
        0: {
            "local_path": "raw/internet-archive/schaff-herzog-pages/vol_99/leaf_0000.jpg",
            "ia_leaf_id": "0000",
            "ia_filename": "99.Foo._jp2/99.Foo._0000.jp2",
            "ia_item_id": "newschaffherzo99macauoft",
            "sha256": _fake_sha(),
            "fetched_at": "2026-06-11T00:00:00+00:00",
            "image_mode": "L",
            "image_size": [1648, 2516],
        }
    }
    leaves, _h, _w = mod.build_v4_leaves(scandata_rows, manifest, leaf_image_provenance=leaf_prov)
    by_leaf = {lf["leaf_num"]: lf for lf in leaves}

    assert by_leaf[0]["kind"] == "front_matter"
    assert by_leaf[0]["image_state"] == "present"
    assert by_leaf[0]["local_path"].endswith("leaf_0000.jpg")
    assert by_leaf[0]["ia_leaf_id"] == "0000"
    # a front leaf with no image stays pending
    assert by_leaf[1]["image_state"] == "pending" and "local_path" not in by_leaf[1]

    # still schema-valid through the full builder
    out = mod.build_v4_manifest(scandata_rows, manifest, leaf_image_provenance=leaf_prov)
    _validate(out)


# --- backfill a legacy record's lost fetched_at from the image mtime ---------


def test_backfill_fetched_at_from_disk_recovers_lost_timestamp(tmp_path):
    """A legacy page with an on-disk image but a missing fetched_at (a real
    pre-existing defect in vol_13 pages 1/5/9) is repaired from the image file's
    mtime -- a real observable property, not a fabricated value. Pages that
    already carry fetched_at are left untouched."""
    vdir = tmp_path / "vol_99"
    img = vdir / "page_0009.jpg"
    _write_jpg(img)
    import os
    os.utime(img, (1_700_000_000, 1_700_000_000))  # fixed mtime

    rel = "vol_99/page_0009.jpg"
    bad = _page(9, 25)
    bad["local_path"] = rel
    del bad["fetched_at"]
    good = _page(8, 24)
    good["local_path"] = "vol_99/page_0008.jpg"
    good_ts = good["fetched_at"]
    manifest = {"ia_item_id": "x", "pages": [bad, good]}

    warnings = mod.backfill_fetched_at_from_disk(manifest, tmp_path)

    assert "fetched_at" in bad and bad["fetched_at"].startswith("2023-11-")  # 1.7e9 epoch
    assert good["fetched_at"] == good_ts  # untouched
    assert any("9" in w and "fetched_at" in w for w in warnings)


def test_backfill_fetched_at_noop_when_all_complete(tmp_path):
    """No image-bearing page is missing fetched_at -> no change, no warning."""
    manifest = {"ia_item_id": "x", "pages": [_page(1, 3), _page(2, 4)]}
    before = json.dumps(manifest, sort_keys=True)
    warnings = mod.backfill_fetched_at_from_disk(manifest, tmp_path)
    assert warnings == []
    assert json.dumps(manifest, sort_keys=True) == before


# --- real-data: vol_03 scandata fixture + the live manifest (PIPE-29) -------

_VOL03_SCANDATA = REPO_ROOT / "tests" / "fixtures" / "fetch_ia_pages" / "vol_03_scandata.xml"
_VOL03_MANIFEST = (REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
                   / "vol_03.manifest.json")


def test_parse_scandata_rows_from_fixture():
    rows = mod.parse_scandata_rows(_VOL03_SCANDATA.read_text(encoding="utf-8"))
    assert len(rows) == 531
    leaves = [leaf for leaf, _ in rows]
    assert min(leaves) == 0 and max(leaves) == 530
    assert len(set(leaves)) == 531  # contiguous, unique


@pytest.mark.skipif(not _VOL03_MANIFEST.exists(), reason="raw/ vol_03 manifest not downloaded")
def test_real_vol03_migration_reconciles_to_scandata():
    """vol_03 reconciles to its scandata in the v4 model. Works whether the
    on-disk manifest is still legacy (pre-migration) or already v4 (post-P2):
    a legacy manifest is migrated here; a v4 manifest is verified as-is."""
    rows = mod.parse_scandata_rows(_VOL03_SCANDATA.read_text(encoding="utf-8"))
    manifest = json.loads(_VOL03_MANIFEST.read_text(encoding="utf-8"))
    if "leaves" in manifest:
        out = manifest  # already migrated (P2 applied); verify the on-disk v4
        prior = {lf["page_num"] for lf in out["leaves"] if lf["page_num"] is not None}
    else:
        out = mod.build_v4_manifest(rows, manifest)  # raises if invariants fail
        prior = {p["page_num"] for p in manifest["pages"]}
    _validate(out)

    leaves = out["leaves"]
    assert len(leaves) == 531  # every scandata leaf, no drop
    assert out["page_count"] == 500
    # the old-form double-record (front leaves 23-31) is gone: each appears once
    assert len({lf["leaf_num"] for lf in leaves}) == 531
    # page_num set preserved exactly vs the prior manifest
    assert {lf["page_num"] for lf in leaves if lf["page_num"] is not None} == prior
    # front matter precedes the first body leaf; back follows the last
    body = sorted(lf["leaf_num"] for lf in leaves if lf["kind"] == "body")
    fronts = [lf["leaf_num"] for lf in leaves if lf["kind"] == "front_matter"]
    backs = [lf["leaf_num"] for lf in leaves if lf["kind"] == "back_matter"]
    assert all(f < body[0] for f in fronts)
    assert all(b > body[-1] for b in backs)


# --- no-op proof: the P2b scandata-leaf rule must not change the 11 migrated ---
# For 01-09/12/13, ia_leaf_id == scandata leafNum, so the new rule (leaf_num =
# scandata leaf) must reproduce the OLD rule (leaf_num = int(ia_leaf_id)) exactly.
# We re-run the NEW tool on each volume's quarantined LEGACY manifest and assert
# the resulting leaves[] is byte-identical (leaf_num+page_num+kind+image_state) to
# the committed v4 (leaf_num+page_num+kind; image_state excluded post-P3 — see below).
# Guarded: the quarantined manifest + scandata cache are in raw/
# (gitignored), so this runs locally and skips on a clean CI checkout.

_NSH_BASE = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"
_SCANDATA_CACHE = _NSH_BASE / "scandata_cache"


def _newest_quarantine(vol: int) -> Path | None:
    quars = sorted(_NSH_BASE.glob(f"vol_{vol:02d}.manifest.preP2_*.json"))
    return quars[-1] if quars else None


def _noop_inputs_available(vol: int) -> bool:
    live = _NSH_BASE / f"vol_{vol:02d}.manifest.json"
    cache = _SCANDATA_CACHE / f"vol_{vol:02d}_scandata.xml"
    if not (live.exists() and cache.exists() and _newest_quarantine(vol)):
        return False
    return "leaves" in json.loads(live.read_text(encoding="utf-8"))


# image_state excluded: after P3 imaging, non-body leaves carry 'present' or
# 'not_imaged'; P2b's scandata rule cannot reproduce blank detection and would
# regress them to 'pending'. The no-op invariant covers numbering only.
_STRUCT_KEYS = ("leaf_num", "page_num", "kind")


@pytest.mark.parametrize("vol", [3, 6])  # vol_03 clean, vol_06 holed (recovered-gap)
def test_p2b_rule_is_noop_for_migrated_volumes(vol):
    """The scandata-leaf rule produces the same leaf_num/page_num/kind assignments
    as the committed v4 leaves[] when re-run on the quarantined legacy manifest.
    image_state is excluded: P3 imaging advances leaves beyond what P2b can reproduce.
    Operator-discarded leaves (kind='discarded' in the committed manifest) are also
    excluded: the 2a discard is a post-migration override the scandata rule cannot
    reproduce -- same rationale as image_state above."""
    if not _noop_inputs_available(vol):
        pytest.skip(f"vol_{vol:02d} legacy quarantine / scandata cache not on disk")
    rows = mod.parse_scandata_rows(
        (_SCANDATA_CACHE / f"vol_{vol:02d}_scandata.xml").read_text(encoding="utf-8"))
    legacy = json.loads(_newest_quarantine(vol).read_text(encoding="utf-8"))
    live = json.loads((_NSH_BASE / f"vol_{vol:02d}.manifest.json").read_text(encoding="utf-8"))

    # replicate migrate_volume's read path on the LEGACY manifest
    mod.backfill_fetched_at_from_disk(legacy, REPO_ROOT)
    scan_p2l = {p: lf for lf, p in rows if p is not None}
    body_map, _h, _w = mod._body_leaf_map(legacy, scan_p2l)
    vdir = _NSH_BASE / f"vol_{vol:02d}"
    leaf_prov, _sup = mod.discover_leaf_images(vdir, set(body_map), legacy, REPO_ROOT)
    out = mod.build_v4_manifest(rows, legacy, leaf_image_provenance=leaf_prov)

    # Exclude operator-discarded leaves: 2a sets kind='discarded' as a post-migration
    # override the scandata rule has no knowledge of and cannot reproduce.
    discarded_leaf_nums = {
        lf["leaf_num"] for lf in live["leaves"] if lf.get("kind") == "discarded"
    }
    new_struct = [
        {k: lf.get(k) for k in _STRUCT_KEYS}
        for lf in out["leaves"]
        if lf.get("leaf_num") not in discarded_leaf_nums
    ]
    cur_struct = [
        {k: lf.get(k) for k in _STRUCT_KEYS}
        for lf in live["leaves"]
        if lf.get("kind") != "discarded"
    ]
    assert new_struct == cur_struct, (
        f"vol_{vol:02d}: scandata-leaf rule changed leaves[] vs committed v4 "
        f"(expected a no-op)"
    )


# --- on-disk leaf-image discovery (vol_01 orphans, design SS4.5) ------------


def _write_jpg(path: Path) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (8, 10)).save(path, "JPEG")


def test_discover_leaf_images_maps_front_back_and_flags_body_dups(tmp_path):
    """leaf_*.jpg for a non-body leaf becomes referenced provenance; leaf_*.jpg
    that duplicates a body leaf is flagged superseded (not referenced)."""
    vdir = tmp_path / "vol_99"
    _write_jpg(vdir / "leaf_0000.jpg")   # front matter -> map in
    _write_jpg(vdir / "leaf_0037.jpg")   # duplicates body leaf 37 -> superseded
    _write_jpg(vdir / "leaf_0540.jpg")   # back matter -> map in
    _write_jpg(vdir / "page_0001.jpg")   # body image, ignored by this scan

    manifest = {
        "ia_item_id": "newschaffherzo99macauoft",
        "pages": [_page(1, 37)],  # body leaf 37
    }
    body_leaf_nums = {37}

    prov, superseded = mod.discover_leaf_images(vdir, body_leaf_nums, manifest, tmp_path)

    assert set(prov) == {0, 540}
    assert superseded == [37]
    # provenance is schema-complete for a present leaf
    p0 = prov[0]
    assert p0["local_path"].endswith("leaf_0000.jpg")
    assert p0["ia_leaf_id"] == "0000"
    assert p0["ia_item_id"] == "newschaffherzo99macauoft"
    assert p0["sha256"].startswith("sha256:") and p0["image_size"] == [8, 10]
    assert "_0000.jp2" in p0["ia_filename"]  # derived from the volume's jp2 pattern
    # local_path is repo-root-relative (OUT-03)
    assert not p0["local_path"].startswith(str(tmp_path))
