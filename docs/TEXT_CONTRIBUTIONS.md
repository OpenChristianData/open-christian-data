# Contribute a text

Help us add faithful Christian texts. Start with the [acquisition and research
list](ACQUISITIONS.md), or suggest another text. A better source, a correction,
or an idea for the project is welcome too.

## Choose the text and copy

Search the current release catalog and public issues before starting. A work
can have several translations or editions; finding its title does not establish
that we have the copy you want to contribute. Open or join a
[source issue](https://github.com/OpenChristianData/open-christian-data/issues/new?template=source-proposal.md)
with the title, author, edition or translation, public source, and the work you
want to do. Include the acquisition-list ID when there is one. Confirm the
scope and assignment there so people do not unknowingly repeat the same work.

Use the [queue cataloging template](examples/information-templates.md#acquisition-queue-cataloging)
to describe the work and the copy you found. You can contribute this research
even when you are not offering to reconstruct the text.

## Give your agent the maintained workflow

Use [source-to-TEI](../.agents/skills/source-to-tei/SKILL.md), including its linked
references. This is the same skill used for the project's reconstructions, not
a separate contribution standard. A tool that supports repository-local skills
can discover it; otherwise give the agent the file directly:

> Follow `.agents/skills/source-to-tei/SKILL.md` for the text and exact copy agreed
> in this issue. Work in an isolated source/identity workspace. Produce a faithful
> TEI candidate, the required independent checks and review evidence, and a
> handoff that another reviewer can reopen. Explain any unavailable inputs or
> unresolved questions. Keep canonical installation and publication separate.

The skill explains source accounting, work boundaries, faithful mapping,
independent checking, challenges, reproduction, and visual review. Read the
[pipeline specification](OCD_LIBRARY_PIPELINE_SPEC.md) for the identities and
authority model, and [reconstruction contract](RECONSTRUCTION_CONTRACT.md) for
the maintained candidate interface.

## Set up and try the tools

Use Python 3.12. From the repository root on Windows:

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e .\ocd_kernel pytest
& .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_reconstruct_candidate.py::test_successful_handoff_is_deterministic_and_explicitly_nonaccepted tests/test_reconstruct_candidate.py::test_manifest_and_implementation_hash_drift_fail_before_destination_write tests/test_admit_accepted_work.py::test_command_admits_contrasting_source_shapes -v
```

On macOS or Linux, use `python3.12 -m venv .venv`, then
`.venv/bin/python -m pip install -e ./ocd_kernel pytest` and the same test arguments
with `.venv/bin/python -m pytest`. CVW's supported launcher is Windows-only.

These four fixture checks demonstrate the candidate and admission interfaces,
determinism and rejection of changed bindings. Their supplied converters,
reviews and decisions are test records. They do not reconstruct or accept a
new real text. Your text needs its own source-grounded checks under the skill.

Use the existing runner once the source-specific manifest and implementations
are ready:

```powershell
& .\.venv\Scripts\python.exe -m build.tools.reconstruct_candidate --manifest sources/<work>/<source-manifest.json> --destination <fresh-external-candidate-directory> --repository-root <source-and-identity-workspace>
```

The implementation comes from this checkout; `--repository-root` identifies
your source/identity workspace. The manifest binds retained source bytes,
profile, policy, schema, converter and independent validator. Use command help
and the skill to prepare those inputs. A new source format may need a converter
and independent reader; the runner does not invent them.

## Check it against the source

Use the skill's [visual verification procedure](../.agents/skills/source-to-tei/SKILL.md#visual-verification)
and the [CVW setup and launch guide](../cvw_app/README.md). Build its frontend
with the locked dependencies:

```powershell
& .\.venv\Scripts\python.exe -m pip install Pillow==12.0.0
Set-Location cvw_app
npm ci
npm run build
Set-Location ..
& .\.venv\Scripts\python.exe .\cvw_app\launch_windows.py --declared-library --repository-root <source-and-identity-workspace> --candidate-dir <candidate-directory> --port 0
```

CVW reads the declared work/acquisition sidecars in your workspace and the
validated candidate. It compares source and TEI; it does not accept or publish
them. The [review operations](SOURCE_TO_TEI_REVIEW_OPERATIONS.md) explain exact
identity, source reachability, capture evidence and findings. OCR production
and correction belong to EzraOCR; record that dependency when the source needs it.

## What to submit

Open a pull request linked to the work's issue. Include or provide an agreed
download location for the source files you may share, their hashes and source
locators, and the proposed work/edition/acquisition identities. Preserve source
credits and reuse terms; when source bytes cannot be redistributed, explain how
an authorized reviewer can obtain the exact copy.

Submit the source manifest, profile/policy/schema, converter and independent
validator implementations, checks and challenge results, plus the candidate:

```text
candidate/
  package/
    README.source.md
    content.tei.xml
    manifest.json
    provenance.json
    source-accountability.json
    unresolved.jsonl
  validation.json
  text-quality.json
```

Include reproduction commands, visual-review coverage and captured evidence,
findings and uncertain readings. Explain exclusions and any incomplete scope.
Keep a complete work together; a partial contribution must name what it covers
and what is still missing. Source meaning, source errors and your corrections
must remain distinguishable.

A maintainer or authorized agent reviews the evidence and handles canonical
admission using the [existing handoff](SOURCE_TO_TEI_REVIEW_OPERATIONS.md#accepted-master-administrative-handoff).
The issue or pull request remains the place for questions, revisions, the
decision and contributor credit. Technical acceptance, recorded human review,
reuse decisions and publication retain their actual separate status.

## Workspace and storage

A public checkout has the software and examples, not the project's private
research records or full production library. Use a task-owned workspace with
the agreed source and sidecars. Keep candidates in a fresh directory outside
repository `data`, `ir`, `raw`, `reports` and `exports`. Preserve retained source
bytes; fix generated output through its producer. Maintainer workspaces may
route durable storage through the configured library resolver. Use explicit
workspace roots rather than copying another machine's paths or configuration.
