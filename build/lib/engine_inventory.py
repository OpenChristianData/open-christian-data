"""Engine inventory + readiness smoke for the Schaff-Herzog OCR engine stack (S1).

Each engine lives in its own virtualenv under ``~/ocr-engines/`` (outside any
sync folder). The venv root is resolved from the user home at runtime -- never a
hardcoded absolute path, so committed content carries no machine identity.

Smoke depth, by design:
  * tesseract -> a real OCR run on a sample leaf (this is the newly installed
    engine, so it is proven end-to-end here).
  * surya / kraken / kraken-greek -> a readiness probe (the venv's interpreter
    imports the engine and reports its version). Full per-engine OCR runners are
    built in batch B4 (the S1 sidecar production harness); B1 only proves the
    active engines are installed and importable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class EngineSpec:
    name: str          # short engine name
    family: str        # engine_family label (must be schema-valid)
    venv: str          # venv directory name under ~/ocr-engines/
    import_module: str  # module the venv interpreter imports as the readiness check
    kind: str          # "ocr" -> real run smoke; "readiness" -> import+version probe


# Families must be members of the word-confusion-table-v1 engine_family enum
# (verified by tests/test_engine_smoke.py against get_enum, never hardcoded here).
ENGINE_SPECS: tuple[EngineSpec, ...] = (
    EngineSpec("tesseract", "tesseract", "tesseract-py314", "pytesseract", "ocr"),
    EngineSpec("surya", "surya", "surya-py312", "surya", "readiness"),
    EngineSpec("kraken", "kraken", "kraken-py312", "kraken", "readiness"),
    # Greek specialist lane: same venv as kraken, Ciaconna model weights.
    # engine_family="kraken" so family_independence collapses both to one block.
    # import_module differs so the readiness probe identifies this spec distinctly.
    EngineSpec("kraken-greek", "kraken", "kraken-py312", "kraken.lib.models", "readiness"),
)

DEFAULT_SAMPLE_LEAF = (
    Path("raw") / "internet-archive" / "schaff-herzog-pages" / "vol_01" / "page_0010.jpg"
)
SMOKE_REPORT_SUBDIR = Path("reports") / "engine_smoke"

# Probe runs inside each engine's venv. It reports import success/version without
# raising, so the host subprocess always exits 0 and the JSON is parseable.
_PROBE_CODE = (
    "import json, sys, importlib\n"
    "module = sys.argv[1]\n"
    "try:\n"
    "    mod = importlib.import_module(module)\n"
    "    print(json.dumps({'import_ok': True, 'version': str(getattr(mod, '__version__', 'unknown'))}))\n"
    "except Exception as exc:\n"  # report, never swallow (REL-10): the message is the payload
    "    print(json.dumps({'import_ok': False, 'error': type(exc).__name__ + ': ' + str(exc)[:200]}))\n"
)

_TESS_CODE = (
    "import json, sys\n"
    "import pytesseract\n"
    "from PIL import Image\n"
    "image_path, tess_cmd = sys.argv[1], sys.argv[2]\n"
    "pytesseract.pytesseract.tesseract_cmd = tess_cmd\n"
    "text = pytesseract.image_to_string(Image.open(image_path))\n"
    "print(json.dumps({'ok': True, 'text_len': len(text), 'text_sample': text[:200]}))\n"
)


def engines_root() -> Path:
    """Resolve the per-engine venv root from the user home (no hardcoded path)."""
    return Path(os.path.expanduser("~")) / "ocr-engines"


def venv_python(spec: EngineSpec) -> Path:
    """Path to the engine venv's interpreter (Windows layout, POSIX fallback)."""
    root = engines_root() / spec.venv
    win = root / "Scripts" / "python.exe"
    if win.exists():
        return win
    return root / "bin" / "python"


def tesseract_binary() -> str:
    """Resolve the tesseract executable: PATH first, then the standard install dir.

    PROGRAMFILES is used rather than a literal drive path so nothing machine- or
    user-specific is baked in.
    """
    found = shutil.which("tesseract")
    if found:
        return found
    program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    return str(program_files / "Tesseract-OCR" / "tesseract.exe")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relative_to_repo(path: Path, repo_root: Path) -> str:
    """Repo-root-relative POSIX string; falls back to the name for out-of-repo tmp paths."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _run_probe(python_exe: Path, module: str, timeout: float) -> dict:
    result = subprocess.run(
        [str(python_exe), "-c", _PROBE_CODE, module],
        capture_output=True, text=True, timeout=timeout, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def _run_tesseract(python_exe: Path, image_path: Path, timeout: float) -> dict:
    try:
        result = subprocess.run(
            [str(python_exe), "-c", _TESS_CODE, str(image_path), tesseract_binary()],
            capture_output=True, text=True, timeout=timeout, check=True,
        )
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "error": (exc.stderr or "").strip()[-300:]}
    return json.loads(result.stdout.strip().splitlines()[-1])


def smoke_engine(
    spec: EngineSpec,
    sample_leaf: Path,
    repo_root: Path,
    timeout: float = 180.0,
) -> dict:
    """Produce one engine smoke sidecar dict (readiness for all; real OCR for tesseract)."""
    sidecar: dict = {
        "engine": spec.name,
        "engine_family": spec.family,
        "venv": spec.venv,
        "mode": "ocr" if spec.kind == "ocr" else "readiness",
        "sample_leaf": _relative_to_repo(sample_leaf, repo_root),
        "checked_at": _now_iso(),
    }
    python_exe = venv_python(spec)
    if not python_exe.exists():
        sidecar.update({"venv_python_present": False, "import_ok": False, "ok": False,
                        "note": "venv interpreter not found"})
        return sidecar

    sidecar["venv_python_present"] = True
    probe = _run_probe(python_exe, spec.import_module, timeout)
    sidecar["import_ok"] = bool(probe.get("import_ok"))
    sidecar["version"] = probe.get("version")
    if probe.get("error"):
        sidecar["probe_error"] = probe["error"]

    if spec.kind == "ocr" and sidecar["import_ok"] and sample_leaf.exists():
        ocr = _run_tesseract(python_exe, sample_leaf, timeout)
        sidecar["ocr_ran"] = bool(ocr.get("ok"))
        sidecar["text_len"] = ocr.get("text_len")
        sidecar["text_sample"] = ocr.get("text_sample")
        if ocr.get("error"):
            sidecar["ocr_error"] = ocr["error"]
        sidecar["ok"] = bool(ocr.get("ok"))
    else:
        sidecar["ok"] = sidecar["import_ok"]

    return sidecar


def run_all_smokes(repo_root: Path, sample_leaf: Path | None = None,
                   timeout: float = 180.0) -> list[dict]:
    leaf = sample_leaf if sample_leaf is not None else (repo_root / DEFAULT_SAMPLE_LEAF)
    return [smoke_engine(spec, leaf, repo_root, timeout) for spec in ENGINE_SPECS]
