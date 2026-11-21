"""用标准库读取 xlsx。运行时不依赖 openpyxl，避免已装好的环境还要再装包。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}


def load_workbook(path: Path) -> dict[str, dict[int, dict[int, str]]]:
    """返回 {表名: {行号: {列号: 文本}}}。行、列都从 1 开始，空单元格不出现。"""

    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        names = _sheet_targets(archive)
        book: dict[str, dict[int, dict[int, str]]] = {}
        for name, target in names:
            book[name] = _sheet(archive, target, shared)
    return book


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("m:si", _NS):
        values.append("".join(node.text or "" for node in item.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))
    return values


def _sheet_targets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {node.attrib["Id"]: node.attrib["Target"] for node in rels.findall("r:Relationship", _REL)}
    found: list[tuple[str, str]] = []
    for sheet in workbook.findall("m:sheets/m:sheet", _NS):
        name = sheet.attrib["name"]
        rel_id = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = targets[rel_id]
        if not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        found.append((name, target))
    return found


def _sheet(archive: zipfile.ZipFile, target: str, shared: list[str]) -> dict[int, dict[int, str]]:
    root = ET.fromstring(archive.read(target))
    rows: dict[int, dict[int, str]] = {}
    for row in root.findall("m:sheetData/m:row", _NS):
        number = int(row.attrib["r"])
        cells: dict[int, str] = {}
        for cell in row.findall("m:c", _NS):
            ref = cell.attrib.get("r", "")
            column = _column(ref)
            value = _value(cell, shared)
            if column and value != "":
                cells[column] = value
        if cells:
            rows[number] = cells
    return rows


def _column(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    if not letters:
        return 0
    number = 0
    for ch in letters:
        number = number * 26 + (ord(ch.upper()) - 64)
    return number


def _value(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")).strip()
    node = cell.find("m:v", _NS)
    if node is None or node.text is None:
        return ""
    raw = node.text
    if kind == "s":
        return shared[int(raw)].strip()
    return raw.strip()
