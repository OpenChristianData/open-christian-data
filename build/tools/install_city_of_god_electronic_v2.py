"""Preflight or guardedly install the two reviewed City electronic masters.

Default mode is read-only. Apply swaps one complete City work generation with an
exact before/after manifest, retained rollback generation, and public validation.
"""
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from ocd_kernel.lib.atomic_io import acquire_jsonl_lock
from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.identities import load_work
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path("library/works/augustine-city-of-god")
CONTRACT = "ocd-city-electronic-v2-complete-generation-install-v1"
DEFAULT_MANIFEST = ROOT / "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-326-electronic-v2-install-plan-20260926.json"
PROMOTED = Path("C:/Scratch/city-promoted-pair-v1")
EDITION_NAMES = (
    ("augustine-city-of-god-dods-retained-en", "augustine-city-of-god-dods-retained-electronic", "augustine-city-of-god-dods-acquired"),
    ("augustine-city-of-god-npnf-retained-en", "augustine-city-of-god-npnf-retained-electronic", "augustine-city-of-god-npnf-acquired"),
)
REASON = "Evidence-backed TEI is the master; human verification, rights, and publication remain separate."
DEPENDENCY_FILES = (
    "sources/city-of-god/city-of-god-dods-1871-electronic-v2.source-manifest.json",
    "sources/city-of-god/city-of-god-npnf-1887-electronic-v2.source-manifest.json",
    "sources/city-of-god/city-of-god.electronic-v2.reconstruction-profile.json",
    "build/tei/city_of_god_reconstruction_electronic_v2.py",
    "build/tei/city_of_god_oracle_electronic_v2.py",
    "build/tools/prepare_city_of_god_acceptance_electronic_v2.py",
    "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-326-electronic-v2-repair-20260926.json",
    "plans/2026-08-31-sample-first-library-verification/artifacts/2026-09-08-ticket37/reviews/37c-326-electronic-v2-acceptance-stage-20260926.json",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write(path: Path, value: Mapping[str, object]) -> None:
    io = _io_path(path)
    io.parent.mkdir(parents=True, exist_ok=True)
    io.write_text(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def _safe_roots(root: Path, promoted: Path) -> tuple[Path, Path]:
    root, promoted = root.resolve(strict=True), promoted.resolve(strict=True)
    if root == promoted or root in promoted.parents or promoted in root.parents:
        raise PipelineError("City install roots overlap")
    for base in (root, promoted):
        path = base / WORK
        if not _io_path(path).is_dir() or path.is_symlink() or path.is_junction():
            raise PipelineError("City install requires local complete work directories")
    return root, promoted


def _edition_paths(form: str, edition: str) -> tuple[str, str, str]:
    prefix = f"forms/{form}/editions/{edition}"
    return prefix + "/master.tei.xml", prefix + "/acceptance.json", f"integration/city-{'dods' if 'dods' in edition else 'npnf'}-electronic-v2-acceptance/"


def _scoped(root: Path, promoted: Path, before: Mapping[str, str], after: Mapping[str, str]) -> None:
    if before.get("SOURCE_CREDIT.md") != after.get("SOURCE_CREDIT.md") or "SOURCE_CREDIT.md" not in before:
        raise PipelineError("City SOURCE_CREDIT.md must be preserved byte-for-byte")
    allowed = {"state.json", "work.json"}
    evidence_prefixes = []
    for form, edition, _aid in EDITION_NAMES:
        master, acceptance, evidence_prefix = _edition_paths(form, edition)
        if master in before or acceptance in before or master not in after or acceptance not in after:
            raise PipelineError("City accepted edition collides with existing master or acceptance")
        allowed.update((master, acceptance))
        evidence_prefixes.append(evidence_prefix)
    for path in set(before) | set(after):
        if before.get(path) == after.get(path):
            continue
        if path in allowed:
            continue
        if any(path.startswith(prefix) for prefix in evidence_prefixes):
            if path in before:
                raise PipelineError(f"City install overwrites existing evidence: {path}")
            continue
        raise PipelineError(f"City install changes unrelated work authority: {path}")
    for prefix in evidence_prefixes:
        if not any(path.startswith(prefix) for path in after):
            raise PipelineError(f"City acceptance evidence directory is empty: {prefix}")
    old_work = load_work(_io_path(root / WORK / "work.json"))
    new_work = load_work(_io_path(promoted / WORK / "work.json"))
    expected = json.loads(json.dumps(old_work))
    for form in expected["textual_forms"]:
        for edition in form["editions"]:
            if edition["edition_id"] not in {name for _, name, _ in EDITION_NAMES} or "category" in edition:
                raise PipelineError("City canonical edition category or identity changed")
            edition["category"] = "prose"
    if expected != new_work:
        raise PipelineError("City work.json differs beyond exact prose category additions")
    old_state = json.loads(_io_path(root / WORK / "state.json").read_bytes())
    new_state = json.loads(_io_path(promoted / WORK / "state.json").read_bytes())
    old_targets = {item["target_id"]: item for item in old_state["targets"]}
    new_targets = {item["target_id"]: item for item in new_state["targets"]}
    if set(old_targets) != set(new_targets):
        raise PipelineError("City install changes state target set")
    for target_id, old in old_targets.items():
        new = new_targets[target_id]
        if target_id in {name for _, name, _ in EDITION_NAMES}:
            form = next(form for form,name,_ in EDITION_NAMES if name == target_id)
            master, acceptance, _ = _edition_paths(form, target_id)
            expected_evidence = old["evidence"] + [f"{WORK.as_posix()}/{master}", f"{WORK.as_posix()}/{acceptance}"]
            if (old["stage"] != "acquired" or new["stage"] != "accepted" or
                    new.get("reason") != REASON or new.get("evidence") != expected_evidence):
                raise PipelineError(f"City edition state transition differs: {target_id}")
            if {k:v for k,v in old.items() if k not in ("stage","reason","updated_at","evidence")} != {k:v for k,v in new.items() if k not in ("stage","reason","updated_at","evidence")}:
                raise PipelineError(f"City edition state identity changed: {target_id}")
        elif old != new:
            raise PipelineError(f"City unrelated state target changed: {target_id}")
    if {k:v for k,v in old_state.items() if k != "targets"} != {k:v for k,v in new_state.items() if k != "targets"}:
        raise PipelineError("City work state identity changed")


def _dependencies(root: Path, promoted: Path) -> dict[str, str]:
    state = json.loads(_io_path(root / WORK / "state.json").read_bytes())
    refs = set(DEPENDENCY_FILES)
    refs.update(ref for item in state["targets"] for ref in item.get("evidence", []) if not ref.startswith(WORK.as_posix()+"/"))
    for form, edition, aid in EDITION_NAMES:
        acquisition = json.loads(_io_path(root / WORK / "forms" / form / "editions" / edition / "acquisitions" / f"{aid}.json").read_bytes())
        refs.add(acquisition["source_path"])
        refs.update(item["path"] for item in acquisition["retained_files"])
    result = {}
    for ref in sorted(refs):
        relative = Path(ref)
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != ref:
            raise PipelineError(f"City dependency path is unsafe: {ref}")
        canonical = resolve_repo_path(root, ref) if relative.parts[0] in {"raw","reports","exports"} else root / relative
        if not _io_path(canonical).is_file():
            raise PipelineError(f"City dependency missing: {ref}")
        result[ref] = _sha(canonical)
        staged = promoted / relative
        if _io_path(staged).is_file() and _sha(staged) != result[ref]:
            raise PipelineError(f"City promoted dependency differs: {ref}")
    return result


def _valid_promoted(promoted: Path, after: Mapping[str,str]) -> None:
    records = []
    for form, edition, _aid in EDITION_NAMES:
        master, acceptance, _ = _edition_paths(form, edition)
        record = validate_acceptance(_io_path(promoted / WORK / acceptance), root=_io_path(promoted))
        if record["promotion"]["status"] != "promoted" or record["promotion"]["master"]["sha256"] != after[master]:
            raise PipelineError(f"City promoted record/master differs: {edition}")
        records.append(record)
    validate_state(_io_path(promoted / WORK / "state.json"), root=_io_path(promoted))
    if len(records) != 2:
        raise PipelineError("City promoted acceptance count differs")


def prepare_manifest(root: Path, promoted: Path, output: Path) -> dict[str, object]:
    root, promoted = _safe_roots(root, promoted)
    if output.exists():
        raise PipelineError("City install manifest output must be fresh")
    before, after = _files(root / WORK), _files(promoted / WORK)
    _scoped(root, promoted, before, after)
    _valid_promoted(promoted, after)
    dependencies = _dependencies(root, promoted)
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    record: dict[str, object] = dict(contract=CONTRACT, prepared_at=_now(), status="staged-only",
                                    canonical_root=root.as_posix(), promoted_root=promoted.as_posix(),
                                    work_id="augustine-city-of-god", before=before, after=after,
                                    changed_paths=changed, external_dependencies=dependencies,
                                    category_decision="Both exact retained electronic witnesses have prose book/chapter bodies; edition category prose only.",
                                    source_role="Exact extracted XHTML/XML files; ZIP/EPUB packages are acquisition containers only.")
    _write(output, record)
    return record


def preflight(manifest: Path) -> tuple[dict,Path,Path]:
    record = json.loads(_io_path(manifest.resolve(strict=True)).read_bytes())
    if record.get("contract") != CONTRACT or record.get("work_id") != "augustine-city-of-god":
        raise PipelineError("City install manifest contract differs")
    root, promoted = _safe_roots(Path(record["canonical_root"]), Path(record["promoted_root"]))
    before, after = _files(root / WORK), _files(promoted / WORK)
    if before != record.get("before") or after != record.get("after"):
        raise PipelineError("City install generation changed")
    if sorted(path for path in set(before)|set(after) if before.get(path)!=after.get(path)) != record.get("changed_paths"):
        raise PipelineError("City install changed-path inventory differs")
    _scoped(root, promoted, before, after)
    _valid_promoted(promoted, after)
    if _dependencies(root, promoted) != record.get("external_dependencies"):
        raise PipelineError("City retained source or authority changed")
    return record, root, promoted


def install(manifest: Path, *, fail_at: Callable[[str],None] | None = None) -> dict[str,object]:
    record, root, promoted = preflight(manifest)
    target, source = root / WORK, promoted / WORK
    with acquire_jsonl_lock(target, acquire_timeout=30.0):
        if _files(target) != record["before"] or _files(source) != record["after"] or _dependencies(root,promoted) != record["external_dependencies"]:
            raise PipelineError("City generation changed while acquiring lock")
        operation = root / "library/.sidecar-operations" / ("city-electronic-v2-"+uuid.uuid4().hex[:16])
        _io_path(operation).mkdir(parents=True,exist_ok=False)
        incoming, previous, failed_new = (operation/name for name in ("incoming","previous","failed-new"))
        journal = operation / "operation.json"
        status: dict[str,object] = dict(contract=CONTRACT, work_id="augustine-city-of-god", before=record["before"], after=record["after"], phase="created", created_at=_now())
        _write(journal,status)
        moved = live = False
        try:
            shutil.copytree(_io_path(source),_io_path(incoming))
            if _files(incoming) != record["after"] or _files(target) != record["before"]:
                raise PipelineError("City incoming generation differs")
            status["phase"]="prepared"; _write(journal,status)
            if fail_at: fail_at("after-copy")
            if _dependencies(root,promoted) != record["external_dependencies"] or _files(target) != record["before"]:
                raise PipelineError("City source or live work changed before swap")
            os.replace(_io_path(target),_io_path(previous)); moved=True
            status["phase"]="previous-moved"; _write(journal,status)
            if fail_at: fail_at("after-old-rename")
            os.replace(_io_path(incoming),_io_path(target)); live=True
            status["phase"]="new-live"; _write(journal,status)
            if fail_at: fail_at("after-new-rename")
            if _files(target) != record["after"]:
                raise PipelineError("City installed generation differs")
            for form,edition,_ in EDITION_NAMES:
                _master,acceptance,_evidence=_edition_paths(form,edition)
                validate_acceptance(_io_path(target / acceptance),root=_io_path(root))
            validate_state(_io_path(target / "state.json"),root=_io_path(root))
            if fail_at: fail_at("after-validation")
            if _files(target) != record["after"]:
                raise PipelineError("City post-swap generation changed")
            status["phase"]="complete";status["completed_at"]=_now();_write(journal,status)
            return dict(status="installed-and-validated",operation=operation.as_posix(),backup=previous.as_posix(),before_file_count=len(record["before"]),after_file_count=len(record["after"]))
        except BaseException:
            try:
                if live:
                    if _files(target) != record["after"]:
                        raise PipelineError("City new generation changed after swap")
                    os.replace(_io_path(target),_io_path(failed_new))
                if moved:
                    if _io_path(target).exists() or _files(previous) != record["before"]:
                        raise PipelineError("City rollback previous generation differs")
                    os.replace(_io_path(previous),_io_path(target))
                    if _files(target) != record["before"]:
                        raise PipelineError("City rollback restored unexpected bytes")
                status["phase"]="rolled-back" if moved else "failed-before-swap";status["updated_at"]=_now();_write(journal,status)
            except BaseException as rollback_error:
                status["phase"]="recovery-required";status["rollback_error"]=str(rollback_error);_write(journal,status)
                raise PipelineError(f"City rollback needs recovery: {operation}") from rollback_error
            raise


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=ROOT)
    parser.add_argument("--promoted",type=Path,default=PROMOTED)
    parser.add_argument("--manifest",type=Path,default=DEFAULT_MANIFEST)
    parser.add_argument("--prepare",action="store_true")
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    if args.prepare and args.apply: parser.error("--prepare and --apply are mutually exclusive")
    if args.prepare: result=prepare_manifest(args.root,args.promoted,args.manifest)
    elif args.apply: result=install(args.manifest)
    else:
        record,_root,_promoted=preflight(args.manifest)
        result={"status":"ready","changed_paths":len(record["changed_paths"])}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
