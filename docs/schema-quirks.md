# Schema quirks

## catechism_qa has no enum on era / audience

The `catechism_qa` schema has NO enum constraint on `era` or `audience` — those fields are free-form. Don't write validation code or downstream classifiers that assume a fixed value set for these fields.

## build/lib/_generated_enums.py is generated — never edit manually

`build/lib/_generated_enums.py` is regenerated from schema sources. Edits made by hand are wiped on the next regeneration. If you need a new enum value, add it to the source schema and regenerate.

## Author registry encoding corruption — grep for `Ã`

`data/authors/registry.json` has known encoding corruption in some entries (UTF-8 bytes mis-decoded as Latin-1, producing `Ã` characters in author names). To find remaining corrupted entries:

```bash
grep '"Ã"' data/authors/registry.json
```

Past fixes have included Adamnán and Vincent of Lérins. New entries should be inspected after import.
