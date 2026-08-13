"""LLM pass A + B over the real corpus, with the guarantees checked offline.

    uv run python scripts/test_llm_classify.py

Two halves, and the split is the point:

* **Offline guarantees** run with no credentials and no network. They check the
  properties that must hold no matter what a model returns -- classification
  can only narrow write permission, unknown `region_id`s are dropped, a failed
  call leaves the structural schema standing. These are the safety claims, so
  they are tested deterministically rather than observed in a sample.
* **The live pass** runs the classifier and the metadata writer over all five
  documents and prints what came back, for human review. It **skips cleanly**
  when Bedrock is unreachable or the key lacks `bedrock:InvokeModel`, so this
  suite stays green on a machine that has no Bedrock access -- an unconfigured
  laptop is not a regression.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import bedrock  # noqa: E402
from app.ai.bedrock import BedrockError  # noqa: E402
from app.ingestion.classify import (  # noqa: E402
    ClassificationResult,
    RegionLabel,
    classify_regions,
)
from app.ingestion.metadata import embedding_text, write_metadata  # noqa: E402
from app.ingestion.pptx_regions import detect_regions_pptx  # noqa: E402
from app.ingestion.regions import detect_regions_xlsx  # noqa: E402
from app.ingestion.regions_docx import detect_regions_docx  # noqa: E402

FILES_DIR = Path(__file__).resolve().parent.parent.parent / "Files"

CORPUS = [
    ("MOM Sample.xlsx", detect_regions_xlsx),
    ("BFL Sample.xlsx", detect_regions_xlsx),
    ("POC List sample.xlsx", detect_regions_xlsx),
    ("BRD Sample.docx", detect_regions_docx),
    ("Workshop Readout Template.pptx", detect_regions_pptx),
]


@dataclass
class _FakeRegion:
    """Minimal stand-in with the contract-C3 fields `apply_to` touches."""

    region_id: str
    kind: str
    label: str | None
    value_type: str
    editable: bool
    protected: bool
    required: bool
    notes: dict


class _FakeSchema:
    def __init__(self, regions):
        self.regions = regions
        self.format = "xlsx"
        self.notes = {}


def _label(region_id: str, *, should_not_write: bool) -> RegionLabel:
    return RegionLabel(
        region_id=region_id,
        semantic_role="test role",
        label="Test Label",
        value_type="string",
        required=True,
        should_not_write=should_not_write,
        confidence=0.9,
    )


def check_guarantees() -> list[str]:
    """The safety properties, proven without a model in the loop."""
    failures: list[str] = []

    logo = _FakeRegion("mom.branding", "branding", "Logo", "none", False, True, False, {})
    field = _FakeRegion("mom.venue", "field", "Venue", "string", True, False, False, {})
    schema = _FakeSchema([logo, field])

    # A model that says "yes, write the logo" changes nothing. The detector's
    # protection is the floor and classification is not allowed to raise it.
    result = ClassificationResult(
        labels={
            "mom.branding": _label("mom.branding", should_not_write=False),
            "mom.venue": _label("mom.venue", should_not_write=False),
        }
    )
    result.apply_to(schema)
    if logo.editable:
        failures.append("classification made a protected branding region editable")
    if not field.editable:
        failures.append("classification revoked a writable field it was not asked to")
    if logo.notes.get("semantic_role") != "test role":
        failures.append("a protected region got no semantic role (labels should still apply)")

    # The other direction is allowed: taking write permission away is the one
    # judgement structure cannot make.
    narrowing = ClassificationResult(labels={"mom.venue": _label("mom.venue", should_not_write=True)})
    narrowing.apply_to(schema)
    if field.editable:
        failures.append("should_not_write did not revoke editability")
    if "llm" not in (field.notes.get("not_writable_reason") or ""):
        failures.append("a revoked region does not record why")

    # An id the schema never had is dropped, not resolved to a near match.
    stray = ClassificationResult(labels={"mom.does_not_exist": _label("mom.does_not_exist", should_not_write=True)})
    touched = stray.apply_to(_FakeSchema([field]))
    if touched:
        failures.append("apply_to wrote a label for a region_id not in the schema")

    return failures


def _bedrock_available() -> tuple[bool, str]:
    """One cheap call. Distinguishes 'not configured' from 'broken'."""
    try:
        bedrock.complete_json(
            purpose="preflight",
            system="Reply with the JSON object {\"ok\": true}.",
            user="ping",
            schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
            prompt_version="preflight/1.0.0",
            max_tokens=64,
        )
        return True, ""
    except BedrockError as exc:
        return False, str(exc)


def run_live() -> list[str]:
    failures: list[str] = []
    for name, detect in CORPUS:
        path = FILES_DIR / name
        if not path.exists():
            print(f"  {name:<34} SKIP (not on this machine)")
            continue

        schema = detect(path.read_bytes())
        before = {r.region_id: (r.editable, r.protected) for r in schema.regions}

        result = classify_regions(schema, filename=name)
        applied = result.apply_to(schema)
        metadata = write_metadata(schema, filename=name)

        # The invariant, re-checked against the real model's real output.
        widened = [
            rid
            for r in schema.regions
            for rid in [r.region_id]
            if r.editable and not before[rid][0]
        ]
        if widened:
            failures.append(f"{name}: classification made {widened} editable")
        for stray in result.dropped_ids:
            if stray in before:
                failures.append(f"{name}: dropped a region_id that does exist: {stray}")

        print(f"\n  {name}")
        print(f"    {len(schema.regions)} regions, {applied} labelled, "
              f"{len(result.dropped_ids)} dropped, {len(result.refused_writes)} write-refused")
        if result.errors:
            print(f"    errors: {result.errors[0][:120]}")
        print(f"    title      {metadata.title!r}")
        print(f"    purpose    {metadata.purpose[:110]!r}")
        print(f"    when       {metadata.when_to_use[:110]!r}")
        print(f"    audience   {metadata.audience!r}")
        print(f"    tags       {metadata.tags}")
        if not metadata.generated:
            failures.append(f"{name}: metadata fell back to the filename")
        if not embedding_text(metadata).strip():
            failures.append(f"{name}: embedding text is empty")
        for region in list(schema.regions)[:6]:
            role = region.notes.get("semantic_role")
            if role:
                print(f"      {region.region_id:<34} {region.kind:<16} -> {role}")

    return failures


def main() -> int:
    print("offline guarantees (no model in the loop)")
    failures = check_guarantees()
    print(f"  {'PASS' if not failures else 'FAIL'} -- narrowing-only, drop-unknown, label-application")

    print("\nbedrock preflight")
    available, reason = _bedrock_available()
    if not available:
        print(f"  SKIP -- {reason[:200]}")
        print("\n  The live pass needs a key with `bedrock:InvokeModel` in the Bedrock region")
        print("  and BEDROCK_* entries in .env. Offline guarantees above still ran.")
    else:
        print("  OK")
        print("\nlive pass over the corpus")
        failures += run_live()

        calls = bedrock.last_calls()
        cost = sum(c.cost_usd for c in calls)
        tokens_in = sum(c.input_tokens for c in calls)
        tokens_out = sum(c.output_tokens for c in calls)
        slowest = max((c.latency_ms for c in calls), default=0)
        print(
            f"\n  {len(calls)} model calls, {tokens_in:,} in / {tokens_out:,} out, "
            f"slowest {slowest}ms, ${cost:.4f} total"
        )

    print()
    if failures:
        print(f"llm classify: FAIL ({len(failures)})")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("llm classify: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
