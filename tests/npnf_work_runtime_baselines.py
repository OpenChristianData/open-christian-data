"""Real current NPNF candidates preserve the immutable retained body members."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest

def current_work_baseline(root, case, destination):
    raw = (root / case["original"]).read_bytes()
    assert sha256(raw).hexdigest() == case["original_sha256"]
    retained = CandidatePackage.load(Path(case["retained_package"]))
    assert retained.sha256 == case["retained_sha256"]
    assert retained.manifest["source_manifest"]["sha256"] == case["retained_source_manifest_sha256"]
    execution_root = root
    protected = {}
    if "historical_work" in case:
        from tests.retained_handoff_runtime_fixture import _mirror, _copy
        binding = case["historical_work"]
        record = json.loads((root / case["manifest"]).read_bytes())
        profile_path = next(row["path"] for row in record["authorities"]
                            if row["name"] == "reconstruction-profile")
        profile = json.loads((root / profile_path).read_bytes())
        work_raw = (root / binding["fixture"]).read_bytes()
        assert len(work_raw) == binding["bytes"]
        assert sha256(work_raw).hexdigest() == binding["sha256"] == profile["work_sha256"]
        assert binding["path"] == "library/works/" + case["work_id"] + "/work.json"
        acquisition = root / profile["acquisition_path"]
        acquisition_raw = acquisition.read_bytes()
        assert sha256(acquisition_raw).hexdigest() == profile["acquisition_sha256"]
        protected = {path: path.read_bytes() for path in
                     (root / binding["path"], acquisition, root / case["original"])}
        execution_root = destination.parent / (case["work_id"] + "-historical-root")
        execution_root.mkdir()
        _mirror(root, execution_root, record)
        for relative in case["closure_inputs"]:
            logical = Path(relative)
            assert not logical.is_absolute() and ".." not in logical.parts
            _copy(execution_root, relative, (root / logical).read_bytes())
        _copy(execution_root, case["manifest"], (root / case["manifest"]).read_bytes())
        _copy(execution_root, binding["path"], work_raw)
        _copy(execution_root, profile["acquisition_path"], acquisition_raw)
    result = subprocess.run([sys.executable, "-m", "build.tools.reconstruct_candidate",
        "--repository-root", str(execution_root), "--manifest", case["manifest"],
        "--destination", str(destination)], cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout)["status"] == "pass"
    current = CandidatePackage.load(destination / "package")
    assert current.member_names == retained.member_names
    for name in current.member_names:
        if name != "manifest.json":
            assert current.member_bytes(name) == retained.member_bytes(name), name
    assert current.manifest["status"] == "nonaccepted"
    assert sha256((root / case["original"]).read_bytes()).hexdigest() == case["original_sha256"]
    for path, original in protected.items():
        assert path.read_bytes() == original
    return SourceManifest.load(execution_root / case["manifest"], repository_root=execution_root), current
