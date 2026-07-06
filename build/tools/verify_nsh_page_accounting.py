"""
End-to-end NSH page-accounting verification across ALL sources of truth.

For every volume, independently read:
  S1. Disk: page_*.jpg + leaf_*.jpg files actually present
  S2. Manifest: page_count, pages[] array, gaps[] array
  S3. page_order.json: the generated canonical sequence

Then assert every cross-source invariant. Report PASS/FAIL per check.
No trust in prior session outputs -- everything recomputed from primary state.

Importable (PY-06): the work lives in ``verify(base, volumes)``; nothing runs at
import time. The CLI entry point preserves the original behaviour -- verify the
real corpus across vols 1-13 and exit 0/1 -- so the subprocess caller
(``rebuild_nsh_pages.py``) is unaffected.
"""
import json
import pathlib
import sys
from collections import Counter
from collections import defaultdict

# Resolve relative to this file so the path carries no machine-specific identity.
REPO_ROOT = pathlib.Path(__file__).parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.edition_page_key import edition_page_sort_key  # noqa: E402
from build.lib.nsh_leaf_model import body_pages, leaves_view  # noqa: E402
from build.lib.ocr_store_paths import s1_sidecars_root  # noqa: E402
from build.tools.ocr_pipeline.reconcile_page_classes import (  # noqa: E402
    classify_volume,
    classify_volume_details,
    load_manifest,
)
from build.tools.verify_nsh_running_headers import (  # noqa: E402
    detect_sustained_runs,
    read_header_number,
    resolve_tesseract,
)

BASE = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"

# Model B (docs/NSH_FETCHER_MECHANISM_DIAGNOSIS.md): page_num is the TRUE printed
# page number, scan gaps are preserved as holes, and the body-missing set is
# DERIVED from the manifest gaps[] rather than hardcoded. A gap counts toward the
# body total (and is a real hole with no disk file) when its status is body-missing.
# Keep this set in sync with BODY_MISSING_GAP_STATUSES in fetch_ia_pages.py.
BODY_MISSING_GAP_STATUSES = {"permanently_missing", "absent_from_primary_scan"}

REASONED_HOLE_STATUSES = {
    "out_of_range",
    "permanently_missing",
    "confirmed_absent",
    "absent_from_primary_scan",
}

PRIMARY_COPY_LINEAGES = {
    "tesseract-py314-v1",
    "kraken-py312-v1",
    "surya-py312-v1",
    "kraken-greek-py312-v1",
    "ia-abbyy-v1",
    "azure-ai-vision-v1",
}

# Depth counts independent physical scan-copies, not engines. All primary
# engines read the same IA scan and therefore collapse to one copy-family.
COPY_FAMILY = {lineage: "primary" for lineage in PRIMARY_COPY_LINEAGES}
COPY_FAMILY.update(
    {
        "ia-abbyy-dli-v1": "ia-abbyy-dli-v1",
        "ia-abbyy-haucgoog-v1": "ia-abbyy-haucgoog-v1",
        "ia-abbyy-haucgoog-c1-v1": "ia-abbyy-haucgoog-c1-v1",
        "ia-abbyy-haucgoog-c2-v1": "ia-abbyy-haucgoog-c2-v1",
        "ia-abbyy-haucgoog-c3-v1": "ia-abbyy-haucgoog-c3-v1",
        "ia-abbyy-haucgoog-c4-v1": "ia-abbyy-haucgoog-c4-v1",
    }
)

VALID_EDITION_SECTIONS = {"front_matter", "body", "back_matter"}


