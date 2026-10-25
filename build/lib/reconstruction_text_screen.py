"""Advisory character evidence for the supported reconstruction handoff."""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path

from build.lib.text_lint import lint_file, lint_json_strings, lint_xml_file
from ocd_kernel.lib.path_io import io_path
from ocd_kernel.reconstruction.contract import _contained


def _screen(path: Path, *, reference: str, expected_sha256: str, role: str) -> dict:
    row = {"path": reference, "sha256": expected_sha256, "role": role}
    suffix = path.suffix.lower()
    if suffix not in {".txt", ".json", ".xml", ".xhtml", ".thml", ".tei"}:
        return row | {"status": "not_screened", "reason": "No generic character reader for this format; account for text-bearing inputs with a source-specific reader."}
    # ponytail: source inputs above the preflight limit need a source-specific reader.
    if role != "candidate-tei" and io_path(path).stat().st_size > 64 * 1024 * 1024:
        return row | {"status": "not_screened", "reason": "Source exceeds the 64 MiB preflight limit."}
    reader = lint_json_strings if suffix == ".json" else lint_file if suffix == ".txt" else lint_xml_file
    try:
        report = reader(io_path(path))
    except (ValueError, RecursionError) as exc:
        if role == "candidate-tei":
            raise ValueError("Candidate TEI character screening failed: " + str(exc)) from exc
        return row | {"status": "not_screened", "reason": str(exc)}
    if report["source_sha256"] != expected_sha256:
        raise ValueError("Character-screen input differs from its binding: " + reference)
    for observation in report["observations"]:
        if "roles" in report["coverage"]:
            observation["role"] = report["coverage"]["roles"][observation["locator"]]
    return row | {"status": "screened", "tool_version": report["tool_version"],
                  "implementation_sha256": report["implementation_sha256"],
                  "unicode_version": report["unicode_version"],
                  "coverage": {k: v for k, v in report["coverage"].items() if k not in {"roles", "locators"}},
                  "groups": report["groups"], "observations": report["observations"]}


def screen_reconstruction(source_manifest, candidate) -> dict:
    """Account for every bound authority and screen actual TEI before handoff."""
    # Resolve the already-bound record directly; repeated name lookup is quadratic.
    inputs = [_screen(_contained(source_manifest.repository_root, a["path"], a["name"]), reference=a["path"],
                      expected_sha256=a["sha256"], role=a["role"])
              for a in source_manifest.record["authorities"]]
    raw = candidate.member_bytes("content.tei.xml")
    inputs.append(_screen(candidate.path / "content.tei.xml", reference="package/content.tei.xml",
                          expected_sha256=hashlib.sha256(raw).hexdigest(), role="candidate-tei"))
    source_manifest.verify()
    candidate.verify_integrity()
    counts = Counter(o["rule"] for row in inputs for o in row.get("observations", []))
    return {"contract": "ocd-reconstruction-text-screen-v1", "status": "completed",
            "source_manifest_sha256": source_manifest.sha256, "candidate_sha256": candidate.sha256,
            "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "coverage": "partial" if any(r["status"] != "screened" for r in inputs) else "complete",
            "review_status": "required" if counts or any(r["status"] != "screened" for r in inputs) else "no_character_observations",
            "text_correctness": "not_assessed", "observation_counts": dict(sorted(counts.items())),
            "inputs": inputs,
            "limits": "Character observations only. XML attributes/comments/PI values, JSON keys, embedded markup interpretation, cross-segment sequences, spelling and intended readings are outside coverage. Unsupported inputs require a source-specific disposition. Findings never authorize corrections or establish editorial acceptance."}
