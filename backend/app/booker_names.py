"""Booker name normalisation — ONE definition, shared by every booker report.

``mcleod_gld_order_post_hist.posted_by_name`` is free text typed by McLeod
users. The same person surfaces as ``EUGENIO MIRANDA``, ``Eugenio Miranda`` and
occasionally ``Miranda, Eugenio``; accents come and go; compound surnames are
written with and without a space (``SAN MIGUEL`` / ``SANMIGUEL``). Any roster
supplied by a stakeholder is therefore matched on a normalised form, never on
string equality.

Extracted 2026-08-31 from ``routers/podium_top.py``, which has carried this
since the 2026-06-09 "Bookers vs All DFW" round. Both consumers now read the
same tables so a fix to the accent map cannot land in one report only (§69):

* ``routers/podium_top.py``      — the 14-name DFW Podium roster
* ``routers/booker_scorecard.py`` — the 15-name Rank roster (Bruno 2026-08-31)

⚠ The two ROSTERS are deliberately different lists of people, and must stay
that way — they overlap on 10 names but each carries 4-5 the other does not.
Only the *normalisation* is shared. Merging the rosters would silently rewrite
who each report is about.

⚠ Normalisation is a MATCHING key, never a display value. Every report shows
the name McLeod actually recorded, so a person who is missing from a roster is
visibly missing rather than silently renamed.
"""

from __future__ import annotations

import re

# Lowercase + strip accents + keep [a-z] only. Kept as a translate() pair
# because the same map is interpolated into SQL by podium_top's
# ``_NORM_POSTED_BY`` — a Python-only implementation there would have made the
# two sides of that report disagree about who is on the roster.
ACCENTS_FROM = "áàäâãåÁÀÄÂÃÅéèëêÉÈËÊíìïîÍÌÏÎóòöôõÓÒÖÔÕúùüûÚÙÜÛñÑçÇ"
ACCENTS_TO = "a" * 12 + "e" * 8 + "i" * 8 + "o" * 10 + "u" * 8 + "n" * 2 + "c" * 2
assert len(ACCENTS_FROM) == len(ACCENTS_TO)

_ACCENT_MAP = str.maketrans(ACCENTS_FROM, ACCENTS_TO)


def name_tokens(name: str) -> list[str]:
    """A name split into lowercase, unaccented, letters-only tokens."""
    if not name:
        return []
    plain = name.translate(_ACCENT_MAP).lower()
    return [t for t in (re.sub(r"[^a-z]", "", p) for p in plain.split()) if t]


def name_key(name: str) -> str:
    """A whitespace-insensitive match key: every letter, in order.

    ``"Andres Sanmiguel"`` and ``"ANDRES SAN MIGUEL"`` collapse to the same
    key, which is the compound-surname case that broke the first roster.

    ⚠ Deliberately NOT order-insensitive. Sorting the tokens would make
    ``"Rodriguez, Jonathan"`` match ``"Jonathan Rodriguez"`` — desirable — but
    would also collide distinct people whose names are anagrams of one another
    across the first/last split, which is exactly the class of silent merge
    §83 is about. ``matches_roster`` handles the reversed form explicitly.
    """
    return "".join(name_tokens(name))


def matches_roster(name: str, roster_keys: set[str]) -> bool:
    """True when ``name`` is one of the roster entries in ``roster_keys``.

    Tries the name as written and with its first/last tokens swapped, so the
    ``"Montoya, Anthares"`` spelling McLeod sometimes records still resolves.
    """
    toks = name_tokens(name)
    if not toks:
        return False
    if "".join(toks) in roster_keys:
        return True
    if len(toks) >= 2 and "".join([toks[-1], *toks[:-1]]) in roster_keys:
        return True
    return "".join([*toks[1:], toks[0]]) in roster_keys


def roster_keys(names) -> set[str]:
    """Match keys for a roster, for use with :func:`matches_roster`."""
    return {name_key(n) for n in names if name_key(n)}