def verify(base: pathlib.Path = BASE, volumes=range(1, 14), *, out=print) -> bool:
    """Run every cross-source invariant for each volume under ``base``.

    Returns True iff all checks pass. ``out`` is the line sink (default ``print``);
    tests pass a collector. The default arguments reproduce the original script:
    the real corpus, vols 1-13.
    """
    all_pass = True

    def check(name, ok, detail=""):
        nonlocal all_pass
        if not ok:
            all_pass = False
        flag = "PASS" if ok else "**FAIL**"
        out(f"  [{flag}] {name}" + (f"  -- {detail}" if detail else ""))
        return ok

    grand_body = grand_present = grand_missing = 0

    for vol in volumes:
        vol_id = f"vol_{vol:02d}"
        vdir = base / vol_id
        out(f"\n=== {vol_id} ===")

        # S1: disk
        disk_pages = {int(f.stem.split("_")[1]) for f in vdir.glob("page_*.jpg")}
        disk_leaves = {int(f.stem.split("_")[1]) for f in vdir.glob("leaf_*.jpg")}

        # S2: manifest
        mf = json.loads((base / f"{vol_id}.manifest.json").read_bytes())
        page_count = mf["page_count"]
        pages = body_pages(mf)  # accessor; legacy fallback carries page_num/ia_leaf_id/ia_item_id verbatim
        page_nums = [p["page_num"] for p in pages]
        # Namespace leaf ids per source item: an alternate-sourced page carries the
        # alternate item's leaf number (in ia_item_id), which can legitimately match a
        # primary leaf. Only a collision WITHIN one item is the phantom bug.
        leaf_ids = [
            (p.get("ia_item_id") or "<primary>", p["ia_leaf_id"])
            for p in pages if p.get("ia_leaf_id")
        ]
        gaps = mf.get("gaps", [])
        # Model B: the body-missing set is every in-body gap whose status marks it as a
        # real hole (permanently missing OR absent from the primary scan). Pages flagged
        # duplicate_needs_adjudication are NOT missing -- they have a file -- so they are
        # excluded here and must appear on disk.
        body_missing = {
            g["page_num"]
            for g in gaps
            if isinstance(g.get("page_num"), int)
            and g["page_num"] <= page_count
            and g.get("status") in BODY_MISSING_GAP_STATUSES
        }
        # v4 (schema 4.1.0): a body page recovered from an alternate scan that the
        # primary scan never captured (Scenario A) has NO spine leaf, so it is NOT in
        # body_pages(); its image + provenance live on its gaps[] entry (local_path
        # present). It is a present body page on disk all the same -- count it so the
        # tiling / orphan / page_count checks include it.
        recovered_present = {
            g["page_num"]
            for g in gaps
            if isinstance(g.get("page_num"), int)
            and g["page_num"] <= page_count
            and g.get("local_path")
        }
        page_nums = page_nums + sorted(recovered_present - set(page_nums))

        # S3: page_order
        po = json.loads((vdir / "page_order.json").read_bytes())
        po_pages = po.get("pages", po.get("entries", []))
        po_body = [e for e in po_pages if e.get("corpus_role") == "body"]
        po_body_present = [e for e in po_body if e.get("scan_status") == "present"]
        po_body_unresolved = [e for e in po_body if e.get("scan_status") == "unresolved"]

        # --- Invariant checks ---
        # 1. No duplicate page_nums in manifest pages[]
        dup_pn = [pn for pn, c in Counter(page_nums).items() if c > 1]
        check("no duplicate page_num in manifest pages[]", not dup_pn, f"dups={dup_pn}")

        # 2. No duplicate leaf IDs in manifest pages[]
        dup_leaf = [l for l, c in Counter(leaf_ids).items() if c > 1]
        check("no duplicate ia_leaf_id in manifest pages[]", not dup_leaf, f"dups={dup_leaf}")

        # 3. Model B: present page_nums and in-body body-missing gaps TILE 1..page_count
        #    disjointly -- every body page is either a present file or a recorded hole,
        #    never both, never neither. (Replaces the Model-A contiguity check, which
        #    forced squeezing out scan gaps -- the source of the content-position corruption.)
        present_pn = set(page_nums)
        expected_body = set(range(1, page_count + 1))
        overlap = present_pn & body_missing
        tiled = present_pn | body_missing
        check("present pages + body-missing gaps tile 1..page_count (Model B)",
              tiled == expected_body and not overlap,
              f"untiled={sorted(expected_body - tiled)[:5]} extra={sorted(tiled - expected_body)[:5]} overlap={sorted(overlap)[:5]}")

        # 4. Every manifest page_num has a disk file
        pn_set = set(page_nums)
        missing_on_disk = pn_set - disk_pages
        check("every manifest page has a disk file", not missing_on_disk,
              f"manifest pages with no jpg={sorted(missing_on_disk)[:10]}")

        # 5. Every disk page_*.jpg has a manifest entry (no orphan files)
        orphan_disk = disk_pages - pn_set
        check("no orphan disk page_*.jpg (all in manifest)", not orphan_disk,
              f"orphans={sorted(orphan_disk)[:10]}")

        # 6. page_count = disk-present body pages + body-missing holes (Model B)
        expected_missing = body_missing
        check("page_count == disk_present + body_missing",
              page_count == len(disk_pages) + len(expected_missing),
              f"page_count={page_count} disk={len(disk_pages)} body_missing={len(expected_missing)}")

        # 7. Every body-missing gap is a real hole: no disk file at that page number.
        missing_with_file = body_missing & disk_pages
        check("body-missing gaps have no disk file (real holes)",
              not missing_with_file,
              f"missing-but-on-disk={sorted(missing_with_file)[:10]}")

        # 8. page_order body count == page_count
        check("page_order body count == page_count",
              len(po_body) == page_count,
              f"po_body={len(po_body)} page_count={page_count}")

        # 9. page_order present == disk pages count
        # (vol_01 counts leaf files as present too, so compare body-present specifically)
        check("page_order body-present == disk page_*.jpg count",
              len(po_body_present) == len(disk_pages),
              f"po_present={len(po_body_present)} disk={len(disk_pages)}")

        # 10. page_order unresolved == body-missing count
        check("page_order body-unresolved == body_missing count",
              len(po_body_unresolved) == len(expected_missing),
              f"po_unresolved={len(po_body_unresolved)} expected={len(expected_missing)}")

        grand_body += page_count
        grand_present += len(disk_pages)
        grand_missing += len(expected_missing)

        out(f"  -> body={page_count} present={len(disk_pages)} missing={len(expected_missing)} leaves={len(disk_leaves)}")

    out(f"\n{'='*60}")
    out(f"CORPUS TOTAL: body={grand_body} present={grand_present} missing={grand_missing}")
    out(f"  present + missing = {grand_present + grand_missing} (should == body {grand_body})")
    if grand_body:
        out(f"  coverage = {100*grand_present/grand_body:.2f}%")
    out(f"\nOVERALL: {'ALL CHECKS PASS' if all_pass else '*** SOME CHECKS FAILED ***'}")
    return all_pass


