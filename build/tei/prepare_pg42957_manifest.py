"""Create pinned source-feature and manifest authorities for PG42957."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build.tei.modern_scepticism_manifest_oracle import (  # noqa: E402
    EXPECTED_HEADS,
    _closure_sha,
    _sha,
    _source_snapshot,
)
from build.tei.modern_scepticism_manifest_reconstruction import (  # noqa: E402
    CONVERTER_ID,
    CONVERTER_VERSION,
)
from ocd_kernel.library._common import io_path  # noqa: E402


BASE = ROOT / "sources/manifest-acquisitions/pg42957-modern-scepticism"
SOURCE_ROOT = ROOT / (
    "raw/clean-ready-acquisition-to-tei/master-4/28/"
    "modern-scepticism-christian-evidence-society-1871"
)
RECEIPT_PATH = ROOT / (
    "reports/clean-ready-acquisition-to-tei/master-4/28/"
    "modern-scepticism-christian-evidence-society-1871/evidence/source_receipt.json"
)
WORK_ROOT = ROOT / "library/works/modern-scepticism-christian-evidence-society-1871"
FORM = "modern-scepticism-christian-evidence-society-1871-gutenberg-retained-en"
EDITION = "modern-scepticism-christian-evidence-society-1871-gutenberg-electronic"
ACQUISITION = f"{EDITION}-acquired"
TEXTUAL_FORM = f"{WORK_ROOT.name}-gutenberg-retained-en"
PRIMARY = "42957-h.htm"
MEMBER_TREATMENTS = {
    "42957-h.htm": ("primary-source", "sole retained textual and structural authority"),
    "42957-0.txt": ("retained-source-member", "retained legacy plain-text corroborating witness"),
    "files-index.html": ("retained-source-member", "provider directory index; acquisition evidence"),
    "landing.html": ("retained-source-member", "provider landing page; identity and metadata evidence"),
    "legacy-html-index.html": ("retained-source-member", "provider legacy-directory index; acquisition evidence"),
    "pg42957-h.zip": ("retained-source-member", "retained provider HTML container; member and cover evidence"),
    "pg42957-images.html": ("retained-source-member", "current HTML corroborating witness; not the selected text authority"),
    "pg42957.txt": ("retained-source-member", "current plain-text corroborating witness; not the selected text authority"),
}


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _authority(name: str, path: str, role: str, **extra: object) -> dict[str, Any]:
    content = io_path(ROOT / path).read_bytes()
    return {
        "bytes": len(content),
        "name": name,
        "path": path,
        "role": role,
        "sha256": _sha(content),
        **extra,
    }


def _write_json(path: Path, value: object) -> None:
    io_path(path).parent.mkdir(parents=True, exist_ok=True)
    io_path(path).write_bytes(_canonical(value))


def _build() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    receipt = json.loads(io_path(RECEIPT_PATH).read_text(encoding="utf-8"))
    if set(item["name"] for item in receipt["retained_members"]) != set(MEMBER_TREATMENTS):
        raise ValueError("source receipt member list differs from the reviewed eight-member set")
    member_authorities = []
    for name, (role, treatment) in MEMBER_TREATMENTS.items():
        receipt_item = next(item for item in receipt["retained_members"] if item["name"] == name)
        path = SOURCE_ROOT / name
        content = io_path(path).read_bytes()
        if len(content) != receipt_item["bytes"] or _sha(content) != receipt_item["sha256"]:
            raise ValueError(f"retained source receipt changed for {name}")
        member_authorities.append(
            {
                "bytes": len(content),
                "name": "primary-source" if name == PRIMARY else name,
                "path": path.relative_to(ROOT).as_posix(),
                "role": role,
                "sha256": _sha(content),
                "treatment": treatment,
                "source_url": receipt_item["url"],
            }
        )

    source_path = SOURCE_ROOT / PRIMARY
    source_body = _source_snapshot(io_path(source_path).read_bytes())
    source_state_path = WORK_ROOT / "state.json"
    state_bytes = io_path(source_state_path).read_bytes()
    state = json.loads(state_bytes.decode("utf-8"))
    state_snapshot = {
        "contract": "ocd-target-state-snapshot-v1",
        "work_id": state["work_id"],
        "source_path": source_state_path.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(state_bytes).hexdigest(),
        "targets": [
            {
                "evidence": target["evidence"],
                "stage": target["stage"],
                "target_id": target["target_id"],
                "target_type": target["target_type"],
                "updated_at": target["updated_at"],
            }
            for target in state["targets"]
            if target["target_id"] in {EDITION, ACQUISITION}
        ],
    }
    if len(state_snapshot["targets"]) != 2 or any(
        item["stage"] != "acquired" for item in state_snapshot["targets"]
    ):
        raise ValueError("expected exact current acquired edition and acquisition targets")
    _write_json(BASE / "state-at-reconstruction.json", state_snapshot)

    config_path = "sources/structured-text/modern-scepticism-christian-evidence-society-1871/config.json"
    work_path = WORK_ROOT.relative_to(ROOT).as_posix() + "/work.json"
    acquisition_path = (
        WORK_ROOT.relative_to(ROOT).as_posix()
        + f"/forms/{FORM}/editions/{EDITION}/acquisitions/{ACQUISITION}.json"
    )
    source_mapping = [
        {"source_feature": "complete legacy XHTML body text and mixed inline order", "tei_representation": "front/body/back content in source order", "exceptions": "parser recovery normalization only; exact normalized text hash required"},
        {"source_feature": "eleven h2 lecture starts and the explanatory paper", "tei_representation": "eleven body div type=lecture followed by one explanatory_paper div", "exceptions": "headings nested within each complete volume TEI"},
        {"source_feature": "526 identified page markers", "tei_representation": "TEI ref type=page_milestone with source xml:id and label", "exceptions": "none"},
        {"source_feature": "181 endnotes and 362 note references", "tei_representation": "attached TEI note elements and typed ref targets", "exceptions": "source's acknowledged numbering anomalies remain visible"},
        {"source_feature": "22 poetry containers and one 26-row/40-cell table", "tei_representation": "TEI quote/lg/l and table/row/cell", "exceptions": "source wording and layout carriers are not modernized"},
        {"source_feature": "all source fragment and external href targets", "tei_representation": "ordered TEI ref target values with local fragment closure", "exceptions": "external intended-target verification is not claimed"},
        {"source_feature": "requesting society and multiple named contributors", "tei_representation": "no aggregate author; source-attested named contributors in respStmt", "exceptions": "preface and transcription credits are not promoted to aggregate authorship"},
    ]
    exclusions = [
        {"item": "HTML head, stylesheet, and provider container controls", "reason": "metadata/package structures rather than body text; exact source bytes remain bound"},
        {"item": "cover image in pg42957-h.zip", "reason": "container cover is not embedded or referenced in the selected legacy XHTML body"},
        {"item": "print-page correspondence", "reason": "no printed-page scan is retained; no print-equivalence assertion is made"},
        {"item": "aggregate author Christian Evidence Society", "reason": "the title page identifies a requesting society and the volume names multiple text contributors"},
    ]
    profile = {
        "contract": "ocd-source-feature-profile-v1",
        "source_id": "pg42957-modern-scepticism-retained-legacy-xhtml",
        "manifest_row": "L879 / Project Gutenberg 42957 constituent",
        "work_id": WORK_ROOT.name,
        "textual_form_id": TEXTUAL_FORM,
        "edition_id": EDITION,
        "acquisition_id": ACQUISITION,
        "retained_source_path": source_path.relative_to(ROOT).as_posix(),
        "source_url": "https://www.gutenberg.org/files/42957/42957-h/42957-h.htm",
        "source_sha256": _sha(io_path(source_path).read_bytes()),
        "source_bytes": io_path(source_path).stat().st_size,
        "source_body": source_body,
        "top_level_title_count": source_body["title_heading_count"],
        "work_boundary_evidence": [
            {"locator": "body h1 title-page heading", "observation": "the retained title page identifies one top-level Modern Scepticism volume"},
            {"locator": "Preface, paragraph beginning 'The following Lectures'", "observation": "states that the lectures delivered at the Society's request were gathered together into one volume"},
            {"locator": "Contents, title-page volume table", "observation": "lists eleven lecture titles and the explanatory paper as parts of the same volume"},
            {"locator": "body final marker", "observation": "one Gutenberg ebook end marker closes the complete retained volume"},
        ],
        "source_member_set": [
            {"name": Path(item["path"]).name, "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"], "role": item["role"], "treatment": item["treatment"]}
            for item in sorted(member_authorities, key=lambda value: value["path"])
        ],
        "source_transcription_note": "The retained source notes punctuation/spelling normalization, corrected typographical errors and Greek accents, and renumbered/moved notes; this candidate preserves the transcription and does not infer print text.",
        "mapping": source_mapping,
        "exclusions": exclusions,
        "prior_exposure": "Not a blind check: a prior source-specific converter and candidate were inspected. The validator is separately implemented with html5lib, while the producer uses lxml.html; expectations are recomputed from exact retained source bytes.",
        "visual_review": "not performed; exact candidate pair is not used to claim visual or print-page collation",
    }
    _write_json(BASE / "profile.json", profile)

    authorities = list(member_authorities)
    authority_specs = [
        ("source-receipt", "reports/clean-ready-acquisition-to-tei/master-4/28/modern-scepticism-christian-evidence-society-1871/evidence/source_receipt.json", "source-acquisition-evidence"),
        ("profile", "sources/manifest-acquisitions/pg42957-modern-scepticism/profile.json", "complete-source-feature-profile"),
        ("policy", "sources/manifest-acquisitions/pg42957-modern-scepticism/validation-policy.json", "independent-validation-policy"),
        ("accountability-schema", "sources/manifest-acquisitions/pg42957-modern-scepticism/accountability.schema.json", "source-accountability-schema"),
        ("source-config", config_path, "canonical-source-metadata"),
        ("source-config-readme", "sources/structured-text/modern-scepticism-christian-evidence-society-1871/README.md", "source-metadata-notes"),
        ("source-credit", "library/works/modern-scepticism-christian-evidence-society-1871/SOURCE_CREDIT.md", "human-visible-source-credit"),
        ("work-identity", work_path, "canonical-work-identity"),
        ("target-state", "sources/manifest-acquisitions/pg42957-modern-scepticism/state-at-reconstruction.json", "canonical-target-state-snapshot"),
        ("acquisition-record", acquisition_path, "canonical-acquisition-identity"),
        ("project-instructions", "AGENTS.md", "project-agent-instructions"),
        ("source-to-tei-skill", ".agents/skills/source-to-tei/SKILL.md", "active-source-to-tei-method"),
        ("acquisition-manifest", "research/MANIFEST.md", "canonical-acquisition-manifest"),
        ("converter-source-map", "build/tei/modern_scepticism_christian_evidence_society_1871.py", "implementation-dependency"),
        ("candidate-wrapper", "build/tei/modern_scepticism_manifest_reconstruction.py", "implementation-dependency"),
        ("independent-oracle", "build/tei/modern_scepticism_manifest_oracle.py", "implementation-dependency"),
        ("manifest-preparer", "build/tei/prepare_pg42957_manifest.py", "implementation-dependency"),
        ("reconstruction-contract", "ocd_kernel/reconstruction/contract.py", "implementation-dependency"),
        ("reconstruction-cli", "build/tools/reconstruct_candidate.py", "implementation-dependency"),
        ("tei-validation-schema", "ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-validation-schema"),
        ("tei-p5-relaxng", "ocd_kernel/tei/vendor/relaxng/tei_all.rng", "tei-p5-relaxng-schema"),
        ("candidate-package-schema", "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", "candidate-package-schema"),
        ("focused-tests", "tests/test_modern_scepticism_christian_evidence_society_1871.py", "focused-existing-source-tests"),
        ("mutation-challenger", "build/tei/modern_scepticism_manifest_mutation_challenge.py", "independent-validation-challenge"),
    ]
    authorities.extend(_authority(*spec) for spec in authority_specs)
    converter_path = "build/tei/modern_scepticism_manifest_reconstruction.py"
    converter_bytes = io_path(ROOT / converter_path).read_bytes()
    oracle_path = "build/tei/modern_scepticism_manifest_oracle.py"
    oracle_bytes = io_path(ROOT / oracle_path).read_bytes()
    manifest = {
        "contract": "ocd-source-manifest-v1",
        "source_id": profile["source_id"],
        "manifest_row": profile["manifest_row"],
        "work_id": WORK_ROOT.name,
        "textual_form_id": TEXTUAL_FORM,
        "edition_id": EDITION,
        "acquisition_id": ACQUISITION,
        "retained_source_path": source_path.relative_to(ROOT).as_posix(),
        "source_scope": "One complete 1871 Modern Scepticism volume as encoded by the complete retained Project Gutenberg legacy XHTML body: eleven lectures and its explanatory paper, with the title page, preface, contents, endnotes, transcriber's notes, and provider start/end markers.",
        "source_url": profile["source_url"],
        "scope": {
            "kind": "one-complete-top-level-titled-work",
            "top_level_title_count": 1,
            "body_division_count": 12,
            "candidate_tei_count": 1,
            "included": "the complete retained legacy XHTML body in source order",
            "not_claimed": ["print-page equivalence", "full visual review", "human acceptance", "rights clearance", "publication authorization"],
        },
        "source_bundle": {
            "members": 8,
            "bytes": sum(item["bytes"] for item in member_authorities),
            "sha256": _sha(
                _canonical(
                    {
                        "contract": "ocd-source-member-set-v1",
                        "members": [
                            {"name": Path(item["path"]).name, "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]}
                            for item in sorted(member_authorities, key=lambda value: (value["path"], value["name"]))
                        ],
                    }
                )
            ),
        },
        "authorities": authorities,
        "converter": {
            "id": CONVERTER_ID,
            "version": CONVERTER_VERSION,
            "callable": "_convert",
            "implementation_path": converter_path,
            "implementation_sha256": hashlib.sha256(converter_bytes).hexdigest(),
        },
        "validator": {
            "id": "ocd-l879-pg42957-independent-html5-tei-oracle",
            "version": "1",
            "callable": "_oracle",
            "implementation_path": oracle_path,
            "implementation_sha256": hashlib.sha256(oracle_bytes).hexdigest(),
            "import_closure_sha256": _closure_sha(),
        },
        "package_schema": {
            "path": "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
            "sha256": _sha(io_path(ROOT / "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json").read_bytes()),
        },
    }
    _write_json(BASE / "source-manifest.json", manifest)


if __name__ == "__main__":
    _build()
