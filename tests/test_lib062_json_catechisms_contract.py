from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import etree
import pytest

from build.tei import lib062_json_catechisms_oracle as oracle
from build.tei import lib062_json_catechisms_reconstruction as producer
from ocd_kernel.lib.storage_topology import resolve_repo_path


ROOT = Path(__file__).resolve().parents[1]
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NS = {"tei": "http://www.tei-c.org/ns/1.0"}
LEAF_COUNTS = {
    "1695-baptist-catechism": 1146,
    "catechism-for-young-children": 445,
    "exposition-of-the-assemblies-catechism": 4141,
    "heidelberg-catechism": 1898,
    "keachs-catechism": 1058,
    "matthew-henrys-scripture-catechism": 8593,
    "puritan-catechism": 772,
    "shorter-catechism-explained": 11836,
    "westminster-larger-catechism": 4432,
}


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


@pytest.fixture(scope="session")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> Path:
    session_root = tmp_path_factory.mktemp("lib062-session")
    candidate = session_root / "baseline"
    producer.reconstruct(ROOT, candidate)
    oracle.finalize(ROOT, candidate)
    oracle.verify_sealed(candidate)
    return candidate


def _unsealed_copy(tmp_path: Path, baseline: Path, label: str) -> Path:
    candidate = tmp_path / label
    shutil.copytree(baseline, candidate)
    (candidate / "manifest.json").unlink()
    (candidate / "evidence" / "oracle-result.json").unlink()
    (candidate / "evidence" / "oracle-import-closure.json").unlink()
    return candidate


