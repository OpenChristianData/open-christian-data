"""Publish an already verified v2 release with an exact Hub revision guard.

The default invocation is an offline preview. Live publication requires the
operator to name the current Hub commit and the exact dataset repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from ocd_kernel.library._common import PipelineError, canonical_bytes, load_json, sha256_file
from ocd_kernel.release.public_allowlist import _scan, preview_release, public_files
from ocd_kernel.release.selection import load_release_selection


REPO_ID = "OpenChristianDataOrg/open-christian-data"
REPO_TYPE = "dataset"
_SHA = re.compile(r"[0-9a-f]{40}")
_HUB_METADATA = frozenset({".gitattributes"})
_LEGACY_FILES = frozenset(f"data/{name}.jsonl" for name in (
    "bible_text", "catechism_qa", "church_fathers", "commentary", "devotional",
    "doctrinal_document", "hymn_collection", "prayer", "reference_entry",
    "sermon", "structured_text", "topical_reference",
))


class UploadError(ValueError):
    """A publication precondition or postcondition failed."""


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise UploadError(f"{label} must be a full 40-character commit SHA")
    return value


def _verified_preview(root: Path, release: Path, selection: dict,
                      path: Path, expected_sha256: str) -> dict:
    """Reuse an operator-pinned proof only while its entire package is unchanged."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or sha256_file(path) != expected_sha256:
        raise UploadError("verified manifest differs from operator-pinned digest")
    manifest = load_json(path)
    if (manifest.get("contract") != "ocd-verified-hf-upload-manifest-v1"
            or manifest.get("status") != "pass"
            or manifest.get("selection_sha256") != _digest(canonical_bytes(selection))):
        raise UploadError("verified manifest selection or contract differs")
    evidence = manifest.get("verification_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise UploadError("verified manifest has no bound verification evidence")
    for entry in evidence:
        relative = entry["path"]
        if (not isinstance(relative, str) or relative.startswith("/") or "\\" in relative
                or ":" in relative or any(p in ("", ".", "..") for p in relative.split("/"))
                or sha256_file(root / relative) != entry["sha256"]):
            raise UploadError("bound verification evidence changed")
    release = release.resolve(strict=True)
    tree = {name: sha256_file(release / name) for name in sorted(public_files(release))}
    if _digest(canonical_bytes(tree)) != manifest.get("release_tree_sha256"):
        raise UploadError("verified release tree changed")
    actual = [{"path": name.removeprefix("public/"),
               "size_bytes": (release / name).stat().st_size, "sha256": digest}
              for name, digest in tree.items() if name.startswith("public/")]
    if actual != manifest.get("files"):
        raise UploadError("verified public manifest differs from package")
    return {"status": "pass", "errors": [], "files": actual,
            "verification_basis": "operator-pinned completed verification and unchanged package",
            "verified_manifest_sha256": expected_sha256, "upload_performed": False}


def _local_payload(root: Path, release: Path, selection: dict, *,
                   verified_manifest: Path | None = None, manifest_sha256: str | None = None,
                   card: Path | None = None, card_sha256: str | None = None,
                   publication_docs: Path | None = None, publication_docs_sha256: str | None = None) -> tuple[dict, dict[str, Path | bytes]]:
    if bool(verified_manifest) != bool(manifest_sha256) or bool(card) != bool(card_sha256):
        raise UploadError("manifest and card each require their operator-pinned digest")
    if bool(publication_docs) != bool(publication_docs_sha256):
        raise UploadError("publication documents require their operator-pinned digest")
    if publication_docs and (card or not verified_manifest):
        raise UploadError("publication documents require a pinned data proof and replace the card option")
    preview = (_verified_preview(root, release, selection, verified_manifest, manifest_sha256)
               if verified_manifest else preview_release(root, release, selection=selection))
    if preview["status"] != "pass":
        raise UploadError("v2 release preview failed: " + "; ".join(preview["errors"]))
    payload: dict[str, Path | bytes] = {}
    for item in preview["files"]:
        relative = item["path"]
        content = release / "public" / relative
        if content.stat().st_size != item["size_bytes"] or sha256_file(content) != item["sha256"]:
            raise UploadError(f"public file changed after validation: {relative}")
        payload[relative] = content
    if len(payload) != len(preview["files"]):
        raise UploadError("public file list has duplicate paths")
    if card:
        replacement = card.read_bytes()
        if _digest(replacement) != card_sha256:
            raise UploadError("release card differs from operator-pinned digest")
        original = (release / "public/README.md").read_text(encoding="utf-8")
        text = replacement.decode("utf-8")
        before = original.split("\n---\n", 1)[0]
        after = text.split("\n---\n", 1)[0]
        # The editorial title can change; all generated reader metadata stays exact.
        normalize_title = lambda value: re.sub(r"(?m)^pretty_name: .*", "pretty_name: Open Christian Data", value)
        notices = original[original.index("## Source notices"):] if "## Source notices" in original else ""
        if normalize_title(before) != normalize_title(after) or (notices and not text.endswith(notices)) or _scan(text, "release card"):
            raise UploadError("release card changed reader metadata, notices, or privacy boundary")
        payload["README.md"] = replacement
        preview["files"] = [dict(item, size_bytes=len(replacement), sha256=_digest(replacement))
                            if item["path"] == "README.md" else item for item in preview["files"]]
        preview["card_sha256"] = card_sha256
    if publication_docs:
        from build.tools.prepare_hf_publication_docs import check_documents, DocumentError

        try:
            documents = check_documents(root, release, selection, publication_docs, publication_docs_sha256)
        except (DocumentError, OSError, ValueError, KeyError, TypeError) as exc:
            raise UploadError(f"publication documents failed: {exc}") from exc
        payload.update(documents)
        files = {item["path"]: item for item in preview["files"]}
        files.update({path: {"path": path, "size_bytes": len(content), "sha256": _digest(content)}
                      for path, content in documents.items()})
        preview["files"] = [files[path] for path in sorted(files)]
        preview["publication_documents_sha256"] = publication_docs_sha256
    return preview, payload


def _head(api: Any) -> str:
    info = api.repo_info(repo_id=REPO_ID, repo_type=REPO_TYPE, revision="main")
    return _sha(info.sha, "remote main revision")


def _tree(api: Any, revision: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for entry in api.list_repo_tree(
        REPO_ID, recursive=True, revision=revision, repo_type=REPO_TYPE
    ):
        size = getattr(entry, "size", None)
        if size is None:  # RepoFolder
            continue
        path = getattr(entry, "path", None)
        if (not isinstance(path, str) or not path or path.startswith("/")
                or "\\" in path or any(part in ("", ".", "..") for part in path.split("/"))
                or type(size) is not int or size < 0 or path in result):
            raise UploadError("remote tree contains an invalid or duplicate file entry")
        result[path] = size
    return result


def _remote_digest(api: Any, path: str, revision: str) -> str:
    local = Path(api.hf_hub_download(
        REPO_ID, path, repo_type=REPO_TYPE, revision=revision
    ))
    digest = hashlib.sha256()
    with local.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _receipt_path(path: Path, release: Path) -> Path:
    resolved = path.resolve(strict=False)
    release_root = release.resolve(strict=True)
    if resolved.is_relative_to(release_root):
        raise UploadError("receipt cannot be written inside the release")
    if path.exists() or not path.parent.is_dir():
        raise UploadError("receipt path must be fresh and its parent must exist")
    return path


def _write_receipt(path: Path, receipt: dict, *, initial: bool = False) -> None:
    content = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if initial:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def upload_release(
    root: Path, release: Path, selection: dict, *, api: Any,
    expected_revision: str, confirm_repo: str, receipt_path: Path,
    operation_add: Any,
    operation_delete: Any = None, replace_legacy: bool = False,
    verified_manifest: Path | None = None, manifest_sha256: str | None = None,
    card: Path | None = None, card_sha256: str | None = None,
    publication_docs: Path | None = None, publication_docs_sha256: str | None = None,
) -> dict:
    """Upload one guarded commit, then check the complete remote public tree."""
    expected_revision = _sha(expected_revision, "expected revision")
    if confirm_repo != REPO_ID:
        raise UploadError(f"confirm_repo must exactly equal {REPO_ID}")
    receipt_path = _receipt_path(receipt_path, release)
    preview, payload = _local_payload(root, release, selection,
        verified_manifest=verified_manifest, manifest_sha256=manifest_sha256,
        card=card, card_sha256=card_sha256,
        publication_docs=publication_docs, publication_docs_sha256=publication_docs_sha256)
    expected = {item["path"]: item for item in preview["files"]}
    baseline = _head(api)
    if baseline != expected_revision:
        raise UploadError(f"remote revision changed: expected {expected_revision}, found {baseline}")
    baseline_tree = _tree(api, baseline)
    extras = set(baseline_tree) - set(expected) - _HUB_METADATA
    if extras and not (replace_legacy and operation_delete and extras == _LEGACY_FILES):
        raise UploadError("remote contains files outside the exact v2 release: " + ", ".join(sorted(extras)))
    metadata = {
        path: {"size_bytes": baseline_tree[path], "sha256": _remote_digest(api, path, baseline)}
        for path in sorted(set(baseline_tree) & _HUB_METADATA)
    }
    if _head(api) != baseline:
        raise UploadError("remote revision changed while reading the baseline")
    receipt: dict[str, Any] = {
        "contract": "ocd-hf-v2-upload-receipt-v1",
        "repo_id": REPO_ID, "repo_type": REPO_TYPE,
        "status": "baseline-checked", "upload_performed": False,
        "baseline_revision": baseline,
        "baseline_files": [{"path": path, "size_bytes": size}
                           for path, size in sorted(baseline_tree.items())],
        "expected_files": [expected[path] for path in sorted(expected)],
        "preserved_hub_metadata": metadata,
        "removed_legacy_files": sorted(extras),
        "local_verification": {key: preview[key] for key in
            ("verification_basis", "verified_manifest_sha256", "card_sha256", "publication_documents_sha256") if key in preview},
    }
    _write_receipt(receipt_path, receipt, initial=True)
    # A second live check narrows the interval before the conditional commit.
    if _head(api) != baseline:
        receipt["status"] = "remote-changed-before-commit"
        _write_receipt(receipt_path, receipt)
        raise UploadError("remote revision changed before commit")
    operations = [operation_add(path_in_repo=path, path_or_fileobj=payload[path])
                  for path in sorted(payload)]
    operations.extend(operation_delete(path_in_repo=path) for path in sorted(extras))
    # Once the request is about to leave this process, a crash or transport
    # error can no longer prove that the remote stayed unchanged.
    receipt.update(status="commit-attempted", upload_performed=None)
    _write_receipt(receipt_path, receipt)
    try:
        commit = api.create_commit(
            repo_id=REPO_ID, repo_type=REPO_TYPE, revision="main",
            parent_commit=baseline, operations=operations,
            commit_message="Publish Open Christian Data v1.0.0 - The De-slop release" if card else "Publish verified OCD v2 release",
        )
        revision = _sha(commit.oid, "created commit revision")
    except Exception:
        # A transport failure can occur after the server has committed. Never
        # retry automatically or claim that the remote is unchanged. This
        # includes a malformed success response with no verifiable revision.
        receipt["status"] = "commit-outcome-unknown"
        receipt["upload_performed"] = None
        _write_receipt(receipt_path, receipt)
        raise
    receipt.update(status="post-upload-verification", upload_performed=True,
                   commit_revision=revision)
    _write_receipt(receipt_path, receipt)
    try:
        if _head(api) != revision:
            raise UploadError("remote main revision differs from created commit")
        remote_tree = _tree(api, revision)
        expected_paths = set(expected) | set(metadata)
        if set(remote_tree) != expected_paths:
            raise UploadError("post-upload remote file set differs from the exact allowlist")
        for path, item in expected.items():
            if remote_tree[path] != item["size_bytes"] or _remote_digest(api, path, revision) != item["sha256"]:
                raise UploadError(f"post-upload remote size or digest differs: {path}")
        for path, item in metadata.items():
            if remote_tree[path] != item["size_bytes"] or _remote_digest(api, path, revision) != item["sha256"]:
                raise UploadError(f"Hub metadata changed during publication: {path}")
        if _head(api) != revision:
            raise UploadError("remote main revision changed during verification")
    except Exception as exc:
        receipt["status"] = "post-upload-verification-failed"
        receipt["error"] = str(exc)
        _write_receipt(receipt_path, receipt)
        raise
    receipt["status"] = "pass"
    receipt["verified_revision"] = revision
    receipt["verified_files"] = [expected[path] for path in sorted(expected)]
    _write_receipt(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="Publish one guarded commit")
    parser.add_argument("--expected-revision", help="Fresh, full current Hub main SHA")
    parser.add_argument("--confirm-repo", help="Exact dataset repository identifier")
    parser.add_argument("--receipt", type=Path, help="Fresh private receipt path, required for live mode")
    parser.add_argument("--verified-manifest", type=Path, help="Reuse completed verification with an exact package digest")
    parser.add_argument("--manifest-sha256", help="Operator-pinned verified-manifest digest")
    parser.add_argument("--publication-docs", type=Path, help="Pinned public-document delivery manifest over unchanged data")
    parser.add_argument("--publication-docs-sha256", help="Operator-pinned publication-document manifest digest")
    parser.add_argument("--card", type=Path, help="Reviewed editorial card preserving generated metadata and notices")
    parser.add_argument("--card-sha256", help="Operator-pinned editorial-card digest")
    parser.add_argument("--replace-legacy", action="store_true", help="Replace only the exact twelve legacy data paths")
    args = parser.parse_args(argv)
    if args.live and (not args.expected_revision or not args.confirm_repo or not args.receipt):
        parser.error("--live requires --expected-revision, --confirm-repo, and --receipt")
    if not args.live and any((args.expected_revision, args.confirm_repo, args.receipt)):
        parser.error("live-only arguments require --live")
    receipt_was_present = bool(args.receipt and args.receipt.exists())
    try:
        selection = load_release_selection(args.selection)
        if args.live:
            from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi
            result = upload_release(
                args.root, args.release, selection, api=HfApi(),
                expected_revision=args.expected_revision, confirm_repo=args.confirm_repo,
                receipt_path=args.receipt, operation_add=CommitOperationAdd,
                operation_delete=CommitOperationDelete, replace_legacy=args.replace_legacy,
                verified_manifest=args.verified_manifest, manifest_sha256=args.manifest_sha256,
                card=args.card, card_sha256=args.card_sha256,
                publication_docs=args.publication_docs, publication_docs_sha256=args.publication_docs_sha256,
            )
        else:
            if any((args.verified_manifest, args.manifest_sha256, args.card, args.card_sha256, args.publication_docs, args.publication_docs_sha256)):
                result, _ = _local_payload(args.root, args.release, selection,
                    verified_manifest=args.verified_manifest, manifest_sha256=args.manifest_sha256,
                    card=args.card, card_sha256=args.card_sha256,
                    publication_docs=args.publication_docs, publication_docs_sha256=args.publication_docs_sha256)
            else:
                result = preview_release(args.root, args.release, selection=selection)
    except (PipelineError, OSError, ValueError, ImportError) as exc:
        result = {"status": "fail", "errors": [str(exc)], "upload_performed": False}
        if args.live and args.receipt and not receipt_was_present and args.receipt.is_file():
            try:
                saved = json.loads(args.receipt.read_text(encoding="utf-8"))
                if saved.get("contract") == "ocd-hf-v2-upload-receipt-v1":
                    result["upload_performed"] = saved.get("upload_performed")
                    result["receipt_status"] = saved.get("status")
                    result["receipt_path"] = str(args.receipt)
            except (OSError, ValueError):
                result["receipt_status"] = "unreadable"
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
