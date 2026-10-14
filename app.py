from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import re
import secrets
import shutil
import sys
import threading
import time
import unicodedata
import webbrowser
import zipfile
from dataclasses import dataclass, asdict, field
from datetime import datetime
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse
import xml.etree.ElementTree as ET

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
DATA_DIR = APP_DIR / "data"
CATALOG_PATH = DATA_DIR / "catalogo_articulos.csv"
BACKUP_DIR = DATA_DIR / "backups"
HOST = "127.0.0.1"
PORT = 8765
MAX_FILE_SIZE = 50 * 1024 * 1024
DOWNLOAD_TTL_SECONDS = 30 * 60
CATALOG_PAGE_SIZE_DEFAULT = 25
CATALOG_PAGE_SIZE_MAX = 100
MAX_CATALOG_BACKUPS = 20

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

NAMESPACE_PREFIXES = {
    "": NS_MAIN,
    "r": NS_REL,
    "mx": "http://schemas.microsoft.com/office/mac/excel/2008/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "mv": "urn:schemas-microsoft-com:mac:vml",
    "x14": "http://schemas.microsoft.com/office/spreadsheetml/2009/9/main",
    "x15": "http://schemas.microsoft.com/office/spreadsheetml/2010/11/main",
    "x14ac": "http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac",
    "xm": "http://schemas.microsoft.com/office/excel/2006/main",
    "xr": "http://schemas.microsoft.com/office/spreadsheetml/2014/revision",
    "xr2": "http://schemas.microsoft.com/office/spreadsheetml/2015/revision2",
    "xr3": "http://schemas.microsoft.com/office/spreadsheetml/2016/revision3",
}
for prefix, uri in NAMESPACE_PREFIXES.items():
    try:
        ET.register_namespace(prefix, uri)
    except ValueError:
        pass

REF_RE = re.compile(r"REF\s*[-–—−]\s*(\d+)", re.IGNORECASE)
NUMERIC_RE = re.compile(r"^-?\d+(?:[.,]0+)?$")
SCI_NUMERIC_RE = re.compile(r"^-?\d+(?:[.,]\d+)?[eE][+]?\d+$")
NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")
UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')

TARGET_ID_HEADER = "ID INTERNO ARTICULO"
TARGET_NAME_HEADER = "NOMBRE DE ARTICULO"
CATALOG_ID_HEADER = "ID INTERNO"
CATALOG_NAME_HEADER = "NOMBRE"
CATALOG_REF_HEADER = "REF"
CATALOG_CSV_FIELDS = ["ID interno", "Nombre", "Ref"]

CATALOG_LOCK = threading.Lock()


@dataclass
class Issue:
    sheet: str
    row: int
    value: str
    reason: str


@dataclass
class ProcessSummary:
    processed: int = 0
    already_internal: int = 0
    recovered_from_text: int = 0
    recovered_from_name: int = 0
    skipped_blank: int = 0
    not_found: int = 0
    sheets_processed: int = 0
    catalog_entries: int = 0
    catalog_added: int = 0
    output_files: List[str] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class CatalogItem:
    internal_id: str
    name: str
    ref: str

    def to_dict(self) -> dict:
        return {
            "internal_id": self.internal_id,
            "name": self.name,
            "ref": self.ref,
        }


@dataclass
class ProcessOutput:
    data: bytes
    filename: str
    content_type: str
    summary: ProcessSummary


def normalize_header(value: object) -> str:
    text = "" if value is None else str(value)
    replacements = str.maketrans({
        "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U", "Ü": "U", "Ñ": "N",
        "á": "A", "é": "E", "í": "I", "ó": "O", "ú": "U", "ü": "U", "ñ": "N",
    })
    text = text.translate(replacements).upper().strip()
    return NON_ALNUM_RE.sub(" ", text).strip()


