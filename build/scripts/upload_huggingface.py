"""
upload_huggingface.py -- Push exports/huggingface/ to HuggingFace dataset repo.

Uploads the JSONL files and README.md from exports/huggingface/ to the
HuggingFace dataset repo open-christian-data/open-christian-data.

Requires:
    pip install huggingface_hub
    HF_TOKEN environment variable set to a HuggingFace write token.
    To set the token on Windows, run in a command prompt:
        setx HF_TOKEN "your-token-here"
    Or add HF_TOKEN to Windows User environment variables via System Properties.

Usage:
    py -3 build/scripts/upload_huggingface.py                           # dry run (default)
    py -3 build/scripts/upload_huggingface.py --live                    # full live upload
    py -3 build/scripts/upload_huggingface.py --live --readme-only      # README only

The script defaults to dry run. Pass --live to push files to HuggingFace.
Pass --readme-only to push only the dataset card (skips JSONL files and the
doc-numbers checklist -- useful for license, schema, or attribution updates).
Each file upload retries up to 3 times on transient failures (2s/4s/8s backoff).
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Derive project root from this script's location (build/scripts/ -> project root)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT_DIR = PROJECT_ROOT / "exports" / "huggingface"

# Live upload destination -- changing this points uploads at a different repo.
# Double-check before running with --live.
HF_REPO_ID = "OpenChristianDataOrg/open-christian-data"
HF_REPO_TYPE = "dataset"

LOG_FILE = Path(__file__).parent / "upload_huggingface.log"

# Files to upload (relative to EXPORT_DIR)
UPLOAD_GLOB = "*.jsonl"
UPLOAD_README = "README.md"

# Default to dry run (API-01: safe default for first-time runs)
DRY_RUN = True

# Retry config for transient upload failures (API-04)
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # seconds between attempts


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def collect_upload_files(readme_only=False):
    """Return list of (local_path, repo_path) tuples to upload.

    If readme_only is True, only the README.md is included.
    """
    files = []

    # README.md goes to the repo root
    readme = EXPORT_DIR / UPLOAD_README
    if readme.exists():
        files.append((readme, "README.md"))
    else:
        logging.warning("README.md not found at %s -- will be skipped", readme)

    if readme_only:
        return files

    # JSONL data files go into data/ subfolder in the repo
    for jsonl_path in sorted(EXPORT_DIR.glob(UPLOAD_GLOB)):
        repo_path = f"data/{jsonl_path.name}"
        files.append((jsonl_path, repo_path))

    return files


# ---------------------------------------------------------------------------
# Upload with retry (API-04)
# ---------------------------------------------------------------------------

def upload_with_retry(api, local_path, repo_path):
    """
    Attempt to upload a single file, retrying on transient failures.
    Returns True on success, False after all retries exhausted.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            api.upload_file(
                path_or_fileobj=str(local_path),
                path_in_repo=repo_path,
                repo_id=HF_REPO_ID,
                repo_type=HF_REPO_TYPE,
            )
            if attempt > 1:
                logging.info("  OK on attempt %d: %s", attempt, repo_path)
            else:
                logging.info("  OK: %s", repo_path)
            return True
        except Exception as e:
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAYS[attempt - 1]
                logging.warning(
                    "  Attempt %d failed for %s: %s -- retrying in %ds",
                    attempt, repo_path, e, delay,
                )
                time.sleep(delay)
            else:
                logging.error(
                    "  FAILED after %d attempts for %s: %s",
                    MAX_RETRIES, repo_path, e,
                )
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Upload OCD exports to HuggingFace dataset repo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Defaults to dry run. Pass --live to push files to HuggingFace.\n"
            "Requires HF_TOKEN environment variable (run: setx HF_TOKEN your-token)."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Push files to HuggingFace. Without this flag, the script is a dry run.",
    )
    parser.add_argument(
        "--readme-only",
        action="store_true",
        help="Upload only README.md (dataset card). Skips JSONL files and the doc-numbers checklist.",
    )
    return parser.parse_args()


