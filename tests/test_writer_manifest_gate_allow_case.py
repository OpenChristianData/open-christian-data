from __future__ import annotations


def _manifest(writer_identity: str, run_id: str) -> dict:
    data_path = "data/reference/schaff-herzog-encyclopedia.json"
    return {
        "schema_version": "1.0.0",
        "writer": "parser",
        "writer_version": "build/parsers/ia_schaff_herzog.py@v1.0.0",
        "writer_identity": writer_identity,
        "run_id": run_id,
        "started_at": "2026-05-12T10:00:00+00:00",
        "data_paths": [data_path],
        "checksums": {
            data_path: {
                "before_sha256": "a" * 64,
                "after_sha256": "b" * 64,
            }
        },
        "expected_delta_counts": {
            data_path: {
                "entries_changed": 1,
                "fields_changed": 1,
            }
        },
        "allowed_field_paths": ["/data/*/layers/*/display"],
        "partial_completion_policy": "all_or_nothing",
        "renames": [],
    }


def test_allow_case_with_registered_identity():
    from build.lib import writer_identities
    from build.tools.check_writer_manifest_gate import evaluate_gate

    assert writer_identities.is_authorised("ia_schaff_herzog_parser")

    manifest_body = _manifest("ia_schaff_herzog_parser", "test-allow-case-001")
    staged = [
        "data/reference/schaff-herzog-encyclopedia.json",
        "review/writer-manifests/test-allow-case-001.json",
    ]

    def fake_loader(path):
        if path == "review/writer-manifests/test-allow-case-001.json":
            return manifest_body
        return None

    exit_code, messages = evaluate_gate(staged, load_manifest=fake_loader)
    assert exit_code == 0, f"Gate should pass but blocked with: {messages}"


def test_allow_case_all_registered_identities_pass():
    from build.lib import writer_identities
    from build.tools.check_writer_manifest_gate import evaluate_gate

    for identity in writer_identities.registered_identities():
        manifest_body = _manifest(identity, f"test-{identity}-001")
        staged = [
            "data/reference/schaff-herzog-encyclopedia.json",
            f"review/writer-manifests/test-{identity}-001.json",
        ]
        exit_code, messages = evaluate_gate(
            staged,
            load_manifest=lambda p, mb=manifest_body: mb if p.startswith("review/writer-manifests/") else None,
        )
        assert exit_code == 0, f"Identity {identity!r} should pass gate but blocked: {messages}"
