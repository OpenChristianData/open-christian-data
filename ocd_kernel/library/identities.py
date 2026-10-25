"""Load and validate the stable identity sidecars used by the library.

The work sidecar is deliberately small. It records only the identity hierarchy
and evidence needed to explain why a work belongs in the project. State and
acquisition facts are validated by their own modules and are never folded into a
work record here.
"""

from __future__ import annotations

from ocd_kernel.lib.path_io import io_path, resolve_path, io_glob, io_iterdir

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from ._common import PipelineError, load_json, require_string, safe_identifier, read_input_bytes, _read_inputs


_SCHEMA_ROOT = resolve_path(Path(__file__)).parents[2] / "schemas" / "v2"


def _schema_path(name: str) -> Path:
    if name not in {"work", "state", "acquisition", "acceptance", "library-record", "library-record-links", "lead-migration", "release-selection", "source-metadata", "rights-record", "rights-subject", "metadata-labels"}:
        raise PipelineError(f"unsupported library schema: {name}")
    path = _SCHEMA_ROOT / f"{name}.schema.json"
    if not io_path(path).is_file():
        raise PipelineError(f"missing library schema: {path}")
    return path


def _schema(name: str) -> dict[str, Any]:
    path = _schema_path(name)
    try:
        value = json.loads(read_input_bytes(path).decode("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot load library schema {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"library schema must be an object: {path}")
    return value


def schema_enum(name: str, definition: str) -> tuple[str, ...]:
    """Return an enum from a local schema definition.

    Runtime modules use this for controlled vocabulary checks so a stage value
    cannot silently diverge from the executable schema.
    """

    schema = _schema(name)
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        raise PipelineError(f"{name} schema has no definitions")
    value = definitions.get(definition)
    if not isinstance(value, dict) or not isinstance(value.get("enum"), list):
        raise PipelineError(f"{name} schema definition has no enum: {definition}")
    result = tuple(item for item in value["enum"] if isinstance(item, str))
    if len(result) != len(value["enum"]):
        raise PipelineError(f"{name} schema enum is not a string enum: {definition}")
    return result


def validate_record(
    name: str, record: Mapping[str, Any], *, context: str = "record"
) -> dict[str, Any]:
    """Validate one sidecar against a local closed JSON Schema.

    The schemas intentionally contain only local ``#/$defs`` references. This
    function reads those files from the repository and never resolves a URL or
    performs network I/O.
    """

    if not isinstance(record, dict):
        raise PipelineError(f"{context} must be a JSON object")
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - dependency is required by the package
        raise PipelineError("jsonschema is required for library sidecar validation") from exc

    cache = _read_inputs.get()
    key = ("validator", name)
    validator = cache.get(key) if cache is not None else None
    if validator is None:
        options: dict[str, Any] = {}
        if name == "library-record":
            from referencing import Registry, Resource
            resources = [_schema(kind) for kind in ("work", "state", "acquisition", "acceptance", "source-metadata", "release-selection", "library-record-links")]
            options["registry"] = Registry().with_resources(
                (schema["$id"], Resource.from_contents(schema)) for schema in resources
            )
        validator = jsonschema.Draft202012Validator(
            _schema(name), format_checker=jsonschema.FormatChecker(), **options
        )
        if cache is not None:
            cache[key] = validator
    errors = sorted(validator.iter_errors(record), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(
            f"{context}{error.json_path}: {error.message}" for error in errors[:8]
        )
        if len(errors) > 8:
            details += f"; {len(errors) - 8} more schema errors"
        raise PipelineError(details)
    return dict(record)


def _validate_work_structure(record: Mapping[str, Any], *, context: str) -> None:
    safe_identifier(
        require_string(dict(record), "work_id", context=context), field="work_id"
    )
    forms = record.get("textual_forms")
    if not isinstance(forms, list):
        raise PipelineError(f"{context} textual_forms must be a list")

    seen_forms: set[str] = set()
    seen_editions: dict[str, str] = {}
    seen_acquisitions: dict[str, str] = {}
    for raw_form in forms:
        if not isinstance(raw_form, dict):
            raise PipelineError(f"{context} textual_forms entries must be objects")
        form_id = safe_identifier(
            require_string(raw_form, "textual_form_id", context=context),
            field="textual_form_id",
        )
        if form_id in seen_forms:
            raise PipelineError(f"duplicate textual_form_id in {context}: {form_id}")
        seen_forms.add(form_id)
        editions = raw_form.get("editions")
        if not isinstance(editions, list):
            raise PipelineError(f"{context} form {form_id} editions must be a list")
        for raw_edition in editions:
            if not isinstance(raw_edition, dict):
                raise PipelineError(f"{context} edition entries must be objects")
            edition_id = safe_identifier(
                require_string(raw_edition, "edition_id", context=context),
                field="edition_id",
            )
            prior_form = seen_editions.get(edition_id)
            if prior_form is not None:
                raise PipelineError(
                    f"edition_id collision in {context}: {edition_id} belongs to "
                    f"textual forms {prior_form!r} and {form_id!r}"
                )
            seen_editions[edition_id] = form_id
            acquisition_ids = raw_edition.get("acquisition_ids", [])
            if not isinstance(acquisition_ids, list):
                raise PipelineError(
                    f"{context} edition {edition_id} acquisition_ids must be a list"
                )
            local_acquisitions: set[str] = set()
            for raw_acquisition_id in acquisition_ids:
                if not isinstance(raw_acquisition_id, str):
                    raise PipelineError(
                        f"{context} edition {edition_id} acquisition_ids must be strings"
                    )
                acquisition_id = safe_identifier(raw_acquisition_id, field="acquisition_id")
                if acquisition_id in local_acquisitions:
                    raise PipelineError(
                        f"duplicate acquisition_id in {context} edition {edition_id}: "
                        f"{acquisition_id}"
                    )
                local_acquisitions.add(acquisition_id)
                prior_edition = seen_acquisitions.get(acquisition_id)
                if prior_edition is not None and prior_edition != edition_id:
                    raise PipelineError(
                        f"acquisition_id collision in {context}: {acquisition_id} belongs to "
                        f"editions {prior_edition!r} and {edition_id!r}"
                    )
                seen_acquisitions[acquisition_id] = edition_id


def resolve_edition_language(
    work_record: Mapping[str, Any],
    edition_record: Mapping[str, Any],
    textual_form_id: str,
) -> str | None:
    """Resolve a declared edition's language, then its exact parent form's.

    Records have already passed their owning schema validation. Reject a
    detached or ambiguous parent rather than borrowing another form's language.
    Missing or unsupported values remain unavailable for the caller's category
    check or TEI fallback; work-level language is not part of this contract.
    """

    forms = work_record.get("textual_forms")
    matches = [
        form for form in forms
        if isinstance(form, Mapping) and form.get("textual_form_id") == textual_form_id
    ] if isinstance(forms, list) else []
    if len(matches) != 1:
        raise PipelineError(f"edition language requires one declared textual form: {textual_form_id}")
    form = matches[0]
    editions = form.get("editions")
    declared = [
        edition for edition in editions
        if isinstance(edition, Mapping) and edition.get("edition_id") == edition_record.get("edition_id")
    ] if isinstance(editions, list) else []
    if len(declared) != 1 or declared[0] != edition_record:
        raise PipelineError(
            f"edition language parent mismatch: {textual_form_id}/{edition_record.get('edition_id')}"
        )
    value = edition_record.get("language", form.get("language"))
    return value if isinstance(value, str) and value.strip() else None


@dataclass(frozen=True)
class Edition:
    work_id: str
    textual_form_id: str
    edition_id: str
    title: str
    path: Path
    record: dict[str, Any]


@dataclass(frozen=True)
class Work:
    work_id: str
    title: str
    path: Path
    record: dict[str, Any]
    editions: tuple[Edition, ...]


_edition_lookup_snapshot: ContextVar[dict[Path, tuple[Work, ...]] | None] = ContextVar(
    "edition_lookup_snapshot", default=None
)


@contextmanager
def cached_edition_lookups() -> Iterator[None]:
    """Share one validating catalog discovery within a read-only check phase.

    Callers must end this scope before mutating the library. A later phase gets
    a fresh discovery, including validation of every sibling work.
    """

    token = _edition_lookup_snapshot.set({})
    try:
        yield
    finally:
        _edition_lookup_snapshot.reset(token)


def load_work(path: Path) -> dict[str, Any]:
    """Load one exact v2 ``work.json`` sidecar."""

    record = load_json(path)
    validate_record("work", record, context=str(path))
    _validate_work_structure(record, context=str(path))
    return record


def _forms(record: dict[str, Any], *, path: Path) -> Iterable[tuple[str, dict[str, Any]]]:
    raw_forms = record.get("textual_forms")
    if not isinstance(raw_forms, list):
        raise PipelineError(f"{path} requires textual_forms")
    for raw_form in raw_forms:
        if not isinstance(raw_form, dict):
            raise PipelineError(f"{path} textual_forms entries must be objects")
        form_id = safe_identifier(
            require_string(raw_form, "textual_form_id", context=str(path)),
            field="textual_form_id",
        )
        yield form_id, raw_form


def _editions(
    work_id: str,
    work_path: Path,
    form_id: str,
    form: dict[str, Any],
) -> Iterable[Edition]:
    raw_editions = form.get("editions")
    if not isinstance(raw_editions, list):
        raise PipelineError(f"{work_path} form {form_id} requires editions")
    form_root = work_path.parent / "forms" / form_id / "editions"
    for raw_edition in raw_editions:
        if not isinstance(raw_edition, dict):
            raise PipelineError(f"{work_path} edition entries must be objects")
        edition_id = safe_identifier(
            require_string(raw_edition, "edition_id", context=str(work_path)),
            field="edition_id",
        )
        title = require_string(raw_edition, "title", context=str(work_path))
        yield Edition(
            work_id=work_id,
            textual_form_id=form_id,
            edition_id=edition_id,
            title=title,
            path=form_root / edition_id / "master.tei.xml",
            record=raw_edition,
        )


def load_editions(work_path: Path) -> tuple[Edition, ...]:
    record = load_work(work_path)
    work_id = safe_identifier(record["work_id"], field="work_id")
    editions: list[Edition] = []
    seen: set[str] = set()
    for form_id, form in _forms(record, path=work_path):
        for edition in _editions(work_id, work_path, form_id, form):
            if edition.edition_id in seen:
                raise PipelineError(f"duplicate edition_id across forms: {edition.edition_id}")
            seen.add(edition.edition_id)
            editions.append(edition)
    return tuple(editions)


def _validate_acquisition_layout(
    work_path: Path, *, work: dict[str, Any], editions: tuple[Edition, ...]
) -> None:
    """Reject acquisition sidecars that are orphaned or contradict the work."""

    from .acquisitions import load_acquisition

    form_ids = {
        str(form["textual_form_id"])
        for form in work.get("textual_forms", [])
        if isinstance(form, dict)
    }
    edition_by_path = {
        (edition.textual_form_id, edition.edition_id): edition for edition in editions
    }
    declared: dict[str, str] = {}
    for edition in editions:
        for acquisition_id in edition.record.get("acquisition_ids", []):
            declared[str(acquisition_id)] = edition.edition_id
    actual: dict[str, str] = {}
    forms_root = work_path.parent / "forms"
    if io_path(forms_root).is_dir():
        for sidecar in sorted(
            io_glob(forms_root, "*/editions/*/acquisitions/*.json"),
            key=lambda item: item.as_posix(),
        ):
            form_id = sidecar.parent.parent.parent.parent.name
            edition_id = sidecar.parent.parent.name
            if form_id not in form_ids or (form_id, edition_id) not in edition_by_path:
                raise PipelineError(
                    f"orphan acquisition sidecar under undeclared form or edition: {sidecar}"
                )
            acquisition = load_acquisition(sidecar)
            acquisition_id = str(acquisition["acquisition_id"])
            edition_record = edition_by_path[(form_id, edition_id)].record
            if "acquisition_ids" in edition_record and acquisition_id not in edition_record["acquisition_ids"]:
                raise PipelineError(
                    f"acquisition {acquisition_id} is absent from edition {edition_id}'s declared acquisition_ids"
                )
            if acquisition_id != sidecar.stem:
                raise PipelineError(
                    f"acquisition_id does not match sidecar filename: {sidecar} says "
                    f"{acquisition_id!r}"
                )
            if acquisition["edition_id"] != edition_id:
                raise PipelineError(
                    f"acquisition edition_id does not match directory: {sidecar} says "
                    f"{acquisition['edition_id']!r}, expected {edition_id!r}"
                )
            prior = actual.get(acquisition_id)
            if prior is not None and prior != edition_id:
                raise PipelineError(
                    f"acquisition_id collision below {work_path}: {acquisition_id} belongs to "
                    f"editions {prior!r} and {edition_id!r}"
                )
            actual[acquisition_id] = edition_id
    for acquisition_id, edition_id in declared.items():
        if acquisition_id not in actual:
            raise PipelineError(
                f"declared acquisition_id is missing a sidecar for edition {edition_id}: "
                f"{acquisition_id}"
            )
        if actual[acquisition_id] != edition_id:
            raise PipelineError(
                f"declared acquisition_id points to the wrong edition: {acquisition_id} "
                f"declares {edition_id!r}, sidecar is under {actual[acquisition_id]!r}"
            )


def discover_work(root: Path, work_id: str) -> Work:
    """Load and validate one complete work without scanning its siblings.

    This is for transactions whose authority is explicitly one work. It does
    not establish library-wide work or edition-ID uniqueness; corpus and
    release checks must continue to use :func:`discover_library`.
    """

    root = Path(root)
    work_id = safe_identifier(work_id, field="work_id")
    work_path = root / "library" / "works" / work_id / "work.json"
    record = load_work(work_path)
    recorded_work_id = safe_identifier(record["work_id"], field="work_id")
    if recorded_work_id != work_id:
        raise PipelineError(
            "work sidecar identity does not match directory: "
            f"{recorded_work_id} != {work_id}"
        )
    editions = load_editions(work_path)
    _validate_acquisition_layout(work_path, work=record, editions=editions)
    return Work(
        work_id=work_id,
        title=require_string(record, "title", context=str(work_path)),
        path=work_path,
        record=record,
        editions=editions,
    )


def discover_library(root: Path) -> tuple[Work, ...]:
    """Discover every stable work below ``root/library/works`` in order."""

    root = Path(root)
    works_root = root / "library" / "works"
    if not io_path(works_root).is_dir():
        raise PipelineError(f"missing library work root: {works_root}")
    result: list[Work] = []
    seen: set[str] = set()
    for work_dir in sorted(
        (path for path in io_iterdir(works_root) if io_path(path).is_dir()), key=lambda path: path.name
    ):
        work = discover_work(root, work_dir.name)
        if work.work_id in seen:
            raise PipelineError(f"duplicate work_id: {work.work_id}")
        seen.add(work.work_id)
        result.append(work)
    if not result:
        raise PipelineError(f"library contains no works: {works_root}")
    return tuple(result)


def edition_by_id(
    root: Path, edition_id: str, *, work_id: str | None = None
) -> tuple[Work, Edition]:
    """Resolve an edition, fully validating its work.

    A known work avoids unrelated acquisitions in single-work commands.
    Batch phases retain whole-library validation and ambiguity checks.
    """

    edition_id = safe_identifier(edition_id, field="edition_id")
    if work_id is not None:
        work_id = safe_identifier(work_id, field="work_id")
    snapshot = _edition_lookup_snapshot.get()
    if work_id is not None and snapshot is None:
        works = (discover_work(root, work_id),)
    elif snapshot is None:
        works = discover_library(root)
    else:
        key = resolve_path(Path(root), preserve_prefix=True)
        if key not in snapshot:
            snapshot[key] = discover_library(root)
        works = snapshot[key]
    matches = [
        (work, edition)
        for work in works
        for edition in work.editions
        if edition.edition_id == edition_id
    ]
    if not matches:
        raise PipelineError(f"edition not found: {edition_id}")
    if len(matches) > 1:
        raise PipelineError(f"edition_id is ambiguous: {edition_id}")
    if work_id is not None and matches[0][0].work_id != work_id:
        raise PipelineError(f"edition {edition_id!r} does not belong to work {work_id!r}")
    return matches[0]


def immutable_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the identity hierarchy used for immutable update comparison."""

    _validate_work_structure(record, context="work record")
    work_id = require_string(dict(record), "work_id", context="work record")
    forms: dict[str, dict[str, Any]] = {}
    editions: dict[str, tuple[str, str]] = {}
    acquisitions: dict[str, tuple[str, str, str]] = {}
    raw_forms = record.get("textual_forms")
    assert isinstance(raw_forms, list)  # validated by _validate_work_structure
    for raw_form in raw_forms:
        assert isinstance(raw_form, dict)
        form_id = str(raw_form["textual_form_id"])
        forms[form_id] = {"work_id": work_id}
        raw_editions = raw_form["editions"]
        assert isinstance(raw_editions, list)
        for raw_edition in raw_editions:
            assert isinstance(raw_edition, dict)
            edition_id = str(raw_edition["edition_id"])
            editions[edition_id] = (work_id, form_id)
            for raw_acquisition_id in raw_edition.get("acquisition_ids", []):
                acquisition_id = str(raw_acquisition_id)
                acquisitions[acquisition_id] = (work_id, form_id, edition_id)
    return {
        "work_id": work_id,
        "forms": forms,
        "editions": editions,
        "acquisitions": acquisitions,
    }


def validate_identity_update(previous: dict[str, Any], current: dict[str, Any]) -> None:
    """Reject an update that changes an existing identity or its parent.

    Titles, creator names, evidence, language, and other descriptive facts may
    be corrected in place. Existing work, textual-form, edition, and declared
    acquisition IDs cannot be removed, reused, or moved to another parent.
    """

    validate_record("work", previous, context="previous work")
    validate_record("work", current, context="current work")
    old = immutable_identity(previous)
    new = immutable_identity(current)
    if old["work_id"] != new["work_id"]:
        raise PipelineError(
            f"immutable work_id changed: {old['work_id']!r} -> {new['work_id']!r}"
        )
    for field in ("forms", "editions", "acquisitions"):
        for identifier, parent in old[field].items():
            if identifier not in new[field]:
                raise PipelineError(f"immutable {field[:-1]} ID removed: {identifier}")
            if new[field][identifier] != parent:
                raise PipelineError(
                    f"immutable {field[:-1]} parent changed for {identifier}: "
                    f"{parent!r} -> {new[field][identifier]!r}"
                )


def compare_immutable_ids(previous: dict[str, Any], current: dict[str, Any]) -> None:
    """Compatibility name for callers that describe the check as a comparison."""

    validate_identity_update(previous, current)
