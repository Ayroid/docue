"""Any valid input is accepted. No model, no database.

    uv run python scripts/test_open_input.py

The bug this suite pins down had three faces and one cause. The extractor's enum
was `question.covers_regions`, so:

  * anything a user said beyond the question was parsed against nothing and
    dropped in silence -- no chip, no warning, no record;
  * "change the heading" could not work at any phrasing, because `title` was
    `editable=False` and the conversation had no vocabulary for it;
  * an already-filled base document made it worse, because the context agent
    read last month's venue as settled and never asked.

Each check below drives the parsing layer with the payload a healthy model would
have returned, so what is under test is our contract rather than Bedrock's mood.

Covers:
  * a message supplies values beyond the asked cluster, and they are kept apart
  * the extractor's enum spans the whole addressable document
  * a heading is addressable but never askable, and never a deriver target
  * a heading is askable on a deck, where a slide title is content
  * an instruction turn does not advance the question pointer
  * a message that lands nowhere is reported, not swallowed
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.conversation.extractor import extract_answer  # noqa: E402
from app.conversation.scope import (  # noqa: E402
    addressable_ids,
    askable_ids,
    is_user_directed,
)
from app.conversation.planner import PlannedQuestion  # noqa: E402
from app.conversation.state import (  # noqa: E402
    TURN_ANSWER,
    TURN_INSTRUCTION,
    TURN_PREFILL,
    answered_count,
    freeze_ask_plan,
    session_questions,
)
from app.ingestion.detect import detect  # noqa: E402

FILES = Path(__file__).resolve().parent.parent.parent / "Files"
SOURCE = FILES / "MOM Sample.xlsx"

passed: list[str] = []


def ok(label: str, detail: str = "") -> None:
    passed.append(label)
    print(f"  PASS  {label}" + (f" -- {detail}" if detail else ""))


class _FakeSession:
    """Just enough of `GenerationSession` for `answered_count`."""

    def __init__(self, turns):
        self.turns = turns


def _scalar_ids(schema, ids):
    """Ids of plain single-valued regions, which take a `value` not `rows`."""
    by_id = {r.region_id: r for r in schema.regions}
    return [i for i in ids if by_id[i].kind in ("field", "field_empty")]


def _volunteered_is_kept(schema, ids) -> None:
    """A value for a region nobody asked about is captured, and labelled."""
    scalars = _scalar_ids(schema, ids)
    assert len(scalars) >= 2, "need two scalar regions in the MOM to tell the two apart"
    asked, aside = scalars[0], scalars[1]

    payload = {
        "entries": [
            {"region_id": asked, "value": "Room 2"},
            {"region_id": aside, "value": "Priya"},
        ]
    }
    with patch("app.conversation.extractor.complete_json", return_value=payload):
        result = extract_answer(
            schema,
            "Venue was Room 2, and Priya is chairing the next one.",
            [asked],
            also_regions=ids,
        )

    assert result.values == {asked: "Room 2"}, (
        f"the answered cluster is wrong: {result.values}"
    )
    assert result.volunteered == {aside: "Priya"}, (
        f"the volunteered half was dropped -- this is the whole bug: {result.volunteered}"
    )
    assert result.all_values == {asked: "Room 2", aside: "Priya"}, (
        "both halves must be written; only the reporting is split"
    )

    sources = {c["key"]: c["source"] for c in result.chips({})}
    assert sources[asked] == "answer" and sources[aside] == "volunteered", (
        f"chips do not distinguish asked from volunteered: {sources}"
    )
    ok("a volunteered value is kept and labelled", f"{asked} asked, {aside} volunteered")


def _enum_spans_the_document(schema, ids) -> None:
    """The model is offered every addressable region, not one cluster."""
    seen: dict = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        return {"entries": []}

    with patch("app.conversation.extractor.complete_json", side_effect=_capture):
        extract_answer(schema, "anything at all", [ids[0]], also_regions=ids)

    enum = seen["schema"]["properties"]["entries"]["items"]["properties"]["region_id"]["enum"]
    assert set(enum) == set(ids), (
        f"the enum offered {len(enum)} of {len(ids)} addressable regions; a value for "
        "any region outside it is unreachable and would be dropped in silence"
    )
    ok("the enum spans the whole addressable document", f"{len(enum)} regions")


def _headings_are_directable_not_askable(schema) -> None:
    """A heading may be set on request and proposed by nothing."""
    titles = [r for r in schema.regions if r.kind == "title"]
    assert titles, "no title region in the MOM to test against"

    addressable = set(addressable_ids(schema))
    askable = set(askable_ids(schema))

    for region in titles:
        assert region.region_id in addressable, (
            f"{region.region_id} is not addressable, so 'change the heading' has no "
            "region to name and cannot work at any phrasing"
        )
        assert region.region_id not in askable, (
            f"{region.region_id} is askable, so the planner can ask about a heading and "
            "the deriver can invent one -- the thing editable=False was protecting"
        )
        assert is_user_directed(schema, region), f"{region.region_id} is not user-directed"

    assert askable < addressable, "askable must be the strictly smaller set"
    ok(
        "headings are addressable but never askable",
        f"{len(titles)} title(s); {len(askable)} askable of {len(addressable)} addressable",
    )


def _decks_still_ask_about_slide_titles() -> None:
    """On a deck a title is the slide's content, and must stay in the interview."""

    class _Region:
        def __init__(self):
            self.region_id = "slide1.title"
            self.kind = "title"
            self.editable = True
            self.protected = False

    class _Schema:
        format = "pptx"
        regions = [_Region()]

    schema = _Schema()
    assert not is_user_directed(schema, schema.regions[0]), (
        "a slide title was excluded from the interview; decks would stop being asked "
        "for the one thing every slide has"
    )
    assert askable_ids(schema) == ["slide1.title"], "a slide title fell out of askable"
    ok("a deck still asks about its slide titles")


