# Church Fathers verse-reference quotations retained-source route

This route binds the `church-fathers-quotations` catalog work to the complete
retained Commentaries-Database member envelope. The historical
`Commentaries-Database.tar` contains 59,021 members (58,682 regular files,
339 directories, and 58,675 TOML files) and has SHA-256
`5a4ba3ef4bfd168cdaf4cd6bcc4e8cc655c90da97bfe5abf3e6fe9338d86fbe6`.

The canonical retained source is the extracted
`raw/Commentaries-Database` tree. `source-member-equality.json` records the
archive member order, every member byte hash, and the byte-for-byte equality
check against that tree. TOML members are primary source authorities; the
archive receipt and member-equality file preserve the container and extraction
lineage. Repository metadata and cache files outside the recovered member set
are accounted for as excluded tree extras.

The route projects each retained metadata object and commentary record to a
nonaccepted TEI candidate in archive order. It preserves the source's TOML
field names, order, values, and integer/string types. The 325 existing JSON
files are catalog derived-output claims linked through the manifest's explicit
`catalog_claim_lineage`; they are not textual source authority.

The retained `LICENSE` says that the source is public domain and requires no
attribution, while warning that a small number of quotations may originate
from copyrighted translations. That source assertion is preserved for human
rights review. No authorship, edition, date, translator, or publication claim
is added here. Human textual acceptance, rights clearance, and publication
authorization remain separate and unresolved.
