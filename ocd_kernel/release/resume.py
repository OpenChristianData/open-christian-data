"""Durable edition checkpoints and read-only recovery into a fresh build."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import uuid

from ocd_kernel.library._common import PipelineError, canonical_bytes, io_path
from .build_state import _json, item_fingerprint
from .streaming import MAX_JSONL_ROW_BYTES, _unique_object, file_sha256

CONTRACT = "ocd-release-checkpoint-v1"
INPUTS = "internal/build-inputs.json"
DIRECTORY = "internal/checkpoints"


class StageLock:
    """OS-owned lock: process termination releases it without stale PID cleanup."""
    def __init__(self, stage: Path):
        from .public_allowlist import _is_link
        directory = stage.parent / '.release-stage-locks'
        identity = str(stage.resolve())
        if os.name == 'nt':
            identity = identity.casefold()
        path = directory / (hashlib.sha256(identity.encode()).hexdigest() + '.lock')
        if _is_link(directory) or _is_link(path):
            raise PipelineError('resume lock cannot be a reparse point')
        directory.mkdir(exist_ok=True)
        self.stream = path.open('a+b')
        if path.stat().st_size == 0:
            self.stream.write(b'0')
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise PipelineError(f'release stage is actively owned: {stage}') from exc

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def atomic_json(path: Path, value: dict) -> None:
    io_path(path.parent).mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with io_path(temporary).open("xb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(io_path(temporary), io_path(path))
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        io_path(temporary).unlink(missing_ok=True)


def save_inputs(stage: Path, selection: dict, inputs: dict) -> None:
    atomic_json(stage / INPUTS, {"contract": CONTRACT, "selection_sha256":
        hashlib.sha256(canonical_bytes(selection)).hexdigest(), "inputs": inputs})


def checkpoint(stage: Path, selected: dict, item: dict, saved: dict) -> None:
    atomic_json(stage / DIRECTORY / f"{selected['item_id']}.json", {
        "contract": CONTRACT, "selection": selected, "item": item, "range": saved})


def check_checkpoints(stage: Path, selection: dict, manifest: dict, report: dict) -> set[str]:
    if not (stage / INPUTS).exists():
        return set()  # Historical ready candidates predate checkpoints.
    expected = {"contract": CONTRACT, "selection_sha256": manifest["selection_sha256"],
                "inputs": manifest["inputs"]}
    if _json(stage / INPUTS) != expected:
        raise PipelineError("checkpoint inputs differ from final manifest")
    choices = {item["item_id"]: item for item in selection["items"]}
    reports = {item["item_id"]: item for item in report["items"]}
    files = {INPUTS}
    for saved in manifest["items"]:
        identifier = saved["item_id"]
        path = f"{DIRECTORY}/{identifier}.json"
        expected = {"contract": CONTRACT, "selection": choices[identifier],
                    "item": reports[identifier], "range": saved}
        if _json(stage / path) != expected:
            raise PipelineError(f"edition checkpoint differs from final accounting: {identifier}")
        files.add(path)
    return files


def _read_rows(path: Path, saved: dict) -> tuple[list, str]:
    begin, end, count = (saved[key] for key in ("begin", "end", "row_count"))
    if (any(type(value) is not int for value in (begin, end, count))
            or begin < 0 or end <= begin or count <= 0):
        raise PipelineError("invalid checkpoint byte range/count")
    rows, digest = [], hashlib.sha256()
    with path.open("rb") as stream:
        stream.seek(begin)
        while stream.tell() < end:
            line = stream.readline(min(end - stream.tell(), MAX_JSONL_ROW_BYTES + 1))
            if not line or len(line) > MAX_JSONL_ROW_BYTES or not line.endswith(b"\n"):
                raise PipelineError("truncated or oversized checkpoint row")
            row = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object)
            if not isinstance(row, dict) or canonical_bytes(row) != line:
                raise PipelineError("checkpoint row is not canonical")
            digest.update(line)
            rows.append(row)
            if len(rows) > count:
                raise PipelineError("checkpoint has extra rows")
    value = digest.hexdigest()
    if len(rows) != count or saved.get("sha256", value) != value:
        raise PipelineError("checkpoint row count/digest differs")
    return rows, value


class ResumeStage:
    """A checkpoint is a cache hint; current independent checking grants reuse."""

    def __init__(self, directory: Path, *, progress: Path | None = None):
        from .public_allowlist import public_files
        from .selection import validate_release_selection
        self.directory = Path(directory).absolute()
        with StageLock(self.directory):
            pass
        public_files(self.directory)  # Reject links in private files as well.
        selection = validate_release_selection(_json(self.directory / "internal/release-selection.json"))
        self.choices = {item["item_id"]: item for item in selection["items"]}
        self.saved = {}
        self.legacy = not (self.directory / INPUTS).exists()
        self.last_miss = None
        self.last_kind = None
        self.last_source = None
        if self.legacy:
            if progress is None:
                raise PipelineError("legacy stage recovery requires its original --resume-progress")
            self._legacy_ranges(Path(progress), selection)
        else:
            snapshot = _json(self.directory / INPUTS)
            if (snapshot.get("contract") != CONTRACT or snapshot.get("selection_sha256") !=
                    hashlib.sha256(canonical_bytes(selection)).hexdigest()):
                raise PipelineError("resume input snapshot differs from its selection")
            for identifier, choice in self.choices.items():
                path = self.directory / DIRECTORY / f"{identifier}.json"
                if path.exists():
                    self.saved[identifier] = path

    def _legacy_ranges(self, progress: Path, selection: dict) -> None:
        order = {item["item_id"]: index for index, item in enumerate(selection["items"])}
        offsets, last, active = {}, -1, None
        from .public_allowlist import _is_link
        if _is_link(progress):
            raise PipelineError('legacy progress cannot be a reparse point')
        with io_path(progress).open("rb") as stream:
            for line in iter(lambda: stream.readline(1024 * 1024 + 1), b''):
                if len(line) > 1024 * 1024:
                    raise PipelineError('legacy progress event exceeds bounded size')
                if not line.endswith(b"\n"):
                    break  # A crash may leave only the final event incomplete.
                event = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object)
                if event.get("phase") == "projecting":
                    active = event.get("item_id")
                if event.get("phase") not in {"projected", "reused"}:
                    continue
                identifier = event.get("item_id")
                if identifier not in order or identifier != active or order[identifier] <= last:
                    raise PipelineError("legacy progress identities/order differ from selection")
                choice = self.choices[identifier]
                size, count = event.get("bytes"), event.get("rows")
                if ("exclude_reason" in choice or type(size) is not int or size <= 0
                        or type(count) is not int or count <= 0):
                    raise PipelineError("invalid legacy completion event")
                category = choice["category"]
                begin = offsets.get(category, 0)
                self.saved[identifier] = {"begin": begin, "end": begin + size, "row_count": count}
                offsets[category] = begin + size
                last = order[identifier]

    def read_item(self, root: Path, selected: dict, inputs: dict):
        """Return revalidated current public rows, or a cache miss for this edition."""
        with StageLock(self.directory):
            return self._read_item(root, selected, inputs)

    def copy_assembled(self, stage: Path, selection: dict, inputs: dict):
        """Reuse complete encoded bytes; only fresh terminal checks can pass them."""
        import shutil
        from .build_state import MANIFEST, READER, READY, check_ranges
        from .public_allowlist import _configurations, public_files
        from .verify import _schema_diagnostics

        source = self.directory
        if self.legacy or not all((source / path).exists() for path in
                (MANIFEST, 'internal/release-report.json')):
            return None
        with StageLock(source):
            stored = _json(source / 'internal/release-selection.json')
            if {**stored, 'release_id': selection['release_id']} != selection:
                return None
            report = _json(source / 'internal/release-report.json')
            errors = _schema_diagnostics(report, schema_name='release-report.schema.json', label='resume report')
            if errors or (report['status'] == 'pass' and report['accounting']['failed']):
                raise PipelineError(f'assembled resume report is invalid: {errors}')
            if report['status'] == 'fail':
                return None
            if ([{key: item[key] for key in ('item_id', 'category', 'acceptance_path')}
                 for item in report['items']] !=
                    [{key: item[key] for key in ('item_id', 'category', 'acceptance_path')}
                     for item in selection['items']]):
                raise PipelineError('assembled resume item identities differ')
            manifest = _json(source / MANIFEST)
            # Code can change before a fresh independent check; library and
            # Python/package inputs must still describe these exact outputs.
            def authority(value):
                return {**value, 'shared': [entry for entry in value['shared']
                                          if entry['scope'] != 'runtime']}
            if authority(manifest['inputs']) != authority(inputs):
                return None
            check_ranges(source, report, manifest)
            files = check_checkpoints(source, stored, manifest, report)
            files.update({MANIFEST, 'internal/release-selection.json', 'internal/release-report.json',
                          'internal/checks/independent-check.json', 'public/README.md'})
            if 'work_coverage' in selection:
                files.add('internal/work-coverage.json')
            for item in manifest['items']:
                files.add(f"internal/projection-receipts/{item['item_id']}.json")
                if item.get('transform_sha256') is not None:
                    files.add(f"internal/public-row-transforms/{item['item_id']}.json")
            for config in _configurations(report['configurations']):
                files.add(config['path'])
                if 'typed_companion' in config:
                    files.add(config['typed_companion']['path'])
            actual = {path for path in public_files(source) if not path.startswith('.work/')}
            if actual - {READER, READY} != files:
                raise PipelineError('assembled resume file inventory differs')
            for reference in sorted(files):
                path = source / reference
                digest = file_sha256(path)
                target = stage / reference
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                if file_sha256(target) != digest or file_sha256(path) != digest:
                    raise PipelineError(f'assembled resume file changed during copy: {reference}')
            selection_digest = hashlib.sha256(canonical_bytes(selection)).hexdigest()
            report = {**report, 'release_id': selection['release_id'], 'selection_sha256': selection_digest}
            atomic_json(stage / 'internal/release-selection.json', selection)
            atomic_json(stage / 'internal/release-report.json', report)
            atomic_json(stage / MANIFEST, {**manifest, 'inputs': inputs, 'selection_sha256': selection_digest})
            save_inputs(stage, selection, inputs)
            return report

    def _check_paths(self, choice: dict) -> None:
        from .public_allowlist import _is_link
        identifier = choice['item_id']
        for path in (self.directory / 'internal/release-selection.json', self.directory / INPUTS,
                self.directory / DIRECTORY / f'{identifier}.json',
                self.directory / f"public/data/{choice['category']}/train.jsonl",
                self.directory / f'internal/projection-receipts/{identifier}.json',
                self.directory / f'internal/public-row-transforms/{identifier}.json'):
            for parent in (path, *path.parents):
                if _is_link(parent):
                    raise PipelineError(f'resume source became a reparse point: {parent}')
                if parent == self.directory:
                    break

    def _read_item(self, root: Path, selected: dict, inputs: dict):
        from .verify import restore_release_item, verify_release_item
        from .selection import resolve_acceptance_path
        from .work_metadata import compose_work_metadata
        from .public_rows import HASH_BOUND_ITEMS, publication_transform_key, public_rows_with_omissions
        from .public_rights import requires_wrapper
        identifier = selected["item_id"]
        self.last_miss = None
        self.last_kind = None
        self.last_source = None
        if identifier not in self.saved:
            return None
        try:
            old = self.choices[identifier]
            self._check_paths(old)
            if any(old.get(key) != selected.get(key) for key in ("category", "acceptance_path", "work_id")):
                raise PipelineError("selected identity/category changed")
            if self.legacy:
                saved = self.saved[identifier]
            else:
                record = _json(self.saved[identifier])
                if record.get("contract") != CONTRACT or record.get("selection") != old:
                    raise PipelineError("invalid edition checkpoint")
                saved = record["range"]
                if saved.get("item_id") != identifier or record["item"].get("row_count") != saved["row_count"]:
                    raise PipelineError("checkpoint identity/count differs")
            path = self.directory / f"public/data/{old['category']}/train.jsonl"
            rows, _digest = _read_rows(path, saved)
            receipt_path = self.directory / f"internal/projection-receipts/{identifier}.json"
            transform_path = self.directory / f"internal/public-row-transforms/{identifier}.json"
            receipt_digest = file_sha256(receipt_path)
            receipt = _json(receipt_path)
            transform_digest = file_sha256(transform_path) if transform_path.exists() else None
            transform = _json(transform_path) if transform_digest is not None else None
            if not self.legacy and (saved['receipt_sha256'] != receipt_digest or saved.get('transform_sha256') != transform_digest):
                raise PipelineError("checkpoint receipt/transform digest differs")
            base, proof = restore_release_item(root, old, rows, receipt, transform, retained=True)
            # Only the authored work record is refreshed; the independent
            # checker must re-establish every source/text/receipt claim.
            authority = proof.get('authority', {})
            if not isinstance(authority, dict):
                raise PipelineError('invalid retained receipt authority')
            work_binding = authority.get('work')
            work_reference = f"library/works/{selected['work_id']}/work.json"
            if isinstance(work_binding, dict) and work_binding.get('path') == work_reference:
                from ocd_kernel.lib.storage_topology import resolve_repo_path
                proof['authority'] = {**proof['authority'], 'work': {
                    'path': work_reference, 'sha256': file_sha256(resolve_repo_path(root, work_reference))}}
            if 'license' in selected:
                base = [dict(row, license=selected['license']) for row in base]
            acceptance = resolve_acceptance_path(root, selected['acceptance_path'])
            accepted = _json(acceptance)
            key = publication_transform_key(accepted['identity'])
            authority = {'acceptance_sha256': file_sha256(acceptance), 'master_sha256': proof.get('master_sha256')} if key in HASH_BOUND_ITEMS or requires_wrapper(key, selected.get('license')) else {}
            rows, transform = public_rows_with_omissions(base, item_id=identifier, accepted_identity=accepted['identity'], **authority)
            rows, proof = compose_work_metadata(root, rows, proof, public_layer=True)
            errors = verify_release_item(root, selected, rows, proof, transform)
            if errors:
                raise PipelineError("; ".join(errors))
            if receipt_digest != file_sha256(receipt_path) or transform_digest != (file_sha256(transform_path) if transform_path.exists() else None):
                raise PipelineError("resume evidence changed while checking")
            self.last_kind = 'legacy-verified' if self.legacy else ('fingerprint-verified' if
                saved.get('input_fingerprint') == item_fingerprint(inputs, selected) else 'revalidated')
            self.last_source = {'stage': str(self.directory), 'begin': saved['begin'], 'end': saved['end'],
                                'observed_rows_sha256': _digest, 'receipt_sha256': receipt_digest,
                                'transform_sha256': transform_digest}
            return rows, proof, transform
        except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
            self.last_miss = str(exc)
            return None
