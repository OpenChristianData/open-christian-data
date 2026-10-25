"""Prepare the source profile, policy, and manifest for retained TCP A23804."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build.tei.whole_duty_prayer_a23804_oracle import _closure_digest
from build.tei.whole_duty_prayer_a23804_reconstruction import _inspect


SOURCE = "raw/tcp/high-range/A23804/A23804.xml"
SOURCE_ID = "tcp-A23804"
WORK_ID = "whole-duty-of-prayer"
TEXTUAL_FORM_ID = "whole-duty-of-prayer-tcp-retained"
EDITION_ID = "whole-duty-of-prayer-tcp-electronic"
ACQUISITION_ID = "whole-duty-of-prayer-tcp-acquired"
LOCAL = ROOT / "sources/structured-text" / WORK_ID
WORK_ROOT = ROOT / "library/works" / WORK_ID
PROFILE_PATH = f"sources/structured-text/{WORK_ID}/{WORK_ID}.reconstruction-profile.json"
POLICY_PATH = f"sources/structured-text/{WORK_ID}/{WORK_ID}.validation-policy.json"
MANIFEST_PATH = f"sources/structured-text/{WORK_ID}/{WORK_ID}.source-manifest.json"
SOURCE_CREDIT_PATH = f"library/works/{WORK_ID}/SOURCE_CREDIT.md"
SOURCE_TITLE = (
    "The whole duty of prayer containing devotions for every day in the week, and for several "
    "occasions, ordinary and extraordinary / by the author of The whole duty of man ..."
)
SOURCE_SCOPE = (
    "Complete retained single-member TCP A23804 TEI P5 witness: preserve the header, nested text "
    "group, complete front/body/back, internal title pages, source gaps, glyphs, page-break and "
    "facsimile references, text, tails, and attributes. Candidate content is the exact source XML "
    "byte stream; no source material is added, normalized, split, or excluded. One complete "
    "top-level titled work produces one TEI document."
)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def _binding(path: str, name: str, role: str) -> dict[str, object]:
    content = (ROOT / path).read_bytes()
    return {
        "name": name,
        "path": path,
        "role": role,
        "bytes": len(content),
        "sha256": sha256(content).hexdigest(),
    }


def main() -> None:
    source = (ROOT / SOURCE).read_bytes()
    source_sha = sha256(source).hexdigest()
    expected_sha = "4ce798180f8b9ef8c9b9cd9200b50a9c324ab858c7aad07d1e7d22931ee2a5f1"
    if len(source) != 242909 or source_sha != expected_sha:
        raise ValueError("retained TCP A23804 source no longer matches its acquisition receipt")
    receipt_path = ROOT / "raw/tcp/high-range/A23804/acquisition-receipt.json"
    inventory_path = ROOT / "raw/tcp/high-range/A23804/member-inventory.tsv"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    inventory = inventory_path.read_bytes()
    if (
        receipt.get("source_id") != SOURCE_ID
        or receipt.get("member", {}).get("path") != SOURCE
        or receipt.get("member", {}).get("bytes") != len(source)
        or receipt.get("member", {}).get("sha256") != source_sha
        or sha256(inventory).hexdigest() != receipt.get("verification", {}).get("member_inventory_sha256")
        or len(inventory.decode("utf-8").splitlines()) != 2
    ):
        raise ValueError("TCP A23804 acquisition receipt or one-member inventory differs")
    work = json.loads((WORK_ROOT / "work.json").read_text(encoding="utf-8"))
    acquisition_rel = (
        f"library/works/{WORK_ID}/forms/{TEXTUAL_FORM_ID}/editions/{EDITION_ID}/"
        f"acquisitions/{ACQUISITION_ID}.json"
    )
    acquisition = json.loads((ROOT / acquisition_rel).read_text(encoding="utf-8"))
    if (
        work.get("work_id") != WORK_ID
        or work.get("title") != SOURCE_TITLE
        or acquisition.get("acquisition_id") != ACQUISITION_ID
        or acquisition.get("edition_id") != EDITION_ID
        or acquisition.get("source_sha256") != source_sha
        or acquisition.get("source_bytes") != len(source)
    ):
        raise ValueError("existing canonical work/acquisition sidecars do not bind this source")

    counts, census, features = _inspect(source)
    profile = {
        "contract": "ocd-tcp-a23804-complete-source-profile-v1",
        "source_id": SOURCE_ID,
        "source_path": SOURCE,
        "source_bytes": len(source),
        "source_sha256": source_sha,
        "element_counts": counts,
        "source_census": census,
        "source_features": features,
    }
    _write_json(ROOT / PROFILE_PATH, profile)

    source_credit = f"""# Source credit - TCP A23804

