"""Deterministic public cards, private-content checks, and offline release previews.

The original prose-only allowlist remains available for the provisional tracer.
V2 publication previews use the verified release's exact configuration paths.
"""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache
import base64
import binascii
import hashlib
import json
import re
import stat
from urllib.parse import unquote

from ocd_kernel.library._common import PipelineError
from .streaming import file_sha256, iter_jsonl


ALLOWED_PUBLIC_FILES = frozenset({"README.md", "data/prose/train.jsonl"})


def public_files(root: Path) -> set[str]:
    if _is_link(root):
        raise PipelineError("public root cannot be a reparse point")
    if not root.is_dir():
        raise PipelineError(f"missing public release root: {root}")
    files = set()
    pending = [root]
    while pending:
        for path in pending.pop().iterdir():
            if _is_link(path):
                raise PipelineError("public tree cannot contain reparse points")
            if path.is_dir():
                pending.append(path)
            elif path.is_file():
                files.add(path.relative_to(root).as_posix())
            else:
                raise PipelineError("public tree contains a nonregular entry")
    return files


def check_public_allowlist(root: Path) -> list[str]:
    actual = public_files(root)
    errors: list[str] = []
    for path in sorted(actual - ALLOWED_PUBLIC_FILES):
        errors.append(f"public file is not allowlisted: {path}")
    for path in sorted(ALLOWED_PUBLIC_FILES - actual):
        # Empty configurations are not required; README is required, prose is
        # required only when at least one row is selected.  The checker handles
        # that conditional separately.
        if path == "README.md":
            errors.append(f"public file is missing: {path}")
    return errors


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _configurations(configurations: list[dict]) -> list[dict]:
    if not isinstance(configurations, list) or not configurations:
        raise PipelineError("public release requires nonempty configurations")
    seen = set()
    for config in configurations:
        category = config["category"]
        if (not isinstance(category, str) or not re.fullmatch(r"[a-z][a-z_]*", category)
                or category in seen or config["path"] != f"public/data/{category}/train.jsonl"
                or type(config["row_count"]) is not int or config["row_count"] <= 0):
            raise PipelineError("invalid public configuration")
        seen.add(category)
        if "typed_companion" in config:
            typed = config["typed_companion"]
            if (not isinstance(typed, dict) or set(typed) != {"path", "sha256"}
                    or typed["path"] != f"public/data/{category}/train.arrow"
                    or not isinstance(typed["sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", typed["sha256"])
                    or "features" not in config):
                raise PipelineError("invalid typed public configuration")
        if "typed_encoding" in config:
            from .typed_rows import BOUNDED_ENCODING, LEGACY_ENCODING
            if "typed_companion" not in config or config["typed_encoding"] not in {BOUNDED_ENCODING, LEGACY_ENCODING}:
                raise PipelineError("invalid typed encoding")
    return sorted(configurations, key=lambda config: config["category"])


def render_dataset_card(configurations: list[dict], *, notices: list[str] | None = None) -> str:
    """Render verified configuration facts and explicitly bound public notices."""
    configs = _configurations(configurations)
    lines = ["---", "pretty_name: Open Christian Data", "configs:"]
    for config in configs:
        reader_path = config.get("typed_companion", config)["path"]
        lines.extend([f"- config_name: {config['category']}", "  data_files:",
                      f"  - path: {reader_path.removeprefix('public/')}", "    split: train"])
    described = [config for config in configs if "features" in config]
    if described:
        lines.append("dataset_info:")
        for config in described:
            lines.extend([f"- config_name: {config['category']}",
                          "  features: " + json.dumps(config["features"], ensure_ascii=True, sort_keys=True)])
    lines.extend(["---", "", "# Open Christian Data", "",
                  "This staged dataset contains the configurations listed below. JSONL provides one record per line.",
                  "Typed Arrow companions, where listed, are the configured dataset-reader input and preserve literal strings without JSON type inference.",
                  "", "| Configuration | Split | Records | JSONL |", "| --- | --- | ---: | --- |"])
    for config in configs:
        path = config['path'].removeprefix('public/')
        lines.append(f"| {config['category']} | train | {config['row_count']} | [{path}]({path}) |")
    lines.extend(["", "Records preserve source wording within each category's documented projection limits.",
                  "Records labeled `content_format: ocd-native-content-v1` provide readable `text` alongside ordered, nested `structure`.",
                  "Native prose records follow top-level source units; their paragraphs, lists, and verse remain nested inside those units.",
                  "Native sermon records follow accepted source units; where present, `front_matter` retains introductory material on the first sermon record.",
                  "Within native structure, text leaves and element content stay in source order. Notes and page markers remain in structure but are omitted from readable text.",
                  "A successful technical check does not establish source completeness or rights clearance.",
                  "Licenses vary by record; use each record's `license` value and its source notice.",
                  "CC BY-SA terms and attribution apply to the licensed item and its adaptations, not automatically to unrelated records in this collection.", ""])
    card = "\n".join(lines)
    if notices:
        unique = sorted(set(notices))
        if any(notice != notice.strip("\n") + "\n" or not _safe_notice_markdown(notice)
               for notice in unique):
            raise PipelineError("public notice is not a safe verbatim Markdown block")
        card += "\n## Source notices\n\n" + "\n".join(unique)
    return card


_PRIVATE_KEYS = frozenset({"authority", "acceptance_path", "receipt_path", "source_path",
    "retained_path", "master_path", "local_path", "internal_state", "independent_check",
    "source_accounting", "review", "reviews", "receipt", "receipts"})
_PRIVATE_NORMALIZED_KEYS = frozenset(re.sub(r"[^a-z0-9]", "", key) for key in _PRIVATE_KEYS)
_LOCAL_PATH = re.compile(
    r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/]|\\\\[^\\\s]+\\|file://|"
    r"(?<![\w:/])/(?:home|users|tmp|mnt|var|opt)/|"
    r"(?<![\w:/])(?:raw|ir|library|internal|reports|exports|plans)[\\/][^\s]+)"
)
_TEI = re.compile(r"<(?:[\w.-]+:)?(?:TEI|teiHeader)(?:\s|/?>)")
_DIGEST = re.compile(r"(?i)\b[0-9a-f]{64}\b")


