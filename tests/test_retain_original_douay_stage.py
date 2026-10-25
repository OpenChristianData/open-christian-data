import pytest

from build.tools import retain_original_douay_stage as retain


def test_missing_durable_library_fails_before_any_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(retain, "BASE", tmp_path / "missing-library")
    monkeypatch.setattr(retain.shutil, "copytree", lambda *a, **k: pytest.fail("copy attempted"))
    with pytest.raises(FileNotFoundError):
        retain.main()
