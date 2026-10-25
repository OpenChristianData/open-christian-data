"""Declare exact source and external-stage cases for portable public CI."""
from pathlib import Path, PurePosixPath
import json

import pytest


def local_input_cases(root):
    record = json.loads((root / "tests/fixtures/public-local-input-cases.json").read_bytes())
    if (not {"contract", "modules"} <= record.keys()
            or record.keys() - {"contract", "modules", "external_modules", "private_cases"}
            or record["contract"] != "ocd-public-test-inputs-v1"):
        raise ValueError("invalid public test input inventory")
    cases = {}
    for module, binding in record["modules"].items():
        logical = PurePosixPath(binding["required_path"])
        if (logical.is_absolute() or len(logical.parts) < 2 or logical.parts[0] != "raw"
                or ".." in logical.parts or logical.as_posix() != binding["required_path"]
                or "\\" in binding["required_path"]):
            raise ValueError(f"invalid raw test input: {module}")
        for name in binding["tests"]:
            node = f"{module}::{name}"
            if node in cases:
                raise ValueError(f"duplicate public test input: {node}")
            cases[node] = root / logical
    for module, binding in record.get("external_modules", {}).items():
        external = binding["external_path"]
        prefixes = ("D:/Library/Open Christian Data", "C:/Scratch")
        if (not any(external == prefix or external.startswith(prefix + "/") for prefix in prefixes)
                or ".." in PurePosixPath(external).parts or "\\" in external
                or PurePosixPath(external).as_posix() != external):
            raise ValueError(f"invalid external test input: {module}")
        for name in binding["tests"]:
            node = f"{module}::{name}"
            if node in cases:
                raise ValueError(f"duplicate public test input: {node}")
            cases[node] = None
    for node, private in record.get("private_cases", {}).items():
        logical = PurePosixPath(private)
        if (logical.is_absolute() or not logical.parts or ":" in logical.parts[0]
                or ".." in logical.parts or "\\" in private or logical.as_posix() != private):
            raise ValueError(f"invalid private test input: {node}")
        if node in cases:
            raise ValueError(f"duplicate public test input: {node}")
        cases[node] = None
    return cases


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    cases = local_input_cases(Path(config.rootpath))
    missing = {path for path in set(cases.values()) if path is None or not path.exists()}
    for item in items:
        node = item.nodeid if item.nodeid in cases else item.nodeid.split("[", 1)[0]
        if node in cases and cases[node] in missing:
            item.add_marker(pytest.mark.requires_local_artifacts)
