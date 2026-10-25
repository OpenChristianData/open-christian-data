"""Fresh private/public release assembly for the PIPE-001 tracer."""

from __future__ import annotations

import json
import hashlib
import shutil
import uuid
from pathlib import Path
from ocd_kernel.lib.atomic_io import _replace_with_retry
from typing import Any

from ocd_kernel.library._common import PipelineError, canonical_bytes, write_json
from ocd_kernel.library.acquisitions import acquisition_for_edition, source_sha256
from ocd_kernel.library.identities import Edition, Work, discover_library, edition_by_id, resolve_edition_language
from ocd_kernel.library.views import build_library_views
from ocd_kernel.projection.categories.prose import ASSEMBLER_VERSION, project_prose
from ocd_kernel.projection.receipt import build_receipt

from .selection import make_selection


RELEASE_VERSION = "ocd-offline-release-provisional-v1"


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise PipelineError(f"path is outside fixture root: {path}") from exc


def _edition_language(work: Work, edition: Edition) -> str | None:
    return resolve_edition_language(work.record, edition.record, edition.textual_form_id)


def _readme() -> str:
    return (
        "# OCD offline release\n\n"
        "This deterministic private/public tree was assembled offline from the "
        "selected accepted TEI master. The `public/` directory is the only "
        "uploadable tree; `internal/` contains private receipts and checks.\n"
    )


def _item_key(item: dict[str, Any]) -> tuple[str, str]:
    return (str(item.get("work_id", "")), str(item.get("edition_id", "")))


