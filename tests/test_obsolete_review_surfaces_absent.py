from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _module_spec(module_name: str):
    try:
        return importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        return None


def test_obsolete_modules_are_absent() -> None:
    for module_name in (
        "build.lib.render_cache",
        "build.tools.apply_review_patch",
        "build.tools.phase1_completion_audit",
        "build.tools.render_corpus_dashboard",
        "build.tools.render_review_html",
        "build.patch_kd_cross_refs",
        "build.reconstruction.city_of_god.accept_city_masters",
        "build.reconstruction.city_of_god.city_projection",
        "build.reconstruction.city_of_god.city_semantic_slice",
        "build.reconstruction.cross_category_pilot",
        "build.reconstruction.cross_category_pilot_archive",
        "build.reconstruction.cross_category_pilot_verifier",
        "build.reconstruction.path_compat",
        "build.reconstruction.preserved_evidence",
        "build.scripts.backfill_maclaren_osis",
        "build.scripts.add_pg_whitefield_sermons",
        "build.scripts.dump_target_entries",
        "build.scripts.extend_author_registry",
        "build.scripts.extend_registry_non_cf",
        "build.scripts.fix_contributors",
        "build.scripts.fix_misattributed_entries",
        "build.scripts.inspect_sword_zld",
        "build.scripts.patch_author_registry",
        "build.scripts.patch_expositors_osis",
        "build.scripts.pre_flight_source_availability",
        "build.scripts.prepare_curation_session",
        "build.scripts.rebuild_calvin_psalms",
        "build.scripts.sample_church_fathers",
        "build.scripts.test_osis_integration",
        "build.tools.rebind_preserved_evidence_successors",
        "build.tools.create_reconstruction_evidence_archive",
        "build.tools.restore_reconstruction_evidence",
        "ocd_kernel.reconstruction.case_declaration",
        "ocd_kernel.reconstruction.interface",
        "ocd_kernel.reconstruction.model",
        "ocd_kernel.reconstruction.package",
        "ocd_kernel.reconstruction.persistence",
        "ocd_kernel.reconstruction.repository",
        "ocd_kernel.reconstruction.review",
        "ocd_kernel.reconstruction.rights",
        "ocd_kernel.reconstruction.semantic",
        "ocd_kernel.reconstruction.source",
        "ocd_kernel.reconstruction.verifier_process",
        "ocd_kernel.reconstruction.wave_codec",
        "ocd_kernel.reconstruction.wave",
    ):
        assert _module_spec(module_name) is None


def test_obsolete_reconstruction_control_trees_are_absent() -> None:
    assert not any(
        path.is_file()
        for path in (REPO_ROOT / "config" / "reconstruction").rglob("*")
    )
    assert not any(
        path.is_file()
        for path in (REPO_ROOT / "tests" / "fixtures" / "reconstruction").rglob("*")
    )
    assert not list((REPO_ROOT / "build" / "reconstruction").rglob("*.py"))
    assert {
        path.relative_to(REPO_ROOT / "ocd_kernel" / "reconstruction").as_posix()
        for path in (REPO_ROOT / "ocd_kernel" / "reconstruction").rglob("*")
        if path.is_file() and path.suffix != ".pyc"
    } == {
        "__init__.py",
        "closure_verification.py",
        "contract.py",
        "decision.py",
        "destination_policy.py",
        "schemas/candidate-package-v1.schema.json",
        "text_quality.py",
        "verifier.py",
    }


def test_obsolete_static_review_source_trees_are_absent() -> None:
    for relative_path in (
        "build/lib/reference_resources",
        "build/lib/render_strategies",
        "build/lib/review_ui_js",
    ):
        source_root = REPO_ROOT / relative_path
        assert not any(
            path.suffix in {".js", ".py", ".yaml"}
            for path in source_root.rglob("*")
            if path.is_file()
        )


def test_source_title_patch_estate_is_absent() -> None:
    assert not list((REPO_ROOT / "build").glob("patch*source*title*.py"))
    assert not list((REPO_ROOT / "build" / "scripts").glob("patch*source*title*.py"))
    assert not (
        REPO_ROOT / "sources" / "church-fathers" / "source-title-authority.json"
    ).exists()


def test_completed_b03b_prompts_are_absent() -> None:
    for name in (
        "2026-07-16-1300-b03b-projector-ledger-v2.md",
        "codex-b03b-projector-prompt.md",
        "codex-b03b-redteam-prompt.md",
    ):
        assert not (REPO_ROOT / "prompts" / name).exists()
