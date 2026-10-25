"""Bind immutable coordinator review and terminal evidence without repeating gates."""

import json

from build.tools.prepare_nave_current import ROOT, LOG, WORK_ID, digest, save, json_bytes
from build.tools.complete_nave_private_release import OUT, WORK, EDITION, hash_path
from ocd_kernel.library._common import io_path


def main():
    terminal = LOG / "private-release.log.exit"
    if terminal.read_text().strip() != "0":
        raise ValueError("Nave release has no authoritative successful terminal")
    final_path = OUT / "final-current-binding-audit.json"
    final = json.loads(final_path.read_bytes())
    completion = OUT / "completion.json"
    if (final["status"] != "pass" or not final["release_gates_complete"]
            or completion.read_bytes() != io_path(ROOT / WORK / "publication/completion.json").read_bytes()):
        raise ValueError("Completed private/canonical accounting differs")
    coordinator = LOG / "coordinator-installed-generation-review.json"
    if hash_path(coordinator) != "bc45e98d16260fdc001f7990f90d762a3c8be19ea5fbf8341f93c8632be02d0e":
        raise ValueError("Exact coordinator installed generation proof differs")
    for name in ("assembly", "independent-verification", "statistics", "readers"):
        if json.loads((OUT / (name + ".json")).read_bytes())["status"] != "pass":
            raise ValueError("Saved release gate not passed: " + name)
    anchors = [coordinator, LOG / "private-release.log", terminal, LOG / "canonical-install/installed-generation.json",
               LOG / "canonical-install/notice-delivery.json", LOG / "native-support-proposal-v2/coordinator-adapter-clearance.json",
               ROOT / "reports/_logs/nave-coordinator-source-review-20261002-v1/review.json"]
    supplement = {"status": "pass", "work_id": WORK_ID, "final_audit_path": final_path.relative_to(ROOT).as_posix(),
                  "final_audit_sha256": hash_path(final_path), "immutable_additional_root_bindings": {p.relative_to(ROOT).as_posix(): hash_path(p) for p in anchors},
                  "authoritative_terminal_exit": 0, "release_gates_repeated": False, "accepted_master_sha256": hash_path(ROOT / EDITION / "master.tei.xml"),
                  "historical_body_reused_unchanged": True, "rows": 5322, "literal_references": 82303, "text_characters": 1410060,
                  "source_inventory_vs_reading_order": "Four physical extracted members in acquisition inventory; dict.idx addresses all 5322 ordered payloads. Config/ZIP/support accounted separately.",
                  "public_rendering": "One complete-definition item per native entry; exact literal reference order; list depth visible by indentation and boundaries. Full native hierarchy/whitespace preserved in master and private receipt, not asserted for plain-text public rows.",
                  "historical_manifest_gap": "Missing l876-v2 source-manifest retained as historical reference, replaced by current physical source-member authority and full current source/native proofs, not fabricated.",
                  "rights_clearance": "unresolved", "human_decision": "not-recorded", "exact_print_lineage": "unverified", "publication_performed": False}
    save(OUT / "delivery-supplement.json", json_bytes(supplement))
    readme = ("# Nave's Topical Bible — private technical completion\n\n"
              "The complete retained Nave v3 electronic module is installed as one native TEI master. Its verified private release contains 5,322 ordered entries, 82,303 literal references, and 1,410,060 rendered text characters. Duplicate keys and payload labels remain distinct source occurrences.\n\n"
              "Actual canonical-master projection matches the reviewed stage. Standard assembly, independent verification, statistics, and normal/streaming readers passed; the owned terminal exit is 0. Final map bases and immutable coordinator/source/terminal anchors are in `final-current-binding-audit.json` and `delivery-supplement.json`. Canonical publication accounting points to this private output.\n\n"
              "CrossWire and stated CCEL TextSource roles and module-stated public-domain terms are visible in both source and data notices and the private release README. Human acceptance, rights clearance, exact print lineage, and public publication remain unassessed or unresolved. No acquisition, source-body conversion, Git action, or public publication occurred.\n")
    save(OUT / "README.md", readme.encode())
    result = {"status": "pass", "authoritative_exit": 0, "root_bindings": len(final["root_bindings"]), "release_bindings": len(final["release_bindings"]), "output_bindings": len(final["output_bindings"]), "supplement_bindings": len(supplement["immutable_additional_root_bindings"]), "final_audit_sha256": hash_path(final_path), "supplement_sha256": hash_path(OUT / "delivery-supplement.json"), "readme_sha256": hash_path(OUT / "README.md")}
    save(OUT / "delivery-result.json", json_bytes(result))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
