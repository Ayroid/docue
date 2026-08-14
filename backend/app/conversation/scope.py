"""Which regions a conversation may ask about, and which it may write.

Two sets, and the gap between them is the whole point of this module.

**`askable(schema)`** is what the interview covers. The context agent buckets
these, the planner asks about these, the deriver fills these. Nothing outside it
is ever *offered* to a model as somewhere to put content, so nothing outside it
can be filled by a model that decided a value was expected.

**`addressable(schema)`** is larger. It is every region a user may explicitly
direct a value into, including regions the interview deliberately never raises.

A heading is the case that motivates the split. "Change the heading to Q3
Review" is a reasonable instruction and used to be impossible -- `title` was
`editable=False` in the xlsx and docx detectors, so the conversation had no
vocabulary for it at all. But "invent a heading because one was expected" is
precisely what a non-editable heading was protecting against. Making the set the
*user* can reach wider than the set a *model* is offered gets both: the
instruction lands, and no stage fills a heading nobody asked to change.

Protected regions are in neither set and are not reachable from here by any
route. Branding, formulas, the Instruction sheet and anything unclassified are
refused by the compiler's pre-flight as well, which is the guarantee this module
is layered on top of rather than a replacement for it.
"""

from typing import Any

__all__ = [
    "USER_DIRECTED_KINDS",
    "addressable",
    "addressable_ids",
    "askable",
    "askable_ids",
    "is_user_directed",
]

# Kinds a user may set by saying so, but that no stage may raise on its own.
#
# `title` only. A heading names the document; changing it is a decision, and a
# decision is something a person makes and an interview does not make for them.
USER_DIRECTED_KINDS = frozenset({"title"})

# ...except on a deck, where a slide title *is* the slide's content and always
# has been askable -- `pptx_regions.py` marks it `editable=True` for exactly
# that reason. Excluding it here would silently drop slide titles out of the
# interview that fills them.
_ASKS_TITLES = frozenset({"pptx"})


def is_user_directed(schema: Any, region: Any) -> bool:
    """True if this region is writable only on an explicit instruction."""
    if getattr(schema, "format", None) in _ASKS_TITLES:
        return False
    return region.kind in USER_DIRECTED_KINDS


def addressable(schema: Any) -> list[Any]:
    """Every region any part of the conversation may write.

    Editable and unprotected. This is the extractor's vocabulary: the set of
    `region_id`s a user's own words are allowed to name.
    """
    return [r for r in schema.regions if r.editable and not r.protected]


def askable(schema: Any) -> list[Any]:
    """The regions the interview may raise and the deriver may fill.

    `addressable` minus the user-directed kinds. Passed to the context agent,
    which is why a heading never reaches the planner or the deriver: neither
    stage is ever shown one.
    """
    return [r for r in addressable(schema) if not is_user_directed(schema, r)]


def addressable_ids(schema: Any) -> list[str]:
    return [r.region_id for r in addressable(schema)]


def askable_ids(schema: Any) -> list[str]:
    return [r.region_id for r in askable(schema)]
