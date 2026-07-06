"""Tests for generated schema enum constants and freshness checks."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib import _generated_enums  # noqa: E402
from build.lib.schema_enums import get_enum  # noqa: E402

TMP_ROOT = REPO_ROOT / "tests" / "_tmp_generated_enums"


def _reset_tmp_dir(name: str) -> Path:
    path = TMP_ROOT / name
    if path.exists():
        shutil.rmtree(path)  # standards: log/temp rotation
    path.mkdir(parents=True, exist_ok=False)
    return path


@pytest.mark.slow
def test_generated_enums_are_deterministic() -> None:
    temp_dir = _reset_tmp_dir("deterministic")
    output_path = temp_dir / "_generated_enums.py"
    command = [
        sys.executable,
        "build/tools/generate_schema_enums.py",
        "--output",
        str(output_path),
    ]
    subprocess.run(command, check=True, cwd=REPO_ROOT)
    first = output_path.read_text(encoding="utf-8")
    subprocess.run(command, check=True, cwd=REPO_ROOT)
    second = output_path.read_text(encoding="utf-8")
    assert first == second


def test_generated_constants_match_get_enum() -> None:
    assert _generated_enums.STRUCTURED_TEXT__META__TRADITION == get_enum(
        "structured_text", "meta", "tradition"
    )
    assert _generated_enums.STRUCTURED_TEXT__DATA__WORK_KIND == get_enum(
        "structured_text", "data", "work_kind"
    )
    assert _generated_enums.STRUCTURED_TEXT__META__ERA == get_enum(
        "structured_text", "meta", "era"
    )
    assert _generated_enums.DOCTRINAL_DOCUMENT__META__TRADITION == get_enum(
        "doctrinal_document", "meta", "tradition"
    )


def test_new_v3_schema_enums_loadable_via_get_enum() -> None:
    """Asserts get_enum works for all four new v3 schemas and returns expected values.

    Fails until the four new schemas exist and generate_schema_enums.py has been run.
    """
    block_types = get_enum("reconciled_record", "blocks", "block_type")
    assert "paragraph" in block_types
    assert "heading" in block_types
    assert "article" not in block_types, "R35: article is Phase 2; must be absent in Phase 1"
    assert "question" not in block_types, "R35: question is Phase 2; must be absent in Phase 1"
    assert "answer" not in block_types, "R35: answer is Phase 2; must be absent in Phase 1"

    structural_kinds = get_enum(
        "reconciled_record", "blocks", "structural_disagreements", "kind"
    )
    expected_kinds = {
        "neighbour_merged_in_source",
        "block_split_in_source",
        "block_missing_in_source",
        "heading_extra_in_source",
        "heading_missing_in_source",
        "block_type_conflict_in_source",
        "annotation_chunking_disagreement",
        "unclassified",
    }
    for k in expected_kinds:
        assert k in structural_kinds, f"structural_disagreement kind {k!r} missing"

    rendering_roles = get_enum("rendering_catalog", "renderings", "role")
    assert "pd_anchor" in rendering_roles
    assert "pd_attestor" in rendering_roles
    assert "reference_only" in rendering_roles
    assert "pending" in rendering_roles


@pytest.mark.slow
def test_drift_check_exits_nonzero_when_generated_file_is_stale() -> None:
    temp_dir = _reset_tmp_dir("stale")
    generated_path = temp_dir / "_generated_enums.py"
    generated_path.write_text("STALE = frozenset(['bad'])\n", encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        subprocess.run(
            [
                sys.executable,
                "build/tools/check_schema_enums_fresh.py",
                "--generated-path",
                str(generated_path),
            ],
            check=True,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
    assert "stale" in exc_info.value.stdout.lower()
