"""Build a gold-free word lexicon from raw WCT candidate attestation."""

from __future__ import annotations

import csv
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from build.lib.wct_builder import confusion_distance

_WCT_SCHEMA_VERSION = "word-confusion-table-v1"
_SOURCE_KIND = "raw-wct-candidate-attestation"


@dataclass(frozen=True)
class ConsensusLexicon:
    """Queryable, serializable word lexicon for P2 lexicality rescoring."""

    words: frozenset[str]
    languages: tuple[str, ...]
    dictionary_source: str | None
    dictionary_word_count: int
    distance_function: str = "build.lib.wct_builder.confusion_distance"

    def is_word(self, token: str) -> bool:
        """Return membership for the grouping-normalized token form."""
        return _normalise_word(token) in self.words

    def nearest(self, token: str, max_distance: float) -> list[tuple[str, float]]:
        """Return lexicon words within the bounded WCT confusion distance."""
        query = _normalise_word(token)
        matches = [
            (word, confusion_distance(query, word))
            for word in self.words
        ]
        return sorted(
            (item for item in matches if item[1] <= max_distance),
            key=lambda item: (item[1], item[0]),
        )

    def to_dict(self) -> dict:
        return {
            "schema_type": "gold_free_consensus_lexicon",
            "schema_version": "gold-free-consensus-lexicon-v1",
            "languages": list(self.languages),
            "dictionary_source": self.dictionary_source,
            "dictionary_word_count": self.dictionary_word_count,
            "distance_function": self.distance_function,
            "sources": {
                "wct_consensus": _SOURCE_KIND,
                "dictionary": self.dictionary_source,
            },
            "words": sorted(self.words),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def build_lexicon_from_wct_pages(
    wct_pages: Iterable[dict],
    *,
    dictionary_headwords: Iterable[str] | str | Path | None = None,
    dictionary_source: str | None = None,
    languages: Iterable[str] = (),
) -> ConsensusLexicon:
    """Build a lexicon from raw WCT pages plus an optional vetted PD headword source."""
    consensus_words = _consensus_words(wct_pages)
    dictionary_words = frozenset(_dictionary_words(dictionary_headwords))
    return ConsensusLexicon(
        words=frozenset(sorted(consensus_words | dictionary_words)),
        languages=tuple(sorted({_normalise_language(language) for language in languages})),
        dictionary_source=dictionary_source if dictionary_headwords is not None else None,
        dictionary_word_count=len(dictionary_words),
    )


def lexicon_from_dict(artifact: dict) -> ConsensusLexicon:
    return ConsensusLexicon(
        words=frozenset(str(word) for word in artifact["words"]),
        languages=tuple(str(language) for language in artifact.get("languages", [])),
        dictionary_source=artifact.get("dictionary_source"),
        dictionary_word_count=int(artifact.get("dictionary_word_count", 0)),
        distance_function=str(
            artifact.get("distance_function", "build.lib.wct_builder.confusion_distance")
        ),
    )


def write_lexicon(lexicon: ConsensusLexicon, path: str | Path) -> None:
    target = Path(path)
    target.write_text(lexicon.to_json() + "\n", encoding="utf-8")


def read_lexicon(path: str | Path) -> ConsensusLexicon:
    source = Path(path)
    return lexicon_from_dict(json.loads(source.read_text(encoding="utf-8")))


def _consensus_words(wct_pages: Iterable[dict]) -> frozenset[str]:
    words: set[str] = set()
    for page in wct_pages:
        _require_raw_wct_page(page)
        for position in page.get("positions", []):
            for candidate in position.get("candidate_set", []):
                key = _normalise_word(str(candidate.get("candidate_key", "")))
                families = {
                    _normalise_family(str(family))
                    for family in candidate.get("attesting_families", [])
                }
                if len(families) >= 2 and _eligible_word(key):
                    words.add(key)
    return frozenset(words)


def _dictionary_words(headwords: Iterable[str] | str | Path | None) -> Iterator[str]:
    if headwords is None:
        return
    if isinstance(headwords, (str, Path)):
        path = Path(headwords)
        yield from _dictionary_words_from_path(path)
        return
    for headword in headwords:
        word = _normalise_word(str(headword))
        if _eligible_word(word):
            yield word


def _dictionary_words_from_path(path: Path) -> Iterator[str]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if not row:
                    continue
                word = _normalise_word(row[0])
                if _eligible_word(word):
                    yield word
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        word = _normalise_word(line.strip())
        if _eligible_word(word):
            yield word


def _require_raw_wct_page(page: dict) -> None:
    if page.get("schema_version") != _WCT_SCHEMA_VERSION or "positions" not in page:
        raise ValueError("lexicon input must be a raw WCT page")


def _normalise_word(token: str) -> str:
    return unicodedata.normalize("NFKC", token).casefold()


def _normalise_language(language: str) -> str:
    return unicodedata.normalize("NFKC", str(language)).casefold()


def _normalise_family(family: str) -> str:
    value = unicodedata.normalize("NFKC", family).casefold()
    if value == "kraken-greek":
        return "kraken"
    return value


def _eligible_word(word: str) -> bool:
    return len(word) >= 3 and word.isalpha()
