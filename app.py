from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import tempfile
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
IMPORT_TTL_SECONDS = 30 * 60
CATALOG_PAGE_SIZE_DEFAULT = 25
CATALOG_PAGE_SIZE_MAX = 100
MAX_CATALOG_BACKUPS = 20
MAX_ZIP_UNCOMPRESSED = 200 * 1024 * 1024
MAX_ZIP_ENTRIES = 5000
PREVIEW_SAMPLE_LIMIT = 15

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

REF_RE = re.compile(r"REF\s*[-–—−]\s*([A-Z0-9]+)", re.IGNORECASE)
NUMERIC_RE = re.compile(r"^-?\d+(?:[.,]0+)?$")
SCI_NUMERIC_RE = re.compile(r"^-?\d+(?:[.,]\d+)?[eE][+]?\d+$")
NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")
UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
INTERNAL_ID_RE = re.compile(r"^\d+$")

TARGET_ID_HEADER = "ID INTERNO ARTICULO"
TARGET_NAME_HEADER = "NOMBRE DE ARTICULO"
CATALOG_ID_HEADER = "ID INTERNO"
CATALOG_NAME_HEADER = "NOMBRE"
CATALOG_REF_HEADER = "REF"
CATALOG_DISPLAY_HEADER = "NOMBRE PARA MOSTRAR"
CATALOG_CSV_FIELDS = ["ID interno", "Nombre", "Ref"]

# Plantilla exacta de "Alexis Compras pruebas.csv" (UTF-8-BOM, delimitador ';', CRLF).
PURCHASE_HEADERS = [
    "ID SUBSIDIARIA",
    "iDENTIFICAR",
    "FECHA DE AJUSTE",
    "TIPO DE AJUSTE",
    "UBICACIÓN DE AJUSTE",
    "NOTA",
    "ID INTERNO ARTICULO",
    "NOMBRE DE ARTICULO",
    "AJUSTE DE CANTIDAD",
    "ESTADO",
    "CENTRO DE COSTOS",
    "SUBCENTRO DE COSTOS",
    "AREA",
    "SOLICITANTE",
]
PURCHASE_DELIMITER = ";"
PURCHASE_LINETERMINATOR = "\r\n"
PURCHASE_REQUIRED_FIELDS = [
    "ID SUBSIDIARIA",
    "iDENTIFICAR",
    "FECHA DE AJUSTE",
    "TIPO DE AJUSTE",
    "UBICACIÓN DE AJUSTE",
    "ID INTERNO ARTICULO",
    "NOMBRE DE ARTICULO",
    "AJUSTE DE CANTIDAD",
    "ESTADO",
]
PURCHASE_OPTIONAL_FIELDS = [
    "NOTA",
    "CENTRO DE COSTOS",
    "SUBCENTRO DE COSTOS",
    "AREA",
    "SOLICITANTE",
]
PURCHASE_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
PURCHASE_QTY_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")
CATALOG_SUGGEST_LIMIT_DEFAULT = 20
CATALOG_SUGGEST_LIMIT_MAX = 50
PURCHASE_EXPORT_MAX_ROWS = 5000

CATALOG_LOCK = threading.RLock()
ADMIN_TOKEN_ENV = "CATALOG_ADMIN_TOKEN"


@dataclass
class Issue:
    sheet: str
    row: int
    value: str
    reason: str


@dataclass
class ProcessSummary:
    total_rows: int = 0
    converted: int = 0
    not_found: int = 0
    blank_ref: int = 0
    errors: int = 0
    skipped_blank: int = 0
    recovered_from_text: int = 0
    recovered_from_name: int = 0
    sheets_processed: int = 0
    catalog_entries: int = 0
    conversion_pct: float = 0.0
    output_files: List[str] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)

    # Backwards-compatible aliases used by older clients
    @property
    def processed(self) -> int:
        return self.converted

    def to_dict(self):
        data = asdict(self)
        data["processed"] = self.converted
        data["already_internal"] = 0
        data["catalog_added"] = 0
        return data


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
    issues_csv: bytes = b""


