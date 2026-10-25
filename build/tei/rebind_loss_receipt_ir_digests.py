"""Governed rebind of loss-receipt IR digests to canonical Git-blob bytes."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

from lxml import etree

from build.lib.paths import REPO_ROOT
from ocd_kernel.lib.git_artifact import (
    CanonicalGitArtifactError,
    committed_artifact,
    committed_artifact_candidate,
    repository_lexical_path,
    repository_revision,
)


class ReceiptRebindError(ValueError):
    """Raised when a receipt pair cannot prove a metadata-only rebind."""


@dataclass(frozen=True, slots=True)
class ReceiptRebindPlan:
    receipt_path: Path
    receipt_repository_path: str
    ir_repository_path: str
    output_repository_path: str
    old_stored_ir_sha256: str
    current_stored_ir_sha256: str
    canonical_ir_sha256: str
    checkout_ir_sha256: str
    canonical_output_sha256: str
    checkout_output_sha256: str
    stored_output_sha256: str
    ir_blob_oid: str
    output_blob_oid: str
    canonical_ir_byte_count: int
    checkout_ir_byte_count: int
    pure_eol_normalization: bool
    xml_c14n_equal: bool
    output_json_semantics_equal: bool
    receipt_checkout_sha256: str

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["receipt_path"] = self.receipt_repository_path
        return record


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _resolve_repository_path(root: Path, relative: str) -> Path:
    try:
        return repository_lexical_path(root / relative, repository_root=root)
    except CanonicalGitArtifactError as error:
        raise ReceiptRebindError(
            f"receipt path escapes repository root: {relative}"
        ) from error


def _xml_c14n(content: bytes) -> bytes:
    try:
        root = etree.fromstring(
            content,
            parser=etree.XMLParser(resolve_entities=False, no_network=True),
        )
    except etree.XMLSyntaxError as error:
        raise ReceiptRebindError(f"IR is not valid XML: {error}") from error
    return etree.tostring(root, method="c14n")


def _jsonl_semantics(content: bytes) -> list[Any]:
    try:
        text = content.decode("utf-8", errors="strict")
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReceiptRebindError(f"output is not valid UTF-8 JSONL: {error}") from error


def _tracked_receipts(root: Path, revision: str) -> tuple[Path, ...]:
    try:
        completed = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", revision],
            check=True,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReceiptRebindError("could not enumerate committed receipts") from error
    return tuple(
        root / line
        for line in completed.stdout.splitlines()
        if line.endswith(".loss.json")
    )


def _committed_receipt_bytes(root: Path, commit: str, relative: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "show", f"{commit}:{relative}"],
            check=True,
            cwd=root,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReceiptRebindError(
            f"could not read committed receipt: {relative}"
        ) from error


def plan_receipt_rebinds(
    repository_root: Path = REPO_ROOT,
    *,
    revision: str = "HEAD",
    receipt_paths: Iterable[Path] | None = None,
    expected_count: int = 15,
) -> tuple[ReceiptRebindPlan, ...]:
    """Prove and plan exact receipt-only IR digest updates."""

    root = Path(repository_root).resolve(strict=True)
    commit = repository_revision(root, revision)
    selected = tuple(receipt_paths or _tracked_receipts(root, commit))
    if len(selected) != expected_count:
        raise ReceiptRebindError(
            f"expected {expected_count} receipts, found {len(selected)}"
        )

    plans: list[ReceiptRebindPlan] = []
    for receipt_path in selected:
        try:
            receipt_target = repository_lexical_path(
                Path(receipt_path),
                repository_root=root,
            )
            receipt_artifact = committed_artifact_candidate(
                receipt_target,
                repository_root=root,
                revision=commit,
            )
        except CanonicalGitArtifactError as error:
            raise ReceiptRebindError(str(error)) from error
        receipt_repository_path = receipt_artifact.repository_relative_path
        try:
            committed_receipt = json.loads(receipt_artifact.canonical_bytes)
            current_receipt_bytes = receipt_artifact.checkout_bytes
            current_receipt = json.loads(current_receipt_bytes)
            ir_repository_path = committed_receipt["ir"]["path"]
            output_repository_path = committed_receipt["output"]["path"]
            old_stored_ir_sha256 = committed_receipt["ir"]["sha256"]
            current_stored_ir_sha256 = current_receipt["ir"]["sha256"]
            stored_output_sha256 = committed_receipt["output"]["sha256"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise ReceiptRebindError(
                f"invalid loss receipt: {Path(receipt_path).as_posix()}"
            ) from error

        expected_current = json.loads(json.dumps(committed_receipt))
        expected_current["ir"]["sha256"] = current_stored_ir_sha256
        if current_receipt != expected_current:
            raise ReceiptRebindError(
                f"{receipt_repository_path} differs from its Git blob beyond ir.sha256"
            )

        ir_path = _resolve_repository_path(root, ir_repository_path)
        output_path = _resolve_repository_path(root, output_repository_path)
        try:
            ir_artifact = committed_artifact(
                ir_path,
                repository_root=root,
                revision=commit,
            )
            output_artifact = committed_artifact(
                output_path,
                repository_root=root,
                revision=commit,
            )
        except CanonicalGitArtifactError as error:
            raise ReceiptRebindError(str(error)) from error

        canonical_ir_sha256 = _sha256(ir_artifact.canonical_bytes)
        checkout_ir_sha256 = _sha256(ir_artifact.checkout_bytes)
        canonical_output_sha256 = _sha256(output_artifact.canonical_bytes)
        checkout_output_sha256 = _sha256(output_artifact.checkout_bytes)
        pure_eol = (
            ir_artifact.checkout_bytes.replace(b"\r\n", b"\n")
            == ir_artifact.canonical_bytes
        )
        xml_equal = _xml_c14n(ir_artifact.checkout_bytes) == _xml_c14n(
            ir_artifact.canonical_bytes
        )
        output_semantics_equal = _jsonl_semantics(
            output_artifact.checkout_bytes
        ) == _jsonl_semantics(output_artifact.canonical_bytes)
        if not pure_eol:
            raise ReceiptRebindError(
                f"{ir_repository_path} differs from its Git blob beyond CRLF normalization"
            )
        if not xml_equal:
            raise ReceiptRebindError(
                f"{ir_repository_path} XML canonical semantics differ from its Git blob"
            )
        if not output_semantics_equal:
            raise ReceiptRebindError(
                f"{output_repository_path} JSONL semantics differ from its Git blob"
            )
        if old_stored_ir_sha256 not in {
            checkout_ir_sha256,
            canonical_ir_sha256,
        }:
            raise ReceiptRebindError(
                f"{receipt_repository_path} has an unexplained stored IR digest"
            )
        if current_stored_ir_sha256 not in {
            old_stored_ir_sha256,
            canonical_ir_sha256,
        }:
            raise ReceiptRebindError(
                f"{receipt_repository_path} has an unexplained current IR digest"
            )
        if stored_output_sha256 != canonical_output_sha256:
            raise ReceiptRebindError(
                f"{receipt_repository_path} output digest is not its canonical Git identity"
            )

        plans.append(
            ReceiptRebindPlan(
                receipt_path=receipt_target,
                receipt_repository_path=receipt_repository_path,
                ir_repository_path=ir_repository_path,
                output_repository_path=output_repository_path,
                old_stored_ir_sha256=old_stored_ir_sha256,
                current_stored_ir_sha256=current_stored_ir_sha256,
                canonical_ir_sha256=canonical_ir_sha256,
                checkout_ir_sha256=checkout_ir_sha256,
                canonical_output_sha256=canonical_output_sha256,
                checkout_output_sha256=checkout_output_sha256,
                stored_output_sha256=stored_output_sha256,
                ir_blob_oid=ir_artifact.blob_oid,
                output_blob_oid=output_artifact.blob_oid,
                canonical_ir_byte_count=len(ir_artifact.canonical_bytes),
                checkout_ir_byte_count=len(ir_artifact.checkout_bytes),
                pure_eol_normalization=pure_eol,
                xml_c14n_equal=xml_equal,
                output_json_semantics_equal=output_semantics_equal,
                receipt_checkout_sha256=_sha256(current_receipt_bytes),
            )
        )
    return tuple(plans)


def write_receipt_rebinds(plans: Iterable[ReceiptRebindPlan]) -> None:
    """Apply plans while proving the receipt changed only at ``ir.sha256``."""

    for plan in plans:
        before_bytes = plan.receipt_path.read_bytes()
        if _sha256(before_bytes) != plan.receipt_checkout_sha256:
            raise ReceiptRebindError(
                f"{plan.receipt_repository_path} changed after proof"
            )
        before = json.loads(before_bytes)
        if before["ir"]["sha256"] != plan.current_stored_ir_sha256:
            raise ReceiptRebindError(
                f"{plan.receipt_repository_path} IR digest changed after proof"
            )
        after = json.loads(json.dumps(before))
        after["ir"]["sha256"] = plan.canonical_ir_sha256
        expected = json.loads(json.dumps(before))
        expected["ir"]["sha256"] = plan.canonical_ir_sha256
        if after != expected:
            raise ReceiptRebindError(
                f"{plan.receipt_repository_path} planned a non-governed change"
            )
        plan.receipt_path.write_text(
            json.dumps(after, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--write", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    plans = plan_receipt_rebinds(
        args.repository_root,
        revision=args.revision,
    )
    if args.write:
        write_receipt_rebinds(plans)
    print(
        json.dumps(
            {
                "contract": "ocd-loss-receipt-canonical-ir-rebind-v1",
                "revision": repository_revision(args.repository_root, args.revision),
                "write_applied": args.write,
                "receipts": [plan.to_record() for plan in plans],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