def _instruction_does_not_advance_the_interview() -> None:
    """An aside must not consume a question the user was never asked."""
    turns = [
        {"kind": TURN_ANSWER, "question_id": "q1"},
        {"kind": TURN_INSTRUCTION, "question_id": ""},
        {"kind": TURN_ANSWER, "question_id": "q2"},
    ]
    count = answered_count(_FakeSession(turns))
    assert count == 2, (
        f"answered_count is {count} over 3 turns; the instruction advanced the pointer "
        "and q3 would never be asked"
    )

    # Turns written before instructions existed carry no `kind` at all.
    legacy = [{"question_id": "q1"}, {"question_id": "q2"}]
    assert answered_count(_FakeSession(legacy)) == 2, (
        "a turn with no `kind` was not counted as an answer; every session started "
        "before this change would rewind its own interview"
    )
    ok("an instruction does not advance the question pointer", "2 answers of 3 turns")


def _unplaceable_input_is_visible(schema, ids) -> None:
    """A message that matches nothing must not look like a success."""
    with patch("app.conversation.extractor.complete_json", return_value={"entries": []}):
        result = extract_answer(schema, "please make it nicer", [ids[0]], also_regions=ids)

    assert result.ok, "an empty extraction is not an error, it is an empty result"
    assert not result.values and not result.volunteered, "expected nothing to be placed"
    assert result.chips({}) == [], "chips were rendered for values that do not exist"
    ok("input that lands nowhere produces no phantom chips")


