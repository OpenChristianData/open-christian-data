# Document Classification Log

Records rationale for non-obvious `document_kind` and `tradition` assignments in
`creeds_json_confession.py` and `creeds_json_catechism.py`. The code is the canonical
source; `tradition_notes` on each DOCUMENT_CONFIGS entry has the routine rationale.
Only add an entry here when a classification would look wrong to a future reviewer
without knowing the decision history.

---

## Five Scripture-passage creeds — removed on rights grounds, not classification grounds

Removed from `DOCUMENT_CONFIGS` and from `data/doctrinal-documents/`:

- `christ_hymn_of_colossians` = Col 1:15-19
- `christ_hymn_of_philippians` = Phil 2:6-10
- `christian_shema` = 1 Cor 8:6 (the Pauline expansion of the Shema)
- `confession_of_peter` = Matt 16:16
- `shema_yisrael` = Deut 6:4-5 (the Jewish original)

Upstream Creeds.json supplies the text of all five from the ESV
(`esv.literalword.com`), a copyrighted modern translation, and the exported records
carried `cc0-1.0` labels that the ESV text does not support. Unlike the composed
creeds, these five are bare Scripture passages: the wording is wholly the modern
translation's, so there is no public-domain source text underneath to fall back on.
Every passage is already present in the CC0 Berean Standard Bible under `bible_text`,
so removal costs the collection no text — only the editorial identification of these
passages as creedal fragments.

Their classification was never in question and the earlier reasoning still holds:
`shema_yisrael` was once excluded as out-of-scope (Jewish, not Christian), then
reinstated because Jesus cites Deut 6:4-5 as the greatest commandment (Mark 12:29),
making it foundational to Christian theology. To restore any of the five, re-source the
wording from a public-domain or CC0 translation; `creed, ecumenical` remains the right
classification.

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
