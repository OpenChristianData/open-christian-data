"""Source-binding and fidelity-contract tests for LIB-073 / 37c-250."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
import pytest

from build.tei.maclaren_expositions_oracle import _oracle
from ocd_kernel.reconstruction import SourceManifest, validate


ROOT = Path(__file__).resolve().parents[3]
PROFILE_PATH = (
    ROOT
    / "sources/sermons/maclaren-expositions/"
    "maclaren-expositions.reconstruction-profile.json"
)
INVENTORY_PATH = ROOT / "raw/gutenberg/sermons/PG_SERMON_INVENTORY.md"
MANIFEST_PATH = ROOT / "sources/sermons/maclaren-expositions/maclaren-expositions.source-manifest.json"
PRODUCER_PATH = ROOT / "build/tei/maclaren_expositions_reconstruction.py"
ORACLE_PATH = ROOT / "build/tei/maclaren_expositions_oracle.py"
ACCOUNTABILITY_SCHEMA_PATH = (
    ROOT
    / "sources/sermons/maclaren-expositions/"
    "maclaren-expositions.source-accountability.schema.json"
)
PACKAGE_MEMBER_NAMES = {
    "content.tei.xml",
    "source-accountability.json",
    "provenance.json",
    "unresolved.jsonl",
    "README.source.md",
}
EXPECTED_MEMBERS = (
    ("7069", "raw/gutenberg/sermons/maclaren/pg7069.txt"),
    ("8068", "raw/gutenberg/sermons/maclaren/pg8068.txt"),
    ("7883", "raw/gutenberg/sermons/maclaren/pg7883.txt"),
    ("7925", "raw/gutenberg/sermons/maclaren/pg7925.txt"),
    ("8069", "raw/gutenberg/sermons/maclaren/pg8069.txt"),
    ("15836", "raw/gutenberg/sermons/maclaren/pg15836.txt"),
    ("7351", "raw/gutenberg/sermons/maclaren/pg7351.txt"),
    ("8071", "raw/gutenberg/sermons/maclaren/pg8071.txt"),
    ("8200", "raw/gutenberg/sermons/maclaren/pg8200.txt"),
    ("8070", "raw/gutenberg/sermons/maclaren/pg8070.txt"),
    ("8381", "raw/gutenberg/sermons/maclaren/pg8381.txt"),
    ("8397", "raw/gutenberg/sermons/maclaren/pg8397.txt"),
    ("13601", "raw/gutenberg/sermons/maclaren/pg13601.txt"),
    ("21190", "raw/gutenberg/sermons/maclaren/pg21190.txt"),
    ("24674", "raw/gutenberg/sermons/maclaren/pg24674.txt"),
)


def _inventory_members() -> tuple[tuple[str, str], ...]:
    inventory = INVENTORY_PATH.read_text(encoding="utf-8")
    section = inventory.split("## Alexander Maclaren", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(
        r"\|\s*(\d+)\s*\|[^|]+\|\s*"
        r"(raw/gutenberg/sermons/maclaren/pg\d+\.txt)\s*\|",
        section,
    )
    return tuple(rows)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


class _InMemoryCandidateView:
    """Contract-shaped view for tests; it never creates a candidate directory."""

    def __init__(self, source: SourceManifest, members: Mapping[str, bytes]) -> None:
        if set(members) != PACKAGE_MEMBER_NAMES:
            raise ValueError("test candidate view requires exactly the five converter outputs")
        self.contents = dict(members)
        self._manifest = {
            "contract": "ocd-candidate-package-v1",
            "status": "nonaccepted",
            "source_id": source.record["source_id"],
            "source_manifest": {
                "path": source.path.relative_to(source.repository_root).as_posix(),
                "sha256": source.sha256,
            },
            "converter": dict(source.record["converter"]),
            "package_schema": dict(source.record["package_schema"]),
            "members": [
                {
                    "name": name,
                    "bytes": len(self.contents[name]),
                    "sha256": hashlib.sha256(self.contents[name]).hexdigest(),
                }
                for name in sorted(self.contents)
            ],
        }
        self.sha256 = hashlib.sha256(_canonical(self._manifest)).hexdigest()
        package_schema = json.loads(
            source.authority_path("candidate-package-schema").read_text(encoding="utf-8")
        )
        Draft202012Validator(package_schema).validate(self._manifest)

    @property
    def manifest(self) -> dict[str, object]:
        return self._manifest

    def member_bytes(self, name: str) -> bytes:
        if name not in self.contents:
            raise ValueError(f"unknown in-memory candidate member {name!r}")
        self.verify_integrity()
        return self.contents[name]

    def verify_integrity(self) -> None:
        if set(self.contents) != PACKAGE_MEMBER_NAMES:
            raise ValueError("in-memory candidate member set drifted")
        if hashlib.sha256(_canonical(self._manifest)).hexdigest() != self.sha256:
            raise ValueError("in-memory candidate manifest digest drifted")
        listed = {row["name"]: row for row in self._manifest["members"]}
        if set(listed) != PACKAGE_MEMBER_NAMES:
            raise ValueError("in-memory candidate manifest member set drifted")
        for name, content in self.contents.items():
            if (
                listed[name]["bytes"] != len(content)
                or listed[name]["sha256"] != hashlib.sha256(content).hexdigest()
            ):
                raise ValueError(f"in-memory candidate member {name} drifted")


@pytest.fixture(scope="module")
def verified_route():
    """Exercise the existing validator in memory; do not package or write a candidate."""

    from build.tei.maclaren_expositions_reconstruction import _convert

    source = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    output_members = _convert(source)
    candidate_view = _InMemoryCandidateView(source, output_members)
    report = validate(source, candidate_view, _oracle)
    return source, candidate_view, report


def test_profile_binds_the_complete_ordered_source_and_keeps_count_uncertainty() -> None:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))

    assert _inventory_members() == EXPECTED_MEMBERS
    assert profile["contract"] == "ocd-maclaren-expositions-profile-v1"
    assert profile["work_id"] == "maclaren-expositions"
    assert profile["ticket_id"] == "LIB-073"

    members = profile["members"]
    assert len(members) == len(EXPECTED_MEMBERS)
    assert tuple((item["pg_id"], item["path"]) for item in members) == EXPECTED_MEMBERS

    aggregate_bytes = 0
    aggregate_lines = 0
    aggregate_empty_lines = 0
    aggregate_whitespace_lines = 0
    aggregate_uppercase_lines = 0
    aggregate_note_lines = 0
    aggregate_underscore_spans = 0
    for position, (member, (pg_id, path)) in enumerate(
        zip(members, EXPECTED_MEMBERS, strict=True), start=1
    ):
        source_bytes = (ROOT / path).read_bytes()
        source_text = source_bytes.decode("utf-8-sig", errors="strict")
        source_lines = source_text.splitlines()
        source_start = [
            number
            for number, line in enumerate(source_lines, 1)
            if line.startswith("*** START OF THE PROJECT GUTENBERG EBOOK ")
        ]
        source_end = [
            number
            for number, line in enumerate(source_lines, 1)
            if line.startswith("*** END OF THE PROJECT GUTENBERG EBOOK ")
        ]
        source_contents = [
            number
            for number, line in enumerate(source_lines, 1)
            if line.strip() == "CONTENTS"
        ]
        license_lines = [
            number
            for number, line in enumerate(source_lines, 1)
            if "START: FULL LICENSE" in line
        ]
        uppercase_lines = [
            number
            for number, line in enumerate(source_lines, 1)
            if line.strip()
            and any(character.isalpha() for character in line.strip())
            and line.strip() == line.strip().upper()
        ]
        note_lines = [
            number
            for number, line in enumerate(source_lines, 1)
            if re.search(r"\[\d+\]", line)
        ]
        underscore_spans = sum(
            len(re.findall(r"_[^_\r\n]+_", line)) for line in source_lines
        )
        title_line = next(line for line in source_lines[:80] if line.startswith("Title:"))
        author_line = next(line for line in source_lines[:80] if line.startswith("Author:"))
        language_line = next(line for line in source_lines[:80] if line.startswith("Language:"))
        assert member["inventory_order"] == position
        assert member["pg_id"] == pg_id
        assert member["path"] == path
        assert member["bytes"] == len(source_bytes)
        assert member["sha256"] == hashlib.sha256(source_bytes).hexdigest()
        assert member["physical_line_count"] == len(source_lines)
        assert member["leading_utf8_bom"] is True
        assert member["line_ending"] == "CRLF"
        assert member["lone_lf_count"] == 0
        assert member["lone_cr_count"] == 0
        assert source_bytes.count(b"\r\n") == len(source_lines)
        assert member["start_marker_lines"] == source_start
        assert member["end_marker_lines"] == source_end
        assert member["contents_lines"] == source_contents
        assert member["full_license_line"] == license_lines[0]
        assert member["start_marker_lines"][0] < member["end_marker_lines"][0] < license_lines[0]
        assert member["title_observation"] == title_line.partition(":")[2].strip()
        assert member["author_observation"] == author_line.partition(":")[2].strip() == "Alexander Maclaren"
        assert member["language_observation"] == language_line.partition(":")[2].strip() == "English"
        assert member["empty_line_count"] == sum(line == "" for line in source_lines)
        assert member["whitespace_only_line_count"] == sum(
            line != "" and line.isspace() for line in source_lines
        )
        assert member["uppercase_line_count"] == len(uppercase_lines)
        assert member["uppercase_line_count_within_pg_wrapper"] == sum(
            member["start_marker_lines"][0] <= number <= member["end_marker_lines"][0]
            for number in uppercase_lines
        )
        assert member["bracketed_digit_marker_lines"] == note_lines
        assert member["underscore_delimited_inline_span_count"] == underscore_spans
        aggregate_bytes += len(source_bytes)
        aggregate_lines += len(source_lines)
        aggregate_empty_lines += member["empty_line_count"]
        aggregate_whitespace_lines += member["whitespace_only_line_count"]
        aggregate_uppercase_lines += member["uppercase_line_count"]
        aggregate_note_lines += len(note_lines)
        aggregate_underscore_spans += underscore_spans

    assert aggregate_bytes == profile["aggregate"]["bytes"] == 20_141_441
    assert aggregate_lines == profile["aggregate"]["physical_line_count"] == 339_526
    assert aggregate_empty_lines == profile["aggregate"]["exact_empty_line_count"] == 36_845
    assert aggregate_whitespace_lines == profile["aggregate"]["whitespace_only_line_count"] == 120
    assert aggregate_uppercase_lines == profile["aggregate"]["uppercase_nonblank_line_count"] == 1_854
    assert aggregate_note_lines == profile["aggregate"]["bracketed_digit_marker_lines"] == 7
    assert aggregate_underscore_spans == profile["aggregate"]["underscore_delimited_inline_span_count"] == 4_642
    assert profile["scope"]["source_inventory"]["sha256"] == hashlib.sha256(
        INVENTORY_PATH.read_bytes()
    ).hexdigest()
    assert profile["aggregate"]["all_lines_disposition"].startswith(
        "represented exactly once"
    )
    excluded = profile["excluded_inventory_items"]
    assert [item["pg_id"] for item in excluded] == ["42445", "42488", "44027"]
    assert all(item["disposition"] == "excluded-different-series" for item in excluded)
    assert all("different authors" in item["reason"] for item in excluded)

    discrepancy = profile["count_discrepancy"]
    assert discrepancy["legacy_config_claim"] == 1_263
    assert discrepancy["legacy_projection_records"] == 1_255
    assert discrepancy["difference"] == 8
    assert discrepancy["source_verified_exposition_count"] is None
    assert discrepancy["resolution"] == "unresolved-from-retained-source"
    assert discrepancy["route_uses_either_count_as_a_selection_limit"] is False
    assert "all source text remains in scope" in discrepancy["disposition"]

    config = json.loads(
        (ROOT / "sources/sermons/maclaren-expositions/config.json").read_text(
            encoding="utf-8"
        )
    )
    projection = json.loads(
        (ROOT / "data/sermons/maclaren-expositions.json").read_text(encoding="utf-8")
    )
    assert "1263 expositions" in config["notes"]
    assert len(projection["data"]) == 1255
    assert discrepancy["diagnostic_inputs_are_source_authority"] is False
    assert profile["source_feature_observations"]["notes_and_inline_markers"].find(
        "preserves every literal underscore"
    ) >= 0
    assert "U+2014 EM DASH" in profile["source_feature_observations"][
        "source_errors_and_special_characters"
    ]
    assert (ROOT / "raw/gutenberg/sermons/maclaren/pg7069.txt").read_bytes().decode(
        "utf-8-sig"
    ).splitlines()[88].strip() == "ABRAM AND THE LIFE OF FAITH"


def test_source_manifest_and_route_authorities_are_exact_and_nonshared() -> None:
    source = SourceManifest.load(MANIFEST_PATH, repository_root=ROOT)
    source.verify()
    policy = json.loads(source.authority_path("validation-policy").read_bytes())
    profile = json.loads(source.authority_path("reconstruction-profile").read_bytes())
    primary = [
        item
        for item in source.record["authorities"]
        if item["role"] == "primary-source"
    ]
    assert len(primary) == 15
    assert [item["path"] for item in primary] == [item["path"] for item in profile["members"]]
    assert source.record["converter"]["implementation_path"] == PRODUCER_PATH.relative_to(ROOT).as_posix()
    assert source.record["validator"]["implementation_path"] == ORACLE_PATH.relative_to(ROOT).as_posix()
    assert source.record["validator"]["import_closure_sha256"] == _oracle_import_closure(source)
    assert source.record["validator"]["id"] == "ocd-lib073-maclaren-expositions-independent-source-oracle"
    assert "build.tei.maclaren_expositions_reconstruction" in policy[
        "forbidden_import_prefixes"
    ]
    assert "build.tei.maclaren_expositions_oracle" in policy[
        "producer_forbidden_import_prefixes"
    ]
    assert "build.tei.maclaren_expositions_reconstruction" not in ORACLE_PATH.read_text(
        encoding="utf-8"
    )
    assert "build.tei.maclaren_expositions_oracle" not in PRODUCER_PATH.read_text(
        encoding="utf-8"
    )
    Draft202012Validator(
        json.loads(ACCOUNTABILITY_SCHEMA_PATH.read_text(encoding="utf-8"))
    )


def _oracle_import_closure(source: SourceManifest) -> str:
    from build.tei.maclaren_expositions_oracle import _closure

    return _closure(source.repository_root)


def test_manifest_bound_in_memory_validation_and_accounting(verified_route) -> None:
    source, candidate, report = verified_route
    assert report.status == "pass"
    assert report.findings == ()
    assert candidate.manifest["status"] == "nonaccepted"
    assert candidate.manifest["source_id"] == source.record["source_id"]
    assert candidate.sha256 == report.candidate_sha256

    attestation = dict(report.attestation)
    assert attestation["status"] == "pass"
    primary = sorted(
        (
            {
                key: authority[key]
                for key in ("name", "path", "bytes", "sha256")
            }
            for authority in source.record["authorities"]
            if authority["role"] == "primary-source"
        ),
        key=lambda item: (item["path"], item["name"]),
    )
    assert attestation["source_sha256"] == hashlib.sha256(
        _canonical({"contract": "ocd-source-member-set-v1", "members": primary})
    ).hexdigest()
    assert attestation["profile_sha256"] == source.record["authorities"][-7]["sha256"]
    assert attestation["policy_sha256"] == next(
        item["sha256"] for item in source.record["authorities"] if item["name"] == "validation-policy"
    )
    account_bytes = candidate.member_bytes("source-accountability.json")
    account = json.loads(account_bytes)
    schema = json.loads(ACCOUNTABILITY_SCHEMA_PATH.read_bytes())
    Draft202012Validator(schema).validate(account)
    assert account["source_member_count"] == 15
    assert account["physical_line_count"] == account["represented_line_count"] == 339_526
    assert account["excluded_line_count"] == account["omitted_line_count"] == account["duplicate_line_count"] == 0
    assert [item["path"] for item in account["source_members"]] == [
        item["path"] for item in json.loads(PROFILE_PATH.read_bytes())["members"]
    ]
    for member in account["source_members"]:
        assert len(member["regions"]) == 3
        assert sum(region["line_count"] for region in member["regions"]) == member[
            "physical_line_count"
        ] == member["represented_line_count"]
        assert all(region["disposition"] == "represented-in-tei" for region in member["regions"])
    assert account["count_discrepancy"]["difference"] == 8
    assert account["count_discrepancy"]["resolution"] == "unresolved-from-retained-source"

    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines()
    ]
    assert "maclaren-expositions-count-discrepancy-exact-eight" in {
        item["id"] for item in unresolved
    }
    provenance = json.loads(candidate.member_bytes("provenance.json"))
    assert provenance["rights_status"] == "not-reviewed"
    assert provenance["acceptance_status"] == "not-performed"
    assert provenance["publication_status"] == "not-authorized"
    assert provenance["canonical_data_or_ir_written"] is False


@pytest.mark.parametrize(
    ("member_name", "mutation"),
    [
        (
            "content.tei.xml",
            lambda value: value.replace(
                b"ABRAM AND THE LIFE OF FAITH",
                b"XBRAM AND THE LIFE OF FAITH",
                1,
            ),
        ),
        (
            "content.tei.xml",
            lambda value: value.replace(
                b'type="source-member" n="7069"',
                b'type="source-member" n="8068"',
                1,
            ),
        ),
        (
            "content.tei.xml",
            lambda value: value.replace(
                b"*** START OF THE PROJECT GUTENBERG EBOOK",
                b"*** START OF THE PROJECT GUTENBERG EBXOK",
                1,
            ),
        ),
        (
            "content.tei.xml",
            lambda value: value.replace(
                b"START: FULL LICENSE",
                b"START: FULL LICEN5E",
                1,
            ),
        ),
        (
            "source-accountability.json",
            lambda value: _mutate_accountability_digest(value),
        ),
    ],
)
def test_independent_oracle_rejects_resealed_source_and_accounting_mutations(
    verified_route, member_name: str, mutation
) -> None:
    source, candidate, _report = verified_route
    mutated_members = dict(candidate.contents)
    original = mutated_members[member_name]
    changed = mutation(original)
    assert changed != original
    mutated_members[member_name] = changed
    resealed_view = _InMemoryCandidateView(source, mutated_members)
    with pytest.raises(ValueError):
        validate(source, resealed_view, _oracle)


def _mutate_accountability_digest(value: bytes) -> bytes:
    account = json.loads(value)
    account["source_members"][0]["line_accounting_sha256"] = "0" * 64
    return _canonical(account)


def test_fresh_process_reconstruction_is_deterministic_without_packaging(
    verified_route, tmp_path: Path
) -> None:
    source, candidate, _report = verified_route
    source_path = MANIFEST_PATH.relative_to(ROOT).as_posix()
    output_hashes = {
        name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in candidate.contents.items()
    }
    other_cwd = tmp_path / "clean-cwd"
    other_cwd.mkdir()
    code = (
        "import hashlib,json; from pathlib import Path; "
        "from ocd_kernel.reconstruction import SourceManifest; "
        "from build.tei.maclaren_expositions_reconstruction import _convert; "
        f"root=Path({str(ROOT)!r}); "
        f"source=SourceManifest.load(root/{source_path!r},repository_root=root); "
        "members=_convert(source); "
        "print(json.dumps({name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} "
        "for name,data in members.items()},sort_keys=True))"
    )

    def run(seed: str, cwd: Path) -> dict[str, object]:
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=240,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    first = run("1", ROOT)
    second = run("random", other_cwd)
    assert first == second == output_hashes
    assert source.record["work_id"] == "maclaren-expositions"
