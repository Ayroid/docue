"""Surgical zip-level xlsx compiler.

openpyxl round-trips (load_workbook -> save) silently drop package parts it has
no model for -- in-cell rich-value images, docMetadata sensitivity labels,
richData. This module never calls openpyxl.save(). It rewrites only the
targeted worksheet XML for the cells named in the Change Spec and copies every
other zip part byte-for-byte from the original archive, so nothing the
workbook doesn't understand can be lost.
"""

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Literal

ValueType = Literal["string", "number", "date"]


@dataclass
class SetValueOp:
    sheet_file: str  # e.g. "xl/worksheets/sheet1.xml"
    ref: str  # e.g. "E5"
    value: str | int | float
    value_type: ValueType = "string"
    preserve_number_format: bool = True  # keep the cell's existing `s` style index


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _style_attr(existing_attrs: str) -> str:
    match = re.search(r'\bs="(\d+)"', existing_attrs)
    return f' s="{match.group(1)}"' if match else ""


def _apply_set_value(sheet_xml: str, op: SetValueOp) -> str:
    pattern = re.compile(r'<c\s+r="' + re.escape(op.ref) + r'"([^>]*?)(?:/>|>.*?</c>)', re.DOTALL)
    match = pattern.search(sheet_xml)
    if match is None:
        raise ValueError(f"Cell {op.ref} not found in {op.sheet_file}")

    style_attr = _style_attr(match.group(1)) if op.preserve_number_format else ""

    if op.value_type == "string":
        escaped = _xml_escape(str(op.value))
        new_cell = f'<c r="{op.ref}"{style_attr} t="inlineStr"><is><t xml:space="preserve">{escaped}</t></is></c>'
    else:
        new_cell = f'<c r="{op.ref}"{style_attr}><v>{op.value}</v></c>'

    return sheet_xml[: match.start()] + new_cell + sheet_xml[match.end() :]


def apply_change_spec(original_bytes: bytes, operations: list[SetValueOp]) -> bytes:
    """Apply `set_value` operations and return a new xlsx as bytes.

    Every zip part not named in `operations` is copied unchanged (same
    ZipInfo, same bytes) from the original archive.
    """
    with zipfile.ZipFile(io.BytesIO(original_bytes)) as src:
        edited: dict[str, str] = {}
        for op in operations:
            xml = edited.get(op.sheet_file)
            if xml is None:
                xml = src.read(op.sheet_file).decode("utf-8")
            edited[op.sheet_file] = _apply_set_value(xml, op)

        out_buffer = io.BytesIO()
        with zipfile.ZipFile(out_buffer, "w", zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                if item.filename in edited:
                    dst.writestr(item, edited[item.filename].encode("utf-8"))
                else:
                    dst.writestr(item, src.read(item.filename))

    return out_buffer.getvalue()
