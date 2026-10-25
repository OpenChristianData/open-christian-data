"""Resolve private editorial decisions against current library authorities."""
from __future__ import annotations

import hashlib
from contextvars import ContextVar
from pathlib import Path

import jsonschema

from ocd_kernel.lib.storage_topology import repository_relative_path, resolve_repo_path, storage_read_phase
from ocd_kernel.library._common import PipelineError, inspection_read_phase, io_glob, io_path, load_json
from ocd_kernel.library.identities import discover_library
from ocd_kernel.library.record_read import RecordRead
from ocd_kernel.library.rights import collect_rights
from ocd_kernel.release.notices import notice_texts_for_item
from ocd_kernel.release.rights import require_release_rights
from ocd_kernel.release.selection import validate_release_selection, validate_work_cohort


CONTRACT = "ocd-publication-profile-v1"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas/v2/publication-profile.schema.json"
PENDING_REASON = "Private pending explicit publication profile disposition"
_file_cache: ContextVar[dict | None] = ContextVar("publication_profile_file_bindings", default=None)


def _file(root: Path, reference: str) -> dict:
    cache = _file_cache.get()
    key = (root, reference)
    if cache is not None and key in cache:
        return dict(cache[key][1])
    path = resolve_repo_path(root, reference)
    digest = hashlib.sha256()
    try:
        observed = io_path(path).stat()
        stamp = (str(path), observed.st_size, observed.st_mtime_ns, observed.st_ctime_ns)
        with io_path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        observed = io_path(path).stat()
        if stamp != (str(path), observed.st_size, observed.st_mtime_ns, observed.st_ctime_ns):
            raise PipelineError(f"publication input changed during hashing: {reference}")
    except OSError as exc:
        raise PipelineError(f"publication input unavailable: {reference}: {exc}") from exc
    binding = {"path": reference, "sha256": digest.hexdigest()}
    if cache is not None:
        cache[key] = (stamp, binding)
    return binding


def load_publication_profile(path: Path) -> dict:
    value = load_json(path)
    schema = load_json(SCHEMA_PATH)
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(value),
                    key=lambda error: str(error.path))
    if errors:
        raise PipelineError(f"publication profile schema: {errors[0].json_path}: {errors[0].message}")
    works = {entry["work_id"]: entry for entry in value["works"]}
    items = {entry["item_id"]: entry for entry in value["items"]}
    if len({key.casefold() for key in works}) != len(value["works"]):
        raise PipelineError("duplicate publication profile work_id")
    if len({key.casefold() for key in items}) != len(value["items"]):
        raise PipelineError("duplicate publication profile item_id")
    for item in items.values():
        if item["item_id"] != f'{item["work_id"]}--{item["edition_id"]}':
            raise PipelineError(f'publication profile item identity differs: {item["item_id"]}')
        if item["work_id"] not in works or works[item["work_id"]]["disposition"] != "cohort":
            raise PipelineError(f'publication profile item outside cohort: {item["item_id"]}')
    return value


def _rights_selection(root: Path, item: dict, identity: dict) -> tuple[dict, dict]:
    read = RecordRead(root)
    rights = collect_rights(read, identity["work_id"], identity["textual_form_id"], identity["edition_id"])
    if rights["health"] != "valid":
        raise PipelineError(f'{item["item_id"]}: invalid normalized rights: {rights["issues"]}')
    candidates = [finding for finding in rights["records"]
                  if finding["record"]["scope"] == "selected-text"
                  and finding["record"]["rights_status"] in ("public-domain", "licensed", "mixed")
                  and finding["normalization"] is not None
                  and finding["normalization"].get("item_id") == item["item_id"]]
    if not candidates:
        raise PipelineError(f'{item["item_id"]}: no current reviewed rights normalization')
    choices = [{"license": entry["normalization"].get("effective_license"),
                "public_notices": entry["normalization"].get("public_notices", [])}
               for entry in candidates]
    if any(choice != choices[0] for choice in choices):
        raise PipelineError(f'{item["item_id"]}: ambiguous normalized license or notices')
    selected = dict(item)
    if choices[0]["license"] is not None:
        selected["license"] = choices[0]["license"]
    if choices[0]["public_notices"]:
        selected["public_notices"] = choices[0]["public_notices"]
    subjects = {entry["subject_id"]: entry for entry in rights["subjects"]}
    subject = subjects[candidates[0]["record"]["subject"]["id"]]
    include, exclude = subject["public_scope"]["include"], subject["public_scope"]["exclude"]
    if any(selector["kind"] != "record-id" for selector in include + exclude):
        raise PipelineError(f'{item["item_id"]}: rights require explicit public record IDs')
    included = {identifier for selector in include for identifier in selector["values"]}
    omitted = {identifier for selector in exclude for identifier in selector["values"]}
    require_release_rights(root, selected, identity,
                           [{"record_id": identifier} for identifier in sorted(included - omitted)])
    notice_texts_for_item(root, selected, resolve_repo_path(root, selected["acceptance_path"]))
    if not read.stable():
        raise PipelineError(f'{item["item_id"]}: rights changed during profile resolution')
    return selected, {"files": [{"path": key, "sha256": record["sha256"]}
                                for key, record in sorted(read.inputs.items())],
                      "discovery": sorted(read.discovery.values(), key=lambda entry: entry["path"])}


