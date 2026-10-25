"""WU-03: a bounded shared ThML collection remains fully accountable."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from lxml import etree

from build.tei.selected_thml import _convert
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.source_selection import (
    derive_source_carrier_inventory,
    verify_complete_source_accounting,
    verify_source_selection,
)
from ocd_kernel.reconstruction import CandidatePackage
from ocd_kernel.release.assemble import assemble_release_v2
from ocd_kernel.release.verify import verify_release_v2
from ocd_kernel.tei.acceptance import promote_accepted_master, validate_acceptance
from ocd_kernel.tei.reviewed_composition import compose_reviewed_documents
from tests.test_selected_thml_lifecycle import _fixture


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_package(root: Path, work_id: str, produced: dict[str, bytes]) -> CandidatePackage:
    package_root = root / "packages" / work_id
    package_root.mkdir(parents=True)
    for name, content in produced.items():
        (package_root / name).write_bytes(content)
    manifest = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": "wu03-shared-fixture",
        "source_manifest": {"path": "fixture-source-manifest.json", "sha256": "0" * 64},
        "converter": {"id": "ocd-selected-thml-to-tei", "version": "1", "callable": "_convert"},
        "package_schema": {"path": "candidate-package.schema.json", "sha256": "0" * 64},
        "members": [
            {"name": name, "bytes": len(produced[name]), "sha256": _sha(produced[name])}
            for name in sorted(produced)
        ],
    }
    (package_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return CandidatePackage.load(package_root)


@pytest.fixture
def shared_collection(tmp_path: Path):
    root = tmp_path / "fixture"
    source_path = root / "retained" / "shared.xml"
    source_path.parent.mkdir(parents=True)
    raw = (
        b'<ThML><ThML.head><DC.Title>Shared Fixture Source</DC.Title></ThML.head>'
        b'<ThML.body>'
        b'<div1 id="shared" title="Shared credits"><p id="credit">Shared context.</p></div1>'
        b'<div1 id="child-a" title="Child A"><p id="a-text">Alpha.</p></div1>'
        b'<div1 id="child-b" title="Child B"><p id="b-text">Beta.</p></div1>'
        b'<div1 id="excluded" title="Excluded index"><p>Index only.</p></div1>'
        b'<div1 id="pending" title="Pending child"><p>Pending text.</p></div1>'
        b'</ThML.body></ThML>'
    )
    source_path.write_bytes(raw)
    member = {
        "path": "retained/shared.xml",
        "bytes": len(raw),
        "sha256": _sha(raw),
        "media_type": "application/xml",
    }

    def declaration(work_id: str, native_id: str) -> tuple[dict, dict]:
        acquisition_id = f"acq-{work_id}"
        acquisition = {
            "schema_version": "2.0",
            "acquisition_id": acquisition_id,
            "edition_id": f"edition-{work_id}",
            "provider": "WU-03 fixture",
            "url": "https://example.test/shared.xml",
            "retained_files": [member],
            "source_path": member["path"],
            "source_bytes": member["bytes"],
            "source_sha256": member["sha256"],
            "source_scope": "bounded shared fixture",
            "source_selection": {
                "selection_id": f"selection-{work_id}",
                "work_id": work_id,
                "member_path": member["path"],
                "units": [{"native_id": native_id, "title": native_id.replace("-", " ").title(), "role": "body"}],
                "dependencies": [{
                    "native_id": "credit",
                    "text_sha256": _sha(b"Shared context."),
                    "purpose": "source-credit",
                }],
            },
        }
        work = {
            "schema_version": "2.0",
            "work_id": work_id,
            "title": native_id.replace("-", " ").title(),
            "evidence": [member["path"] + "#" + native_id, member["path"] + "#credit"],
            "textual_forms": [{
                "textual_form_id": "english",
                "language": "en",
                "editions": [{
                    "edition_id": acquisition["edition_id"],
                    "title": acquisition["source_selection"]["units"][0]["title"],
                    "category": "prose",
                    "language": "en",
                    "acquisition_ids": [acquisition_id],
                    "containing_source": {"title": "Shared Fixture Source", "locator": member["path"], "evidence": [member["path"]]},
                }],
            }],
        }
        return acquisition, work

    children = {}
    for work_id, native_id in (("child-a", "child-a"), ("child-b", "child-b")):
        acquisition, work = declaration(work_id, native_id)
        authority_dir = root / "library" / "works" / work_id / "forms" / "english" / "editions" / acquisition["edition_id"] / "acquisitions"
        authority_dir.mkdir(parents=True)
        acquisition_path = authority_dir / f"{acquisition['acquisition_id']}.json"
        work_path = root / "library" / "works" / work_id / "work.json"
        acquisition_path.write_text(json.dumps(acquisition), encoding="utf-8")
        work_path.write_text(json.dumps(work), encoding="utf-8")
        produced = _convert(SimpleNamespace(
            repository_root=root,
            authority_path=lambda key, a=acquisition, w=work: {
                "retained-source": source_path,
                "acquisition": acquisition_path,
                "work": work_path,
            }[key],
            verify=lambda: None,
        ))
        package = _write_package(root, work_id, produced)
        children[work_id] = {"acquisition": acquisition, "work": work, "package": package, "produced": produced}
    return root, children, member


def _accounting(*, pending: bool = False):
    return [
        {"native_id": "shared", "disposition": "shared-credit-context", "relationship": "dependency-of-child-a-and-child-b"},
        {"native_id": "child-a", "disposition": "selected", "work_id": "child-a"},
        {"native_id": "child-b", "disposition": "pending" if pending else "selected", **({} if pending else {"work_id": "child-b"})},
        {"native_id": "excluded", "disposition": "excluded", "reason": "index outside selected works"},
        {"native_id": "pending", "disposition": "pending" if pending else "excluded", "reason": "not part of bounded fixture release"},
    ]


def test_source_derived_collection_accounting_supports_valid_child_and_complete_collection(shared_collection):
    root, children, _ = shared_collection
    acquisition = children["child-a"]["acquisition"]
    assert [row["native_id"] for row in derive_source_carrier_inventory(acquisition, root=root)] == [
        "shared", "child-a", "child-b", "excluded", "pending"
    ]
    for child in children.values():
        verified = verify_source_selection(child["acquisition"], child["work"], root=root)
        assert verified["selected_native_ids"] == [child["work"]["work_id"]]

    partial = verify_complete_source_accounting(
        acquisition,
        [{"work_id": "child-a", "selected_native_ids": ["child-a"]}],
        _accounting(pending=True),
        root=root,
    )
    assert [row["position"] for row in partial] == list(range(5))
    complete = verify_complete_source_accounting(
        acquisition,
        [{"work_id": "child-a", "selected_native_ids": ["child-a"]},
         {"work_id": "child-b", "selected_native_ids": ["child-b"]}],
        _accounting(),
        root=root,
    )
    assert [row["disposition"] for row in complete] == [
        "shared-credit-context", "selected", "selected", "excluded", "excluded"
    ]


@pytest.mark.parametrize("mutation", ["omitted", "duplicated", "reordered", "misassigned"])
def test_collection_accounting_rejects_carrier_mutations(shared_collection, mutation):
    root, children, _ = shared_collection
    accounting = _accounting()
    if mutation == "omitted":
        accounting.pop()
    elif mutation == "duplicated":
        accounting.insert(2, dict(accounting[1]))
    elif mutation == "reordered":
        accounting[1], accounting[2] = accounting[2], accounting[1]
    else:
        accounting[1]["work_id"] = "child-b"
    with pytest.raises(PipelineError, match="source accounting"):
        verify_complete_source_accounting(
            children["child-a"]["acquisition"],
            [{"work_id": "child-a", "selected_native_ids": ["child-a"]},
             {"work_id": "child-b", "selected_native_ids": ["child-b"]}],
            accounting,
            root=root,
        )


def test_fixture_review_binds_child_packages_and_release_order(shared_collection):
    root, children, _ = shared_collection
    packages = [children[name]["package"] for name in ("child-a", "child-b")]
    assert all(package.manifest["status"] == "nonaccepted" for package in packages)
    package_bindings = [
        {"work_id": name, "package_sha256": children[name]["package"].sha256}
        for name in ("child-a", "child-b")
    ]
    assert len({item["package_sha256"] for item in package_bindings}) == 2

    for name, package in zip(("child-a", "child-b"), packages):
        tree = etree.fromstring(package.member_bytes("content.tei.xml"))
        assert tree.get("{http://www.w3.org/XML/1998/namespace}id") == name
        provenance = json.loads((package.path / "provenance.json").read_text(encoding="utf-8"))
        assert provenance["work_id"] == name
        assert provenance["acquisition_id"] == children[name]["acquisition"]["acquisition_id"]
        assert json.loads((package.path / "source-accountability.json").read_text(encoding="utf-8"))["source_envelope"]

    first = etree.fromstring(packages[0].member_bytes("content.tei.xml"))
    header = etree.tostring(first[0], encoding="utf-8")
    members = [
        (package.member_bytes("content.tei.xml"), _sha(package.member_bytes("content.tei.xml")))
        for package in packages
    ]
    with pytest.raises(PipelineError, match="duplicate source identifiers"):
        compose_reviewed_documents(header, members)


def test_separate_fixture_acceptance_and_release_proof(tmp_path, monkeypatch):
    root, accepted, _, _, _ = _fixture(tmp_path, "anthology", monkeypatch)
    assert validate_acceptance(accepted, root=root)["promotion"]["status"] == "pending"
    promoted = promote_accepted_master(root, acceptance_path=accepted, destination=tmp_path / "p")
    selection = {
        "schema_version": "2.0",
        "release_id": "wu03-fixture-release",
        "items": [{
            "item_id": "first",
            "category": "prose",
            "acceptance_path": promoted.acceptance_path.relative_to(promoted.destination_root).as_posix(),
        }],
    }
    release = tmp_path / "release"
    from tests.release_rights_fixture import authorize_release_fixture
    authorize_release_fixture(promoted.destination_root, selection['items'][0])
    report = assemble_release_v2(promoted.destination_root, release, selection=selection)
    assert report["status"] == "pass"
    assert verify_release_v2(promoted.destination_root, release, selection=selection) == {
        "status": "pass", "errors": []
    }
