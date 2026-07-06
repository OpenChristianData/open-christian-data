"""Check a public checkout for obvious private identity markers.

This script is intentionally public-safe. Keep sensitive terms constructed from
parts so the scanner does not report its own source as a hit.
"""

from __future__ import annotations

import re
import subprocess
import sys
from argparse import ArgumentParser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LITERALS = [
    "C:" + "\\Users\\" + "".join(["Rob", "bie"]),
    "Based" + "GPT",
    "-".join(["github", "".join(["bas", "ed", "gpt"])]),
]
WORDS = ["Co" + "work"]
FILENAME_DENYLIST = [
    "AGENTS.md",
    "CLAUDE",
    "LAST_SESSION",
    "PIPELINE_REFERENCE.md",
    "PROJECT_",
    ".agents/",
    ".claude/",
    ".codex/",
    ".context/",
    ".gbrain",
    ".githooks/",
    ".gstack/",
    ".playwright-mcp/",
    "plans/",
    "prompts/",
    "secrets/",
    "tests/local_artifacts/",
]


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def word_pattern(word: str) -> str:
    return rf"(?<![A-Za-z0-9_-]){re.escape(word)}(?![A-Za-z0-9_-])"


def tracked_paths(tree: str) -> list[str]:
    if tree == "HEAD":
        return [path for path in run_git(["ls-files", "-z"]).split("\0") if path]
    return [path for path in run_git(["ls-tree", "-r", "--name-only", "-z", tree]).split("\0") if path]


def filename_hits(paths: list[str]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        path_lower = path.lower()
        for denied in FILENAME_DENYLIST:
            if path_lower == denied.lower().rstrip("/") or path_lower.startswith(denied.lower()):
                hits.append(f"{path}: forbidden public path")
        for literal in LITERALS:
            if literal.lower() in path_lower:
                hits.append(f"{path}: filename contains blocked literal")
        for word in WORDS:
            if re.search(word_pattern(word), path, re.IGNORECASE):
                hits.append(f"{path}: filename contains blocked word")
    return hits


def grep_hits(tree: str) -> list[str]:
    hits: list[str] = []
    for literal in LITERALS:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "grep", "-I", "-n", "-i", "--fixed-strings", literal, tree, "--"],
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0:
            hits.extend(result.stdout.splitlines())
        elif result.returncode != 1:
            raise RuntimeError(result.stderr.strip())
    for word in WORDS:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "grep", "-I", "-n", "-i", "-P", word_pattern(word), tree, "--"],
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0:
            hits.extend(result.stdout.splitlines())
        elif result.returncode != 1:
            raise RuntimeError(result.stderr.strip())
    return hits


def main() -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--tree", default="HEAD", help="Git tree-ish to scan; defaults to HEAD.")
    args = parser.parse_args()
    hits = [*filename_hits(tracked_paths(args.tree)), *grep_hits(args.tree)]
    if hits:
        print("Public identity scan failed:", file=sys.stderr)
        for hit in hits[:200]:
            print(hit, file=sys.stderr)
        if len(hits) > 200:
            print(f"... {len(hits) - 200} more hits omitted", file=sys.stderr)
        return 1
    print("Public identity scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
