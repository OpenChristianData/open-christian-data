"""Tests for the R6a primary-chain leaf-keying verifier (TEST-08).

The verifier reads the gitignored OCR stores on disk and asserts the four
primary-chain invariants (design plans/2026-06-13-nsh-leaf-rekey-design.md SS5 R6a):

  (a) every primary S1 sidecar + S1 manifest page + S2 rendering for a *body*
      leaf carries an int ``canonical_leaf_id`` equal to the leaf it resolves to;
  (b) reuse held -- no body leaf's sidecar ``source_payload_sha256`` disagrees
      with the current canonical manifest (a disagreement is a re-OCR/staleness);
  (c) cross-engine joins are leaf-keyed -- two primary engines that both OCR'd
      one leaf carry the SAME content sha under that ``canonical_leaf_id``;
  (d) each current-shape S2 rendering dir == the S1 manifest's body-leaf set.

Recovered-gap pages (``gaps[]``, no spine leaf), non-body preserved sidecars,
and 1:N duplicate-sha leaves are EXEMPT from (a) and reported in their own
buckets -- they legitimately carry no single ``canonical_leaf_id``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_pipeline import verify_leaf_keying as vlk  # noqa: E402


# --- (a) page classification ------------------------------------------------

def _index(leaves):
    """Build (by_sha, gaps, body_leaf_nums) from a leaves list the way the
    verifier does, so classification tests share the production indexer."""
    manifest = {"leaves": leaves, "page_count": len(leaves), "volume": 1}
    return vlk.build_indices(manifest)


def test_body_leaf_with_correct_leaf_id_is_ok():
    leaves = [{"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa"}]
    by_sha, gaps, body = _index(leaves)
    assert vlk.classify_page(10, "sha256:aaa", by_sha=by_sha, gaps=gaps, body_leaf_nums=body) == vlk.BODY_OK


def test_body_leaf_missing_leaf_id_is_flagged():
    leaves = [{"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa"}]
    by_sha, gaps, body = _index(leaves)
    assert vlk.classify_page(None, "sha256:aaa", by_sha=by_sha, gaps=gaps, body_leaf_nums=body) == vlk.BODY_MISSING_LEAF


def test_body_leaf_wrong_leaf_id_is_flagged():
    leaves = [{"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa"}]
    by_sha, gaps, body = _index(leaves)
    # stamped 99 but the sha resolves to leaf 10
    assert vlk.classify_page(99, "sha256:aaa", by_sha=by_sha, gaps=gaps, body_leaf_nums=body) == vlk.BODY_WRONG_LEAF


def test_sha_prefix_is_normalised():
    leaves = [{"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa"}]
    by_sha, gaps, body = _index(leaves)
    # bare sha (no "sha256:" prefix) must still resolve to the same leaf
    assert vlk.classify_page(10, "aaa", by_sha=by_sha, gaps=gaps, body_leaf_nums=body) == vlk.BODY_OK


def test_recovered_gap_page_is_exempt():
    leaves = [{"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa"}]
    manifest = {
        "leaves": leaves,
        "gaps": [{"page_num": 96, "sha256": "sha256:ggg", "local_path": "x"}],
        "page_count": 1,
        "volume": 1,
    }
    by_sha, gaps, body = vlk.build_indices(manifest)
    # a gap-page sidecar legitimately has no canonical_leaf_id
    assert vlk.classify_page(None, "sha256:ggg", by_sha=by_sha, gaps=gaps, body_leaf_nums=body) == vlk.GAP


def test_nonbody_leaf_is_exempt():
    leaves = [
        {"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa"},
        {"leaf_num": 2, "page_num": None, "kind": "plate", "sha256": "sha256:fff"},
    ]
    by_sha, gaps, body = _index(leaves)
    assert vlk.classify_page(None, "sha256:fff", by_sha=by_sha, gaps=gaps, body_leaf_nums=body) == vlk.NONBODY


def test_frontback_leaf_with_valid_edition_key_is_named_ok():
    leaves = [
        {"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa"},
        {"leaf_num": 2, "page_num": None, "kind": "front_matter", "sha256": "sha256:fff"},
    ]
    by_sha, gaps, body = _index(leaves)
    assert (
        vlk.classify_page(
            None,
            "sha256:fff",
            by_sha=by_sha,
            gaps=gaps,
            body_leaf_nums=body,
            edition_page_key={"section": "front_matter", "anchor": 1, "ordinal": 0},
        )
        == vlk.FRONTBACK_OK
    )


def test_frontback_leaf_without_valid_edition_key_is_named_failure():
    leaves = [
        {"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa"},
        {"leaf_num": 2, "page_num": None, "kind": "back_matter", "sha256": "sha256:bbb"},
    ]
    by_sha, gaps, body = _index(leaves)
    assert (
        vlk.classify_page(None, "sha256:bbb", by_sha=by_sha, gaps=gaps, body_leaf_nums=body)
        == vlk.FRONTBACK_UNKEYED
    )


def test_duplicate_sha_leaf_hits_the_1N_guard():
    leaves = [
        {"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:dup"},
        {"leaf_num": 11, "page_num": 2, "kind": "body", "sha256": "sha256:dup"},
    ]
    by_sha, gaps, body = _index(leaves)
    assert vlk.classify_page(10, "sha256:dup", by_sha=by_sha, gaps=gaps, body_leaf_nums=body) == vlk.MULTILEAF


def test_unknown_sha_is_unresolved():
    leaves = [{"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa"}]
    by_sha, gaps, body = _index(leaves)
    assert vlk.classify_page(7, "sha256:zzz", by_sha=by_sha, gaps=gaps, body_leaf_nums=body) == vlk.UNRESOLVED


# --- (c) cross-engine join correctness --------------------------------------

def test_cross_engine_same_leaf_same_sha_has_no_conflict():
    engine_leaf_sha = {
        "tesseract-py314-v1": {10: "aaa", 11: "bbb"},
        "kraken-py312-v1": {10: "aaa", 11: "bbb"},
    }
    assert vlk.cross_engine_conflicts(engine_leaf_sha) == []


def test_cross_engine_same_leaf_different_sha_is_a_conflict():
    engine_leaf_sha = {
        "tesseract-py314-v1": {10: "aaa"},
        "kraken-py312-v1": {10: "XXX"},
    }
    conflicts = vlk.cross_engine_conflicts(engine_leaf_sha)
    assert len(conflicts) == 1
    assert conflicts[0]["leaf_id"] == 10


# --- (d) S2 rendering dir == expected set -----------------------------------

def test_s2_set_diff_reports_missing_and_extra():
    missing, extra = vlk.set_diff(rendered={10, 11}, expected={10, 11, 12})
    assert missing == [12] and extra == []
    missing, extra = vlk.set_diff(rendered={10, 11, 99}, expected={10, 11})
    assert missing == [] and extra == [99]


# --- selftest (TEST-09) -----------------------------------------------------

def test_selftest_passes():
    assert vlk.selftest() == 0


# --- integration: read a tiny on-disk store ---------------------------------

def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# leaf_num -> (native stem, page_num, content sha)
_LEAVES = {
    10: ("page_0001", 1, "sha256:aaa"),
    11: ("page_0002", 2, "sha256:bbb"),
    12: ("page_0003", 3, "sha256:ccc"),
}


def _build_store(root: Path, *, source_leaves=(10, 11), s1_leaves=(10, 11), leaf_id_for_page1=10):
    """Source manifest (``source_leaves``) + one tesseract S1 cell (``s1_leaves``).

    ``leaf_id_for_page1`` overrides the canonical_leaf_id stamped on the leaf-10
    sidecar so a test can simulate a migration miss (None) without touching shas.
    """
    src_dir = root / "raw" / "internet-archive" / "schaff-herzog-pages"
    source = {
        "volume": 1,
        "page_count": len(source_leaves),
        "leaves": [
            {"leaf_num": lid, "page_num": _LEAVES[lid][1], "kind": "body", "sha256": _LEAVES[lid][2],
             "local_path": f"raw/internet-archive/schaff-herzog-pages/vol_01/{_LEAVES[lid][0]}.jpg"}
            for lid in source_leaves
        ],
    }
    _write_json(src_dir / "vol_01.manifest.json", source)

    cell = root / "reports" / "s1-sidecars" / "tesseract-py314-v1" / "vol_01"
    page_refs = []
    for lid in s1_leaves:
        native, _pn, sha = _LEAVES[lid]
        stamp = leaf_id_for_page1 if lid == 10 else lid
        _write_json(
            cell / "pages" / f"{native}.json",
            {"page_native_id": native, "source_payload_sha256": sha, "canonical_leaf_id": stamp},
        )
        page_refs.append({
            "page_native_id": native, "source_payload_sha256": sha,
            "canonical_leaf_id": stamp, "status": "eligible",
            "sidecar_page_path": f"reports/s1-sidecars/tesseract-py314-v1/vol_01/pages/{native}.json",
        })
    _write_json(cell / "manifest.json",
                {"volume": 1, "source_lineage_id": "tesseract-py314-v1", "pages": page_refs})
    return source


def _build_frontback_store(root: Path, *, edition_page_key):
    src_dir = root / "raw" / "internet-archive" / "schaff-herzog-pages"
    source = {
        "volume": 1,
        "page_count": 1,
        "leaves": [
            {"leaf_num": 2, "page_num": None, "kind": "front_matter", "sha256": "sha256:fff",
             "local_path": "raw/internet-archive/schaff-herzog-pages/vol_01/leaf_0002.jpg"},
            {"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa",
             "local_path": "raw/internet-archive/schaff-herzog-pages/vol_01/page_0001.jpg"},
        ],
    }
    _write_json(src_dir / "vol_01.manifest.json", source)
    cell = root / "reports" / "s1-sidecars" / "tesseract-py314-v1" / "vol_01"
    sidecar = {
        "page_native_id": "leaf_0002",
        "source_payload_sha256": "sha256:fff",
        "clid_exempt": True,
    }
    if edition_page_key is not None:
        sidecar["edition_page_key"] = edition_page_key
    _write_json(cell / "pages" / "leaf_0002.json", sidecar)
    page_ref = {
        "page_native_id": "leaf_0002",
        "source_payload_sha256": "sha256:fff",
        "status": "eligible",
        "clid_exempt": True,
        "sidecar_page_path": "reports/s1-sidecars/tesseract-py314-v1/vol_01/pages/leaf_0002.json",
    }
    if edition_page_key is not None:
        page_ref["edition_page_key"] = edition_page_key
    _write_json(cell / "manifest.json", {"volume": 1, "source_lineage_id": "tesseract-py314-v1", "pages": [page_ref]})


def _build_s2_split_cell(root: Path, *, leaf_ids=(10, 11), unstamped=()):
    """A current-shape S2 cell: index.json + pages/<id>.rendering-v1.json, each
    page a single-page rendering doc carrying source_payload_sha256 (+leaf id).
    Leaves listed in ``unstamped`` omit canonical_leaf_id."""
    cell = root / "reports" / "s2-renderings" / "vol_01" / "tesseract-py314-v1"
    page_ids = [_LEAVES[lid][0] for lid in leaf_ids]
    _write_json(cell / "index.json", {"source_lineage_id": "tesseract-py314-v1", "volume": 1, "pages": page_ids})
    for lid in leaf_ids:
        native, _pn, sha = _LEAVES[lid]
        page = {"page_native_id": native, "source_payload_sha256": sha}
        if lid not in unstamped:
            page["canonical_leaf_id"] = lid
        _write_json(cell / "pages" / f"{native}.rendering-v1.json", {"volume": 1, "pages": [page]})


def test_verify_store_passes_on_clean_cell(tmp_path):
    _build_store(tmp_path)
    _build_s2_split_cell(tmp_path)
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is True
    assert report["body_leaf_failures"] == 0


def test_s2_extra_rendering_is_flagged(tmp_path):
    # leaf 12 exists in the source + S2 but the S1 cell never OCR'd it -> stale render
    _build_store(tmp_path, source_leaves=(10, 11, 12), s1_leaves=(10, 11))
    _build_s2_split_cell(tmp_path, leaf_ids=(10, 11, 12))
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is False
    assert report["s2_failures"] >= 1


def test_s2_partial_stamp_missing_leaf_id_is_flagged(tmp_path):
    # A cell that HAS been leaf-stamped (leaf 10) but leaf 11 slipped through
    # unstamped is a genuine (a)-S2 failure, not a pending-rekey gap.
    _build_store(tmp_path)
    _build_s2_split_cell(tmp_path, unstamped={11})
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is False
    assert report["s2_failures"] >= 1


def test_s2_wholesale_unstamped_cell_is_pending_not_failure(tmp_path):
    # Split shape but NO body page stamped -> rendered before R4a leaf-stamping.
    # A bounded-re-render coverage gap, reported but NOT a verifier failure.
    _build_store(tmp_path)
    _build_s2_split_cell(tmp_path, unstamped={10, 11})
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is True
    assert report["s2_failures"] == 0
    assert "tesseract-py314-v1/vol_01" in report["s2_pending_rekey"]


def test_s1_cell_with_sidecars_but_no_manifest_is_flagged(tmp_path):
    # A cell whose pages/ holds OCR sidecars but whose manifest.json is absent is
    # un-indexed content the verifier cannot leaf-check (the staleness class).
    # It must FAIL (and be surfaced), not be silently skipped.
    _build_store(tmp_path)
    cell = tmp_path / "reports" / "s1-sidecars" / "tesseract-py314-v1" / "vol_01"
    (cell / "manifest.json").unlink()
    assert list((cell / "pages").glob("*.json"))  # sidecars still present
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is False
    assert "tesseract-py314-v1/vol_01" in report["s1_no_manifest"]


def test_empty_s1_cell_without_manifest_is_not_flagged(tmp_path):
    # The opposite case: a cell with no manifest AND no sidecars is simply
    # not-yet-OCR'd. Incomplete coverage is allowed -- it must NOT fail.
    _build_store(tmp_path)
    cell = tmp_path / "reports" / "s1-sidecars" / "surya-py312-v1" / "vol_01"
    (cell / "pages").mkdir(parents=True, exist_ok=True)
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is True
    assert report["s1_no_manifest"] == []


def test_verify_store_flags_missing_leaf_id(tmp_path):
    # page_0001 sidecar carries no leaf id (None) -> a body_missing_leaf failure
    _build_store(tmp_path, leaf_id_for_page1=None)
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is False
    assert report["body_leaf_failures"] >= 1


def test_verify_store_frontback_keyed_sidecar_is_ok(tmp_path):
    _build_frontback_store(tmp_path, edition_page_key={"section": "front_matter", "anchor": 1, "ordinal": 0})

    report = vlk.verify_store(tmp_path, volumes=[1], primary_only=True)

    assert report["ok"] is True
    assert report["frontback_ok"] == 2
    assert report["frontback_unkeyed"] == 0


def test_verify_store_frontback_unkeyed_sidecar_fails(tmp_path):
    _build_frontback_store(tmp_path, edition_page_key=None)

    report = vlk.verify_store(tmp_path, volumes=[1], primary_only=True)

    assert report["ok"] is False
    assert report["frontback_unkeyed"] >= 1


def test_cli_returns_nonzero_on_failure(tmp_path):
    _build_store(tmp_path, leaf_id_for_page1=None)
    rc = vlk.main(["--repo-root", str(tmp_path), "--volumes", "1"])
    assert rc != 0


def test_cli_returns_zero_on_clean_store(tmp_path):
    _build_store(tmp_path)
    rc = vlk.main(["--repo-root", str(tmp_path), "--volumes", "1"])
    assert rc == 0


# =========================================================================== #
# R6b -- source-aware (alternate-scan) verification
#
# Alternate lineages (ABBYY families + azure) are different physical scans, so
# their source_payload_sha256 = sha(rich GZ / azure JSON) never SHA-matches a
# primary image. canonical_leaf_id (stamped at R7 alignment time) is the join
# key; the verifier confirms its presence + structural validity, not
# sha-resolution. See .tmp_audit/R6b-design-rfinal2.md.
# =========================================================================== #

# --- (a) alternate page classification (pure) -------------------------------

def test_classify_alt_body_with_valid_leaf_is_ok():
    assert vlk.classify_alt_page(10, "page_0001", body_leaf_nums={10, 11},
                                 leafmap_classified=None) == vlk.ALT_BODY_OK


def test_classify_alt_clid_not_a_body_leaf_is_wrong():
    # stamped to a leaf that is not in the canonical body set -> mis-key
    assert vlk.classify_alt_page(99, "page_0001", body_leaf_nums={10, 11},
                                 leafmap_classified=None) == vlk.ALT_WRONG_LEAF


def test_classify_alt_null_clid_classified_nonbody_is_exempt():
    lm = {"page_0009": {"class": "non-body", "words": 7, "best_score": 0.0}}
    assert vlk.classify_alt_page(None, "page_0009", body_leaf_nums={10, 11},
                                 leafmap_classified=lm) == vlk.ALT_EXEMPT_CLASSIFIED


def test_classify_alt_null_clid_classified_body_unrecoverable_is_exempt():
    lm = {"page_0009": {"class": "body-unrecoverable", "words": 3, "best_score": 0.1}}
    assert vlk.classify_alt_page(None, "page_0009", body_leaf_nums={10, 11},
                                 leafmap_classified=lm) == vlk.ALT_EXEMPT_CLASSIFIED


def test_classify_alt_null_clid_unclassified_with_leafmap_is_failure():
    # leafmap present but this stem is not classified -> a body page that R7
    # should have mapped but did not. A failure.
    lm = {"page_0008": {"class": "non-body"}}
    assert vlk.classify_alt_page(None, "page_0009", body_leaf_nums={10, 11},
                                 leafmap_classified=lm) == vlk.ALT_MISSING_LEAF


def test_classify_alt_null_clid_no_leafmap_is_exempt_residue():
    # ia-abbyy-v1 / azure carry no leafmap; an unmapped page is offset-oracle
    # residue. The verifier does not interpolate a canonical leaf for it.
    assert vlk.classify_alt_page(None, "page_0009", body_leaf_nums={10, 11},
                                 leafmap_classified=None) == vlk.ALT_EXEMPT_NO_LEAFMAP


# --- (c) alternate cross-engine leaf-membership (pure) ----------------------

def test_alt_duplicate_clid_across_stems_is_a_conflict():
    conflicts = vlk.duplicate_clid_conflicts([("page_0001", 10), ("page_0009", 10)])
    assert len(conflicts) == 1 and conflicts[0]["clid"] == 10


def test_alt_unique_clids_have_no_conflict():
    assert vlk.duplicate_clid_conflicts([("page_0001", 10), ("page_0002", 11)]) == []


# --- (a) WCT page carries clid (pure) ---------------------------------------

def test_wct_clid_present_true_for_int_leaf():
    assert vlk.wct_clid_present({"page_id": "page_0010", "canonical_leaf_id": 37}) is True


def test_wct_clid_present_false_when_missing():
    assert vlk.wct_clid_present({"page_id": "page_0010"}) is False
    assert vlk.wct_clid_present({"page_id": "page_0010", "canonical_leaf_id": None}) is False


def test_wct_edition_key_present_true_for_well_formed_key():
    page = {"edition_page_key": {"section": "body", "anchor": 96, "ordinal": 0}}
    assert vlk.wct_edition_key_present(page) is True


def test_wct_edition_key_present_false_for_malformed_or_missing_key():
    assert vlk.wct_edition_key_present({}) is False
    assert vlk.wct_edition_key_present({"edition_page_key": {"section": "body", "anchor": "96", "ordinal": 0}}) is False
    assert vlk.wct_edition_key_present({"edition_page_key": {"section": "plate", "anchor": 96, "ordinal": 0}}) is False


def test_wct_page_key_present_accepts_clid_or_edition_key():
    assert vlk.wct_page_key_present({"canonical_leaf_id": 37}) is True
    assert vlk.wct_page_key_present({"edition_page_key": {"section": "body", "anchor": 96, "ordinal": 0}}) is True
    assert vlk.wct_page_key_present({"clid_exempt": True}) is False


# --- integration: alternate cells on disk -----------------------------------

def _build_alt_cell(root, lineage, *, refs, volume=1):
    """Write one alternate S1 cell (manifest + per-page sidecars).

    ``refs`` is a list of dicts: {stem, clid (int|None), sha (optional;
    defaults to a foreign sha never present in the primary manifest),
    sidecar_clid (optional; defaults to clid)}.
    """
    cell = root / "reports" / "s1-sidecars" / lineage / f"vol_{volume:02d}"
    page_refs = []
    for r in refs:
        stem = r["stem"]
        clid = r.get("clid")
        sha = r.get("sha", f"sha256:alt_{lineage}_{stem}")
        side_clid = r.get("sidecar_clid", clid)
        sidecar = {"page_native_id": stem, "source_payload_sha256": sha}
        if side_clid is not None:
            sidecar["canonical_leaf_id"] = side_clid
        _write_json(cell / "pages" / f"{stem}.json", sidecar)
        pr = {"page_native_id": stem, "source_payload_sha256": sha, "status": "eligible",
              "sidecar_page_path": f"reports/s1-sidecars/{lineage}/vol_{volume:02d}/pages/{stem}.json"}
        if clid is not None:
            pr["canonical_leaf_id"] = clid
        page_refs.append(pr)
    _write_json(cell / "manifest.json",
                {"volume": volume, "source_lineage_id": lineage, "pages": page_refs})


def _write_leafmap(root, lineage, classified, *, volume=1):
    lm = (root / "raw" / "internet-archive" / "schaff-herzog-pages"
          / f"vol_{volume:02d}.{lineage}.leafmap.json")
    _write_json(lm, {"lineage": lineage, "volume": volume, "unmapped_classified": classified})


def test_alt_clean_cell_passes_and_skips_reuse_check(tmp_path):
    # Alternate cell with foreign shas (never in the primary manifest). The (b)
    # reuse/no-re-OCR check must be SKIPPED for alternates -- foreign shas are
    # by-design, not a re-OCR signature.
    _build_store(tmp_path)  # primary source manifest: body leaves 10, 11
    _build_alt_cell(tmp_path, "ia-abbyy-v1",
                    refs=[{"stem": "page_0001", "clid": 10}, {"stem": "page_0002", "clid": 11}])
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is True
    assert report["reuse_failures"] == 0  # (b) skipped for alternates


def test_alt_null_clid_classified_exempt_passes(tmp_path):
    _build_store(tmp_path)
    _build_alt_cell(tmp_path, "ia-abbyy-haucgoog-v1",
                    refs=[{"stem": "page_0001", "clid": 10}, {"stem": "page_0009", "clid": None}])
    _write_leafmap(tmp_path, "ia-abbyy-haucgoog-v1",
                   {"page_0009": {"class": "non-body", "words": 5, "best_score": 0.0}})
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is True


def test_alt_null_clid_unclassified_with_leafmap_fails(tmp_path):
    _build_store(tmp_path)
    _build_alt_cell(tmp_path, "ia-abbyy-haucgoog-v1",
                    refs=[{"stem": "page_0001", "clid": 10}, {"stem": "page_0009", "clid": None}])
    # leafmap exists but does NOT classify page_0009 -> a body page R7 missed.
    _write_leafmap(tmp_path, "ia-abbyy-haucgoog-v1",
                   {"page_0007": {"class": "non-body"}})
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is False
    assert report["alt_body_leaf_failures"] >= 1


def test_alt_null_clid_no_leafmap_is_exempt(tmp_path):
    _build_store(tmp_path)
    _build_alt_cell(tmp_path, "ia-abbyy-v1",
                    refs=[{"stem": "page_0001", "clid": 10}, {"stem": "page_0009", "clid": None}])
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is True


def test_alt_wholly_unstamped_cell_fails(tmp_path):
    # A 0%-stamped alternate cell means R7 never ran -> failure (not a soft gap),
    # even with no leafmap (the exempt-no-leafmap path must NOT mask this).
    _build_store(tmp_path)
    _build_alt_cell(tmp_path, "ia-abbyy-v1",
                    refs=[{"stem": "page_0001", "clid": None}, {"stem": "page_0002", "clid": None}])
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is False
    assert "ia-abbyy-v1/vol_01" in report["alt_unstamped_cells"]


def test_alt_within_cell_duplicate_clid_is_reported_not_failed(tmp_path):
    # The R7 content aligner legitimately maps two alternate stems to one canonical
    # leaf (a secondary scan re-shooting a page run). Both pages carry the key, so
    # it is a REPORTED diagnostic, never a keying failure (verified 2026-06-16).
    _build_store(tmp_path)
    _build_alt_cell(tmp_path, "ia-abbyy-haucgoog-v1",
                    refs=[{"stem": "page_0001", "clid": 10}, {"stem": "page_0002", "clid": 10}])
    _write_leafmap(tmp_path, "ia-abbyy-haucgoog-v1", {})
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is True
    assert report["alt_duplicate_clid_stamps"] >= 1


def test_alt_clid_not_in_body_set_fails(tmp_path):
    _build_store(tmp_path)
    _build_alt_cell(tmp_path, "ia-abbyy-v1",
                    refs=[{"stem": "page_0001", "clid": 10}, {"stem": "page_0002", "clid": 99}])
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is False
    assert report["alt_body_leaf_failures"] >= 1


def test_alt_sidecar_disagrees_with_manifest_fails(tmp_path):
    _build_store(tmp_path)
    _build_alt_cell(tmp_path, "ia-abbyy-v1",
                    refs=[{"stem": "page_0001", "clid": 10, "sidecar_clid": 11}])
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is False
    assert report["alt_body_leaf_failures"] >= 1


# --- WCT integration --------------------------------------------------------

def _write_wct_page(root, volume, stem, *, clid, sha):
    page = {"work_id": "schaff-herzog-encyclopedia", "volume_id": f"vol_{volume:02d}",
            "page_id": stem, "positions": [], "reading_order": [],
            "source_image": {"path": f"raw/x/{stem}.jpg", "sha256": sha}}
    if clid is not None:
        page["canonical_leaf_id"] = clid
    _write_json(root / "reports" / "wct" / f"vol_{volume:02d}" / f"{stem}.json", page)


def _write_wct_page_with_edition_key(root, volume, stem, *, clid, edition_page_key, sha):
    page = {"work_id": "schaff-herzog-encyclopedia", "volume_id": f"vol_{volume:02d}",
            "page_id": stem, "positions": [], "reading_order": [],
            "source_image": {"path": f"raw/x/{stem}.jpg", "sha256": sha}}
    if clid is not None:
        page["canonical_leaf_id"] = clid
    if edition_page_key is not None:
        page["edition_page_key"] = edition_page_key
    if clid is None:
        page["clid_exempt"] = True
    _write_json(root / "reports" / "wct" / f"vol_{volume:02d}" / f"{stem}.json", page)


def test_wct_body_pages_carry_correct_clid_passes(tmp_path):
    # The WCT clid is verified against the leaf its source image resolves to
    # (not merely present): a body page must carry the resolved leaf.
    _build_store(tmp_path)  # leaves 10 (sha aaa), 11 (sha bbb)
    _write_wct_page(tmp_path, 1, "page_0001", clid=10, sha="sha256:aaa")
    _write_wct_page(tmp_path, 1, "page_0002", clid=11, sha="sha256:bbb")
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is True
    assert report["wct_pages"] == 2
    assert report["wct_missing_clid"] == 0


def test_wct_body_page_wrong_clid_fails(tmp_path):
    # clid present but not the leaf the source image resolves to -> mis-key.
    _build_store(tmp_path)
    _write_wct_page(tmp_path, 1, "page_0001", clid=99, sha="sha256:aaa")
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is False
    assert report["wct_missing_clid"] >= 1


def test_wct_wholesale_unkeyed_volume_is_pending_not_failure(tmp_path):
    # A WCT that predates R4b (or awaits the full rebuild incl. alternate ABBYY +
    # the remaining volumes) carries 0 clid across the whole volume -> PENDING, not
    # a failure (mirrors the legacy-monolithic S2 softening). The word-confusion-
    # table-v1 flip is gated on this pending state separately.
    _build_store(tmp_path)
    _write_wct_page(tmp_path, 1, "page_0001", clid=None, sha="sha256:aaa")
    _write_wct_page(tmp_path, 1, "page_0002", clid=None, sha="sha256:bbb")
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is True
    assert report["wct_missing_clid"] == 0
    assert report["wct_pending_volumes"] == 1


def test_wct_partially_keyed_with_missing_body_clid_fails(tmp_path):
    # Once a volume has ANY clid (a real/partial keying), a body page still missing
    # it is a genuine failure -- NOT softened to pending.
    _build_store(tmp_path)
    _write_wct_page(tmp_path, 1, "page_0001", clid=10, sha="sha256:aaa")
    _write_wct_page(tmp_path, 1, "page_0002", clid=None, sha="sha256:bbb")
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is False
    assert report["wct_missing_clid"] >= 1


def test_wct_recovered_gap_page_without_clid_is_exempt(tmp_path):
    # A WCT page whose source image is a recovered-gap page (in the manifest's
    # gaps[], no spine leaf) legitimately carries no clid -- exempt, not a failure.
    # (Real case: vol_01/page_0096, 1646 positions, all engines clid=None.)
    src_dir = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    source = {
        "volume": 1, "page_count": 1,
        "leaves": [{"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa",
                    "local_path": "raw/internet-archive/schaff-herzog-pages/vol_01/page_0001.jpg"}],
        "gaps": [{"page_num": 96, "sha256": "sha256:gap96", "local_path": "vol_01/page_0096.jpg"}],
    }
    _write_json(src_dir / "vol_01.manifest.json", source)
    _write_wct_page(tmp_path, 1, "page_0001", clid=10, sha="sha256:aaa")
    _write_wct_page(tmp_path, 1, "page_0096", clid=None, sha="sha256:gap96")
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is True
    assert report["wct_missing_clid"] == 0
    assert report["wct_exempt"] >= 1


def test_wct_recovered_gap_page_with_edition_key_is_keyed(tmp_path):
    src_dir = tmp_path / "raw" / "internet-archive" / "schaff-herzog-pages"
    source = {
        "volume": 1, "page_count": 1,
        "leaves": [{"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa",
                    "local_path": "raw/internet-archive/schaff-herzog-pages/vol_01/page_0001.jpg"}],
        "gaps": [{"page_num": 96, "sha256": "sha256:gap96", "local_path": "vol_01/page_0096.jpg"}],
    }
    _write_json(src_dir / "vol_01.manifest.json", source)
    _write_wct_page_with_edition_key(
        tmp_path,
        1,
        "page_0096",
        clid=None,
        edition_page_key={"section": "body", "anchor": 96, "ordinal": 0},
        sha="sha256:gap96",
    )
    report = vlk.verify_store(tmp_path, volumes=[1])
    assert report["ok"] is True
    assert report["wct_body_ok"] == 1
    assert report["wct_exempt"] == 0
