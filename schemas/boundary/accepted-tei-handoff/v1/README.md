# Accepted TEI handoff v1

This directory is a portable file boundary between EzraOCR and OCD. The
versioned JSON Schema is the contract; the package contains only package
relative byte/hash bindings and small evidence envelopes.

The contract carries the identity of one accepted TEI representation, its
source and acquisition evidence, the expected source member envelope, bounded
technical and review evidence, the representation revision, and separate agent
and human decision fields. It does not carry OCR editor state, OCD workflow or
publication state, executable imports, or a promotion instruction.

Compatibility rules:

1. A consumer validates the `schema_version` and `contract` before reading any
   other field.
2. A `v1` package is valid only when every referenced path is relative to the
   package root and its recorded byte count and SHA-256 match.
3. Additive fields require a new schema version because the contract is closed
   (`additionalProperties: false`). A new version may be accepted only after
   both repositories carry the same schema and fixtures.
4. A valid handoff is evidence for the declared scope. It is not a publication
   authorization, a rights clearance, a live-state update, or proof of human
   review. The fixture's human decision is deliberately `not-recorded`.

JSON objects must have unique field names, including objects in referenced
evidence. Every file binding uses portable package paths, including bindings
inside acquisition evidence.

The declared acceptance scope is bound to the source accounting and technical
proofs. A review may preserve broader reached or unreviewed context; that context
does not enlarge acceptance. Inspected loci must remain within the recorded
reached coverage. A partial human review may name a narrower scope, but a recorded
human rejection or block conflicts with agent acceptance, as in PIPE-004.
