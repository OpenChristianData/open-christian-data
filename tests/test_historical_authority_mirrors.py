from hashlib import sha256

import pytest

from tests.historical_authority_mirrors import retained_preimage


def test_exact_original_preimage_and_only_authorized_eol_recovery():
    original = b"one\r\ntwo\r\n"
    lf = original.replace(b"\r\n", b"\n")
    digest = sha256(original).hexdigest()
    assert retained_preimage(original, digest, len(original), allow_eol=False) == original
    assert retained_preimage(lf, digest, len(original), allow_eol=True) == original
    assert retained_preimage(original, sha256(lf).hexdigest(), len(lf), allow_eol=True) == lf
    with pytest.raises(ValueError, match="complete original SHA"):
        retained_preimage(lf, digest, len(original), allow_eol=False)


@pytest.mark.parametrize("changed,size", [(b"changed", 7), (b"same", 5), (b"same ", 5)])
def test_unexplained_content_or_size_never_becomes_original_authority(changed, size):
    with pytest.raises(ValueError, match="complete original SHA"):
        retained_preimage(changed, sha256(b"same").hexdigest(), size, allow_eol=True)


def test_davis_current_mirror_preserves_original_and_binds_reviewed_code(tmp_path, monkeypatch):
    from pathlib import Path
    from tests import historical_authority_mirrors as mirrors

    repository = Path(__file__).resolve().parents[1]
    original = repository / mirrors.CASES["davis"]["manifest"]
    before = original.read_bytes()
    monkeypatch.setattr(mirrors, "resolve_repo_path", lambda _root, _path: tmp_path / "library" / "raw")
    _root, manifest = mirrors.prepare_historical_mirror(repository, tmp_path / "mirror", "davis")
    assert original.read_bytes() == before
    assert (manifest.parent / "original-source-manifest.json").read_bytes() == before