def verify_completeness(
    repo_root: pathlib.Path = REPO_ROOT,
    volumes=range(1, 14),
    *,
    header_reader=read_header_number,
    out=print,
    content_sample_pages=None,
    full_content: bool = False,
) -> dict:
    """Verify NSH edition-page completeness across coverage, depth, and content.

    Coverage delegates page classification to ``reconcile_page_classes``. This
    gate adds status-based true-hole reasoning, edition-page-key validation,
    scan-copy depth, and sampled running-header reads.
    """
    repo_root = pathlib.Path(repo_root)
    selected = list(volumes)
    result = {
        "ok": True,
        "coverage": {"hard_failures": [], "unkeyed_body_pages": [], "classes": {}},
        "depth": {"by_volume": {}, "corpus_distribution": {}, "missing_manifests": []},
        "frontback": {"by_volume": {}, "unkeyed": [], "orphans": []},
        "content": {"mismatches": [], "rename_signature_runs": [], "sampled_pages": {}, "available": True},
    }

    # The real running-header reader shells out to tesseract; resolve the binary
    # once (the standalone tool does this in its CLI) and probe availability so a
    # missing binary degrades to a skipped content axis with one NOTE rather than
    # crashing the gate (REL-02/REL-08: safe to run unattended). An injected reader
    # (tests) bypasses tesseract entirely.
    content_available = _ensure_content_reader(header_reader, out)
    result["content"]["available"] = content_available

    out("=== NSH edition-completeness gate ===")
    for volume in selected:
        manifest = load_manifest(repo_root, volume)
        vol_id = f"vol_{volume:02d}"
        out(f"\n=== {vol_id} ===")

        classes = classify_volume(manifest, repo_root)
        details = classify_volume_details(manifest, repo_root)
        result["coverage"]["classes"][volume] = classes
        coverage_failures = _coverage_failures(volume, manifest, details)
        key_failures = _unkeyed_body_pages(repo_root, volume, out=out)
        result["coverage"]["hard_failures"].extend(coverage_failures)
        result["coverage"]["unkeyed_body_pages"].extend(key_failures)

        if coverage_failures or key_failures:
            result["ok"] = False
        _print_coverage_report(out, classes, coverage_failures, key_failures)

        depth_report = _depth_for_volume(repo_root, volume, out=out)
        result["depth"]["by_volume"][volume] = {
            "distribution": dict(depth_report["distribution"]),
            "body_depths": depth_report["body_depths"],
        }
        result["depth"]["missing_manifests"].extend(depth_report["missing_manifests"])
        _print_depth_report(out, depth_report)

        frontback_report = _frontback_for_volume(repo_root, volume, manifest)
        result["frontback"]["by_volume"][volume] = {
            "covered": frontback_report["covered"],
            "awaiting_ocr": frontback_report["awaiting_ocr"],
        }
        result["frontback"]["unkeyed"].extend(frontback_report["unkeyed"])
        result["frontback"]["orphans"].extend(frontback_report["orphans"])
        if frontback_report["unkeyed"] or frontback_report["orphans"]:
            result["ok"] = False
        _print_frontback_report(out, frontback_report)

        content_report = _content_for_volume(
            repo_root,
            volume,
            manifest,
            header_reader=header_reader,
            content_sample_pages=content_sample_pages,
            full_content=full_content,
            content_available=content_available,
            out=out,
        )
        result["content"]["mismatches"].extend(content_report["mismatches"])
        result["content"]["rename_signature_runs"].extend(content_report["rename_signature_runs"])
        result["content"]["sampled_pages"][volume] = content_report["sampled_pages"]
        if content_report["rename_signature_runs"]:
            result["ok"] = False
        _print_content_report(out, content_report)

    corpus_counter = Counter()
    for volume_report in result["depth"]["by_volume"].values():
        corpus_counter.update(volume_report["distribution"])
    result["depth"]["corpus_distribution"] = dict(sorted(corpus_counter.items()))

    if (
        result["coverage"]["hard_failures"]
        or result["coverage"]["unkeyed_body_pages"]
        or result["frontback"]["unkeyed"]
        or result["frontback"]["orphans"]
    ):
        result["ok"] = False
    out(f"\nCORPUS DEPTH DISTRIBUTION: {result['depth']['corpus_distribution']}")
    out(f"OVERALL COMPLETENESS: {'PASS' if result['ok'] else 'FAIL'}")
    return result


