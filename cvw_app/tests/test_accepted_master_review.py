"""Review copies reuse current acceptance; they cannot reseal different sources or text."""
import json
from types import SimpleNamespace

import pytest

from build.tools import prepare_cvw_review as review


@pytest.fixture
def review_copy(tmp_path, monkeypatch):
    (tmp_path / "master.xml").write_bytes(b"<TEI>Unchanged accepted text.</TEI>")
    member = dict(path="source.txt", bytes=6, sha256="a" * 64)
    (tmp_path / "acquisition.json").write_text(json.dumps(dict(retained_files=[member])), encoding="utf-8")
    (tmp_path / "acceptance.json").write_text("{}", encoding="utf-8")
    implementation = tmp_path / review.IMPLEMENTATION
    implementation.parent.mkdir(parents=True)
    implementation.write_text("# bound implementation", encoding="utf-8")
    acquisition = dict(path="acquisition.json", bytes=100, sha256="b" * 64)
    master = dict(path="master.xml", bytes=39, sha256="c" * 64)
    record = dict(identity=dict(work_id="book"), promotion=dict(status="promoted", master=master), source=dict(source_manifest=acquisition))
    authorities = [dict(member, role="primary-source", name="source"),
        dict(acquisition, name="acquisition", role="acquisition-selection-authority"),
        dict(master, name="accepted-master", role="accepted-master"),
        dict(path="acceptance.json", name="acceptance-record", role="existing-acceptance-proof")]
    manifest = SimpleNamespace(repository_root=tmp_path, sha256="d" * 64,
        record=dict(work_id="book", authorities=authorities, validator=dict(import_closure_sha256=review._sha(review._json([])))),
        verify=lambda: None, authority_path=lambda name: tmp_path / next(item["path"] for item in authorities if item["name"] == name))
    candidate = SimpleNamespace(member_bytes=lambda name: (tmp_path / "master.xml").read_bytes())
    checked = []
    def check_acceptance(path, *, root):
        checked.append((path, root))
        return record
    monkeypatch.setattr(review, "validate_acceptance", check_acceptance)
    monkeypatch.setattr(review, "_closure", lambda root: [])
    monkeypatch.setattr(review, "_source_authorities", lambda root, acquired: [dict(member, role="primary-source", name="source")])
    monkeypatch.setattr(review, "_validation_authority_bindings", lambda manifest: dict.fromkeys(
        ("source_sha256", "profile_sha256", "package_schema_sha256", "xsd_sha256", "policy_sha256"), "e" * 64))
    monkeypatch.setattr(review, "verify_mechanical_facts", lambda *args: SimpleNamespace(as_record=lambda: dict(status="pass")))
    return manifest, candidate, record, checked


def test_review_copy_checks_existing_acceptance_and_preserves_master(review_copy):
    manifest, candidate, _, checked = review_copy
    assert review._oracle(manifest, candidate) == dict(status="pass")
    assert checked == [(manifest.authority_path("acceptance-record"), manifest.repository_root)]
    produced = review._convert(manifest)
    assert len(produced) == 5
    assert produced["content.tei.xml"] == candidate.member_bytes("content.tei.xml")


@pytest.mark.parametrize("mutation", ["candidate", "source", "master", "acquisition", "closure", "acceptance"])
def test_review_copy_rejects_changed_evidence(review_copy, monkeypatch, mutation):
    manifest, candidate, record, _ = review_copy
    if mutation == "candidate":
        candidate.member_bytes = lambda name: b"<TEI>Different text</TEI>"
    elif mutation == "source":
        manifest.record["authorities"][0]["sha256"] = "f" * 64
    elif mutation == "master":
        record["promotion"]["master"] = dict(path="different.xml", bytes=39, sha256="c" * 64)
    elif mutation == "acquisition":
        record["source"]["source_manifest"] = dict(path="different.json", bytes=100, sha256="b" * 64)
    elif mutation == "closure":
        manifest.record["validator"]["import_closure_sha256"] = "f" * 64
    else:
        def stale(*args, **kwargs):
            raise ValueError("existing acceptance evidence drifted")
        monkeypatch.setattr(review, "validate_acceptance", stale)
    with pytest.raises(ValueError):
        review._oracle(manifest, candidate)


def test_member_set_keeps_acquired_order_and_binds_the_envelope(tmp_path):
    from hashlib import sha256
    members=[]
    for name in ("book-2.xhtml", "book-1.xhtml"):
        payload=name.encode()
        (tmp_path/name).write_bytes(payload)
        members.append(dict(path=name, bytes=len(payload), sha256=sha256(payload).hexdigest()))
    (tmp_path/"members.json").write_text("{}", encoding="utf-8")
    result=review._source_authorities(tmp_path, dict(source_kind="retained-member-set", source_path="members.json", retained_files=members))
    assert [item["path"] for item in result] == ["book-2.xhtml", "book-1.xhtml", "members.json"]
    assert [item["role"] for item in result] == ["primary-source", "primary-source", "retained-member-set"]
