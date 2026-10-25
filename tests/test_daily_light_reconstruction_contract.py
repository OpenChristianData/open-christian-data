from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from types import ModuleType

from lxml import etree
import pytest

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "sources/devotionals/daily-light/daily-light.source-manifest.json"
MEMBERS = {"manifest.json", "content.tei.xml", "source-accountability.json", "provenance.json", "unresolved.jsonl", "README.source.md"}
TEI = {"t": "http://www.tei-c.org/ns/1.0", "xml": "http://www.w3.org/XML/1998/namespace"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
RAW_MEMBERS = (
    "modules/lexdict/rawld/devotionals/daily/daily.dat",
    "modules/lexdict/rawld/devotionals/daily/daily.idx",
    "mods.d/daily.conf",
)
RAW_MEMBER_ROLES = {
    RAW_MEMBERS[0]: "textual-witness",
    RAW_MEMBERS[1]: "binary-order-index-authority",
    RAW_MEMBERS[2]: "module-metadata-and-rights-evidence",
}


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _rebind_source_mirror(mirror: Path) -> SourceManifest:
    manifest_path = mirror / MANIFEST.relative_to(ROOT)
    record = json.loads(manifest_path.read_bytes())
    members = []
    for relative in RAW_MEMBERS:
        path = mirror / "raw/sword_modules/Daily" / relative
        payload = path.read_bytes()
        members.append({"name": relative, "role": RAW_MEMBER_ROLES[relative], "bytes": len(payload), "sha256": _sha(payload)})
    record["retained_member_census"]["extracted_dir_bytes"] = sum(item["bytes"] for item in members)
    record["retained_member_census"]["members"] = members
    for authority in record["authorities"]:
        path = mirror / authority["path"]
        authority.update(bytes=path.stat().st_size, sha256=_sha(path.read_bytes()))
    for section in ("converter", "validator"):
        path = mirror / record[section]["implementation_path"]
        record[section]["implementation_sha256"] = _sha(path.read_bytes())
    oracle_module = _load_module(mirror / "build/tei/daily_light_oracle.py", f"_daily_light_oracle_rebind_{id(mirror)}")
    record["validator"]["import_closure_sha256"] = oracle_module._closure(mirror)
    record["package_schema"]["sha256"] = _sha((mirror / record["package_schema"]["path"]).read_bytes())
    manifest_path.write_bytes(_canonical(record))
    return SourceManifest.load(manifest_path, repository_root=mirror)


def _admit_member_identity(monkeypatch: pytest.MonkeyPatch, module: ModuleType, mirror: Path) -> None:
    digests = {}
    sizes = {}
    for relative in RAW_MEMBERS:
        payload = (mirror / "raw/sword_modules/Daily" / relative).read_bytes()
        digests[relative] = _sha(payload)
        sizes[relative] = len(payload)
    monkeypatch.setattr(module, "_MEMBER_DIGESTS", digests)
    monkeypatch.setattr(module, "_MEMBER_BYTES", sizes)


@pytest.fixture(scope="module")
def validation_mirror(tmp_path_factory: pytest.TempPathFactory) -> Path:
    mirror = tmp_path_factory.mktemp("daily-light-validation-mirror")
    source = ROOT / "sources/devotionals/daily-light"
    shutil.copytree(source, mirror / "sources/devotionals/daily-light")
    shutil.copytree(ROOT / "raw/sword_modules/Daily", mirror / "raw/sword_modules/Daily")
    for relative in (
        "build/tei/daily_light_reconstruction.py",
        "build/tei/daily_light_oracle.py",
        "ocd_kernel/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
    ):
        destination = mirror / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    shutil.copytree(ROOT / "ocd_kernel/tei/vendor/xsd", mirror / "ocd_kernel/tei/vendor/xsd")
    return mirror


@pytest.fixture(scope="module")
def daily_manifest(validation_mirror: Path):
    return _rebind_source_mirror(validation_mirror)


@pytest.fixture(scope="module")
def daily_route(validation_mirror: Path) -> ModuleType:
    return _load_module(validation_mirror / "build/tei/daily_light_reconstruction.py", "_daily_light_route")


@pytest.fixture(scope="module")
def daily_oracle(validation_mirror: Path) -> ModuleType:
    return _load_module(validation_mirror / "build/tei/daily_light_oracle.py", "_daily_light_oracle")


@pytest.fixture(scope="module")
def daily_candidate(tmp_path_factory: pytest.TempPathFactory, daily_manifest, daily_route):
    return reconstruct(daily_manifest, tmp_path_factory.mktemp("daily-light") / "candidate", daily_route._convert)


def _copy(tmp_path: Path, candidate: CandidatePackage, label: str) -> Path:
    destination = tmp_path / label
    shutil.copytree(candidate.path, destination)
    return destination


def _reseal(path: Path, name: str, content: bytes) -> CandidatePackage:
    (path / name).write_bytes(content)
    manifest = json.loads((path / "manifest.json").read_bytes())
    member = next(item for item in manifest["members"] if item["name"] == name)
    member.update(bytes=len(content), sha256=_sha(content))
    (path / "manifest.json").write_bytes(_canonical(manifest))
    return CandidatePackage.load(path)


def _json_mutation(path: Path, name: str, mutate) -> CandidatePackage:
    record = json.loads((path / name).read_bytes())
    mutate(record)
    return _reseal(path, name, _canonical(record))


def _tei_mutation(path: Path, mutate) -> CandidatePackage:
    tree = etree.fromstring((path / "content.tei.xml").read_bytes())
    mutate(tree)
    return _reseal(path, "content.tei.xml", etree.tostring(tree, encoding="utf-8", xml_declaration=True, pretty_print=False))


def _mutated_source_mirror(tmp_path: Path, validation_mirror: Path, mutation: str) -> Path:
    mirror = tmp_path / mutation
    shutil.copytree(validation_mirror, mirror)
    root = mirror / "raw/sword_modules/Daily"
    dat_path = root / RAW_MEMBERS[0]
    idx_path = root / RAW_MEMBERS[1]
    dat = bytearray(dat_path.read_bytes())
    idx = bytearray(idx_path.read_bytes())

    def slot(ordinal: int) -> tuple[int, int]:
        offset = int.from_bytes(idx[ordinal * 6 : ordinal * 6 + 4], "little")
        size = int.from_bytes(idx[ordinal * 6 + 4 : ordinal * 6 + 6], "little")
        return offset, size

    def put_slot(ordinal: int, offset: int, size: int) -> None:
        struct.pack_into("<IH", idx, ordinal * 6, offset, size)

    if mutation == "nonzero-sentinel":
        idx[0] = 1
    elif mutation == "missing-interior-delimiter":
        offset, size = slot(1)
        del dat[offset + size : offset + size + 2]
        for ordinal in range(2, 367):
            later_offset, later_size = slot(ordinal)
            put_slot(ordinal, later_offset - 2, later_size)
    elif mutation == "interior-delimiter-drift":
        offset, size = slot(1)
        dat[offset + size : offset + size + 2] = b"\n\n"
    elif mutation == "terminal-delimiter-missing":
        del dat[-2:]
    elif mutation == "overlapping-span":
        first_offset, first_size = slot(1)
        _, second_size = slot(2)
        put_slot(2, first_offset + first_size - 1, second_size)
    elif mutation == "reordered-slot":
        first, second = bytes(idx[6:12]), bytes(idx[12:18])
        idx[6:12], idx[12:18] = second, first
    elif mutation == "invalid-utf8-header":
        dat[0] = 0xFF
    elif mutation == "invalid-utf8-key":
        offset, _ = slot(1)
        dat[offset] = 0xFF
    elif mutation == "invalid-utf8-body":
        offset, _ = slot(1)
        dat[offset + len(b"01.01\r\n")] = 0xFF
    elif mutation == "missing-leap-day":
        leap_offset, _ = slot(60)
        put_slot(60, leap_offset, 0)
    elif mutation == "bad-period-split":
        marker = b"<i>Evening</i>:<br />\n"
        at = dat.find(marker)
        assert at >= 0
        dat[at : at + len(marker)] = b"<i>Eventng</i>:<br />\n"
    elif mutation == "unknown-markup":
        marker = b"<br />"
        at = dat.find(marker)
        assert at >= 0
        dat[at : at + len(marker)] = b"<zz />"
    elif mutation == "extra-member":
        extra = root / "unexpected.bin"
        extra.write_bytes(b"unexpected")
    elif mutation == "wrong-member-role":
        pass
    else:
        raise AssertionError(f"unknown Daily Light source mutation {mutation}")
    if mutation not in {"extra-member", "wrong-member-role"}:
        dat_path.write_bytes(bytes(dat))
        idx_path.write_bytes(bytes(idx))
    manifest = _rebind_source_mirror(mirror)
    if mutation == "wrong-member-role":
        record = json.loads(manifest.path.read_bytes())
        record["retained_member_census"]["members"][0]["role"] = "support-evidence"
        manifest.path.write_bytes(_canonical(record))
    return mirror


_SOURCE_MUTATIONS = (
    "nonzero-sentinel", "missing-interior-delimiter", "interior-delimiter-drift", "terminal-delimiter-missing",
    "overlapping-span", "reordered-slot",
    "invalid-utf8-header",
    "invalid-utf8-key",
    "invalid-utf8-body",
    "missing-leap-day", "bad-period-split", "unknown-markup", "wrong-member-role", "extra-member",
)


@pytest.mark.parametrize("mutation", _SOURCE_MUTATIONS)
def test_producer_rejects_admitted_source_carrier_mutations(tmp_path, validation_mirror, daily_route, monkeypatch, mutation):
    mirror = _mutated_source_mirror(tmp_path, validation_mirror, mutation)
    manifest = SourceManifest.load(mirror / MANIFEST.relative_to(ROOT), repository_root=mirror)
    _admit_member_identity(monkeypatch, daily_route, mirror)
    expected = UnicodeDecodeError if mutation.startswith("invalid-utf8") else ValueError
    with pytest.raises(expected):
        if mutation == "unknown-markup":
            source = daily_route._source(manifest)
            profile = json.loads(manifest.authority_path("reconstruction-profile").read_bytes())
            daily_route._tei(source, profile)
        else:
            daily_route._source(manifest)


@pytest.mark.parametrize("mutation", _SOURCE_MUTATIONS)
def test_independent_oracle_rejects_admitted_source_carrier_mutations(tmp_path, validation_mirror, daily_oracle, daily_route, monkeypatch, mutation):
    mirror = _mutated_source_mirror(tmp_path, validation_mirror, mutation)
    manifest = SourceManifest.load(mirror / MANIFEST.relative_to(ROOT), repository_root=mirror)
    _admit_member_identity(monkeypatch, daily_oracle, mirror)
    expected = UnicodeDecodeError if mutation.startswith("invalid-utf8") else ValueError
    with pytest.raises(expected):
        if mutation == "wrong-member-role":
            candidate = reconstruct(manifest, tmp_path / "candidate", daily_route._convert)
            daily_oracle._oracle(manifest, candidate)
        elif mutation == "unknown-markup":
            source = daily_oracle._source(manifest)
            daily_oracle._expected_accountability(manifest, source)
        else:
            daily_oracle._source(manifest)


def test_extracted_members_have_exact_source_and_support_authorities(daily_manifest):
    daily_manifest.verify()
    record = json.loads(daily_manifest.path.read_bytes())
    assert record["work_id"] == "daily-light"
    assert record["external_library_root"] == "D:/Library/Open Christian Data"
    primary = [item for item in record["authorities"] if item["role"] == "primary-source"]
    assert [item["name"] for item in primary] == ["retained-daily-dat", "retained-daily-idx"]
    assert [item["path"] for item in primary] == [
        "raw/sword_modules/Daily/modules/lexdict/rawld/devotionals/daily/daily.dat",
        "raw/sword_modules/Daily/modules/lexdict/rawld/devotionals/daily/daily.idx",
    ]
    support = [
        item
        for item in record["authorities"]
        if item["role"] == "source-support-metadata-rights"
    ]
    assert [(item["name"], item["path"]) for item in support] == [
        (
            "retained-daily-conf",
            "raw/sword_modules/Daily/mods.d/daily.conf",
        )
    ]
    retained_inputs = [*primary, *support]
    assert {item["name"] for item in retained_inputs} == {
        "retained-daily-dat",
        "retained-daily-idx",
        "retained-daily-conf",
    }
    assert [item["role"] for item in record["retained_member_census"]["members"]] == list(RAW_MEMBER_ROLES.values())
    assert not any("zip" in str(item["path"]).lower() for item in retained_inputs)


def test_source_collectors_reject_conf_promoted_to_primary(
    tmp_path, validation_mirror, daily_route, daily_oracle
):
    mirror = tmp_path / "promoted-conf-authority"
    shutil.copytree(validation_mirror, mirror)
    manifest_path = mirror / MANIFEST.relative_to(ROOT)
    record = json.loads(manifest_path.read_bytes())
    conf = next(
        item
        for item in record["authorities"]
        if item["name"] == "retained-daily-conf"
    )
    conf["role"] = "primary-source"
    manifest_path.write_bytes(_canonical(record))
    manifest = SourceManifest.load(manifest_path, repository_root=mirror)
    for module in (daily_route, daily_oracle):
        with pytest.raises(ValueError, match="authority role drifted"):
            module._source(manifest)


def test_complete_candidate_passes_independent_oracle_and_is_nonaccepted(daily_manifest, daily_candidate, daily_oracle):
    assert {item["name"] for item in daily_candidate.manifest["members"]} | {"manifest.json"} == MEMBERS
    assert daily_candidate.manifest["status"] == "nonaccepted"
    report = validate(daily_manifest, daily_candidate, daily_oracle._oracle)
    assert report.status == "pass"
    assert report.findings == ()
    assert report.candidate_sha256 == daily_candidate.sha256
    assert report.attestation["oracle_id"] == "ocd-daily-light-sword-independent-oracle"


def test_binary_accounting_and_tei_shape_are_exact(daily_manifest, daily_candidate):
    accountability = json.loads(daily_candidate.member_bytes("source-accountability.json"))
    assert accountability["member_count"] == 3
    assert accountability["member_bytes"] == {RAW_MEMBERS[0]: 1034668, RAW_MEMBERS[1]: 2202, RAW_MEMBERS[2]: 603}
    assert accountability["member_sha256"] == {
        RAW_MEMBERS[0]: "a7b7a9a4207836d152365e465ca3ba219de3df01d5516e2bfcf7ed6201f8e543",
        RAW_MEMBERS[1]: "76bdcf08e75da1bcb98b46fbc7a0b97183c055756cef9b4e4b7318e439083899",
        RAW_MEMBERS[2]: "4c5afc29317b58ad7c110affbac23ffc534a9e04d1d4f86c05efd4cb584689fb",
    }
    assert [item["name"] for item in accountability["members"]] == list(RAW_MEMBERS)
    assert [item["role"] for item in accountability["members"]] == list(RAW_MEMBER_ROLES.values())
    assert accountability["index_record_count"] == 367
    assert accountability["index_sentinel_count"] == 1
    assert accountability["header_bytes"] == 1550
    assert accountability["day_count"] == 366
    assert accountability["day_span_bytes"] == 1_032_386
    assert accountability["record_delimiter_count"] == 366
    assert accountability["record_delimiter_bytes"] == 732
    assert accountability["terminal_tail_bytes"] == 2
    assert accountability["gap_count"] == 367
    assert accountability["gap_bytes"] == 2_282
    assert accountability["unexplained_gap_count"] == 0
    assert accountability["period_count"] == 732
    assert accountability["source_element_count"] == 22298
    assert accountability["tag_counts"] == {"b": 1, "br": 20346, "center": 1, "i": 732, "scripRef": 1218}
    assert len(accountability["carriers"]) == 735
    assert accountability["carriers"][-2]["offset"] == 1_034_666
    assert accountability["carriers"][-2]["terminal"] is True
    tei = etree.fromstring(daily_candidate.member_bytes("content.tei.xml"))
    xsd = etree.XMLSchema(etree.parse(str(daily_manifest.authority_path("tei-p5-xsd"))))
    assert xsd.validate(tei), xsd.error_log
    assert tei.get(XML_ID) == "daily-light-candidate"
    days = tei.xpath("/t:TEI/t:text/t:body/t:div[@type='day']", namespaces=TEI)
    assert len(days) == 366
    assert [day.get("n") for day in days[:2]] == ["01.01", "01.02"]
    assert days[-1].get("n") == "12.31"
    assert len(tei.xpath("//t:div[@type='period']", namespaces=TEI)) == 732
    assert len(tei.xpath("//*[@corresp]", namespaces=TEI)) == 22298


def test_candidate_is_byte_identical_in_process_and_fresh_process(tmp_path, daily_manifest, daily_candidate, daily_route, validation_mirror):
    again = reconstruct(daily_manifest, tmp_path / "again", daily_route._convert)
    assert again.sha256 == daily_candidate.sha256
    destination = tmp_path / "fresh"
    result = subprocess.run(
        [sys.executable, str(ROOT / "build/tools/reconstruct_candidate.py"), "--manifest", MANIFEST.relative_to(ROOT).as_posix(), "--destination", str(destination), "--repository-root", str(validation_mirror)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    assert json.loads(result.stdout)["candidate"]["sha256"] == daily_candidate.sha256


@pytest.mark.parametrize("mutation", ["omission", "duplication", "reordering"])
def test_oracle_rejects_structure_mutations(tmp_path, daily_manifest, daily_candidate, daily_oracle, mutation):
    path = _copy(tmp_path, daily_candidate, mutation)

    def mutate(tei):
        days = tei.xpath("/t:TEI/t:text/t:body/t:div[@type='day']", namespaces=TEI)
        if mutation == "omission":
            days[0].getparent().remove(days[0])
        elif mutation == "duplication":
            duplicate = copy.deepcopy(days[0])
            for node in [duplicate, *duplicate.xpath(".//*[@xml:id]", namespaces=TEI)]:
                node.set(XML_ID, (node.get(XML_ID) or "duplicate") + "-copy")
            days[0].addnext(duplicate)
        else:
            first, second = days[:2]
            parent = first.getparent()
            parent.remove(second)
            parent.insert(0, second)

    mutated = _tei_mutation(path, mutate)
    with pytest.raises(ValueError, match="Daily Light|candidate|source|day|observation"):
        validate(daily_manifest, mutated, daily_oracle._oracle)


@pytest.mark.parametrize("mutation", ["payload-drift", "binary-order", "binary-payload", "sentinel-carrier", "delimiter-carrier", "member-role", "terminal-tail"])
def test_oracle_rejects_payload_and_binary_accounting_mutations(tmp_path, daily_manifest, daily_candidate, daily_oracle, mutation):
    path = _copy(tmp_path, daily_candidate, mutation)
    if mutation == "payload-drift":
        def mutate(tei):
            node = tei.xpath("//t:ref[@type='scripture']", namespaces=TEI)[0]
            node.text = (node.text or "") + " drift"
        mutated = _tei_mutation(path, mutate)
    else:
        def mutate(accountability):
            if mutation == "binary-order":
                accountability["members"][0], accountability["members"][1] = accountability["members"][1], accountability["members"][0]
            elif mutation == "binary-payload":
                accountability["member_sha256"][RAW_MEMBERS[0]] = "0" * 64
            elif mutation == "sentinel-carrier":
                sentinel = next(item for item in accountability["carriers"] if item["kind"] == "index-sentinel")
                sentinel["disposition"] = "represented"
            elif mutation == "delimiter-carrier":
                delimiter = next(item for item in accountability["carriers"] if item["kind"] == "record-delimiter")
                delimiter["sha256"] = "0" * 64
            elif mutation == "member-role":
                accountability["members"][0]["role"] = "support-evidence"
            else:
                accountability["terminal_tail_bytes"] = 0
        mutated = _json_mutation(path, "source-accountability.json", mutate)
    with pytest.raises(ValueError, match="Daily Light|candidate|source|member|payload|observation"):
        validate(daily_manifest, mutated, daily_oracle._oracle)


def test_oracle_rejects_target_semantics_and_metadata_mutations(tmp_path, daily_manifest, daily_candidate, daily_oracle):
    path = _copy(tmp_path, daily_candidate, "target-semantics")
    mutated = _tei_mutation(path, lambda tei: tei.xpath("//t:ref[@type='scripture']", namespaces=TEI)[0].set("cRef", "Invented 1:1"))
    with pytest.raises(ValueError, match="Daily Light|target|observation|source"):
        validate(daily_manifest, mutated, daily_oracle._oracle)
    path = _copy(tmp_path, daily_candidate, "metadata")
    mutated = _json_mutation(path, "provenance.json", lambda value: value["identity"].update(title="Invented Daily Light title"))
    with pytest.raises(ValueError, match="Daily Light|candidate|provenance|metadata"):
        validate(daily_manifest, mutated, daily_oracle._oracle)


def test_oracle_rejects_target_identity_center_and_header_mutations(
    tmp_path, daily_manifest, daily_candidate, daily_oracle
):
    target_identity_path = _copy(tmp_path, daily_candidate, "target-identity")

    def drift_target_identity(tei):
        node = tei.xpath("//t:ref[@type='scripture']", namespaces=TEI)[0]
        node.set(XML_ID, (node.get(XML_ID) or "target") + "-invented")

    target_identity_mutation = _tei_mutation(target_identity_path, drift_target_identity)
    with pytest.raises(ValueError, match="Daily Light|target|observation|identity|source"):
        validate(daily_manifest, target_identity_mutation, daily_oracle._oracle)

    center_path = _copy(tmp_path, daily_candidate, "center-semantics")

    def drift_center(tei):
        node = tei.xpath("//t:hi[@rend='center']", namespaces=TEI)[0]
        node.set("rend", "bold")

    center_mutation = _tei_mutation(center_path, drift_center)
    with pytest.raises(ValueError, match="Daily Light|target|observation|semantics|source"):
        validate(daily_manifest, center_mutation, daily_oracle._oracle)

    header_path = _copy(tmp_path, daily_candidate, "header-metadata")

    def drift_header(tei):
        title = tei.xpath(
            "/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=TEI
        )[0]
        title.text = "Invented Daily Light title"

    header_mutation = _tei_mutation(header_path, drift_header)
    with pytest.raises(ValueError, match="Daily Light|header|identity|metadata"):
        validate(daily_manifest, header_mutation, daily_oracle._oracle)


@pytest.mark.parametrize("mutation", ["evidence", "stale-manifest", "unresolved"])
def test_oracle_rejects_evidence_stale_manifest_and_unresolved_mutations(
    tmp_path, daily_manifest, daily_candidate, daily_oracle, mutation
):
    path = _copy(tmp_path, daily_candidate, mutation)
    if mutation == "evidence":
        mutated = _reseal(
            path,
            "README.source.md",
            daily_candidate.member_bytes("README.source.md") + b"\nInvented evidence.\n",
        )
    elif mutation == "unresolved":
        lines = (path / "unresolved.jsonl").read_bytes().splitlines(keepends=True)
        mutated = _reseal(path, "unresolved.jsonl", b"".join(lines[1:]))
    else:
        manifest = json.loads((path / "manifest.json").read_bytes())
        manifest["source_manifest"]["sha256"] = "0" * 64
        (path / "manifest.json").write_bytes(_canonical(manifest))
        mutated = CandidatePackage.load(path)
    with pytest.raises(ValueError, match="Daily Light|candidate|README|unresolved|binding"):
        validate(daily_manifest, mutated, daily_oracle._oracle)