def _coverage_failures(volume: int, manifest: dict, details: list[dict]) -> list[dict]:
    status_by_page = {
        gap.get("page_num"): gap.get("status")
        for gap in manifest.get("gaps", [])
        if isinstance(gap, dict) and isinstance(gap.get("page_num"), int)
    }
    failures = []
    for detail in details:
        page_class = detail["class"]
        if page_class in {"stale_gap_record", "image_not_ocrd"}:
            failures.append({"volume": volume, "page_num": detail["page_num"], "class": page_class})
        elif page_class == "true_hole":
            status = status_by_page.get(detail["page_num"])
            if status not in REASONED_HOLE_STATUSES:
                failures.append(
                    {
                        "volume": volume,
                        "page_num": detail["page_num"],
                        "class": page_class,
                        "status": status,
                    }
                )
    return failures


def _unkeyed_body_pages(repo_root: pathlib.Path, volume: int, *, out=print) -> list[dict]:
    """Flag covered BODY pages whose sidecar lacks a well-formed edition_page_key.

    Only the body namespace (page_NNNN.json) is in scope. A well-formed key whose
    section is front_matter / back_matter is legitimately keyed -- it is SKIPPED,
    not failed (a non-body key is not a defect). A non-numeric page_* stem is not a
    body page and is skipped. A corrupted sidecar is logged and skipped, never
    aborts the volume (REL-08).
    """
    failures = []
    for lineage, cell in _iter_volume_cells(repo_root, volume):
        pages_dir = cell / "pages"
        if not pages_dir.is_dir():
            continue
        for sidecar_path in sorted(pages_dir.glob("page_*.json")):
            page_num = _page_num_from_native(sidecar_path.stem)
            if page_num is None:
                continue  # not a body-namespace numbered page
            try:
                payload = _read_json(sidecar_path)
            except (json.JSONDecodeError, ValueError) as exc:
                out(f"  [NOTE] unreadable sidecar {lineage}/{sidecar_path.name}: {type(exc).__name__}")
                continue
            key = payload.get("edition_page_key")
            if _edition_key_well_formed(key) and key.get("section") != "body":
                continue  # legitimately keyed front/back matter -- not a body defect
            if not _edition_key_well_formed(key):
                failures.append({"volume": volume, "page_num": page_num, "lineage": lineage})
    failures.sort(key=lambda item: (item["volume"], item["page_num"], item["lineage"]))
    return failures


