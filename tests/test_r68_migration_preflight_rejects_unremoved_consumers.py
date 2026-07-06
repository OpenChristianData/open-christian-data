from __future__ import annotations

from pathlib import Path


R68_TARGETS = [
    "build/validate.py",
    "build/lib/review_warnings.py",
    "build/lib/render_strategies/commentary.py",
    "tests/test_render_review_html.py",
]


def _stage_r68_targets(root: Path, with_removed_consumers: bool) -> None:
    for rel_path in R68_TARGETS:
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if with_removed_consumers:
            body = "def clean_consumer():\n    return 'kept text fields only'\n"
        else:
            body = (
                "def stale_consumer(entry):\n"
                "    return entry.get('summary') or entry.get('key_quote_review_status')\n"
            )
        target.write_text(body, encoding="utf-8")


def test_r68_migration_preflight_rejects_unremoved_consumers(tmp_path):
    from build.tools.migrate_schaff_herzog import find_unremoved_consumers, run_r68_preflight

    _stage_r68_targets(tmp_path, with_removed_consumers=False)
    hits = find_unremoved_consumers(tmp_path)
    assert {str(path).replace("\\", "/") for path, _line in hits} == set(R68_TARGETS)
    assert all(line_number == 2 for _path, line_number in hits)

    result = run_r68_preflight(tmp_path)
    assert result.returncode != 0
    for rel_path in R68_TARGETS:
        assert rel_path in result.stderr
        assert ":2" in result.stderr
    assert not (tmp_path / "data").exists()

    clean_root = tmp_path / "clean"
    _stage_r68_targets(clean_root, with_removed_consumers=True)
    assert find_unremoved_consumers(clean_root) == []
    assert run_r68_preflight(clean_root).returncode == 0
