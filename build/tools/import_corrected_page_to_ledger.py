"""Import corrected-page machine releases into the decision ledger."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.canonical_token import canonical_token_id, edition_position_ordinal  # noqa: E402
from build.lib.decision_store import DecisionStore  # noqa: E402
from build.lib.edition_page_key import body_edition_key  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402


WORK_ID = "jewish-encyclopedia.vol_02"
VOLUME_ID = "vol_02"
VOLUME = 2
CORPUS_SLUG = "jewish-encyclopedia"
THRESHOLDS_FILE_ID = "prompts/je-measurement-thresholds.json"
CORRECTED_PAGES_DIR = REPO_ROOT / "reports" / "je-corrected" / VOLUME_ID
IA_MANIFEST_PATH = REPO_ROOT / "raw" / "jewish-encyclopedia" / "ia-pages" / f"{VOLUME_ID}.manifest.json"


@dataclass(frozen=True)
class ImportResult:
    accepted_count: int
    imported_count: int
    skipped_existing_count: int
    routed_count: int
    first_event_id: str | None
    store_path: Path


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _page_files(corrected_pages_dir: Path) -> list[Path]:
    return sorted(corrected_pages_dir.glob("page_*.json"))


def _bare_sha(sha: str) -> str:
    return sha.removeprefix("sha256:")


def _page_num_by_bare_sha(ia_manifest: Mapping[str, Any]) -> dict[str, int]:
    pages = ia_manifest.get("pages")
    if not isinstance(pages, list):
        raise ValueError("IA manifest is missing pages[]")
    mapping: dict[str, int] = {}
    for page in pages:
        sha = page.get("sha256")
        page_num = page.get("page_num")
        if not isinstance(sha, str) or not isinstance(page_num, int):
            raise ValueError(f"Malformed IA manifest page: {page!r}")
        mapping[_bare_sha(sha)] = page_num
    return mapping


def _edition_key_for_wct_page(
    wct_page: Mapping[str, Any],
    ia_manifest: Mapping[str, Any],
) -> dict[str, int | str]:
    source_image = wct_page.get("source_image")
    if not isinstance(source_image, Mapping):
        raise ValueError(f"{wct_page.get('page_id')}: missing source_image")
    sha = source_image.get("sha256")
    if not isinstance(sha, str):
        raise ValueError(f"{wct_page.get('page_id')}: missing source_image.sha256")
    page_num = _page_num_by_bare_sha(ia_manifest).get(_bare_sha(sha))
    if page_num is None:
        raise ValueError(f"{wct_page.get('page_id')}: source image sha not found in IA manifest")
    return body_edition_key(page_num)


def resolve_canonical_token_id(
    *,
    corrected_page: Mapping[str, Any],
    position: Mapping[str, Any],
    wct_page: Mapping[str, Any],
    ia_manifest: Mapping[str, Any],
) -> str:
    position_id = position.get("position_id")
    if not isinstance(position_id, str):
        raise ValueError(f"{corrected_page.get('page_id')}: corrected position missing position_id")
    ordinal = edition_position_ordinal(wct_page, position_id)
    if ordinal is None:
        raise ValueError(f"{corrected_page.get('page_id')} {position_id}: not in WCT reading_order")
    return canonical_token_id(
        str(corrected_page["work_id"]),
        str(corrected_page["volume_id"]),
        _edition_key_for_wct_page(wct_page, ia_manifest),
        ordinal,
    )


def _chosen_reading(position: Mapping[str, Any]) -> Mapping[str, Any]:
    index = position.get("chosen_reading_index")
    readings = position.get("derivable_readings")
    if not isinstance(index, int) or not isinstance(readings, list):
        raise ValueError(f"{position.get('position_id')}: accepted position missing chosen reading")
    try:
        reading = readings[index]
    except IndexError as exc:
        raise ValueError(f"{position.get('position_id')}: chosen_reading_index out of range") from exc
    if not isinstance(reading, Mapping):
        raise ValueError(f"{position.get('position_id')}: chosen reading is not an object")
    return reading


def _machine_release_event(
    *,
    corrected_page: Mapping[str, Any],
    position: Mapping[str, Any],
    wct_page: Mapping[str, Any],
    ia_manifest: Mapping[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    reading = _chosen_reading(position)
    wct_sha = wct_page["source_image"]["sha256"]
    return {
        "schema_version": "decision-event-v1",
        "event_id": str(position["decision_event_id"]),
        "event_type": "machine_release",
        "event_category": "authority_decision",
        "volume": VOLUME,
        "canonical_token_id": resolve_canonical_token_id(
            corrected_page=corrected_page,
            position=position,
            wct_page=wct_page,
            ia_manifest=ia_manifest,
        ),
        "structural_path_at_decision": str(position["position_id"]),
        "previous_status_at_view": "unresolved",
        "new_status": "consensus",
        "status_authority": "consensus",
        "evidence_seen": {
            "wct_page_sha256": _bare_sha(str(wct_sha)),
            "chosen_candidate_text": str(reading["text"]),
            "thresholds_file_id": THRESHOLDS_FILE_ID,
        },
        "decision_extras_carried": {
            "origin_kind": str(reading["origin_kind"]),
            "derivation_method": position.get("derivation_method"),
            "chosen_action": str(position["chosen_action"]),
            "chosen_reading_index": position.get("chosen_reading_index"),
        },
        "measurement_eligible": False,
        "actor_id": "system:corrector",
        "timestamp": timestamp,
    }


def iter_machine_release_events(
    *,
    base_dir: Path,
    corrected_pages_dir: Path,
    ia_manifest: Mapping[str, Any],
    timestamp: str,
    work_id: str,
    volume_id: str,
) -> Iterable[tuple[dict[str, Any], int]]:
    for corrected_path in _page_files(corrected_pages_dir):
        corrected_page = _read_json(corrected_path)
        if corrected_page.get("work_id") != work_id or corrected_page.get("volume_id") != volume_id:
            raise ValueError(f"{corrected_path}: unexpected work_id/volume_id")
        source_wct = corrected_page.get("source_wct_page")
        if not isinstance(source_wct, Mapping) or not isinstance(source_wct.get("path"), str):
            raise ValueError(f"{corrected_path}: missing source_wct_page.path")
        wct_page = _read_json(base_dir / source_wct["path"])
        for position in corrected_page["positions"]:
            if position.get("chosen_action") != "release_accepted":
                yield {}, 1
                continue
            yield (
                _machine_release_event(
                    corrected_page=corrected_page,
                    position=position,
                    wct_page=wct_page,
                    ia_manifest=ia_manifest,
                    timestamp=timestamp,
                ),
                0,
            )


def import_corrected_pages(
    *,
    base_dir: Path = REPO_ROOT,
    corrected_pages_dir: Path = CORRECTED_PAGES_DIR,
    decisions_base_dir: Path = REPO_ROOT,
    work_id: str = WORK_ID,
    volume_id: str = VOLUME_ID,
    volume: int = VOLUME,
) -> ImportResult:
    ia_manifest = _read_json(IA_MANIFEST_PATH)
    store = DecisionStore(
        base_dir=decisions_base_dir,
        volume=volume,
        corpus_slug=CORPUS_SLUG,
        volume_id=volume_id,
    )
    existing_ids = {event["event_id"] for event in store.fold()}
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    events_to_append: list[dict[str, Any]] = []
    accepted_count = 0
    routed_count = 0
    skipped_existing_count = 0
    first_event_id: str | None = None

    for event, routed_increment in iter_machine_release_events(
        base_dir=base_dir,
        corrected_pages_dir=corrected_pages_dir,
        ia_manifest=ia_manifest,
        timestamp=timestamp,
        work_id=work_id,
        volume_id=volume_id,
    ):
        routed_count += routed_increment
        if not event:
            continue
        accepted_count += 1
        if first_event_id is None:
            first_event_id = event["event_id"]
        if event["event_id"] in existing_ids:
            skipped_existing_count += 1
            continue
        events_to_append.append(event)
        existing_ids.add(event["event_id"])

    store.append_many(
        events_to_append,
        preserve_event_id=True,
        enforce_ratification_context=True,
    )
    events = store.fold()
    round_trip_machine_releases(
        base_dir=base_dir,
        corrected_pages_dir=corrected_pages_dir,
        events=events,
        work_id=work_id,
        volume_id=volume_id,
    )
    return ImportResult(
        accepted_count=accepted_count,
        imported_count=len(events_to_append),
        skipped_existing_count=skipped_existing_count,
        routed_count=routed_count,
        first_event_id=first_event_id,
        store_path=store.store_path,
    )


def round_trip_machine_releases(
    *,
    base_dir: Path,
    corrected_pages_dir: Path,
    events: Sequence[Mapping[str, Any]],
    work_id: str,
    volume_id: str,
) -> None:
    ia_manifest = _read_json(IA_MANIFEST_PATH)
    by_token = {
        event["canonical_token_id"]: event
        for event in events
        if event.get("event_type") == "machine_release"
    }
    for corrected_path in _page_files(corrected_pages_dir):
        corrected_page = _read_json(corrected_path)
        if corrected_page.get("work_id") != work_id or corrected_page.get("volume_id") != volume_id:
            raise ValueError(f"{corrected_path}: unexpected work_id/volume_id")
        wct_page = _read_json(base_dir / corrected_page["source_wct_page"]["path"])
        for position in corrected_page["positions"]:
            if position.get("chosen_action") != "release_accepted":
                continue
            token_id = resolve_canonical_token_id(
                corrected_page=corrected_page,
                position=position,
                wct_page=wct_page,
                ia_manifest=ia_manifest,
            )
            event = by_token.get(token_id)
            if event is None:
                raise ValueError(f"{corrected_path} {position['position_id']}: missing ledger event")
            reading = _chosen_reading(position)
            evidence_seen = event.get("evidence_seen", {})
            extras = event.get("decision_extras_carried", {})
            expected = {
                "text": reading["text"],
                "origin_kind": reading["origin_kind"],
                "derivation_method": position.get("derivation_method"),
            }
            actual = {
                "text": evidence_seen.get("chosen_candidate_text"),
                "origin_kind": extras.get("origin_kind"),
                "derivation_method": extras.get("derivation_method"),
            }
            if actual != expected:
                raise ValueError(
                    f"{corrected_path} {position['position_id']}: round-trip mismatch "
                    f"expected {expected!r}, got {actual!r}"
                )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=REPO_ROOT)
    parser.add_argument("--corrected-pages-dir", type=Path, default=CORRECTED_PAGES_DIR)
    parser.add_argument("--decisions-base-dir", type=Path, default=REPO_ROOT)
    parser.add_argument("--work-id", default=WORK_ID)
    parser.add_argument("--volume-id", default=VOLUME_ID)
    parser.add_argument("--volume", type=int, default=VOLUME)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = import_corrected_pages(
        base_dir=args.base_dir,
        corrected_pages_dir=args.corrected_pages_dir,
        decisions_base_dir=args.decisions_base_dir,
        work_id=args.work_id,
        volume_id=args.volume_id,
        volume=args.volume,
    )
    print(
        json.dumps(
            {
                "accepted_count": result.accepted_count,
                "imported_count": result.imported_count,
                "skipped_existing_count": result.skipped_existing_count,
                "routed_count": result.routed_count,
                "store_path": str(result.store_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
