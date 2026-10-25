"""Shared record reading works without loading lookup or generated views."""
from pathlib import Path
import subprocess
import sys

from ocd_kernel.library.record_read import RecordRead, normalize_diagnostic


def test_reader_does_not_import_lookup_or_views() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import sys; "
         "sys.modules['ocd_kernel.library.records'] = None; "
         "sys.modules['ocd_kernel.library.views'] = None; "
         "from ocd_kernel.library.record_read import RecordRead; "
         "assert callable(RecordRead)"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, check=True,
    )
    assert result.returncode == 0


def test_reader_detects_record_and_membership_changes(tmp_path: Path) -> None:
    directory = tmp_path / "library"
    directory.mkdir()
    record = directory / "one.json"
    record.write_text("{}", encoding="utf-8")
    read = RecordRead(tmp_path)
    assert read.bytes("library/one.json", "identity") == b"{}"
    assert read.members("library", "*.json", "identity") == ["one.json"]
    assert read.stable()
    record.write_text('{"changed":true}', encoding="utf-8")
    assert not read.stable()

    read = RecordRead(tmp_path)
    read.members("library", "*.json", "identity")
    (directory / "two.json").write_text("{}", encoding="utf-8")
    assert not read.stable()


def test_diagnostics_remove_only_the_selected_root(tmp_path: Path) -> None:
    assert normalize_diagnostic(tmp_path, f"missing {tmp_path}/library/work.json") == "missing library/work.json"
    assert normalize_diagnostic(tmp_path, f"{tmp_path}-other/file") == str(tmp_path).replace("\\", "/") + "-other/file"
