from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from build.tei.npnf2_lib048_oracle import (
    _expected_image_binding,
    _closure_digest,
    _closure_paths,
    _neutral_reference_inventory,
    _oracle,
    SOURCES as _ORACLE_SOURCES,
    _selected as _oracle_selected,
    _source_tree,
    _verify_node,
)
from build.tei.npnf2_lib048_reconstruction import (
    ASSIGNED,
    EXPECTED_CENSUS,
    SOURCES,
    _append,
    _convert,
    _image_binding,
    _parse,
    _reference_exception_map,
    _selected as _producer_selected,
    _validate_reference_exceptions,
)
from build.tools.count_dataset_records import (
    _runtime_evidence_paths,
    collect_work_catalog,
)
from tests.runtime_candidate_baselines import current_runtime_catalog

from ocd_kernel.reconstruction import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


from ocd_kernel.tei.writer import tei_el

pytestmark = [
    pytest.mark.slow,
    pytest.mark.xdist_group(name="npnf2-lib048-reconstruction"),
]

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/npnf2-lib048.source-manifest.json'
SOURCE_ID = "ccel-npnf2-lib048-four-retained-xml-members"
TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = {"tei": TEI_NS}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _reseal(path: Path, member_name: str) -> CandidatePackage:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    content = (path / member_name).read_bytes()
    record = next(item for item in manifest["members"] if item["name"] == member_name)
    record.update(bytes=len(content), sha256=_sha(content))
    manifest_path.write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _clone(candidate: CandidatePackage, path: Path) -> Path:
    shutil.copytree(candidate.path, path)
    return path


