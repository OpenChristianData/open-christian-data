# Contributing to Open Christian Data

Help us add more Christian texts. You can find a reliable source, prepare a
faithful digital copy with our tools, or check a reconstruction against its
source. Better metadata, software fixes, documentation and other ideas are
welcome too.

## Add or improve a text

Start with the [acquisition and research list](docs/ACQUISITIONS.md), or suggest
another work. Check the exact edition or translation against the current release
catalog and existing issues, then open or join a
[source issue](https://github.com/OpenChristianData/open-christian-data/issues/new?template=source-proposal.md).
Say what you want to contribute and confirm the scope before substantial work.
The list is a dated view of recorded work and research; it is not a live claim board.

Follow the [text contribution workflow](docs/TEXT_CONTRIBUTIONS.md). It provides
the same [source-to-TEI skill](.agents/skills/source-to-tei/SKILL.md) and tools
used by the project, setup commands, the candidate/evidence package to submit,
and the visual-review route. Your agent can use that skill directly. A small
complete work is a useful first reconstruction; partial work is welcome when
its scope and remaining gaps are explicit.

A source suggestion can be an issue without a reconstruction. Give the title,
edition or translation, public source link and exact page, section or record
supporting the suggestion. An OCD identifier helps when known but is not required.
For a metadata correction, explain the fact to change and the source evidence.
Include relevant reuse terms and requested source credits.

## Software, documentation and other ideas

Open an issue for a larger change so people can coordinate. A small documentation
correction can go straight to a pull request. Use the
[software/documentation issue template](https://github.com/OpenChristianData/open-christian-data/issues/new?template=software-docs-bug.md)
for a reproducible problem; other ideas can start as a general issue.

Use Python 3.12. This small setup installs the kernel and pytest:

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e .\ocd_kernel pytest
& .\.venv\Scripts\python.exe -m build.validate data/bible-text/bsb/genesis.json
& .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_library_simplification.py::test_incomplete_lookup_preserves_alternatives_and_hold_reason -v
```

On macOS or Linux, use `python3.12 -m venv .venv` and `.venv/bin/python`
in place of the Windows interpreter path. Run the smallest additional check
covering your change. For documentation-only corrections, explain that no code
test was needed. The example test uses simulated records, not real text acceptance.

Fork the [public repository](https://github.com/OpenChristianData/open-christian-data),
make your change on a branch, and open a pull request back to it. Generated
`data/` JSON is an output: fix its source or producer and regenerate it. OCR
production belongs to EzraOCR; use a source issue when you need help routing it.
Share only files you may redistribute, and keep credentials and private material
out of issues and pull requests.

## Review and credit

A maintainer will review the evidence and checks, then reply on the issue or
pull request. If more work is needed, we will explain what to change. A proposal
may also be declined or deferred with a reason. We cannot promise a response time.

The public repository is generated from our production repository. We integrate
accepted contributions there, retain your authorship or requested credit, and
include the change in a later public update. A passing test or a change in
someone else's fork does not establish acceptance or publication.

The code license and each text's recorded reuse terms continue to apply.
Contributing does not broaden either. Please be specific and respectful when
discussing evidence or revisions. For a conduct concern that should not be posted
publicly, email `openchristiandata@gmail.com`.