def _reseal_manifest(candidate: Path) -> None:
    manifest_path = candidate / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    members = []
    for path in sorted(
        (
            item
            for item in candidate.rglob("*")
            if item.is_file() and item != manifest_path
        ),
        key=lambda item: item.relative_to(candidate).as_posix(),
    ):
        content = path.read_bytes()
        members.append(
            {
                "path": path.relative_to(candidate).as_posix(),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest["members"] = members
    manifest_path.write_bytes(_canonical(manifest))


def _inventory_records(candidate: Path, excluded: set[str]) -> list[dict[str, object]]:
    records = []
    for path in sorted(
        (
            item
            for item in candidate.rglob("*")
            if item.is_file() and item.relative_to(candidate).as_posix() not in excluded
        ),
        key=lambda item: item.relative_to(candidate).as_posix(),
    ):
        content = path.read_bytes()
        records.append(
            {
                "path": path.relative_to(candidate).as_posix(),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return records


def _self_consistently_reseal_closures(candidate: Path) -> None:
    producer_path = candidate / "evidence/producer-import-closure.json"
    oracle_path = candidate / "evidence/oracle-import-closure.json"
    producer_record = json.loads(producer_path.read_bytes())
    oracle_record = json.loads(oracle_path.read_bytes())
    producer_record["sha256"] = hashlib.sha256(
        _canonical(producer_record["members"])
    ).hexdigest()
    oracle_record["sha256"] = hashlib.sha256(
        _canonical(oracle_record["members"])
    ).hexdigest()
    producer_path.write_bytes(_canonical(producer_record))
    oracle_path.write_bytes(_canonical(oracle_record))
    result_path = candidate / "evidence/oracle-result.json"
    result = json.loads(result_path.read_bytes())
    result["producer_import_closure_sha256"] = producer_record["sha256"]
    result["oracle_import_closure_sha256"] = oracle_record["sha256"]
    pre_result = _inventory_records(
        candidate, {"manifest.json", "evidence/oracle-result.json"}
    )
    result["validated_payload_sha256"] = hashlib.sha256(
        _canonical(pre_result)
    ).hexdigest()
    result_path.write_bytes(_canonical(result))
    _reseal_manifest(candidate)


@pytest.mark.parametrize("module", [producer, oracle])
def test_recursive_json_equality_is_type_and_order_aware(module: object) -> None:
    assert not module._json_equal(True, 1)
    assert not module._json_equal(False, 0)
    assert not module._json_equal({"a": 1, "b": 2}, {"b": 2, "a": 1})
    assert not module._json_equal([1, 2], [2, 1])
    assert module._json_equal({"a": [1, False]}, {"a": [1, False]})


@pytest.mark.requires_local_artifacts
def test_all_nine_packets_census_and_leaf_counts_are_exact() -> None:
    census_path = (
        ROOT / "sources/1695-baptist-catechism/LIB-062.retained-member-census.json"
    )
    census = json.loads(census_path.read_bytes())
    assert census["member_count"] == len(census["members"]) == 61
    assert [item["path"] for item in census["members"]] == sorted(
        item["path"] for item in census["members"]
    )
    assert (
        sum(item["disposition"] == "included-authority" for item in census["members"])
        == 9
    )
    assert (
        sum(
            item["disposition"] == "excluded-outside-LIB-062-assigned-scope"
            for item in census["members"]
        )
        == 34
    )
    assert (
        sum(
            item["disposition"] == "excluded-adjacent-witness-no-human-source-choice"
            for item in census["members"]
        )
        == 2
    )
    assert (
        sum(
            item["disposition"] == "excluded-unrelated-to-LIB-062-assigned-scope"
            for item in census["members"]
        )
        == 15
    )
    assert (
        sum(
            item["disposition"] == "included-terms-evidence"
            for item in census["members"]
        )
        == 1
    )
    census_binding = {
        "path": census_path.relative_to(ROOT).as_posix(),
        "bytes": len(census_path.read_bytes()),
        "sha256": hashlib.sha256(census_path.read_bytes()).hexdigest(),
    }
    observed = {}
    empty_leaf_count = 0
    for work_id, _ in producer.WORKS:
        packet = json.loads(
            (ROOT / "sources" / work_id / "LIB-062.packet.json").read_bytes()
        )
        assert packet["authority"]["path"].startswith("raw/")
        assert packet["terms_evidence"]["path"] == "raw/Creeds.json/README.md"
        assert all(
            item["path"].startswith("raw/") for item in packet["adjacent_witnesses"]
        )
        assert packet["retained_member_census"] == census_binding
        observed[work_id] = packet["profile"]["accountable_leaf_count"]
        source = json.loads(
            resolve_repo_path(ROOT, packet["authority"]["path"]).read_bytes()
        )
        empty_leaf_count += sum(
            value in ({}, []) for _, value in producer._accountable_leaves(source)
        )
    assert observed == LEAF_COUNTS
    assert sum(observed.values()) == 34321
    assert empty_leaf_count == 44
    producer._retained_member_census(ROOT)
    oracle._retained_member_census(ROOT)


@pytest.mark.requires_local_artifacts
def test_baseline_is_complete_nonaccepted_and_self_contained(baseline: Path) -> None:
    manifest = oracle.verify_sealed(baseline)
    assert manifest["work_count"] == manifest["tei_count"] == 9
    assert manifest["member_count"] == len(manifest["members"]) == 34
    assert len(list((baseline / "tei").glob("*.tei.xml"))) == 9
    assert len(list((baseline / "source-accounting").glob("*.json"))) == 9
    assert (baseline / "evidence" / "retained-member-census.json").read_bytes() == (
        ROOT / "sources/1695-baptist-catechism/LIB-062.retained-member-census.json"
    ).read_bytes()
    result = json.loads((baseline / "evidence" / "oracle-result.json").read_bytes())
    assert (
        result["technical_acceptance"],
        result["human_acceptance"],
        result["publication"],
    ) == ("not_claimed", "not_performed", "not_ready")


@pytest.mark.requires_local_artifacts
def test_fresh_process_different_cwd_and_hash_seed_is_byte_identical(
    tmp_path: Path,
) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    other_cwd = tmp_path / "different-cwd"
    other_cwd.mkdir()
    for destination, cwd, seed in ((first, ROOT, "17"), (second, other_cwd, "941")):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = str(ROOT)
        subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "build/tei/lib062_json_catechisms_reconstruction.py"),
                "--repository-root",
                str(ROOT),
                "--destination",
                str(destination),
            ],
            cwd=cwd,
            env=environment,
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                "-B",
                str(ROOT / "build/tei/lib062_json_catechisms_oracle.py"),
                "--repository-root",
                str(ROOT),
                "--candidate-root",
                str(destination),
            ],
            cwd=cwd,
            env=environment,
            check=True,
        )
    paths = {
        path.relative_to(first).as_posix()
        for path in first.rglob("*")
        if path.is_file()
    }
    assert paths == {
        path.relative_to(second).as_posix()
        for path in second.rglob("*")
        if path.is_file()
    }
    assert all(
        (first / path).read_bytes() == (second / path).read_bytes() for path in paths
    )


@pytest.mark.parametrize("scope", ["repository", pytest.param("durable", marks=pytest.mark.requires_local_artifacts), "git"])
def test_destination_safety_rejects_repository_durable_and_git_ancestors(
    tmp_path: Path, scope: str
) -> None:
    if scope == "repository":
        destination = ROOT / "forbidden-lib062-candidate"
        match = "outside the repository"
    elif scope == "durable":
        destination = (
            resolve_repo_path(ROOT, "raw").parent / "forbidden-lib062-candidate"
        )
        match = "outside every durable library surface"
    else:
        git_root = tmp_path / "detected-git-worktree"
        git_root.mkdir()
        (git_root / ".git").mkdir()
        destination = git_root / "candidate"
        match = "outside every Git repository or worktree"
    with pytest.raises(ValueError, match=match):
        producer._safe_destination(ROOT, destination)
    assert not destination.exists()


