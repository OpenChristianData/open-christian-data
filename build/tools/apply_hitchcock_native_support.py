"""Apply only the coordinator-reviewed, tested single-file successor."""

from datetime import datetime, timezone
import json

from build.tools.prepare_hitchcock_current import ROOT, LOG, BASE, save, json_bytes, digest


def main() -> None:
    proposal = LOG / "native-support-proposal"
    before = (proposal / "reference_entries.before.py").read_bytes()
    after = (proposal / "reference_entries.after.py").read_bytes()
    module = ROOT / "ocd_kernel/projection/categories/reference_entries.py"
    if digest(before) != "ba8a1886ca39b06ba47adb5c4c06c24d118a24612385c0fc4673c212994c88bc" or digest(after) != "2211d08e5726fdabac379485bf4dedac68f1130f5f43432f226089222070d857":
        raise ValueError("Reviewed proposal snapshot changed")
    if module.read_bytes() != before:
        raise ValueError("Immediate shared preimage differs; do not overwrite")
    if int((proposal / "focused-tests.log.exit").read_text().strip()) or int((proposal / "compatibility-tests.log.exit").read_text().strip()):
        raise ValueError("Focused test terminal failed")
    actual = json.loads((proposal / "actual-candidate-proof.json").read_text())
    if actual["status"] != "pass" or actual["adapter_proposed_sha256"] != digest(after) or actual["rows"] != 2622:
        raise ValueError("Whole candidate proof differs")
    bindings = {}
    paths = [proposal / name for name in ("design.json", "reference_entries.before.py", "reference_entries.after.py", "patch.diff", "focused-tests.log", "focused-tests.log.exit", "compatibility-tests.log", "compatibility-tests.log.exit", "actual-candidate-proof.json")]
    paths.extend(ROOT / name for name in ("tests/test_projection_hitchcock_native.py", "tests/test_projection_reference_entries.py", "build/tools/prove_hitchcock_candidate.py", "build/tools/prove_hitchcock_compatibility.py", "schemas/v2/categories/reference-entries.schema.json", "schemas/v2/public-row.schema.json"))
    paths.extend(BASE / name for name in ("candidate.tei.xml", "source-proof.json", "source-accounting.json"))
    for path in paths:
        bindings[path.relative_to(ROOT).as_posix()] = digest(path.read_bytes())
    clearance = {"status": "coordinator-cleared", "cleared_at": datetime.now(timezone.utc).isoformat(), "authority": "ROOT message: exact single shared-file apply cleared after full patch, 27 focused tests, 23 compatibility tests and actual full candidate proof; Easton freeze closed.", "before_sha256": digest(before), "after_sha256": digest(after), "focused_tests": {"new": 27, "compatibility": 23, "exit_codes": [0, 0]}, "actual_candidate_terminal": {"session_id": 92669, "chunk_id": "f6d09a", "exit_code": 0}, "bindings": bindings, "schema_changed": False}
    save(proposal / "apply-clearance.json", json_bytes(clearance))
    if module.read_bytes() != before:
        raise ValueError("Shared file changed before reviewed apply")
    module.write_bytes(after)
    if module.read_bytes() != after:
        raise ValueError("Shared successor readback differs")
    freeze = {"status": "pass", "module": module.relative_to(ROOT).as_posix(), "before_sha256": digest(before), "after_sha256": digest(module.read_bytes()), "clearance_sha256": digest(json_bytes(clearance)), "schema_changed": False, "tests_reused_basis": "Applied bytes equal the separately tested snapshot exactly; no passed gates repeated.", "bindings": bindings}
    save(proposal / "applied-freeze.json", json_bytes(freeze))
    print(json.dumps(freeze))


if __name__ == "__main__":
    main()
