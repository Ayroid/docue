"""Contract C1 — the Change Specification.

The artifact at the deterministic boundary. Plan §3.2 froze its shape at hour 0
for one reason: it is what makes the project's central claim true rather than
aspirational — *the model decides **what** changes, deterministic code decides
**how** the file changes.* A model that emits this JSON has never touched a byte
of the output.

Three properties are load-bearing, and each one is a rule about what the model
is **not** allowed to do:

- **Targets are named, never addressed.** An operation points at a `region_id`
  the detector already found. It cannot invent a cell reference, a paragraph
  index, a shape id, a sheet name, a file path, or XML. A `ref` is accepted for
  convenience but is resolved back to the region that contains it, and dropped
  if there is none.
- **Unknown targets are dropped, not guessed** (contract C5). A spec naming a
  region that doesn't exist is not an error — models hallucinate, and the whole
  safety argument is that the failure mode is a *visible gap* rather than a
  plausible wrong value. So resolution reports what it dropped and why, and the
  caller shows it. A *malformed* operation is different and does raise: that is
  a bug in the emitter, not a hallucination.
- **`provenance` is required on every operation.** It is what lets the review
  screen badge a value as typed, derived, AI-drafted or system-supplied. An
  operation that cannot say where its value came from has no business writing
  to somebody's document.

This module deliberately imports nothing from `app.compiler`. Track B emits
against it, and should not have to install openpyxl, python-docx and
python-pptx to construct a spec. `app/compiler/from_spec.py` is where a
validated spec meets the compilers.
"""

import uuid
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPEC_VERSION = "1.0"

# Plan §3.1's three change tiers. Informational for the compiler and meaningful
# in the UI: T1 is the safety net, T3 is the demo.
Tier = Literal["T1", "T2", "T3"]

# Contract C2's op names. `set_value` and `set_text` are the same intent -- write
# a scalar into a region -- kept as two names because that is how §3.2 and the
# three compilers each spell it; the adapter picks the right one per format.
# `set_bullets` and `set_notes` are pptx-only extensions to C2, added because the
# pptx compiler has no other way to write a bullet list or a speaker note and the
# deck is in the demo.
OpName = Literal[
    "set_value",
    "set_text",
    "clear_region",
    "clone_table_rows",
    "replace_region_rows",
    "set_bullets",
    "set_notes",
    "protect",
]

ValueType = Literal["string", "number", "date"]


class Target(BaseModel):
    """What an operation points at.

    `region_id` is the contract. `ref` exists because §3.2's own example writes
    `Sheet1!E5`, and because a human hand-writing a spec thinks in refs -- but it
    is resolved through the schema like everything else, never used directly.
    """

    model_config = ConfigDict(extra="forbid")

    region_id: str | None = None
    ref: str | None = Field(
        default=None,
        description="A cell/range ref, resolved to the region containing it. Dropped if none does.",
    )
    sheet: str | None = Field(default=None, description="Disambiguates a `ref` in a workbook.")
    format: str | None = Field(default=None, description="Advisory only; the stored version wins.")

    @model_validator(mode="after")
    def _needs_something_to_point_at(self) -> "Target":
        if not self.region_id and not self.ref:
            raise ValueError("target must carry a region_id or a ref")
        return self

    def describe(self) -> str:
        if self.region_id:
            return self.region_id
        return f"{self.sheet + '!' if self.sheet else ''}{self.ref}"


class _BaseOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Target
    provenance: str = Field(
        min_length=1,
        description=(
            "Where this value came from: `user_answer:q2`, `llm_generated`, "
            "`llm_derived:q3`, `system:today`, `retrieved:<version-uuid>`. Required -- "
            "it drives the review screen's badging, and a value with no traceable "
            "origin should not reach a client document."
        ),
    )
    grounded_by: list[str] = Field(
        default_factory=list,
        description="Version ids or artifact keys this content was grounded in (RAG-2).",
    )
    note: str | None = Field(default=None, description="Free text for the audit trail.")


class SetValueOp(_BaseOp):
    """Write a scalar into a `field` / `field_empty` region."""

    op: Literal["set_value", "set_text"]
    value: Any = None
    value_type: ValueType | None = Field(
        default=None,
        description="Omit to let the region's detected type decide; that is usually right.",
    )
    expected_after: Any = Field(
        default=None, description="Optional: what the cell should read once written."
    )


