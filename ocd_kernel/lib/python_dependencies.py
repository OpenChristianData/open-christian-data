"""Shared Python import discovery for executable dependency closures."""

from __future__ import annotations

import ast
from collections.abc import Iterator


def iter_python_imports(tree: ast.AST) -> Iterator[ast.Import | ast.ImportFrom]:
    """Yield every import statement, including nested function and match bodies."""

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
