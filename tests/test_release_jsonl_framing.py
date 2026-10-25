"""Unicode line separators remain JSON string content through all release gates."""
from pathlib import Path
import json
import pytest

from build.tools.check_release_reader import check_reader
from build.tools.report_release_stats import release_statistics
from ocd_kernel.library._common import canonical_bytes
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.public_allowlist import check_public_boundary
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import promote_accepted_master
from tests.test_projection_quotations import accepted_fixture
from tests.test_release_assembly_v2 import _item, _selection


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("jf")


def test_literal_unicode_line_separators_preserve_lf_rows_and_failure_checks(tmp_path: Path) -> None:
    fixture, acceptance = accepted_fixture(tmp_path / "f", "quotations")
    identity = json.loads(acceptance.read_text(encoding="utf-8"))["identity"]
    work_path = fixture / "library/works" / identity["work_id"] / "work.json"
    work = json.loads(work_path.read_text(encoding="utf-8"))
    title = "Synthetic NEL\u0085line separator\u2028paragraph separator\u2029edition"
    work["textual_forms"][0]["editions"][0]["title"] = title
    work_path.write_bytes(canonical_bytes(work))
    promoted = promote_accepted_master(fixture, acceptance_path=acceptance, destination=tmp_path / "p")
    root = promoted.destination_root
    selection = _selection(_item(root, "quote", "quotations", promoted.acceptance_path))
    release = tmp_path / "release"
    report = assemble_release_v2(root, release, selection=selection)
    assert report["status"] == "pass"
    config = report["configurations"][0]
    path = release / config["path"]
    original = path.read_bytes()
    rows = [json.loads(line) for line in original.split(b"\n")[:-1]]
    assert len(rows) == config["row_count"] == 5
    assert all(row["provenance"]["edition_title"] == title for row in rows)
    assert all(char.encode("utf-8") in original for char in ("\u0085", "\u2028", "\u2029"))
    assert verify_release_v2(root, release, selection=selection) == {"status": "pass", "errors": []}
    assert check_public_boundary(release, report) == []
    stats = release_statistics(root, release, selection)
    assert stats["status"] == "pass" and stats["total"]["records"] == 5
    readers = check_reader(root, release, selection)
    assert readers["status"] == "pass"
    assert readers["configurations"] == [{"category": "quotations", "rows": 5,
        "normal_and_streaming": "pass", "all_original_values_and_order_preserved": True}]

    first, rest = original.split(b"\n", 1)
    for changed, expected_error in [
        (original[:-1], "not canonical JSONL"),
        (first + b"\n\n" + rest, "release verification failed"),
        (b'{"text":\n', "release verification failed"),
        (b'{"text":"one","text":"two"}\n', "duplicate public row key"),
        (original + first + b"\n", "row count or digest differs"),
    ]:
        path.write_bytes(changed)
        checked = verify_release_v2(root, release, selection=selection)
        assert checked["status"] == "fail"
        assert any(expected_error in error for error in checked["errors"]), checked
    path.write_bytes(original)