def _source_files(root: Path, acceptance: dict, edition) -> list[dict]:
    """Bind declared retained members and recursively referenced source manifests."""
    files: dict[str, dict] = {}
    manifests: set[str] = set()

    def visit(value, *, manifest: bool = False) -> None:
        if isinstance(value, list):
            for member in value:
                visit(member, manifest=manifest)
        elif isinstance(value, dict):
            for key, member in value.items():
                if key in ("path", "source_path") and isinstance(member, str):
                    reference = member.partition("#")[0]
                    if reference not in files:
                        files[reference] = _file(root, reference)
                    expected = value.get("sha256") if key == "path" else value.get("source_sha256")
                    if expected is not None and files[reference]["sha256"] != expected:
                        raise PipelineError(f"declared source SHA-256 differs: {reference}")
                    if reference not in manifests and (manifest or "/acquisitions/" in reference or "manifest" in Path(reference).name) and reference.endswith(".json"):
                        manifests.add(reference)
                        visit(load_json(resolve_repo_path(root, reference)))
                else:
                    visit(member, manifest=key in ("source_manifest", "dependencies", "manifest"))

    visit(acceptance.get("source", {}))
    visit(acceptance.get("scope", {}))
    acquisition_root = edition.path.parent / "acquisitions"
    for acquisition_id in edition.record.get("acquisition_ids", []):
        reference = repository_relative_path(root, acquisition_root / f"{acquisition_id}.json")
        files[reference] = _file(root, reference)
        visit(load_json(resolve_repo_path(root, reference)))
    return sorted(files.values(), key=lambda entry: entry["path"])


def resolve_publication_profile(root: Path, *, profile_path: Path, release_id: str) -> tuple[dict, dict]:
    """Return an existing-format selection plus uncached current input bindings."""
    token = _file_cache.set({})
    try:
        with inspection_read_phase(), storage_read_phase():
            result = _resolve_publication_profile(root, profile_path=profile_path, release_id=release_id)
            for (authority_root, reference), (stamp, _binding) in _file_cache.get().items():
                path = resolve_repo_path(authority_root, reference)
                observed = io_path(path).stat()
                if stamp != (str(path), observed.st_size, observed.st_mtime_ns, observed.st_ctime_ns):
                    raise PipelineError(f"publication input changed during resolution: {reference}")
            return result
    finally:
        _file_cache.reset(token)