def _depth_for_volume(repo_root: pathlib.Path, volume: int, *, out=print) -> dict:
    by_key: dict[tuple, set[str]] = defaultdict(set)
    body_depths = {}
    missing_manifests = []
    for lineage, cell in _iter_volume_cells(repo_root, volume):
        manifest_path = cell / "manifest.json"
        pages_dir = cell / "pages"
        if not manifest_path.exists():
            if pages_dir.is_dir() and any(pages_dir.glob("*.json")):
                missing_manifests.append({"volume": volume, "lineage": lineage, "cell": str(cell)})
            continue
        family = COPY_FAMILY.get(lineage, lineage)
        # A malformed cell manifest is a per-cell condition, not a global
        # precondition: log it and continue so one bad cell never aborts the
        # corpus-wide gate (REL-08, safe to run unattended).
        try:
            manifest = _read_json(manifest_path)
            pages = manifest.get("pages", [])  # nsh-legacy-read: S1 sidecar manifest, not source manifest.
            if not isinstance(pages, list):
                raise ValueError(f"S1 manifest pages is not a list: {manifest_path}")
            for page_ref in pages:
                if not isinstance(page_ref, dict):
                    raise ValueError(f"S1 manifest page ref is not an object: {manifest_path}")
                key = page_ref.get("edition_page_key")
                if not _edition_key_well_formed(key):
                    continue
                by_key[_edition_key_tuple(key)].add(family)
        except (json.JSONDecodeError, ValueError) as exc:
            out(f"  [NOTE] malformed S1 manifest {lineage}/vol_{volume:02d}: {type(exc).__name__}")
            missing_manifests.append({"volume": volume, "lineage": lineage, "cell": str(cell)})
            continue

    distribution = Counter()
    for key_tuple, families in sorted(by_key.items(), key=lambda item: edition_page_sort_key(_key_from_tuple(item[0]))):
        key = _key_from_tuple(key_tuple)
        depth = len(families)
        distribution[depth] += 1
        if key["section"] == "body":
            body_depths[key_tuple] = depth
    # Lane B front/back orphan coverage folds in here when the manifest/image
    # model lands; this pass already enumerates every lineage cell.
    return {
        "distribution": dict(sorted(distribution.items())),
        "body_depths": body_depths,
        "missing_manifests": missing_manifests,
    }


def _content_for_volume(
    repo_root: pathlib.Path,
    volume: int,
    manifest: dict,
    *,
    header_reader,
    content_sample_pages,
    full_content: bool,
    content_available: bool = True,
    out=print,
) -> dict:
    if not content_available:
        return {"sampled_pages": [], "mismatches": [], "rename_signature_runs": []}
    sampled = _select_content_pages(repo_root, volume, manifest, content_sample_pages, full_content)
    records = []
    mismatches = []
    for page_num in sampled:
        img_path = (
            repo_root
            / "raw"
            / "internet-archive"
            / "schaff-herzog-pages"
            / f"vol_{volume:02d}"
            / f"page_{page_num:04d}.jpg"
        )
        if not img_path.exists():
            continue
        try:
            info = header_reader(img_path)
        except Exception as exc:  # noqa: BLE001 - per-page OCR failure must not abort the gate (REL-08)
            out(f"  [NOTE] content read failed page={page_num}: {type(exc).__name__}")
            records.append({"page_num": page_num, "status": "unreadable", "header_num": None, "delta": None})
            continue
        header_num = info.get("header_num")
        if header_num is None:
            record = {"page_num": page_num, "status": "unreadable", "header_num": None, "delta": None}
        else:
            delta = int(header_num) - page_num
            record = {
                "page_num": page_num,
                "status": "match" if delta == 0 else "mismatch",
                "header_num": int(header_num),
                "delta": delta,
            }
            if delta != 0:
                mismatches.append(
                    {
                        "volume": volume,
                        "page_num": page_num,
                        "expected": page_num,
                        "actual": int(header_num),
                        "delta": delta,
                    }
                )
        records.append(record)
    rename_runs = [
        dict(run, volume=volume)
        for run in detect_sustained_runs(records)
        if not run.get("recovers")
    ]
    return {"sampled_pages": sampled, "mismatches": mismatches, "rename_signature_runs": rename_runs}


