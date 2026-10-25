"""Safety checks for Standard Ebooks source-manifest preparation."""

from pathlib import Path
import subprocess

import pytest

from build.tools import prepare_se_candidate_manifests


def test_preparation_rejects_dirty_retained_checkout_before_writing(tmp_path, monkeypatch):
    slug = "g-k-chesterton_heretics"
    work_id = "heretics"
    source_root = tmp_path / "raw/standard_ebooks" / slug
    source_root.mkdir(parents=True)
    source_file = source_root / "src/epub/text/chapter.xhtml"
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"<html>retained</html>\n")

    git = ["git", "-C", str(source_root)]
    subprocess.run(git + ["init", "--quiet"], check=True, capture_output=True)
    subprocess.run(git + ["config", "user.name", "OCD Test"], check=True)
    subprocess.run(
        git + ["config", "user.email", "ocd-test@example.invalid"],
        check=True,
    )
    subprocess.run(git + ["add", "--", "src/epub/text/chapter.xhtml"], check=True)
    subprocess.run(git + ["commit", "--quiet", "-m", "retained source"], check=True)
    source_file.write_bytes(b"<html>dirty</html>\n")

    output_dir = tmp_path / "sources/standard-ebooks" / slug
    output_dir.mkdir(parents=True)
    monkeypatch.setattr(
        prepare_se_candidate_manifests,
        "WORKS",
        {slug: (work_id, "LIB-086")},
    )
    monkeypatch.setattr(
        prepare_se_candidate_manifests,
        "_closure",
        lambda *_args: ("0" * 64, []),
    )

    with pytest.raises(ValueError, match=f"Retained SE checkout is dirty: {slug}"):
        prepare_se_candidate_manifests.prepare(tmp_path)

    assert not (output_dir / "reconstruction-profile.json").exists()
    assert not (output_dir / "validation-policy.json").exists()
    assert not (output_dir / f"{work_id}.source-manifest.json").exists()