## Work and edition

The retained TCP TEI identifies this work as *{SOURCE_TITLE}* and carries the source identifier `A23804`. This notice concerns the complete retained electronic witness, not an independently collated print copy.

The retained header names `Allestree, Richard, 1619-1681.` Its source note says that authorship is not established with absolute certainty and that the preponderance of opinion favors Dr. Allestree. This qualification is retained in the candidate. The source also identifies the preface as signed `G.B.`.

The source note describes “Additional devotions for several occasions” on printed pages [139]-164 as having a special title page. It remains internal matter of this one titled work in the same TEI document.

## TCP attribution and scope

The TCP Phase I header says those texts were released into the public domain as of January 1, 2015, and respectfully requests due credit and attribution to the original source. The retained acquisition receipt states that this TCP Phase I text is available under CC0 1.0 Universal. Credit the Text Creation Partnership and the original source when using this electronic witness.

This statement records the retained text source's terms and attribution request. It does not assess broader rights, image rights, human acceptance, or publication authorization. The retained acquisition contains one XML member and no page-image files.

- TCP source: [{SOURCE_ID}](https://github.com/textcreationpartnership/A23804)
- Retained XML: `{SOURCE}` (SHA-256 `{source_sha}`)
- Source XML URL: {receipt['source_url']}
"""
    _write(ROOT / SOURCE_CREDIT_PATH, source_credit.encode("utf-8"))

    identity = {
        "work_id": WORK_ID,
        "textual_form_id": TEXTUAL_FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
    }
    unresolved = [
        {
            "id": "a23804-print-collation",
            "status": "unresolved",
            "scope": "edition comparison",
            "question": "Has this keyboarded witness been collated against the print exemplar?",
            "evidence": "The retained acquisition has one XML member and no page images; candidate fidelity is byte preservation of that member.",
        },
        {
            "id": "a23804-human-decision",
            "status": "unresolved",
            "scope": "human review and acceptance",
            "question": "Will a human separately decide textual, identity, and acceptance questions?",
            "evidence": "This package records technical source-to-TEI evidence only and remains nonaccepted.",
        },
        {
            "id": "a23804-rights-publication",
            "status": "unresolved",
            "scope": "rights and publication",
            "question": "What broader rights disposition and publication decision will be made?",
            "evidence": "The package preserves only the source's text-layer terms and attribution request; no broader rights or publication status is set.",
        },
    ]
    profile_sha = sha256((ROOT / PROFILE_PATH).read_bytes()).hexdigest()
    policy = {
        "contract": "ocd-tcp-a23804-independent-validation-policy-v1",
        "source_id": SOURCE_ID,
        "identity": identity,
        "scope": SOURCE_SCOPE,
        "profile_sha256": profile_sha,
        "accountability": {
            "contract": "ocd-tcp-a23804-source-accountability-v1",
            "source_path": SOURCE,
            "source_member_set": [
                {
                    "position": 1,
                    "path": SOURCE,
                    "bytes": len(source),
                    "sha256": source_sha,
                    "inventory_line": inventory.decode("utf-8").splitlines()[1],
                }
            ],
            "retained_member_count": 1,
            "candidate_tei_document_count": 1,
            "complete_source_scope": SOURCE_SCOPE,
            "work_boundary": {
                "decision": "one complete work in one TEI document",
                "evidence": [
                    "one retained TEI root with one titleStmt/title matching the current work sidecar",
                    "one top-level TEI text containing one grouped work text with front, body, and back",
                    "the TCP source note identifies the additional-devotions title page as internal matter on pages [139]-164",
                ],
                "internal_matter": "The special title page for Additional devotions for several occasions remains in the body of the same work and is not split into another TEI.",
            },
            "transformation": "none; candidate TEI preserves the complete retained source member byte-for-byte",
            "omitted_source_members": [],
            "duplicated_source_members": [],
            "source_gap_disposition": "All source-encoded gap elements are preserved unchanged.",
            "source_page_and_facs_disposition": "All source-encoded page-break and facsimile pointer attributes are preserved unchanged; no image bytes are claimed.",
            "status": "complete-source-member-preserved",
        },
        "provenance": {
            "contract": "ocd-tcp-a23804-provenance-v1",
            "status": "nonaccepted",
            "source_id": SOURCE_ID,
            "provider": "Text Creation Partnership",
            "source_path": SOURCE,
            "source_bytes": len(source),
            "source_sha256": source_sha,
            "source_url": receipt["source_url"],
            "retrieved_utc": receipt["downloaded_utc"],
            "identity": identity,
            "source_attribution": "The TCP Phase I header requests due credit and attribution to the original source; see the work-local SOURCE_CREDIT.md.",
            "text_rights_scope": "The retained receipt records the TCP Phase I CC0 1.0 Universal statement for the keyboarded and encoded text. No page-image rights are claimed; broader rights status remains unresolved.",
            "candidate_relation": "Exact copy of the complete retained XML TEI member; no lexical or structural transformation.",
            "acceptance_status": "nonaccepted",
            "publication_authorized": False,
        },
        "unresolved": unresolved,
        "required": [
            "exact retained source identity, size, and SHA-256 binding",
            "complete declared one-member acquisition accounting",
            "one top-level complete titled work represented by exactly one candidate TEI",
            "preservation of source header, front/body/back, notes, gaps, page references, glyphs, attributes, order, and text",
            "independent source census and byte comparison",
            "TEI P5 XSD validation",
            "nonaccepted candidate status and source-visible credit",
        ],
    }
    _write_json(ROOT / POLICY_PATH, policy)

    converter_path = "build/tei/whole_duty_prayer_a23804_reconstruction.py"
    oracle_path = "build/tei/whole_duty_prayer_a23804_oracle.py"
    schema_path = "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json"
    xsd_path = "ocd_kernel/tei/vendor/xsd/tei_all.xsd"
    authorities = [
        _binding(SOURCE, "retained-tei-p5", "primary-source"),
        _binding("raw/tcp/high-range/A23804/acquisition-receipt.json", "acquisition-receipt", "source-acquisition-evidence"),
        _binding("raw/tcp/high-range/A23804/member-inventory.tsv", "source-member-inventory", "source-member-inventory"),
        _binding(
            f"library/works/{WORK_ID}/work.json",
            "canonical-work-sidecar",
            "canonical-work-identity",
        ),
        _binding(acquisition_rel, "canonical-acquisition-sidecar", "canonical-acquisition-linkage"),
        _binding(SOURCE_CREDIT_PATH, "source-local-attribution-readme", "source-attribution-readme"),
        _binding(PROFILE_PATH, "reconstruction-profile", "complete-source-feature-profile"),
        _binding(POLICY_PATH, "validation-policy", "independent-validation-policy"),
        _binding(xsd_path, "tei-p5-xsd", "tei-validation-schema"),
        _binding(schema_path, "candidate-package-schema", "candidate-package-schema"),
    ]
    converter_content = (ROOT / converter_path).read_bytes()
    oracle_content = (ROOT / oracle_path).read_bytes()
    manifest = {
        "contract": "ocd-source-manifest-v1",
        "source_id": SOURCE_ID,
        "work_id": WORK_ID,
        "textual_form_id": TEXTUAL_FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "manifest_row": "L788",
        "authorities": authorities,
        "converter": {
            "id": "ocd-tcp-a23804-exact-tei-p5",
            "version": "1",
            "callable": "_convert",
            "implementation_path": converter_path,
            "implementation_sha256": sha256(converter_content).hexdigest(),
        },
        "validator": {
            "id": "ocd-tcp-a23804-independent-source-oracle",
            "version": "1",
            "callable": "_oracle",
            "implementation_path": oracle_path,
            "implementation_sha256": sha256(oracle_content).hexdigest(),
            "import_closure_sha256": _closure_digest(),
        },
        "package_schema": {
            "path": schema_path,
            "sha256": sha256((ROOT / schema_path).read_bytes()).hexdigest(),
        },
    }
    _write_json(ROOT / MANIFEST_PATH, manifest)
    print(
        json.dumps(
            {
                "source_bytes": len(source),
                "source_sha256": source_sha,
                "profile_sha256": profile_sha,
                "source_manifest_sha256": sha256((ROOT / MANIFEST_PATH).read_bytes()).hexdigest(),
                "work_credit_path": SOURCE_CREDIT_PATH,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
