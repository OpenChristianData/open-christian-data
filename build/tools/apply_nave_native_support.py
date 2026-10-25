"""Apply only the two exact coordinator-cleared Nave support byte images."""

import json

from build.tools.prepare_nave_current import ROOT, LOG, digest, save, json_bytes


def main():
    proposal = LOG / "native-support-proposal-v2"
    clearance = proposal / "coordinator-adapter-clearance.json"
    expected_clearance = "94747eb60a35317dd2da9ad8a3a6ec33743468a8199fdd9a623e26785d86e713"
    if digest(clearance.read_bytes()) != expected_clearance:
        raise ValueError("Exact Nave coordinator adapter clearance differs")
    design = json.loads((proposal / "design.json").read_bytes())
    dispatch = ROOT / design["existing_file"]
    added = ROOT / design["new_module"]
    before = (proposal / "topical_indexes.before.py").read_bytes()
    after = (proposal / "topical_indexes.after.py").read_bytes()
    module = (proposal / "topical_nave.after.py").read_bytes()
    if dispatch.read_bytes() != before or added.exists() or digest(before) != design["before_sha256"] or digest(after) != design["after_sha256"] or digest(module) != design["new_module_sha256"]:
        raise ValueError("Immediate Nave cleared code preimages/successors differ")
    compile(after, str(dispatch), "exec"); compile(module, str(added), "exec")
    added.write_bytes(module)
    temporary = dispatch.with_name(".nave-dispatch.tmp")
    if temporary.exists():
        raise ValueError("Unowned dispatch temporary file exists")
    try:
        temporary.write_bytes(after); temporary.replace(dispatch)
    except OSError:
        if added.read_bytes() == module and dispatch.read_bytes() == before:
            added.unlink()
        raise
    if dispatch.read_bytes() != after or added.read_bytes() != module:
        raise ValueError("Applied Nave shared code readback differs")
    report = {"status": "pass", "clearance_sha256": expected_clearance, "files": {design["existing_file"]: {"before": design["before_sha256"], "after": digest(dispatch.read_bytes())}, design["new_module"]: {"before": None, "after": digest(added.read_bytes())}}, "scope": "Exact reviewed dispatch branches and new Nave native module; no schema, source, metadata or canonical master change."}
    save(proposal / "applied-runtime.json", json_bytes(report)); print(json.dumps(report))


if __name__ == "__main__":
    main()
