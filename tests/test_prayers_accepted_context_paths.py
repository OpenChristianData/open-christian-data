"""Prayer accepted authority paths retain containment across Windows I/O spellings."""
from hashlib import sha256
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ocd_kernel.lib.path_io import io_path, resolve_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.projection.categories import prayers


def _fixture(tmp_path, monkeypatch, external=None, extended_acquisition=False):
    from ocd_kernel.library import acquisitions, identities
    from ocd_kernel.tei import acceptance
    root = tmp_path / "root"
    root.mkdir()
    paths = {key: root / f"{key}.json" for key in ("acceptance", "work", "master", "acquisition")}
    if external:
        paths[external] = tmp_path / f"outside-{external}.json"
    for key, path in paths.items():
        path.write_bytes(key.encode())
    identity = {"work_id": "work", "textual_form_id": "form", "edition_id": "edition", "acquisition_id": "acq"}
    accepted = {"promotion": {"status": "promoted"}, "identity": identity, "representation_revision": {"id": "r1"}}
    work = SimpleNamespace(work_id="work", path=paths["work"], record={"textual_forms": [{"textual_form_id": "form", "language": "en"}]})
    edition = SimpleNamespace(textual_form_id="form", edition_id="edition", path=paths["master"], title="Prayer fixture", record={"category": "prayers", "language": "en"})
    edition.record["edition_id"] = edition.edition_id
    work.record["textual_forms"][0]["editions"] = [edition.record]
    monkeypatch.setattr(acceptance, "validate_acceptance", lambda path, root: accepted)
    monkeypatch.setattr(identities, "edition_by_id", lambda root, edition_id, *, work_id: (work, edition))
    acquired = io_path(paths["acquisition"]) if extended_acquisition else paths["acquisition"]
    monkeypatch.setattr(acquisitions, "acquisition_for_edition", lambda *a, **k: (acquired, {}))
    return root, paths


@pytest.mark.parametrize("extended_root,extended_acquisition", ((False, False), (False, True), (True, False), (True, True)))
def test_same_authorities_with_mixed_extended_paths_remain_relative(tmp_path, monkeypatch, extended_root, extended_acquisition):
    if os.name != "nt" and (extended_root or extended_acquisition):
        pytest.skip("Windows extended path spelling")
    root, paths = _fixture(tmp_path, monkeypatch, extended_acquisition=extended_acquisition)
    context = prayers._accepted_context(io_path(root) if extended_root else root, paths["acceptance"])
    assert context["root"] == resolve_path(root)
    for key, path in paths.items():
        assert context["authority"][key] == {"path": path.relative_to(root).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}


@pytest.mark.parametrize("external", ("acceptance", "work", "master", "acquisition"))
def test_each_real_outside_authority_still_fails_closed(tmp_path, monkeypatch, external):
    root, paths = _fixture(tmp_path, monkeypatch, external=external)
    with pytest.raises(PipelineError, match="accepted authority outside root"):
        prayers._accepted_context(root, paths["acceptance"])
