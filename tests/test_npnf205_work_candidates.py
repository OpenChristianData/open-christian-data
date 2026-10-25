"""Exact source-root fidelity checks for fourteen Gregory NPNF2-05 works."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest
from lxml import etree

from build.tei.npnf205_work_oracle import check
from build.tools import prepare_npnf205_work_candidates as family
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import compiled_schema


DURABLE = Path(r"D:\Library\Open Christian Data\candidate-reviews\npnf205-fourteen-work-candidates-20260926")
SCRATCH = Path(r"C:\Scratch\npnf205\candidates3")


def _read(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def test_exact_fourteen_source_roots_reproduce_and_validate() -> None:
    plan = json.loads(_read(family.ROOT / family.PLAN))
    receipt = json.loads(_read(DURABLE / "receipt.json"))
    prior = json.loads(_read(SCRATCH / "receipt.json"))
    assert len(plan["works"]) == len(receipt["works"]) == len(prior["works"]) == 14
    assert len(plan["volume_direct_divisions"]) == 14
    assert len(plan["volume_direct_non_elements"]) == 2
    assert receipt["source_sha256"] == family.SOURCE_SHA
    assert receipt["canonical_install"] == "not-performed"
    assert sha256(_read(DURABLE / "receipt.json")).hexdigest() == "9b88b39570265cf1fedc4b64f97eb94910fbbf291432da0e2238f092bcc44312"
    assert sha256(_read(SCRATCH / "receipt.json")).hexdigest() == "cc82601b6c7018aad424795bd54dcb2ad37c6f626fe1c9e41e369c0031e6ec60"
    prior_by_id = {row["work_id"]: row for row in prior["works"]}
    assert set(prior_by_id) == {row["work_id"] for row in receipt["works"]}
    for row in receipt["works"]:
        manifest = SourceManifest.load(family.ROOT / row["manifest_path"],
                                       repository_root=family.ROOT)
        package = CandidatePackage.load(Path(_io_path(Path(row["candidate_root"]) / "package")))
        report = json.loads(_read(Path(row["candidate_root"]) / "validation.json"))
        assert package.sha256 == row["candidate_sha256"]
        assert report["status"] == "pass" and report["findings"] == []
        # Each frozen package retains its own historical manifest identity.
        assert package.manifest["source_manifest"]["sha256"] == row["manifest_sha256"]
        previous_row = prior_by_id[row["work_id"]]
        previous = CandidatePackage.load(Path(_io_path(Path(previous_row["candidate_root"]) / "package")))
        assert previous.sha256 == previous_row["candidate_sha256"]
        assert previous.member_names == package.member_names
        for name in package.member_names:
            if name != "manifest.json":
                assert previous.member_bytes(name) == package.member_bytes(name), name
        # The current exact source/profile independently validates the retained text.
        profile = json.loads(_read(family.ROOT / row["profile_path"]))
        policy = json.loads(_read(family.ROOT / family.POLICY))
        facts = check(_read(family.ROOT / family.SOURCE), package.member_bytes("content.tei.xml"),
                      source_root_id=profile["source_root_id"], source_parent_id=profile["source_parent_id"],
                      source_tag=profile["source_tag"], work_id=row["work_id"],
                      legacy_policy=json.loads(_read(family.ROOT / family.LEGACY_POLICY)),
                      exceptions=policy["neutral_reference_exceptions"] if row["work_id"] == "gregory-of-nyssa-letters" else [])
        assert facts["element_count"] == profile["element_count"]
        assert next(a["sha256"] for a in manifest.record["authorities"] if a["role"] == "primary-source") == family.SOURCE_SHA
        assert row["native_prose_rows"] == 1
        assert row["native_prose_independent_check"] == "pass"
        compiled_schema().assertValid(etree.fromstring(package.member_bytes("content.tei.xml")))


def test_oracle_rejects_invented_text_omitted_note_and_wrong_root() -> None:
    receipt = json.loads(_read(DURABLE / "receipt.json"))
    row = next(x for x in receipt["works"]
               if x["work_id"] == "gregory-of-nyssa-not-three-gods")
    profile = json.loads(_read(family.ROOT / row["profile_path"]))
    policy = json.loads(_read(family.ROOT / family.LEGACY_POLICY))
    source = _read(family.ROOT / family.SOURCE)
    candidate = _read(Path(row["candidate_root"]) / "package/content.tei.xml")
    kwargs = {"source_root_id": profile["source_root_id"],
              "source_parent_id": profile["source_parent_id"],
              "source_tag": profile["source_tag"], "work_id": profile["work_id"],
              "legacy_policy": policy, "exceptions": []}
    assert check(source, candidate, **kwargs)["element_count"] == profile["element_count"]
    document = etree.fromstring(candidate)
    body = document.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
    assert body is not None
    text = next(node for node in body.iter("{http://www.tei-c.org/ns/1.0}p") if node.text and node.text.strip())
    text.text = (text.text or "") + " invented"
    with pytest.raises(ValueError, match="text or tail drift"):
        check(source, etree.tostring(document), **kwargs)
    document = etree.fromstring(candidate)
    note = document.find(".//{http://www.tei-c.org/ns/1.0}note")
    assert note is not None
    note.getparent().remove(note)
    with pytest.raises(ValueError, match="TEI source child omitted|TEI tag or attribute drift"):
        check(source, etree.tostring(document), **kwargs)
    with pytest.raises(ValueError, match="retained XML hash differs"):
        check(source + b" ", candidate, **kwargs)
    with pytest.raises(ValueError, match="source work root parent|TEI tag or attribute drift"):
        check(source, candidate, **(kwargs | {"source_root_id": "viii.iv"}))


def test_letters_keep_complete_collection_and_neutral_epistle_reference() -> None:
    receipt = json.loads(_read(DURABLE / "receipt.json"))
    row = next(x for x in receipt["works"] if x["work_id"] == "gregory-of-nyssa-letters")
    profile = json.loads(_read(family.ROOT / row["profile_path"]))
    policy = json.loads(_read(family.ROOT / family.POLICY))
    source = _read(family.ROOT / family.SOURCE)
    candidate = _read(Path(row["candidate_root"]) / "package/content.tei.xml")
    result = check(source, candidate, source_root_id="xiii", source_parent_id=None,
                   source_tag="div1", work_id=row["work_id"],
                   legacy_policy=json.loads(_read(family.ROOT / family.LEGACY_POLICY)),
                   exceptions=policy["neutral_reference_exceptions"])
    assert result["element_count"] == profile["element_count"] == 597
    tree = etree.fromstring(candidate)
    body = tree.find("{http://www.tei-c.org/ns/1.0}text/{http://www.tei-c.org/ns/1.0}body")
    assert body is not None and len(body[0].findall("{http://www.tei-c.org/ns/1.0}div")) == 19
    assert sha256(candidate).hexdigest() == row["candidate_tei_sha256"]
