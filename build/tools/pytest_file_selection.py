"""Collect the runner's exact file selection without Windows filename cross-comparisons."""
import json
from fnmatch import fnmatchcase
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption("--ocd-selected-files", help="Internal complete-file selection from the commit runner")


def pytest_configure(config):
    path = config.getoption("ocd_selected_files")
    if not path:
        raise pytest.UsageError("--ocd-selected-files is required by the file-selection plugin")
    try:
        record = json.loads(Path(path).read_bytes())
        if not isinstance(record, dict) or set(record) != {"root", "files"}:
            raise ValueError("invalid file-selection record")
        root = Path(record["root"]).resolve(strict=True)
        if root != config.rootpath.resolve(strict=True):
            raise ValueError("file-selection repository differs from pytest root")
        values = record["files"]
        if not isinstance(values, list) or not values or len(set(values)) != len(values):
            raise ValueError("file selection must contain unique complete files")
        order, ancestors = {}, {root}
        for rank, logical in enumerate(values):
            if not isinstance(logical, str):
                raise ValueError("selected targets must be strings")
            relative = Path(logical.split("::", 1)[0])
            if "[" in logical or logical.count("::") > 1 or relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"invalid selected file: {logical}")
            if not any(fnmatchcase(relative.name, pattern) for pattern in config.getini("python_files")):
                raise ValueError(f"selected file does not match pytest file patterns: {logical}")
            member = root / relative
            if not member.is_file() or not member.resolve(strict=True).is_relative_to(root):
                raise ValueError(f"selected file missing or outside repository: {logical}")
            order.setdefault(member, []).append((logical, rank))
            parent = member.parent
            while parent != root:
                ancestors.add(parent)
                parent = parent.parent
        config._ocd_file_selection = (order, ancestors, set(), set())
    except (OSError, ValueError, TypeError) as error:
        raise pytest.UsageError(f"Invalid selected-file input: {error}") from error


@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(collection_path, config):
    order, ancestors, _, _ = config._ocd_file_selection
    return collection_path not in order and collection_path not in ancestors


def pytest_collect_file(file_path, parent):
    order, _, seen, _ = parent.config._ocd_file_selection
    if file_path in order:
        seen.add(file_path)


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    report = outcome.get_result()
    if report.skipped:
        collector.config._ocd_file_selection[3].add(collector.path)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_collection_modifyitems(config, items):
    order, _, seen, skipped = config._ocd_file_selection
    missing = set(order) - seen
    extra = {item.path for item in items} - set(order)
    if missing or extra:
        raise pytest.UsageError(f"Selected-file coverage differs: missing={sorted(map(str, missing))}, extra={sorted(map(str, extra))}")
    ranks, matched, omitted = {}, set(), []
    for item in items:
        for target, position in order[item.path]:
            if "::" not in target or item.nodeid == target or item.nodeid.startswith(target + "["):
                ranks[item.nodeid] = position
                matched.add(target)
                break
        else:
            omitted.append(item)
    missing_nodes = [target for path, entries in order.items() if path not in skipped
                     for target, _ in entries if "::" in target and target not in matched]
    if missing_nodes:
        raise pytest.UsageError(f"Selected test names were not collected: {missing_nodes}")
    items[:] = [item for item in items if item.nodeid in ranks]
    if len({item.nodeid for item in items}) != len(items):
        raise pytest.UsageError("Selected-file collection duplicated a case")
    if omitted:
        config.hook.pytest_deselected(items=omitted)
    outcome = yield
    outcome.get_result()
    items.sort(key=lambda item: ranks[item.nodeid])