def test_producer_rejects_dangling_destination_reparse_before_following(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "dangling-candidate-alias"
    monkeypatch.setattr(
        producer,
        "_lexical_is_reparse",
        lambda path: path == destination,
    )
    with pytest.raises(ValueError, match="symlink, junction, or reparse"):
        producer._safe_destination(ROOT, destination)
    assert not destination.exists()


@pytest.mark.parametrize("scope", ["repository", *[pytest.param(scope, marks=pytest.mark.requires_local_artifacts) for scope in ("raw", "reports", "exports")], "git"])
def test_oracle_guard_rejects_repository_durable_and_git_ancestors(
    tmp_path: Path, scope: str
) -> None:
    if scope == "repository":
        candidate = ROOT
        match = "outside the repository"
    elif scope in {"raw", "reports", "exports"}:
        candidate = resolve_repo_path(ROOT, scope)
        match = "outside every durable library surface"
    else:
        git_root = tmp_path / "oracle-git-ancestor"
        candidate = git_root / "populated-candidate"
        candidate.mkdir(parents=True)
        (git_root / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        (candidate / "payload.txt").write_text("populated\n", encoding="utf-8")
        match = "outside every Git repository or worktree"
    with pytest.raises(ValueError, match=match):
        oracle._guard_candidate_destination(ROOT, candidate)


@pytest.mark.requires_local_artifacts
def test_verify_only_rejects_candidate_root_alias_lexically(
    baseline: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        oracle,
        "_lexical_is_reparse",
        lambda path: path == baseline,
    )
    with pytest.raises(ValueError, match="non-reparse lexical path"):
        oracle.verify_sealed(baseline)


@pytest.mark.parametrize("module", [producer, oracle])
@pytest.mark.requires_local_artifacts
def test_protected_census_rejects_reparse_or_nonregular_member(
    monkeypatch: pytest.MonkeyPatch, module: object
) -> None:
    protected = resolve_repo_path(
        ROOT, "raw/Creeds.json/creeds/1695_baptist_catechism.json"
    ).resolve()
    original = module._is_reparse

    def selected_reparse(path: Path) -> bool:
        return path.resolve() == protected or original(path)

    monkeypatch.setattr(module, "_is_reparse", selected_reparse)
    with pytest.raises(ValueError, match="non-reparse regular file"):
        module._retained_member_census(ROOT)


@pytest.mark.parametrize(
    "location", ["top-level", "nested-file", "nested-directory", "reparse"]
)
@pytest.mark.requires_local_artifacts
def test_oracle_rejects_preseal_unexpected_or_reparse_entries(
    tmp_path: Path,
    baseline: Path,
    monkeypatch: pytest.MonkeyPatch,
    location: str,
) -> None:
    candidate = _unsealed_copy(tmp_path, baseline, f"preseal-{location}")
    if location == "top-level":
        (candidate / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        match = "candidate file set drift"
    elif location == "nested-file":
        (candidate / "evidence/unexpected.txt").write_text(
            "unexpected\n", encoding="utf-8"
        )
        match = "candidate file set drift"
    elif location == "nested-directory":
        (candidate / "evidence/unexpected").mkdir()
        match = "candidate directory set drift"
    else:
        selected = (candidate / "README.source.md").resolve()
        original = oracle._is_reparse
        monkeypatch.setattr(
            oracle,
            "_is_reparse",
            lambda path: path.resolve() == selected or original(path),
        )
        match = "candidate contains reparse entry"
    with pytest.raises(ValueError, match=match):
        oracle.finalize(ROOT, candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        "omission",
        "duplication",
        "reorder",
        "invented-question",
        "nested-loss",
        "metadata-drift",
        "adjacent-mixing",
        "additive-invention",
    ],
)
@pytest.mark.requires_local_artifacts
def test_oracle_rejects_qa_structure_metadata_and_adjacent_mutations(
    tmp_path: Path, baseline: Path, mutation: str
) -> None:
    candidate = _unsealed_copy(tmp_path, baseline, mutation)
    work_id = (
        "exposition-of-the-assemblies-catechism"
        if mutation == "nested-loss"
        else "heidelberg-catechism"
    )
    tei_path = candidate / "tei" / f"{work_id}.tei.xml"
    document = etree.fromstring(tei_path.read_bytes())
    rows = document.xpath("./tei:text/tei:body/tei:div/tei:div", namespaces=NS)
    if mutation == "omission":
        rows[0].getparent().remove(rows[0])
    elif mutation == "duplication":
        duplicate = copy.deepcopy(rows[0])
        for node in duplicate.xpath(
            ".//*[@xml:id]", namespaces={"xml": "http://www.w3.org/XML/1998/namespace"}
        ):
            node.set(XML_ID, f"invented-{node.get(XML_ID)}")
        duplicate.set(XML_ID, f"invented-{duplicate.get(XML_ID)}")
        rows[0].getparent().append(duplicate)
    elif mutation == "reorder":
        parent = rows[0].getparent()
        parent.remove(rows[1])
        parent.insert(0, rows[1])
    elif mutation == "invented-question":
        document.xpath(".//tei:p[@ana='#question']", namespaces=NS)[
            0
        ].text = "Invented modern wording?"
    elif mutation == "nested-loss":
        nested = document.xpath(".//tei:list[@type='subquestions']", namespaces=NS)[0]
        nested.getparent().remove(nested)
    elif mutation == "metadata-drift":
        document.xpath(
            "./tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", namespaces=NS
        )[0].text = "Invented edition title"
    elif mutation == "adjacent-mixing":
        adjacent = json.loads(
            resolve_repo_path(
                ROOT,
                "raw/TheologAI/data/historical-documents/heidelberg-catechism.json",
            ).read_bytes()
        )
        document.xpath(".//tei:p[@ana='#question']", namespaces=NS)[97].text = adjacent[
            "sections"
        ][97]["q"]
    else:
        etree.SubElement(rows[0], f"{{{NS['tei']}}}p").text = "Invented commentary"
    tei_path.write_bytes(
        etree.tostring(
            document, encoding="UTF-8", xml_declaration=True, pretty_print=False
        )
    )
    with pytest.raises(ValueError, match="complete TEI projection drift"):
        oracle.finalize(ROOT, candidate)


@pytest.mark.parametrize(
    "pointer", ["/Metadata/Authors/1", "/Metadata/AlternativeTitles"]
)
@pytest.mark.requires_local_artifacts
def test_oracle_rejects_second_author_and_empty_container_accountability_omission(
    tmp_path: Path, baseline: Path, pointer: str
) -> None:
    work_id = (
        "shorter-catechism-explained"
        if pointer.endswith("/1")
        else "catechism-for-young-children"
    )
    candidate = _unsealed_copy(tmp_path, baseline, f"leaf-{work_id}")
    path = candidate / "source-accounting" / f"{work_id}.json"
    record = json.loads(path.read_bytes())
    record["crosswalk"] = [
        item for item in record["crosswalk"] if item["pointer"] != pointer
    ]
    record["represented_leaf_count"] = len(record["crosswalk"])
    path.write_bytes(_canonical(record))
    with pytest.raises(
        ValueError,
        match="exact ordered accountability crosswalk drift|complete accountability pointer set drift",
    ):
        oracle.finalize(ROOT, candidate)


@pytest.mark.parametrize("mutation", ["target-swap", "row-order-swap"])
@pytest.mark.requires_local_artifacts
def test_oracle_requires_exact_ordered_crosswalk_records(
    tmp_path: Path, baseline: Path, mutation: str
) -> None:
    work_id = "1695-baptist-catechism"
    candidate = _unsealed_copy(tmp_path, baseline, f"crosswalk-{mutation}")
    accounting_path = candidate / "source-accounting" / f"{work_id}.json"
    accounting = json.loads(accounting_path.read_bytes())
    if mutation == "target-swap":
        (
            accounting["crosswalk"][0]["tei_target"],
            accounting["crosswalk"][1]["tei_target"],
        ) = (
            accounting["crosswalk"][1]["tei_target"],
            accounting["crosswalk"][0]["tei_target"],
        )
    else:
        accounting["crosswalk"][0], accounting["crosswalk"][1] = (
            accounting["crosswalk"][1],
            accounting["crosswalk"][0],
        )
    accounting_bytes = _canonical(accounting)
    accounting_path.write_bytes(accounting_bytes)
    report_path = candidate / "validation" / f"{work_id}.producer-validation.json"
    report = json.loads(report_path.read_bytes())
    report["accounting_sha256"] = hashlib.sha256(accounting_bytes).hexdigest()
    report_path.write_bytes(_canonical(report))
    with pytest.raises(
        ValueError, match="exact ordered accountability crosswalk drift"
    ):
        oracle.finalize(ROOT, candidate)


@pytest.mark.parametrize("mutation", ["one-to-true", "zero-to-false"])
@pytest.mark.requires_local_artifacts
def test_type_aware_accounting_rejects_bool_integer_substitution_after_rehash(
    tmp_path: Path, baseline: Path, mutation: str
) -> None:
    work_id = "1695-baptist-catechism"
    candidate = _unsealed_copy(tmp_path, baseline, f"typed-accounting-{mutation}")
    accounting_path = candidate / "source-accounting" / f"{work_id}.json"
    accounting = json.loads(accounting_path.read_bytes())
    if mutation == "one-to-true":
        observation = next(
            row for row in accounting["crosswalk"] if row["pointer"] == "/Data/0/Number"
        )
        assert type(observation["value"]) is int and observation["value"] == 1
        observation["value"] = True
        match = "exact ordered accountability crosswalk drift"
    else:
        assert type(accounting["omitted_leaf_count"]) is int
        accounting["omitted_leaf_count"] = False
        match = "accounting count drift"
    accounting_bytes = _canonical(accounting)
    accounting_path.write_bytes(accounting_bytes)
    report_path = candidate / "validation" / f"{work_id}.producer-validation.json"
    report = json.loads(report_path.read_bytes())
    report["accounting_sha256"] = hashlib.sha256(accounting_bytes).hexdigest()
    report_path.write_bytes(_canonical(report))
    with pytest.raises(ValueError, match=match):
        oracle.finalize(ROOT, candidate)


@pytest.mark.requires_local_artifacts
def test_oracle_rejects_stale_evidence_and_census(
    tmp_path: Path, baseline: Path
) -> None:
    candidate = _unsealed_copy(tmp_path, baseline, "stale-evidence")
    report_path = candidate / "validation/heidelberg-catechism.producer-validation.json"
    report = json.loads(report_path.read_bytes())
    report["source_raw_sha256"] = "0" * 64
    report_path.write_bytes(_canonical(report))
    with pytest.raises(ValueError, match="producer report stale"):
        oracle.finalize(ROOT, candidate)
    candidate = _unsealed_copy(tmp_path, baseline, "stale-census")
    census_path = candidate / "evidence/retained-member-census.json"
    census_path.write_bytes(census_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="candidate retained-member census drift"):
        oracle.finalize(ROOT, candidate)


@pytest.mark.parametrize(
    "identity",
    [
        "accounting",
        "producer-report",
        "review-state",
        "source-bindings",
        "producer-closure",
        "readme",
    ],
)
@pytest.mark.requires_local_artifacts
def test_finalize_rejects_every_candidate_evidence_identity_class(
    tmp_path: Path, baseline: Path, identity: str
) -> None:
    candidate = _unsealed_copy(tmp_path, baseline, f"identity-{identity}")
    if identity == "readme":
        path = candidate / "README.source.md"
        path.write_bytes(path.read_bytes() + b"\n")
        match = "source attribution README drift"
    else:
        paths = {
            "accounting": candidate / "source-accounting/1695-baptist-catechism.json",
            "producer-report": candidate
            / "validation/1695-baptist-catechism.producer-validation.json",
            "review-state": candidate / "evidence/review-state.json",
            "source-bindings": candidate / "evidence/source-bindings.json",
            "producer-closure": candidate / "evidence/producer-import-closure.json",
        }
        path = paths[identity]
        record = json.loads(path.read_bytes())
        if identity in {"accounting", "producer-report", "source-bindings"}:
            record["invented"] = True
            match = "key set drift"
        elif identity == "review-state":
            record["ticket"] = "LIB-999"
            match = "review state drift"
        else:
            record["entry"] = "build/tei/invented.py"
            match = "producer closure identity drift"
        path.write_bytes(_canonical(record))
    with pytest.raises(ValueError, match=match):
        oracle.finalize(ROOT, candidate)


@pytest.mark.parametrize("mutation", ["add", "remove", "reformat"])
@pytest.mark.requires_local_artifacts
def test_sealed_package_rejects_add_remove_and_reformat(
    tmp_path: Path, baseline: Path, mutation: str
) -> None:
    candidate = tmp_path / mutation
    shutil.copytree(baseline, candidate)
    if mutation == "add":
        (candidate / "invented.txt").write_text("invented\n", encoding="utf-8")
    elif mutation == "remove":
        (candidate / "README.source.md").unlink()
    else:
        manifest = json.loads((candidate / "manifest.json").read_bytes())
        (candidate / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
    with pytest.raises(
        ValueError, match="candidate (file set|package add/remove/reformat) drift"
    ):
        oracle.verify_sealed(candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        "resealed-add",
        "resealed-remove",
        "manifest-ticket",
        "manifest-count",
        "oracle-identity",
        "oracle-count",
    ],
)
@pytest.mark.requires_local_artifacts
def test_verify_only_rejects_self_consistently_resealed_mutations(
    tmp_path: Path, baseline: Path, mutation: str
) -> None:
    candidate = tmp_path / f"verify-{mutation}"
    shutil.copytree(baseline, candidate)
    if mutation == "resealed-add":
        (candidate / "invented.txt").write_text("invented\n", encoding="utf-8")
    elif mutation == "resealed-remove":
        (candidate / "README.source.md").unlink()
    elif mutation in {"manifest-ticket", "manifest-count"}:
        manifest_path = candidate / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        if mutation == "manifest-ticket":
            manifest["ticket"] = "LIB-999"
        else:
            manifest["member_count"] = 33
        manifest_path.write_bytes(_canonical(manifest))
    else:
        result_path = candidate / "evidence/oracle-result.json"
        result = json.loads(result_path.read_bytes())
        if mutation == "oracle-identity":
            result["status"] = "accepted"
        else:
            result["work_count"] = 8
        result_path.write_bytes(_canonical(result))
    if mutation not in {"manifest-ticket", "manifest-count"}:
        _reseal_manifest(candidate)
    with pytest.raises(ValueError, match="candidate|oracle result"):
        oracle.verify_sealed(candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        "member-path",
        "member-extra-key",
        "stale-current-byte",
        "oracle-includes-producer",
        "producer-entry",
        "oracle-entry",
    ],
)
@pytest.mark.requires_local_artifacts
def test_verify_only_anchors_self_consistent_closure_forgeries_to_current_checkout(
    tmp_path: Path, baseline: Path, mutation: str
) -> None:
    candidate = tmp_path / f"closure-forgery-{mutation}"
    shutil.copytree(baseline, candidate)
    producer_path = candidate / "evidence/producer-import-closure.json"
    oracle_path = candidate / "evidence/oracle-import-closure.json"
    producer_record = json.loads(producer_path.read_bytes())
    oracle_record = json.loads(oracle_path.read_bytes())
    if mutation == "member-path":
        producer_record["members"][0]["path"] = "build/invented.py"
        producer_record["members"].sort(key=lambda row: row["path"])
    elif mutation == "member-extra-key":
        producer_record["members"][0]["alternative_claim"] = "invented"
    elif mutation == "stale-current-byte":
        member = next(
            row
            for row in producer_record["members"]
            if row["path"] == "build/tei/lib062_json_catechisms_reconstruction.py"
        )
        member["bytes"] += 1
        member["sha256"] = "0" * 64
    elif mutation == "oracle-includes-producer":
        producer_member = next(
            copy.deepcopy(row)
            for row in producer_record["members"]
            if row["path"] == "build/tei/lib062_json_catechisms_reconstruction.py"
        )
        oracle_record["members"].append(producer_member)
        oracle_record["members"].sort(key=lambda row: row["path"])
    elif mutation == "producer-entry":
        producer_record["entry"] = "build/tei/invented.py"
    else:
        oracle_record["entry"] = "build/tei/invented.py"
    producer_path.write_bytes(_canonical(producer_record))
    oracle_path.write_bytes(_canonical(oracle_record))
    _self_consistently_reseal_closures(candidate)
    with pytest.raises(ValueError, match="closure"):
        oracle.verify_sealed(candidate)


@pytest.mark.requires_local_artifacts
def test_verify_only_rejects_unrelated_caller_selected_repository(
    tmp_path: Path, baseline: Path
) -> None:
    unrelated = tmp_path / "unrelated-checkout"
    unrelated.mkdir()
    with pytest.raises(ValueError, match="not the executing oracle checkout"):
        oracle.verify_sealed(baseline, unrelated)


@pytest.mark.requires_local_artifacts
def test_oracle_rejects_source_hash_drift_through_logical_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = resolve_repo_path(
        ROOT, "raw/Creeds.json/creeds/heidelberg_catechism.json"
    ).resolve()
    _, _, census_indexes = oracle._retained_member_census(ROOT)
    original = Path.read_bytes

    def drift(path: Path) -> bytes:
        content = original(path)
        return content + b"\n" if path.resolve() == authority else content

    monkeypatch.setattr(Path, "read_bytes", drift)
    with pytest.raises(ValueError, match="source hash drift"):
        oracle._verify_packet_and_source(ROOT, "heidelberg-catechism", census_indexes)


@pytest.mark.parametrize(
    "mutation",
    [
        "authority-path",
        "authority-disposition",
        "authority-extra",
        "terms-path",
        "terms-disposition",
        "terms-extra",
        "witness-omission",
        "witness-addition",
        "witness-swap",
        "witness-disposition",
        "witness-extra",
        "packet-omission",
        "packet-extra",
        "primary-omission",
        "primary-extra",
        "primary-drift",
        "accountability-omission",
        "accountability-extra",
        "accountability-drift",
        "accountability-true-one",
        "accountability-zero-false",
        "structural-omission",
        "structural-extra",
        "structural-drift",
        "profile-extra",
        "profile-zero-false",
        "census-binding-extra",
    ],
)
@pytest.mark.requires_local_artifacts
def test_packet_bindings_must_equal_exact_census_disposition_indexes(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    work_id = (
        "1695-baptist-catechism"
        if mutation == "witness-addition"
        else "heidelberg-catechism"
    )
    packet_path = (ROOT / "sources" / work_id / "LIB-062.packet.json").resolve()
    packet = json.loads(packet_path.read_bytes())
    heidelberg = json.loads(
        (ROOT / "sources/heidelberg-catechism/LIB-062.packet.json").read_bytes()
    )
    westminster = json.loads(
        (ROOT / "sources/westminster-larger-catechism/LIB-062.packet.json").read_bytes()
    )
    if mutation == "authority-path":
        packet["authority"]["path"] = "raw/Creeds.json/creeds/keachs_catechism.json"
    elif mutation == "authority-disposition":
        packet["authority"]["disposition"] = "included-authority"
    elif mutation == "authority-extra":
        packet["authority"]["alternative_claim"] = "invented"
    elif mutation == "terms-path":
        packet["terms_evidence"]["path"] = packet["authority"]["path"]
    elif mutation == "terms-disposition":
        packet["terms_evidence"]["disposition"] = "included without attribution"
    elif mutation == "terms-extra":
        packet["terms_evidence"]["alternative_claim"] = "invented"
    elif mutation == "witness-omission":
        packet["adjacent_witnesses"] = []
    elif mutation == "witness-addition":
        packet["adjacent_witnesses"] = heidelberg["adjacent_witnesses"]
    elif mutation == "witness-swap":
        packet["adjacent_witnesses"] = westminster["adjacent_witnesses"]
    elif mutation == "witness-disposition":
        packet["adjacent_witnesses"][0]["disposition"] = "included-authority"
    elif mutation == "witness-extra":
        packet["adjacent_witnesses"][0]["alternative_claim"] = "invented"
    elif mutation == "packet-omission":
        packet.pop("primary_metadata")
    elif mutation == "packet-extra":
        packet["alternative_claim"] = "invented"
    elif mutation == "primary-omission":
        packet["primary_metadata"].pop("Year")
    elif mutation == "primary-extra":
        packet["primary_metadata"]["Edition"] = "invented"
    elif mutation == "primary-drift":
        packet["primary_metadata"]["Title"] = "Invented title"
    elif mutation == "accountability-omission":
        packet["accountability_contract"].pop("leaf_model")
    elif mutation == "accountability-extra":
        packet["accountability_contract"]["alternative_claim"] = True
    elif mutation == "accountability-drift":
        packet["accountability_contract"]["omitted_leaf_count"] = 1
    elif mutation == "accountability-true-one":
        packet["accountability_contract"]["require_every_recursive_key"] = 1
    elif mutation == "accountability-zero-false":
        packet["accountability_contract"]["omitted_leaf_count"] = False
    elif mutation == "structural-omission":
        packet["structural_policy"].pop("grouping")
    elif mutation == "structural-extra":
        packet["structural_policy"]["alternative_claim"] = "invented"
    elif mutation == "structural-drift":
        packet["structural_policy"]["ordering"] = "modernized order"
    elif mutation == "profile-extra":
        packet["profile"]["alternative_claim"] = 1
    elif mutation == "profile-zero-false":
        assert packet["profile"]["proofless_record_count"] == 0
        packet["profile"]["proofless_record_count"] = False
    else:
        packet["retained_member_census"]["alternative_claim"] = "invented"
    mutated = _canonical(packet)
    original = Path.read_bytes
    _, _, producer_indexes = producer._retained_member_census(ROOT)
    _, _, oracle_indexes = oracle._retained_member_census(ROOT)

    def packet_bytes(path: Path) -> bytes:
        return mutated if path.resolve() == packet_path else original(path)

    monkeypatch.setattr(Path, "read_bytes", packet_bytes)
    with pytest.raises(
        ValueError, match="drift|key set|authority|census|terms evidence|witness"
    ):
        producer._source_and_packet(ROOT, work_id, producer_indexes)
    with pytest.raises(
        ValueError, match="drift|key set|authority|census|terms evidence|witness"
    ):
        oracle._verify_packet_and_source(ROOT, work_id, oracle_indexes)


@pytest.mark.parametrize(
    "mutation",
    [
        "path",
        "disposition",
        "related-work",
        "duplicate-authority",
        "top-omission",
        "top-extra",
        "ticket",
        "protected-omission",
        "protected-order",
        "protected-path",
        "protected-count",
        "protected-hash",
        "protected-extra",
        "terms-path",
        "terms-omission",
        "terms-extra",
        "member-extra",
        "member-omission",
    ],
)
@pytest.mark.requires_local_artifacts
def test_census_member_identity_mutations_cannot_pass(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    census_path = (
        ROOT / "sources/1695-baptist-catechism/LIB-062.retained-member-census.json"
    ).resolve()
    census = json.loads(census_path.read_bytes())
    if mutation == "path":
        census["members"][1]["path"] = "raw/Creeds.json/creeds/invented.json"
        census["members"] = sorted(census["members"], key=lambda row: row["path"])
    elif mutation == "disposition":
        census["members"][1]["disposition"] = "excluded-outside-LIB-062-assigned-scope"
        census["members"][1].pop("work_id")
    elif mutation == "related-work":
        witness = next(
            row
            for row in census["members"]
            if row.get("related_work_id") == "heidelberg-catechism"
        )
        witness["related_work_id"] = "keachs-catechism"
    elif mutation == "duplicate-authority":
        authority = next(
            row
            for row in census["members"]
            if row.get("work_id") == "1695-baptist-catechism"
        )
        duplicate = copy.deepcopy(authority)
        duplicate["path"] = "raw/Creeds.json/creeds/abstract_of_principles.json"
        census["members"] = [
            duplicate if row["path"] == duplicate["path"] else row
            for row in census["members"]
        ]
    elif mutation == "top-omission":
        census.pop("ticket")
    elif mutation == "top-extra":
        census["alternative_claim"] = "invented"
    elif mutation == "ticket":
        census["ticket"] = "LIB-999"
    elif mutation == "protected-omission":
        census["protected_directories"].pop()
    elif mutation == "protected-order":
        census["protected_directories"].reverse()
    elif mutation == "protected-path":
        census["protected_directories"][0]["path"] = "raw/invented"
    elif mutation == "protected-count":
        census["protected_directories"][0]["file_count"] = 42
    elif mutation == "protected-hash":
        census["protected_directories"][0]["manifest_sha256"] = "0" * 64
    elif mutation == "protected-extra":
        census["protected_directories"][0]["alternative_claim"] = "invented"
    elif mutation == "terms-path":
        census["terms_evidence"]["path"] = "raw/invented.md"
    elif mutation == "terms-omission":
        census["terms_evidence"].pop("bytes")
    elif mutation == "terms-extra":
        census["terms_evidence"]["alternative_claim"] = "invented"
    elif mutation == "member-extra":
        census["members"][0]["alternative_claim"] = "invented"
    else:
        census["members"].pop()
    mutated = _canonical(census)
    original = Path.read_bytes

    def census_bytes(path: Path) -> bytes:
        return mutated if path.resolve() == census_path else original(path)

    monkeypatch.setattr(Path, "read_bytes", census_bytes)
    with pytest.raises(ValueError, match="census|retained-member"):
        producer._retained_member_census(ROOT)
    with pytest.raises(ValueError, match="census|retained-member"):
        oracle._retained_member_census(ROOT)


@pytest.mark.requires_local_artifacts
def test_recursive_closures_are_current_and_independent(baseline: Path) -> None:
    producer_records = producer.repository_import_closure(
        ROOT, ROOT / "build/tei/lib062_json_catechisms_reconstruction.py"
    )
    oracle_records = oracle.repository_import_closure(
        ROOT, ROOT / "build/tei/lib062_json_catechisms_oracle.py"
    )
    assert (
        json.loads((baseline / "evidence/producer-import-closure.json").read_bytes())[
            "members"
        ]
        == producer_records
    )
    assert (
        json.loads((baseline / "evidence/oracle-import-closure.json").read_bytes())[
            "members"
        ]
        == oracle_records
    )
    assert "build/tei/lib062_json_catechisms_reconstruction.py" not in {
        record["path"] for record in oracle_records
    }


@pytest.mark.requires_local_artifacts
def test_ticket_map_rows_and_hashes_are_exact_read_only() -> None:
    work_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/02-work-ticket-map.md"
    ).read_text(encoding="utf-8")
    source_map = (
        ROOT
        / "plans/2026-08-26-whole-library-faithful-tei-completion/05-source-ticket-map.md"
    ).read_text(encoding="utf-8")
    work_catalog = (ROOT / "docs/WORK_CATALOG.md").read_text(encoding="utf-8")
    catechisms = work_catalog.split("## Catechisms\n", 1)[1].split("\n## ", 1)[0]
    for work_id, _ in producer.WORKS:
        packet = json.loads(
            (ROOT / "sources" / work_id / "LIB-062.packet.json").read_bytes()
        )
        work_rows = [
            line for line in work_map.splitlines() if f"| `{work_id}` |" in line
        ]
        source_rows = [
            line for line in source_map.splitlines() if f"| `{work_id}` |" in line
        ]
        assert len(work_rows) == len(source_rows) == 1
        assert "LIB-062" in work_rows[0] and "LIB-062" in source_rows[0]
        assert (
            f"sha256:{packet['authority']['normalized_utf8_sha256']}" in source_rows[0]
        )
        catalog_rows = [
            entry
            for entry in catechisms.split("\n### ")
            if entry.splitlines()[0] == packet["primary_metadata"]["Title"]
        ]
        assert len(catalog_rows) == 1
        assert f"`work_id={work_id}`" in catalog_rows[0]