def strip_invisible_chars(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    cleaned = []
    for char in text:
        if char in "\n\r\t":
            cleaned.append(" ")
            continue
        category = unicodedata.category(char)
        if category in {"Cf", "Cc", "Mn"}:
            continue
        cleaned.append(" " if char == "\u00a0" else char)
    return "".join(cleaned)


def normalize_number(value: object) -> str:
    """Normalize catalog Ref / ID values: 180178, '180178', 180178.0 → 180178.

    Does not drop legitimate leading zeros. Does not use float() for long IDs.
    """
    if value is None:
        return ""
    text = strip_invisible_chars(str(value)).strip().strip("'\"")
    if not text:
        return ""
    compact = text.replace(" ", "")
    if NUMERIC_RE.fullmatch(compact):
        return re.split(r"[.,]", compact, maxsplit=1)[0]
    sci = SCI_NUMERIC_RE.fullmatch(compact)
    if sci:
        try:
            as_int = int(float(compact.replace(",", ".")))
            return str(as_int)
        except (TypeError, ValueError, OverflowError):
            return compact
    if re.fullmatch(r"-?\d+", compact):
        return compact
    return text


def csv_cell_value(value: object) -> str:
    """Normalize values for CSV export, avoiding trailing .0 on IDs/refs."""
    if value is None:
        return ""
    text = strip_invisible_chars(str(value)).strip()
    if not text:
        return ""
    normalized = normalize_number(text)
    if normalized and (NUMERIC_RE.fullmatch(text.replace(" ", "")) or re.fullmatch(r"-?\d+", normalized)):
        return normalized
    return text


def extract_ref(value: object) -> Optional[str]:
    if value is None:
        return None
    text = strip_invisible_chars(str(value))
    match = REF_RE.search(text)
    return match.group(1) if match else None


def column_number(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        raise ValueError(f"Referencia de celda inválida: {cell_ref}")
    result = 0
    for char in match.group(1):
        result = result * 26 + (ord(char) - 64)
    return result


def load_shared_strings(zf: zipfile.ZipFile) -> List[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    strings: List[str] = []
    for si in root.findall(f"{{{NS_MAIN}}}si"):
        text_parts = [node.text or "" for node in si.iter(f"{{{NS_MAIN}}}t")]
        strings.append("".join(text_parts))
    return strings


def read_cell_value(cell: Optional[ET.Element], shared_strings: List[str]) -> str:
    if cell is None:
        return ""
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{NS_MAIN}}}t"))
    value_node = cell.find(f"{{{NS_MAIN}}}v")
    if value_node is not None and value_node.text is not None:
        raw = value_node.text
        if cell_type == "s":
            try:
                return shared_strings[int(raw)]
            except (ValueError, IndexError):
                return ""
        return raw
    return "".join(node.text or "" for node in cell.iter(f"{{{NS_MAIN}}}t"))


def worksheet_rows(root: ET.Element) -> Iterable[ET.Element]:
    sheet_data = root.find(f"{{{NS_MAIN}}}sheetData")
    if sheet_data is None:
        return []
    return sheet_data.findall(f"{{{NS_MAIN}}}row")


def row_cells(row: ET.Element) -> Dict[int, ET.Element]:
    result: Dict[int, ET.Element] = {}
    implied = 0
    for cell in row.findall(f"{{{NS_MAIN}}}c"):
        ref = cell.get("r")
        if ref:
            implied = column_number(ref)
        else:
            implied += 1
        result[implied] = cell
    return result


def find_header_row(
    root: ET.Element,
    shared_strings: List[str],
    required: Tuple[str, ...],
) -> Optional[Tuple[int, Dict[str, int], List[Tuple[int, str]]]]:
    required_set = set(required)
    for row in list(worksheet_rows(root))[:25]:
        headers_by_name: Dict[str, int] = {}
        ordered: List[Tuple[int, str]] = []
        for col, cell in sorted(row_cells(row).items()):
            raw = read_cell_value(cell, shared_strings).strip()
            header = normalize_header(raw)
            if not header:
                continue
            headers_by_name[header] = col
            ordered.append((col, raw))
        if required_set.issubset(headers_by_name.keys()):
            return int(row.get("r", "0")), {name: headers_by_name[name] for name in required}, ordered
    return None


def workbook_sheet_targets(zf: zipfile.ZipFile) -> List[Tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.get("Id"): rel.get("Target") for rel in rels.findall(f"{{{NS_PKG_REL}}}Relationship")}
    result: List[Tuple[str, str]] = []
    sheets = workbook.find(f"{{{NS_MAIN}}}sheets")
    if sheets is None:
        return result
    for sheet in sheets.findall(f"{{{NS_MAIN}}}sheet"):
        name = sheet.get("name", "")
        rid = sheet.get(f"{{{NS_REL}}}id")
        target = rel_map.get(rid)
        if target:
            if target.startswith("/"):
                path = target.lstrip("/")
            else:
                path = "xl/" + target.lstrip("/")
            result.append((name, path))
    return result


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def ensure_catalog_file() -> None:
    ensure_data_dir()
    if not CATALOG_PATH.exists():
        with CATALOG_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CATALOG_CSV_FIELDS)
            writer.writeheader()


