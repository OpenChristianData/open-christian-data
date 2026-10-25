"""Resolve explicitly selected, source-bound public attribution notices."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import stat
from typing import Mapping

from ocd_kernel.library._common import PipelineError, load_json
from .public_allowlist import _safe_notice_markdown


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _bound_file(root: Path, relative: str, digest: str, *, label: str) -> bytes:
    parts = PurePosixPath(relative).parts
    path = root
    for part in parts:
        path = path / part
        if _is_reparse(path):
            raise PipelineError(f"{label} crosses a reparse point: {relative}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        content = resolved.read_bytes()
    except (OSError, RuntimeError, ValueError) as exc:
        raise PipelineError(f"{label} is unavailable inside release root: {relative}") from exc
    if hashlib.sha256(content).hexdigest() != digest:
        raise PipelineError(f"{label} SHA-256 mismatch: {relative}")
    return content


def _utf8_markdown(content: bytes, *, label: str) -> str:
    if not content or len(content) > 65536:
        raise PipelineError(f"{label} must be a nonempty bounded Markdown file")
    try:
        value = content.decode("utf-8")
    except UnicodeError as exc:
        raise PipelineError(f"{label} is not UTF-8") from exc
    if value.startswith("\ufeff") or "\r" in value or "\x00" in value or not value.endswith("\n"):
        raise PipelineError(f"{label} requires LF-only UTF-8 Markdown ending in newline")
    return value


def notice_texts_for_item(root: Path, selected: Mapping, acceptance_path: Path) -> list[str]:
    """Read only explicitly bound notices for one included/warned selection item."""
    bindings = selected.get("public_notices", [])
    if not bindings:
        return []
    if "exclude_reason" in selected:
        raise PipelineError("excluded release item cannot bind public notices")
    root = Path(root).resolve(strict=True)
    identity = load_json(acceptance_path).get("identity")
    work_id = identity.get("work_id") if isinstance(identity, dict) else None
    if not isinstance(work_id, str) or selected.get("work_id", work_id) != work_id:
        raise PipelineError("notice item does not match accepted work identity")
    result = []
    for binding in bindings:
        source_path = binding["source_path"]
        notice_path = binding["notice_path"]
        source_parts = PurePosixPath(source_path).parts
        notice_parts = PurePosixPath(notice_path).parts
        if (len(source_parts) < 4 or source_parts[0] != "sources"
                or source_parts[-2:] != (work_id, "README.source.md")
                or len(notice_parts) < 3 or notice_parts[0] != "data"
                or notice_parts[-1] != "README.md"):
            raise PipelineError("public notice path is not source-bound to this work and a data README")
        source_note = _utf8_markdown(_bound_file(
            root, source_path, binding["source_sha256"], label="source notice"
        ), label="source notice")
        if f"`{notice_path}`" not in source_note:
            raise PipelineError("source notice does not explicitly direct to the selected data README")
        notice = _utf8_markdown(_bound_file(
            root, notice_path, binding["notice_sha256"], label="public notice"
        ), label="public notice")
        if not _safe_notice_markdown(notice):
            raise PipelineError("public notice contains private path, digest, TEI, or HTML")
        result.append(notice)
    return result


def selected_notice_texts(root: Path, requested_items: list[dict], actual_items: list[dict]) -> list[str]:
    """Recompute release notices from the original selection and item statuses."""
    from .selection import resolve_acceptance_path

    if len(requested_items) != len(actual_items):
        raise PipelineError("notice accounting item count differs")
    texts = []
    for selected, item in zip(requested_items, actual_items, strict=True):
        if selected["item_id"] != item["item_id"]:
            raise PipelineError("notice accounting item identity differs")
        if item["status"] in {"included", "warned"}:
            acceptance = resolve_acceptance_path(root, selected["acceptance_path"])
            texts.extend(notice_texts_for_item(root, selected, acceptance))
    return sorted(set(texts))
