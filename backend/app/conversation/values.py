"""The value shape stages ⑤ and ⑥ both return, and the barrier that guards it.

Both stages answer the same question in different words -- *what content goes in
which region* -- so they share one output shape and one validator. Keeping it
here rather than duplicating it twice means the injection barrier is written
once and cannot drift between the two call sites.

**Why the shape looks like this.** A model returning `{region_id: value}` as an
object cannot be schema-constrained: JSON Schema pins *keys* only through
`properties`, and Bedrock's forced-tool validation would then accept any
additional key. So the payload is a *list* of entries each carrying an explicit
`region_id` with an `enum` of the ids the caller allows. The model physically
cannot name a region outside the enum, and the parser drops anything that
somehow arrives anyway.

Table rows are a list of `{column, value}` cells for the same reason -- column
names vary per document and cannot be enumerated at schema-build time, so they
are validated by the caller against the region's own detected header instead.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["parse_entries", "region_columns", "value_entry_schema"]


def region_columns(region: Any) -> list[str]:
    """The column names a caller may use for this region's rows.

    Mirrors `app.compiler.region_ops.column_map` without importing it: that
    module pulls in openpyxl, and nothing in this package should need a
    spreadsheet library to describe a table. The two must agree -- a name
    offered here and rejected there becomes a dropped operation.

    A `repeating_block` has no header row to name, so it exposes `serial` and
    `content` plus whatever its serial column was captioned (MOM's `Sl.No.`),
    exactly as `column_map` does.
    """
    notes = region.notes or {}
    if region.kind == "repeating_block":
        names = ["serial", "content"]
        header = notes.get("column_header")
        if header and header not in names:
            names.append(header)
        return names
    return [c["name"] for c in notes.get("columns", []) if c.get("name")]


def value_entry_schema(
    region_ids: list[str], *, extra_properties: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A schema for `{entries: [{region_id, value?, rows?}]}`.

    `region_id` is pinned to `region_ids` as an enum. That is the enforcement
    point for contract C5: not a prompt instruction the model may ignore, but a
    constraint the API validates the tool arguments against before they reach us.

    `value` and `rows` are both optional and neither is `null`-typed, because a
    region the model has nothing for should be *omitted*, not returned empty --
    with one exception, the deriver, which must be able to say "I considered
    this and have nothing", and passes `value: null` explicitly through
    `extra_properties`.
    """
    properties: dict[str, Any] = {
        "region_id": {"type": "string", "enum": list(region_ids)},
        "value": {"type": "string"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cells": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["column", "value"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["cells"],
                "additionalProperties": False,
            },
        },
    }
    required = ["region_id"]
    if extra_properties:
        properties.update(extra_properties)
        required.extend(extra_properties)

    return {
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            }
        },
        "required": ["entries"],
        "additionalProperties": False,
    }


def _rows(entry: dict[str, Any], columns: list[str] | None) -> list[dict[str, Any]]:
    """`[{cells: [{column, value}]}]` → `[{column: value}]`, unknown columns dropped.

    A column the detector did not read off the header row is dropped here rather
    than passed on: `region_ops.add_table_rows` would drop it too, but doing it
    here means the count of what was ignored is reportable next to the region it
    belongs to.
    """
    allowed = set(columns or [])
    out: list[dict[str, Any]] = []
    for row in entry.get("rows") or []:
        if not isinstance(row, dict):
            continue
        built: dict[str, Any] = {}
        for cell in row.get("cells") or []:
            if not isinstance(cell, dict):
                continue
            name = cell.get("column")
            if not name or not isinstance(name, str):
                continue
            if allowed and name not in allowed:
                logger.debug("dropping unknown column %r", name)
                continue
            built[name] = cell.get("value")
        if built:
            out.append(built)
    return out


def parse_entries(
    payload: dict[str, Any],
    known_ids: set[str],
    columns_by_region: dict[str, list[str]] | None = None,
    *,
    keep_null: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    """`(values by region_id, dropped ids)`.

    A table region yields a list of column-keyed row dicts; everything else
    yields a scalar. `keep_null` preserves an explicit `value: null` as `None`
    -- the deriver needs that to distinguish "considered and nothing follows"
    from "not considered", and the caller badges the two differently.

    Duplicate ids keep the first entry. A model that answers the same region
    twice has contradicted itself, and silently taking the last one would make
    which value lands depend on iteration order.
    """
    values: dict[str, Any] = {}
    dropped: list[str] = []

    for entry in payload.get("entries", []):
        # The forced tool does not reliably enforce nested item shape -- see
        # `app/ai/bedrock.py::complete_json`. An entry that is not an object
        # names no region, so there is nothing to write and nothing to guess.
        if not isinstance(entry, dict):
            logger.warning("dropping a malformed entry: %r", entry)
            continue
        region_id = entry.get("region_id")
        if not isinstance(region_id, str) or region_id not in known_ids:
            dropped.append(str(region_id))
            continue
        if region_id in values:
            continue

        if entry.get("rows"):
            rows = _rows(entry, (columns_by_region or {}).get(region_id))
            if rows:
                values[region_id] = rows
            continue

        if "value" in entry:
            value = entry["value"]
            if value is None:
                if keep_null:
                    values[region_id] = None
                continue
            text = str(value).strip()
            if text or keep_null:
                values[region_id] = text or None

    if dropped:
        logger.warning("dropped %d unknown region_id(s): %s", len(dropped), dropped[:8])
    return values, dropped