@pytest.fixture(scope="module")
def verified_candidate(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    output = tmp_path_factory.mktemp("npnf2-lib048-candidate")
    candidate = reconstruct(source, output / "candidate", _convert)
    report = validate(source, candidate, _oracle)
    record = {
        "contract": "ocd-validation-report-v1",
        "status": report.status,
        "candidate_sha256": report.candidate_sha256,
        "source_manifest_sha256": report.source_manifest_sha256,
        "attestation": dict(report.attestation),
        "findings": list(report.findings),
    }
    assert _sha(_canonical(record)) == report.sha256
    validation_path = output / "validation.json"
    validation_path.write_bytes(_canonical({**record, "report_sha256": report.sha256}))
    return source, candidate, validation_path


def test_exact_four_member_authority_and_fifteen_bindings() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    source.verify()
    for key, path, size, digest in SOURCES:
        content = (ROOT / path).read_bytes()
        assert (key, len(content), _sha(content)) == (key, size, digest)
    assert len(ASSIGNED) == 15
    assert ASSIGNED[5] == ("npnf206", "vi.v", "jerome-perpetual-virginity-of-mary")
    assert len({work_id for _, _, work_id in ASSIGNED}) == 15


def test_retained_gregory_image_projection_and_binding() -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    source.verify()
    tree = _parse(source.authority_path("retained-npnf212"))
    roots = tree.xpath("/ThML/ThML.body/div1[@id='iii']")
    assert len(roots) == 1
    source_root = roots[0]
    images = source_root.xpath(".//img[@id=$source_id]", source_id="iii.iii-p86.1")
    assert len(images) == 1
    source_image = images[0]

    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    exceptions = _reference_exception_map(policy)
    parent = tei_el("p")
    rows = []
    _append(
        source_image,
        parent,
        "npnf212",
        rows,
        "parent-feature",
        reference_exceptions=exceptions,
        source_root_id="iii",
    )
    projected = parent[0]
    assert etree.QName(projected).localname == "figure"
    assert [etree.QName(child).localname for child in projected] == ["graphic", "figDesc"]
    _verify_node(
        source_image,
        projected,
        "npnf212",
        policy,
        [0],
        source_root_id="iii",
        reference_exceptions=exceptions,
    )

    for mutation in ("url", "label", "identity"):
        changed = copy.deepcopy(projected)
        if mutation == "url":
            changed[0].set("url", "/wrong/fig1.png")
        elif mutation == "label":
            changed[1].text = "Unrelated pedigree"
        else:
            changed.set("{http://www.w3.org/XML/1998/namespace}id", "unrelated-image")
        with pytest.raises(ValueError, match="TEI tag or attribute drift|TEI source image figure drift"):
            _verify_node(
                source_image,
                changed,
                "npnf212",
                policy,
                [0],
                source_root_id="iii",
                reference_exceptions=exceptions,
            )

    selected = [("npnf212", source_root, "gregory-the-great-pastoral-rule-and-epistles")]
    binding_rows = [
        {
            "feature_id": "parent-feature",
            "source_member": "npnf212",
            "source_xml_id": "iii.iii-p86",
            "tei_xml_id": "lib048-npnf212-043141-iii.iii-p86",
        },
        {
            **rows[0],
            "tei_xml_id": "lib048-npnf212-043142-iii.iii-p86.1",
        },
    ]
    assert _image_binding(source, selected, binding_rows) == _expected_image_binding(
        source, selected, binding_rows
    )
    binding_rows[1]["tei_xml_id"] = "lib048-npnf212-000001-iii.iii-p86.1"
    with pytest.raises(ValueError, match="candidate image placement drifted"):
        _image_binding(source, selected, binding_rows)
    with pytest.raises(ValueError, match="candidate image placement drifted"):
        _expected_image_binding(source, selected, binding_rows)

@pytest.mark.parametrize("mutation", ["work-scope", "logical-path"])
def test_rebound_image_authority_must_match_source_work_and_path(tmp_path, mutation):
    record = json.loads(MANIFEST.read_bytes())
    mirror = tmp_path / "authority-root"
    for authority in record["authorities"]:
        target = mirror / authority["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / authority["path"]).read_bytes())
    for binding in (record["converter"], record["validator"]):
        target = mirror / binding["implementation_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / binding["implementation_path"]).read_bytes())
    asset = next(item for item in record["authorities"] if item["name"] == "gregory-pedigree-image")
    if mutation == "work-scope":
        asset["work_ids"] = ["unrelated-work"]
    else:
        content = (mirror / asset["path"]).read_bytes()
        asset["path"] = "raw/elsewhere.png"
        (mirror / asset["path"]).write_bytes(content)
    manifest_path = mirror / MANIFEST.relative_to(ROOT)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(_canonical(record))
    changed = SourceManifest.load(manifest_path, repository_root=mirror)
    selected = _oracle_selected({key: _source_tree(changed.authority_path(authority).read_bytes()) for key, authority, *_ in _ORACLE_SOURCES})
    with pytest.raises(ValueError, match="source authority path or work scope"):
        _expected_image_binding(changed, selected, [])


def test_candidate_is_exact_p5_and_independently_verified(verified_candidate) -> None:
    source, candidate, validation_path = verified_candidate
    tree = etree.parse(str(candidate.path / "content.tei.xml"))
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    schema.assertValid(tree)
    assert validate(source, candidate, _oracle).status == "pass"
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    assert accountability["assigned_census"] == EXPECTED_CENSUS
    assert accountability["feature_count"] == 53_294
    assert accountability["attribute_count"] == 115_741
    assert [item["work_id"] for item in accountability["work_bindings"]] == [
        item[2] for item in ASSIGNED
    ]
    assert validation_path.is_file()


@pytest.mark.parametrize("mutation", ["url", "label", "identity", "placement", "asset-hash"])
def test_gregory_image_relationship_rejects_resealed_mutation(verified_candidate, tmp_path, mutation):
    source, candidate, _ = verified_candidate
    path = _clone(candidate, tmp_path / mutation)
    if mutation == "asset-hash":
        provenance = json.loads((path / "provenance.json").read_bytes())
        provenance["asset_bindings"][0]["sha256"] = "0" * 64
        (path / "provenance.json").write_bytes(_canonical(provenance))
        member = "provenance.json"
    else:
        member = "content.tei.xml"
        tree = etree.parse(str(path / member))
        figure = tree.xpath('//*[@xml:id="lib048-npnf212-043142-iii.iii-p86.1"]', namespaces={"xml": "http://www.w3.org/XML/1998/namespace"})[0]
        if mutation == "url":
            figure[0].set("url", "/wrong/fig1.png")
        elif mutation == "label":
            figure[1].text = "Unrelated pedigree"
        elif mutation == "identity":
            figure.set("{http://www.w3.org/XML/1998/namespace}id", "unrelated-image")
        else:
            parent = figure.getparent()
            parent.remove(figure)
            parent.getparent().append(figure)
        (path / member).write_bytes(etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False))
    mutated = _reseal(path, member)
    with pytest.raises(ValueError, match="TEI|source metadata"):
        _oracle(source, mutated)


def test_reference_classification_is_source_bound_and_conservative(
    verified_candidate,
) -> None:
    _source, candidate, _validation = verified_candidate
    policy = json.loads(
        (
            ROOT
            / "sources/structured-text/npnf2-lib048/npnf2-lib048.validation-policy.json"
        ).read_bytes()
    )
    entries = policy["projection"]["reference_classification"][
        "neutral_non_scripture_exceptions"
    ]
    assert len(entries) == 31
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    rows = {
        (row["source_member"], row["source_xml_id"]): row
        for row in accountability["crosswalk"]
    }
    for entry in entries:
        row = rows[(entry["source_member"], entry["source_xml_id"])]
        assert row["source_tag"] == "scripRef"
        assert row["source_xml_id"] == entry["source_xml_id"]
        assert row["source_attributes"] == {
            "id": entry["source_xml_id"],
            "passage": entry["passage"],
        }
        assert set(row["tei_attributes"]) == {"xml:id"}
        disposition = next(
            item
            for item in row["attribute_dispositions"]
            if item["source_attribute"] == "passage"
        )
        assert disposition == {
            "source_attribute": "passage",
            "source_value": entry["passage"],
            "destination": "source-accountability",
            "method": "preserved-exactly-in-accountability",
        }
    assert accountability["assigned_census"]["scripture_refs"] == 7_082

    bible_row = next(
        row
        for row in accountability["crosswalk"]
        if row["source_tag"] == "scripRef"
        and "osisRef" in row["source_attributes"]
    )
    assert bible_row["tei_attributes"]["type"] == "scripture"
    assert bible_row["tei_attributes"]["target"] == bible_row["source_attributes"][
        "osisRef"
    ]

    unknown_row = rows[("npnf206", "v.I-p19.1")]
    assert unknown_row["source_attributes"]["passage"] == (
        "Song of the Three Holy Children"
    )
    assert unknown_row["tei_attributes"]["type"] == "scripture"
    assert unknown_row["tei_attributes"]["cRef"] == unknown_row[
        "source_attributes"
    ]["passage"]


def test_oracle_rejects_resealed_neutral_reference_semantic_invention(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _validation = verified_candidate
    target = _clone(candidate, tmp_path / "invented-neutral-reference-semantics")
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    row = next(
        item
        for item in accountability["crosswalk"]
        if item["source_member"] == "npnf206"
        and item["source_xml_id"] == "vi.i-p4.1"
    )
    tree = etree.parse(str(target / "content.tei.xml"))
    matches = tree.xpath(
        "//*[@xml:id=$xml_id]", namespaces=TEI, xml_id=row["tei_xml_id"]
    )
    assert len(matches) == 1
    matches[0].set("type", "scripture")
    matches[0].set("cRef", "Ep. x.")
    (target / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(target, "content.tei.xml")
    with pytest.raises(ValueError, match="TEI tag or attribute drift"):
        _oracle(source, mutated)


@pytest.mark.parametrize("mutation", ["passage", "root", "id", "duplicate"])
def test_reference_policy_rejects_inventory_mutations(mutation: str) -> None:
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    source.verify()
    policy = json.loads(
        (
            ROOT
            / "sources/structured-text/npnf2-lib048/npnf2-lib048.validation-policy.json"
        ).read_bytes()
    )
    entries = policy["projection"]["reference_classification"][
        "neutral_non_scripture_exceptions"
    ]
    if mutation == "passage":
        entries[0]["passage"] = "Ep. source-drift"
    elif mutation == "root":
        entries[0]["source_root_id"] = "vi.i"
    elif mutation == "id":
        entries[0]["source_xml_id"] = "v.I-p19.1"
    else:
        entries.append(dict(entries[0]))

    producer_trees = {
        key: _parse(ROOT / path) for key, path, _bytes, _digest in SOURCES
    }
    producer_selected = _producer_selected(producer_trees)
    oracle_trees = {
        key: _source_tree(source.authority_path(authority).read_bytes())
        for key, authority, _path, _bytes, _digest in _ORACLE_SOURCES
    }
    oracle_selected = _oracle_selected(oracle_trees)

    with pytest.raises(ValueError):
        exceptions = _reference_exception_map(policy)
        _validate_reference_exceptions(exceptions, producer_selected)
    with pytest.raises(ValueError):
        _neutral_reference_inventory(policy, oracle_selected)


def test_retained_credit_evidence_is_exact_and_not_invented(verified_candidate) -> None:
    _source, candidate, _validation = verified_candidate
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    jerome = provenance["sources"]["npnf206"]
    evidence = jerome["retained_title_page_and_preface_credit_evidence"]
    assert jerome["display_credit_names"] == [
        "W. H. Fremantle",
        "G. Lewis",
        "W. G. Martley",
    ]
    assert "w. h. fremantle" in evidence["ii-p4"].lower()
    assert "G. Lewis" in evidence["ii-p7"]
    assert "w. g. martley" in evidence["ii-p10"].lower()
    assert "coadjutors" in evidence["iii-p4"].lower()
    assert "W. H. Fremantle" in evidence["iii-p7"]
    assert b"Open Christian Data" not in candidate.member_bytes("content.tei.xml")


def test_oracle_rejects_fully_resealed_p5_valid_invented_notes_stmt(
    verified_candidate, tmp_path: Path
) -> None:
    source, candidate, _validation = verified_candidate
    target = _clone(candidate, tmp_path / "invented-notes-stmt")
    tree = etree.parse(str(target / "content.tei.xml"))
    file_desc = tree.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc", namespaces=TEI)[0]
    notes_stmt = etree.Element(f"{{{TEI_NS}}}notesStmt")
    note = etree.SubElement(notes_stmt, f"{{{TEI_NS}}}note")
    note.text = "Invented but schema-valid metadata"
    file_desc.insert(len(file_desc) - 1, notes_stmt)
    (target / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(target, "content.tei.xml")
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(etree.parse(str(target / "content.tei.xml")))
    with pytest.raises(
        ValueError, match="header metadata, rights, credit, or topology drift"
    ):
        _oracle(source, mutated)


@pytest.mark.parametrize("location", ["root", "body"])
def test_oracle_rejects_fully_resealed_p5_valid_comment_invention(
    verified_candidate, tmp_path: Path, location: str
) -> None:
    source, candidate, _validation = verified_candidate
    target = _clone(candidate, tmp_path / f"invented-{location}-comment")
    tree = etree.parse(str(target / "content.tei.xml"))
    parent = (
        tree.getroot()
        if location == "root"
        else tree.xpath("/tei:TEI/tei:text/tei:body", namespaces=TEI)[0]
    )
    parent.append(etree.Comment("invented candidate matter"))
    (target / "content.tei.xml").write_bytes(
        etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    )
    mutated = _reseal(target, "content.tei.xml")
    schema = etree.XMLSchema(
        etree.parse(str(ROOT / "ocd_kernel/tei/vendor/xsd/tei_all.xsd"))
    )
    assert schema.validate(etree.parse(str(target / "content.tei.xml")))
    with pytest.raises(ValueError, match="root child invention|work count drift"):
        _oracle(source, mutated)


@pytest.mark.parametrize(
    "member_name", ["provenance.json", "source-accountability.json"]
)
def test_oracle_rejects_fully_resealed_evidence_invention(
    verified_candidate, tmp_path: Path, member_name: str
) -> None:
    source, candidate, _validation = verified_candidate
    target = _clone(candidate, tmp_path / member_name.removesuffix(".json"))
    path = target / member_name
    value = json.loads(path.read_bytes())
    if member_name == "provenance.json":
        value["sources"]["npnf206"]["display_credit_names"].append("Invented Editor")
    else:
        value["work_bindings"][0]["source_root_id"] = "wrong-source-root"
    path.write_bytes(_canonical(value))
    mutated = _reseal(target, member_name)
    with pytest.raises(ValueError):
        _oracle(source, mutated)


def test_source_manifest_rejects_a_mutated_retained_member(tmp_path: Path) -> None:
    record = json.loads(MANIFEST.read_bytes())
    isolated_root = tmp_path / "isolated-source-root"
    for authority in record["authorities"]:
        source_path = ROOT / authority["path"]
        target = isolated_root / authority["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
    for binding in (record["converter"], record["validator"]):
        source_path = ROOT / binding["implementation_path"]
        target = isolated_root / binding["implementation_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
    manifest_path = isolated_root / MANIFEST.relative_to(ROOT)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MANIFEST, manifest_path)
    source = SourceManifest.load(manifest_path, repository_root=isolated_root)
    source.verify()
    retained = isolated_root / "raw/ccel/npnf2/npnf206.xml"
    retained.write_bytes(retained.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="retained-npnf206 authority bytes drifted"):
        source.verify()


def test_oracle_closure_is_source_local_and_excludes_the_producer() -> None:
    policy = json.loads(
        (
            ROOT
            / "sources/structured-text/npnf2-lib048/npnf2-lib048.validation-policy.json"
        ).read_bytes()
    )
    paths = {path.relative_to(ROOT).as_posix() for path in _closure_paths(ROOT, policy)}
    assert "build/tei/npnf2_lib048_oracle.py" in paths
    assert "build/tei/npnf2_lib048_reconstruction.py" not in paths
    manifest = json.loads(MANIFEST.read_bytes())
    assert (
        _closure_digest(ROOT, policy) == manifest["validator"]["import_closure_sha256"]
    )


def test_all_fifteen_workcatalog_routes_are_verified_and_nonaccepted(
    verified_candidate,
) -> None:
    _source, candidate, validation_path = verified_candidate
    evidence = {
        (SOURCE_ID, work_id): (candidate.path, validation_path)
        for _, _, work_id in ASSIGNED
    }
    catalog = current_runtime_catalog(
        root=ROOT, manifest=MANIFEST, work_ids=[work_id for _, _, work_id in ASSIGNED], reconstruction_evidence=evidence)
    by_id = {work["work_id"]: work for work in catalog.works}
    for _, _, work_id in ASSIGNED:
        state = by_id[work_id]["reconstruction_state"]
        assert state["retained_source"] == "manifest_bound"
        assert state["tei_candidate"] == "verified"
        assert state["validation"] == "verified"
        assert state["human_review"] == "required"
        assert state["accepted_ir"] == "not_accepted"
        assert state["publication"] == "not_ready"
        routes = [route for route in state["routes"] if route["source_id"] == SOURCE_ID]
        assert len(routes) == 1
        assert routes[0]["association"] == "source_hash+exact_id"
        assert routes[0]["scope"] == "work"
        assert routes[0]["candidate_verification"] == "verified"
        assert routes[0]["validation_verification"] == "verified"


def test_catalog_route_seam_rejects_incomplete_runtime_evidence(
    verified_candidate,
) -> None:
    _source, candidate, _validation_path = verified_candidate
    work_id = ASSIGNED[0][2]
    with pytest.raises(ValueError, match="must include both paths"):
        _runtime_evidence_paths(
            {(SOURCE_ID, work_id): (candidate.path, None)},
            source_id=SOURCE_ID,
            work_id=work_id,
        )
