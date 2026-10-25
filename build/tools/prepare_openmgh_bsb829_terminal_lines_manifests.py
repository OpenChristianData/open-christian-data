"""Bind two complete terminal-line candidates to work-local source manifests."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from build.tools import prepare_openmgh_bsb829_terminal_lines as prior
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _io_path


ROOT = prior.ROOT
HOME = Path("sources/openmgh-bsb829-terminal-lines")
PRODUCER = Path("build/tools/prepare_openmgh_bsb829_terminal_lines.py")
ORACLE = Path("build/tei/openmgh_bsb829_terminal_lines_oracle.py")
CONTRACT = Path("ocd_kernel/reconstruction/contract.py")
LONG_PATH = Path("ocd_kernel/tei/install_accepted.py")
XSD = Path("ocd_kernel/tei/vendor/xsd/tei_all.xsd")
SCHEMA = Path("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json")
POLICY = HOME / "validation-policy.json"


def _sha(path: Path) -> str:
    return sha256(Path(_io_path(path)).read_bytes()).hexdigest()


def _authority(name: str, path: Path, role: str) -> dict:
    content = Path(_io_path(ROOT / path)).read_bytes()
    return {"name": name, "path": path.as_posix(), "role": role,
            "bytes": len(content), "sha256": sha256(content).hexdigest()}


def _put_owned(path: Path, data: bytes, *, refresh: bool) -> None:
    if path.exists() and path.read_bytes() != data and refresh:
        old = json.loads(path.read_bytes())
        new = json.loads(data)
        if (old.get("contract") != new.get("contract")
                or old.get("work_id", old.get("source_id"))
                != new.get("work_id", new.get("source_id"))):
            raise ValueError(f"refusing to refresh different owned evidence: {path}")
        path.write_bytes(data)
    else:
        prior._write_once(path, data)


def prepare(direct_receipt: Path, destination: Path, *, refresh: bool = False) -> dict:
    direct_receipt = direct_receipt.resolve(strict=True)
    destination = destination.resolve()
    if (destination == ROOT or ROOT in destination.parents
            or destination.exists() and any(destination.iterdir())):
        raise ValueError("fresh external package destination required")
    direct = json.loads(direct_receipt.read_bytes())
    if (direct.get("contract") != "ocd-openmgh-bsb829-terminal-lines-candidates-v1"
            or direct.get("source_sha256") != prior.SOURCE_SHA
            or direct.get("selection_plan_sha256") != prior.PLAN_SHA
            or len(direct.get("candidates", [])) != 2):
        raise ValueError("two-work direct receipt differs")
    source, _root, _divisions, plan = prior._source()
    plan_by_id = {item["work_id"]: item for item in plan["works"]}
    policy = {
        "contract": "ocd-openmgh-bsb829-terminal-lines-policy-v1",
        "source_selection": "Complete terminal line of one numbered section or letter; stop before the next lb.",
        "source_envelope": "Twenty-one source divisions; adjacent numbered sections, letters, and collection matter remain in retained XML.",
        "closure_inputs": [ORACLE.as_posix(), CONTRACT.as_posix(), LONG_PATH.as_posix()],
        "forbidden_oracle_imports": ["build.tools.prepare_openmgh_bsb829_terminal_lines"],
        "checks": ["exact-extracted-xml", "terminal-line-completeness", "full-tree-equality",
                   "word-link-closure", "header-license-and-bibliography",
                   "tei-p5-xsd", "work-acquisition-binding"],
    }
    _put_owned(ROOT / POLICY, prior._json(policy), refresh=refresh)
    destination.mkdir(parents=True, exist_ok=True)
    results = []
    for row in direct["candidates"]:
        work_id = row["work_id"]
        entry = plan_by_id[work_id]
        work_path = Path(row["work_sidecar_path"])
        if _sha(ROOT / work_path) != row["work_sidecar_sha256"]:
            raise ValueError(f"work sidecar changed: {work_id}")
        work = json.loads(Path(_io_path(ROOT / work_path)).read_bytes())
        form = work["textual_forms"][0]
        edition = form["editions"][0]
        if len(edition["acquisition_ids"]) != 1:
            raise ValueError(f"ambiguous acquisition: {work_id}")
        acquisition_id = edition["acquisition_ids"][0]
        acquisition = (Path("library/works") / work_id / "forms" /
                       form["textual_form_id"] / "editions" / edition["edition_id"] /
                       "acquisitions" / f"{acquisition_id}.json")
        record = json.loads(Path(_io_path(ROOT / acquisition)).read_bytes())
        if (record["source_path"] != prior.SOURCE.as_posix()
                or record["source_sha256"] != prior.SOURCE_SHA
                or record["source_bytes"] != len(source)):
            raise ValueError(f"source acquisition changed: {work_id}")
        home = HOME / work_id
        boundary = {
            "contract": "ocd-openmgh-bsb829-terminal-lines-boundary-v1",
            "work_id": work_id, "source_path": prior.SOURCE.as_posix(),
            "source_sha256": prior.SOURCE_SHA,
            "declared_locator_ids": row["declared_locator_ids"],
            **{key: row[key] for key in (
                "division", "first_id", "last_line_id", "next_line_id",
                "first_child_index", "last_line_child_index",
                "last_selected_child_index", "next_line_child_index",
                "terminal_word_ids", "scope_note", "selection_c14n_sha256",
            )},
            "next_line_disposition": "Boundary marker for the next section or letter; excluded from this work.",
            "zip_disposition": "Acquisition package only; extracted XML is text authority.",
        }
        boundary_path = home / "boundary-review.json"
        _put_owned(ROOT / boundary_path, prior._json(boundary), refresh=refresh)
        profile = {
            "contract": "ocd-openmgh-bsb829-terminal-lines-profile-v1",
            "work_id": work_id, "work_title": work["title"],
            "edition_id": edition["edition_id"], "acquisition_id": acquisition_id,
            "acquisition_path": acquisition.as_posix(), "acquisition_sha256": _sha(ROOT / acquisition),
            "source_path": prior.SOURCE.as_posix(), "source_sha256": prior.SOURCE_SHA,
            "selection_plan_sha256": prior.PLAN_SHA,
            "candidate_sha256": row["candidate_sha256"],
            "declared_locator_ids": row["declared_locator_ids"],
            **{key: entry[key] for key in (
                "division", "first_id", "last_line_id", "next_line_id",
                "first_child_index", "last_line_child_index",
                "last_selected_child_index", "next_line_child_index",
                "terminal_word_ids", "scope_note",
            )},
            "selection_c14n_sha256": row["selection_c14n_sha256"],
        }
        profile_path = home / "reconstruction-profile.json"
        _put_owned(ROOT / profile_path, prior._json(profile), refresh=refresh)
        closure = prior._json([
            {"path": path.as_posix(), "sha256": _sha(ROOT / path)}
            for path in (ORACLE, CONTRACT, LONG_PATH)
        ])
        manifest = {
            "contract": "ocd-source-manifest-v1",
            "source_id": f"{work_id}-openmgh-bsb829-terminal-lines-electronic-v1",
            "authorities": [
                _authority("extracted-xml", prior.SOURCE, "primary-source"),
                _authority("work-sidecar", work_path, "work-identity-sidecar"),
                _authority("boundary-review", boundary_path, "inspected-terminal-line-boundary"),
                _authority("selection-plan", prior.PLAN, "reviewed-terminal-line-plan"),
                _authority("reconstruction-profile", profile_path, "complete-source-feature-profile"),
                _authority("validation-policy", POLICY, "independent-validation-policy"),
                _authority("tei-p5-xsd", XSD, "tei-validation-schema"),
                _authority("candidate-package-schema", SCHEMA, "candidate-package-schema"),
            ],
            "converter": {
                "id": "ocd-openmgh-bsb829-terminal-lines-to-tei", "version": "1",
                "callable": "_convert", "implementation_path": PRODUCER.as_posix(),
                "implementation_sha256": _sha(ROOT / PRODUCER),
            },
            "validator": {
                "id": "ocd-openmgh-bsb829-terminal-lines-source-oracle", "version": "1",
                "callable": "_oracle", "implementation_path": ORACLE.as_posix(),
                "implementation_sha256": _sha(ROOT / ORACLE),
                "import_closure_sha256": sha256(closure).hexdigest(),
            },
            "package_schema": {"path": SCHEMA.as_posix(), "sha256": _sha(ROOT / SCHEMA)},
        }
        manifest_path = home / "source-manifest.json"
        _put_owned(ROOT / manifest_path, prior._json(manifest), refresh=refresh)
        SourceManifest.load(ROOT / manifest_path, repository_root=ROOT)
        package_root = destination / work_id
        process = subprocess.run([
            sys.executable, "-m", "build.tools.reconstruct_candidate",
            "--manifest", manifest_path.as_posix(), "--destination", str(package_root),
            "--repository-root", str(ROOT),
        ], cwd=ROOT, capture_output=True, text=True, check=True)
        if not process.stdout.strip():
            raise ValueError(f"candidate command gave no receipt: {work_id}")
        package = CandidatePackage.load(package_root / "package")
        validation = json.loads((package_root / "validation.json").read_bytes())
        if (validation.get("status") != "pass" or validation.get("findings")
                or _sha(package_root / "package/content.tei.xml") != row["candidate_sha256"]):
            raise ValueError(f"reconstructed package differs: {work_id}")
        results.append({
            "work_id": work_id, "manifest_path": manifest_path.as_posix(),
            "manifest_sha256": _sha(ROOT / manifest_path),
            "profile_path": profile_path.as_posix(), "profile_sha256": _sha(ROOT / profile_path),
            "boundary_path": boundary_path.as_posix(),
            "boundary_sha256": _sha(ROOT / boundary_path),
            "work_sidecar_sha256": row["work_sidecar_sha256"],
            "acquisition_path": acquisition.as_posix(),
            "acquisition_sha256": _sha(ROOT / acquisition),
            "package_root": package_root.as_posix(), "package_sha256": package.sha256,
            "candidate_tei_sha256": row["candidate_sha256"],
            "validation_sha256": _sha(package_root / "validation.json"),
            "category": "prose", "language": "la",
        })
    receipt = {
        "contract": "ocd-openmgh-bsb829-terminal-lines-packages-v1",
        "status": "nonaccepted", "source_path": prior.SOURCE.as_posix(),
        "source_sha256": prior.SOURCE_SHA,
        "direct_receipt_path": direct_receipt.as_posix(),
        "direct_receipt_sha256": _sha(direct_receipt),
        "frozen_batch_sha256": prior.BATCH_SHA,
        "selection_plan_sha256": prior.PLAN_SHA,
        "works": results, "canonical_install": "not-performed",
    }
    prior._write_once(destination / "receipt.json", prior._json(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-receipt", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true",
                        help="refresh only this route's generated source sidecars")
    args = parser.parse_args()
    result = prepare(args.direct_receipt, args.destination, refresh=args.refresh)
    print(json.dumps({"packages": len(result["works"]),
                      "receipt": str(args.destination / "receipt.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
