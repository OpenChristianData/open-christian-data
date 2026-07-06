"""pre_commit_pytest.py -- OCD pre-commit helper: scoped pytest for staged build/ files.

Runs pytest ONLY on test files matched to staged build/ Python files.
Does NOT run the full suite -- that is intentional to keep commit speed fast.

Mapping rules:
  staged build/parsers/foo.py  -> tests/test_foo.py (repo root)
                               -> build/parsers/tests/test_foo.py (sibling)
  staged build/tools/bar/baz.py -> tests/test_baz.py (repo root)
                                -> build/tools/bar/tests/test_baz.py (sibling)
  schema/, data/, docs/, *.json, *.md  -> skipped (no tests to run)

Speed budget: warns if matched test count exceeds 50, but always proceeds.
Exit code 0 = pass or no applicable tests; exit 1 = test failure.

Usage (from .githooks/pre-commit):
    py -3 build/tools/pre_commit_pytest.py

Selftest:
    py -3 build/tools/pre_commit_pytest.py --selftest
"""
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAX_TESTS_WARN = 50


def _get_staged_build_py_files():
    """Return list of staged .py files under build/ (relative paths from repo root)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=REPO_ROOT,
            check=True,
        )
    except subprocess.CalledProcessError:
        return []
    files = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("build/") and line.endswith(".py"):
            files.append(line)
    return files


def _derive_test_paths(staged_file):
    """Given a staged build/ file (relative to repo root), return candidate test paths."""
    basename = os.path.basename(staged_file)         # e.g. ccel_puritan_works.py
    name = os.path.splitext(basename)[0]             # e.g. ccel_puritan_works
    test_name = "test_" + name + ".py"               # e.g. test_ccel_puritan_works.py
    source_dir = os.path.dirname(staged_file)        # e.g. build/parsers

    # Use forward slashes for consistent cross-platform relative paths
    return [
        "tests/" + test_name,                        # tests/test_ccel_puritan_works.py (repo root)
        source_dir + "/tests/" + test_name,          # build/parsers/tests/test_ccel_puritan_works.py
    ]


def _find_existing_tests(staged_files):
    """Return list of test file paths (relative to repo root) that exist on disk."""
    found = []
    seen = set()
    for f in staged_files:
        for candidate in _derive_test_paths(f):
            if candidate in seen:
                continue
            seen.add(candidate)
            if os.path.isfile(os.path.join(REPO_ROOT, candidate)):
                found.append(candidate)
    return found


def _run_pytest(test_files):
    """Run pytest -q on the given test files. Returns pytest exit code."""
    if len(test_files) > MAX_TESTS_WARN:
        print(
            f"[pre-commit pytest] Warning: {len(test_files)} test file(s) matched "
            f"(> {MAX_TESTS_WARN} threshold), proceeding anyway."
        )
    cmd = ["py", "-3", "-m", "pytest", "-q"] + test_files
    try:
        result = subprocess.run(cmd, cwd=REPO_ROOT, check=True)
        return result.returncode
    except subprocess.CalledProcessError as e:
        return e.returncode


def _selftest():
    """Verify path-derivation and filter logic. Exit 1 on failure."""
    failures = []

    # _derive_test_paths: check both repo-root and sibling-dir candidates
    cases = [
        (
            "build/parsers/ccel_puritan_works.py",
            ["tests/test_ccel_puritan_works.py", "build/parsers/tests/test_ccel_puritan_works.py"],
        ),
        (
            "build/tools/bar/baz.py",
            ["tests/test_baz.py", "build/tools/bar/tests/test_baz.py"],
        ),
    ]
    for staged, expected in cases:
        result = _derive_test_paths(staged)
        if result != expected:
            failures.append(
                f"FAIL _derive_test_paths({staged!r}): got {result}, expected {expected}"
            )
        else:
            print(f"  PASS _derive_test_paths: {staged!r} -> {result}")

    # Filter: only build/ .py files kept; non-build and non-.py excluded
    mixed = [
        "build/parsers/foo.py",   # keep
        "data/records.json",       # skip -- not build/
        "tests/test_other.py",     # skip -- not build/
        "schema/prayers.json",     # skip -- not .py
    ]
    build_py = [f for f in mixed if f.startswith("build/") and f.endswith(".py")]
    if build_py != ["build/parsers/foo.py"]:
        failures.append(f"FAIL filter: got {build_py}")
    else:
        print("  PASS filter: only build/ .py files kept")

    # _find_existing_tests TP: real file known to exist in this repo
    tp_staged = ["build/parsers/ccel_puritan_works.py"]
    tp_found = _find_existing_tests(tp_staged)
    if not tp_found:
        failures.append(
            "FAIL _find_existing_tests TP: expected tests/test_ccel_puritan_works.py to exist"
        )
    elif tp_found != ["tests/test_ccel_puritan_works.py"]:
        failures.append(f"FAIL _find_existing_tests TP: unexpected result {tp_found}")
    else:
        print(f"  PASS _find_existing_tests TP: {tp_found}")

    # _find_existing_tests TN: fictional parser that has no test file
    tn_staged = ["build/parsers/nonexistent_xyz_parser_abc.py"]
    tn_found = _find_existing_tests(tn_staged)
    if tn_found:
        failures.append(f"FAIL _find_existing_tests TN: expected no tests, got {tn_found}")
    else:
        print("  PASS _find_existing_tests TN: no tests found for nonexistent file")

    if failures:
        for f in failures:
            print(f, file=sys.stderr)
        sys.exit(1)
    print("Selftest passed.")
    sys.exit(0)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        _selftest()

    staged_files = _get_staged_build_py_files()
    if not staged_files:
        sys.exit(0)  # nothing staged in build/ -- skip

    test_files = _find_existing_tests(staged_files)
    if not test_files:
        sys.exit(0)  # no test files found -- skip silently

    print(f"[pre-commit pytest] Found {len(test_files)} test file(s): {', '.join(test_files)}")
    rc = _run_pytest(test_files)
    if rc != 0:
        print(f"[pre-commit pytest] Tests FAILED (exit {rc}). Fix before committing.")
        sys.exit(rc)

    print("[pre-commit pytest] All tests passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