def _resolve_publication_profile(root: Path, *, profile_path: Path, release_id: str) -> tuple[dict, dict]:
    root = Path(root).resolve(strict=True)
    profile_path = Path(profile_path)
    if not profile_path.is_absolute():
        profile_path = root / profile_path
    profile_binding = _file(root, repository_relative_path(root, profile_path))
    profile = load_publication_profile(profile_path)
    if profile_binding != _file(root, profile_binding["path"]):
        raise PipelineError("publication profile changed during resolution")
    works = discover_library(root)
    work_decisions = {entry["work_id"]: entry for entry in profile["works"]}
    item_decisions = {entry["item_id"]: entry for entry in profile["items"]}
    missing_works = set(work_decisions) - {work.work_id for work in works}
    if missing_works:
        raise PipelineError(f"profile work identities disappeared: {sorted(missing_works)}")
    items, bindings, work_bindings, pending = [], [], [], []
    included, excluded, inventory = [], [], []
    observed_items = set()
    for work in works:
        decision = work_decisions.get(work.work_id)
        state_path = work.path.with_name("state.json")
        state = load_json(state_path)
        if state.get("work_id") != work.work_id:
            raise PipelineError(f"state identity differs from work: {state_path}")
        common = [_file(root, repository_relative_path(root, path)) for path in (work.path, state_path)]
        work_bindings.append({"work_id": work.work_id, "files": common})
        inventory.append({"work_id": work.work_id, "editions": [
            {"textual_form_id": edition.textual_form_id, "edition_id": edition.edition_id}
            for edition in work.editions]})
        if decision is None or decision["disposition"] == "private":
            reason = PENDING_REASON if decision is None else decision["reason"]
            excluded.append({"work_id": work.work_id, "reason": reason})
            if decision is None:
                pending.append({"work_id": work.work_id, "reason": reason})
            continue
        included.append(work.work_id)
        categories = {entry["textual_form_id"]: entry.get("category")
                      for entry in work.record.get("textual_forms", [])}
        for edition in work.editions:
            item_id = f"{work.work_id}--{edition.edition_id}"
            item_decision = item_decisions.get(item_id)
            observed_items.add(item_id)
            acceptance_path = edition.path.with_name("acceptance.json")
            acceptance_relative = repository_relative_path(root, acceptance_path)
            if item_decision is not None and item_decision["textual_form_id"] != edition.textual_form_id:
                raise PipelineError(f"profile textual form identity differs: {item_id}")
            held = decision.get("hold_reason") or (item_decision or {}).get("reason")
            if item_decision is None:
                pending.append({"item_id": item_id, "reason": held or PENDING_REASON,
                                "disposition": "private" if held else "pending"})
                continue
            if not io_path(acceptance_path).is_file():
                raise PipelineError(f"profile item acceptance unavailable: {item_id}")
            acceptance = load_json(acceptance_path)
            if acceptance.get("promotion", {}).get("status") != "promoted":
                raise PipelineError(f"profile item is not promoted accepted text: {item_id}")
            identity = acceptance["identity"]
            if any(identity.get(key) != value for key, value in (
                ("work_id", work.work_id), ("textual_form_id", edition.textual_form_id),
                ("edition_id", edition.edition_id))) or identity.get("acquisition_id") not in edition.record.get("acquisition_ids", []):
                raise PipelineError(f"promoted acceptance differs from declared edition: {item_id}")
            master = _file(root, repository_relative_path(root, edition.path))
            if master["sha256"] != acceptance["promotion"]["master"]["sha256"]:
                raise PipelineError(f"promoted master SHA-256 differs: {item_id}")
            target = next((entry for entry in state.get("targets", []) if entry.get("target_type") == "edition"
                           and entry.get("target_id") == edition.edition_id), None)
            if not target or target.get("stage") != "accepted" or not {master["path"], acceptance_relative} <= set(target.get("evidence", [])):
                raise PipelineError(f"profile item state is not accepted with evidence: {item_id}")
            category = edition.record.get("category") or categories.get(edition.textual_form_id)
            if category is None and held and item_decision and item_decision.get("category") == "unassigned":
                category = "unassigned"
            if not isinstance(category, str) or not category:
                raise PipelineError(f"promoted edition has no exact category: {item_id}")
            category = {"doctrinal-documents": "doctrinal_documents", "reference-entries": "reference_entries",
                        "topical-indexes": "topical_indexes"}.get(category, category)
            item = {"item_id": item_id, "work_id": work.work_id, "category": category,
                    "acceptance_path": acceptance_relative}
            files = common + [master, _file(root, acceptance_relative)]
            discovery = []
            if held:
                item["exclude_reason"] = held
            else:
                # Rights can bind large historical receipts; release their bytes per edition.
                with inspection_read_phase():
                    item, rights = _rights_selection(root, item, identity)
                files += rights["files"] + _source_files(root, acceptance, edition)
                discovery = rights["discovery"]
                for notice in item.get("public_notices", []):
                    files += [_file(root, notice[key]) for key in ("source_path", "notice_path")]
            items.append(item)
            bindings.append({"item_id": item_id, "files": sorted(
                {entry["path"]: entry for entry in files}.values(), key=lambda entry: entry["path"]),
                "discovery": discovery})
    vanished = set(item_decisions) - observed_items
    if vanished:
        raise PipelineError(f"profile item identities disappeared: {sorted(vanished)}")
    declared_acceptances = {edition.path.with_name("acceptance.json") for work in works for edition in work.editions}
    orphaned = set(io_glob(root / "library/works", "*/forms/*/editions/*/acceptance.json")) - declared_acceptances
    if orphaned:
        raise PipelineError(f"acceptance outside declared edition: {sorted(orphaned)}")
    selection = validate_release_selection({"schema_version": "2.0", "release_id": release_id,
        "items": items, "work_coverage": {"included_work_ids": included, "excluded_works": excluded}})
    validate_work_cohort(root, selection)
    return selection, {"contract": "ocd-profile-derivation-v1", "profile": profile_binding,
        "canonical_works": len(works), "included_works": len(included), "excluded_works": len(excluded),
        "excluded_ocr_works": sum(entry["reason"] == "OCR / Outside Publishing Scope" for entry in excluded),
        "selected_text_items": sum("exclude_reason" not in item for item in items),
        "excluded_text_items": sum("exclude_reason" in item for item in items),
        "pending_private": pending, "inventory": inventory, "work_bindings": work_bindings,
        "item_bindings": sorted(bindings, key=lambda entry: entry["item_id"])}
