"""Focused checks for the retained-source PG 37311 publication projection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

import pytest

from build.tools.project_woolman_pg37311 import (
    ACCEPTANCE_SHA256,
    EDITION,
    MASTER_SHA256,
    OUTPUT,
    ROOT,
    WORK_ID,
    build_projection_view,
)
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories.native_documents import (
    project_document,
    verify_document,
)
from ocd_kernel.projection.categories.woolman_pg37311_source_profile import PROFILE
from ocd_kernel.tei.validate import validate_file


def _canonical_jsonl(rows: list[dict]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )


def test_woolman_projection_adapter_keeps_text_and_passes_independent_check() -> None:
    master_path = ROOT / EDITION / "master.tei.xml"
    master_bytes = master_path.read_bytes()
    assert hashlib.sha256(master_bytes).hexdigest() == MASTER_SHA256

    view_bytes, audit = build_projection_view(master_bytes)
    with tempfile.TemporaryDirectory(prefix="woolman-proj-test-") as directory:
        view = Path(directory) / "view.xml"
        view.write_bytes(view_bytes)
        assert validate_file(master_path) == []
        assert validate_file(view) == []
        assert audit["text_subtree_unchanged"] is True
        assert audit["source_text_characters"] == audit["view_text_characters"]
        assert audit["source_text_sha256"] == audit["view_text_sha256"]
        assert audit["source_element_mappings"] == {
            "source-p": 872,
            "source-hr": 54,
            "source-blockquote": 20,
            "source-div": 7,
            "source-header": 1,
            "source-footer": 1,
        }
        assert len(audit["removed_cell_locator_attributes"]) == 18

        identity = {
            "work_id": WORK_ID,
            "textual_form_id": "english",
            "edition_id": "everyman-402-1910-electronic",
        }
        with pytest.raises(ValueError, match="exact accepted master"):
            project_document(
                view, identity=identity, language="en", category="prose",
                representation_revision="john-woolman-pg37311-accepted-v1",
                edition_title="Project Gutenberg eBook 37311 electronic witness of The Journal, with Other Writings of John Woolman (Everyman's Library no. 402, 1910)",
                projection_profile=PROFILE, _allow_acceptance_metadata=True,
            )
        result = project_document(
            master_path,
            identity=identity,
            language="en",
            representation_revision="john-woolman-pg37311-accepted-v1",
            edition_title="Project Gutenberg eBook 37311 electronic witness of The Journal, with Other Writings of John Woolman (Everyman's Library no. 402, 1910)",
            category="prose",
            projection_profile=PROFILE,
            _allow_acceptance_metadata=True,
        )
        assert len(result["rows"]) == 12
        assert all(row["work_id"] == WORK_ID for row in result["rows"])
        assert verify_document(
            master_path,
            result["rows"],
            result["receipt"],
            identity=identity,
            language="en",
            representation_revision="john-woolman-pg37311-accepted-v1",
            edition_title="Project Gutenberg eBook 37311 electronic witness of The Journal, with Other Writings of John Woolman (Everyman's Library no. 402, 1910)",
            category="prose",
            projection_profile=PROFILE,
            _allow_acceptance_metadata=True,
        ) == []


@pytest.mark.parametrize(
    "old,new",
    [
        (b'unit="source-tbody-start"', b'unit="source-tbody-wrong"'),
        (b'n="52.1.1.1"', b'n="52.1.1.2"'),
    ],
)
def test_woolman_projection_adapter_rejects_changed_source_structure(
    old: bytes, new: bytes
) -> None:
    master_bytes = (ROOT / EDITION / "master.tei.xml").read_bytes()
    assert old in master_bytes
    with pytest.raises(PipelineError):
        build_projection_view(master_bytes.replace(old, new, 1))


def test_woolman_saved_projection_artifacts_bind_current_accepted_master() -> None:
    master_bytes = (ROOT / EDITION / "master.tei.xml").read_bytes()
    acceptance_bytes = (ROOT / EDITION / "acceptance.json").read_bytes()
    assert hashlib.sha256(acceptance_bytes).hexdigest() == ACCEPTANCE_SHA256
    rows_bytes = (ROOT / OUTPUT / "prose.jsonl").read_bytes()
    rows = [json.loads(line) for line in rows_bytes.splitlines()]
    receipt = json.loads((ROOT / OUTPUT / "projection-receipt.json").read_bytes())
    correspondence = json.loads(
        (ROOT / OUTPUT / "independent-correspondence.json").read_bytes()
    )
    assert len(rows) == 12
    assert receipt["status"] == correspondence["status"] == "pass"
    assert receipt["master_sha256"] == hashlib.sha256(master_bytes).hexdigest()
    assert receipt["acceptance_sha256"] == hashlib.sha256(acceptance_bytes).hexdigest()
    assert receipt["rows_sha256"] == hashlib.sha256(rows_bytes).hexdigest()
    assert receipt["rows"] == correspondence["rows"] == 12
    assert receipt["rights"] == "not-cleared"
    assert receipt["publication"] == "not-authorized"
    assert _canonical_jsonl(rows) == rows_bytes


def test_current_writer_uses_scoped_profile_and_retains_source_bindings(monkeypatch) -> None:
    from build.tools import project_woolman_pg37311 as writer

    captured = {}

    def capture_generation(root, files):
        assert root.resolve() == ROOT.resolve()
        captured.update(files)

    monkeypatch.setattr(writer, "_write_generation", capture_generation)
    receipt = writer.run(ROOT)
    assert set(captured) == {"prose.jsonl", "projection-receipt.json", "independent-correspondence.json"}
    assert receipt["status"] == "pass" and receipt["rows"] == 12
    assert receipt["master_sha256"] == MASTER_SHA256
    assert receipt["projection_view_sha256"] == MASTER_SHA256
    assert receipt["projector_profile"] == PROFILE
    assert receipt["acceptance_sha256"] == ACCEPTANCE_SHA256
    assert receipt["rows_sha256"] == hashlib.sha256(captured["prose.jsonl"]).hexdigest()
    assert json.loads(captured["projection-receipt.json"]) == receipt
    independent = json.loads(captured["independent-correspondence.json"])
    assert independent["status"] == "pass" and independent["errors"] == []
    assert independent["rows_sha256"] == receipt["rows_sha256"]
    assert receipt["rights"] == "not-cleared" and receipt["publication"] == "not-authorized"
