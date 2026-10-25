"""Producer output tests; these do not substitute for independent route review."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from build.tei.se_candidate_reconstruction import _convert
from ocd_kernel.tei.validate import validate_file


@pytest.fixture
def producer_input(tmp_path):
    root = tmp_path
    source = root / "retained/src/epub"
    (source / "text").mkdir(parents=True)
    (source / "images").mkdir()
    (source / "images/logo.svg").write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><text>Logo</text></svg>')
    (source / "content.opf").write_text('<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="one" href="text/one.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/></spine></package>', encoding="utf-8")
    (source / "text/one.xhtml").write_text('<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>One</title></head><body epub:type="bodymatter"><section id="one" epub:type="chapter"><h2>One</h2><p>Before <img src="../images/logo.svg" alt="Logo"/> after.</p></section></body></html>', encoding="utf-8")
    config = root / "config.json"
    config.write_text(json.dumps({"title": "One", "author": "Example", "source_url": "https://standardebooks.org/ebooks/example", "source_revision": "abc"}), encoding="utf-8")
    readme = root / "README.source.md"
    readme.write_text("Retained test source; nonaccepted.\n", encoding="utf-8")
    members = []
    paths = {"work-config": config, "source-attribution-readme": readme}
    for index, path in enumerate(sorted((root / "retained").rglob("*"))):
        if not path.is_file():
            continue
        name = f"member-{index}"
        paths[name] = path
        members.append({"path": path.relative_to(root / "retained").as_posix(), "authority": name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
                        "disposition": "readable-text" if path.suffix == ".xhtml" else "embedded-image" if path.suffix == ".svg" else "support-evidence", "reason": "Fixture source scope"})
    profile = root / "profile.json"
    profile.write_text(json.dumps({"contract": "ocd-standard-ebooks-reconstruction-profile-v1", "work_id": "one", "source_root": "retained", "source_revision": "abc", "image_policy": "exact-bytes-data-uri", "members": sorted(members, key=lambda row: row["path"]), "unresolved": []}), encoding="utf-8")
    paths["reconstruction-profile"] = profile
    # The fixture supplies already-bound files; SourceManifest's own cryptographic
    # and callable validation is covered by the kernel contract suite.
    fixture = SimpleNamespace(repository_root=root, sha256="0" * 64, record={"work_id": "one", "authorities": [{"name": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for name, path in paths.items()]}, verify=lambda: None, authority_path=lambda name: paths[name])
    return fixture


def test_flat_producer_returns_self_contained_five_members(producer_input, tmp_path):
    result = _convert(producer_input)
    assert set(result) == {"content.tei.xml", "source-accountability.json", "provenance.json", "unresolved.jsonl", "README.source.md"}
    assert b"data:image/svg+xml;base64," in result["content.tei.xml"]
    assert result == _convert(producer_input)
    output = tmp_path / "result.xml"
    output.write_bytes(result["content.tei.xml"])
    assert validate_file(output) == []
    accounting = json.loads(result["source-accountability.json"])
    assert len(accounting["members"]) == 3
    assert all(member["xml_carriers"] for member in accounting["members"])


def test_producer_rejects_uninventoried_retained_file(producer_input):
    (producer_input.repository_root / "retained/extra.txt").write_text("Unaccounted", encoding="utf-8")
    with pytest.raises(ValueError, match="envelope"):
        _convert(producer_input)


def test_producer_rejects_changed_source_bytes(producer_input):
    image = producer_input.repository_root / "retained/src/epub/images/logo.svg"
    image.write_bytes(b"Changed")
    with pytest.raises(ValueError, match="content drifted"):
        _convert(producer_input)
