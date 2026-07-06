"""TEI intermediate-representation tooling (ADR-0019).

Raw source -> TEI IR -> projections. This package owns the raw-source census
(the raw->TEI fidelity oracle), the TEI writers, and the projection/ledger
machinery. It is a pipeline stage, not a data/ parser, so it lives beside
build/parsers/ rather than in it.
"""
