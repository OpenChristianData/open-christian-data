# Library pipeline real-source fixture

This fixture is a bounded, identity-preserving simulation of an accepted
library master. It does not accept or change any live master, candidate,
`library/works/**`, `raw/**`, `data/**`, `ir/**`, report, export, or publication
state.

## Bound source

- Work: Athanasius of Alexandria, *On the Incarnation of the Word*
- `work_id`: `athanasius-on-the-incarnation`
- Textual form: `athanasius-on-the-incarnation-prose`
- Edition/rendering: `ccel-npnf204`
- Source URL: `https://www.ccel.org/ccel/schaff/npnf204.xml`
- Retained source location: `raw/ccel/npnf2/npnf204.xml`
- Retained source bytes: `5,809,854`
- Retained source SHA-256: `bd625a0fa4f5ddd4b2fa13fcee753de8832ea4b316625e0e06454beb81cfa652`
- Source scope: `div1[@id='vii']`

The fixture master selects the complete source-native `div3[@id='vii.ii.i']`
section under `div2[@id='vii.ii']`, preserving its head, four direct
paragraph carriers, two nested note paragraph carriers, page break, display
span, inline markup, and two end notes. The
`retained/npnf204.vii.ii.i.thml.xml` member is the actual source-native ThML
section extracted from the retained source for conservation checks. Its fixture
bytes are `4,174` with SHA-256
`d16a6d825621cde9b93c5ed54489521895b9b9e44098b38bd61c437b927faafa`.
It is a bounded fixture payload, not a replacement for the retained
whole-source authority above.

The original acquisition access date was not retained by the historical source
evidence. Under the PIPE-003 contracts, `accessed_at` is absent. Public provenance
also omits that unknown fact. The state update timestamp records this fixture's
contract promotion, not historical source acquisition or real master acceptance.
Work identity evidence points to the known CCEL work; the representation revision
remains in the TEI header rather than being repeated in stable edition metadata.

The surrounding NPNF volume, `div1` front matter (`vii.i`), the remaining
`vii.ii` sibling sections (`vii.ii.ii` through `vii.ii.lvii`), and any source
material outside `div1[@id='vii']` are explicitly outside this fixture's bound.
Their absence is an intentional fixture exclusion, not a claim that the source
work is complete in this small test package.

## Review-pattern coverage

- RP-01: the selected section is nested in a larger NPNF volume and its
  enclosing/omitted carriers are declared above.
- RP-04: the readable TEI and source excerpt are inspected as structures; a
  matching blob or hash alone is not used as the fidelity claim.
- RP-06: the release checker recomputes row text and order independently from
  the receipt and rejects changed text/order.
- RP-11: logical source location, URL, byte count, and whole-source digest are
  bound in the acquisition sidecar and TEI source description.

The fixture is used only in temporary pytest output directories. Its public
projection contains prose rows; source hashes, local paths, sidecars, and
receipts remain private release evidence.