def assemble_release(
    root: Path,
    output: Path,
    *,
    release_id: str,
    edition_id: str | None = None,
    category: str = "prose",
) -> dict[str, Any]:
    """Build views, public rows, receipts, and the independent check in one run."""

    root = Path(root).resolve()
    output = Path(output).resolve()
    if edition_id is None:
        raise PipelineError("PIPE-001 requires one explicit edition_id")
    if output.exists():
        raise PipelineError(f"release output must be fresh: {output}")
    if output == root or root in output.parents:
        raise PipelineError("release output must not be inside the fixture root")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    try:
        views = build_library_views(root, stage)
        selection = make_selection(
            release_id=release_id,
            category=category,
            edition_id=edition_id,
            status_report=views["status"],
        )
        public_rows: list[dict[str, Any]] = []
        projections: list[tuple[dict[str, Any], Work, Edition, Path, dict[str, Any], Any]] = []
        final_items: list[dict[str, Any]] = []
        for selected in selection["items"]:
            item = dict(selected)
            if not selected.get("selected"):
                final_items.append(item)
                continue
            work, edition = edition_by_id(root, selected["edition_id"])
            if work.work_id != selected["work_id"] or edition.textual_form_id != selected["textual_form_id"]:
                raise PipelineError(
                    f"selection identity mismatch for edition {selected['edition_id']}"
                )
            try:
                acquisition_path, acquisition = acquisition_for_edition(
                    root,
                    work.work_id,
                    edition.edition_id,
                    acquisition_id=edition.record.get("acquisition_id"),
                )
                source_hash = source_sha256(acquisition, context=str(acquisition_path))
                retained_hash = acquisition["retained_files"][0]["sha256"].lower()
                language = _edition_language(work, edition)
                accessed_at = acquisition.get("accessed_at")
                if accessed_at is not None and (not isinstance(accessed_at, str) or not accessed_at.strip()):
                    raise PipelineError("acquisition accessed_at must be a nonempty date when present")
                projection = project_prose(
                    edition.path,
                    work_id=work.work_id,
                    textual_form_id=edition.textual_form_id,
                    edition_id=edition.edition_id,
                    acquisition_id=acquisition["acquisition_id"],
                    edition_title=edition.title,
                    language=language,
                    representation_revision=None,  # Read the authoritative TEI header.
                    source_url=acquisition["url"],
                    accessed_at=accessed_at,
                    source_sha256=source_hash,
                    retained_sha256=retained_hash,
                    scope_id=edition.record.get("scope_id"),
                    rights=acquisition.get("rights") if isinstance(acquisition.get("rights"), str) else None,
                )
            except (PipelineError, OSError) as exc:
                item["status"] = "failed"
                item["selected"] = False
                item.setdefault("reasons", []).append(str(exc))
                final_items.append(item)
                continue
            public_rows.extend(projection.rows)
            projections.append((item, work, edition, acquisition_path, acquisition, projection))
            if projection.warnings and item["status"] == "included":
                item["status"] = "warned"
            final_items.append(item)

        if not public_rows:
            final_selection = dict(selection)
            final_selection["items"] = sorted(final_items, key=_item_key)
            final_selection["accounting"] = {
                "requested": len(final_items),
                "selected": 0,
                "included": 0,
                "warned": 0,
                "failed": sum(1 for item in final_items if item.get("status") == "failed"),
                "excluded": sum(1 for item in final_items if item.get("status") == "excluded"),
            }
            errors = [
                f"{item.get('edition_id', '<unknown>')}: {reason}"
                for item in final_items
                for reason in item.get("reasons", [])
            ]
            failure = {
                "schema_version": "provisional-v1",
                "release_version": RELEASE_VERSION,
                "release_id": release_id,
                "assembler": {"version": ASSEMBLER_VERSION},
                "requested_categories": [category],
                "items": final_selection["items"],
                "receipts": [],
                "status": "fail",
                "errors": errors or ["no included accepted edition"],
            }
            write_json(stage / "internal" / "release-selection.json", final_selection)
            write_json(stage / "internal" / "release-report.json", failure)
            write_json(
                stage / "internal" / "checks" / "independent-check.json",
                {"status": "fail", "errors": failure["errors"]},
            )
            _replace_with_retry(stage, output)
            raise PipelineError("release produced no public prose rows: " + "; ".join(failure["errors"]))
        public_bytes = b"".join(canonical_bytes(row) for row in public_rows)
        public_path = stage / "public" / "data" / "prose" / "train.jsonl"
        public_path.parent.mkdir(parents=True, exist_ok=True)
        public_path.write_bytes(public_bytes)
        (stage / "public" / "README.md").write_text(_readme(), encoding="utf-8", newline="\n")

        receipt_paths: list[str] = []
        for item, work, edition, acquisition_path, acquisition, projection in projections:
            receipt = build_receipt(
                work_id=work.work_id,
                textual_form_id=edition.textual_form_id,
                edition_id=edition.edition_id,
                acquisition_id=acquisition["acquisition_id"],
                master_relative_path=_relative(root, edition.path),
                source_sha256=source_sha256(acquisition, context=str(acquisition_path)),
                retained_sha256=acquisition["retained_files"][0]["sha256"].lower(),
                source_path=acquisition.get("source_path") if isinstance(acquisition.get("source_path"), str) else None,
                acquisition_relative_path=_relative(root, acquisition_path),
                public_relative_path="public/data/prose/train.jsonl",
                public_bytes=public_bytes,
                projection=projection,
            )
            receipt_path = stage / "internal" / "projection-receipts" / f"{edition.edition_id}.json"
            write_json(receipt_path, receipt)
            receipt_paths.append(_relative(stage, receipt_path))

        final_selection = dict(selection)
        final_selection["items"] = sorted(final_items, key=_item_key)
        final_selection["accounting"] = {
            "requested": len(final_items),
            "selected": sum(1 for item in final_items if item.get("selected")),
            "included": sum(1 for item in final_items if item.get("status") == "included"),
            "warned": sum(1 for item in final_items if item.get("status") == "warned"),
            "failed": sum(1 for item in final_items if item.get("status") == "failed"),
            "excluded": sum(1 for item in final_items if item.get("status") == "excluded"),
        }
        write_json(stage / "internal" / "release-selection.json", final_selection)
        report = {
            "schema_version": "provisional-v1",
            "release_version": RELEASE_VERSION,
            "release_id": release_id,
            "assembler": {"version": ASSEMBLER_VERSION},
            "requested_categories": [category],
            "items": final_selection["items"],
            "receipts": sorted(receipt_paths),
            "public": {
                "files": ["README.md", "data/prose/train.jsonl"],
                "row_count": len(public_rows),
            },
        }
        write_json(stage / "internal" / "release-report.json", report)

        from .check import check_release

        check_result = check_release(root, stage)
        for receipt_path in (stage / "internal" / "projection-receipts").glob("*.json"):
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["independent_check"] = {
                "status": check_result["status"],
                "errors": list(check_result.get("errors", [])),
            }
            write_json(receipt_path, receipt)
        write_json(stage / "internal" / "checks" / "independent-check.json", check_result)
        report["independent_check"] = check_result
        report["status"] = check_result["status"]
        write_json(stage / "internal" / "release-report.json", report)
        if check_result["status"] != "pass":
            raise PipelineError("independent release check failed: " + "; ".join(check_result.get("errors", [])))
        if output.exists():
            raise PipelineError("release destination appeared during assembly")
        _replace_with_retry(stage, output)
        return report
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise


