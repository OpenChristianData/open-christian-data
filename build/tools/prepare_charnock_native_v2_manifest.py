"""Pin Volume 2 PG53527 stock-native carrier producer and independent oracle."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from build.tei.charnock_gutenberg_native_v2_reconstruction import _closure as _producer_closure
from build.tei.charnock_gutenberg_native_v2_oracle import _closure_digest


ROOT = Path(__file__).resolve().parents[2]
BASE = Path("sources/structured-text/charnock-existence-attributes-vol-2")
V1 = BASE / "charnock-existence-attributes-vol-2.source-manifest.json"
PROFILE = BASE / "charnock-existence-attributes-vol-2.native-v2.reconstruction-profile.json"
POLICY = BASE / "charnock-existence-attributes-vol-2.native-v2.validation-policy.json"
OUT = BASE / "charnock-existence-attributes-vol-2.native-v2.source-manifest.json"
PRODUCER = Path("build/tei/charnock_gutenberg_native_v2_reconstruction.py")
ORACLE = Path("build/tei/charnock_gutenberg_native_v2_oracle.py")


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(path: Path) -> str:
    return sha256((ROOT / path).read_bytes()).hexdigest()


def main() -> None:
    profile = json.loads((ROOT / PROFILE).read_bytes())
    profile.update(
        contract="ocd-charnock-pg53527-native-reconstruction-profile-v2",
        profile_id="charnock-existence-attributes-vol-2-pg53527-native-v2",
        version=2,
        native_carriers={
            "page": "pb@n and corresp retain 542 source page markers",
            "blank_line": "lb@type=source-blank-line, n and corresp retain 2765 empty source lines",
            "source_line_ledger": "32140 JSON entries in note@type=source-line-accountability; native readable text omits them",
        },
        producer_import_closure_sha256=sha256(_canonical(_producer_closure(ROOT, ROOT / PRODUCER))).hexdigest(),
    )
    (ROOT / PROFILE).write_bytes(_canonical(profile))
    policy = json.loads((ROOT / POLICY).read_bytes())
    policy.update(
        contract="ocd-charnock-pg53527-native-validation-policy-v2",
        policy_id="charnock-existence-attributes-vol-2-pg53527-native-v2",
        version=2,
        forbidden_import_prefixes=[
            "build.tei.charnock_gutenberg_native_v2_reconstruction",
            "build.parsers.gutenberg_puritan",
        ],
    )
    for check in (
        "source-derived-page-pb-sequence",
        "source-derived-blank-lb-sequence",
        "exact-json-note-line-ledger-and-native-readable-omission",
    ):
        if check not in policy["checks"]:
            policy["checks"].append(check)
    (ROOT / POLICY).write_bytes(_canonical(policy))
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
        id="ocd-charnock-pg53527-native-volume-to-tei", version="2",
        implementation_path=PRODUCER.as_posix(), implementation_sha256=_sha(PRODUCER),
    )
    record["validator"].update(
        id="ocd-charnock-pg53527-independent-native-partition-oracle", version="2",
        implementation_path=ORACLE.as_posix(), implementation_sha256=_sha(ORACLE),
        import_closure_sha256=_closure_digest(ROOT, policy, ROOT / ORACLE),
    )
    (ROOT / OUT).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
