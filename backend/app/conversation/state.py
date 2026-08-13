"""Session state: load, mutate, persist. Plan §10's "state lives in Postgres".

This module is the reason the plan skips Semantic Kernel and LangChain. A
framework would hold the conversation in memory; keeping it in
`generation_sessions` makes every run inspectable, resumable and auditable, and
means a server restart mid-demo costs nothing. That is a capability, not a
preference, and it is the answer to the "why no framework?" question the PS
invites.

Everything here is deliberately dull. The interesting decisions are upstream in
the four model stages; this is the part that must simply not lose anything.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conversation.planner import PlannedQuestion
from app.models.generation_session import GenerationSession
from app.models.question_plan import QuestionPlan

logger = logging.getLogger(__name__)

__all__ = [
    "SessionProgress",
    "load_question_plan",
    "record_turn",
    "save_question_plan",
    "session_questions",
]


@dataclass
class SessionProgress:
    """The derivation counter. `4 answers → 26 of 31 fields`.

    `fields_total` counts regions a conversation could ever fill -- editable and
    unprotected -- not every region in the document. Counting branding and the
    revision block in the denominator would understate the fill rate with
    regions nobody is allowed to touch.
    """

    answered: int
    total_questions: int
    fields_filled: int
    fields_total: int

    def as_dict(self) -> dict[str, int]:
        return {
            "answered": self.answered,
            "total_questions": self.total_questions,
            "fields_filled": self.fields_filled,
            "fields_total": self.fields_total,
        }


def save_question_plan(
    db: Session,
    version_id: uuid.UUID,
    questions: list[PlannedQuestion],
    *,
    planner_version: str,
) -> None:
    """Cache the plan for this version, replacing any earlier one.

    Replace rather than merge: `uq_question_plans_version_question` makes a
    partial overwrite a constraint violation, and a plan half from one planner
    version and half from another would be worse than either.
    """
    existing = db.execute(
        select(QuestionPlan).where(QuestionPlan.version_id == version_id)
    ).scalars().all()
    for row in existing:
        db.delete(row)
    db.flush()

    for question in questions:
        db.add(
            QuestionPlan(
                id=uuid.uuid4(),
                version_id=version_id,
                question_no=question.question_no,
                question_text=question.question_text,
                hint=question.hint,
                example=question.example,
                covers_regions=list(question.covers_regions),
                planner_version=planner_version,
            )
        )
    db.flush()


def load_question_plan(db: Session, version_id: uuid.UUID) -> list[PlannedQuestion]:
    """The cached plan for a version, or `[]`.

    A cache hit is what makes the second session against a document cost zero
    planner calls, and what keeps the questions stable when Bedrock is not
    reachable.
    """
    rows = (
        db.execute(
            select(QuestionPlan)
            .where(QuestionPlan.version_id == version_id)
            .order_by(QuestionPlan.question_no)
        )
        .scalars()
        .all()
    )
    return [
        PlannedQuestion(
            question_no=row.question_no,
            question_text=row.question_text,
            hint=row.hint,
            example=row.example,
            covers_regions=list(row.covers_regions or []),
        )
        for row in rows
    ]


def session_questions(session: GenerationSession, db: Session) -> list[PlannedQuestion]:
    return load_question_plan(db, session.base_version_id)


def record_turn(
    session: GenerationSession,
    *,
    question_id: str,
    question_text: str,
    answer: str,
    extracted: dict[str, Any],
    skipped: bool = False,
    degraded: bool = False,
) -> None:
    """Append one turn and merge its values into `filled_values`.

    The raw answer is stored **whether or not extraction worked**. A turn whose
    extractor call failed is not lost -- the user's words are on the record and
    can be re-extracted later, which is a far better outage story than asking
    them the same question twice.

    JSONB columns are reassigned rather than mutated in place: SQLAlchemy does
    not track mutation inside a JSONB value, and an in-place `append` would be
    silently discarded on commit. This has bitten this codebase before.
    """
    turns = list(session.turns or [])
    turns.append(
        {
            "question_id": question_id,
            "question_text": question_text,
            "answer": answer,
            "extracted": extracted,
            "skipped": skipped,
            "degraded": degraded,
        }
    )
    session.turns = turns

    if extracted:
        filled = dict(session.filled_values or {})
        filled.update(extracted)
        session.filled_values = filled

    session.current_step = len(turns)
