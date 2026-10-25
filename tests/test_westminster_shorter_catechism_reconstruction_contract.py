from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei import westminster_shorter_catechism_oracle as oracle_module
from build.tei.westminster_shorter_catechism_oracle import (
    _assert_runtime_paths,
    _closure_digest,
    _digest,
    _independent_outer_html_census,
    _independent_source_model,
    _oracle,
    _repository_import_closure,
)
from build.tei.westminster_shorter_catechism_reconstruction import _convert
from ocd_kernel.reconstruction.contract import (
    CandidatePackage,
    SourceManifest,
    reconstruct,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]
RETAINED_MANIFEST = (
    ROOT
    / "sources/catechisms/westminster-shorter-catechism/westminster-shorter-catechism.source-manifest.json"
)
MANIFEST = ROOT / "tests/fixtures/reconstruction-runtime/westminster-shorter-catechism.source-manifest.json"
NS = {
    "tei": "http://www.tei-c.org/ns/1.0",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
MEMBERS = {
    "README.source.md",
    "content.tei.xml",
    "manifest.json",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def test_runtime_fixture_preserves_retained_inputs_and_only_updates_shared_runtime_closures() -> None:
    raw = RETAINED_MANIFEST.read_bytes()
    assert _sha(raw) == "4d102bed9eb7be4fec5ea08493fdf382597a6164cea3d0bf18fdaf82c26614a9"
    expected = json.loads(raw)
    policy_path = next(item["path"] for item in expected["authorities"]
                       if item["name"] == "validation-policy")
    policy = json.loads((ROOT / policy_path).read_bytes())
    forbidden = tuple(policy["forbidden_import_prefixes"])
    expected["producer_import_closure_sha256"] = _digest(_repository_import_closure(
        ROOT, ROOT / expected["converter"]["implementation_path"], forbidden))
    expected["validator"]["import_closure_sha256"] = _closure_digest(ROOT, policy)
    profile = next(item for item in expected["authorities"]
                   if item["name"] == "reconstruction-profile")
    original_profile = (ROOT / profile["path"]).read_bytes()
    assert _sha(original_profile) == "89e20dcf86e71dde7d5dd0fcd386c8c00bd6bd193486f10799856df97a526ea7"
    expected_profile = json.loads(original_profile)
    expected_profile["producer_import_closure_sha256"] = expected["producer_import_closure_sha256"]
    runtime_profile = MANIFEST.with_name("westminster-shorter-catechism.reconstruction-profile.json")
    runtime_profile_bytes = runtime_profile.read_bytes()
    assert json.loads(runtime_profile_bytes) == expected_profile
    profile.update(path=runtime_profile.relative_to(ROOT).as_posix(),
                   bytes=len(runtime_profile_bytes), sha256=_sha(runtime_profile_bytes))
    assert json.loads(MANIFEST.read_bytes()) == expected


@pytest.fixture(scope="module")
def wsc_manifest() -> SourceManifest:
    return SourceManifest.load(MANIFEST, repository_root=ROOT)


@pytest.fixture(scope="module")
def wsc_model(wsc_manifest: SourceManifest) -> dict[str, object]:
    return _independent_source_model(wsc_manifest)


@pytest.fixture(scope="module")
def wsc_candidate(
    tmp_path_factory: pytest.TempPathFactory, wsc_manifest: SourceManifest
) -> CandidatePackage:
    return reconstruct(wsc_manifest, tmp_path_factory.mktemp("wsc-candidate"), _convert)


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


def _accountability(candidate: CandidatePackage) -> dict[str, object]:
    return json.loads(candidate.member_bytes("source-accountability.json"))


class _ResealedProfileFacade:
    def __init__(
        self,
        manifest: SourceManifest,
        profile_path: Path,
        producer_closure_sha256: str,
    ) -> None:
        self._manifest = manifest
        self._profile_path = profile_path
        self.repository_root = manifest.repository_root
        self.path = manifest.path
        record = json.loads(manifest.path.read_bytes())
        profile_bytes = profile_path.read_bytes()
        profile_authority = next(
            item
            for item in record["authorities"]
            if item["name"] == "reconstruction-profile"
        )
        profile_authority.update(bytes=len(profile_bytes), sha256=_sha(profile_bytes))
        record["producer_import_closure_sha256"] = producer_closure_sha256
        self.sha256 = _sha(_canonical(record))
        record["authorities"] = tuple(record["authorities"])
        self.record = record

    def verify(self) -> None:
        return None

    def authority_path(self, name: str) -> Path:
        if name == "reconstruction-profile":
            return self._profile_path
        return self._manifest.authority_path(name)


def test_manifest_binds_three_witnesses_and_local_rights_authority(
    wsc_manifest: SourceManifest,
) -> None:
    primary = [
        item
        for item in wsc_manifest.record["authorities"]
        if item["role"] == "primary-source"
    ]
    assert [(item["name"], item["bytes"], item["sha256"]) for item in primary] == [
        (
            "creeds-wsc",
            32442,
            "0a569c527fb4332448b5b853ff0dd6c3d6b5dd6abb8c5a746d58d9172886ffc6",
        ),
        (
            "theologai-wsc",
            31139,
            "89547581ed26576d2ab595894d7b21ac12e78a66d96e251b419ed023856283de",
        ),
        (
            "westminster-standard-wsc",
            98505,
            "8ffe7e7ae54c16066cce41456a8260d21e5dc3948568507ffbfc83658d10615a",
        ),
    ]
    assert sum(int(item["bytes"]) for item in primary) == 162086
    rights = [
        item
        for item in wsc_manifest.record["authorities"]
        if item["role"] == "rights-evidence"
    ]
    assert [(item["name"], item["bytes"], item["sha256"]) for item in rights] == [
        (
            "creeds-readme",
            8871,
            "caa2a135ceb89bdea2baf411bcb2897b03c34d24473de7c43ca373c9d9008bef",
        ),
        (
            "theologai-readme",
            36726,
            "1f00454aa2be25c5b2c702878c671042b5b64a260dade323bb1db7623135cd1f",
        ),
        (
            "theologai-license",
            768,
            "757a501a3a9e69ff464efc40596ddeb6c322c4db4be80ada63d3c8171bde38c4",
        ),
    ]
    assert sum(int(item["bytes"]) for item in rights) == 46365
    assert (
        sum(int(item["bytes"]) for item in primary)
        + sum(int(item["bytes"]) for item in rights)
        == 208451
    )
    local_config = next(
        item
        for item in wsc_manifest.record["authorities"]
        if item["name"] == "local-source-config"
    )
    assert (local_config["bytes"], local_config["sha256"]) == (
        1606,
        "408335d74a50989be73188d1e14146dee34d3ae2fb40362e0b3b0a49fe8016f7",
    )
    profile = json.loads(
        wsc_manifest.authority_path("reconstruction-profile").read_bytes()
    )
    assert not any(key.startswith("reviewed_") for key in profile)
    assert not any(key.startswith("reviewed_") for key in profile["source_scope"])


def test_independent_source_truth_is_107_by_three_1083_and_401(
    wsc_model: dict[str, object],
) -> None:
    readings = wsc_model["readings"]
    assert {source: len(rows) for source, rows in readings.items()} == {
        "creeds-json": 107,
        "theologai-json": 107,
        "westminster-standard-html": 107,
    }
    assert all(
        [int(row["number"]) for row in rows] == list(range(1, 108))
        for rows in readings.values()
    )
    assert len(wsc_model["metadata"]) + 3 * 3 * 107 + 107 == 1083
    assert len(wsc_model["relationships"]) == 401
    assert wsc_model["question_exact_agreements"] == 79
    assert wsc_model["answer_exact_agreements"] == 22
    q37 = [item for item in wsc_model["relationships"] if item["question_number"] == 37]
    assert len(q37) == 7
    assert q37[-1] == {
        "id": "wsc-proof-q37-7",
        "question_number": 37,
        "occurrence": 7,
        "raw": "Job 19:26-27",
        "osis": ["Job.19.26-Job.19.27"],
        "source": "westminster-standard-html",
        "proof_group": "#wsc-westminster-standard-html-q37-proof-group",
        "target": "#wsc-westminster-standard-html-q37-proof-7",
    }


def test_complete_candidate_validates_is_xsd_valid_and_nonaccepted(
    wsc_manifest: SourceManifest,
    wsc_model: dict[str, object],
    wsc_candidate: CandidatePackage,
) -> None:
    assert set(wsc_candidate.member_names) == MEMBERS
    assert wsc_candidate.manifest["status"] == "nonaccepted"
    report = validate(wsc_manifest, wsc_candidate, _oracle)
    assert report.status == "pass"
    assert report.findings == ()
    tei = etree.fromstring(wsc_candidate.member_bytes("content.tei.xml"))
    oracle_module.compiled_schema().assertValid(etree.ElementTree(tei))
    accountability = _accountability(wsc_candidate)
    assert accountability["observation_counts"] == {
        "total": 1083,
        "represented": 1083,
        "evidence_only": 0,
        "omitted": 0,
        "duplicate": 0,
    }
    assert len(accountability["crosswalk"]) == 1083
    assert len({item["id"] for item in accountability["crosswalk"]}) == 1083
    assert len(accountability["proof_relationships"]) == 401
    assert accountability["outer_html_census"] == wsc_model["outer_html_census"]
    assert accountability["outer_html_census"] == _independent_outer_html_census(
        wsc_manifest.authority_path("westminster-standard-wsc").read_bytes()
    )


def test_fresh_process_complete_packages_are_byte_identical(tmp_path: Path) -> None:
    script = (
        "from pathlib import Path;import hashlib,sys;"
        "from ocd_kernel.reconstruction.contract import SourceManifest,reconstruct;"
        "from build.tei.westminster_shorter_catechism_reconstruction import _convert;"
        "r=Path(sys.argv[1]);m=SourceManifest.load(r/sys.argv[3],repository_root=r);"
        "c=reconstruct(m,Path(sys.argv[2]),_convert);"
        "print('|'.join(n+':'+hashlib.sha256(c.member_bytes(n)).hexdigest() for n in c.member_names))"
    )
    outputs = []
    for ordinal in (1, 2):
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                script,
                str(ROOT),
                str(tmp_path / f"fresh-{ordinal}"),
                MANIFEST.relative_to(ROOT).as_posix(),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(completed.stdout.strip())
    assert outputs[0] == outputs[1]


def test_oracle_closure_is_recursive_repo_local_and_producer_independent(
    wsc_manifest: SourceManifest,
) -> None:
    policy = json.loads(wsc_manifest.authority_path("validation-policy").read_bytes())
    assert (
        _closure_digest(ROOT, policy)
        == wsc_manifest.record["validator"]["import_closure_sha256"]
    )
    forbidden = tuple(policy["forbidden_import_prefixes"])
    oracle_closure = _repository_import_closure(
        ROOT, Path(oracle_module.__file__), forbidden
    )
    producer_closure = _repository_import_closure(
        ROOT,
        ROOT / "build/tei/westminster_shorter_catechism_reconstruction.py",
        forbidden,
    )
    paths = {item["path"] for item in oracle_closure}
    assert {
        "build/__init__.py",
        "build/tei/__init__.py",
        "build/tei/westminster_shorter_catechism_oracle.py",
        "ocd_kernel/__init__.py",
        "ocd_kernel/lib/__init__.py",
        "ocd_kernel/lib/path_io.py",
        "ocd_kernel/lib/storage_topology.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/tei/__init__.py",
        "ocd_kernel/tei/normalization.py",
        "ocd_kernel/tei/projection_profile.py",
        "ocd_kernel/tei/validate.py",
    } == paths
    producer_digest = _digest(producer_closure)
    profile = json.loads(
        wsc_manifest.authority_path("reconstruction-profile").read_bytes()
    )
    assert producer_digest == profile["producer_import_closure_sha256"]
    assert producer_digest == wsc_manifest.record["producer_import_closure_sha256"]
    _assert_runtime_paths(ROOT, oracle_closure, producer_closure)
    source = Path(oracle_module.__file__).read_text(encoding="utf-8")
    for forbidden in policy["forbidden_import_prefixes"]:
        assert f"import {forbidden}" not in source
        assert f"from {forbidden}" not in source
    for forbidden_path in policy["forbidden_answer_paths"]:
        assert forbidden_path not in source


def test_closure_rejects_forbidden_import_and_runtime_shadow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = tmp_path / "entry.py"
    entry.write_text(
        "import build.reconstruction.westminster_shorter_catechism_verifier\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="forbidden dependency"):
        _repository_import_closure(
            tmp_path,
            entry,
            ("build.reconstruction.westminster_shorter_catechism_verifier",),
        )
    entry.write_text(
        "__import__('build.reconstruction.westminster_shorter_catechism_verifier')\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="dynamic import or execution"):
        _repository_import_closure(
            tmp_path,
            entry,
            ("build.reconstruction.westminster_shorter_catechism_verifier",),
        )
    policy = json.loads(
        RETAINED_MANIFEST.with_name(
            "westminster-shorter-catechism.validation-policy.json"
        ).read_bytes()
    )
    forbidden = tuple(policy["forbidden_import_prefixes"])
    oracle_closure = _repository_import_closure(
        ROOT, Path(oracle_module.__file__), forbidden
    )
    producer_closure = _repository_import_closure(
        ROOT,
        ROOT / "build/tei/westminster_shorter_catechism_reconstruction.py",
        forbidden,
    )
    contract_module = sys.modules["ocd_kernel.reconstruction.contract"]
    monkeypatch.setattr(
        contract_module,
        "__file__",
        str(tmp_path / "site-packages/ocd_kernel/reconstruction/contract.py"),
    )
    with pytest.raises(ValueError, match="shadow"):
        _assert_runtime_paths(ROOT, oracle_closure, producer_closure)


@pytest.mark.parametrize(
    "source",
    [
        "eval('1')\n",
        "exec('value = 1')\n",
        "import importlib\nimportlib.import_module('invented')\n",
        "loader.exec_module(None)\n",
    ],
)
def test_closure_rejects_every_dynamic_execution_surface(
    source: str,
    tmp_path: Path,
) -> None:
    entry = tmp_path / "entry.py"
    entry.write_text(source, encoding="utf-8")
    with pytest.raises(ValueError, match="dynamic import or execution"):
        _repository_import_closure(tmp_path, entry, ())


def test_producer_dependency_and_package_initializer_drift_change_closures(
    tmp_path: Path,
    wsc_manifest: SourceManifest,
) -> None:
    policy = json.loads(wsc_manifest.authority_path("validation-policy").read_bytes())
    forbidden = tuple(policy["forbidden_import_prefixes"])
    entries = {
        "producer": ROOT / "build/tei/westminster_shorter_catechism_reconstruction.py",
        "oracle": ROOT / "build/tei/westminster_shorter_catechism_oracle.py",
    }
    mutations = {
        "producer": "ocd_kernel/reconstruction/contract.py",
        "oracle": "ocd_kernel/tei/__init__.py",
    }
    for label, entry in entries.items():
        closure = _repository_import_closure(ROOT, entry, forbidden)
        copy_root = tmp_path / label
        for record in closure:
            destination = copy_root / record["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / record["path"], destination)
        copied_entry = copy_root / entry.relative_to(ROOT)
        before = _digest(_repository_import_closure(copy_root, copied_entry, forbidden))
        dependency = copy_root / mutations[label]
        dependency.write_bytes(dependency.read_bytes() + b"\n# isolated drift\n")
        after = _digest(_repository_import_closure(copy_root, copied_entry, forbidden))
        assert after != before


def test_coordinated_profile_manifest_closure_reseal_fails_independent_oracle(
    tmp_path: Path,
    wsc_manifest: SourceManifest,
) -> None:
    invented = "0" * 64
    profile = json.loads(
        wsc_manifest.authority_path("reconstruction-profile").read_bytes()
    )
    profile["producer_import_closure_sha256"] = invented
    profile_path = tmp_path / "resealed-profile.json"
    profile_path.write_bytes(
        json.dumps(profile, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
    facade = _ResealedProfileFacade(wsc_manifest, profile_path, invented)
    candidate = reconstruct(facade, tmp_path / "resealed-candidate", _convert)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="producer recursive import closure drift"):
        _oracle(facade, candidate)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "module_name",
    ["ocd_kernel.reconstruction.contract", "ocd_kernel.tei", "build.tei"],
)
def test_subprocess_rejects_editable_or_site_package_closure_shadow(
    module_name: str,
    tmp_path: Path,
) -> None:
    script = (
        "import json,sys;from pathlib import Path;"
        "import build.tei.westminster_shorter_catechism_reconstruction;"
        "import build.tei.westminster_shorter_catechism_oracle as o;"
        "r=Path(sys.argv[1]);p=json.loads((r/'sources/catechisms/westminster-shorter-catechism/westminster-shorter-catechism.validation-policy.json').read_bytes());"
        "f=tuple(p['forbidden_import_prefixes']);"
        "oc=o._repository_import_closure(r,Path(o.__file__),f);"
        "pc=o._repository_import_closure(r,r/'build/tei/westminster_shorter_catechism_reconstruction.py',f);"
        "sys.modules[sys.argv[2]].__file__=str(Path(sys.argv[3])/'site-packages'/Path(*sys.argv[2].split('.')));"
        "o._assert_runtime_paths(r,oc,pc)"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script, str(ROOT), module_name, str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "runtime module path shadow detected" in completed.stderr


def test_maintained_candidate_launcher_accepts_exact_digest_bound_module_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "candidate"
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "build.tools.reconstruct_candidate",
            "--manifest",
            MANIFEST.relative_to(ROOT).as_posix(),
            "--destination",
            str(destination),
            "--repository-root",
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    handoff = json.loads(completed.stdout)
    assert handoff["status"] == "pass"
    assert handoff["acceptance_status"] == "nonaccepted"
    assert handoff["human_review_required"] is True
    assert handoff["publication_status"] == "not-authorized"

    from build.tools import count_dataset_records

    manifest_selection = MANIFEST.relative_to(ROOT).as_posix()

    def selected_manifest_paths(sources_root: Path, selections):
        assert sources_root == ROOT / "sources"
        assert tuple(selections) == (manifest_selection,)
        return sources_root, None

    original_rglob = Path.rglob

    def selected_manifest_discovery(path: Path, pattern: str):
        if path == ROOT / "sources" and pattern in {"*.source-manifest.json", "source-manifest.json"}:
            return iter((MANIFEST,))
        return original_rglob(path, pattern)

    # Select the exact test authority while preserving production evidence checks.
    monkeypatch.setattr(Path, "rglob", selected_manifest_discovery)
    monkeypatch.setattr(
        count_dataset_records, "_resolve_source_manifest_allowlist", selected_manifest_paths
    )

    catalog = count_dataset_records.collect_work_catalog(
        ROOT / "data",
        source_manifest_allowlist=[manifest_selection],
        data_resource_allowlist=["data/catechisms/westminster-shorter-catechism.json"],
        reconstruction_evidence={
            (
                "westminster-shorter-catechism-three-retained-witnesses",
                "westminster-shorter-catechism",
            ): (destination / "package", destination / "validation.json")
        },
    )
    work = next(
        item
        for item in catalog.works
        if item["work_id"] == "westminster-shorter-catechism"
    )
    state = work["reconstruction_state"]
    assert state["tei_candidate"] == "verified"
    assert state["validation"] == "verified"
    assert state["human_review"] == "required"
    assert state["accepted_ir"] == "not_accepted"
    assert state["publication"] == "not_ready"


@pytest.mark.parametrize(
    "mutation",
    [
        "witness-wrapper-swap",
        "question-wrapper-swap",
        "question-answer-carrier-swap",
        "question-carrier-omission",
        "answer-carrier-duplication",
        "disagreement-reading-swap",
        "answer-reading-swap",
        "reading-conflation",
        "proof-q37-job-drop",
        "proof-cross-question-move",
        "proof-order-swap",
        "proof-occurrence-swap",
        "proof-raw-swap",
        "proof-osis-swap",
        "selected-reading-invention",
        "header-author-invention",
        "header-provider-invention",
        "metadata-date-invention",
        "edition-certainty-invention",
        "rights-certainty-invention",
    ],
)
def test_oracle_rejects_xsd_valid_structure_reading_proof_header_and_rights_mutations(
    tmp_path: Path,
    wsc_candidate: CandidatePackage,
    wsc_manifest: SourceManifest,
    mutation: str,
) -> None:
    path = _copy(tmp_path, wsc_candidate, mutation)
    tei = etree.fromstring((path / "content.tei.xml").read_bytes())
    if mutation == "witness-wrapper-swap":
        first, second = tei.xpath("./tei:text/tei:group/tei:text", namespaces=NS)[:2]
        first_id, first_n = first.get(XML_ID), first.get("n")
        first.set(XML_ID, second.get(XML_ID))
        first.set("n", second.get("n"))
        second.set(XML_ID, first_id)
        second.set("n", first_n)
    elif mutation == "question-wrapper-swap":
        first, second = tei.xpath(
            "./tei:text/tei:group/tei:text[1]/tei:body/tei:div", namespaces=NS
        )[:2]
        first_id, first_n = first.get(XML_ID), first.get("n")
        first.set(XML_ID, second.get(XML_ID))
        first.set("n", second.get("n"))
        second.set(XML_ID, first_id)
        second.set("n", first_n)
    elif mutation == "question-answer-carrier-swap":
        unit = tei.xpath("//*[@xml:id='wsc-creeds-json-q1']", namespaces=NS)[0]
        question, answer = unit[1], unit[2]
        unit.remove(question)
        unit.insert(2, question)
        assert list(unit)[1:3] == [answer, question]
    elif mutation == "question-carrier-omission":
        node = tei.xpath("//*[@xml:id='wsc-creeds-json-q1-question']", namespaces=NS)[0]
        node.getparent().remove(node)
    elif mutation == "answer-carrier-duplication":
        node = tei.xpath("//*[@xml:id='wsc-creeds-json-q1-answer']", namespaces=NS)[0]
        duplicate = copy.deepcopy(node)
        duplicate.set(XML_ID, "wsc-creeds-json-q1-answer-invented")
        node.getparent().append(duplicate)
    elif mutation == "disagreement-reading-swap":
        creeds = tei.xpath("//*[@xml:id='wsc-creeds-json-q3-question']", namespaces=NS)[
            0
        ]
        theologai = tei.xpath(
            "//*[@xml:id='wsc-theologai-json-q3-question']", namespaces=NS
        )[0]
        creeds.text, theologai.text = theologai.text, creeds.text
    elif mutation == "answer-reading-swap":
        creeds = tei.xpath("//*[@xml:id='wsc-creeds-json-q1-answer']", namespaces=NS)[0]
        theologai = tei.xpath(
            "//*[@xml:id='wsc-theologai-json-q1-answer']", namespaces=NS
        )[0]
        creeds.text, theologai.text = theologai.text, creeds.text
    elif mutation == "reading-conflation":
        readings = tei.xpath(
            "//*[@xml:id='wsc-retained-witnesses']/tei:text/tei:body/tei:div[3]/tei:p[@ana='#question']",
            namespaces=NS,
        )
        assert len(readings) == 3
        for reading in readings[1:]:
            reading.text = readings[0].text
    elif mutation == "proof-q37-job-drop":
        node = tei.xpath(
            "//*[@xml:id='wsc-westminster-standard-html-q37-proof-7']", namespaces=NS
        )[0]
        node.getparent().remove(node)
    elif mutation == "proof-cross-question-move":
        node = tei.xpath(
            "//*[@xml:id='wsc-westminster-standard-html-q37-proof-7']", namespaces=NS
        )[0]
        destination = tei.xpath(
            "//*[@xml:id='wsc-westminster-standard-html-q36-proof-group']",
            namespaces=NS,
        )[0]
        node.getparent().remove(node)
        node.set(
            XML_ID, f"wsc-westminster-standard-html-q36-proof-{len(destination) + 1}"
        )
        destination.append(node)
    elif mutation == "proof-order-swap":
        group = tei.xpath(
            "//*[@xml:id='wsc-westminster-standard-html-q37-proof-group']",
            namespaces=NS,
        )[0]
        first = group[0]
        group.remove(first)
        group.insert(1, first)
    elif mutation == "proof-occurrence-swap":
        first, second = tei.xpath(
            "//*[@xml:id='wsc-westminster-standard-html-q37-proof-group']/tei:bibl",
            namespaces=NS,
        )[:2]
        first_id = first.get(XML_ID)
        first.set(XML_ID, second.get(XML_ID))
        second.set(XML_ID, first_id)
    elif mutation == "proof-raw-swap":
        first, second = tei.xpath("//tei:ref[@type='scripture']", namespaces=NS)[:2]
        first.text, second.text = second.text, first.text
    elif mutation == "proof-osis-swap":
        first, second = tei.xpath("//tei:ref[@type='scripture']", namespaces=NS)[:2]
        first_osis, second_osis = first.get("cRef"), second.get("cRef")
        first.set("cRef", second_osis)
        second.set("cRef", first_osis)
    elif mutation == "selected-reading-invention":
        paragraph = tei.xpath("./tei:teiHeader/tei:encodingDesc/tei:p", namespaces=NS)[
            0
        ]
        paragraph.text = "Creeds.json is selected as the normalized edition reading."
    elif mutation == "header-author-invention":
        author = tei.xpath(
            "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", namespaces=NS
        )[0]
        author.text = "The Westminster Standard"
    elif mutation == "header-provider-invention":
        provider = tei.xpath(
            "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:respStmt[1]/tei:name",
            namespaces=NS,
        )[0]
        provider.text = "Selected Westminster edition publisher"
    elif mutation == "metadata-date-invention":
        item = next(
            node
            for node in tei.xpath(
                "./tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:item", namespaces=NS
            )
            if ":date=" in (node.text or "")
        )
        item.text = (item.text or "").replace("1647", "1648")
    elif mutation == "edition-certainty-invention":
        note = tei.xpath(
            "./tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:note[@type='edition-status']",
            namespaces=NS,
        )[0]
        note.text = "Authoritative 1647 edition selected."
    elif mutation == "rights-certainty-invention":
        availability = tei.xpath(
            "./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability",
            namespaces=NS,
        )[0]
        availability.set("status", "free")
        availability[0].text = "Public domain worldwide; publication is authorized."
    assert oracle_module.compiled_schema().validate(etree.ElementTree(tei))
    mutated = _reseal(
        path,
        "content.tei.xml",
        etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False),
    )
    with pytest.raises(ValueError):
        validate(wsc_manifest, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    [
        "observation-omission",
        "observation-duplication",
        "identical-number-target-swap",
        "identical-answer-target-swap",
        "question-answer-target-swap",
        "proof-relationship-shift",
        "proof-relationship-400",
        "proof-repeated-occurrence-replacement",
        "outer-carrier-stream",
    ],
)
def test_oracle_rejects_resealed_accountability_count_and_attachment_attacks(
    tmp_path: Path,
    wsc_candidate: CandidatePackage,
    wsc_manifest: SourceManifest,
    mutation: str,
) -> None:
    path = _copy(tmp_path, wsc_candidate, mutation)
    record = json.loads((path / "source-accountability.json").read_bytes())
    crosswalk = record["crosswalk"]
    relationships = record["proof_relationships"]
    if mutation == "observation-omission":
        crosswalk.pop()
    elif mutation == "observation-duplication":
        crosswalk[-1] = copy.deepcopy(crosswalk[-2])
    elif mutation == "identical-number-target-swap":
        first = next(
            item
            for item in crosswalk
            if item["id"] == "wsc-observation-creeds-json-q1-number"
        )
        second = next(
            item
            for item in crosswalk
            if item["id"] == "wsc-observation-theologai-json-q1-number"
        )
        first["target"], second["target"] = second["target"], first["target"]
    elif mutation == "identical-answer-target-swap":
        first = next(
            item
            for item in crosswalk
            if item["id"] == "wsc-observation-theologai-json-q1-answer"
        )
        second = next(
            item
            for item in crosswalk
            if item["id"] == "wsc-observation-westminster-standard-html-q1-answer"
        )
        assert first["value"] == second["value"]
        first["target"], second["target"] = second["target"], first["target"]
    elif mutation == "question-answer-target-swap":
        first = next(
            item
            for item in crosswalk
            if item["id"] == "wsc-observation-creeds-json-q1-question"
        )
        second = next(
            item
            for item in crosswalk
            if item["id"] == "wsc-observation-creeds-json-q1-answer"
        )
        first["target"], second["target"] = second["target"], first["target"]
    elif mutation == "proof-relationship-shift":
        moved = next(item for item in relationships if item["id"] == "wsc-proof-q37-7")
        moved.update(
            id="wsc-proof-q36-6",
            question_number=36,
            occurrence=6,
            proof_group="#wsc-westminster-standard-html-q36-proof-group",
            target="#wsc-westminster-standard-html-q36-proof-6",
        )
    elif mutation == "proof-relationship-400":
        relationships[:] = [
            item for item in relationships if item["id"] != "wsc-proof-q37-7"
        ]
        record["proof_reference_count"] = 400
    elif mutation == "proof-repeated-occurrence-replacement":
        by_raw: dict[str, list[dict[str, object]]] = {}
        for item in relationships:
            by_raw.setdefault(str(item["raw"]), []).append(item)
        repeated = [items for items in by_raw.values() if len(items) > 1]
        omitted, replacement = repeated[:2]
        omitted[-1]["raw"] = replacement[0]["raw"]
        omitted[-1]["osis"] = replacement[0]["osis"]
    elif mutation == "outer-carrier-stream":
        record["outer_html_census"]["comments"]["stream_sha256"] = "0" * 64
    mutated = _reseal(path, "source-accountability.json", _canonical(record))
    with pytest.raises(ValueError):
        validate(wsc_manifest, mutated, _oracle)


def test_oracle_rejects_coordinated_metadata_rights_and_readme_invention(
    tmp_path: Path, wsc_candidate: CandidatePackage, wsc_manifest: SourceManifest
) -> None:
    path = _copy(tmp_path, wsc_candidate, "coordinated-invention")
    provenance = json.loads((path / "provenance.json").read_bytes())
    provenance["rights"] = {
        key: "public domain worldwide; publication authorized"
        for key in provenance["rights"]
    }
    mutated = _reseal(path, "provenance.json", _canonical(provenance))
    unresolved = (
        b'{"detail":"none","id":"wsc-clear","kind":"rights","status":"resolved"}\n'
    )
    mutated = _reseal(path, "unresolved.jsonl", unresolved)
    mutated = _reseal(
        path,
        "README.source.md",
        b"Public domain worldwide; accepted and publishable.\n",
    )
    tei = etree.fromstring((path / "content.tei.xml").read_bytes())
    availability = tei.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability",
        namespaces=NS,
    )[0]
    availability.set("status", "free")
    availability[0].text = "Public domain worldwide; accepted and publishable."
    mutated = _reseal(
        path,
        "content.tei.xml",
        etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False),
    )
    with pytest.raises(ValueError):
        validate(wsc_manifest, mutated, _oracle)


@pytest.mark.parametrize(
    "mutation",
    [
        "appended-definitive-date",
        "appended-worldwide-rights-certainty",
        "appended-selected-reading-division",
    ],
)
def test_oracle_rejects_resealed_xsd_valid_additive_tei_inventions(
    tmp_path: Path,
    wsc_candidate: CandidatePackage,
    wsc_manifest: SourceManifest,
    mutation: str,
) -> None:
    path = _copy(tmp_path, wsc_candidate, mutation)
    tei = etree.fromstring((path / "content.tei.xml").read_bytes())
    tei_namespace = "{http://www.tei-c.org/ns/1.0}"
    if mutation == "appended-definitive-date":
        bibl = tei.xpath(
            "./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:listBibl/tei:bibl[1]",
            namespaces=NS,
        )[0]
        date = etree.SubElement(bibl, f"{tei_namespace}date", when="1647")
        date.text = "1647 (definitive)"
    elif mutation == "appended-worldwide-rights-certainty":
        availability = tei.xpath(
            "./tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability",
            namespaces=NS,
        )[0]
        certainty = etree.SubElement(availability, f"{tei_namespace}p")
        certainty.text = (
            "This work is in the public domain worldwide and cleared for publication."
        )
    elif mutation == "appended-selected-reading-division":
        body = tei.xpath("./tei:text/tei:group/tei:text[1]/tei:body", namespaces=NS)[0]
        selected = etree.SubElement(
            body,
            f"{tei_namespace}div",
            type="selected-reading",
        )
        selected.set(XML_ID, "invented-selected-reading")
        paragraph = etree.SubElement(selected, f"{tei_namespace}p")
        paragraph.text = "Definitive normalized reading."
    assert oracle_module.compiled_schema().validate(etree.ElementTree(tei))
    mutated = _reseal(
        path,
        "content.tei.xml",
        etree.tostring(tei, encoding="UTF-8", xml_declaration=True, pretty_print=False),
    )
    with pytest.raises(ValueError, match="complete TEI projection"):
        validate(wsc_manifest, mutated, _oracle)


@pytest.mark.parametrize(
    "authority_name",
    [
        "creeds-wsc",
        "theologai-wsc",
        "westminster-standard-wsc",
        "creeds-readme",
        "theologai-readme",
        "theologai-license",
        "local-source-config",
        "reconstruction-profile",
        "outer-html-profile",
        "validation-policy",
        "source-accountability-schema",
        "tei-p5-xsd",
        "candidate-package-schema",
    ],
)
def test_source_manifest_rejects_source_and_governance_drift(
    tmp_path: Path, authority_name: str
) -> None:
    record = json.loads(MANIFEST.read_bytes())
    for authority in record["authorities"]:
        source = ROOT / authority["path"]
        destination = tmp_path / authority["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    for binding in (record["converter"], record["validator"]):
        source = ROOT / binding["implementation_path"]
        destination = tmp_path / binding["implementation_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    manifest_path = tmp_path / MANIFEST.relative_to(ROOT)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(MANIFEST.read_bytes())
    target = next(
        item for item in record["authorities"] if item["name"] == authority_name
    )
    path = tmp_path / target["path"]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="authority bytes drifted"):
        SourceManifest.load(manifest_path, repository_root=tmp_path)


def test_candidate_rejects_extra_member(
    tmp_path: Path, wsc_candidate: CandidatePackage
) -> None:
    path = _copy(tmp_path, wsc_candidate, "extra-member")
    (path / "answers.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly six flat members"):
        CandidatePackage.load(path)