def run():
    global DRY_RUN

    args = parse_args()

    # Override module-level DRY_RUN based on CLI flag
    if args.live:
        DRY_RUN = False

    readme_only = args.readme_only

    # Pre-publish gate: doc numbers must be verified before a full live upload.
    # Skipped for --readme-only since that flag is for non-data updates (license,
    # schema docs, attribution) where record counts haven't changed.
    if not DRY_RUN and not readme_only:
        print()
        print("=" * 76)
        print("PRE-PUBLISH CHECKLIST")
        print("=" * 76)
        print("Before uploading, confirm doc numbers have been reconciled against source.")
        print()
        print("  Prompt file:")
        print("    plans/2026-04-27-doc-numbers-reconciliation.md")
        print("  Section: 'OCD docs -- numbers reconciliation'")
        print()
        print("Run that prompt in Claude Code (from the repo root) to verify and patch")
        print("README.md, docs/HUGGINGFACE_DATASET_CARD.md, and docs/DATASET_PROJECT_STATE.md.")
        print()
        answer = input("Doc numbers reconciled? [y/N]: ").strip().lower()
        if answer != "y":
            print("Aborting. Run the reconciliation prompt first, then retry with --live.")
            sys.exit(0)
        print()

    setup_logging()

    if DRY_RUN:
        logging.info("DRY RUN -- no files will be uploaded (pass --live to upload)")
    else:
        logging.info("LIVE UPLOAD to %s", HF_REPO_ID)

    # Resolve HF_TOKEN (API-07: never log the token value)
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        logging.error(
            "HF_TOKEN environment variable is not set.\n"
            "  To set it in the current session: set HF_TOKEN=your-token-here\n"
            "  To set it permanently on Windows:  setx HF_TOKEN your-token-here\n"
            "  Or add HF_TOKEN via System Properties > Environment Variables."
        )
        sys.exit(1)

    # Collect upload plan
    upload_files = collect_upload_files(readme_only=readme_only)
    if not upload_files:
        logging.error("No files found in %s to upload.", EXPORT_DIR)
        sys.exit(1)

    # Print upload plan
    print()
    print("=" * 76)
    print(f"Upload plan: {HF_REPO_ID} ({HF_REPO_TYPE})")
    if DRY_RUN:
        print("  (DRY RUN -- pass --live to push)")
    print("=" * 76)
    print(f"{'Local file':<42}  {'Repo path':<22}  {'Size (KB)':>8}")
    print("-" * 76)
    total_size_kb = 0
    for local_path, repo_path in upload_files:
        size_kb = local_path.stat().st_size // 1024
        total_size_kb += size_kb
        print(f"{local_path.name:<42}  {repo_path:<22}  {size_kb:>8,}")
    print("-" * 76)
    print(f"{'TOTAL':<67}  {total_size_kb:>8,} KB")
    print()

    if DRY_RUN:
        print("DRY RUN complete -- nothing uploaded.")
        print("Run with --live to push to HuggingFace.")
        print("=" * 76)
        logging.info("Dry run complete. [DONE]")
        return

    # Live upload
    try:
        from huggingface_hub import HfApi
    except ImportError:
        logging.error(
            "huggingface_hub is not installed. "
            "Run: pip install huggingface_hub"
        )
        sys.exit(1)

    api = HfApi(token=hf_token)

    # Create the repo if it doesn't exist yet (safe to call on existing repos)
    try:
        api.create_repo(
            repo_id=HF_REPO_ID,
            repo_type=HF_REPO_TYPE,
            exist_ok=True,  # no-op if already exists
            private=False,
        )
        logging.info("Repo ready: %s", HF_REPO_ID)
    except Exception as e:
        logging.error("Failed to create/verify repo %s: %s", HF_REPO_ID, e)
        sys.exit(1)

    start = time.time()
    uploaded = 0
    errors = 0

    for local_path, repo_path in upload_files:
        logging.info("Uploading %s -> %s ...", local_path.name, repo_path)
        success = upload_with_retry(api, local_path, repo_path)
        if success:
            uploaded += 1
        else:
            errors += 1

    elapsed = time.time() - start

    # API-08: verify all files were uploaded successfully
    expected = len(upload_files)
    if uploaded != expected:
        logging.error(
            "Upload incomplete: %d of %d files uploaded successfully.",
            uploaded, expected,
        )

    print()
    print("=" * 76)
    print("Upload complete" if errors == 0 else "Upload finished with errors")
    print(f"  Uploaded : {uploaded} / {expected} files")
    print(f"  Errors   : {errors}")
    print(f"  Elapsed  : {elapsed:.1f}s")
    print(f"  Repo     : https://huggingface.co/datasets/{HF_REPO_ID}")
    print("=" * 76)

    if errors > 0 or uploaded != expected:
        logging.warning("Upload finished with errors -- %d/%d files uploaded.", uploaded, expected)
        sys.exit(1)
    else:
        logging.info("Upload complete. [DONE]")


if __name__ == "__main__":
    run()
