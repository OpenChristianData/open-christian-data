"""Load warning-producer evidence renderers without module-name collisions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def load_evidence_renderer(producer_id: str, evidence_renderer_path: Path | str) -> ModuleType:
    """Load an evidence renderer module scoped to ``producer_id``."""
    module_key = f"warning_producer_evidence.{producer_id}"
    path = Path(evidence_renderer_path).resolve()
    spec = importlib.util.spec_from_file_location(module_key, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load evidence renderer at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_key] = module
    spec.loader.exec_module(module)
    return module
