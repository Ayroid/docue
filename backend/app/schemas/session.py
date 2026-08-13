"""Request and response shapes for the fill conversation. Plan §6.

The frontend's `/templates/:id/generate` screen is built against these: chat on
the left from `question` and `turns`, live preview on the right from `spec`, and
the derivation counter from `progress`.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.change_spec import ChangeSpec, Tier


class QuestionOut(BaseModel):
    """One planned question and the regions it supplies.

    `covers_regions` is exposed rather than kept server-side because the live
    preview highlights exactly those regions while the user is typing -- it is
    what makes the document visibly respond to the answer in progress.
    """

    question_id: str
    question_no: int
    question_text: str
    hint: str | None = None
    example: str | None = None
    covers_regions: list[str] = Field(default_factory=list)


class ProgressOut(BaseModel):
    """The derivation counter: `4 answers → 26 of 31 fields`."""

    answered: int
    total_questions: int
    fields_filled: int
    fields_total: int


class TurnOut(BaseModel):
    question_id: str
    question_text: str
    answer: str
    extracted: dict[str, Any] = Field(default_factory=dict)
    skipped: bool = False
    degraded: bool = Field(
        default=False, description="The extractor was unavailable; the raw answer was kept."
    )


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: uuid.UUID
    version_id: uuid.UUID | None = Field(
        default=None, description="Defaults to the template's current version."
    )
    intent: str | None = Field(
        default=None, description="What the user is trying to produce, in their words."
    )
    tier: Tier = "T2"


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    answer: str = ""
    skip: bool = Field(
        default=False,
        description="Move on without answering. The regions stay untouched, visibly.",
    )


class ChipOut(BaseModel):
    """What the extractor pulled out, for the chip row under the user's message."""

    key: str
    value: str


class AnswerOut(BaseModel):
    session_id: uuid.UUID
    extracted: dict[str, Any] = Field(default_factory=dict)
    chips: list[ChipOut] = Field(default_factory=list)
    derived: dict[str, Any] = Field(
        default_factory=dict,
        description="Populated on the final turn: the deriver runs once, not per answer.",
    )
    next_question: QuestionOut | None = None
    progress: ProgressOut
    degraded: bool = False
    warnings: list[str] = Field(default_factory=list)


class SessionOut(BaseModel):
    """Full resumable state. Everything the chat screen needs to rebuild itself."""

    session_id: uuid.UUID
    template_id: uuid.UUID
    base_version_id: uuid.UUID
    format: str
    tier: Tier
    intent: str | None = None
    status: str
    questions: list[QuestionOut] = Field(default_factory=list)
    current_question: QuestionOut | None = None
    turns: list[TurnOut] = Field(default_factory=list)
    filled_values: dict[str, Any] = Field(default_factory=dict)
    derived_values: dict[str, Any] = Field(default_factory=dict)
    known_context: dict[str, Any] = Field(default_factory=dict)
    progress: ProgressOut
    started_at: datetime
    completed_at: datetime | None = None


class SessionCreateOut(SessionOut):
    plan_summary: str = Field(
        description="One line on what the triage decided, for the top of the chat."
    )


class SpecOut(BaseModel):
    """The Change Specification this session would compile. Plan §6: show judges this."""

    session_id: uuid.UUID
    base_version_id: uuid.UUID
    spec: ChangeSpec
    operation_count: int
    provenance_counts: dict[str, int] = Field(default_factory=dict)
    skipped: list[dict[str, str]] = Field(
        default_factory=list,
        description="Values with nowhere to go, and why. The honest half of the plan.",
    )


class SpecOperationPatch(BaseModel):
    """A user's edit to one operation on the review screen.

    Only the value may change. The op name and the target are not editable
    through this door: re-pointing an operation at another region would let the
    review screen do what the injection barrier exists to prevent.
    """

    model_config = ConfigDict(extra="forbid")

    value: Any = None
    rows: list[dict[str, Any]] | None = None


class SessionCompileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    publish: bool = Field(
        default=False,
        description="Point the template's current version at the result. Off by default.",
    )
    overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Final `{region_id: value}` edits from the review screen.",
    )
