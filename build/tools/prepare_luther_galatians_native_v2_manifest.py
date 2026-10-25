"""Pin Luther PG1549's work-local native-line v2 source contract."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei.luther_galatians_native_v2_reconstruction import _canonical, _closure
from build.tei.luther_galatians_native_v2_oracle import _closure as _oracle_closure


ROOT = Path(__file__).resolve().parents[2]
BASE = Path("sources/structured-text/luther-commentary-on-galatians")
V1 = BASE / "luther-commentary-on-galatians.source-manifest.json"
PROFILE = BASE / "luther-commentary-on-galatians.native-v2.reconstruction-profile.json"
POLICY = BASE / "luther-commentary-on-galatians.native-v2.validation-policy.json"
OUT = BASE / "luther-commentary-on-galatians.native-v2.source-manifest.json"
PRODUCER = Path("build/tei/luther_galatians_native_v2_reconstruction.py")
ORACLE = Path("build/tei/luther_galatians_native_v2_oracle.py")


def _sha(path: Path) -> str:
    return sha256((ROOT / path).read_bytes()).hexdigest()


def main() -> None:
    profile = json.loads((ROOT / PROFILE).read_bytes())
    profile["producer_import_closure_sha256"] = sha256(
        _canonical(_closure(ROOT, ROOT / PRODUCER))
    ).hexdigest()
    (ROOT / PROFILE).write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record = json.loads((ROOT / V1).read_bytes())
    for item in record["authorities"]:
        if item["name"] == "reconstruction-profile":
            item["path"] = PROFILE.as_posix()
        elif item["name"] == "validation-policy":
            item["path"] = POLICY.as_posix()
        path = Path(item["path"])
        item["bytes"] = (ROOT / path).stat().st_size
        item["sha256"] = _sha(path)
    record["converter"].update(
        id="ocd-luther-galatians-pg1549-native-line-tei", version="2",
        implementation_path=PRODUCER.as_posix(), implementation_sha256=_sha(PRODUCER),
    )
    record["validator"].update(
        id="ocd-luther-galatians-pg1549-independent-native-line-oracle", version="2",
        implementation_path=ORACLE.as_posix(), implementation_sha256=_sha(ORACLE),
        import_closure_sha256=sha256(_canonical(_oracle_closure(
            ROOT, ROOT / ORACLE, ("build.tei.luther_galatians_native_v2_reconstruction",)
        ))).hexdigest(),
    )
    (ROOT / OUT).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
