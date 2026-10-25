"""Exact retained MGH sidecars for isolated historical installer tests."""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
from ocd_kernel.tei.install_accepted import _files, _io_path


def restore_mgh_journal_before(destination: Path, record: dict) -> None:
    work_id = record["work_id"]
    assert work_id and all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in work_id)
    stage = Path(record["stage_root"])
    work = Path("library/works") / work_id
    assert _files(stage / work) == record["after"]
    assert not _io_path(destination / work).exists()
    fixture_home = Path(__file__).parent / "fixtures/openmgh-historical-sidecars" / work_id
    assert len(record["before"]) == 3
    for relative, digest in record["before"].items():
        raw = (fixture_home / "work" / relative).read_bytes()
        assert sha256(raw).hexdigest() == digest
        target = _io_path(destination / work / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    assert _files(destination / work) == record["before"]
    for name, key, digest_key in (
        ("manifest-before.json", "manifest_path", "source_manifest_before_sha256"),
        ("profile-before.json", "profile_path", "profile_before_sha256"),
    ):
        raw = (fixture_home / name).read_bytes()
        assert sha256(raw).hexdigest() == record[digest_key]
        target = _io_path(destination / record[key])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        assert sha256(target.read_bytes()).hexdigest() == record[digest_key]
