"""Compatibility gate for migrating the generic reconstruction runner."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import ocd_kernel.reconstruction.destination_policy as destination_policy
from ocd_kernel.reconstruction.destination_policy import preflight_destination


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load_module(
    "_ticket04_migration_runner",
    ROOT / "build/tools/reconstruct_candidate.py",
)
RUNNER_SUPPORT = _load_module(
    "_ticket04_migration_support",
    ROOT / "tests/test_reconstruct_candidate.py",
)


def test_shared_policy_explicit_mode_supports_runner_appeared_empty_replacement(
    tmp_path: Path,
) -> None:
    """Bind the explicit Ticket 03 compatibility seam for Ticket 04."""

    repository = tmp_path / "repo"
    repository.mkdir()
    destination = tmp_path / "candidate"
    plan = preflight_destination(
        repository,
        destination,
        appeared_empty="replace",
        repository_lexical="allow_resolved_escape",
    )

    with plan.stage() as staged:
        (staged.path / "package").mkdir()
        (staged.path / "validation.json").write_bytes(b"complete")
        destination.mkdir()
        staged.promote()

    assert {path.name for path in destination.iterdir()} == {
        "package",
        "validation.json",
    }
    assert (destination / "validation.json").read_bytes() == b"complete"
    assert not list(destination.parent.glob(f".{destination.name}.staging-*"))


def test_runner_selects_both_shared_compatibility_modes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The migrated runner must use the reaccepted public compatibility seam."""

    repository = RUNNER_SUPPORT._synthetic_repository(tmp_path / "fixture")
    destination = tmp_path / "candidate"
    original = destination_policy.preflight_destination
    calls: list[tuple[Path, Path, str, str]] = []

    def record_call(
        repository_root,
        requested_destination,
        *,
        appeared_empty,
        repository_lexical,
    ):
        calls.append(
            (
                Path(repository_root),
                Path(requested_destination),
                appeared_empty,
                repository_lexical,
            )
        )
        return original(
            repository_root,
            requested_destination,
            appeared_empty=appeared_empty,
            repository_lexical=repository_lexical,
        )

    monkeypatch.setattr(destination_policy, "preflight_destination", record_call)

    summary = RUNNER.run(
        manifest=RUNNER_SUPPORT.MANIFEST,
        destination=str(destination),
        repository_root=str(repository),
    )

    assert summary["status"] == "pass"
    assert calls == [
        (
            repository.resolve(strict=True),
            destination,
            "replace",
            "allow_resolved_escape",
        )
    ]
