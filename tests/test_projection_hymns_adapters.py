"""Exact accepted-work routes for retained L744 hymn source profiles."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import ocd_kernel.projection.categories.hymns as hymns
from ocd_kernel.library._common import PipelineError


@pytest.mark.parametrize(
    ("work_id", "module_name", "project_name", "verify_name"),
    [
        (
            "l744-pg33105-chinook-hymns",
            "chinook_hymns",
            "project_chinook_document",
            "verify_chinook_document",
        ),
        (
            "l744-pg33128-gospel-hymns",
            "pg33128_hymns",
            "project_pg33128_document",
            "verify_pg33128_document",
        ),
    ],
)
def test_accepted_dispatch_uses_exact_work_adapter_and_binds_authority(
    monkeypatch, work_id, module_name, project_name, verify_name
):
    from importlib import import_module

    adapter = import_module(f"ocd_kernel.projection.categories.{module_name}")
    authority = {"acceptance": {"path": "acceptance.json", "sha256": "a" * 64}}
    metadata = {
        "identity": {
            "work_id": work_id,
            "textual_form_id": "form",
            "edition_id": "edition",
        },
        "master_path": Path("master.tei.xml"),
        "retained_path": Path("source.html"),
        "language": "mul",
        "representation_revision": "retained-digital-v1",
        "edition": SimpleNamespace(title="Source title"),
        "authority": authority,
        "source_url": None,
        "source_sha256": None,
        "retained_sha256": None,
    }
    monkeypatch.setattr(hymns, "_accepted_metadata", lambda *args: metadata)
    calls = {}

    def project(path, **kwargs):
        calls["project"] = (path, kwargs)
        return {"rows": [{"record_id": "row-1"}], "receipt": {"route": "adapter"}}

    def verify(path, rows, receipt, **kwargs):
        calls["verify"] = (path, rows, receipt, kwargs)
        return []

    monkeypatch.setattr(adapter, project_name, project)
    monkeypatch.setattr(adapter, verify_name, verify)

    result = hymns.project_accepted_hymns(Path("root"), acceptance_path=Path("acceptance.json"))
    assert calls["project"] == (
        metadata["master_path"],
        {
            "retained_path": metadata["retained_path"],
            "identity": metadata["identity"],
            "language": "mul",
            "representation_revision": "retained-digital-v1",
            "edition_title": "Source title",
        },
    )
    assert result["authority"] == authority
    assert result["receipt"]["authority"] == authority

    errors = hymns.verify_accepted_hymns(
        Path("root"),
        acceptance_path=Path("acceptance.json"),
        rows=result["rows"],
        receipt={"route": "adapter", "authority": authority},
    )
    assert errors == []
    path, rows, receipt, kwargs = calls["verify"]
    assert path == metadata["master_path"]
    assert rows == result["rows"]
    assert receipt == {"route": "adapter"}
    assert kwargs["retained_path"] == metadata["retained_path"]
    assert kwargs["identity"] == metadata["identity"]
    assert kwargs["language"] == "mul"


def test_accepted_member_selection_is_exact_and_keeps_other_work_fail_closed():
    from ocd_kernel.projection.categories.chinook_hymns import SOURCE_MEMBER_PATH
    from ocd_kernel.projection.categories.pg33128_hymns import ENVELOPE, SOURCE_MEMBER_PATH as PG33128_PATH

    chinook_member = {"path": SOURCE_MEMBER_PATH, "bytes": 10, "sha256": "a" * 64}
    assert hymns._select_accepted_source_member("l744-pg33105-chinook-hymns", [chinook_member]) == chinook_member
    with pytest.raises(PipelineError, match="only its exact HTML text member"):
        hymns._select_accepted_source_member("l744-pg33105-chinook-hymns", [chinook_member, chinook_member])

    pg33128_members = [
        {"path": path, "bytes": size, "sha256": digest, "position": position}
        for position, (path, size, digest) in enumerate(ENVELOPE, 1)
    ]
    selected = hymns._select_accepted_source_member("l744-pg33128-gospel-hymns", pg33128_members)
    assert selected["path"] == PG33128_PATH
    with pytest.raises(PipelineError, match="complete five-member"):
        hymns._select_accepted_source_member("l744-pg33128-gospel-hymns", pg33128_members[:-1])

    with pytest.raises(PipelineError, match="exactly one retained source member"):
        hymns._select_accepted_source_member("another-hymn-work", [chinook_member, chinook_member])