def _ensure_content_reader(header_reader, out) -> bool:
    """Resolve tesseract and confirm it runs, for the real running-header reader.

    Returns True when the content axis can run. An injected (non-default) reader
    is assumed self-contained and always available. When tesseract is absent the
    content axis is skipped with one NOTE -- it is a sampled cross-check, not the
    primary coverage gate, so its absence must not crash an unattended run.
    """
    if header_reader is not read_header_number:
        return True
    import pytesseract  # local import: tests with an injected reader need no tesseract
    try:
        pytesseract.pytesseract.tesseract_cmd = resolve_tesseract()
        pytesseract.get_tesseract_version()
        return True
    except Exception as exc:  # noqa: BLE001 - missing binary degrades, never aborts
        out(f"  [NOTE] content axis skipped -- tesseract unavailable ({type(exc).__name__})")
        return False


def _select_content_pages(
    repo_root: pathlib.Path,
    volume: int,
    manifest: dict,
    content_sample_pages,
    full_content: bool,
) -> list[int]:
    present_body = [
        page["page_num"]
        for page in body_pages(manifest)
        if isinstance(page.get("page_num"), int)
        and (
            repo_root
            / "raw"
            / "internet-archive"
            / "schaff-herzog-pages"
            / f"vol_{volume:02d}"
            / f"page_{page['page_num']:04d}.jpg"
        ).exists()
    ]
    present_body = sorted(set(present_body))
    if full_content:
        return present_body
    if isinstance(content_sample_pages, dict):
        return [page for page in content_sample_pages.get(volume, []) if page in present_body]
    if content_sample_pages is not None:
        return [page for page in content_sample_pages if page in present_body]
    return present_body[-5:]


def _print_coverage_report(out, classes: dict, failures: list[dict], key_failures: list[dict]) -> None:
    out(
        "  coverage classes: "
        + " ".join(f"{name}={len(pages)}" for name, pages in classes.items())
    )
    for failure in failures:
        extra = f" status={failure['status']}" if "status" in failure else ""
        out(f"  [FAIL] coverage {failure['class']} page={failure['page_num']}{extra}")
    for failure in key_failures:
        out(
            "  [FAIL] unkeyed covered body page "
            f"lineage={failure['lineage']} page={failure['page_num']}"
        )
    if not failures and not key_failures:
        out("  [PASS] coverage")


def _print_depth_report(out, report: dict) -> None:
    out(f"  depth distribution: {report['distribution']}")
    for missing in report["missing_manifests"]:
        out(f"  [NOTE] sidecars without manifest lineage={missing['lineage']}")


def _frontback_for_volume(repo_root: pathlib.Path, volume: int, manifest: dict) -> dict:
    covered = 0
    awaiting_ocr = 0
    unkeyed = []
    orphans = []
    for leaf in leaves_view(manifest):
        kind = leaf.get("kind")
        leaf_num = leaf.get("leaf_num")
        if not isinstance(leaf_num, int):
            continue
        sidecars = _frontback_sidecars(repo_root, volume, leaf_num)
        if kind == "discarded":
            for lineage, _path in sidecars:
                orphans.append({"volume": volume, "leaf_num": leaf_num, "lineage": lineage})
            continue
        if kind not in {"front_matter", "back_matter"}:
            continue
        if leaf.get("image_state") != "present" or leaf.get("blank") is True:
            continue
        if not sidecars:
            awaiting_ocr += 1
            continue
        valid_seen = False
        invalid_seen = False
        for lineage, path in sidecars:
            try:
                payload = _read_json(path)
            except (json.JSONDecodeError, ValueError):
                unkeyed.append({"volume": volume, "leaf_num": leaf_num, "lineage": lineage})
                invalid_seen = True
                continue
            key = payload.get("edition_page_key")
            if _frontback_key_well_formed(key):
                valid_seen = True
            else:
                unkeyed.append({"volume": volume, "leaf_num": leaf_num, "lineage": lineage})
                invalid_seen = True
        if valid_seen and not invalid_seen:
            covered += 1
    return {
        "covered": covered,
        "awaiting_ocr": awaiting_ocr,
        "unkeyed": sorted(unkeyed, key=lambda item: (item["volume"], item["leaf_num"], item["lineage"])),
        "orphans": sorted(orphans, key=lambda item: (item["volume"], item["leaf_num"], item["lineage"])),
    }


