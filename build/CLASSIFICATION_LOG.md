# Document Classification Log

Records rationale for non-obvious `document_kind` and `tradition` assignments in
`creeds_json_confession.py` and `creeds_json_catechism.py`. The code is the canonical
source; `tradition_notes` on each DOCUMENT_CONFIGS entry has the routine rationale.
Only add an entry here when a classification would look wrong to a future reviewer
without knowing the decision history.

---

## `shema_yisrael` vs `christian_shema` — two documents, both included

These are distinct source files in Creeds.json:
- `christian_shema` = 1 Cor 8:6 (the Pauline expansion of the Shema)
- `shema_yisrael` = Deut 6:4-5 (the Jewish original)

`shema_yisrael` was initially excluded as out-of-scope (Jewish, not Christian). Reversed:
Jesus cites Deut 6:4-5 as the greatest commandment (Mark 12:29), making it foundational
to Christian theology. Both classified as `creed, ecumenical`.

## `canons_of_dort` and `council_of_orange` — `canon`, not `confession`

Both use `document_kind: canon`. They are synodal canons (formal resolutions of church
councils), not confessions of faith. Dort defines the five points of Calvinism; Orange
addresses semi-Pelagianism. Calling them confessions would misrepresent their genre.

## `chalcedonian_definition` — `declaration`, not `creed`

It is a conciliar definition of Christ's two natures, not a credal formula for liturgical
use. "Declaration" better represents that it was a doctrinal ruling, not a statement of
faith recited by congregations.

## `waldensian_confession` — classified `reformed` despite pre-Reformation origins

The Waldensian movement predates the Reformation but formally aligned with Reformed
churches at the Synod of Chanforan (1532), adopting the Reformed confession. `reformed`
is accurate for the document as received.

## `westminster_larger_catechism` — audience `clergy`, not `lay`

The WLC was designed for ministerial use and public teaching, not lay memorisation
(that role belongs to the WSC). Audience `clergy` is intentional and correct.
