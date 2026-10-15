"""Minimal XLSX builder for tests (no third-party deps)."""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Dict, List, Sequence, Tuple
from xml.sax.saxutils import escape


def _col_letter(index: int) -> str:
    result = ""
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def _sheet_xml(rows: Sequence[Sequence[str]], shared_start: int) -> Tuple[str, List[str]]:
    strings: List[str] = []
    row_xml = []
    for r_idx, row in enumerate(rows, start=1):
        cells = []
        for c_idx, value in enumerate(row, start=1):
            text = "" if value is None else str(value)
            ref = f"{_col_letter(c_idx)}{r_idx}"
            sid = shared_start + len(strings)
            strings.append(text)
            cells.append(f'<c r="{ref}" t="s"><v>{sid}</v></c>')
        row_xml.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    )
    return xml, strings


def build_xlsx(sheets: Dict[str, Sequence[Sequence[str]]]) -> bytes:
    """Build a simple .xlsx from {sheet_name: [[cell, ...], ...]}."""
    memory = BytesIO()
    all_strings: List[str] = []
    sheet_files: List[Tuple[str, str, str]] = []  # name, path, xml

    for idx, (name, rows) in enumerate(sheets.items(), start=1):
        xml, strings = _sheet_xml(rows, len(all_strings))
        all_strings.extend(strings)
        path = f"xl/worksheets/sheet{idx}.xml"
        sheet_files.append((name, path, xml))

    shared_items = "".join(
        f"<si><t>{escape(s)}</t></si>" for s in all_strings
    )
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(all_strings)}" uniqueCount="{len(all_strings)}">{shared_items}</sst>'
    )

    workbook_sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{idx}" r:id="rId{idx}"/>'
        for idx, (name, _path, _xml) in enumerate(sheet_files, start=1)
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{workbook_sheets}</sheets></workbook>'
    )

    rels = "".join(
        f'<Relationship Id="rId{idx}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{idx}.xml"/>'
        for idx in range(1, len(sheet_files) + 1)
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{rels}</Relationships>'
    )

    content_types_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{idx}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for idx in range(1, len(sheet_files) + 1)
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        f'{content_types_overrides}</Types>'
    )

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )

    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/sharedStrings.xml", shared_xml)
        for _name, path, xml in sheet_files:
            zf.writestr(path, xml)

    return memory.getvalue()
