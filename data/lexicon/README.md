# Historical English lexicon

This directory holds the historical English lexicon (`archaic_forms_en.json`)
used by the project's checking and modernization tools to recognize archaic
names and spellings in the texts.

The lexicon supports the collection; it is not itself a category of Christian
text. It is not published as a Hugging Face dataset configuration and is not
counted in the public category totals.

Related tooling:

- `build/lib/warning_producers/historical_lexicon.py` — flags historical
  spelling and naming variants in records.
- `build/tools/lexicon_coverage_report.py` — reports lexicon coverage.
