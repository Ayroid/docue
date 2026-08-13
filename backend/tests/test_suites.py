"""Run every `scripts/test_*.py` suite and report which ones failed.

    uv run pytest -v          # with uv
    python -m pytest -v       # without it

The scripts stay the primary artifact-producing path -- run them directly when
you want to read the report or open the file they wrote. This wrapper exists so
that "did anything break?" is one command, which matters now that more than one
person is landing work.
"""

from pathlib import Path

import pytest

from conftest import (
    SCRIPTS_DIR,
    SUITE_TIMEOUT_SECONDS,
    missing_assets,
    run_script,
)


def _suites() -> list[Path]:
    """Discovered, not listed.

    A new suite is picked up the moment it lands -- no edit here, and no chance
    of a suite existing that nothing runs.
    """
    return sorted(SCRIPTS_DIR.glob("test_*.py"))


def _tail(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else f"...\n{text[-limit:]}"


@pytest.mark.parametrize("script", _suites(), ids=lambda path: path.stem)
def test_suite_passes(script: Path) -> None:
    absent = missing_assets(script.stem)
    if absent:
        pytest.skip(
            f"corpus file(s) not on this machine: {', '.join(p.name for p in absent)} "
            f"(expected in {absent[0].parent})"
        )

    try:
        result = run_script(script)
    except Exception as exc:  # noqa: BLE001 - a timeout is a real failure, reported as one
        pytest.fail(f"{script.name} did not finish within {SUITE_TIMEOUT_SECONDS}s: {exc}")

    if result.returncode == 0:
        return

    output = f"{result.stdout}\n{result.stderr}"
    # A locked artifact is not a regression. `test_surgical_compile.py` writes a
    # fixed path and raises if that file is still open in Excel, and reading
    # that as a broken compiler wastes real time.
    if "PermissionError" in output:
        pytest.fail(
            f"{script.name} hit a PermissionError -- an output file in scratch/ is probably "
            f"still open in Office. Close it and re-run.\n{_tail(output)}"
        )
    pytest.fail(f"{script.name} exited {result.returncode}\n{_tail(output)}")


def test_every_suite_is_discovered() -> None:
    """The runner is only useful if it actually covers the suites.

    Cheap guard against a glob that silently matches nothing -- a green run over
    zero suites looks identical to a green run over all of them.
    """
    assert _suites(), f"no test_*.py suites found in {SCRIPTS_DIR}"
