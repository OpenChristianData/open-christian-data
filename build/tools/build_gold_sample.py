"""Build a B7 gold sample manifest from S1 sidecar records."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.atomic_io import AtomicWriteError, write_json_atomic  # noqa: E402
from build.lib.gold_strata import (  # noqa: E402
    DOMINANT_FAILURE_MIN,
    MIN_PER_OBSERVED_VALUE,
    STRATA_CONTRACT,
    STRATA_DIMENSIONS,
    derive_page_strata,
    enumerate_observed_values,
    select_stratified_sample,
)
from build.lib.ocr_store_paths import S1_SIDECARS_ROOT  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

SAMPLE_ROLE_DOMINANT_FAILURE = "dominant_failure"
SAMPLE_ROLE_CALIBRATION = "calibration"
SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "gold-sample-manifest-v1.schema.json"
DEFAULT_SIDECAR_ROOT = S1_SIDECARS_ROOT


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_page_path(manifest_path: Path, sidecar_page_path: str) -> Path:
    repo_path = REPO_ROOT / sidecar_page_path
    if repo_path.exists():
        return repo_path
    local_path = manifest_path.parent / sidecar_page_path
    if local_path.exists():
        return local_path
    return repo_path


def _find_sidecar_manifests(sidecar_root: Path, volume: int) -> list[tuple[Path, dict[str, Any]]]:
    manifests: list[tuple[Path, dict[str, Any]]] = []
    if not sidecar_root.exists():
        return manifests
    for path in sorted(sidecar_root.rglob("*.json")):
        try:
            payload = _load_json(path)
        except json.JSONDecodeError:
            continue
        if payload.get("schema_version") != "sidecar-manifest-v1":
            continue
        if payload.get("volume") != volume:
            continue
        manifests.append((path, payload))
    return manifests


def load_page_strata_records(sidecar_root: Path, volume: int) -> list[dict[str, Any]]:
    manifests = _find_sidecar_manifests(sidecar_root, volume)
    if not manifests:
        raise FileNotFoundError(f"no sidecar manifests found for volume {volume} under {sidecar_root}")

    grouped: dict[tuple[int, str], dict[str, Any]] = {}
    for manifest_path, manifest in manifests:
        engine_family = str(manifest["engine_family"])
        for page_ref in manifest.get("pages", []):
            if not isinstance(page_ref, Mapping):
                continue
            if page_ref.get("status") not in {"eligible", "diagnostic_only"}:
                continue
            sidecar_page_path = page_ref.get("sidecar_page_path")
            if not isinstance(sidecar_page_path, str):
                continue
            page_path = _resolve_page_path(manifest_path, sidecar_page_path)
            if not page_path.exists():
                raise FileNotFoundError(f"sidecar page is missing: {sidecar_page_path}")
            page = _load_json(page_path)
            # R4b cross-engine grouping key. Post-R3-apply the body filename stem is
            # consistent across engines for a physical page, so (page_sequence,
            # page_native_id) groups them correctly. TODO(R7): switch to
            # canonical_leaf_id once the ABBYY + azure lanes carry it -- grouping on
            # the leaf NOW would split the leaf-keyed primary engines (tesseract /
            # kraken / surya) from the still-filename-keyed abbyy / azure_read pages
            # of the same physical page. Tracked with the ABBYY geometry lane R7 closes.
            key = (int(page_ref["page_sequence"]), str(page_ref["page_native_id"]))
            group = grouped.setdefault(
                key,
                {
                    "paths": [],
                    "pages_by_engine": {},
                },
            )
            group["paths"].append(sidecar_page_path if "\\" not in sidecar_page_path else _relative_to_repo(page_path))
            group["pages_by_engine"][engine_family] = page

    records: list[dict[str, Any]] = []
    for _key, group in sorted(grouped.items()):
        page_path = sorted(group["paths"])[0]
        records.append(
            {
                "page_path": page_path,
                "strata": derive_page_strata(group["pages_by_engine"]),
            }
        )
    if not records:
        raise FileNotFoundError(f"no eligible sidecar pages found for volume {volume} under {sidecar_root}")
    return records


def strata_definition(all_page_strata: list[dict[str, Any]]) -> dict[str, Any]:
    observed = enumerate_observed_values(all_page_strata)
    dimensions: list[dict[str, Any]] = []
    for dimension in STRATA_DIMENSIONS:
        buckets = list(dimension.buckets)
        if dimension.name == "engine_family_set":
            buckets = [
                "+".join(value) if isinstance(value, (list, tuple)) else str(value)
                for value in sorted(observed.get(dimension.name, set()), key=lambda item: str(item))
            ]
        dimensions.append(
            {
                "name": dimension.name,
                "source": dimension.source,
                "availability": dimension.availability,
                "buckets": buckets,
            }
        )
    return {"dimensions": dimensions}


def sample_result_to_manifest_strata(result: Any) -> list[dict[str, Any]]:
    return [
        {
            "stratum_key": stratum.stratum_key,
            "target_count": stratum.target_count,
            "actual_count": stratum.actual_count,
            "selected_pages": list(stratum.selected_pages),
            "coverage_flag": stratum.coverage_flag,
        }
        for stratum in result.strata
    ]


def build_sample_manifest(
    *,
    sidecar_root: Path,
    volume: int,
    sample_id: str,
    sample_role: str,
    target_total: int,
    min_per_value: int,
    comparison_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records = load_page_strata_records(sidecar_root, volume)
    observed = enumerate_observed_values(records)
    result = select_stratified_sample(
        records,
        observed,
        target_total=target_total,
        min_per_value=min_per_value,
    )
    manifest: dict[str, Any] = {
        "schema_version": "gold-sample-manifest-v1",
        "sample_id": sample_id,
        "volume": volume,
        "sample_role": sample_role,
        "created_at": _utc_now(),
        "strata_definition": strata_definition(records),
        "strata": sample_result_to_manifest_strata(result),
    }
    if comparison_contract is not None:
        manifest["comparison_contract"] = comparison_contract
    return manifest


def _load_manifest_schema() -> dict[str, Any]:
    return _load_json(SCHEMA_PATH)


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    write_json_atomic(path, manifest, _load_manifest_schema())


def default_output_path(volume: int, sample_role: str) -> Path:
    return REPO_ROOT / "reports" / "gold" / f"vol_{volume:02d}" / f"{sample_role}.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar-root", type=Path, default=DEFAULT_SIDECAR_ROOT)
    parser.add_argument("--volume", type=int, default=1)
    parser.add_argument("--sample-id", default="gold-sample-vol01-dominant-failure")
    parser.add_argument(
        "--sample-role",
        choices=(SAMPLE_ROLE_DOMINANT_FAILURE, SAMPLE_ROLE_CALIBRATION),
        default=SAMPLE_ROLE_DOMINANT_FAILURE,
    )
    parser.add_argument("--target-total", type=int, default=DOMINANT_FAILURE_MIN)
    parser.add_argument("--min-per-value", type=int, default=MIN_PER_OBSERVED_VALUE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--write", action="store_true", help="Write the manifest. Default is dry-run.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv or []))
    manifest = build_sample_manifest(
        sidecar_root=args.sidecar_root,
        volume=args.volume,
        sample_id=args.sample_id,
        sample_role=args.sample_role,
        target_total=args.target_total,
        min_per_value=args.min_per_value,
    )
    output = args.output or default_output_path(args.volume, args.sample_role)
    if not args.write:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 0
    try:
        write_manifest(output, manifest)
    except AtomicWriteError as exc:
        print(f"atomic write failed: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
