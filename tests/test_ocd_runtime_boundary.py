from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "library-pipeline"
HANDOFF_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "accepted-tei-handoff" / "v1" / "valid"
HANDOFF_SCHEMA = REPO_ROOT / "schemas" / "boundary" / "accepted-tei-handoff" / "v1" / "accepted-tei-handoff.schema.json"
JE_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "witnessless_lemma_fixture.tei.xml"
WORK_ID = "athanasius-on-the-incarnation"
FORM_ID = "athanasius-on-the-incarnation-prose"
EDITION_ID = "ccel-npnf204"
ACQUISITION_ID = "ccel-npnf204-retained-xml"
SOURCE_SHA256 = "bd625a0fa4f5ddd4b2fa13fcee753de8832ea4b316625e0e06454beb81cfa652"


@pytest.fixture
def tmp_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Keep copied pipeline roots short for Windows subprocess paths."""

    return tmp_path_factory.mktemp("ocd")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _pipe004_helpers() -> ModuleType:
    """Reuse the settled PIPE-004 fixture builder for a synthetic copy only."""

    path = REPO_ROOT / "tests" / "test_tei_acceptance.py"
    spec = importlib.util.spec_from_file_location("_pipe004_boundary_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load PIPE-004 fixture helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _promoted_pipeline_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "f"
    shutil.copytree(PIPELINE_FIXTURE, root)
    helpers = _pipe004_helpers()
    acceptance_path, record = helpers._write_valid_acceptance(root)
    candidate_path = root / "acceptance" / "candidate.tei.xml"
    master_path = (
        root
        / "library"
        / "works"
        / WORK_ID
        / "forms"
        / FORM_ID
        / "editions"
        / EDITION_ID
        / "master.tei.xml"
    )
    master_path.write_bytes(candidate_path.read_bytes())
    record["promotion"]["status"] = "promoted"
    record["promotion"]["promoted_at"] = "2026-09-06T12:00:00Z"
    record["promotion"]["master"] = helpers.make_file_binding(root, master_path) | {
        "path": (
            f"library/works/{WORK_ID}/forms/{FORM_ID}/editions/"
            f"{EDITION_ID}/master.tei.xml"
        )
    }
    _write_json(acceptance_path, record)
    state_path = root / "library" / "works" / WORK_ID / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["targets"][0]["evidence"].extend(
        [
            f"library/works/{WORK_ID}/forms/{FORM_ID}/editions/{EDITION_ID}/acceptance.json",
            f"library/works/{WORK_ID}/forms/{FORM_ID}/editions/{EDITION_ID}/master.tei.xml",
        ]
    )
    _write_json(state_path, state)
    return root, acceptance_path, master_path


def _run_isolated(source: str, *arguments: Path) -> dict[str, object]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    process = subprocess.run(
        [sys.executable, "-I", "-B", "-c", source, *(str(argument) for argument in arguments)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, (
        f"isolated child failed with exit {process.returncode}\n"
        f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
    )
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"isolated child did not return JSON:\n{process.stdout}\n{process.stderr}"
        ) from exc
    assert isinstance(result, dict)
    return result


_PIPELINE_CHILD = r'''
import importlib
import json
import os
import sys
from pathlib import Path


class EzraBlocker:
    def find_spec(self, fullname, path=None, target=None):
        del path, target
        if fullname.split(".", 1)[0].casefold().startswith("ezra"):
            raise ImportError("EzraOCR runtime is blocked by PIPE-025 boundary test")
        return None


repo = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
acceptance_path = Path(sys.argv[3]).resolve()
master_path = Path(sys.argv[4]).resolve()
je_fixture = Path(sys.argv[5]).resolve()
views_output = Path(sys.argv[6]).resolve()
release_output = Path(sys.argv[7]).resolve()
sys.meta_path.insert(0, EzraBlocker())
sys.path.insert(0, str(repo))
assert not any(name.split(".", 1)[0].casefold().startswith("ezra") for name in sys.modules)

try:
    importlib.import_module("ezra")
except ImportError as exc:
    assert "blocked" in str(exc)
else:
    raise AssertionError("Ezra import unexpectedly succeeded")

from ocd_kernel.library.acquisitions import acquisition_for_edition, source_sha256
from ocd_kernel.library.identities import discover_library, edition_by_id
from ocd_kernel.library.views import build_library_views
from ocd_kernel.projection.categories.prose import project_prose
from ocd_kernel.release.assemble import assemble_release
from ocd_kernel.release.check import check_release
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei import validate as tei_validate
from ocd_kernel.tei import validate_schematron as tei_schematron

runtime_modules = (
    "ocd_kernel.library.acquisitions",
    "ocd_kernel.library.identities",
    "ocd_kernel.library.views",
    "ocd_kernel.projection.categories.prose",
    "ocd_kernel.release.assemble",
    "ocd_kernel.release.check",
    "ocd_kernel.tei.acceptance",
    "ocd_kernel.tei.validate",
    "ocd_kernel.tei.validate_schematron",
)
origins = {
    name: str(Path(importlib.import_module(name).__file__).resolve())
    for name in runtime_modules
}
for origin in origins.values():
    Path(origin).relative_to(repo)

assert tei_validate._SCHEMA_PATH == repo / "ocd_kernel" / "tei" / "vendor" / "xsd" / "tei_all.xsd"
assert tei_schematron._SCHEMA_PATH == repo / "ocd_kernel" / "tei" / "vendor" / "schematron" / "je_critical.sch"
assert tei_validate._SCHEMA_PATH.is_file()
assert tei_schematron._SCHEMA_PATH.is_file()
assert (tei_validate._SCHEMA_PATH.parent.parent / "VERSION.txt").is_file()

works = discover_library(root)
assert [work.work_id for work in works] == ["athanasius-on-the-incarnation"]
work, edition = edition_by_id(root, "ccel-npnf204")
assert work.work_id == "athanasius-on-the-incarnation"
acquisition_path, acquisition = acquisition_for_edition(root, work.work_id, edition.edition_id)
assert source_sha256(acquisition, context=str(acquisition_path)) == "bd625a0fa4f5ddd4b2fa13fcee753de8832ea4b316625e0e06454beb81cfa652"
accepted = validate_acceptance(acceptance_path, root=root)
assert accepted["promotion"]["status"] == "promoted"

assert tei_validate.validate_file(master_path) == []
assert tei_schematron.validate_file(je_fixture) == []
views = build_library_views(root, views_output)
assert views["status"]["counts"]["included"] == 1
projection = project_prose(
    master_path,
    work_id=work.work_id,
    textual_form_id=edition.textual_form_id,
    edition_id=edition.edition_id,
    acquisition_id=acquisition["acquisition_id"],
    edition_title=edition.title,
    language=edition.record["language"],
    representation_revision=None,
    source_url=acquisition["url"],
    accessed_at=acquisition.get("accessed_at"),
    source_sha256=source_sha256(acquisition, context=str(acquisition_path)),
    retained_sha256=acquisition["retained_files"][0]["sha256"],
)
assert len(projection.rows) == 4
release = assemble_release(
    root,
    release_output,
    release_id="pipe-025-boundary",
    edition_id=edition.edition_id,
    category="prose",
)
assert release["status"] == "pass"
assert check_release(root, release_output)["status"] == "pass"
assert not any(name.split(".", 1)[0].casefold().startswith("ezra") for name in sys.modules)
print(json.dumps({
    "status": "pass",
    "isolated": bool(sys.flags.isolated),
    "pythonpath_present": "PYTHONPATH" in os.environ,
    "origins": origins,
    "rows": len(projection.rows),
}, sort_keys=True))
'''


_HANDOFF_CHILD = r'''
import hashlib
import importlib
import json
import os
import sys
from pathlib import Path


class RuntimeBlocker:
    def find_spec(self, fullname, path=None, target=None):
        del path, target
        top = fullname.split(".", 1)[0].casefold()
        if top in {"ocd_kernel", "ezra", "ezraocr"}:
            raise ImportError("application runtime blocked by PIPE-025 handoff test")
        return None


package = Path(sys.argv[1]).resolve()
schema_path = Path(sys.argv[2]).resolve()
sys.meta_path.insert(0, RuntimeBlocker())
for module_name in ("ocd_kernel", "ezra", "EzraOCR"):
    try:
        importlib.import_module(module_name)
    except ImportError as exc:
        assert "runtime blocked" in str(exc)
    else:
        raise AssertionError(f"application runtime import unexpectedly succeeded: {module_name}")

import jsonschema
from lxml import etree


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def binding(value):
    reference = value["path"]
    relative = Path(reference)
    assert not relative.is_absolute()
    assert "\\" not in reference and ":" not in reference
    assert ".." not in relative.parts
    target = (package / Path(*reference.split("/"))).resolve()
    target.relative_to(package)
    payload = target.read_bytes()
    assert len(payload) == value["bytes"]
    assert hashlib.sha256(payload).hexdigest() == value["sha256"]
    return target


handoff = load(package / "handoff.json")
validator = jsonschema.Draft202012Validator(
    load(schema_path), format_checker=jsonschema.FormatChecker()
)
errors = sorted(validator.iter_errors(handoff), key=lambda error: list(error.path))
assert not errors, "; ".join(error.message for error in errors)

accepted = binding(handoff["accepted_tei"])
source = handoff["source"]
for field in ("source_file", "acquisition_record", "source_manifest", "accounting"):
    binding(source[field])
for item in source["included_members"]:
    binding(item)
for name in ("validation", "accounting", "fidelity", "reproducibility", "schema", "closure"):
    binding(handoff["technical"][name]["evidence"])
binding(handoff["review"]["report"])
tree = etree.parse(
    str(accepted),
    etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True),
)
assert etree.QName(tree.getroot()).localname == "TEI"
assert not any(
    name.split(".", 1)[0].casefold() in {"ocd_kernel", "ezra", "ezraocr"}
    for name in sys.modules
)
print(json.dumps({
    "status": "pass",
    "isolated": bool(sys.flags.isolated),
    "pythonpath_present": "PYTHONPATH" in os.environ,
    "bound_source_members": len(source["included_members"]),
}, sort_keys=True))
'''


def test_ocd_runtime_isolated_from_ezra_and_runs_pipeline(tmp_path: Path) -> None:
    root, acceptance_path, master_path = _promoted_pipeline_fixture(tmp_path)
    before = _hash_tree(root)
    je_before = hashlib.sha256(JE_FIXTURE.read_bytes()).hexdigest()
    result = _run_isolated(
        _PIPELINE_CHILD,
        REPO_ROOT,
        root,
        acceptance_path,
        master_path,
        JE_FIXTURE,
        tmp_path / "views",
        tmp_path / "release",
    )
    assert result["status"] == "pass"
    assert result["isolated"] is True
    assert result["pythonpath_present"] is False
    assert result["rows"] == 4
    assert all(str(Path(origin)).lower().startswith(str(REPO_ROOT).lower()) for origin in result["origins"].values())
    assert _hash_tree(root) == before
    assert hashlib.sha256(JE_FIXTURE.read_bytes()).hexdigest() == je_before


def test_frozen_handoff_validates_without_either_runtime() -> None:
    before = _hash_tree(HANDOFF_FIXTURE)
    result = _run_isolated(_HANDOFF_CHILD, HANDOFF_FIXTURE, HANDOFF_SCHEMA)
    assert result == {
        "bound_source_members": 1,
        "isolated": True,
        "pythonpath_present": False,
        "status": "pass",
    }
    assert _hash_tree(HANDOFF_FIXTURE) == before
