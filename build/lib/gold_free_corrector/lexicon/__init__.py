"""Gold-free lexicality support for the corrector."""

from build.lib.gold_free_corrector.lexicon.build_lexicon import (
    ConsensusLexicon,
    build_lexicon_from_wct_pages,
    lexicon_from_dict,
)

__all__ = ["ConsensusLexicon", "build_lexicon_from_wct_pages", "lexicon_from_dict"]