def _ask_plan_narrows_but_never_drops(schema, ids) -> None:
    """Pasted notes shrink a question's cluster; they never delete the question.

    Dropping a fully-supplied question is the shorter interview and the wrong
    trade. The question that covers a region is the only place a mis-extraction
    becomes visible, so removing it deletes exactly the audit that would have
    caught it -- and there is no way to clear a filled value once it is in.
    """
    questions = [
        PlannedQuestion(question_no=1, question_text="Where and when?", covers_regions=ids[:2]),
        PlannedQuestion(question_no=2, question_text="Who was there?", covers_regions=ids[2:4]),
    ]
    frozen = freeze_ask_plan(questions, {ids[0], ids[2], ids[3]})
    rows = frozen["ask_plan"]

    assert len(rows) == 2, (
        f"a question was dropped; {len(rows)} of 2 survived. A fully-supplied "
        "question must still be shown so the user can check what was read."
    )
    assert rows[0]["covers_regions"] == [ids[1]], f"q1 not narrowed: {rows[0]}"
    assert rows[0]["prefilled_regions"] == [ids[0]], f"q1 lost its prefill echo: {rows[0]}"
    assert rows[1]["covers_regions"] == [], "q2 was fully supplied and should cover nothing"
    assert sorted(rows[1]["prefilled_regions"]) == sorted(ids[2:4]), f"q2: {rows[1]}"
    ok(
        "notes narrow a question without deleting it",
        f"q1 covers {rows[0]['covers_regions']}, q2 covers nothing but shows 2",
    )


def _frozen_plan_survives_a_replanned_version() -> None:
    """An in-flight interview must not be renumbered by somebody else's session.

    `save_question_plan` replaces a version's rows wholesale, and `POST
    /sessions` triggers exactly that whenever the cached plan is a structural
    fallback. Freezing indices would let the second session shorten the first
    one's list under a positional pointer; freezing payloads cannot.
    """
    session = _FakeSession([])
    session.known_context = freeze_ask_plan(
        [
            PlannedQuestion(question_no=1, question_text="Original one", covers_regions=["a"]),
            PlannedQuestion(question_no=2, question_text="Original two", covers_regions=["b"]),
        ],
        set(),
    )
    session.base_version_id = "irrelevant"

    class _ExplodingDb:
        """The frozen path must not touch the database at all."""

        def execute(self, *a, **k):
            raise AssertionError("session_questions hit the DB despite a frozen plan")

    got = session_questions(session, _ExplodingDb())
    assert [q.question_text for q in got] == ["Original one", "Original two"], got
    assert [q.question_no for q in got] == [1, 2], "numbering drifted"
    ok("a frozen plan is read without touching the version cache", f"{len(got)} questions")


def _prefill_turn_does_not_advance_the_interview() -> None:
    """Pasting notes must not consume question 1."""
    turns = [
        {"kind": TURN_PREFILL, "question_id": ""},
        {"kind": TURN_ANSWER, "question_id": "q1"},
        {"kind": TURN_INSTRUCTION, "question_id": ""},
    ]
    count = answered_count(_FakeSession(turns))
    assert count == 1, (
        f"answered_count is {count} over 3 turns; the pasted notes consumed a "
        "question the user was never shown"
    )
    ok("pasted notes do not advance the question pointer", "1 answer of 3 turns")


def main() -> int:
    if not SOURCE.exists():
        print(f"SKIP: corpus file not on this machine: {SOURCE.name}")
        return 0

    schema = detect(SOURCE.read_bytes(), "xlsx")
    ids = addressable_ids(schema)
    print(f"Open input, {SOURCE.name} ({len(ids)} addressable regions):\n")

    print("Extractor:")
    _volunteered_is_kept(schema, ids)
    _enum_spans_the_document(schema, ids)
    _unplaceable_input_is_visible(schema, ids)

    print("\nScope:")
    _headings_are_directable_not_askable(schema)
    _decks_still_ask_about_slide_titles()

    print("\nState:")
    _instruction_does_not_advance_the_interview()
    _prefill_turn_does_not_advance_the_interview()

    print("\nPasted notes:")
    _ask_plan_narrows_but_never_drops(schema, ids)
    _frozen_plan_survives_a_replanned_version()

    print(f"\nOK - {len(passed)} checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
