"""Layered, provisional TEI checks without acceptance or publication side effects."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from lxml import etree
from lxml.isoschematron import Schematron

from ocd_kernel.tei.conformance import (
    ConformanceError, FixturePackage, compare_reference, parse_xml,
)
from ocd_kernel.tei.profile import Profile, ProfileError, load_profile, render_schematron
from ocd_kernel.tei.extensions import select_extensions
from ocd_kernel.tei.validate import compiled_schema


@dataclass(frozen=True)
class ValidationIssue:
    stage: str
    rule_id: str
    location: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    document_sha256: str
    profile_sha256: str
    p5_valid: bool
    semantic_valid: bool
    mode: str
    issues: tuple[ValidationIssue, ...]
    reference_accounting: dict[str, Any]
    schema_evidence: dict[str, Any]
    extension_ids: tuple[str, ...] = ()
    projector_readiness: tuple[dict[str, Any], ...] = ()
    status: str = "provisional"
    adoption: str = "not-established"
    source_fidelity: str = "not-assessed"
    publication: str = "not-authorized-by-conformance"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _schema_evidence() -> dict[str, Any]:
    vendor = Path(__file__).parent / "vendor"
    return {
        "version": (vendor / "VERSION.txt").read_text(encoding="utf-8").strip(),
        "xsd_sha256": {
            path.name: sha256(path.read_bytes()).hexdigest()
            for path in sorted((vendor / "xsd").glob("*.xsd"))
        },
    }


def validate_tei(
    document: bytes | Path,
    *,
    profile: Profile | None = None,
    mode: str = "excerpt",
    package: FixturePackage | None = None,
    fixture_id: str | None = None,
    extension_ids: tuple[str, ...] = (),
) -> ValidationResult:
    """Run P5 and contextual vocabulary checks, optionally against an excerpt.

    Excerpt mode never asserts completeness of a master header or source work.
    Master mode additionally requires the profile's stable OCD identifiers and
    a dated revision entry. Header-probe mode applies those same representation
    checks to a source-only derivative without calling it a master. No mode
    establishes editorial acceptance.
    """
    if mode not in ("excerpt", "master", "header-probe"):
        raise ValueError(f"unsupported validation mode: {mode}")
    if (package is None) != (fixture_id is None):
        raise ValueError("fixture package and fixture identity must be supplied together")
    active_profile = load_profile() if profile is None else profile
    if profile is not None and profile != load_profile(profile.root):
        raise ProfileError("provided profile differs from its current hash-bound package")
    fixture_record = package.fixture(fixture_id) if package is not None and fixture_id is not None else None
    if (mode == "master" and fixture_record is not None
            and fixture_record["origin"].get("kind") == "retained-source-only"):
        raise ConformanceError("a retained-source-only derivative requires header-probe mode, not master mode")
    selected = select_extensions(active_profile.extensions, extension_ids)
    readiness: list[dict[str, Any]] = []
    if selected:
        if package is None or fixture_id is None:
            raise ConformanceError("extensions require a bound fixture package and fixture identity")
        record = package.fixture(fixture_id)
        package.reference(fixture_id)
        identity = record["origin"]["identity"]
        source_identity = next((identity.get(key) for key in ("source_id", "legacy_slug", "scope")
                                if isinstance(identity.get(key), str) and identity[key]), None)
        work_identity = identity.get("work_id") or source_identity
        edition_identity = identity.get("edition_id") or record["origin"].get("tei_path")
        for extension in selected:
            matches = [example for example in extension["real_examples"]
                       if example["fixture"] == {"id": fixture_id, "path": record["path"],
                                                  "sha256": record["sha256"]}]
            if not matches:
                raise ConformanceError(f"extension {extension['extension_id']} is not bound to fixture {fixture_id}")
            for example in matches:
                source = example["retained_source"]
                if (not source_identity or example["work"] != work_identity
                        or example["edition"] != edition_identity or source["identity"] != source_identity):
                    raise ConformanceError(f"extension {extension['extension_id']} has a different work, edition, or source identity")
                if not any(member["path"] == source["path"] and member["sha256"] == source["sha256"]
                           and member["locator"] == source["location"]
                           for member in record["origin"]["source_members"]):
                    raise ConformanceError(f"extension {extension['extension_id']} has a different retained-source binding")
            for projector, disposition in extension["projection"].items():
                readiness.append({
                    "extension_id": extension["extension_id"], "projector": projector,
                    "declared_disposition": disposition["disposition"],
                    "observed_enforcement": disposition.get("observed_enforcement", "not-assessed"),
                    "details": disposition,
                    "admission": "provisional-fixture-test-only",
                })
    data = document.read_bytes() if isinstance(document, Path) else document
    if not isinstance(data, bytes):
        raise TypeError("document must be bytes or pathlib.Path")
    issues: list[ValidationIssue] = []
    accounting: dict[str, Any] = {"status": "not-assessed", "source_oracle": "not-rerun"}
    schema_evidence = _schema_evidence()
    try:
        tree = parse_xml(data)
    except (etree.XMLSyntaxError, ConformanceError) as exc:
        issues.append(ValidationIssue("xml", "well-formed-safe-xml", "/", str(exc)))
        return ValidationResult(sha256(data).hexdigest(), active_profile.manifest_sha256,
                                False, False, mode, tuple(issues), accounting, schema_evidence,
                                extension_ids, tuple(readiness))

    schema = compiled_schema()
    p5_valid = schema.validate(tree)
    if not p5_valid:
        for error in schema.error_log:
            issues.append(ValidationIssue("p5", "tei-p5-xsd", error.path or "/", error.message))

    rules = Schematron(
        etree.fromstring(render_schematron(active_profile, extension_ids)),
        error_finder=Schematron.ASSERTS_AND_REPORTS, store_report=True,
    )
    rules.validate(tree)
    report = rules.validation_report
    if report is not None:
        svrl = {"svrl": "http://purl.oclc.org/dsdl/svrl"}
        for failure in report.xpath("//svrl:failed-assert | //svrl:successful-report", namespaces=svrl):
            issues.append(ValidationIssue(
                "semantic", failure.get("id", "unnamed-profile-rule"),
                failure.get("location", "/"),
                " ".join(failure.xpath("string(svrl:text)", namespaces=svrl).split()),
            ))

    if mode in ("master", "header-probe") or fixture_record is not None:
        ns = {"tei": "http://www.tei-c.org/ns/1.0"}
        # Identity tokens come from the profile, never a second Python registry.
        identity_values = [value for value in active_profile.controlled_values["idno/@type"]
                           if value.startswith("ocd-") and value.endswith("-id")]
        for token in identity_values:
            identity_key = token.removeprefix("ocd-").replace("-", "_")
            expected_identity = (fixture_record["origin"]["identity"].get(identity_key)
                                 if fixture_record is not None else None)
            nodes = tree.xpath("/tei:TEI/tei:teiHeader/tei:fileDesc//tei:idno[@type=$token]",
                               namespaces=ns, token=token)
            if ((mode in ("master", "header-probe") or expected_identity is not None)
                    and (len(nodes) != 1 or not "".join(nodes[0].itertext()).strip())):
                issues.append(ValidationIssue("semantic", "master-identity-cardinality",
                                              "/TEI/teiHeader/fileDesc", f"expected one nonempty {token}"))
            if expected_identity is not None and (len(nodes) != 1 or "".join(nodes[0].itertext()).strip() != expected_identity):
                issues.append(ValidationIssue("semantic", "fixture-identity-mismatch",
                                              "/TEI/teiHeader/fileDesc", f"{token} differs from its bound authority identity"))
        revisions = tree.xpath("/tei:TEI/tei:teiHeader/tei:revisionDesc/tei:change[@when][@xml:id]",
                               namespaces=ns)
        if mode in ("master", "header-probe") and not revisions:
            issues.append(ValidationIssue("semantic", "master-revision-binding",
                                          "/TEI/teiHeader/revisionDesc", "expected a dated, identified revision change"))

    if package is not None and fixture_id is not None:
        reference = compare_reference(data, package, fixture_id)
        accounting = reference.as_dict()
        for rule in reference.issues:
            issues.append(ValidationIssue("reference", rule, "/", "candidate differs from its frozen reference excerpt"))
    semantic_valid = p5_valid and not any(issue.stage == "semantic" for issue in issues)
    return ValidationResult(sha256(data).hexdigest(), active_profile.manifest_sha256,
                            p5_valid, semantic_valid, mode, tuple(issues), accounting, schema_evidence,
                            extension_ids, tuple(readiness))
