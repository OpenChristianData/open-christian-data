"""The Watson derivative writes a fresh destination and preserves prior artifacts."""

import pytest

from build.tools import watson_derive_initial as derivative


def test_save_preserves_existing_artifact_and_writes_fresh_one(tmp_path, monkeypatch):
    monkeypatch.setattr(derivative, "ROOT", tmp_path)
    existing = tmp_path / "existing.py"
    existing.write_text("retained", encoding="utf-8")
    with pytest.raises(FileExistsError, match="Preserve prior Watson artifact"):
        derivative.save("existing.py", "replacement")
    assert existing.read_text(encoding="utf-8") == "retained"
    derivative.save("fresh.py", "new derivative")
    assert (tmp_path / "fresh.py").read_text(encoding="utf-8") == "new derivative"


def test_common_binds_work_identity_and_exact_legacy_pins():
    source = "Farrar frederic-w-farrar farrar a335a3ea251871d23f418434dc95a1dff7e564e1c6ab3539cdcfce449078c8b2 2b213b17e96e7e084bb664e90d664a2c364e0fecc19bcf2cb289145da7da4134"
    assert derivative.common(source) == f"Watson r-a-watson watson {derivative.OLDPIN} {derivative.TEIPIN}"