def _string_issue(value: str) -> str | None:
    candidates = (value, unquote(value)) if "%" in value else (value,)
    if any("urn:ocd:" in text.lower() for text in candidates):
        return "private source annotation in public content"
    if any((("/" in text or "\\" in text) and _LOCAL_PATH.search(text))
           or ("<" in text and _TEI.search(text))
           or (len(text) >= 64 and _DIGEST.search(text)) for text in candidates):
        return "private path, TEI, or digest in public content"
    return None


def _key_issues(key: str) -> tuple[str, ...]:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    issues = []
    if (normalized in _PRIVATE_NORMALIZED_KEYS or "sha256" in normalized
            or normalized.endswith(("hash", "hashes", "digest"))):
        issues.append("private field in public content")
    issue = _string_issue(key)
    if issue:
        issues.append(issue)
    return tuple(issues)


_cached_key_issues = lru_cache(maxsize=256)(_key_issues)


def _scan(value, location: str) -> list[str]:
    errors = []
    if isinstance(value, dict):
        for key, child in value.items():
            # Bound cached key bytes; arbitrary long keys still get every check.
            issues = _cached_key_issues(key) if len(key) <= 128 else _key_issues(key)
            errors.extend(f"{issue}: {location}" for issue in issues)
            errors.extend(_scan(child, location))
    elif isinstance(value, list):
        for child in value:
            errors.extend(_scan(child, location))
    elif isinstance(value, str):
        issue = _string_issue(value)
        if issue:
            errors.append(f"{issue}: {location}")
    return errors


