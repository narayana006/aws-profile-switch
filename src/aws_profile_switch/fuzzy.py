"""Rank profile names against a short query.

Each whitespace-separated word of the query must match the name. A word
matches, from best to worst, as: the whole name, a prefix, the start of a
word inside the name (after - _ . / :), any substring, or a subsequence
(letters in order with gaps). Matching ignores case.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

EXACT, PREFIX, WORD_START, SUBSTRING, SUBSEQUENCE = range(5)
SEPARATORS = "-_./:@ "


def _subsequence_span(word: str, name: str) -> Optional[int]:
    """Length of the shortest stretch of `name` found greedily that contains `word` in order."""
    best = None
    for start in range(len(name)):
        if name[start] != word[0]:
            continue
        pos = start
        for char in word[1:]:
            pos = name.find(char, pos + 1)
            if pos < 0:
                break
        else:
            span = pos - start + 1
            best = span if best is None else min(best, span)
    return best


def score_word(word: str, name: str) -> Optional[tuple[int, int]]:
    """Return (match class, tie-break) for one query word, or None if it does not match."""
    word, name = word.lower(), name.lower()
    if word == name:
        return (EXACT, 0)
    if name.startswith(word):
        return (PREFIX, len(name))
    index = name.find(word)
    while index > 0:
        if name[index - 1] in SEPARATORS:
            return (WORD_START, len(name))
        index = name.find(word, index + 1)
    if word in name:
        return (SUBSTRING, len(name))
    span = _subsequence_span(word, name)
    if span is not None:
        return (SUBSEQUENCE, span)
    return None


def score(query: str, name: str) -> Optional[tuple[int, int]]:
    words = query.split()
    if not words:
        return (SUBSTRING, 0)
    total_class = total_tie = 0
    for word in words:
        result = score_word(word, name)
        if result is None:
            return None
        total_class += result[0]
        total_tie += result[1]
    if len(words) == 1:
        return (total_class, total_tie)
    # Several words can never add up to an exact match of the whole name.
    return (max(total_class, PREFIX), total_tie)


def rank(query: str, names: Iterable[str], last_used: Mapping[str, float]) -> list[tuple[str, tuple]]:
    """Matching names, best first. Ties go to the most recently used, then alphabetical."""
    scored = []
    for name in names:
        result = score(query, name)
        if result is not None:
            scored.append((name, (result[0], -last_used.get(name, 0.0), result[1], name)))
    scored.sort(key=lambda item: item[1])
    return scored


def choose(ranked: list[tuple[str, tuple]]) -> tuple[Optional[str], list[str]]:
    """Pick the winner, or return (None, candidates) when the choice is not clear.

    The top result wins if it is an exact match, the only result, in a better
    match class than the runner-up, or more recently used than the runner-up.
    """
    if not ranked:
        return None, []
    if len(ranked) == 1 or ranked[0][1][0] == EXACT:
        return ranked[0][0], []
    first, second = ranked[0][1], ranked[1][1]
    if first[:2] != second[:2]:
        return ranked[0][0], []
    tied = [name for name, key in ranked if key[:2] == first[:2]]
    return None, tied