def _frontback_sidecars(repo_root: pathlib.Path, volume: int, leaf_num: int) -> list[tuple[str, pathlib.Path]]:
    stem = f"leaf_{leaf_num:04d}"
    found = []
    for lineage, cell in _iter_volume_cells(repo_root, volume):
        if lineage not in PRIMARY_COPY_LINEAGES:
            continue
        path = cell / "pages" / f"{stem}.json"
        if path.exists():
            found.append((lineage, path))
    return found


def _frontback_key_well_formed(key) -> bool:
    return _edition_key_well_formed(key) and key.get("section") in {"front_matter", "back_matter"}


def _print_frontback_report(out, report: dict) -> None:
    out(
        "  front/back: "
        f"covered={report['covered']} awaiting_ocr={report['awaiting_ocr']} "
        f"unkeyed={len(report['unkeyed'])} orphans={len(report['orphans'])}"
    )
    for failure in report["unkeyed"]:
        out(
            "  [FAIL] front/back unkeyed "
            f"lineage={failure['lineage']} leaf={failure['leaf_num']}"
        )
    for failure in report["orphans"]:
        out(
            "  [FAIL] front/back orphan "
            f"lineage={failure['lineage']} leaf={failure['leaf_num']}"
        )


def _print_content_report(out, report: dict) -> None:
    out(f"  content sampled pages: {report['sampled_pages']}")
    for mismatch in report["mismatches"]:
        out(
            "  [NOTE] content mismatch "
            f"page={mismatch['page_num']} expected={mismatch['expected']} actual={mismatch['actual']}"
        )
    for run in report["rename_signature_runs"]:
        out(
            "  [FAIL] sustained content-position run "
            f"pages={run['start_page']}-{run['end_page']} delta={run['delta']}"
        )
    if not report["mismatches"] and not report["rename_signature_runs"]:
        out("  [PASS] content sample")


def _iter_volume_cells(repo_root: pathlib.Path, volume: int):
    root = s1_sidecars_root(repo_root)
    if not root.is_dir():
        return
    vol_id = f"vol_{volume:02d}"
    for lineage_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        cell = lineage_dir / vol_id
        if cell.is_dir():
            yield lineage_dir.name, cell


def _edition_key_well_formed(key) -> bool:
    return (
        isinstance(key, dict)
        and key.get("section") in VALID_EDITION_SECTIONS
        and isinstance(key.get("anchor"), int)
        and isinstance(key.get("ordinal"), int)
        and key["ordinal"] >= 0
    )


def _edition_key_tuple(key: dict) -> tuple[str, int, int]:
    return (key["section"], int(key["anchor"]), int(key["ordinal"]))


def _key_from_tuple(key: tuple[str, int, int]) -> dict:
    return {"section": key[0], "anchor": key[1], "ordinal": key[2]}


def _page_num_from_native(native) -> int | None:
    text = str(native)
    if text.startswith("page_") and text[5:].isdigit():
        return int(text[5:])
    return None


def _read_json(path: pathlib.Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON file is not an object: {path}")
    return payload


def _parse_cli_pages(raw: str) -> list[int]:
    pages = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            pages.extend(range(int(lo), int(hi) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        return 0 if verify() else 1
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--completeness", action="store_true", help="Run the edition-completeness gate.")
    parser.add_argument("--repo-root", type=pathlib.Path, default=REPO_ROOT)
    parser.add_argument("--volume", type=int, action="append", help="Volume number to check; repeatable.")
    parser.add_argument("--full-content", action="store_true", help="Read running headers for every present body page.")
    parser.add_argument("--content-pages", help="Comma/range page sample, e.g. 90-100,498.")
    args = parser.parse_args(argv)
    volumes = args.volume if args.volume else range(1, 14)
    if args.completeness:
        sample = _parse_cli_pages(args.content_pages) if args.content_pages else None
        result = verify_completeness(
            repo_root=args.repo_root,
            volumes=volumes,
            content_sample_pages=sample,
            full_content=args.full_content,
        )
        return 0 if result["ok"] else 1
    # Non-zero exit so this can gate a commit or CI step (REL-02).
    return 0 if verify(volumes=volumes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
