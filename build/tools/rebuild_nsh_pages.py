"""
rebuild_nsh_pages.py -- Idempotent disk-as-ground-truth rebuild + gate for NSH page accounting.

WHY THIS EXISTS (post-mortem 2026-06-09, research/2026-06-09-postmortem-nsh-phantom-page-fix.md):
The NSH phantom-page fix drifted because three representations of one truth --
  (1) on-disk page_*.jpg files  (2) manifest page_count/pages[]/gaps[]  (3) page_order.json
-- were reconciled by a chain of order-dependent one-shot scripts across compaction
boundaries. Derived state got reconciled to a disk state that did not exist. The disk
files are the only ground-truth representation AND the only one not in git (raw/ is
gitignored), so the drift was invisible to `git diff`/`git status`.

THE CONTRACT (deliberately narrow -- it owns only the purely disk-derivable layer):
  --rebuild  Treat disk page_*.jpg as ground truth. Recompute each manifest's page_count
             from (disk-present pages + that manifest's own permanently_missing gaps),
             then regenerate page_order.json from disk via the existing generators,
             then run the verifier. Idempotent: a no-op on a clean corpus.
  --check    (default) Run the end-to-end verifier across all three representations and
             exit with its status. Safe to use as a pre-commit / CI gate.

WHAT IT DOES NOT DO -- on purpose:
  It does NOT rebuild the manifest pages[] array. Each entry carries provenance
  (ia_leaf_id, sha256, ia_filename, fetched_at, image_size) that cannot be reconstructed
  from a disk filename. If a disk file has no matching pages[] entry, or pages[] still
  holds stale phantom entries, the verifier REPORTS it loudly (orphan / duplicate / count
  mismatch) -- it is never silently fabricated. Fixing pages[] provenance after a phantom
  delete+rename remains the explicit, dry-runnable job of fix_phantom_files.py. Mutate the
  disk there; derive everything else here.

This is a manually-run idempotent reconciler (REL-03 logfile exemption: prints to stdout).
"""
import argparse
import json
import pathlib
import subprocess
import sys

# Resolve everything from this file so no machine-specific path is embedded (OUT-03).
TOOLS_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parents[1]
PAGES_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog-pages"

VERIFIER = TOOLS_DIR / "verify_nsh_page_accounting.py"
GEN_MAIN = TOOLS_DIR / "generate_page_order.py"          # vols 02-13
GEN_VOL01 = TOOLS_DIR / "generate_vol01_page_order.py"   # vol_01 only

VOLUMES = range(1, 14)


def _disk_page_count(vol_dir: pathlib.Path) -> int:
    """Count page_*.jpg files actually present on disk -- the ground truth."""
    return sum(1 for _ in vol_dir.glob("page_*.jpg"))


def _perm_missing_from_manifest(manifest: dict) -> int:
    """Permanently-missing pages, taken from the manifest's own gaps[].

    Using the manifest's own gaps (not a hardcoded constant) keeps page_count
    self-consistent; the verifier independently asserts this set matches the known
    permanent-missing set, so a wrong gap entry fails loudly rather than here.
    """
    return sum(
        1 for g in manifest.get("gaps", [])
        if g.get("status") == "permanently_missing"
    )


def _write_manifest_atomic(path: pathlib.Path, manifest: dict) -> None:
    """Atomic write (OUT-02): temp file then os.replace, so a partial write can't poison a re-run."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _run(script: pathlib.Path, *args: str) -> int:
    """Run a sibling tool with the current interpreter and return its exit code.

    Uses check=True (SUB-01) so a crash raises; a clean non-zero exit (the verifier
    signalling an inconsistent corpus) is a handled result, returned to the caller --
    not a silently-ignored failure.
    """
    cmd = [sys.executable, str(script), *args]
    print(f"  -> running {script.name} {' '.join(args)}".rstrip())
    try:
        subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)
        return 0
    except subprocess.CalledProcessError as exc:
        return exc.returncode


def reconcile_page_counts(dry_run: bool) -> int:
    """Recompute every manifest's page_count from disk + its own permanent-missing gaps.

    Returns the number of manifests whose page_count was (or would be) changed.
    """
    changed = 0
    for vol in VOLUMES:
        vol_id = f"vol_{vol:02d}"
        manifest_path = PAGES_DIR / f"{vol_id}.manifest.json"
        vol_dir = PAGES_DIR / vol_id
        if not manifest_path.exists():
            raise FileNotFoundError(f"Missing manifest: {manifest_path}")  # REL-02 fail fast
        manifest = json.loads(manifest_path.read_bytes())
        present = _disk_page_count(vol_dir)
        perm_missing = _perm_missing_from_manifest(manifest)
        new_count = present + perm_missing
        old_count = manifest.get("page_count")
        if old_count == new_count:
            print(f"  {vol_id}: page_count={new_count} (present {present} + perm_missing {perm_missing}) -- unchanged")
            continue
        changed += 1
        verb = "WOULD SET" if dry_run else "set"
        print(f"  {vol_id}: page_count {old_count} -> {new_count} "
              f"(present {present} + perm_missing {perm_missing}) -- {verb}")
        if not dry_run:
            manifest["page_count"] = new_count
            _write_manifest_atomic(manifest_path, manifest)
    return changed


def regenerate_page_orders() -> int:
    """Regenerate every page_order.json from disk via the existing generators."""
    rc = _run(GEN_MAIN)            # vols 02-13
    rc |= _run(GEN_VOL01)         # vol_01
    return rc


def run_verifier() -> int:
    """Run the end-to-end verifier; its exit code is the gate result."""
    print("\n=== verifier (verify_nsh_page_accounting.py) ===")
    return _run(VERIFIER)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="(default) run the verifier across all three representations and exit with its status")
    mode.add_argument("--rebuild", action="store_true",
                      help="recompute page_count from disk + regenerate page_order, then verify")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --rebuild: show page_count changes without writing")
    args = parser.parse_args()

    if not PAGES_DIR.is_dir():
        raise FileNotFoundError(f"NSH pages dir not found: {PAGES_DIR}")  # REL-02

    if args.rebuild:
        print("=== rebuild: page_count from disk (ground truth) ===")
        changed = reconcile_page_counts(dry_run=args.dry_run)
        print(f"\n{changed} manifest page_count value(s) {'would change' if args.dry_run else 'changed'}.")
        if args.dry_run:
            print("Dry run -- page_order NOT regenerated, verifier NOT run. Re-run with --rebuild (no --dry-run).")
            return 0
        print("\n=== rebuild: regenerate page_order from disk ===")
        if regenerate_page_orders() != 0:
            print("*** page_order generation reported an error -- aborting before verify ***")
            return 1
        rc = run_verifier()
        print(f"\nREBUILD {'OK -- corpus consistent' if rc == 0 else 'FAILED -- see verifier output above'}")
        return rc

    # default: --check
    rc = run_verifier()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
