"""Shared text analysis for Knowledge retrieval (v1 claim registry and entry search).

One analyzer, one behavior: both stores tokenize identically so a term that finds a fact in
one layer finds it in the other. The rules exist because Salesforce identifiers and Polish
prose both break naive tokenizers:

- the exact scoped symbol survives (`engagement__c.status__c`), so an API name is findable
  as written rather than shredded into `c`;
- the Salesforce suffix (`__c`, `__r`, `__e`, `__mdt`, …) is indexed as its own signal;
- camelCase, snake_case and dotted paths also yield their component words;
- diacritics are preserved AND a folded alias is added, including for letters that carry no
  combining mark under NFD (Polish `ł`, `đ`, `ø`, `ß`, …) — those survive normalization
  untouched and would otherwise make `wlasciwej` fail to match `właściwej`.
"""

from __future__ import annotations

import re
import unicodedata

ANALYZER_VERSION = "1.0.0"

CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
SF_SUFFIX = re.compile(r"__(c|r|e|mdt|b|x|kav|s|hd|share|history)$", re.IGNORECASE)
SEPARATORS = re.compile(r"[\s,;:/\\()\[\]{}<>\"'`|!?]+")
STROKE_FOLDING = str.maketrans(
    {
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
        "ø": "o",
        "Ø": "O",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ß": "ss",
    }
)


def fold_diacritics(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.translate(STROKE_FOLDING))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def analyze(value: str) -> list[str]:
    """Tokens for one text value: exact symbols, component words, and folded aliases."""
    text = unicodedata.normalize("NFKC", value)
    tokens: list[str] = []
    for raw in SEPARATORS.split(text):
        if not raw:
            continue
        symbol = raw.strip(".-").casefold()
        if not symbol:
            continue
        tokens.append(symbol)
        # Dotted segments split first so the Salesforce suffix is still attached when it is
        # detected; splitting on "_" up front would destroy `__c` before it can be indexed.
        for segment in re.split(r"\.+", CAMEL_BOUNDARY.sub(" ", raw)):
            segment = segment.strip().casefold()
            if not segment:
                continue
            suffix = SF_SUFFIX.search(segment)
            if suffix:
                tokens.append(suffix.group(0))
                segment = SF_SUFFIX.sub("", segment)
            for word in re.split(r"[_\s]+", segment):
                if not word:
                    continue
                tokens.append(word)
                folded_word = fold_diacritics(word)
                if folded_word != word:
                    tokens.append(folded_word)
        folded = fold_diacritics(symbol)
        if folded != symbol:
            tokens.append(folded)
    return [token for token in tokens if token]
