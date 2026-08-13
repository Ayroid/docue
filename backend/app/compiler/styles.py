"""Number-format facts from `styles.xml`, read without modifying it.

An Excel date is just a number; only the cell's number format makes it look
like a date. Write serial 46256 into a General-formatted cell and Excel shows
`46256` -- plan Appendix B calls this out as the kind of thing that visibly
breaks on a projector. It's easy to hit when *inserting* rows, because a new
row inherits its template's styles, and a template's date column may not exist
yet (the MOM's Action Plan has no data rows at all).

So the compiler refuses to write a date through a style that won't render as
one, and the error names the style indices that would. This module is the
lookup that makes that check possible. It never writes: adding a number format
would mean editing `styles.xml`, and every part the compiler leaves alone is
part of the preservation guarantee.
"""

import re
from dataclasses import dataclass

# Built-in numFmtIds that render as a date and/or time (ECMA-376 18.8.30):
# 14-22 the common date/time set, 27-36 and 50-58 the East Asian date formats,
# 45-47 elapsed-time formats.
_BUILTIN_DATE_FORMATS = frozenset(
    list(range(14, 23)) + list(range(27, 37)) + [45, 46, 47] + list(range(50, 59))
)
_DATE_TOKEN_RE = re.compile(r"[dmyhs]", re.IGNORECASE)

_CELL_XFS_RE = re.compile(r"<cellXfs\b[^>]*>(.*?)</cellXfs>", re.DOTALL)
_XF_RE = re.compile(r"<xf\b[^>]*/>|<xf\b.*?</xf>", re.DOTALL)
_NUMFMT_ID_RE = re.compile(r'\bnumFmtId="(\d+)"')
_CUSTOM_NUMFMT_RE = re.compile(r'<numFmt\b[^>]*?numFmtId="(\d+)"[^>]*?formatCode="([^"]*)"')


@dataclass
class StyleFormats:
    """Style index -> number format, for one workbook."""

    numfmt_by_style: list[int]
    custom_codes: dict[int, str]

    def numfmt_of(self, style: str | None) -> int:
        """numFmtId for a cell's `s` attribute (absent `s` means style 0)."""
        index = int(style) if style else 0
        if 0 <= index < len(self.numfmt_by_style):
            return self.numfmt_by_style[index]
        return 0

    def renders_as_date(self, style: str | None) -> bool:
        numfmt_id = self.numfmt_of(style)
        if numfmt_id in _BUILTIN_DATE_FORMATS:
            return True
        code = self.custom_codes.get(numfmt_id)
        if code is None:
            return False
        # Strip literals and colour/condition sections before looking for date
        # tokens, so `"0.00 \\d"` isn't mistaken for a day format.
        bare = re.sub(r'".*?"|\[[^\]]*\]|\\.', "", code)
        return bool(_DATE_TOKEN_RE.search(bare))

    def date_styles(self) -> list[str]:
        return [
            str(index)
            for index in range(len(self.numfmt_by_style))
            if self.renders_as_date(str(index))
        ]


def read_style_formats(styles_xml: str) -> StyleFormats:
    custom = {int(nid): code for nid, code in _CUSTOM_NUMFMT_RE.findall(styles_xml)}
    block = _CELL_XFS_RE.search(styles_xml)
    if block is None:
        return StyleFormats(numfmt_by_style=[], custom_codes=custom)
    numfmts = []
    for xf in _XF_RE.findall(block.group(1)):
        match = _NUMFMT_ID_RE.search(xf)
        numfmts.append(int(match.group(1)) if match else 0)
    return StyleFormats(numfmt_by_style=numfmts, custom_codes=custom)