def backup_catalog_file() -> Optional[Path]:
    """Create a catalog backup before real mutations. Keeps the newest 20 files."""
    ensure_data_dir()
    if not CATALOG_PATH.exists() or CATALOG_PATH.stat().st_size == 0:
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = BACKUP_DIR / f"catalogo_articulos_{stamp}.csv"
    # Avoid collisions if two writes happen in the same second.
    suffix = 1
    while destination.exists():
        destination = BACKUP_DIR / f"catalogo_articulos_{stamp}_{suffix}.csv"
        suffix += 1
    shutil.copy2(CATALOG_PATH, destination)
    backups = sorted(
        BACKUP_DIR.glob("catalogo_articulos_*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old in backups[MAX_CATALOG_BACKUPS:]:
        try:
            old.unlink()
        except OSError:
            pass
    return destination


def load_persistent_catalog() -> Dict[str, CatalogItem]:
    ensure_catalog_file()
    by_ref: Dict[str, CatalogItem] = {}
    with CATALOG_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row:
                continue
            internal_id = normalize_number(row.get("ID interno") or row.get("ID INTERNO") or "")
            name = (row.get("Nombre") or row.get("NOMBRE") or "").strip()
            ref = normalize_number(row.get("Ref") or row.get("REF") or "")
            if not internal_id or not name or not ref:
                continue
            by_ref[ref] = CatalogItem(internal_id=internal_id, name=name, ref=ref)
    return by_ref


def save_persistent_catalog(by_ref: Dict[str, CatalogItem]) -> None:
    ensure_data_dir()
    items = sorted(by_ref.values(), key=lambda item: (item.ref, item.internal_id))
    with CATALOG_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CATALOG_CSV_FIELDS)
        writer.writeheader()
        for item in items:
            writer.writerow({
                "ID interno": item.internal_id,
                "Nombre": item.name,
                "Ref": item.ref,
            })


def indexes_from_catalog(by_ref: Dict[str, CatalogItem]) -> Tuple[Dict[str, CatalogItem], Dict[str, CatalogItem]]:
    by_id: Dict[str, CatalogItem] = {}
    for item in by_ref.values():
        by_id[item.internal_id] = item
    return by_ref, by_id


def read_lista_items(
    zf: zipfile.ZipFile,
    shared_strings: List[str],
    sheets: List[Tuple[str, str]],
) -> Dict[str, CatalogItem]:
    """Utility used only for one-time migration tooling. Not used during processing."""
    lista_target = next((target for name, target in sheets if normalize_header(name) == "LISTA"), None)
    if not lista_target:
        raise ValueError("El archivo no contiene una pestaña llamada 'Lista'.")

    root = ET.fromstring(zf.read(lista_target))
    header_info = find_header_row(root, shared_strings, (CATALOG_ID_HEADER, CATALOG_NAME_HEADER, CATALOG_REF_HEADER))
    if not header_info:
        raise ValueError("La pestaña 'Lista' debe contener las columnas ID interno, Nombre y Ref.")
    header_row, cols, _ordered = header_info

    by_ref: Dict[str, CatalogItem] = {}
    by_id: Dict[str, CatalogItem] = {}
    for row in worksheet_rows(root):
        row_number = int(row.get("r", "0"))
        if row_number <= header_row:
            continue
        cells = row_cells(row)
        internal_id = normalize_number(read_cell_value(cells.get(cols[CATALOG_ID_HEADER]), shared_strings))
        name = read_cell_value(cells.get(cols[CATALOG_NAME_HEADER]), shared_strings).strip()
        ref = normalize_number(read_cell_value(cells.get(cols[CATALOG_REF_HEADER]), shared_strings))
        if not internal_id and not ref and not name:
            continue
        if not internal_id or not ref or not name:
            continue
        item = CatalogItem(internal_id=internal_id, name=name, ref=ref)
        if ref in by_ref and by_ref[ref] != item:
            raise ValueError(f"La referencia {ref} aparece duplicada con datos diferentes en la pestaña Lista.")
        if internal_id in by_id and by_id[internal_id] != item:
            raise ValueError(f"El ID interno {internal_id} aparece duplicado con datos diferentes en la pestaña Lista.")
        by_ref[ref] = item
        by_id[internal_id] = item

    if not by_ref:
        raise ValueError("No se encontraron registros válidos en la pestaña 'Lista'.")
    return by_ref


def catalog_count() -> int:
    with CATALOG_LOCK:
        return len(load_persistent_catalog())


def search_catalog(query: str = "", page: int = 1, page_size: int = CATALOG_PAGE_SIZE_DEFAULT) -> dict:
    page = max(1, page)
    page_size = min(max(1, page_size), CATALOG_PAGE_SIZE_MAX)
    needle = (query or "").strip().casefold()
    with CATALOG_LOCK:
        items = list(load_persistent_catalog().values())
    items.sort(key=lambda item: (item.ref, item.internal_id))
    if needle:
        items = [
            item for item in items
            if needle in item.ref.casefold()
            or needle in item.internal_id.casefold()
            or needle in item.name.casefold()
        ]
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]
    return {
        "ok": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size) if total else 1,
        "items": [item.to_dict() for item in page_items],
        "catalog_total": catalog_count(),
    }