def _assemble_release_v2(root: Path, output: Path, *, selection: dict[str, Any],
                         profile_path: Path | None = None, previous_release: Path | None = None,
                         reader_check: bool = False, evidence_dir: Path | None = None,
                         _inputs: dict | None = None, resume_stage: Path | None = None,
                         resume_progress: Path | None = None) -> dict[str, Any]:
    """Assemble explicit configurations from current promoted authorities offline.

    Item failures are retained as private accounting and make the release fail.
    Infrastructure or independent-check failures never promote a staged tree.
    The original PIPE-001 API remains available until consumer cutover.
    """
    import hashlib
    import importlib
    import tempfile
    import os
    import time
    import sys
    from datetime import datetime, timezone
    from .selection import validate_release_selection, validate_work_cohort, resolve_acceptance_path
    from .streaming import file_sha256, iter_jsonl
    from .build_state import (CONTRACT, MANIFEST, capture_inputs, item_fingerprint, PreviousCandidate)
    from .resume import ResumeStage, StageLock, save_inputs, checkpoint, atomic_json

    request = validate_release_selection(selection)
    root = Path(root).resolve(strict=True)
    item_work_ids = validate_work_cohort(root, request)
    targets = set()
    for item in request["items"]:
        resolved = resolve_acceptance_path(root, item["acceptance_path"])
        key = (item["category"], str(resolved).casefold())
        if key in targets:
            raise PipelineError("duplicate resolved release target")
        targets.add(key)
    destination = Path(output).absolute()
    if destination.exists() or _release_is_reparse(destination):
        raise PipelineError(f"release output must be fresh: {destination}")
    destination = destination.resolve()
    if destination == root or root in destination.parents:
        raise PipelineError("release output must be outside the input root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < 512 * 1024 * 1024:
        raise PipelineError("release needs at least 512 MiB free workspace headroom")
    inputs = _inputs if _inputs is not None else (capture_inputs(root, request, profile_path) if profile_path is not None else None)
    master_bytes = 0
    if inputs is not None:
        from ocd_kernel.lib.storage_topology import resolve_repo_path
        masters = {entry["path"] for item in inputs["item_bindings"] for entry in item["files"]
                   if entry["path"].endswith("/master.tei.xml")}
        master_bytes = sum(resolve_repo_path(root, path).stat().st_size for path in masters)
        # Budget is conservative guidance for this text export, not a bound on
        # arbitrary source adapters' temporary files. ENOSPC still aborts safely.
        estimated_workspace = 2 * 1024**3 + 16 * master_bytes
        if shutil.disk_usage(destination.parent).free < estimated_workspace:
            raise PipelineError(f"insufficient release space: estimated {estimated_workspace} bytes including headroom")
    if previous_release is not None and inputs is None:
        raise PipelineError("projection reuse requires a pinned publication profile")
    if (resume_stage is not None and (inputs is None or previous_release is not None)):
        raise PipelineError("stage recovery requires a profile and cannot combine with --previous-release")
    if resume_progress is not None and resume_stage is None:
        raise PipelineError("--resume-progress requires --resume-stage")
    previous = PreviousCandidate(previous_release, inputs) if previous_release is not None else None
    recovery = ResumeStage(resume_stage, progress=resume_progress) if resume_stage is not None else None
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    workdir = stage / ".work"
    workdir.mkdir()
    stage_lock = StageLock(stage) if inputs is not None else None
    old_temp = tempfile.tempdir
    old_env = {key: os.environ.get(key) for key in ("TEMP", "TMP")}
    tempfile.tempdir = str(workdir)
    os.environ.update(TEMP=str(workdir), TMP=str(workdir))
    started = time.monotonic()

    def progress(phase: str, **details) -> None:
        if evidence_dir is not None:
            evidence_dir.mkdir(parents=True, exist_ok=True)
            event = {"at": datetime.now(timezone.utc).isoformat(), "phase": phase,
                     "elapsed_seconds": round(time.monotonic() - started, 3), **details}
            with (evidence_dir / "progress.jsonl").open("ab") as stream:
                stream.write(canonical_bytes(event))
            print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)
    supported = {"prose", "quotations", "devotionals", "bible", "commentary", "topical_indexes",
                 "sermons", "hymns", "liturgies", "poetry", "catechisms",
                 "doctrinal_documents", "reference_entries", "prayers"}
    try:
        with tempfile.TemporaryDirectory(prefix="preflight-", dir=workdir) as probe:
            probe_path = Path(probe) / "probe"
            probe_path.write_bytes(b"release workspace probe\n")
        progress("building", workspace=str(stage), free_bytes=shutil.disk_usage(stage).free,
                 estimated_workspace_bytes=(2 * 1024**3 + 16 * master_bytes) if inputs is not None else None)
        assembled = recovery.copy_assembled(stage, request, inputs) if recovery is not None else None
        if assembled is not None:
            progress("resumed-assembly", source=str(recovery.directory),
                     editions=assembled["accounting"]["included"] + assembled["accounting"]["warned"])
            return _finish_release(root, stage, destination, request, inputs, assembled,
                                   reader_check, workdir, progress)
        atomic_json(stage / "internal/release-selection.json", request)
        if inputs is not None:
            save_inputs(stage, request, inputs)
        items = []
        category_paths: dict[str, Path] = {}
        category_counts: dict[str, int] = {}
        ranges = []
        item_notices: dict[str, list[str]] = {}
        for selected in request["items"]:
            category = selected["category"]
            item = {key: selected[key] for key in ("item_id", "category", "acceptance_path")}
            item.update(status="excluded", reasons=[], row_count=0, receipt_path=None)
            if "exclude_reason" in selected:
                item["reasons"] = [selected["exclude_reason"]]
            else:
                item_started = time.monotonic()
                progress("projecting", item_id=selected["item_id"], completed=len(items), total=len(request["items"]))
                projection = rows = None
                receipt_output = stage / f"internal/projection-receipts/{selected['item_id']}.json"
                transform_output = stage / f"internal/public-row-transforms/{selected['item_id']}.json"
                try:
                    if category not in supported:
                        raise PipelineError(f"unsupported accepted-master adapter: {category}")
                    accepted_path = resolve_acceptance_path(root, selected["acceptance_path"])
                    from ocd_kernel.library._common import load_json
                    accepted = load_json(accepted_path)
                    identity = accepted.get("identity")
                    if "work_coverage" in request:
                        if not isinstance(identity, dict) or identity.get("work_id") != item_work_ids[selected["item_id"]]:
                            raise PipelineError(
                                f"selection work_id differs from accepted identity: {selected['item_id']}"
                            )
                    reused = previous.read_item(selected, inputs) if previous is not None else None
                    if recovery is not None:
                        reused = recovery.read_item(root, selected, inputs)
                        if recovery.last_miss:
                            progress("resume-miss", item_id=selected["item_id"], reason=recovery.last_miss)
                    if reused is not None:
                        public_rows, receipt, omissions = reused
                    else:
                        module = importlib.import_module(f"ocd_kernel.projection.categories.{category}")
                        projector = getattr(module, f"project_accepted_{category}")
                        projection = projector(root, acceptance_path=accepted_path)
                        if not isinstance(projection, dict):
                            raise PipelineError("accepted projection must be an object")
                        rows = projection["rows"]
                        if "license" in selected:
                            rows = [dict(row, license=selected["license"]) for row in rows]
                        receipt = projection["receipt"]
                        if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) for row in rows):
                            raise PipelineError("accepted projection requires nonempty object rows")
                        if not isinstance(receipt, dict):
                            raise PipelineError("accepted projection receipt must be an object")
                        from .public_rows import HASH_BOUND_ITEMS, public_rows_with_omissions, publication_transform_key
                        from .public_rights import requires_wrapper
                        transform_key = publication_transform_key(accepted["identity"])
                        historical_authority = (
                            {"acceptance_sha256": hashlib.sha256(accepted_path.read_bytes()).hexdigest(),
                             "master_sha256": receipt.get("master_sha256")}
                            if (transform_key in HASH_BOUND_ITEMS
                                or requires_wrapper(transform_key, selected.get("license"))) else {}
                        )
                        public_rows, omissions = public_rows_with_omissions(
                            rows, item_id=selected["item_id"], accepted_identity=accepted["identity"], **historical_authority
                        )
                        from .work_metadata import compose_work_metadata
                        public_rows, receipt = compose_work_metadata(root, public_rows, receipt, public_layer=True)
                    if inputs is not None and not (recovery is not None and reused is not None):
                        from .verify import verify_release_item
                        diagnostics = verify_release_item(root, selected, public_rows, receipt, omissions)
                        if diagnostics:
                            raise PipelineError("; ".join(diagnostics))
                    from .public_allowlist import _scan

                    boundary_errors = _scan(
                        public_rows, f"item {selected['item_id']} public rows"
                    )
                    if boundary_errors:
                        raise PipelineError("; ".join(boundary_errors))
                    from .rights import require_release_rights
                    require_release_rights(root, selected, accepted['identity'], public_rows)
                    warnings = receipt.get("warnings", [])
                    if not isinstance(warnings, list) or any(not isinstance(value, (str, dict)) for value in warnings):
                        raise PipelineError("accepted projection warnings must be an array of messages")
                    from .notices import notice_texts_for_item
                    notices = notice_texts_for_item(root, selected, accepted_path)
                    from .public_allowlist import render_dataset_card

                    render_dataset_card([{
                        "category": category,
                        "path": f"public/data/{category}/train.jsonl",
                        "row_count": len(public_rows),
                    }], notices=notices)
                    item.update(
                        status="warned" if warnings else "included",
                        reasons=[v if isinstance(v, str) else canonical_bytes(v).decode().strip() for v in warnings],
                        row_count=len(public_rows),
                        receipt_path=f"internal/projection-receipts/{selected['item_id']}.json",
                    )
                    atomic_json(receipt_output, receipt)
                    if omissions is not None:
                        atomic_json(transform_output, omissions)
                    category_path = stage / f"public/data/{category}/train.jsonl"
                    category_path.parent.mkdir(parents=True, exist_ok=True)
                    with category_path.open("ab") as spool:
                        begin = spool.tell()
                        digest = hashlib.sha256()
                        try:
                            for row in public_rows:
                                content = canonical_bytes(row)
                                spool.write(content)
                                digest.update(content)
                            end = spool.tell()
                            spool.flush()
                            os.fsync(spool.fileno())
                        except (OSError, ValueError, TypeError):
                            spool.seek(begin)
                            spool.truncate()
                            raise
                    category_paths[category] = category_path
                    category_counts[category] = category_counts.get(category, 0) + len(public_rows)
                    if inputs is not None:
                        saved = {"item_id": selected["item_id"], "begin": begin, "end": end,
                                       "row_count": len(public_rows), "sha256": digest.hexdigest(),
                                       "input_fingerprint": item_fingerprint(inputs, selected),
                                       "receipt_sha256": file_sha256(receipt_output),
                                       "transform_sha256": file_sha256(transform_output) if transform_output.exists() else None,
                                       "reused": reused is not None,
                                       "reuse_source": recovery.last_source if recovery is not None and reused is not None else None,
                                       "reuse_kind": recovery.last_kind if recovery is not None and reused is not None else ('previous-ready' if reused is not None else 'projected')}
                        checkpoint(stage, selected, item, saved)
                        ranges.append(saved)
                    item_notices[selected["item_id"]] = notices
                    progress("reused" if reused is not None else "projected", item_id=selected["item_id"], rows=len(public_rows), bytes=end-begin,
                             seconds=round(time.monotonic()-item_started, 3),
                             reuse_kind=recovery.last_kind if recovery is not None and reused is not None else None)
                    # The receipt and inverse are persisted; only public rows
                    # are needed for category serialization and final checks.
                    del projection, rows, receipt, public_rows, omissions
                except OSError as exc:
                    # An unwritable/full workspace is an infrastructure failure,
                    # not a reason to retry the same broken operation per book.
                    progress("failed", item_id=selected["item_id"], kind="infrastructure", error=str(exc))
                    raise PipelineError(f"release infrastructure failed; diagnostics at {stage}: {exc}") from exc
                except (PipelineError, ValueError, KeyError, TypeError) as exc:
                    receipt_output.unlink(missing_ok=True)
                    transform_output.unlink(missing_ok=True)
                    item.update(status="failed", reasons=[str(exc)], row_count=0, receipt_path=None)
                    progress("item-failed", item_id=selected["item_id"], error=str(exc))
            items.append(item)
        if "work_coverage" in request:
            text_by_work: dict[str, list[dict[str, str]]] = {
                work_id: [] for work_id in request["work_coverage"]["included_work_ids"]
            }
            for item in items:
                work_id = item_work_ids.get(item["item_id"])
                if work_id is not None:
                    text_by_work[work_id].append({
                        "item_id": item["item_id"], "status": item["status"],
                    })
            selected_works = []
            for work_id, text_items in text_by_work.items():
                statuses = {entry["status"] for entry in text_items}
                disposition = (
                    "failed_text_selection" if "failed" in statuses else
                    "warned_text" if "warned" in statuses else
                    "included_text" if text_items else
                    "no_accepted_text_selected"
                )
                selected_works.append({
                    "work_id": work_id, "disposition": disposition,
                    "text_items": text_items,
                })
            write_json(stage / "internal/work-coverage.json", {
                "schema_version": "1.0",
                "selected_works": selected_works,
                "excluded_works": request["work_coverage"]["excluded_works"],
            })
        configurations = []
        from .features import configuration_features
        from .typed_rows import BOUNDED_ENCODING, write_rows
        for category, path in sorted(category_paths.items()):
            relative = f"public/data/{category}/train.jsonl"
            progress("encoding", category=category, jsonl_bytes=path.stat().st_size)
            features = configuration_features(iter_jsonl(path, canonical=True))
            typed_path = f"public/data/{category}/train.arrow"
            write_rows(stage / typed_path, iter_jsonl(path, canonical=True), features, encoding=BOUNDED_ENCODING)
            configurations.append({"category": category, "path": relative,
                                   "row_count": category_counts[category], "sha256": file_sha256(path),
                                   "features": features, "typed_encoding": BOUNDED_ENCODING,
                                   "typed_companion": {"path": typed_path,
                                       "sha256": file_sha256(stage / typed_path)}})
        accounting = {"requested": len(items)}
        accounting.update({name: sum(item["status"] == name for item in items)
                           for name in ("included", "warned", "failed", "excluded")})
        report = {
            "schema_version": "2.0", "release_version": "ocd-offline-release-v2",
            "release_id": request["release_id"], "status": "fail" if accounting["failed"] else "pass",
            "items": items, "accounting": accounting, "configurations": configurations,
            "selection_sha256": hashlib.sha256(canonical_bytes(request)).hexdigest(),
        }
        write_json(stage / "internal/release-report.json", report)
        # This staged claim is compared with a fresh independent result before
        # any tree is promoted. Category receipt markers remain untouched.
        expected_check = {"status": report["status"],
                          "errors": ["release contains failed items"] if accounting["failed"] else []}
        if configurations:
            from .public_allowlist import render_dataset_card
            notices = sorted({text for item in items if item["status"] in {"included", "warned"}
                              for text in item_notices.get(item["item_id"], [])})
            (stage / "public/README.md").write_bytes(
                render_dataset_card(configurations, notices=notices).encode("utf-8")
            )
        write_json(stage / "internal/checks/independent-check.json", expected_check)
        if inputs is not None:
            write_json(stage / MANIFEST, {"contract": CONTRACT, "inputs": inputs, "items": ranges,
                                        "selection_sha256": report["selection_sha256"]})
        if accounting["failed"]:
            raise PipelineError(f"release contains failed items; diagnostics retained at {stage}")
        return _finish_release(root, stage, destination, request, inputs, report,
                               reader_check, workdir, progress)
    finally:
        if stage_lock is not None:
            stage_lock.close()
        tempfile.tempdir = old_temp
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _finish_release(root, stage, destination, request, inputs, report, reader_check, workdir, progress):
    """Run the same terminal gates after fresh assembly or encoded-stage recovery."""
    from .streaming import file_sha256
    from .verify import verify_release_v2
    from .build_state import CONTRACT, MANIFEST, READER, READY, check_inputs, check_ready
    expected_check = {"status": report["status"], "errors": []}
    checked_hashes = {path.relative_to(stage).as_posix(): file_sha256(path)
                      for path in stage.rglob("*") if path.is_file() and workdir not in path.parents}
    progress("verifying")
    check = verify_release_v2(root, stage, selection=request, progress=progress)
    # Known failed requests retain a failed report; verification faults do not.
    if check != expected_check:
        raise PipelineError(f"independent release verification failed: {check!r}")
    if reader_check:
        from build.tools.check_release_reader import check_reader
        progress("checking-readers")
        reader = check_reader(root, stage, request, reader_only=True, temp_root=workdir)
        reader["release"] = str(destination)
        write_json(stage / READER, reader)
    if inputs is not None:
        progress("checking-input-drift")
        check_inputs(root, request, inputs)
        if not reader_check:
            raise PipelineError("profile candidate requires both reader modes before readiness")
        for path, digest in checked_hashes.items():
            if file_sha256(stage / path) != digest:
                raise PipelineError(f"checked file changed before readiness: {path}")
        from .public_allowlist import public_files
        if public_files(stage) != set(checked_hashes) | {READER}:
            raise PipelineError("release file inventory changed before readiness")
        write_json(stage / READY, {"contract": CONTRACT, "status": "pass",
                                 "files": {**checked_hashes, READER: file_sha256(stage / READER)}})
        check_ready(stage)
    shutil.rmtree(workdir)
    if destination.exists() or _release_is_reparse(destination):
        raise PipelineError("release destination appeared during assembly")
    _replace_with_retry(stage, destination)
    progress("ready" if reader_check else "assembled", destination=str(destination),
             free_bytes=shutil.disk_usage(destination).free)
    return report


