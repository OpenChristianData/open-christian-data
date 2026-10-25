import json

from build.tools.report_first_publication_rights_inputs import _acquisitions


def test_acquisitions_reads_declared_form_tree_not_integration_copies(tmp_path):
    root = tmp_path
    work_dir = root / "library" / "works" / "sample-work"
    canonical = (
        work_dir
        / "forms"
        / "sample-form"
        / "editions"
        / "sample-edition"
        / "acquisitions"
        / "sample-acquisition.json"
    )
    staged_copy = (
        work_dir
        / "forms"
        / "sample-form"
        / "editions"
        / "sample-edition"
        / "integration"
        / "candidate"
        / "acquisitions"
        / "sample-acquisition.json"
    )
    record = {
        "acquisition_id": "sample-acquisition",
        "edition_id": "sample-edition",
        "provider": "Example source",
        "retained_files": [],
    }
    for path in (canonical, staged_copy):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")

    acquisitions = _acquisitions(work_dir, root)

    assert len(acquisitions) == 1
    assert acquisitions[0]["path"] == canonical.relative_to(root).as_posix()