def add_catalog_item(internal_id: str, name: str, ref: str) -> Tuple[bool, str, Optional[CatalogItem]]:
    internal_id = normalize_number(internal_id)
    name = (name or "").strip()
    ref = normalize_number(ref)
    if not internal_id or not name or not ref:
        return False, "ID interno, Ref y Nombre son obligatorios.", None
    with CATALOG_LOCK:
        catalog = load_persistent_catalog()
        if ref in catalog:
            return False, f"La referencia {ref} ya existe en el catálogo y no puede modificarse.", None
        backup_catalog_file()
        item = CatalogItem(internal_id=internal_id, name=name, ref=ref)
        catalog[ref] = item
        save_persistent_catalog(catalog)
        return True, "Artículo agregado al catálogo.", item


def update_catalog_item(ref: str, internal_id: str, name: str) -> Tuple[bool, str, Optional[CatalogItem]]:
    _ = (ref, internal_id, name)
    return False, "Los artículos existentes del catálogo no pueden modificarse.", None


def resolve_catalog_item(
    raw_id: str,
    raw_name: str,
    by_ref: Dict[str, CatalogItem],
    by_id: Optional[Dict[str, CatalogItem]] = None,
) -> Tuple[Optional[CatalogItem], str]:
    """Resolve using Ref only.

    The value in ID INTERNO ARTICULO is interpreted as a catalog Ref, never as
    the internal ID. Optional recovery extracts REF-xxxxxx from free text.
    """
    _ = by_id  # Call-site compatibility; lookup by internal ID is forbidden.
    normalized_ref = normalize_number(raw_id)
    if normalized_ref and normalized_ref in by_ref:
        return by_ref[normalized_ref], "reference"
    ref_from_id_text = extract_ref(raw_id)
    if ref_from_id_text and ref_from_id_text in by_ref:
        return by_ref[ref_from_id_text], "id_text"
    ref_from_name = extract_ref(raw_name)
    if ref_from_name and ref_from_name in by_ref:
        return by_ref[ref_from_name], "name_text"
    return None, ""


def apply_catalog_to_row(
    raw_id: str,
    raw_name: str,
    by_ref: Dict[str, CatalogItem],
    by_id: Dict[str, CatalogItem],
    summary: ProcessSummary,
    sheet_name: str,
    row_number: int,
) -> Tuple[str, str]:
    item, source_kind = resolve_catalog_item(raw_id, raw_name, by_ref, by_id)
    if item is None:
        value_for_report = raw_id or raw_name
        summary.not_found += 1
        summary.issues.append(Issue(
            sheet=sheet_name,
            row=row_number,
            value=value_for_report,
            reason=f"Referencia {value_for_report} no encontrada",
        ))
        return raw_id, raw_name

    # Always apply master catalog ID + full name when Ref matches.
    summary.processed += 1
    if source_kind == "id_text":
        summary.recovered_from_text += 1
    elif source_kind == "name_text":
        summary.recovered_from_name += 1
    return item.internal_id, item.name


