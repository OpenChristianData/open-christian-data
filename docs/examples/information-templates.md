# Current information template examples

Copy the applicable section into its existing owner. Fill evidenced facts;
leave unsupported values unknown. Executable schemas own machine field shapes.

## Acquisition queue cataloging

Use this for one proposed work or a clearly bounded collection. Search the
library and queue first; keep an existing lead ID when following up a lead.
Copy the block into the contribution issue. Maintainers retain its evidence
under `library/acquisition-research/<lead-id>.md` and bind the relevant lines
through the queue tool. Leave unknown fields blank and name the missing evidence.

```text
Title:
Existing lead ID / work ID, if any:
Author or attributed author, including any qualification:
Work scope: whole work, named part, or collection with its contents
Original language:

Copy being proposed
Edition title and language:
Translator, editor, or other credited contributors:
Historical publisher, place, year, volume, and edition statement:
Electronic provider and exact source URL:
Available format and extent: whole text, excerpt, scan, or transcription
Known omissions, OCR, or other source problems:

Evidence
Title page, catalog entry, contents, or other primary evidence and locator:
Rights statement and its exact URL; distinguish the edition from the provider:
Relationship to existing holdings: same work, different translation/copy, or unknown
What still needs checking:
Proposed next action:
Researcher and date:
```

The title identifies the work; the edition describes a particular translation
or publication; the source identifies the copy we can obtain. Record what the
source actually says, including disputed credits. An accessible file alone
does not establish completeness or permission to redistribute it.

The library queue, `library/acquisition-leads.jsonl`, owns current lead
disposition. For a **new lead**, use the existing tool to bind the completed
note; replace the example ID and line numbers with the real ones:

```powershell
py -3 -m build.tools.maintain_research_lead --root . --lead-id proposed-work --evidence-path library/acquisition-research/proposed-work.md --line-start 1 --line-end 25 add --intent "Identify and assess this source copy" --context "Text contribution proposal"
```

This is a dry run. Inspect the plan, then repeat with `--write` before `add`
when the queue change is authorized. The tool records the exact note bytes and
line extent. Do not add bibliography fields directly to the queue JSONL.
For an **existing lead**, attach the cataloging note to its issue with the
existing lead ID. Do not run `add` for that ID or rewrite its original claim.
The library lookup and generated acquisition list read the matching cataloging
note. Its evidence block binds the original lead and cited research bytes;
refresh those bindings when the evidence changes. Blank fields stay blank.
The research can stay open while facts are missing. Once identity is established,
put supported facts into the existing
[`work.json` model](../../schemas/v2/work.schema.json) and resolve the lead to
that work ID. Add an explicit identity decision and its supporting evidence to
the note, then bind those decision lines with the same tool:

```powershell
py -3 -m build.tools.maintain_research_lead --root . --lead-id existing-lead --evidence-path library/acquisition-research/existing-lead.md --line-start 26 --line-end 26 resolve --disposition promoted --work-id established-work
```

This is also a dry run; use the actual decision line extent, inspect the plan,
then add `--write` before `resolve` when authorized. A changed-claim hold needs
identity review before resolution. Promoting a lead records an identity link;
it does not accept text or clear rights.

The [public acquisition list](../ACQUISITIONS.md) is generated from library
records; editing that page does not update the queue.

## Bibliographic metadata decision

- Typed work/form/edition/component subject:
- Field semantics and vocabulary/term identifier:
- Literal source value and responsibility statement:
- Normalized value or unresolved mapping:
- Exact evidence path, digest and locator:
- Competing evidence and qualification:
- Inspection/adoption, actor and UTC date:
- Destination and unique authored decision owner:

Use the existing source-metadata decision format for persistence.

## Scoped rights

Use [subject JSON](rights-subject.json) and [assessment JSON](rights-record.json).
Record material, territory, result, basis, components, conditions and evidence.
Research stays linked; quality and upload approval retain their own records.

## Current task and completion

**Ticket ID:**
**Triage label:**
**Lifecycle:**
**Status:** concise narrative; do not put triage or lifecycle values here
**Task applicability:** current
**Owner:**
**Execution handle:** stable chat, agent or job locator
**Owned paths:**
**Baseline:** exact input revision or evidence snapshot
**Work ID:**
**Blocked by:**
**Next action:**
**Authorization:**
**Result:** changed behavior and remaining gaps; fill at handoff/completion

Add typed form/edition/acquisition/lead IDs when required. Triage uses the five
canonical labels separately from lifecycle (`open`, `in-progress`, `blocked`,
`complete`, `superseded`, `canceled`). Status retains explanatory wording.
Completion records changed behavior,
callers, check exits, evidence, execution/output homes, unresolved integration
and successor. Task completion does not establish publication or source acceptance.

## Source intake and attribution

- Work, form, edition and acquisition:
- Historical edition versus electronic provider:
- Original credits, role and scope:
- Retained source/member bindings and actual extent:
- Format, encoding, packaging and production disclosure:
- Rights assessment, exact terms and notices:
- Human-readable data-path notice and public destination:
- Unknown facts and evidence needed:

Keep complete item terms. A skeleton does not replace the actual source notice.

### Reader-facing source notice

State the copy's facts, credits, and actual reuse conditions directly. Keep
intake, review, and publication history in maintainer records. Preserve material
omissions and applicable source conditions, with required license texts verbatim.
Use only sections with something useful to say; combine repeated credits and terms.

**Title and author**

**Text and edition.** Give the translation, revision, abridgment and publication
details. Use normal bibliography wording, such as "New York: American Tract
Society, undated. Abridged by Benjamin Fawcett." Do not turn a missing date into
a paragraph about unperformed checks.

**Digital source.** Name and link the organization or project that supplied this
copy. Distinguish it from the original publisher.

**Credits.** List authors, translators, editors, transcribers, and other credited
contributors, with their actual roles. Identify a credit that applies only to
material outside the downloaded text; do not imply its inclusion.

**Reuse.** State the applicable terms in ordinary language, their territory and
the material they cover. Link the license. Include source-specific conditions
and acknowledgment requests without weakening or broadening them.

**Notes about this copy.** State actual omissions, transcription issues, or
differences users need to understand. Do not explain the definition of an
abridgment or list metadata fields that were empty.

**License text.** Put the actual required text here or link to its exact text
elsewhere in the same delivery. Never print instructions such as "include the
provider's complete notice" as if those were the notice. Identical license texts
may be shared through links. Present the current applicable terms once rather
than appending successive assessment histories.

Omit an empty section. Do not print hashes, local file paths, process receipts,
"public upload remains separate," or missing-field diagnostics in the ordinary
reading view. Those belong to the maintainer's evidence and release controls.

## Finding or friction

- Unique observation ID, originating task, UTC time:
- Affected subject and layer:
- Observed result and exact evidence:
- Hypothesis, distinguished from observation:
- Issue code/severity, scope and impact:
- Action/workaround and owner/destination:
- Disposition, verification scope and superseding observation:

Use the existing canonical append log and preserve its active-log exception.
Actual visual comparisons use the existing visual-review template.

## Release consumer documentation

- Release identity and selected scope:
- Fields, IDs and metadata lookup:
- Real examples for representative shapes:
- Language, download groups and exact item terms:
- Reader versions and normal/streaming evidence:
- Migration and retained older revision:
- Complete source-notice index:
- Exact outgoing manifest and actual publication result:

Generate mechanical fields from records and keep explanatory prose readable.