def _release_is_reparse(path: Path) -> bool:
    """Detect symlinks and Windows reparse points on supported Python 3.11+."""
    import stat
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def assemble_release_v2(root: Path, output: Path, *, selection: dict[str, Any] | None = None,
                        profile_path: Path | None = None, previous_release: Path | None = None,
                        reader_check: bool = False, evidence_dir: Path | None = None,
                        release_id: str | None = None, resume_stage: Path | None = None,
                        resume_progress: Path | None = None) -> dict[str, Any]:
    """Assemble a release using one validating catalog scan for this read-only phase."""
    from ocd_kernel.library.identities import cached_edition_lookups

    with cached_edition_lookups():
        inputs = None
        if selection is None:
            if profile_path is None:
                raise PipelineError("release requires a selection or publication profile")
            from .profile import resolve_publication_profile
            from .build_state import capture_inputs, _catalog_inventory
            root = Path(root).resolve(strict=True)
            catalog = _catalog_inventory(root)
            selection, derivation = resolve_publication_profile(
                root, profile_path=profile_path, release_id=release_id or Path(output).name)
            inputs = capture_inputs(root, selection, profile_path, _derivation=derivation, _catalog=catalog)
        return _assemble_release_v2(root, output, selection=selection, profile_path=profile_path,
                                    previous_release=previous_release, reader_check=reader_check,
                                    evidence_dir=evidence_dir, _inputs=inputs,
                                    resume_stage=resume_stage, resume_progress=resume_progress)