class ClearRegionOp(_BaseOp):
    """Blank a region, keeping its formatting."""

    op: Literal["clear_region"]


class CloneTableRowsOp(_BaseOp):
    """Append rows to a table region, cloning an existing row's styling.

    `rows` are keyed by the table's own **column names** as the detector read
    them off the header row -- not by index, and not by cell reference. An
    unknown column name is dropped with the rest of the unknown targets.
    """

    op: Literal["clone_table_rows"]
    rows: list[dict[str, Any]] = Field(min_length=1)
    value_types: dict[str, ValueType] = Field(default_factory=dict)
    column_styles: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "xlsx only: style indices that already exist in the workbook. The "
            "compiler refuses to synthesise a style, so a date column needs one "
            "that carries a date number format or the serial renders as 46256."
        ),
    )


class ReplaceRegionRowsOp(_BaseOp):
    """Rewrite a region's rows or items in full, growing or shrinking to fit.

    Takes column-keyed dicts for a table and plain strings for a paragraph block
    or a bullet list; the adapter resolves which by the region's kind, because a
    caller naming a `region_id` should not have to know its shape.
    """

    op: Literal["replace_region_rows"]
    rows: list[dict[str, Any] | str] = Field(default_factory=list)
    value_types: dict[str, ValueType] = Field(default_factory=dict)
    column_styles: dict[str, str] = Field(default_factory=dict)
    row_template_ref: str | None = Field(
        default=None, description="Advisory; the schema's own template row is preferred."
    )


class SetBulletsOp(_BaseOp):
    """pptx: replace a body placeholder's bullet list."""

    op: Literal["set_bullets"]
    items: list[str] = Field(min_length=1)


class SetNotesOp(_BaseOp):
    """pptx: replace a slide's speaker notes."""

    op: Literal["set_notes"]
    text: str


class ProtectOp(_BaseOp):
    """A declaration, not an edit: no other operation may write inside this region.

    Redundant in the common case -- the detector already marks branding,
    formulas and unclassified regions protected, and the compiler refuses them
    before any byte moves. It exists so a spec can *state* the guarantee it is
    relying on, which is worth having in the audit trail.
    """

    op: Literal["protect"]
    reason: str = ""
    provenance: str = "system:protect"


Operation = Annotated[
    Union[
        SetValueOp,
        ClearRegionOp,
        CloneTableRowsOp,
        ReplaceRegionRowsOp,
        SetBulletsOp,
        SetNotesOp,
        ProtectOp,
    ],
    Field(discriminator="op"),
]


class ValueAssertion(BaseModel):
    """"After compiling, this ref must read this."""

    model_config = ConfigDict(extra="forbid")

    ref: str
    must_equal: Any
    sheet: str | None = None


class InvariantAssertion(BaseModel):
    """A structural fact that must survive the compile.

    `package_parts_preserved` with `expect: "all"` is the one that matters most:
    it is the check that turns "the logo survives" from a hope into a test.
    """

    model_config = ConfigDict(extra="forbid")

    invariant: str
    expect: Any


Assertion = Union[ValueAssertion, InvariantAssertion]


class ChangeSpec(BaseModel):
    """Plan §3.2. The whole contract between the AI layer and the compiler."""

    model_config = ConfigDict(extra="forbid")

    spec_version: str = SPEC_VERSION
    base_version_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "The version these operations were planned against. Checked before "
            "compiling: replaying a spec against different bytes is how a stored "
            "spec silently writes the wrong cell."
        ),
    )
    tier: Tier = "T1"
    intent: str | None = Field(default=None, description="The user's request, for the audit trail.")
    operations: list[Operation] = Field(default_factory=list)
    assertions: list[Assertion] = Field(default_factory=list)

    @field_validator("spec_version")
    @classmethod
    def _known_version(cls, value: str) -> str:
        if value != SPEC_VERSION:
            raise ValueError(f"unsupported spec_version {value!r}; this build speaks {SPEC_VERSION}")
        return value

    @property
    def operation_count(self) -> int:
        return len(self.operations)

    def targets(self) -> list[str]:
        return [op.target.describe() for op in self.operations]

    def provenance_counts(self) -> dict[str, int]:
        """`{'user_answer': 4, 'llm_generated': 12}` — what the UI badges from."""
        counts: dict[str, int] = {}
        for op in self.operations:
            kind = op.provenance.split(":", 1)[0]
            counts[kind] = counts.get(kind, 0) + 1
        return dict(sorted(counts.items()))
