"""Exact historical work/state contexts for three bounded sidecar test owners."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.tei.install_accepted import _io_path


CASES = {
    "creeds-six": ("plans/2026-09-22-source-preflight/lib062-six-source-packet-sidecar-batch-20260926.json", None),
    "bible-two": ("plans/2026-09-22-source-preflight/five-bible-member-sidecar-packet-20260926.json", (0, 4)),
    "npnf103-sixteen": ("plans/2026-09-22-source-preflight/augustine-npnf103-sixteen-sidecar-batch-20260926.json", None),
}


def _frozen_bytes(raw: bytes, digest: str) -> bytes:
    lf = raw.replace(b"\r\n", b"\n")
    for candidate in (raw, lf, lf.replace(b"\n", b"\r\n")):
        if sha256(candidate).hexdigest() == digest:
            return candidate
    raise AssertionError("Historical packet authority differs from its complete original SHA")


def current_work_context(repository_root: Path, destination: Path, relative: str) -> None:
    """Copy a complete current work before testing duplicate packet identity."""
    work_path = Path(relative)
    assert not work_path.is_absolute() and '..' not in work_path.parts
    raw = _io_path(repository_root / work_path).read_bytes()
    record = json.loads(raw)
    for form in record['textual_forms']:
        for edition in form['editions']:
            for acquisition_id in edition.get('acquisition_ids', []):
                logical = (work_path.parent / 'forms' / form['textual_form_id'] /
                           'editions' / edition['edition_id'] / 'acquisitions' /
                           (acquisition_id + '.json'))
                source = _io_path(repository_root / logical)
                target = _io_path(destination / logical)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
    _io_path(destination / work_path).write_bytes(raw)


def historical_packet_context(repository_root: Path, destination: Path, case: str) -> Path:
    packet_path, selected = CASES[case]
    packet = json.loads((repository_root / packet_path).read_bytes())
    rows = packet["entries"] if selected is None else [packet["entries"][i] for i in selected]
    assert len(rows) == {"creeds-six": 6, "bible-two": 2, "npnf103-sixteen": 16}[case]
    destination.mkdir(parents=True, exist_ok=False)
    (destination / ".ocd-storage.json").write_text(
        json.dumps({"library_root": str(resolve_repo_path(repository_root, "raw").parent)}),
        encoding="utf-8", newline="\n")
    written: dict[str, bytes] = {}

    def put(relative: str, data: bytes) -> None:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Historical packet fixture path must stay relative")
        if path.parts[0] in {"raw", "reports", "exports"}:
            return  # Production readers verify real configured retained sources.
        if relative in written:
            assert written[relative] == data
        target = _io_path(destination / path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written[relative] = data

    def bound(reference: dict) -> bytes:
        relative = reference["path"]
        data = _frozen_bytes(_io_path(repository_root / relative).read_bytes(), reference["sha256"])
        put(relative, data)
        return data

    for row in rows:
        for name in ("work", "state"):
            reference = row[name]
            source = repository_root / "tests/fixtures/historical-sidecar-packets" / case / row["work_id"] / (name + ".json")
            data = _io_path(source).read_bytes()
            assert sha256(data).hexdigest() == reference["sha256"]
            put(reference["path"], data)
        for name in ("source_preflight", "source_packet", "attribution_evidence", "config",
                     "bible_member_evidence", "source_manifest", "metadata_evidence"):
            if name not in row:
                continue
            data = bound(row[name])
            if name == "source_packet":
                source_packet = json.loads(data)
                bound(source_packet["retained_member_census"])
    return destination
