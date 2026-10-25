"""Shared operations for existing review commands."""

from __future__ import annotations

import logging


def configure_logging(*, LOG_FILE) -> None:
    """Configure file + console logging."""
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    logging.basicConfig(level=logging.DEBUG, handlers=[fh, sh],
                        format="%(levelname)s: %(message)s")