def _safe_notice_markdown(value: str) -> bool:
    """Allow literal angle brackets only in closed plain-text fences."""
    if _scan(value, "public notice"):
        return False
    # Decode plausible base64 tokens before accepting a notice, including
    # tokens inside a literal license block. Other public scanners remain unchanged.
    for match in re.finditer(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/])", value):
        token = match.group()
        try:
            decoded = base64.b64decode(token + "=" * (-len(token) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeError):
            continue
        if _scan(decoded, "encoded public notice"):
            return False
    fenced = False
    for line in value.splitlines():
        if line == "```text":
            if fenced:
                return False
            fenced = True
        elif line == "```":
            if not fenced:
                return False
            fenced = False
        elif line.lstrip(" \t").startswith("```"):
            # Longer or indented backtick lines can close a Markdown fence.
            return False
        elif ("<" in line or ">" in line) and not fenced:
            return False
    return not fenced


def check_public_boundary(release: Path, report: dict, *, require_success: bool = True, notices: list[str] | None = None) -> list[str]:
    """Check the exact public tree and content; authority verification is separate."""
    try:
        if require_success and (report["status"] != "pass" or report["accounting"]["failed"]):
            raise PipelineError("release contains failed items")
        configs = _configurations(report["configurations"])
        root = Path(release) / "public"
        expected = {"README.md"} | {c["path"].removeprefix("public/") for c in configs}
        expected.update(c["typed_companion"]["path"].removeprefix("public/")
                        for c in configs if "typed_companion" in c)
        if public_files(root) != expected:
            raise PipelineError("public file set differs from allowlist")
        if (root / "README.md").read_bytes() != render_dataset_card(configs, notices=notices).encode("utf-8"):
            raise PipelineError("public dataset card differs from staged configurations")
        errors = []
        for config in configs:
            path = Path(release) / config["path"]
            count = 0
            for count, row in enumerate(iter_jsonl(path, canonical=True), start=1):
                errors.extend(_scan(row, f"{config['path']}/{count - 1}"))
            if count != config["row_count"] or file_sha256(path) != config["sha256"]:
                errors.append("public configuration count or digest differs")
            if "features" in config:
                from .features import configuration_features
                if config["features"] != configuration_features(iter_jsonl(path, canonical=True)):
                    errors.append("public configuration features differ from complete row schema")
            if "typed_companion" in config:
                from .typed_rows import check_rows_file, LEGACY_ENCODING
                typed = config["typed_companion"]
                typed_path = Path(release) / typed["path"]
                if file_sha256(typed_path) != typed["sha256"]:
                    errors.append("typed companion digest differs")
                try:
                    check_rows_file(typed_path, iter_jsonl(path, canonical=True), config["features"],
                                    encoding=config.get("typed_encoding", LEGACY_ENCODING))
                except PipelineError as exc:
                    errors.append(str(exc))
        return errors
    except (PipelineError, OSError, ValueError, TypeError, KeyError) as exc:
        return [f"public boundary failed: {exc}"]


def preview_release(root: Path, release: Path, *, selection: dict) -> dict:
    """Read-only upload manifest. This function has no network or upload path."""
    from .verify import verify_release_v2
    from ocd_kernel.library._common import load_json

    result = {"status": "fail", "errors": [], "files": [], "upload_performed": False,
              "publication_authorized": False,
              "future_handoff_requirements": [
                  "Confirm rights and required attribution for the selected release.",
                  "Obtain explicit publication authorization.",
                  "Read a fresh remote revision and exact file/digest baseline; reconcile live/local differences.",
                  "Recheck this local manifest immediately before upload.",
                  "After upload, verify the exact remote revision, file set, and file digests."]}
    try:
        check = verify_release_v2(root, release, selection=selection)
        if check["status"] != "pass":
            result["errors"] = check["errors"]
            return result
        from .build_state import MANIFEST, check_ready
        profile_build = (Path(release) / MANIFEST).exists()
        if profile_build:
            check_ready(Path(release))
        report = load_json(Path(release) / "internal/release-report.json")
        from .selection import validate_release_selection
        from .notices import selected_notice_texts
        request = validate_release_selection(selection)
        notices = selected_notice_texts(Path(root).resolve(strict=True), request["items"], report["items"])
        errors = check_public_boundary(release, report, notices=notices)
        if errors:
            result["errors"] = errors
            return result
        public = Path(release) / "public"
        expected_digests = {c["path"].removeprefix("public/"): c["sha256"]
                            for c in report["configurations"]}
        expected_digests.update({c["typed_companion"]["path"].removeprefix("public/"):
                                c["typed_companion"]["sha256"]
                                for c in report["configurations"] if "typed_companion" in c})
        expected_digests["README.md"] = hashlib.sha256(
            render_dataset_card(report["configurations"], notices=notices).encode("utf-8")).hexdigest()
        files = []
        for relative in sorted(public_files(public)):
            path = public / relative
            digest = file_sha256(path)
            if digest != expected_digests.get(relative):
                raise PipelineError("public content changed during preview")
            files.append({"path": relative, "size_bytes": path.stat().st_size,
                          "sha256": digest})
        if {entry["path"] for entry in files} != set(expected_digests):
            raise PipelineError("public file set changed during preview")
        if profile_build:
            check_ready(Path(release))
        result.update(status="pass", files=files)
    except (PipelineError, OSError, ValueError, TypeError, KeyError) as exc:
        result["errors"] = [f"offline preview failed: {exc}"]
    return result
