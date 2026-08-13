"""Functional QA: re-open the compiled file and check every value landed.

Plan §11 Level 2. Structural QA proves nothing was *lost*; this proves the
edits were actually *made*, and at the right addresses -- which is the part
row insertion can plausibly get wrong, since a write at `A28` and an insertion
at row 25 both move things.

No AI, no rendering. It reads the output through openpyxl on purpose: a second,
independent implementation of the format agreeing with ours is worth more than
re-parsing our own XML with our own helpers.
"""

import io
from dataclasses import dataclass

import openpyxl
from pptx import Presentation

from app.compiler.pptx_compiler import PptxAssertion
from app.compiler.xlsx_surgical import Assertion, to_excel_serial
from app.ingestion.regions import sheet_part_map


class FunctionalQAError(RuntimeError):
    pass


@dataclass
class CheckedAssertion:
    sheet: str
    ref: str
    expected: object
    actual: object
    passed: bool


@dataclass
class FunctionalQAResult:
    passed: bool
    checks: list[CheckedAssertion]

    @property
    def failures(self) -> list[CheckedAssertion]:
        return [check for check in self.checks if not check.passed]


def _matches(expected: object, actual: object, value_type: str) -> bool:
    if actual is None:
        return False
    if value_type == "date":
        try:
            return to_excel_serial(expected) == to_excel_serial(actual)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    if value_type == "number":
        try:
            return float(expected) == float(actual)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    return str(expected) == str(actual)


def check_assertions(data: bytes, assertions: list[Assertion]) -> FunctionalQAResult:
    """Verify each assertion against the compiled bytes. Raises on failure."""
    part_to_sheet = {part: name for name, part in sheet_part_map(data).items()}
    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    try:
        checks: list[CheckedAssertion] = []
        for assertion in assertions:
            sheet_name = part_to_sheet.get(assertion.sheet_file)
            if sheet_name is None:
                checks.append(
                    CheckedAssertion(
                        assertion.sheet_file, assertion.ref, assertion.expected, None, False
                    )
                )
                continue
            actual = workbook[sheet_name][assertion.ref].value
            checks.append(
                CheckedAssertion(
                    sheet=sheet_name,
                    ref=assertion.ref,
                    expected=assertion.expected,
                    actual=actual,
                    passed=_matches(assertion.expected, actual, assertion.value_type),
                )
            )
    finally:
        workbook.close()

    result = FunctionalQAResult(passed=all(check.passed for check in checks), checks=checks)
    if not result.passed:
        detail = ", ".join(
            f"{check.sheet}!{check.ref} expected {check.expected!r} got {check.actual!r}"
            for check in result.failures
        )
        raise FunctionalQAError(f"{len(result.failures)} assertion(s) failed: {detail}")
    return result


def _pptx_actual(slide: object, assertion: PptxAssertion) -> str | None:
    """Read back whatever the assertion points at, through python-pptx."""
    if assertion.where == "notes":
        if not slide.has_notes_slide:  # type: ignore[attr-defined]
            return None
        return slide.notes_slide.notes_text_frame.text  # type: ignore[attr-defined]

    shape = next(
        (s for s in slide.shapes if s.shape_id == assertion.shape_id),  # type: ignore[attr-defined]
        None,
    )
    if shape is None:
        return None

    if assertion.where == "text":
        return shape.text_frame.text if shape.has_text_frame else None
    if assertion.where.startswith("bullet:"):
        index = int(assertion.where.split(":", 1)[1])
        paragraphs = shape.text_frame.paragraphs if shape.has_text_frame else []
        return paragraphs[index].text if index < len(paragraphs) else None
    if assertion.where.startswith("cell:"):
        row, column = (int(part) for part in assertion.where.split(":", 1)[1].split(","))
        if not getattr(shape, "has_table", False):
            return None
        table = shape.table
        if row >= len(table.rows) or column >= len(table.columns):
            return None
        return table.cell(row, column).text
    return None


def check_pptx_assertions(data: bytes, assertions: list[PptxAssertion]) -> FunctionalQAResult:
    """Re-open the compiled deck and verify each assertion. Raises on failure."""
    presentation = Presentation(io.BytesIO(data))
    slides = {
        str(slide.part.partname).lstrip("/"): slide for slide in presentation.slides
    }

    checks: list[CheckedAssertion] = []
    for assertion in assertions:
        slide = slides.get(assertion.slide_part)
        actual = _pptx_actual(slide, assertion) if slide is not None else None
        checks.append(
            CheckedAssertion(
                sheet=assertion.slide_part,
                ref=f"{assertion.shape_id}/{assertion.where}",
                expected=assertion.expected,
                actual=actual,
                # A pptx reader normalises line endings, so compare on content
                # rather than on bytes.
                passed=actual is not None
                and actual.replace("\r\n", "\n").strip() == assertion.expected.strip(),
            )
        )

    result = FunctionalQAResult(passed=all(check.passed for check in checks), checks=checks)
    if not result.passed:
        detail = ", ".join(
            f"{check.sheet} {check.ref} expected {check.expected!r} got {check.actual!r}"
            for check in result.failures[:5]
        )
        raise FunctionalQAError(f"{len(result.failures)} assertion(s) failed: {detail}")
    return result
