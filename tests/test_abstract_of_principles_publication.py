from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from build.tools.project_abstract_of_principles import (
    ACCEPTANCE,
    EXPECTED_ACCEPTANCE_SHA256,
    EXPECTED_MASTER_SHA256,
    MASTER,
    ROOT,
    SOURCE_SHA256,
    build_publication,
)
from ocd_kernel.projection.categories.doctrinal_documents import (
    project_accepted_doctrinal_documents,
    verify_accepted_doctrinal_documents,
)
from ocd_kernel.tei.install_accepted import _io_path


def test_actual_master_projection_and_mutation_rejection(tmp_path: Path) -> None:
    master_before = _io_path(ROOT / MASTER).read_bytes()
    acceptance_before = _io_path(ROOT / ACCEPTANCE).read_bytes()
    result = build_publication(
        ROOT,
        output_dir=tmp_path / "publication",
        credit_path=tmp_path / "SOURCE_CREDIT.md",
    )
    assert result["status"] == "pass"
    assert result["source_sha256"] == SOURCE_SHA256
    assert result["master_sha256"] == EXPECTED_MASTER_SHA256
    assert result["acceptance_sha256"] == EXPECTED_ACCEPTANCE_SHA256
    assert result["projection_view_sha256"] == EXPECTED_MASTER_SHA256
    assert result["row_count"] == 20
    assert len((tmp_path / "publication/doctrinal-documents.jsonl").read_text(encoding="utf-8").splitlines()) == 20
    assert "rights review" in (tmp_path / "SOURCE_CREDIT.md").read_text(encoding="utf-8")

    output = project_accepted_doctrinal_documents(
        _io_path(ROOT), acceptance_path=_io_path(ROOT / ACCEPTANCE)
    )
    assert verify_accepted_doctrinal_documents(
        _io_path(ROOT),
        acceptance_path=_io_path(ROOT / ACCEPTANCE),
        rows=output["rows"],
        receipt=output["receipt"],
    ) == []
    mutated = deepcopy(output["rows"])
    mutated[0]["content"] += " altered"
    assert verify_accepted_doctrinal_documents(
        _io_path(ROOT),
        acceptance_path=_io_path(ROOT / ACCEPTANCE),
        rows=mutated,
        receipt=output["receipt"],
    )
    assert sha256(_io_path(ROOT / MASTER).read_bytes()).hexdigest() == EXPECTED_MASTER_SHA256
    assert sha256(_io_path(ROOT / ACCEPTANCE).read_bytes()).hexdigest() == EXPECTED_ACCEPTANCE_SHA256
    assert _io_path(ROOT / MASTER).read_bytes() == master_before
    assert _io_path(ROOT / ACCEPTANCE).read_bytes() == acceptance_before
