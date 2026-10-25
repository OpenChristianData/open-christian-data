from __future__ import annotations

import hashlib

from build.lib.paths import REPO_ROOT
from build.tei import regenerate_projections


def _artifact_state(path):
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_mtime_ns, stat.st_size


def test_discover_excludes_receipts_that_are_not_committed(monkeypatch) -> None:
    present = sorted((REPO_ROOT / "ir").rglob("*.loss.json"))
    excluded = present[0]
    checked = []

    def fake_is_committed(path, *, repository_root, revision):
        checked.append((path, repository_root, revision))
        return path != excluded

    monkeypatch.setattr(regenerate_projections, "is_committed_path", fake_is_committed)

    projections = regenerate_projections.discover(REPO_ROOT)

    assert excluded not in {projection.receipt_path for projection in projections}
    assert checked == [(path, REPO_ROOT, "HEAD") for path in present]


def test_list_reports_every_committed_projection_without_regenerating(
    capsys, monkeypatch
) -> None:
    projections = regenerate_projections.discover(REPO_ROOT)
    paths = {
        path
        for projection in projections
        for path in (projection.receipt_path, projection.output_path)
    }
    before = {path: _artifact_state(path) for path in paths}

    def fail_regenerate(*args, **kwargs):
        raise AssertionError("--list must not regenerate or write artifacts")

    monkeypatch.setattr(regenerate_projections, "regenerate", fail_regenerate)

    assert len(projections) == 15
    assert regenerate_projections.main(["--list"]) == 0
    assert {path: _artifact_state(path) for path in paths} == before

    output = capsys.readouterr().out
    for family in sorted({projection.family for projection in projections}):
        count = sum(projection.family == family for projection in projections)
        assert f"{family:<12} {count} projection(s)" in output
    assert "total: 15 projection(s)" in output
