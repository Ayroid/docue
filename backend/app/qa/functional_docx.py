"""Functional QA for docx: re-open the compiled file and check every value landed.

Plan §11 Level 2, the docx half of `functional.py`. Structural QA proves nothing
was *lost*; this proves the edits were actually *made*, and at the right
addresses -- which is the part insertion can plausibly get wrong, since growing
a paragraph block by two moves every paragraph index below it.

It reads the output through python-docx from the compiled bytes rather than from
the editor's in-memory tree, on purpose: re-parsing the file that will actually
be delivered is the only check that covers serialisation as well as editing.
"""

import io
from dataclasses import dataclass

import docx

from app.compiler.docx_compiler import DocxAssertion


class FunctionalQAError(RuntimeError):
    pass


@dataclass
class CheckedAssertion:
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


def _actual(document: docx.document.Document, assertion: DocxAssertion) -> object:
    if assertion.para_index is not None:
        paragraphs = document.paragraphs
        if not 0 <= assertion.para_index < len(paragraphs):
            return None
        return paragraphs[assertion.para_index].text
    tables = document.tables
    if assertion.table_index is None or not 0 <= assertion.table_index < len(tables):
        return None
    rows = tables[assertion.table_index].rows
    if assertion.row_index is None or not 0 <= assertion.row_index < len(rows):
        return None
    cells = rows[assertion.row_index].cells
    if assertion.cell_index is None or not 0 <= assertion.cell_index < len(cells):
        return None
    return cells[assertion.cell_index].text


def check_docx_assertions(
    data: bytes, assertions: list[DocxAssertion]
) -> FunctionalQAResult:
    """Verify each assertion against the compiled bytes. Raises on failure."""
    document = docx.Document(io.BytesIO(data))
    checks: list[CheckedAssertion] = []
    for assertion in assertions:
        actual = _actual(document, assertion)
        checks.append(
            CheckedAssertion(
                ref=assertion.ref,
                expected=assertion.expected,
                actual=actual,
                # Word normalises nothing, but a value written into a cell is
                # compared on its stripped form: the cell's own paragraph may
                # carry indentation the value never asked for.
                passed=actual is not None
                and str(actual).strip() == str(assertion.expected).strip(),
            )
        )

    result = FunctionalQAResult(
        passed=all(check.passed for check in checks), checks=checks
    )
    if not result.passed:
        detail = ", ".join(
            f"{check.ref} expected {check.expected!r} got {check.actual!r}"
            for check in result.failures
        )
        raise FunctionalQAError(f"{len(result.failures)} assertion(s) failed: {detail}")
    return result