def sanitize_base_name(filename: str) -> str:
    base = Path(filename or "archivo.xlsx").name
    stem = Path(base).stem or "archivo"
    cleaned = UNSAFE_FILENAME_RE.sub("_", stem).strip(" .")
    return cleaned or "archivo"


def sanitize_sheet_csv_name(sheet_name: str, used: Dict[str, int]) -> str:
    cleaned = UNSAFE_FILENAME_RE.sub("_", sheet_name or "hoja").strip(" .") or "hoja"
    # Prevent path segments after sanitization.
    cleaned = cleaned.replace("..", "_")
    candidate = f"{cleaned}.csv"
    if candidate not in used:
        used[candidate] = 1
        return candidate
    used[candidate] += 1
    return f"{cleaned}_{used[candidate]}.csv"


def rows_to_csv_bytes(headers: List[str], rows: List[List[str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def build_download_package(
    source_filename: str,
    csv_files: List[Tuple[str, bytes]],
) -> Tuple[bytes, str, str]:
    base = sanitize_base_name(source_filename)
    if len(csv_files) == 1:
        csv_name, csv_data = csv_files[0]
        # Single sheet: download as <workbook>_procesado.csv
        # Keep sheet name available in summary.output_files.
        filename = f"{base}_procesado.csv"
        return csv_data, filename, "text/csv; charset=utf-8"
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for csv_name, csv_data in csv_files:
            # Guard against path traversal inside zip members.
            safe_name = Path(csv_name).name
            zout.writestr(safe_name, csv_data)
    filename = f"{base}_procesado.zip"
    return memory.getvalue(), filename, "application/zip"


def decode_text_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def detect_csv_delimiter(sample: str) -> str:
    probe = "\n".join(sample.splitlines()[:10])
    if probe.strip():
        try:
            dialect = csv.Sniffer().sniff(probe, delimiters=",;")
            if dialect.delimiter in ",;":
                return dialect.delimiter
        except csv.Error:
            pass
    first = sample.splitlines()[0] if sample.splitlines() else ""
    if first.count(";") > first.count(","):
        return ";"
    return ","


def map_required_headers(headers: List[str]) -> Dict[str, int]:
    normalized_to_index: Dict[str, int] = {}
    for index, header in enumerate(headers):
        key = normalize_header(header)
        if key and key not in normalized_to_index:
            normalized_to_index[key] = index
    if TARGET_ID_HEADER not in normalized_to_index:
        raise ValueError("Falta la columna obligatoria 'ID INTERNO ARTICULO'.")
    if TARGET_NAME_HEADER not in normalized_to_index:
        raise ValueError("Falta la columna obligatoria 'NOMBRE DE ARTICULO'.")
    return {
        TARGET_ID_HEADER: normalized_to_index[TARGET_ID_HEADER],
        TARGET_NAME_HEADER: normalized_to_index[TARGET_NAME_HEADER],
    }


def process_csv_bytes(input_bytes: bytes, source_filename: str = "archivo.csv") -> ProcessOutput:
    if len(input_bytes) > MAX_FILE_SIZE:
        raise ValueError("El archivo supera el tamaño máximo permitido de 50 MB.")

    text = decode_text_bytes(input_bytes)
    if not text.strip():
        raise ValueError("El archivo CSV está vacío.")

    delimiter = detect_csv_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        headers = next(reader)
    except StopIteration as exc:
        raise ValueError("El archivo CSV no contiene encabezados.") from exc

    headers = [(cell or "").strip() for cell in headers]
    if not any(headers):
        raise ValueError("El archivo CSV no contiene encabezados válidos.")
    cols = map_required_headers(headers)
    id_idx = cols[TARGET_ID_HEADER]
    name_idx = cols[TARGET_NAME_HEADER]

    with CATALOG_LOCK:
        catalog = load_persistent_catalog()
    if not catalog:
        raise ValueError("El catálogo interno está vacío. Agrega artículos antes de procesar archivos.")
    by_ref, by_id = indexes_from_catalog(catalog)

    summary = ProcessSummary(catalog_entries=len(by_ref), catalog_added=0)
    export_rows: List[List[str]] = []
    row_number = 1
    for raw_row in reader:
        row_number += 1
        values = [""] * len(headers)
        for idx in range(len(headers)):
            if idx < len(raw_row):
                values[idx] = csv_cell_value(raw_row[idx])

        raw_id = values[id_idx] if id_idx < len(values) else ""
        raw_name = values[name_idx] if name_idx < len(values) else ""
        if not raw_id and not raw_name:
            summary.skipped_blank += 1
            if any(values):
                export_rows.append(values)
            continue

        new_id, new_name = apply_catalog_to_row(
            raw_id, raw_name, by_ref, by_id, summary, Path(source_filename).stem or "CSV", row_number
        )
        values[id_idx] = new_id
        values[name_idx] = new_name
        export_rows.append(values)

    summary.sheets_processed = 1
    csv_name = f"{sanitize_base_name(source_filename)}.csv"
    # For single CSV input, download name is <stem>_procesado.csv
    data, filename, content_type = build_download_package(
        source_filename,
        [(csv_name, rows_to_csv_bytes(headers, export_rows))],
    )
    summary.output_files.append(csv_name)
    return ProcessOutput(data=data, filename=filename, content_type=content_type, summary=summary)


def process_workbook_bytes(input_bytes: bytes, source_filename: str = "archivo.xlsx") -> ProcessOutput:
    if len(input_bytes) > MAX_FILE_SIZE:
        raise ValueError("El archivo supera el tamaño máximo permitido de 50 MB.")

    source = io.BytesIO(input_bytes)
    try:
        zin = zipfile.ZipFile(source, "r")
    except zipfile.BadZipFile as exc:
        raise ValueError("El archivo no es un .xlsx válido.") from exc

    with zin:
        required = {"xl/workbook.xml", "[Content_Types].xml"}
        if not required.issubset(set(zin.namelist())):
            raise ValueError("El archivo no tiene la estructura de un libro Excel .xlsx válido.")

        shared_strings = load_shared_strings(zin)
        sheets = workbook_sheet_targets(zin)

        with CATALOG_LOCK:
            catalog = load_persistent_catalog()
        if not catalog:
            raise ValueError("El catálogo interno está vacío. Agrega artículos antes de procesar archivos.")
        by_ref, by_id = indexes_from_catalog(catalog)

        summary = ProcessSummary(catalog_entries=len(by_ref), catalog_added=0)
        csv_files: List[Tuple[str, bytes]] = []
        used_names: Dict[str, int] = {}

        for sheet_name, target in sheets:
            if normalize_header(sheet_name) == "LISTA":
                # Compatibility: ignore Lista completely; never export or sync it.
                continue
            try:
                root = ET.fromstring(zin.read(target))
            except KeyError:
                continue

            header_info = find_header_row(root, shared_strings, (TARGET_ID_HEADER, TARGET_NAME_HEADER))
            if not header_info:
                continue
            header_row, cols, ordered_headers = header_info
            id_col = cols[TARGET_ID_HEADER]
            name_col = cols[TARGET_NAME_HEADER]
            display_headers = [label for _, label in ordered_headers]
            header_cols = [col for col, _ in ordered_headers]
            export_rows: List[List[str]] = []
            sheet_seen = False

            for row in worksheet_rows(root):
                row_number = int(row.get("r", "0"))
                if row_number <= header_row:
                    continue
                cells = row_cells(row)
                values_by_col = {
                    col: csv_cell_value(read_cell_value(cells.get(col), shared_strings))
                    for col in header_cols
                }
                raw_id = values_by_col.get(id_col, "")
                raw_name = values_by_col.get(name_col, "")

                if not raw_id and not raw_name:
                    summary.skipped_blank += 1
                    if any(values_by_col.get(col, "") for col in header_cols):
                        export_rows.append([values_by_col.get(col, "") for col in header_cols])
                        sheet_seen = True
                    continue

                sheet_seen = True
                new_id, new_name = apply_catalog_to_row(
                    raw_id, raw_name, by_ref, by_id, summary, sheet_name, row_number
                )
                values_by_col[id_col] = new_id
                values_by_col[name_col] = new_name
                export_rows.append([values_by_col.get(col, "") for col in header_cols])

            if sheet_seen or export_rows:
                summary.sheets_processed += 1
                csv_name = sanitize_sheet_csv_name(sheet_name, used_names)
                csv_files.append((csv_name, rows_to_csv_bytes(display_headers, export_rows)))
                summary.output_files.append(csv_name)

        if summary.sheets_processed == 0:
            raise ValueError(
                "No se encontró ninguna pestaña con las columnas 'ID INTERNO ARTICULO' y 'NOMBRE DE ARTICULO'."
            )

        data, filename, content_type = build_download_package(source_filename, csv_files)
        return ProcessOutput(data=data, filename=filename, content_type=content_type, summary=summary)


def process_input_bytes(input_bytes: bytes, source_filename: str = "archivo.xlsx") -> ProcessOutput:
    name = Path(source_filename or "archivo.xlsx").name
    lower = name.lower()
    if lower.endswith(".csv"):
        return process_csv_bytes(input_bytes, name)
    if lower.endswith(".xlsx"):
        return process_workbook_bytes(input_bytes, name)
    raise ValueError("Solo se permiten archivos .xlsx o .csv.")


DOWNLOADS: Dict[str, Tuple[float, str, bytes, str]] = {}
DOWNLOADS_LOCK = threading.Lock()


def cleanup_downloads() -> None:
    cutoff = time.time() - DOWNLOAD_TTL_SECONDS
    with DOWNLOADS_LOCK:
        expired = [token for token, (created, _, _, _) in DOWNLOADS.items() if created < cutoff]
        for token in expired:
            DOWNLOADS.pop(token, None)


def read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    content_length = int(handler.headers.get("Content-Length", "0") or "0")
    if content_length <= 0:
        return {}
    if content_length > 1024 * 1024:
        raise ValueError("Cuerpo de solicitud demasiado grande.")
    raw = handler.rfile.read(content_length)
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("JSON inválido.") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON inválido.")
    return payload


class AppHandler(BaseHTTPRequestHandler):
    server_version = "ExcelRefConverter/1.2"

    def log_message(self, format: str, *args) -> None:
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, relative_path: str, content_type: Optional[str] = None) -> None:
        path = (STATIC_DIR / relative_path).resolve()
        try:
            path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        guessed = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", guessed)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        cleanup_downloads()
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self._serve_static("styles.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self._serve_static("app.js", "application/javascript; charset=utf-8")
            return
        if parsed.path == "/api/health":
            self._send_json({"status": "ok", "catalog_total": catalog_count()})
            return
        if parsed.path == "/api/catalog":
            query = parse_qs(parsed.query)
            q = query.get("q", [""])[0]
            try:
                page = int(query.get("page", ["1"])[0] or "1")
                page_size = int(query.get("page_size", [str(CATALOG_PAGE_SIZE_DEFAULT)])[0] or str(CATALOG_PAGE_SIZE_DEFAULT))
            except ValueError:
                self._send_json({"ok": False, "error": "Parámetros de paginación inválidos."}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json(search_catalog(q, page, page_size))
            return
        if parsed.path == "/api/download":
            token = parse_qs(parsed.query).get("token", [""])[0]
            with DOWNLOADS_LOCK:
                item = DOWNLOADS.get(token)
            if not item:
                self._send_json({"ok": False, "error": "El archivo ya no está disponible. Procésalo nuevamente."}, HTTPStatus.NOT_FOUND)
                return
            _, filename, data, content_type = item
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/catalog":
            try:
                payload = read_json_body(self)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            ok, message, item = add_catalog_item(
                payload.get("internal_id", ""),
                payload.get("name", ""),
                payload.get("ref", ""),
            )
            if not ok:
                self._send_json({"ok": False, "error": message, "catalog_total": catalog_count()}, HTTPStatus.CONFLICT if "ya existe" in message else HTTPStatus.BAD_REQUEST)
                return
            self._send_json({
                "ok": True,
                "message": message,
                "item": item.to_dict() if item else None,
                "catalog_total": catalog_count(),
            })
            return

        if parsed.path != "/api/process":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            self._send_json({"ok": False, "error": "No se recibió ningún archivo."}, HTTPStatus.BAD_REQUEST)
            return
        if content_length > MAX_FILE_SIZE + 1024 * 1024:
            self._send_json({"ok": False, "error": "El archivo supera el tamaño máximo permitido de 50 MB."}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._send_json({"ok": False, "error": "Solicitud inválida."}, HTTPStatus.BAD_REQUEST)
            return
        body = self.rfile.read(content_length)
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        )
        file_data = None
        filename = None
        if message.is_multipart():
            for part in message.iter_parts():
                if part.get_content_disposition() != "form-data":
                    continue
                if part.get_param("name", header="content-disposition") == "file":
                    filename = part.get_filename()
                    file_data = part.get_payload(decode=True)
                    break
        if not filename or file_data is None:
            self._send_json({"ok": False, "error": "No se pudo leer el archivo enviado."}, HTTPStatus.BAD_REQUEST)
            return
        safe_name = Path(filename).name
        lower = safe_name.lower()
        if not (lower.endswith(".xlsx") or lower.endswith(".csv")):
            self._send_json({"ok": False, "error": "Solo se permiten archivos .xlsx o .csv."}, HTTPStatus.BAD_REQUEST)
            return
        if re.search(r"\.(exe|bat|cmd|ps1|js|vbs|msi|scr)$", safe_name, re.IGNORECASE):
            self._send_json({"ok": False, "error": "Tipo de archivo no permitido."}, HTTPStatus.BAD_REQUEST)
            return
        try:
            result = process_input_bytes(file_data, safe_name)
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            print(f"Error no controlado: {exc}", file=sys.stderr)
            self._send_json({"ok": False, "error": "No fue posible procesar el archivo. Verifica que no esté dañado."}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        token = secrets.token_urlsafe(24)
        with DOWNLOADS_LOCK:
            DOWNLOADS[token] = (time.time(), result.filename, result.data, result.content_type)
        self._send_json({
            "ok": True,
            "filename": result.filename,
            "downloadUrl": f"/api/download?token={token}",
            "contentType": result.content_type,
            "summary": result.summary.to_dict(),
            "catalog_total": catalog_count(),
        })

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        prefix = "/api/catalog/"
        if not parsed.path.startswith(prefix):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        ref = unquote(parsed.path[len(prefix):]).strip()
        if not ref or "/" in ref or "\\" in ref or ".." in ref:
            self._send_json({"ok": False, "error": "Referencia inválida."}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(
            {
                "ok": False,
                "error": "Los artículos existentes del catálogo no pueden modificarse.",
                "catalog_total": catalog_count(),
            },
            HTTPStatus.METHOD_NOT_ALLOWED,
        )


def process_file_cli(input_path: Path, output_path: Path) -> int:
    data = input_path.read_bytes()
    result = process_input_bytes(data, input_path.name)
    output_path.write_bytes(result.data)
    print(json.dumps({
        "input": str(input_path),
        "output": str(output_path),
        "download_filename": result.filename,
        "content_type": result.content_type,
        "summary": result.summary.to_dict(),
    }, ensure_ascii=False, indent=2))
    return 0


def run_server(host: str = HOST, port: int = PORT, open_browser: bool = True) -> None:
    ensure_catalog_file()
    server = ThreadingHTTPServer((host, port), AppHandler)
    url = f"http://{host}:{port}"
    print(f"Convertidor Excel ejecutándose en {url}")
    print(f"Catálogo local: {CATALOG_PATH}")
    print("Para detenerlo, presiona Ctrl+C.")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()


def main() -> int:
    ensure_catalog_file()
    parser = argparse.ArgumentParser(description="Convertidor de referencias a ID interno para archivos Excel/CSV.")
    parser.add_argument("--process", metavar="ARCHIVO", help="Procesa un archivo .xlsx o .csv desde consola.")
    parser.add_argument("--output", metavar="SALIDA", help="Ruta del archivo procesado (.csv o .zip).")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if args.process:
        input_path = Path(args.process).expanduser().resolve()
        if not input_path.exists():
            print(f"No existe el archivo: {input_path}", file=sys.stderr)
            return 2
        if args.output:
            output_path = Path(args.output).expanduser().resolve()
            return process_file_cli(input_path, output_path)
        preview = process_input_bytes(input_path.read_bytes(), input_path.name)
        output_path = input_path.with_name(preview.filename)
        output_path.write_bytes(preview.data)
        print(json.dumps({
            "input": str(input_path),
            "output": str(output_path),
            "download_filename": preview.filename,
            "content_type": preview.content_type,
            "summary": preview.summary.to_dict(),
        }, ensure_ascii=False, indent=2))
        return 0

    run_server(args.host, args.port, not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
