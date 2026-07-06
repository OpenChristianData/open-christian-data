"""Single source of truth for the repository root.

All build/lib, build/tools, and build/parsers modules should import REPO_ROOT
from here.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

__all__ = ('REPO_ROOT',)