@dataclass
class ImportConflict:
    sheet: str
    row: int
    internal_id: str
    ref: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImportChange:
    kind: str  # new | update | unchanged
    internal_id: str
    before: Optional[dict]
    after: dict

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ImportPreview:
    token: str
    fingerprint: str
    analyzed_rows: int
    new_count: int
    update_count: int
    unchanged_count: int
    conflict_count: int
    invalid_count: int
    changes: List[ImportChange]
    conflicts: List[ImportConflict]
    invalid: List[ImportConflict]
    pending_items: Dict[str, CatalogItem]
    created_at: float = field(default_factory=time.time)

    def summary_dict(self) -> dict:
        samples = [c.to_dict() for c in self.changes if c.kind in {"new", "update"}][:PREVIEW_SAMPLE_LIMIT]
        return {
            "token": self.token,
            "analyzed_rows": self.analyzed_rows,
            "new_count": self.new_count,
            "update_count": self.update_count,
            "unchanged_count": self.unchanged_count,
            "conflict_count": self.conflict_count,
            "invalid_count": self.invalid_count,
            "samples": samples,
            "conflicts": [c.to_dict() for c in self.conflicts[:100]],
            "invalid": [c.to_dict() for c in self.invalid[:100]],
            "apply_ready": self.new_count + self.update_count > 0,
        }


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
    """Normalize catalog Ref / ID values without inventing data.

    Keeps legitimate leading zeros. Avoids float() for long digit strings.
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
        # Only convert scientific notation when the integer form is exact and short.
        try:
            as_float = float(compact.replace(",", "."))
            as_int = int(as_float)
            if as_float == float(as_int) and abs(as_int) < 10**15:
                return str(as_int)
        except (TypeError, ValueError, OverflowError):
            pass
        return compact
    if re.fullmatch(r"-?\d+", compact):
        return compact
    return text


def normalize_ref_value(value: object) -> str:
    """Preserve commercial references as text (leading zeros, alphanumeric)."""
    if value is None:
        return ""
    text = strip_invisible_chars(str(value)).strip().strip("'\"")
    if not text:
        return ""
    compact = text.replace(" ", "")
    if SCI_NUMERIC_RE.fullmatch(compact):
        return normalize_number(compact)
    if NUMERIC_RE.fullmatch(compact):
        return re.split(r"[.,]", compact, maxsplit=1)[0]
    return text


def csv_cell_value(value: object) -> str:
    """Normalize values for CSV export, avoiding trailing .0 on IDs/refs."""
    if value is None:
        return ""
    text = strip_invisible_chars(str(value)).strip()
    if not text:
        return ""
    normalized = normalize_ref_value(text)
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


def validate_zip_safety(zf: zipfile.ZipFile) -> None:
    total_size = 0
    names = zf.namelist()
    if len(names) > MAX_ZIP_ENTRIES:
        raise ValueError("El archivo Excel contiene demasiadas entradas internas.")
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            raise ValueError("El archivo Excel contiene rutas internas no permitidas.")
        total_size += max(0, info.file_size)
        if total_size > MAX_ZIP_UNCOMPRESSED:
            raise ValueError("El archivo Excel supera el límite de descompresión permitido.")


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
    optional: Tuple[str, ...] = (),
) -> Optional[Tuple[int, Dict[str, int], List[Tuple[int, str]]]]:
    required_set = set(required)
    wanted = required_set | set(optional)
    for row in list(worksheet_rows(root))[:40]:
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
            mapped = {name: headers_by_name[name] for name in wanted if name in headers_by_name}
            return int(row.get("r", "0")), mapped, ordered
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


def catalog_fingerprint(path: Optional[Path] = None) -> str:
    target = path or CATALOG_PATH
    if target == CATALOG_PATH:
        ensure_catalog_file()
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    stat = target.stat()
    digest.update(str(stat.st_mtime_ns).encode("ascii"))
    digest.update(str(stat.st_size).encode("ascii"))
    return digest.hexdigest()


def backup_catalog_file() -> Optional[Path]:
    """Create a catalog backup before real mutations. Keeps the newest 20 files."""
    ensure_data_dir()
    if not CATALOG_PATH.exists() or CATALOG_PATH.stat().st_size == 0:
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = BACKUP_DIR / f"catalogo_articulos_{stamp}.csv"
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


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8-sig") -> None:
    ensure_data_dir()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def load_persistent_catalog(path: Optional[Path] = None) -> Dict[str, CatalogItem]:
    """Load catalog keyed by internal ID (article identity)."""
    target = path or CATALOG_PATH
    if target == CATALOG_PATH:
        ensure_catalog_file()
    by_id: Dict[str, CatalogItem] = {}
    if not target.exists():
        return by_id
    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row:
                continue
            internal_id = normalize_number(row.get("ID interno") or row.get("ID INTERNO") or "")
            name = (row.get("Nombre") or row.get("NOMBRE") or "").strip()
            ref = normalize_ref_value(row.get("Ref") or row.get("REF") or "")
            if not internal_id or not name or not ref:
                continue
            by_id[internal_id] = CatalogItem(internal_id=internal_id, name=name, ref=ref)
    return by_id


def save_persistent_catalog(by_id: Dict[str, CatalogItem], path: Optional[Path] = None) -> None:
    target = path or CATALOG_PATH
    items = sorted(by_id.values(), key=lambda item: (item.internal_id, item.ref))
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CATALOG_CSV_FIELDS)
    writer.writeheader()
    for item in items:
        writer.writerow({
            "ID interno": item.internal_id,
            "Nombre": item.name,
            "Ref": item.ref,
        })
    atomic_write_text(target, buffer.getvalue(), encoding="utf-8-sig")


def indexes_from_catalog(by_id: Dict[str, CatalogItem]) -> Tuple[Dict[str, CatalogItem], Dict[str, CatalogItem]]:
    """Return (by_ref, by_id). First matching ref wins; duplicates should already be rejected on import."""
    by_ref: Dict[str, CatalogItem] = {}
    for item in by_id.values():
        if item.ref and item.ref not in by_ref:
            by_ref[item.ref] = item
    return by_ref, by_id


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


def suggest_catalog(query: str = "", limit: int = CATALOG_SUGGEST_LIMIT_DEFAULT) -> dict:
    """Fast typeahead over catalog without shipping the full catalog to the browser."""
    limit = min(max(1, limit), CATALOG_SUGGEST_LIMIT_MAX)
    needle = (query or "").strip()
    if len(needle) < 1:
        return {"ok": True, "items": [], "query": query, "catalog_total": catalog_count()}
    needle_cf = needle.casefold()
    needle_norm = normalize_ref_value(needle)
    with CATALOG_LOCK:
        items = list(load_persistent_catalog().values())

    exact: List[CatalogItem] = []
    prefix: List[CatalogItem] = []
    contains: List[CatalogItem] = []
    for item in items:
        ref_cf = item.ref.casefold()
        id_cf = item.internal_id.casefold()
        name_cf = item.name.casefold()
        if needle_norm and (item.ref == needle_norm or item.internal_id == needle_norm):
            exact.append(item)
        elif ref_cf.startswith(needle_cf) or id_cf.startswith(needle_cf):
            prefix.append(item)
        elif needle_cf in ref_cf or needle_cf in id_cf or needle_cf in name_cf:
            contains.append(item)
        if len(exact) >= limit:
            break

    ranked = exact + prefix + contains
    # De-duplicate while preserving rank.
    seen: set[str] = set()
    selected: List[CatalogItem] = []
    for item in ranked:
        if item.internal_id in seen:
            continue
        seen.add(item.internal_id)
        selected.append(item)
        if len(selected) >= limit:
            break

    return {
        "ok": True,
        "query": query,
        "items": [item.to_dict() for item in selected],
        "catalog_total": catalog_count(),
    }


def purchase_template_contract() -> dict:
    return {
        "ok": True,
        "headers": list(PURCHASE_HEADERS),
        "delimiter": PURCHASE_DELIMITER,
        "encoding": "utf-8-sig",
        "line_terminator": "CRLF",
        "required_fields": list(PURCHASE_REQUIRED_FIELDS),
        "optional_fields": list(PURCHASE_OPTIONAL_FIELDS),
        "article_fields": {
            "id": TARGET_ID_HEADER,
            "name": TARGET_NAME_HEADER,
        },
        "notes": (
            "Contrato tomado de 'Alexis Compras pruebas.csv'. "
            "Los encabezados y el orden son exactos (incluye 'iDENTIFICAR')."
        ),
    }


def _cell_str(value: object) -> str:
    if value is None:
        return ""
    return strip_invisible_chars(str(value)).strip()


def validate_purchase_rows(
    rows: List[dict],
    catalog: Optional[Dict[str, CatalogItem]] = None,
) -> Tuple[List[dict], List[dict]]:
    """Validate purchase form rows. Returns (normalized_rows, errors)."""
    if catalog is None:
        with CATALOG_LOCK:
            catalog = load_persistent_catalog()
    if not isinstance(rows, list):
        raise ValueError("El cuerpo debe incluir una lista 'rows'.")
    if not rows:
        raise ValueError("Agrega al menos una fila antes de descargar.")
    if len(rows) > PURCHASE_EXPORT_MAX_ROWS:
        raise ValueError(f"Máximo {PURCHASE_EXPORT_MAX_ROWS} filas por descarga.")

    normalized: List[dict] = []
    errors: List[dict] = []

    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            errors.append({"row": index, "field": "", "message": "Fila inválida."})
            continue
        row = {header: _cell_str(raw.get(header, "")) for header in PURCHASE_HEADERS}
        row_errors: List[dict] = []

        for field_name in PURCHASE_REQUIRED_FIELDS:
            if not row[field_name]:
                row_errors.append({
                    "row": index,
                    "field": field_name,
                    "message": f"Campo obligatorio vacío: {field_name}",
                })

        if row["FECHA DE AJUSTE"] and not PURCHASE_DATE_RE.fullmatch(row["FECHA DE AJUSTE"]):
            row_errors.append({
                "row": index,
                "field": "FECHA DE AJUSTE",
                "message": "Fecha inválida. Usa el formato DD/MM/AAAA.",
            })

        if row["AJUSTE DE CANTIDAD"] and not PURCHASE_QTY_RE.fullmatch(row["AJUSTE DE CANTIDAD"].replace(" ", "")):
            row_errors.append({
                "row": index,
                "field": "AJUSTE DE CANTIDAD",
                "message": "Cantidad inválida. Usa un número (puede ser negativo).",
            })

        internal_id = normalize_number(row[TARGET_ID_HEADER])
        name = row[TARGET_NAME_HEADER]
        if internal_id:
            item = catalog.get(internal_id)
            if item is None:
                row_errors.append({
                    "row": index,
                    "field": TARGET_ID_HEADER,
                    "message": f"El artículo con ID interno {internal_id} no existe en el catálogo.",
                })
            else:
                row[TARGET_ID_HEADER] = item.internal_id
                if name and name != item.name:
                    row_errors.append({
                        "row": index,
                        "field": TARGET_NAME_HEADER,
                        "message": "El nombre no corresponde al ID interno seleccionado en el catálogo.",
                    })
                elif not name:
                    row[TARGET_NAME_HEADER] = item.name

        if row_errors:
            errors.extend(row_errors)
        else:
            normalized.append(row)

    return normalized, errors


def export_purchase_csv(rows: List[dict]) -> Tuple[bytes, str, List[dict]]:
    """Validate and build purchase CSV bytes. Does not persist to disk."""
    with CATALOG_LOCK:
        catalog = load_persistent_catalog()
    if not catalog:
        raise ValueError("El catálogo está vacío. Actualiza el catálogo antes de crear archivos.")
    normalized, errors = validate_purchase_rows(rows, catalog)
    if errors:
        return b"", "", errors

    buffer = io.StringIO(newline="")
    writer = csv.writer(
        buffer,
        delimiter=PURCHASE_DELIMITER,
        lineterminator=PURCHASE_LINETERMINATOR,
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writerow(PURCHASE_HEADERS)
    for row in normalized:
        writer.writerow([row.get(header, "") for header in PURCHASE_HEADERS])

    # csv module with lineterminator already emits CRLF; encode with BOM.
    data = buffer.getvalue().encode("utf-8-sig")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"compras_{stamp}.csv"
    return data, filename, []


def add_catalog_item(internal_id: str, name: str, ref: str) -> Tuple[bool, str, Optional[CatalogItem]]:
    internal_id = normalize_number(internal_id)
    name = (name or "").strip()
    ref = normalize_ref_value(ref)
    if not internal_id or not name or not ref:
        return False, "ID interno, Ref y Nombre son obligatorios.", None
    if not INTERNAL_ID_RE.fullmatch(internal_id):
        return False, "ID interno inválido: debe ser numérico.", None
    with CATALOG_LOCK:
        catalog = load_persistent_catalog()
        by_ref, _ = indexes_from_catalog(catalog)
        if internal_id in catalog:
            return False, f"El ID interno {internal_id} ya existe en el catálogo.", None
        if ref in by_ref:
            return False, f"La referencia {ref} ya existe en el catálogo y no puede modificarse.", None
        backup_catalog_file()
        item = CatalogItem(internal_id=internal_id, name=name, ref=ref)
        catalog[internal_id] = item
        save_persistent_catalog(catalog)
        return True, "Artículo agregado al catálogo.", item


def resolve_catalog_item(
    raw_id: str,
    raw_name: str,
    by_ref: Dict[str, CatalogItem],
) -> Tuple[Optional[CatalogItem], str, str]:
    """Resolve using Ref only. Never treat the input value as an internal ID.

    Returns (item, source_kind, lookup_ref).
    """
    normalized_ref = normalize_ref_value(raw_id)
    if normalized_ref and normalized_ref in by_ref:
        return by_ref[normalized_ref], "reference", normalized_ref
    ref_from_id_text = extract_ref(raw_id)
    if ref_from_id_text and ref_from_id_text in by_ref:
        return by_ref[ref_from_id_text], "id_text", ref_from_id_text
    if not normalized_ref:
        ref_from_name = extract_ref(raw_name)
        if ref_from_name and ref_from_name in by_ref:
            return by_ref[ref_from_name], "name_text", ref_from_name
    return None, "", normalized_ref


def apply_catalog_to_row(
    raw_id: str,
    raw_name: str,
    by_ref: Dict[str, CatalogItem],
    summary: ProcessSummary,
    sheet_name: str,
    row_number: int,
) -> Tuple[str, str]:
    item, source_kind, lookup_ref = resolve_catalog_item(raw_id, raw_name, by_ref)
    if not raw_id and not lookup_ref and not item:
        summary.blank_ref += 1
        summary.issues.append(Issue(
            sheet=sheet_name,
            row=row_number,
            value=raw_name or "",
            reason="Sin referencia en ID INTERNO ARTICULO",
        ))
        return raw_id, raw_name

    if item is None:
        value_for_report = raw_id or lookup_ref or raw_name
        summary.not_found += 1
        summary.issues.append(Issue(
            sheet=sheet_name,
            row=row_number,
            value=value_for_report,
            reason=f"Referencia {value_for_report} no encontrada",
        ))
        return raw_id, raw_name

    summary.converted += 1
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


def issues_to_csv_bytes(issues: List[Issue]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Origen", "Fila", "Valor", "Motivo"])
    for issue in issues:
        writer.writerow([issue.sheet, issue.row, issue.value, issue.reason])
    return buffer.getvalue().encode("utf-8-sig")


def build_download_package(
    source_filename: str,
    csv_files: List[Tuple[str, bytes]],
) -> Tuple[bytes, str, str]:
    base = sanitize_base_name(source_filename)
    if len(csv_files) == 1:
        _csv_name, csv_data = csv_files[0]
        filename = f"{base}_procesado.csv"
        return csv_data, filename, "text/csv; charset=utf-8"
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for csv_name, csv_data in csv_files:
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
            dialect = csv.Sniffer().sniff(probe, delimiters=",;\t|")
            if dialect.delimiter in ",;\t|":
                return dialect.delimiter
        except csv.Error:
            pass
    first = sample.splitlines()[0] if sample.splitlines() else ""
    counts = {d: first.count(d) for d in (",", ";", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


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


def finalize_conversion_summary(summary: ProcessSummary) -> None:
    eligible = summary.converted + summary.not_found + summary.blank_ref + summary.errors
    summary.total_rows = eligible + summary.skipped_blank
    if eligible > 0:
        summary.conversion_pct = round(100.0 * summary.converted / eligible, 2)
    else:
        summary.conversion_pct = 0.0
    if eligible > 0 and summary.converted == 0:
        raise ValueError(
            "Ninguna referencia pudo convertirse. Verifica que el catálogo contenga las referencias "
            "del archivo o actualiza el catálogo desde el inventario."
        )


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
        raise ValueError("El catálogo interno está vacío. Importa o agrega artículos antes de procesar archivos.")
    by_ref, _by_id = indexes_from_catalog(catalog)

    summary = ProcessSummary(catalog_entries=len(catalog))
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
            raw_id, raw_name, by_ref, summary, Path(source_filename).stem or "CSV", row_number
        )
        values[id_idx] = new_id
        values[name_idx] = new_name
        export_rows.append(values)

    finalize_conversion_summary(summary)
    summary.sheets_processed = 1
    csv_name = f"{sanitize_base_name(source_filename)}.csv"
    data, filename, content_type = build_download_package(
        source_filename,
        [(csv_name, rows_to_csv_bytes(headers, export_rows))],
    )
    summary.output_files.append(csv_name)
    return ProcessOutput(
        data=data,
        filename=filename,
        content_type=content_type,
        summary=summary,
        issues_csv=issues_to_csv_bytes(summary.issues),
    )


def process_workbook_bytes(input_bytes: bytes, source_filename: str = "archivo.xlsx") -> ProcessOutput:
    if len(input_bytes) > MAX_FILE_SIZE:
        raise ValueError("El archivo supera el tamaño máximo permitido de 50 MB.")

    source = io.BytesIO(input_bytes)
    try:
        zin = zipfile.ZipFile(source, "r")
    except zipfile.BadZipFile as exc:
        raise ValueError("El archivo no es un .xlsx válido.") from exc

    with zin:
        validate_zip_safety(zin)
        required = {"xl/workbook.xml", "[Content_Types].xml"}
        if not required.issubset(set(zin.namelist())):
            raise ValueError("El archivo no tiene la estructura de un libro Excel .xlsx válido.")

        shared_strings = load_shared_strings(zin)
        sheets = workbook_sheet_targets(zin)

        with CATALOG_LOCK:
            catalog = load_persistent_catalog()
        if not catalog:
            raise ValueError("El catálogo interno está vacío. Importa o agrega artículos antes de procesar archivos.")
        by_ref, _by_id = indexes_from_catalog(catalog)

        summary = ProcessSummary(catalog_entries=len(catalog))
        csv_files: List[Tuple[str, bytes]] = []
        used_names: Dict[str, int] = {}

        for sheet_name, target in sheets:
            if normalize_header(sheet_name) == "LISTA":
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
                    raw_id, raw_name, by_ref, summary, sheet_name, row_number
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

        finalize_conversion_summary(summary)
        data, filename, content_type = build_download_package(source_filename, csv_files)
        return ProcessOutput(
            data=data,
            filename=filename,
            content_type=content_type,
            summary=summary,
            issues_csv=issues_to_csv_bytes(summary.issues),
        )


def process_input_bytes(input_bytes: bytes, source_filename: str = "archivo.xlsx") -> ProcessOutput:
    name = Path(source_filename or "archivo.xlsx").name
    lower = name.lower()
    if lower.endswith(".csv"):
        return process_csv_bytes(input_bytes, name)
    if lower.endswith(".xlsx"):
        return process_workbook_bytes(input_bytes, name)
    raise ValueError("Solo se permiten archivos .xlsx o .csv.")


# ---------------------------------------------------------------------------
# Catalog import (inventory Excel/CSV)
# ---------------------------------------------------------------------------

def map_inventory_headers(headers: List[str]) -> Dict[str, int]:
    normalized_to_index: Dict[str, int] = {}
    for index, header in enumerate(headers):
        key = normalize_header(header)
        if key and key not in normalized_to_index:
            normalized_to_index[key] = index

    id_aliases = (CATALOG_ID_HEADER, "ID INTERNO ARTICULO", "ID")
    name_aliases = (CATALOG_NAME_HEADER, "DESCRIPCION", "DESCRIPCIÓN")
    ref_aliases = (CATALOG_DISPLAY_HEADER, CATALOG_REF_HEADER, "REFERENCIA", "CODIGO", "CÓDIGO")

    def pick(aliases: Tuple[str, ...]) -> Optional[int]:
        for alias in aliases:
            if alias in normalized_to_index:
                return normalized_to_index[alias]
        return None

    id_idx = pick(id_aliases)
    name_idx = pick(name_aliases)
    ref_idx = pick(ref_aliases)
    if id_idx is None or name_idx is None:
        raise ValueError(
            "No se pudieron identificar las columnas requeridas "
            "('ID interno', 'Nombre' y 'Nombre para mostrar'/Ref)."
        )
    mapped = {
        CATALOG_ID_HEADER: id_idx,
        CATALOG_NAME_HEADER: name_idx,
    }
    if ref_idx is not None:
        mapped[CATALOG_REF_HEADER] = ref_idx
    return mapped


def resolve_import_ref(raw_ref: str, raw_name: str) -> str:
    ref = normalize_ref_value(raw_ref)
    if ref:
        return ref
    extracted = extract_ref(raw_name)
    return extracted or ""


def iter_inventory_rows_from_csv(input_bytes: bytes) -> Iterable[Tuple[str, int, str, str, str]]:
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
    cols = map_inventory_headers(headers)
    id_idx = cols[CATALOG_ID_HEADER]
    name_idx = cols[CATALOG_NAME_HEADER]
    ref_idx = cols.get(CATALOG_REF_HEADER)
    sheet = "CSV"
    row_number = 1
    for raw_row in reader:
        row_number += 1
        def cell(idx: Optional[int]) -> str:
            if idx is None or idx >= len(raw_row):
                return ""
            return strip_invisible_chars(str(raw_row[idx] or "")).strip()
        yield sheet, row_number, cell(id_idx), cell(name_idx), cell(ref_idx)


def _discover_inventory_header_row(
    root: ET.Element,
    shared_strings: List[str],
) -> Optional[Tuple[int, Dict[str, int]]]:
    """Locate inventory headers with flexible aliases across the first rows."""
    for row in list(worksheet_rows(root))[:40]:
        ordered: List[Tuple[int, str]] = []
        for col, cell in sorted(row_cells(row).items()):
            raw = read_cell_value(cell, shared_strings).strip()
            if raw:
                ordered.append((col, raw))
        if not ordered:
            continue
        try:
            mapped = map_inventory_headers([label for _, label in ordered])
        except ValueError:
            continue
        col_by_field = {field_name: ordered[list_idx][0] for field_name, list_idx in mapped.items()}
        return int(row.get("r", "0")), col_by_field
    return None


def iter_inventory_rows_from_xlsx(input_bytes: bytes) -> Iterable[Tuple[str, int, str, str, str]]:
    source = io.BytesIO(input_bytes)
    try:
        zin = zipfile.ZipFile(source, "r")
    except zipfile.BadZipFile as exc:
        raise ValueError("El archivo no es un .xlsx válido.") from exc

    found_any_header = False
    with zin:
        validate_zip_safety(zin)
        required = {"xl/workbook.xml", "[Content_Types].xml"}
        if not required.issubset(set(zin.namelist())):
            raise ValueError("El archivo no tiene la estructura de un libro Excel .xlsx válido.")
        shared_strings = load_shared_strings(zin)
        sheets = workbook_sheet_targets(zin)
        for sheet_name, target in sheets:
            try:
                root = ET.fromstring(zin.read(target))
            except KeyError:
                continue
            discovered = _discover_inventory_header_row(root, shared_strings)
            if not discovered:
                continue
            found_any_header = True
            header_row, cols = discovered
            id_col = cols[CATALOG_ID_HEADER]
            name_col = cols[CATALOG_NAME_HEADER]
            ref_col = cols.get(CATALOG_REF_HEADER)
            for row in worksheet_rows(root):
                row_number = int(row.get("r", "0"))
                if row_number <= header_row:
                    continue
                cells = row_cells(row)
                internal_id = read_cell_value(cells.get(id_col), shared_strings).strip()
                name = read_cell_value(cells.get(name_col), shared_strings).strip()
                ref = read_cell_value(cells.get(ref_col), shared_strings).strip() if ref_col else ""
                yield sheet_name, row_number, internal_id, name, ref

    if not found_any_header:
        raise ValueError(
            "No se encontraron hojas con las columnas 'ID interno', 'Nombre' "
            "y 'Nombre para mostrar' (o Ref)."
        )


def iter_inventory_rows(input_bytes: bytes, filename: str) -> Iterable[Tuple[str, int, str, str, str]]:
    lower = Path(filename).name.lower()
    if lower.endswith(".csv"):
        yield from iter_inventory_rows_from_csv(input_bytes)
        return
    if lower.endswith(".xlsx"):
        yield from iter_inventory_rows_from_xlsx(input_bytes)
        return
    raise ValueError("Solo se permiten archivos .xlsx o .csv.")


def build_import_preview(
    input_bytes: bytes,
    filename: str,
    catalog_path: Optional[Path] = None,
) -> ImportPreview:
    catalog_path = catalog_path or CATALOG_PATH
    if len(input_bytes) > MAX_FILE_SIZE:
        raise ValueError("El archivo supera el tamaño máximo permitido de 50 MB.")

    with CATALOG_LOCK:
        current = load_persistent_catalog(catalog_path)
        fingerprint = catalog_fingerprint(catalog_path) if catalog_path == CATALOG_PATH else catalog_fingerprint(catalog_path)

    by_ref = {item.ref: item for item in current.values()}
    file_by_id: Dict[str, Tuple[str, int, CatalogItem]] = {}
    file_ref_owners: Dict[str, str] = {}
    conflicts: List[ImportConflict] = []
    invalid: List[ImportConflict] = []
    analyzed = 0

    for sheet, row_number, raw_id, raw_name, raw_ref in iter_inventory_rows(input_bytes, filename):
        analyzed += 1
        internal_id = normalize_number(raw_id)
        name = strip_invisible_chars(raw_name or "").strip()
        ref = resolve_import_ref(raw_ref, name)

        if not internal_id and not name and not ref:
            analyzed -= 1
            continue

        if not internal_id or not INTERNAL_ID_RE.fullmatch(internal_id):
            invalid.append(ImportConflict(sheet, row_number, internal_id or raw_id, ref, "ID interno inválido"))
            continue
        if not ref:
            invalid.append(ImportConflict(sheet, row_number, internal_id, ref, "Referencia ausente e irrecuperable"))
            continue
        if not name:
            # Empty name is allowed for update (keep existing); for new items reject.
            if internal_id not in current:
                invalid.append(ImportConflict(sheet, row_number, internal_id, ref, "Nombre obligatorio para artículos nuevos"))
                continue

        item = CatalogItem(internal_id=internal_id, name=name, ref=ref)

        # Duplicate refs inside file with contradictory IDs
        prior_owner = file_ref_owners.get(ref)
        if prior_owner and prior_owner != internal_id:
            conflicts.append(ImportConflict(
                sheet, row_number, internal_id, ref,
                f"Referencia duplicada en el archivo (también asignada a ID {prior_owner})",
            ))
            continue

        if internal_id in file_by_id:
            prev_sheet, prev_row, prev_item = file_by_id[internal_id]
            if prev_item != item and (prev_item.ref != item.ref or (item.name and prev_item.name != item.name)):
                conflicts.append(ImportConflict(
                    sheet, row_number, internal_id, ref,
                    f"ID interno duplicado en el archivo con datos distintos (fila {prev_row} de {prev_sheet})",
                ))
                continue

        # Ref owned by another catalog ID
        existing_ref_owner = by_ref.get(ref)
        if existing_ref_owner and existing_ref_owner.internal_id != internal_id:
            conflicts.append(ImportConflict(
                sheet, row_number, internal_id, ref,
                f"La referencia pertenece al ID interno {existing_ref_owner.internal_id}",
            ))
            continue

        file_ref_owners[ref] = internal_id
        file_by_id[internal_id] = (sheet, row_number, item)

    changes: List[ImportChange] = []
    pending: Dict[str, CatalogItem] = {}

    for internal_id, (_sheet, _row, incoming) in file_by_id.items():
        existing = current.get(internal_id)
        if existing is None:
            if not incoming.name:
                continue
            pending[internal_id] = incoming
            changes.append(ImportChange("new", internal_id, None, incoming.to_dict()))
            continue

        # Empty incoming fields keep existing values
        merged_name = incoming.name if incoming.name else existing.name
        merged_ref = incoming.ref if incoming.ref else existing.ref
        # If ref changes, ensure it does not collide with another ID
        if merged_ref != existing.ref:
            owner = by_ref.get(merged_ref)
            if owner and owner.internal_id != internal_id:
                conflicts.append(ImportConflict(
                    "catálogo", 0, internal_id, merged_ref,
                    f"La nueva referencia pertenece al ID interno {owner.internal_id}",
                ))
                continue
            # Also check against other pending merges
            for other_id, other_item in pending.items():
                if other_id != internal_id and other_item.ref == merged_ref:
                    conflicts.append(ImportConflict(
                        "catálogo", 0, internal_id, merged_ref,
                        f"La nueva referencia colisiona con la actualización del ID {other_id}",
                    ))
                    break
            else:
                merged = CatalogItem(internal_id=internal_id, name=merged_name, ref=merged_ref)
                if merged == existing:
                    changes.append(ImportChange("unchanged", internal_id, existing.to_dict(), merged.to_dict()))
                else:
                    pending[internal_id] = merged
                    changes.append(ImportChange("update", internal_id, existing.to_dict(), merged.to_dict()))
            continue

        merged = CatalogItem(internal_id=internal_id, name=merged_name, ref=merged_ref)
        if merged == existing:
            changes.append(ImportChange("unchanged", internal_id, existing.to_dict(), merged.to_dict()))
        else:
            pending[internal_id] = merged
            changes.append(ImportChange("update", internal_id, existing.to_dict(), merged.to_dict()))

    preview = ImportPreview(
        token=secrets.token_urlsafe(24),
        fingerprint=fingerprint,
        analyzed_rows=analyzed,
        new_count=sum(1 for c in changes if c.kind == "new"),
        update_count=sum(1 for c in changes if c.kind == "update"),
        unchanged_count=sum(1 for c in changes if c.kind == "unchanged"),
        conflict_count=len(conflicts),
        invalid_count=len(invalid),
        changes=changes,
        conflicts=conflicts,
        invalid=invalid,
        pending_items=pending,
    )
    return preview


def apply_import_preview(preview: ImportPreview, catalog_path: Optional[Path] = None) -> dict:
    catalog_path = catalog_path or CATALOG_PATH
    with CATALOG_LOCK:
        current_fp = catalog_fingerprint(catalog_path)
        if current_fp != preview.fingerprint:
            raise ValueError(
                "El catálogo cambió desde la vista previa. Vuelve a generar la vista previa e inténtalo de nuevo."
            )
        current = load_persistent_catalog(catalog_path)
        by_ref = {item.ref: item for item in current.values()}

        # Re-validate pending items against live catalog
        applied_new = 0
        applied_update = 0
        rejected = 0
        for internal_id, incoming in preview.pending_items.items():
            existing = current.get(internal_id)
            owner = by_ref.get(incoming.ref)
            if owner and owner.internal_id != internal_id:
                rejected += 1
                continue
            if existing is None:
                current[internal_id] = incoming
                by_ref[incoming.ref] = incoming
                applied_new += 1
            else:
                # Drop old ref mapping if changed
                if existing.ref != incoming.ref and by_ref.get(existing.ref) is existing:
                    del by_ref[existing.ref]
                current[internal_id] = incoming
                by_ref[incoming.ref] = incoming
                applied_update += 1

        if applied_new + applied_update == 0:
            return {
                "ok": True,
                "message": "No había cambios aplicables.",
                "applied_new": 0,
                "applied_update": 0,
                "rejected": rejected,
                "catalog_total": len(current),
                "backup": None,
            }

        backup = backup_catalog_file() if catalog_path == CATALOG_PATH else None
        try:
            save_persistent_catalog(current, catalog_path)
        except Exception:
            if backup and backup.exists() and catalog_path == CATALOG_PATH:
                shutil.copy2(backup, catalog_path)
            raise

        return {
            "ok": True,
            "message": "Catálogo actualizado correctamente.",
            "applied_new": applied_new,
            "applied_update": applied_update,
            "rejected": rejected,
            "catalog_total": len(current),
            "backup": backup.name if backup else None,
        }


def import_errors_csv(preview: ImportPreview) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["Tipo", "Origen", "Fila", "ID interno", "Ref", "Motivo"])
    for item in preview.conflicts:
        writer.writerow(["conflicto", item.sheet, item.row, item.internal_id, item.ref, item.reason])
    for item in preview.invalid:
        writer.writerow(["invalido", item.sheet, item.row, item.internal_id, item.ref, item.reason])
    return buffer.getvalue().encode("utf-8-sig")


DOWNLOADS: Dict[str, Tuple[float, str, bytes, str]] = {}
DOWNLOADS_LOCK = threading.Lock()
IMPORT_PREVIEWS: Dict[str, ImportPreview] = {}
IMPORT_PREVIEWS_LOCK = threading.Lock()


def cleanup_downloads() -> None:
    cutoff = time.time() - DOWNLOAD_TTL_SECONDS
    with DOWNLOADS_LOCK:
        expired = [token for token, (created, _, _, _) in DOWNLOADS.items() if created < cutoff]
        for token in expired:
            DOWNLOADS.pop(token, None)
    import_cutoff = time.time() - IMPORT_TTL_SECONDS
    with IMPORT_PREVIEWS_LOCK:
        expired_imports = [token for token, preview in IMPORT_PREVIEWS.items() if preview.created_at < import_cutoff]
        for token in expired_imports:
            IMPORT_PREVIEWS.pop(token, None)


def store_download(filename: str, data: bytes, content_type: str) -> str:
    token = secrets.token_urlsafe(24)
    with DOWNLOADS_LOCK:
        DOWNLOADS[token] = (time.time(), filename, data, content_type)
    return token


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


def parse_multipart_file(handler: BaseHTTPRequestHandler) -> Tuple[str, bytes]:
    content_length = int(handler.headers.get("Content-Length", "0") or "0")
    if content_length <= 0:
        raise ValueError("No se recibió ningún archivo.")
    if content_length > MAX_FILE_SIZE + 1024 * 1024:
        raise ValueError("El archivo supera el tamaño máximo permitido de 50 MB.")
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("Solicitud inválida.")
    body = handler.rfile.read(content_length)
    message = BytesParser(policy=default).parsebytes(
        b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    filename = None
    file_data = None
    if message.is_multipart():
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            if part.get_param("name", header="content-disposition") == "file":
                filename = part.get_filename()
                file_data = part.get_payload(decode=True)
                break
    if not filename or file_data is None:
        raise ValueError("No se pudo leer el archivo enviado.")
    safe_name = Path(filename).name
    lower = safe_name.lower()
    if not (lower.endswith(".xlsx") or lower.endswith(".csv")):
        raise ValueError("Solo se permiten archivos .xlsx o .csv.")
    if re.search(r"\.(exe|bat|cmd|ps1|js|vbs|msi|scr)$", safe_name, re.IGNORECASE):
        raise ValueError("Tipo de archivo no permitido.")
    return safe_name, file_data


def client_is_local(handler: BaseHTTPRequestHandler) -> bool:
    host = handler.client_address[0] if handler.client_address else ""
    return host in {"127.0.0.1", "::1", "localhost"}


def require_catalog_admin(handler: BaseHTTPRequestHandler) -> Optional[str]:
    """Return error message if admin access is denied, else None."""
    expected = (os.environ.get(ADMIN_TOKEN_ENV) or "").strip()
    provided = (handler.headers.get("X-Admin-Token") or "").strip()
    if expected:
        if not provided or not secrets.compare_digest(provided, expected):
            return "No autorizado. Se requiere token de administración."
        return None
    if not client_is_local(handler):
        return "No autorizado. Configure CATALOG_ADMIN_TOKEN para acceso remoto."
    return None


class AppHandler(BaseHTTPRequestHandler):
    server_version = "ExcelRefConverter/1.4"

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
            self._send_json({
                "status": "ok",
                "catalog_total": catalog_count(),
                "admin_token_required": bool((os.environ.get(ADMIN_TOKEN_ENV) or "").strip()),
            })
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
        if parsed.path == "/api/catalog/suggest":
            query = parse_qs(parsed.query)
            q = query.get("q", [""])[0]
            try:
                limit = int(query.get("limit", [str(CATALOG_SUGGEST_LIMIT_DEFAULT)])[0] or str(CATALOG_SUGGEST_LIMIT_DEFAULT))
            except ValueError:
                self._send_json({"ok": False, "error": "Parámetro limit inválido."}, HTTPStatus.BAD_REQUEST)
                return
            self._send_json(suggest_catalog(q, limit))
            return
        if parsed.path == "/api/purchase/template":
            self._send_json(purchase_template_contract())
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
        cleanup_downloads()
        parsed = urlparse(self.path)

        if parsed.path == "/api/catalog":
            denied = require_catalog_admin(self)
            if denied:
                self._send_json({"ok": False, "error": denied}, HTTPStatus.UNAUTHORIZED)
                return
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
                status = HTTPStatus.CONFLICT if "ya existe" in message else HTTPStatus.BAD_REQUEST
                self._send_json({"ok": False, "error": message, "catalog_total": catalog_count()}, status)
                return
            self._send_json({
                "ok": True,
                "message": message,
                "item": item.to_dict() if item else None,
                "catalog_total": catalog_count(),
            })
            return

        if parsed.path == "/api/catalog/import/preview":
            denied = require_catalog_admin(self)
            if denied:
                self._send_json({"ok": False, "error": denied}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                filename, file_data = parse_multipart_file(self)
                preview = build_import_preview(file_data, filename)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            except Exception as exc:
                print(f"Error en vista previa de importación: {exc}", file=sys.stderr)
                self._send_json(
                    {"ok": False, "error": "No fue posible analizar el archivo de inventario."},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            with IMPORT_PREVIEWS_LOCK:
                IMPORT_PREVIEWS[preview.token] = preview
            errors_token = store_download(
                "catalogo_importacion_errores.csv",
                import_errors_csv(preview),
                "text/csv; charset=utf-8",
            )
            payload = preview.summary_dict()
            payload["ok"] = True
            payload["errorsDownloadUrl"] = f"/api/download?token={errors_token}"
            payload["catalog_total"] = catalog_count()
            self._send_json(payload)
            return

        if parsed.path == "/api/catalog/import/confirm":
            denied = require_catalog_admin(self)
            if denied:
                self._send_json({"ok": False, "error": denied}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                payload = read_json_body(self)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            token = str(payload.get("token") or "").strip()
            with IMPORT_PREVIEWS_LOCK:
                preview = IMPORT_PREVIEWS.get(token)
            if not preview:
                self._send_json(
                    {"ok": False, "error": "La vista previa expiró o es inválida. Genera una nueva."},
                    HTTPStatus.NOT_FOUND,
                )
                return
            try:
                result = apply_import_preview(preview)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.CONFLICT)
                return
            except Exception as exc:
                print(f"Error al confirmar importación: {exc}", file=sys.stderr)
                self._send_json(
                    {"ok": False, "error": "No fue posible aplicar la actualización del catálogo."},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            with IMPORT_PREVIEWS_LOCK:
                IMPORT_PREVIEWS.pop(token, None)
            self._send_json(result)
            return

        if parsed.path == "/api/purchase/export":
            try:
                payload = read_json_body(self)
                rows = payload.get("rows", [])
                data, filename, errors = export_purchase_csv(rows)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            except Exception as exc:
                print(f"Error al exportar compras: {exc}", file=sys.stderr)
                self._send_json(
                    {"ok": False, "error": "No fue posible generar el archivo de compras."},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            if errors:
                self._send_json({"ok": False, "error": "Hay errores de validación.", "errors": errors}, HTTPStatus.BAD_REQUEST)
                return
            token = store_download(filename, data, "text/csv; charset=utf-8")
            self._send_json({
                "ok": True,
                "filename": filename,
                "downloadUrl": f"/api/download?token={token}",
                "rows": len(rows),
                "catalog_total": catalog_count(),
            })
            return

        # Legacy conversion endpoint retained for CLI/tests; not exposed in the main UI.
        if parsed.path == "/api/process":
            try:
                filename, file_data = parse_multipart_file(self)
                result = process_input_bytes(file_data, filename)
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            except Exception as exc:
                print(f"Error no controlado: {exc}", file=sys.stderr)
                self._send_json(
                    {"ok": False, "error": "No fue posible procesar el archivo. Verifica que no esté dañado."},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return

            token = store_download(result.filename, result.data, result.content_type)
            issues_url = None
            if result.summary.issues:
                issues_token = store_download(
                    f"{sanitize_base_name(filename)}_inconsistencias.csv",
                    result.issues_csv,
                    "text/csv; charset=utf-8",
                )
                issues_url = f"/api/download?token={issues_token}"

            self._send_json({
                "ok": True,
                "filename": result.filename,
                "downloadUrl": f"/api/download?token={token}",
                "issuesDownloadUrl": issues_url,
                "contentType": result.content_type,
                "summary": result.summary.to_dict(),
                "catalog_total": catalog_count(),
            })
            return

        self.send_error(HTTPStatus.NOT_FOUND)

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
                "error": "La edición individual está deshabilitada. Usa la importación acumulativa del inventario.",
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
    if (os.environ.get(ADMIN_TOKEN_ENV) or "").strip():
        print("Administración del catálogo protegida con CATALOG_ADMIN_TOKEN.")
    else:
        print("Administración del catálogo limitada a clientes locales (sin token).")
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
