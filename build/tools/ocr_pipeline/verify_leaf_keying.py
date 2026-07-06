"""R6b full-chain leaf-keying verifier (TEST-08; extends R6a primary chain).

Disk-reading enforcement deliverable for the NSH leaf-rekey. Like
``ocr_inventory.py`` and ``verify_nsh_page_accounting.py`` it treats the
gitignored OCR stores under ``reports/`` as the single source of truth (VER-01):
git gives a false all-clear because the stores are untracked.

R6a verified the PRIMARY engines (tesseract / kraken / surya / kraken-greek) by
sha-resolution against the canonical manifest. R6b (this module, default scope)
adds the ALTERNATE scans (the ABBYY families + azure) with source-aware rules
(``classify_alt_page`` / ``_verify_alt_s1_cell``) and the WCT (``_verify_wct``);
``--primary-only`` restores the R6a subset. See ``.tmp_audit/R6b-design-rfinal2.md``.

It asserts, per (engine, volume) cell, for PRIMARY engines:

  (a) every S1 sidecar + S1 manifest page + current-shape S2 rendering for a
      *body* leaf carries an int ``canonical_leaf_id`` equal to the leaf its
      content sha resolves to in the CURRENT canonical manifest (C5);
  (b) reuse held / no re-OCR -- no sidecar carries a ``source_payload_sha256``
      absent from the current canonical manifest (an unresolvable content sha is
      the re-OCR signature: pixels changed, the manifest never knew them);
  (c) cross-engine joins are leaf-keyed -- two primary engines that both OCR'd
      one leaf carry the SAME content sha under that ``canonical_leaf_id``
      (a disagreement means one engine is joined to the wrong physical page).
      NOTE: on the current single-source model this is subsumed by (a)/(b)
      (primaries all SHA-match the same source images, so they cannot disagree
      at a resolved leaf; a real mis-stamp shows up as (a) BODY_WRONG_LEAF). It
      is retained as a guard for the post-R7 multi-source (alternate-scan) model;
  (d) each current-shape S2 rendering dir is a subset of the leaves its S1 cell
      OCR'd -- a rendered leaf NOT in the current S1 set is a stale render.

Scoping decisions (autonomous R6a, recorded so a cold reader can audit them):
  * Recovered-gap pages (``gaps[]``, no spine leaf), non-body preserved
    sidecars (front/back/plate), and 1:N duplicate-sha leaves are EXEMPT from
    (a): they legitimately carry no single ``canonical_leaf_id``. Each is
    reported in its own bucket, never as a failure.
  * S2 is re-rendered VOLUME-BY-VOLUME (design SS4.3, disk-bounded). A primary
    S2 cell that is still in the legacy monolithic ``rendering-v1.json`` shape
    (no ``index.json``) is reported as ``s2_not_rerendered`` -- a coverage gap
    pending R4a's bounded re-render, NOT a verifier failure.
  * (d) hard-fails only on EXTRA renders (stale leaves). MISSING renders (S2
    lagging S1) are reported as ``s2_lag`` -- expected mid-re-render.

Usage:
  py -3 build/tools/ocr_pipeline/verify_leaf_keying.py                 # full primary verify
  py -3 build/tools/ocr_pipeline/verify_leaf_keying.py --volumes 1-5
  py -3 build/tools/ocr_pipeline/verify_leaf_keying.py --gate          # fast scoped pre-commit gate
  py -3 build/tools/ocr_pipeline/verify_leaf_keying.py --selftest      # TP + TN self-check
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.nsh_leaf_model import (  # noqa: E402
    gap_by_sha,
    leaf_by_sha,
    ocr_input,
)
from build.lib.ocr_store_paths import s1_sidecars_root, s2_renderings_root  # noqa: E402

# --- config (PY-03) ---------------------------------------------------------
PRIMARY_LINEAGES = (
    "tesseract-py314-v1",
    "kraken-py312-v1",
    "surya-py312-v1",
    "kraken-greek-py312-v1",
)
# Alternate-scan lineages (R6b). These are DIFFERENT physical scans of the same
# edition: their source_payload_sha256 = sha(rich GZ / azure JSON) never
# SHA-matches a primary image, so canonical_leaf_id (stamped at R7 alignment
# time) is the join key -- not sha-resolution. The 6 secondary ABBYY lineages
# carry a content leafmap (vol_NN.<lineage>.leafmap.json) whose
# unmapped_classified buckets the pages R7 could not map; ia-abbyy-v1 and azure
# are stamped by the PIPE-29 offset oracle and carry NO leafmap.
ALTERNATE_LINEAGES = (
    "ia-abbyy-v1",
    "ia-abbyy-dli-v1",
    "ia-abbyy-haucgoog-v1",
    "ia-abbyy-haucgoog-c1-v1",
    "ia-abbyy-haucgoog-c2-v1",
    "ia-abbyy-haucgoog-c3-v1",
    "ia-abbyy-haucgoog-c4-v1",
    "azure-ai-vision-v1",
)
NSH_PAGES_BASE = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"

# Classification buckets for one per-page artifact.
BODY_OK = "body_ok"
BODY_MISSING_LEAF = "body_missing_leaf"   # (a) failure: body leaf, no canonical_leaf_id
BODY_WRONG_LEAF = "body_wrong_leaf"       # (a) failure: stamped leaf != resolved leaf
GAP = "gap"                               # exempt: recovered-gap page, no spine leaf
NONBODY = "nonbody"                       # exempt: front/back/plate preserved sidecar
FRONTBACK_OK = "frontback_ok"             # keyed front/back sidecar
FRONTBACK_UNKEYED = "frontback_unkeyed"   # failure: front/back sidecar without section key
MULTILEAF = "multileaf"                   # exempt: 1:N duplicate-sha (resolve_leaf would raise)
UNRESOLVED = "unresolved"                 # (b) failure: sha absent from current manifest

_A_FAILURES = frozenset({BODY_MISSING_LEAF, BODY_WRONG_LEAF, FRONTBACK_UNKEYED})
_B_FAILURES = frozenset({UNRESOLVED})

# R6b alternate-scan buckets for one per-page artifact.
ALT_BODY_OK = "alt_body_ok"
ALT_MISSING_LEAF = "alt_missing_leaf"      # null clid, leafmap present but stem unclassified (failure)
ALT_WRONG_LEAF = "alt_wrong_leaf"          # int clid that is not a canonical body leaf (failure)
ALT_EXEMPT_CLASSIFIED = "alt_exempt_classified"   # null clid, leafmap classes it non-body/body-unrecoverable
ALT_EXEMPT_NO_LEAFMAP = "alt_exempt_no_leafmap"   # null clid, lineage carries no leafmap (offset-oracle residue)

_ALT_A_FAILURES = frozenset({ALT_MISSING_LEAF, ALT_WRONG_LEAF})
_LEAFMAP_EXEMPT_CLASSES = frozenset({"non-body", "body-unrecoverable"})

# Files matching these path prefixes, when staged, mean a code change to the
# leaf-keying chain -- the pre-commit gate then runs the verifier selftest.
_GATE_CODE_PREFIXES = (
    "build/parsers/s1_",
    "build/tools/ocr_pipeline/",
    "build/lib/nsh_leaf_model.py",
)
_GATE_MANIFEST_RE = re.compile(
    r"^raw/internet-archive/schaff-herzog-pages/vol_(\d{2})"
    r"(?:\.manifest\.json|/page_order\.json)$"
)


def normalize_sha(value: Any) -> str | None:
    """Drop a leading ``sha256:`` prefix so prefixed and bare digests compare."""
    if not isinstance(value, str):
        return None
    return value.split(":", 1)[1] if ":" in value else value


def build_indices(manifest: dict) -> tuple[dict[str, list[dict]], set[str], set[int]]:
    """``(by_sha, gap_shas, body_leaf_nums)`` for one canonical manifest.

    Derives through the shared accessor (C4) so the verifier never re-implements
    leaf resolution. ``by_sha`` keys are normalized (prefix-stripped).
    """
    by_sha = {normalize_sha(sha): leaves for sha, leaves in leaf_by_sha(manifest).items()}
    by_sha.pop(None, None)
    gap_shas = {normalize_sha(sha) for sha in gap_by_sha(manifest)}
    gap_shas.discard(None)
    body_leaf_nums = {
        leaf["leaf_num"]
        for leaf in ocr_input(manifest)
        if isinstance(leaf.get("leaf_num"), int)
    }
    return by_sha, gap_shas, body_leaf_nums


def classify_page(
    canonical_leaf_id: Any,
    source_payload_sha256: Any,
    *,
    by_sha: dict[str, list[dict]],
    gaps: set[str],
    body_leaf_nums: set[int],
    edition_page_key: Any = None,
) -> str:
    """Bucket one per-page artifact by its content sha + stamped leaf id."""
    sha = normalize_sha(source_payload_sha256)
    leaves = by_sha.get(sha)
    if leaves is None:
        return GAP if sha in gaps else UNRESOLVED
    if len(leaves) > 1:
        return MULTILEAF
    leaf_num = leaves[0].get("leaf_num")
    if leaf_num not in body_leaf_nums:
        if leaves[0].get("kind") in {"front_matter", "back_matter"}:
            return FRONTBACK_OK if frontback_edition_key_present(edition_page_key) else FRONTBACK_UNKEYED
        return NONBODY
    if not isinstance(canonical_leaf_id, int):
        return BODY_MISSING_LEAF
    if canonical_leaf_id != leaf_num:
        return BODY_WRONG_LEAF
    return BODY_OK


def classify_alt_page(
    canonical_leaf_id: Any,
    page_native_id: str,
    *,
    body_leaf_nums: set[int],
    leafmap_classified: dict[str, dict] | None,
) -> str:
    """Bucket one ALTERNATE-scan per-page artifact (R6b).

    Alternate pages cannot be sha-resolved against the primary manifest, so the
    stamped ``canonical_leaf_id`` IS the join key (content-verified at R7
    alignment time). A page with an int clid must hit a canonical *body* leaf; a
    page with no clid is a failure only when a leafmap exists and does NOT
    classify the stem exempt. ia-abbyy-v1 / azure carry no leafmap -- an unmapped
    page there is offset-oracle residue (the verifier never invents a canonical
    leaf for it; mass un-keying is caught by the cell-unstamped guard instead).
    """
    if isinstance(canonical_leaf_id, int):
        return ALT_BODY_OK if canonical_leaf_id in body_leaf_nums else ALT_WRONG_LEAF
    if leafmap_classified is None:
        return ALT_EXEMPT_NO_LEAFMAP
    cls = (leafmap_classified.get(page_native_id) or {}).get("class")
    return ALT_EXEMPT_CLASSIFIED if cls in _LEAFMAP_EXEMPT_CLASSES else ALT_MISSING_LEAF


def duplicate_clid_conflicts(stem_clid_pairs: list[tuple[str, Any]]) -> list[dict]:
    """(c) for alternates: a clid stamped onto two different physical stems is a
    mis-key (the leaf-membership analogue of a cross-engine sha conflict)."""
    by_clid: dict[int, set[str]] = {}
    for stem, clid in stem_clid_pairs:
        if isinstance(clid, int):
            by_clid.setdefault(clid, set()).add(stem)
    return [
        {"clid": clid, "stems": sorted(stems)}
        for clid, stems in sorted(by_clid.items())
        if len(stems) > 1
    ]


def wct_clid_present(wct_page: dict[str, Any]) -> bool:
    """A WCT page must carry an int ``canonical_leaf_id`` (R4b join key)."""
    return isinstance(wct_page.get("canonical_leaf_id"), int)


def wct_edition_key_present(wct_page: dict[str, Any]) -> bool:
    """A WCT page carries a well-formed scan-independent edition page key."""
    key = wct_page.get("edition_page_key")
    if not isinstance(key, dict):
        return False
    return (
        key.get("section") in {"front_matter", "body", "back_matter"}
        and type(key.get("anchor")) is int
        and type(key.get("ordinal")) is int
        and key["ordinal"] >= 0
    )


def frontback_edition_key_present(key: Any) -> bool:
    """Return True for a well-formed front/back edition page key."""
    if not isinstance(key, dict):
        return False
    return (
        key.get("section") in {"front_matter", "back_matter"}
        and type(key.get("anchor")) is int
        and type(key.get("ordinal")) is int
        and key["ordinal"] >= 0
    )


def wct_page_key_present(wct_page: dict[str, Any]) -> bool:
    """A WCT page is keyed when it has either the copy leaf or edition key."""
    return wct_clid_present(wct_page) or wct_edition_key_present(wct_page)


def resolved_leaf_num(source_payload_sha256: Any, by_sha: dict[str, list[dict]]) -> int | None:
    """The single body/leaf this sha resolves to, or None (unknown / 1:N)."""
    leaves = by_sha.get(normalize_sha(source_payload_sha256))
    if not leaves or len(leaves) != 1:
        return None
    leaf_num = leaves[0].get("leaf_num")
    return leaf_num if isinstance(leaf_num, int) else None


def cross_engine_conflicts(engine_leaf_sha: dict[str, dict[int, str]]) -> list[dict]:
    """Leaf ids where two engines carry different content shas (broken join)."""
    by_leaf: dict[int, dict[str, str | None]] = {}
    for engine, leaf_sha in engine_leaf_sha.items():
        for leaf_id, sha in leaf_sha.items():
            by_leaf.setdefault(leaf_id, {})[engine] = normalize_sha(sha)
    conflicts = []
    for leaf_id, eng_sha in sorted(by_leaf.items()):
        if len({sha for sha in eng_sha.values() if sha is not None}) > 1:
            conflicts.append({"leaf_id": leaf_id, "shas": eng_sha})
    return conflicts


def set_diff(rendered: set[int], expected: set[int]) -> tuple[list[int], list[int]]:
    """``(missing, extra)`` -- expected-not-rendered, rendered-not-expected."""
    return sorted(expected - rendered), sorted(rendered - expected)


# --- disk readers -----------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_source_manifest(repo_root: Path, volume: int) -> dict[str, Any]:
    return _load_json(repo_root / "raw" / "internet-archive" / "schaff-herzog-pages"
                      / f"vol_{volume:02d}.manifest.json")


def _verify_s1_cell(
    repo_root: Path,
    cell_dir: Path,
    by_sha: dict[str, list[dict]],
    gaps: set[str],
    body_leaf_nums: set[int],
) -> dict[str, Any]:
    """Classify every manifest page + its sidecar for one S1 cell."""
    manifest = _load_json(cell_dir / "manifest.json")
    counts: dict[str, int] = {}
    a_failures: list[str] = []
    b_failures: list[str] = []
    leaf_sha: dict[int, str] = {}  # resolved body leaf -> content sha (for cross-engine)

    for page_ref in manifest.get("pages", []):
        native = page_ref.get("page_native_id")
        sha = page_ref.get("source_payload_sha256")
        cli = page_ref.get("canonical_leaf_id")
        bucket = classify_page(
            cli,
            sha,
            by_sha=by_sha,
            gaps=gaps,
            body_leaf_nums=body_leaf_nums,
            edition_page_key=page_ref.get("edition_page_key"),
        )
        counts[bucket] = counts.get(bucket, 0) + 1

        leaf_num = resolved_leaf_num(sha, by_sha)
        if leaf_num is not None and leaf_num in body_leaf_nums:
            # leaf_sha is keyed by the manifest-RESOLVED leaf, and the source
            # manifest maps each body leaf to exactly one content sha. Two PRIMARY
            # engines are all SHA-matched to those same source images, so they can
            # never carry different shas at one resolved leaf -- check (c) is thus
            # subsumed by (a)/(b) on the current single-source model (a real
            # mis-stamp surfaces as BODY_WRONG_LEAF in (a)). (c) is retained as a
            # guard for the post-R7 multi-source model, where an alternate-scan
            # lineage's distinct sha can legitimately resolve to the same leaf.
            # Audit 2026-06-15.
            leaf_sha[leaf_num] = normalize_sha(sha)

        if bucket in _A_FAILURES:
            a_failures.append(f"{native} (cli={cli}, resolves to {leaf_num})")
        elif bucket in _B_FAILURES:
            b_failures.append(f"{native} (sha {str(sha)[:22]}... not in manifest)")

        # (a) also holds for the sidecar payload itself, not only the manifest ref.
        sidecar_rel = page_ref.get("sidecar_page_path")
        if bucket in {BODY_OK, FRONTBACK_OK, FRONTBACK_UNKEYED} and isinstance(sidecar_rel, str):
            sidecar_path = repo_root / sidecar_rel
            if sidecar_path.exists():
                sidecar = _load_json(sidecar_path)
                sidecar_bucket = classify_page(
                    sidecar.get("canonical_leaf_id"),
                    sidecar.get("source_payload_sha256"),
                    by_sha=by_sha,
                    gaps=gaps,
                    body_leaf_nums=body_leaf_nums,
                    edition_page_key=sidecar.get("edition_page_key"),
                )
                counts[sidecar_bucket] = counts.get(sidecar_bucket, 0) + 1
                if sidecar_bucket in {BODY_MISSING_LEAF, BODY_WRONG_LEAF}:
                    side_leaf = resolved_leaf_num(sidecar.get("source_payload_sha256"), by_sha)
                    a_failures.append(f"{native} sidecar cli={sidecar.get('canonical_leaf_id')} != {side_leaf}")
                elif sidecar_bucket == FRONTBACK_UNKEYED:
                    a_failures.append(f"{native} sidecar missing front/back edition_page_key")

    return {
        "counts": counts,
        "a_failures": a_failures,
        "b_failures": b_failures,
        "leaf_sha": leaf_sha,
        "body_leaves": set(leaf_sha),
    }


def _verify_s2_cell(
    cell_dir: Path,
    by_sha: dict[str, list[dict]],
    body_leaf_nums: set[int],
) -> dict[str, Any]:
    """Inspect one current-shape (index.json) S2 cell.

    Each page file is a single-page rendering doc carrying ``source_payload_sha256``;
    a body page is resolved by that sha (recovered-gap / non-body / 1:N pages are
    EXEMPT -- they legitimately carry no ``canonical_leaf_id``).

    Returns the rendered body-leaf set, the per-page (a)-S2 misses, and the
    body-page / leaf-stamped counts the caller uses to tell a *pending-rekey*
    cell (rendered in the split shape but before R4a leaf-stamping -- a bounded
    re-render coverage gap, design SS4.3) from a genuinely broken one.
    """
    rendered: set[int] = set()
    a_failures: list[str] = []
    n_body = 0
    n_stamped = 0
    for page_path in sorted((cell_dir / "pages").glob("*.rendering-v1.json")):
        doc = _load_json(page_path)
        pages = doc.get("pages") or []
        if not pages:
            continue
        page = pages[0]
        native = page.get("page_native_id")
        cli = page.get("canonical_leaf_id")
        leaf = resolved_leaf_num(page.get("source_payload_sha256"), by_sha)
        if leaf is None or leaf not in body_leaf_nums:
            continue  # gap / non-body / 1:N / unknown -> exempt
        n_body += 1
        if not isinstance(cli, int):
            a_failures.append(f"{native}: body leaf {leaf} missing canonical_leaf_id")
            continue
        n_stamped += 1
        if cli == leaf:
            rendered.add(leaf)
        else:
            a_failures.append(f"{native}: wrong leaf (cli={cli} != {leaf})")
    return {"rendered": rendered, "a_failures": a_failures, "n_body": n_body, "n_stamped": n_stamped}


def _load_leafmap_classified(
    repo_root: Path, lineage: str, volume: int
) -> dict[str, dict] | None:
    """``unmapped_classified`` for one alternate cell, or None if no leafmap.

    None means the lineage carries no content leafmap (ia-abbyy-v1 / azure,
    stamped by the offset oracle); an empty dict means a leafmap exists but
    classified nothing unmapped."""
    lm = (repo_root / "raw" / "internet-archive" / "schaff-herzog-pages"
          / f"vol_{volume:02d}.{lineage}.leafmap.json")
    if not lm.exists():
        return None
    return _load_json(lm).get("unmapped_classified", {})


def _verify_alt_s1_cell(
    repo_root: Path,
    cell_dir: Path,
    lineage: str,
    volume: int,
    body_leaf_nums: set[int],
) -> dict[str, Any]:
    """Classify every eligible page_ref + sidecar for one ALTERNATE S1 cell."""
    manifest = _load_json(cell_dir / "manifest.json")
    leafmap_classified = _load_leafmap_classified(repo_root, lineage, volume)
    counts: dict[str, int] = {}
    a_failures: list[str] = []
    stem_clid_pairs: list[tuple[str, Any]] = []
    n_eligible = 0
    n_clid = 0

    for ref in manifest.get("pages", []):
        if ref.get("status") not in {"eligible", "diagnostic_only"}:
            continue
        n_eligible += 1
        native = ref.get("page_native_id")
        clid = ref.get("canonical_leaf_id")
        stem_clid_pairs.append((native, clid))
        if isinstance(clid, int):
            n_clid += 1
        bucket = classify_alt_page(
            clid, native, body_leaf_nums=body_leaf_nums,
            leafmap_classified=leafmap_classified,
        )
        counts[bucket] = counts.get(bucket, 0) + 1
        if bucket in _ALT_A_FAILURES:
            a_failures.append(f"{native} (clid={clid}, bucket={bucket})")
            continue
        # (a) also holds for the sidecar payload: a body ref's sidecar must carry
        # the same clid as the manifest ref.
        if bucket == ALT_BODY_OK:
            sidecar_rel = ref.get("sidecar_page_path")
            if isinstance(sidecar_rel, str):
                sidecar_path = repo_root / sidecar_rel
                if sidecar_path.exists():
                    side_clid = _load_json(sidecar_path).get("canonical_leaf_id")
                    if side_clid != clid:
                        counts[ALT_WRONG_LEAF] = counts.get(ALT_WRONG_LEAF, 0) + 1
                        a_failures.append(f"{native} sidecar clid={side_clid} != manifest {clid}")

    # Cell-unstamped guard: an alternate cell with eligible refs but ZERO int
    # clid means R7 never ran on it (BLOCKED doc: a 0%-stamped cell is a failure,
    # never softened to a coverage gap -- otherwise the flip would reject it).
    cell_unstamped = n_eligible > 0 and n_clid == 0
    conflicts = duplicate_clid_conflicts(stem_clid_pairs)
    return {
        "counts": counts,
        "a_failures": a_failures,
        "cell_unstamped": cell_unstamped,
        "clid_conflicts": conflicts,
        "stamped_leaves": {c for _, c in stem_clid_pairs if isinstance(c, int)},
    }


def _verify_alt_s2_cell(cell_dir: Path, stamped_leaves: set[int]) -> dict[str, Any]:
    """(d) for an alternate current-shape S2 cell: every rendered body page reads
    its ``canonical_leaf_id`` directly (alt shas don't resolve via primary by_sha);
    the rendered clid set must be a subset of the cell's stamped S1 clids. An
    extra rendered leaf (not in S1) is a stale render."""
    rendered: set[int] = set()
    for page_path in sorted((cell_dir / "pages").glob("*.rendering-v1.json")):
        doc = _load_json(page_path)
        pages = doc.get("pages") or []
        if not pages:
            continue
        cli = pages[0].get("canonical_leaf_id")
        if isinstance(cli, int):
            rendered.add(cli)
    extra = sorted(rendered - stamped_leaves)
    return {"rendered": rendered, "extra": extra}


def _verify_wct(repo_root: Path, volumes: list[int]) -> dict[str, Any]:
    """Verify every WCT page (reports/wct/vol_NN/page_*.json) is leaf-keyed.

    Manifest-aware (mirrors R6a ``classify_page``): a WCT page is classified by the
    leaf its ``source_image`` sha resolves to in the canonical manifest. A *body*
    page must carry that exact leaf as ``canonical_leaf_id`` (present AND correct).
    A page whose source is a recovered ``gaps[]`` page, non-body, or 1:N is EXEMPT
    -- it legitimately carries no single clid (real case: vol_01/page_0096, a
    recovered-gap page with 1646 positions and every engine clid=None)."""
    wct_root = repo_root / "reports" / "wct"
    total = 0
    body_ok = 0
    exempt = 0
    failures: list[str] = []
    pending: list[str] = []
    for volume in sorted(volumes):
        vol_dir = wct_root / f"vol_{volume:02d}"
        if not vol_dir.is_dir():
            continue
        try:
            by_sha, gaps, body_leaf_nums = build_indices(_load_source_manifest(repo_root, volume))
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            by_sha = None  # no manifest -> presence-only fallback
        docs = [(p, _load_json(p)) for p in sorted(vol_dir.glob("page_*.json"))]
        total += len(docs)
        n_with_key = sum(1 for _, d in docs if wct_page_key_present(d))
        # Wholesale-unkeyed volume: a WCT that predates R4b (or awaits the full
        # rebuild incl. alternate ABBYY + the remaining volumes) carries 0 page keys.
        # Like a legacy-monolithic S2 cell, that is a PENDING coverage gap, not a
        # failure -- the word-confusion-table-v1 flip is gated on it separately.
        # A PARTIALLY-keyed volume with body pages still missing/wrong IS a failure
        # (real corruption, e.g. a half-finished stamp).
        if n_with_key == 0 and docs:
            pending.append(f"vol_{volume:02d} ({len(docs)} pages, 0 page keys)")
            continue
        for page_path, doc in docs:
            clid = doc.get("canonical_leaf_id")
            label = f"vol_{volume:02d}/{page_path.stem}"
            if by_sha is None:
                if wct_page_key_present(doc):
                    body_ok += 1
                else:
                    failures.append(f"{label}: missing page key (no manifest to classify)")
                continue
            sha = (doc.get("source_image") or {}).get("sha256")
            bucket = classify_page(
                clid,
                sha,
                by_sha=by_sha,
                gaps=gaps,
                body_leaf_nums=body_leaf_nums,
                edition_page_key=doc.get("edition_page_key"),
            )
            if bucket == BODY_OK:
                body_ok += 1
            elif bucket in _A_FAILURES:
                failures.append(f"{label}: {bucket}")
            elif wct_page_key_present(doc):
                body_ok += 1
            else:
                exempt += 1  # gap / non-body / 1:N / unresolved-source -> no clid required
    return {"wct_pages": total, "wct_body_ok": body_ok, "wct_exempt": exempt,
            "wct_failures": failures, "wct_pending": pending}


def verify_store(
    repo_root: Path | str = REPO_ROOT,
    *,
    primary_only: bool = False,
    volumes: list[int] | None = None,
) -> dict[str, Any]:
    """Read the S1 + S2 stores and verify the primary leaf-keying invariants."""
    repo_root = Path(repo_root)
    selected = volumes if volumes is not None else list(range(1, 14))
    s1_root = s1_sidecars_root(repo_root)
    s2_root = s2_renderings_root(repo_root)

    cells: list[dict[str, Any]] = []
    cross_engine: list[dict[str, Any]] = []
    s2_not_rerendered: list[str] = []
    s2_pending_rekey: list[str] = []
    s2_lag: list[str] = []
    s1_no_manifest: list[str] = []
    alt_unstamped_cells: list[str] = []
    alt_duplicate_clid: list[dict[str, Any]] = []
    totals = {
        "body_leaf_failures": 0,
        "reuse_failures": 0,
        "cross_engine_failures": 0,
        "s2_failures": 0,
        "gap_pages": 0,
        "nonbody_pages": 0,
        "frontback_ok": 0,
        "frontback_unkeyed": 0,
        "multileaf_pages": 0,
        "body_ok": 0,
        # R6b alternate-scan + WCT tallies.
        "alt_body_leaf_failures": 0,
        "alt_duplicate_clid_stamps": 0,
        "alt_s2_failures": 0,
        "alt_body_ok": 0,
        "alt_exempt_classified": 0,
        "alt_exempt_no_leafmap": 0,
        "wct_pages": 0,
        "wct_body_ok": 0,
        "wct_exempt": 0,
        "wct_missing_clid": 0,
        "wct_pending_volumes": 0,
    }
    errors: list[str] = []

    for volume in sorted(selected):
        try:
            source = _load_source_manifest(repo_root, volume)
        except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"vol_{volume:02d}: {exc}")
            continue
        by_sha, gaps, body_leaf_nums = build_indices(source)
        engine_leaf_sha: dict[str, dict[int, str]] = {}

        for lineage in PRIMARY_LINEAGES:
            s1_cell = s1_root / lineage / f"vol_{volume:02d}"
            if not (s1_cell / "manifest.json").exists():
                # A cell with OCR sidecars on disk but NO manifest.json is
                # un-indexed content the verifier cannot leaf-check -- the
                # scoped-overwrite / staleness failure class. Surface it (needs
                # reindex_manifest) and fail. An empty or absent cell is simply
                # not-yet-OCR'd: skip it silently (incomplete coverage is allowed).
                pages_dir = s1_cell / "pages"
                if pages_dir.is_dir() and any(pages_dir.glob("*.json")):
                    s1_no_manifest.append(f"{lineage}/vol_{volume:02d}")
                continue
            result = _verify_s1_cell(repo_root, s1_cell, by_sha, gaps, body_leaf_nums)
            counts = result["counts"]
            totals["body_leaf_failures"] += len(result["a_failures"])
            totals["reuse_failures"] += len(result["b_failures"])
            totals["gap_pages"] += counts.get(GAP, 0)
            totals["nonbody_pages"] += counts.get(NONBODY, 0)
            totals["frontback_ok"] += counts.get(FRONTBACK_OK, 0)
            totals["frontback_unkeyed"] += counts.get(FRONTBACK_UNKEYED, 0)
            totals["multileaf_pages"] += counts.get(MULTILEAF, 0)
            totals["body_ok"] += counts.get(BODY_OK, 0)
            engine_leaf_sha[lineage] = result["leaf_sha"]
            cell_record = {
                "lineage": lineage,
                "volume": volume,
                "stage": "s1",
                "counts": counts,
                "a_failures": result["a_failures"],
                "b_failures": result["b_failures"],
            }

            # S2 for the same cell.
            s2_cell = s2_root / f"vol_{volume:02d}" / lineage
            label = f"{lineage}/vol_{volume:02d}"
            if (s2_cell / "index.json").exists():
                s2r = _verify_s2_cell(s2_cell, by_sha, body_leaf_nums)
                if s2r["n_body"] > 0 and s2r["n_stamped"] == 0:
                    # Split shape but NO body page stamped -> rendered before R4a
                    # leaf-stamping. A bounded-re-render coverage gap, not a bug.
                    s2_pending_rekey.append(label)
                else:
                    missing, extra = set_diff(s2r["rendered"], result["body_leaves"])
                    totals["s2_failures"] += len(s2r["a_failures"]) + len(extra)
                    if missing:
                        s2_lag.append(f"{label}: {len(missing)} S1 leaves not yet rendered")
                    cell_record["s2"] = {
                        "rendered": len(s2r["rendered"]),
                        "a_failures": s2r["a_failures"],
                        "extra": extra,
                        "missing": len(missing),
                    }
            elif (s2_cell / "rendering-v1.json").exists() or s2_cell.exists():
                s2_not_rerendered.append(label)
            cells.append(cell_record)

        conflicts = cross_engine_conflicts(engine_leaf_sha)
        if conflicts:
            totals["cross_engine_failures"] += len(conflicts)
            cross_engine.append({"volume": volume, "conflicts": conflicts})

        # --- R6b: alternate-scan lineages (skipped under primary_only) -------
        if primary_only:
            continue
        for lineage in ALTERNATE_LINEAGES:
            s1_cell = s1_root / lineage / f"vol_{volume:02d}"
            label = f"{lineage}/vol_{volume:02d}"
            if not (s1_cell / "manifest.json").exists():
                pages_dir = s1_cell / "pages"
                if pages_dir.is_dir() and any(pages_dir.glob("*.json")):
                    s1_no_manifest.append(label)
                continue
            alt = _verify_alt_s1_cell(repo_root, s1_cell, lineage, volume, body_leaf_nums)
            counts = alt["counts"]
            totals["alt_body_leaf_failures"] += len(alt["a_failures"])
            totals["alt_body_ok"] += counts.get(ALT_BODY_OK, 0)
            totals["alt_exempt_classified"] += counts.get(ALT_EXEMPT_CLASSIFIED, 0)
            totals["alt_exempt_no_leafmap"] += counts.get(ALT_EXEMPT_NO_LEAFMAP, 0)
            if alt["cell_unstamped"]:
                alt_unstamped_cells.append(label)
            if alt["clid_conflicts"]:
                # (c) cross-engine join is leaf-keyed by construction (clid IS the
                # canonical leaf, so any engine covering a physical page agrees on
                # it -- subsumed by (a), per the R6a primary note). A clid stamped
                # onto two stems WITHIN one alternate cell is the R7 aligner's own
                # many-to-one stem_to_leaf (a secondary scan re-shooting a page run);
                # both pages still carry the key, so it is a REPORTED diagnostic,
                # not a keying failure. Verified 2026-06-16 against the leafmaps.
                totals["alt_duplicate_clid_stamps"] += len(alt["clid_conflicts"])
                alt_duplicate_clid.append({"volume": volume, "lineage": lineage,
                                           "count": len(alt["clid_conflicts"])})
            cell_record = {
                "lineage": lineage, "volume": volume, "stage": "s1-alt",
                "counts": counts, "a_failures": alt["a_failures"],
                "cell_unstamped": alt["cell_unstamped"],
            }
            # (d) alternate S2: current-shape cells only; legacy-monolithic
            # alt renderings are reported pending, never failed.
            s2_cell = s2_root / f"vol_{volume:02d}" / lineage
            if (s2_cell / "index.json").exists():
                s2r = _verify_alt_s2_cell(s2_cell, alt["stamped_leaves"])
                totals["alt_s2_failures"] += len(s2r["extra"])
                cell_record["s2"] = {"rendered": len(s2r["rendered"]), "extra": s2r["extra"]}
            elif (s2_cell / "rendering-v1.json").exists() or s2_cell.exists():
                s2_not_rerendered.append(label)
            cells.append(cell_record)

    wct = _verify_wct(repo_root, selected)
    totals["wct_pages"] = wct["wct_pages"]
    totals["wct_body_ok"] = wct["wct_body_ok"]
    totals["wct_exempt"] = wct["wct_exempt"]
    totals["wct_missing_clid"] = len(wct["wct_failures"])
    totals["wct_pending_volumes"] = len(wct["wct_pending"])

    ok = (
        totals["body_leaf_failures"] == 0
        and totals["reuse_failures"] == 0
        and totals["cross_engine_failures"] == 0
        and totals["s2_failures"] == 0
        and totals["alt_body_leaf_failures"] == 0
        and totals["alt_s2_failures"] == 0
        and not alt_unstamped_cells
        and totals["wct_missing_clid"] == 0
        and not s1_no_manifest
        and not errors
    )
    # Cells touched by an (a) failure or an unstamped alt cell -- the >2-cell
    # hard-stop is measured on this set.
    failing_cells = sorted({
        f"{c['lineage']}/vol_{c['volume']:02d}"
        for c in cells if c.get("a_failures") or c.get("b_failures") or c.get("cell_unstamped")
    })
    return {
        "ok": ok,
        "primary_only": primary_only,
        **totals,
        "failing_cells": failing_cells,
        "cross_engine": cross_engine,
        "s2_not_rerendered": sorted(s2_not_rerendered),
        "s2_pending_rekey": sorted(s2_pending_rekey),
        "s2_lag": s2_lag,
        "s1_no_manifest": sorted(s1_no_manifest),
        "alt_unstamped_cells": sorted(alt_unstamped_cells),
        "alt_duplicate_clid": alt_duplicate_clid,
        "wct_missing": wct["wct_failures"],
        "wct_pending": wct["wct_pending"],
        "cells": cells,
        "errors": errors,
    }


# --- reporting + CLI --------------------------------------------------------

def print_report(report: dict[str, Any]) -> None:
    scope = "primary-chain (R6a)" if report.get("primary_only") else "full-chain (R6b)"
    print(f"=== leaf-keying verifier -- {scope} ===")
    print(f"  body_ok               : {report['body_ok']}")
    print(f"  (a) body-leaf failures: {report['body_leaf_failures']}")
    print(f"  (b) reuse failures    : {report['reuse_failures']}  (sha not in current manifest)")
    print(f"  (c) cross-engine fails: {report['cross_engine_failures']}")
    print(f"  (d) S2 failures       : {report['s2_failures']}")
    print(f"  exempt: gap={report['gap_pages']} nonbody={report['nonbody_pages']} multileaf={report['multileaf_pages']}")
    if not report.get("primary_only"):
        print("  --- alternate scans (abbyy/azure) ---")
        print(f"  alt body_ok           : {report['alt_body_ok']}")
        print(f"  alt (a) failures      : {report['alt_body_leaf_failures']}")
        print(f"  alt (d) S2 failures   : {report['alt_s2_failures']}")
        print(f"  alt (c) duplicate-clid stamps (aligner many-to-one; reported, not a failure): "
              f"{report['alt_duplicate_clid_stamps']}")
        for d in report.get("alt_duplicate_clid", [])[:20]:
            print(f"    dup-clid vol_{d['volume']:02d} {d['lineage']}: {d['count']}")
        print(f"  alt exempt: classified={report['alt_exempt_classified']} no_leafmap={report['alt_exempt_no_leafmap']}")
        if report.get("alt_unstamped_cells"):
            print(f"  *** alt cells unstamped (R7 not run): {report['alt_unstamped_cells']}")
        print(f"  WCT pages             : {report['wct_pages']}  body_ok={report['wct_body_ok']} "
              f"exempt={report['wct_exempt']}  failures={report['wct_missing_clid']}")
        for w in report.get("wct_missing", [])[:20]:
            print(f"    WCT failure: {w}")
        if report.get("wct_pending"):
            print(f"  WCT pending (unkeyed, awaits full rebuild incl. alternate ABBYY + remaining vols): "
                  f"{report['wct_pending']}")
    if report["failing_cells"]:
        print(f"  failing cells ({len(report['failing_cells'])}): {report['failing_cells']}")
        for cell in report["cells"]:
            for detail in cell.get("a_failures", [])[:20]:
                print(f"    (a) {cell['lineage']}/vol_{cell['volume']:02d}: {detail}")
            for detail in cell.get("b_failures", [])[:20]:
                print(f"    (b) {cell['lineage']}/vol_{cell['volume']:02d}: {detail}")
    if report["cross_engine"]:
        for entry in report["cross_engine"]:
            print(f"    (c) vol_{entry['volume']:02d}: {len(entry['conflicts'])} leaf-id sha conflicts")
    if report["s2_not_rerendered"]:
        print(f"  s2 legacy monolithic shape (pending bounded R4a re-render): {report['s2_not_rerendered']}")
    if report["s2_pending_rekey"]:
        print(f"  s2 split shape but unstamped (pending R4a leaf-stamp re-render): {report['s2_pending_rekey']}")
    if report["s2_lag"]:
        for note in report["s2_lag"]:
            print(f"  s2_lag: {note}")
    if report.get("s1_no_manifest"):
        print(f"  *** s1 cells with sidecars but NO manifest.json (run reindex_manifest): {report['s1_no_manifest']}")
    if report["errors"]:
        for err in report["errors"]:
            print(f"  ERROR: {err}")
    print(f"OVERALL: {'PASS' if report['ok'] else '*** FAIL ***'}")


def _parse_volumes(raw: str) -> list[int]:
    if "-" in raw:
        start, end = raw.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(part) for part in raw.split(",") if part]


def _staged_paths(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _gate(repo_root: Path) -> int:
    """Fast, scoped pre-commit gate (precedent: nsh_precommit_ocr_gate.py).

    Self-scopes: runs the full S1 verify only over volumes whose NSH manifest /
    page_order is staged; runs the verifier selftest when leaf-keying code is
    staged. Skips gracefully (exit 0) when the gitignored S1 store is absent
    (clean CI) or nothing relevant is staged -- a sub-second no-op otherwise.
    """
    try:
        staged = _staged_paths(repo_root)
    except subprocess.CalledProcessError:
        return 0
    code_staged = any(p.startswith(_GATE_CODE_PREFIXES) for p in staged)
    staged_volumes = sorted(
        {int(m.group(1)) for p in staged if (m := _GATE_MANIFEST_RE.match(p))}
    )
    if not code_staged and not staged_volumes:
        return 0
    if code_staged and selftest() != 0:
        print("[leaf-keying-gate] BLOCKED: verifier selftest failed.")
        return 1
    if not staged_volumes:
        return 0
    if not s1_sidecars_root(repo_root).exists():
        print("[leaf-keying-gate] S1 store absent -- skipped (cannot verify pixels here).")
        return 0
    report = verify_store(repo_root, volumes=staged_volumes)
    if report["ok"]:
        print(f"[leaf-keying-gate] OK -- staged volumes {staged_volumes} leaf-keyed.")
        return 0
    print(f"[leaf-keying-gate] BLOCKED: staged volumes {staged_volumes} fail leaf-keying:")
    print_report(report)
    return 1


def selftest() -> int:
    """One true-positive + one true-negative per pure rule (TEST-09)."""
    ok = True

    def expect(label: str, got, want):
        nonlocal ok
        if got != want:
            print(f"SELFTEST FAIL: {label} -> {got!r} (want {want!r})")
            ok = False
        else:
            print(f"SELFTEST PASS: {label}")

    leaves = [
        {"leaf_num": 10, "page_num": 1, "kind": "body", "sha256": "sha256:aaa"},
        {"leaf_num": 11, "page_num": 2, "kind": "body", "sha256": "sha256:bbb"},
        {"leaf_num": 2, "page_num": None, "kind": "front_matter", "sha256": "sha256:fff"},
    ]
    by_sha, gaps, body = build_indices({"leaves": leaves, "page_count": 2, "volume": 1})
    # (a) TN: correct leaf id passes; TP: missing leaf id flagged.
    expect("(a) TN body_ok", classify_page(10, "sha256:aaa", by_sha=by_sha, gaps=gaps, body_leaf_nums=body), BODY_OK)
    expect("(a) TP missing leaf", classify_page(None, "sha256:aaa", by_sha=by_sha, gaps=gaps, body_leaf_nums=body), BODY_MISSING_LEAF)
    expect(
        "frontback TN keyed",
        classify_page(
            None,
            "sha256:fff",
            by_sha=by_sha,
            gaps=gaps,
            body_leaf_nums=body,
            edition_page_key={"section": "front_matter", "anchor": 1, "ordinal": 0},
        ),
        FRONTBACK_OK,
    )
    expect(
        "frontback TP unkeyed",
        classify_page(None, "sha256:fff", by_sha=by_sha, gaps=gaps, body_leaf_nums=body),
        FRONTBACK_UNKEYED,
    )
    # (b) TP: a sha the manifest never saw is unresolved (re-OCR signature);
    #     TN: a sha the manifest knows is NOT flagged as re-OCR.
    expect("(b) TP unresolved", classify_page(1, "sha256:zzz", by_sha=by_sha, gaps=gaps, body_leaf_nums=body), UNRESOLVED)
    expect("(b) TN resolvable", classify_page(10, "sha256:aaa", by_sha=by_sha, gaps=gaps, body_leaf_nums=body) != UNRESOLVED, True)
    # (c) TN: aligned shas -> no conflict; TP: divergent shas -> conflict.
    expect("(c) TN no conflict", cross_engine_conflicts({"a": {10: "x"}, "b": {10: "x"}}), [])
    expect("(c) TP conflict", len(cross_engine_conflicts({"a": {10: "x"}, "b": {10: "y"}})), 1)
    # (d) TN: equal sets clean; TP: an extra render is surfaced.
    expect("(d) TN equal", set_diff({10, 11}, {10, 11}), ([], []))
    expect("(d) TP extra", set_diff({10, 11, 99}, {10, 11}), ([], [99]))

    # --- R6b alternate-scan rules ---
    # alt (a) TN: int clid in body set passes; TP: clid not a body leaf flagged.
    expect("alt(a) TN body_ok", classify_alt_page(10, "page_0001", body_leaf_nums=body, leafmap_classified=None), ALT_BODY_OK)
    expect("alt(a) TP wrong leaf", classify_alt_page(99, "page_0001", body_leaf_nums=body, leafmap_classified=None), ALT_WRONG_LEAF)
    # alt exempt TN: null clid classified non-body is exempt; TP: null clid with a
    # leafmap but no classification is a missed body page.
    expect("alt TN exempt-classified", classify_alt_page(None, "p", body_leaf_nums=body, leafmap_classified={"p": {"class": "non-body"}}), ALT_EXEMPT_CLASSIFIED)
    expect("alt TP unclassified", classify_alt_page(None, "p", body_leaf_nums=body, leafmap_classified={"q": {"class": "non-body"}}), ALT_MISSING_LEAF)
    # alt no-leafmap TN: null clid with no leafmap is offset-oracle residue.
    expect("alt TN no-leafmap residue", classify_alt_page(None, "p", body_leaf_nums=body, leafmap_classified=None), ALT_EXEMPT_NO_LEAFMAP)
    # alt (c) TN: unique clids no conflict; TP: a clid on two stems is a conflict.
    expect("alt(c) TN unique", duplicate_clid_conflicts([("page_0001", 10), ("page_0002", 11)]), [])
    expect("alt(c) TP duplicate", len(duplicate_clid_conflicts([("page_0001", 10), ("page_0009", 10)])), 1)
    # WCT TN: int clid present; TP: missing clid.
    expect("wct TN present", wct_clid_present({"canonical_leaf_id": 37}), True)
    expect("wct TP missing", wct_clid_present({}), False)
    expect("wct TN edition key", wct_page_key_present({"edition_page_key": {"section": "body", "anchor": 96, "ordinal": 0}}), True)
    # WCT TP: malformed edition key (bad section) + no clid -> not keyed.
    expect("wct TP bad edition key", wct_page_key_present({"edition_page_key": {"section": "x", "anchor": 96, "ordinal": 0}}), False)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify NSH full-chain leaf-keying (R6b / TEST-08): primary + "
                    "alternate scans (abbyy/azure) + WCT."
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--volumes", default="1-13")
    parser.add_argument(
        "--primary-only",
        dest="primary_only",
        action="store_true",
        default=False,
        help="Verify primary engines only (R6a subset; default verifies the full chain).",
    )
    parser.add_argument("--gate", action="store_true", help="Fast scoped pre-commit gate.")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()
    repo_root = Path(args.repo_root)
    if args.gate:
        return _gate(repo_root)
    report = verify_store(repo_root, primary_only=args.primary_only, volumes=_parse_volumes(args.volumes))
    print_report(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
