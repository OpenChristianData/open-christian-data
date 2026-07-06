from __future__ import annotations


def test_allow_case_with_registered_identity():
    from build.lib import writer_identities
    from build.tools.check_writer_manifest_gate import evaluate_gate

    assert writer_identities.is_authorised("ia_schaff_herzog_parser")

    manifest_body = {
        "writer_identity": "ia_schaff_herzog_parser",
        "run_id": "test-allow-case-001",
        "data_paths": ["data/reference/schaff-herzog-encyclopedia.json"],
    }
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
        manifest_body = {
            "writer_identity": identity,
            "run_id": f"test-{identity}-001",
            "data_paths": ["data/reference/schaff-herzog-encyclopedia.json"],
        }
        staged = [
            "data/reference/schaff-herzog-encyclopedia.json",
            f"review/writer-manifests/test-{identity}-001.json",
        ]
        exit_code, messages = evaluate_gate(
            staged,
            load_manifest=lambda p, mb=manifest_body: mb if p.startswith("review/writer-manifests/") else None,
        )
        assert exit_code == 0, f"Identity {identity!r} should pass gate but blocked: {messages}"
