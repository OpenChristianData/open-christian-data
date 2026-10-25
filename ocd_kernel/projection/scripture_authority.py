"""Dataset-side scripture naming authority shared by category projections."""
from __future__ import annotations

import json
from pathlib import Path
import re

from ocd_kernel.library._common import PipelineError

BOOK_CODES_PATH = Path(__file__).resolve().parents[2] / 'build/bible_data/osis_book_codes.json'


def load_book_codes(path: Path = BOOK_CODES_PATH) -> set[str]:
    document = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(document, dict):
        raise PipelineError('invalid scripture book-code authority')
    values = [value for key, value in document.items() if not key.startswith('_')]
    if not values or any(not isinstance(value, str) or not re.fullmatch(r'[1-4]?[A-Za-z][A-Za-z0-9]*', value) for value in values):
        raise PipelineError('invalid scripture book-code declaration')
    return set(values)
