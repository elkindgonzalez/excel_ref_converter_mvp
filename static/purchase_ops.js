/**
 * Pure purchase-grid operations (browser + Node tests).
 * No DOM. No network.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.PurchaseOps = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const ARTICLE_ID = "ID INTERNO ARTICULO";
  const ARTICLE_NAME = "NOMBRE DE ARTICULO";
  const ARTICLE_COL = "__ARTICLE__";
  const DATE_FIELDS = ["FECHA DE AJUSTE"];
  const DATE_FORMAT = "DD/MM/AAAA";
  const DATE_RE = /^(\d{2})\/(\d{2})\/(\d{4})$/;
  const DATE_ERROR =
    "Fecha inválida. Usa DD/MM/AAAA (ej. 30/09/2026) y una fecha existente.";

  const SHORT_LABELS = {
    "ID SUBSIDIARIA": "Subsidiaria",
    iDENTIFICAR: "Identificar",
    "FECHA DE AJUSTE": "Fecha",
    "TIPO DE AJUSTE": "Tipo",
    "UBICACIÓN DE AJUSTE": "Ubicación",
    NOTA: "Nota",
    "ID INTERNO ARTICULO": "ID int.",
    "NOMBRE DE ARTICULO": "Nombre",
    "AJUSTE DE CANTIDAD": "Cantidad",
    ESTADO: "Estado",
    "CENTRO DE COSTOS": "C. costos",
    "SUBCENTRO DE COSTOS": "Subcentro",
    AREA: "Área",
    SOLICITANTE: "Solicitante",
  };

  /** Default column width shares (percent of table). Actions separate. */
  const DEFAULT_WIDTH_SHARES = {
    "ID SUBSIDIARIA": 5,
    iDENTIFICAR: 8,
    "FECHA DE AJUSTE": 8,
    "TIPO DE AJUSTE": 4,
    "UBICACIÓN DE AJUSTE": 5,
    NOTA: 9,
    "ID INTERNO ARTICULO": 11,
    "NOMBRE DE ARTICULO": 15,
    "AJUSTE DE CANTIDAD": 5,
    ESTADO: 6,
    "CENTRO DE COSTOS": 5,
    "SUBCENTRO DE COSTOS": 5,
    AREA: 5,
    SOLICITANTE: 6,
  };

  const MIN_COL_PX = {
    "ID SUBSIDIARIA": 56,
    iDENTIFICAR: 80,
    "FECHA DE AJUSTE": 110,
    "TIPO DE AJUSTE": 48,
    "UBICACIÓN DE AJUSTE": 56,
    NOTA: 80,
    "ID INTERNO ARTICULO": 120,
    "NOMBRE DE ARTICULO": 140,
    "AJUSTE DE CANTIDAD": 56,
    ESTADO: 64,
    "CENTRO DE COSTOS": 56,
    "SUBCENTRO DE COSTOS": 56,
    AREA: 56,
    SOLICITANTE: 72,
  };

  function cloneArticle(article) {
    if (!article) return null;
    return {
      internal_id: String(article.internal_id || ""),
      name: String(article.name || ""),
      ref: String(article.ref || ""),
    };
  }

  function emptyRow(headers, nextId) {
    const data = {};
    for (const header of headers) data[header] = "";
    return { id: nextId, data, selectedArticle: null };
  }

  function cloneRow(row, nextId) {
    const data = {};
    for (const key of Object.keys(row.data || {})) {
      data[key] = row.data[key];
    }
    return {
      id: nextId,
      data,
      selectedArticle: cloneArticle(row.selectedArticle),
    };
  }

  function insertAfter(rows, index, newRow) {
    const next = rows.slice();
    const at = Math.max(0, Math.min(index + 1, next.length));
    next.splice(at, 0, newRow);
    return next;
  }

  function duplicateRow(rows, index, nextId) {
    if (index < 0 || index >= rows.length) {
      throw new Error("Índice de fila inválido para duplicar.");
    }
    const copy = cloneRow(rows[index], nextId);
    return { rows: insertAfter(rows, index, copy), newIndex: index + 1, newRow: copy };
  }

  function applyArticle(row, article) {
    const next = {
      id: row.id,
      data: { ...row.data },
      selectedArticle: cloneArticle(article),
    };
    if (article) {
      next.data[ARTICLE_ID] = String(article.internal_id || "");
      next.data[ARTICLE_NAME] = String(article.name || "");
    } else {
      next.data[ARTICLE_ID] = "";
      next.data[ARTICLE_NAME] = "";
    }
    return next;
  }

  function clearArticle(row) {
    return applyArticle(row, null);
  }

  function copyFieldFromPrevious(rows, rowIndex, field) {
    if (rowIndex <= 0 || rowIndex >= rows.length) {
      return { ok: false, reason: "No hay fila anterior.", rows };
    }
    const prev = rows[rowIndex - 1];
    const current = rows[rowIndex];
    let updated;
    if (field === ARTICLE_COL || field === ARTICLE_ID || field === ARTICLE_NAME) {
      updated = applyArticle(current, prev.selectedArticle);
      if (!prev.selectedArticle) {
        updated.data[ARTICLE_ID] = prev.data[ARTICLE_ID] || "";
        updated.data[ARTICLE_NAME] = prev.data[ARTICLE_NAME] || "";
      }
    } else {
      let value = prev.data[field] || "";
      if (DATE_FIELDS.indexOf(field) !== -1) {
        value = coercePurchaseDateInput(value).value;
      }
      updated = {
        id: current.id,
        data: { ...current.data, [field]: value },
        selectedArticle: cloneArticle(current.selectedArticle),
      };
    }
    const next = rows.slice();
    next[rowIndex] = updated;
    return { ok: true, rows: next };
  }

  function fillDown(rows, field, fromIndex, toIndex) {
    if (fromIndex < 0 || fromIndex >= rows.length) {
      throw new Error("Fila origen inválida.");
    }
    const start = Math.min(fromIndex, toIndex);
    const end = Math.max(fromIndex, toIndex);
    const source = rows[fromIndex];
    let sourceValue = source.data[field] || "";
    if (DATE_FIELDS.indexOf(field) !== -1) {
      sourceValue = coercePurchaseDateInput(sourceValue).value;
    }
    const next = rows.slice();
    for (let i = start; i <= end; i += 1) {
      if (i === fromIndex) continue;
      if (field === ARTICLE_COL || field === ARTICLE_ID || field === ARTICLE_NAME) {
        next[i] = applyArticle(next[i], source.selectedArticle);
        if (!source.selectedArticle) {
          next[i].data[ARTICLE_ID] = source.data[ARTICLE_ID] || "";
          next[i].data[ARTICLE_NAME] = source.data[ARTICLE_NAME] || "";
        }
      } else {
        next[i] = {
          id: next[i].id,
          data: { ...next[i].data, [field]: DATE_FIELDS.indexOf(field) !== -1 ? sourceValue : (source.data[field] || "") },
          selectedArticle: cloneArticle(next[i].selectedArticle),
        };
      }
    }
    return next;
  }

  function fillDownRemaining(rows, field, fromIndex) {
    if (fromIndex >= rows.length - 1) return rows;
    return fillDown(rows, field, fromIndex, rows.length - 1);
  }

  function articleConsistent(row) {
    if (!row.selectedArticle) {
      const id = (row.data[ARTICLE_ID] || "").trim();
      const name = (row.data[ARTICLE_NAME] || "").trim();
      if (!id && !name) return true;
      return false;
    }
    return (
      row.data[ARTICLE_ID] === row.selectedArticle.internal_id
      && row.data[ARTICLE_NAME] === row.selectedArticle.name
    );
  }

  function parseClipboardTSV(text) {
    const normalized = String(text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    if (!normalized.length) return [];
    const lines = normalized.endsWith("\n")
      ? normalized.slice(0, -1).split("\n")
      : normalized.split("\n");
    return lines.map((line) => line.split("\t"));
  }

  /**
   * Orden visual = orden de plantilla (14 columnas, sin columnas auxiliares).
   * Única fuente de verdad compartida con exportación CSV.
   */
  function visibleColumns(headers) {
    return headers.slice();
  }

  function plantillaColumns(headers) {
    return headers.slice();
  }

  function isArticleSearchField(field) {
    return field === ARTICLE_ID || field === ARTICLE_COL;
  }

  function isDateField(field) {
    return DATE_FIELDS.indexOf(field) !== -1;
  }

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function formatPurchaseDate(day, month, year) {
    return `${pad2(day)}/${pad2(month)}/${String(year).padStart(4, "0")}`;
  }

  function dateDigitsOnly(value) {
    return String(value == null ? "" : value).replace(/\D/g, "").slice(0, 8);
  }

  /** Progressive mask: 11102026 → 11/10/2026 (also 11 → 11, 1110 → 11/10). */
  function maskPurchaseDateDigits(digits) {
    const d = dateDigitsOnly(digits);
    if (!d.length) return "";
    if (d.length <= 2) return d;
    if (d.length <= 4) return `${d.slice(0, 2)}/${d.slice(2)}`;
    return `${d.slice(0, 2)}/${d.slice(2, 4)}/${d.slice(4)}`;
  }

  /**
   * Apply DD/MM/AAAA mask and map caret after the same number of digits.
   * cursor = selectionStart in the raw (pre-mask) value; null → end.
   */
  function maskPurchaseDateInput(raw, cursor) {
    const text = String(raw == null ? "" : raw);
    const safeCursor = cursor == null ? text.length : Math.max(0, Math.min(cursor, text.length));
    const digitsBefore = dateDigitsOnly(text.slice(0, safeCursor)).length;
    const digits = dateDigitsOnly(text);
    const masked = maskPurchaseDateDigits(digits);
    let nextCursor = masked.length;
    if (digitsBefore <= 0) {
      nextCursor = 0;
    } else {
      let seen = 0;
      nextCursor = masked.length;
      for (let i = 0; i < masked.length; i += 1) {
        if (/\d/.test(masked[i])) {
          seen += 1;
          if (seen === digitsBefore) {
            nextCursor = i + 1;
            break;
          }
        }
      }
    }
    return { value: masked, cursor: nextCursor, digits };
  }

  function isValidPurchaseDate(value) {
    const text = String(value || "").trim();
    const match = DATE_RE.exec(text);
    if (!match) return false;
    const day = Number(match[1]);
    const month = Number(match[2]);
    const year = Number(match[3]);
    if (year < 1 || month < 1 || month > 12 || day < 1) return false;
    const dt = new Date(year, month - 1, day);
    return (
      dt.getFullYear() === year
      && dt.getMonth() === month - 1
      && dt.getDate() === day
    );
  }

  function purchaseDateToIso(value) {
    if (!isValidPurchaseDate(value)) return "";
    const match = DATE_RE.exec(String(value).trim());
    return `${match[3]}-${match[2]}-${match[1]}`;
  }

  function isoToPurchaseDate(iso) {
    const text = String(iso || "").trim();
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
    if (!match) return "";
    const formatted = formatPurchaseDate(Number(match[3]), Number(match[2]), Number(match[1]));
    return isValidPurchaseDate(formatted) ? formatted : "";
  }

  /**
   * Normaliza entradas a DD/MM/AAAA: máscara de 8 dígitos, barras, ISO, D/M/AAAA.
   * Fechas incompletas quedan enmascaradas (ok=false hasta ser calendario-válidas).
   */
  function coercePurchaseDateInput(raw) {
    const text = String(raw == null ? "" : raw).trim();
    if (!text) return { value: "", ok: true, empty: true };

    if (isValidPurchaseDate(text)) {
      const m = DATE_RE.exec(text);
      return {
        value: formatPurchaseDate(Number(m[1]), Number(m[2]), Number(m[3])),
        ok: true,
        empty: false,
      };
    }

    const fromIso = isoToPurchaseDate(text);
    if (fromIso) return { value: fromIso, ok: true, empty: false };

    const loose = /^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})$/.exec(text);
    if (loose) {
      const formatted = formatPurchaseDate(Number(loose[1]), Number(loose[2]), Number(loose[3]));
      if (isValidPurchaseDate(formatted)) {
        return { value: formatted, ok: true, empty: false };
      }
      return { value: formatted, ok: false, empty: false, message: DATE_ERROR };
    }

    const digits = dateDigitsOnly(text);
    if (digits.length) {
      const masked = maskPurchaseDateDigits(digits);
      if (digits.length === 8 && isValidPurchaseDate(masked)) {
        return { value: masked, ok: true, empty: false };
      }
      if (digits.length === 8) {
        return { value: masked, ok: false, empty: false, message: DATE_ERROR };
      }
      // Escritura parcial enmascarada (ej. 1110 → 11/10): aún no válida.
      return { value: masked, ok: false, empty: false, incomplete: true, message: DATE_ERROR };
    }

    return { value: text, ok: false, empty: false, message: DATE_ERROR };
  }

  function validateDateFields(rows, requiredFields) {
    const required = new Set(requiredFields || []);
    const errors = [];
    rows.forEach((row, index) => {
      for (const field of DATE_FIELDS) {
        const raw = (row.data && row.data[field]) || "";
        if (!raw) {
          if (required.has(field)) {
            errors.push({
              row: index + 1,
              field,
              message: `Campo obligatorio vacío: ${field}`,
            });
          }
          continue;
        }
        if (!isValidPurchaseDate(raw)) {
          errors.push({ row: index + 1, field, message: DATE_ERROR });
        }
      }
    });
    return errors;
  }

  function applyPaste(rows, startRow, startColKey, grid, headers) {
    const cols = visibleColumns(headers);
    const colIndex = cols.indexOf(startColKey);
    if (colIndex < 0) throw new Error("Columna de pegado inválida.");
    let next = rows.slice();
    const errors = [];
    for (let r = 0; r < grid.length; r += 1) {
      const targetIndex = startRow + r;
      while (targetIndex >= next.length) {
        const maxId = next.reduce((m, row) => Math.max(m, row.id), 0);
        next.push(emptyRow(headers, maxId + 1));
      }
      let row = next[targetIndex];
      for (let c = 0; c < grid[r].length; c += 1) {
        const field = cols[colIndex + c];
        if (!field) continue;
        const value = grid[r][c];
        if (isArticleSearchField(field)) {
          // Búsqueda integrada en ID INTERNO: pegado inicia consulta, no fija ID sin selección.
          row = clearArticle(row);
          row = {
            ...row,
            data: { ...row.data },
            _articleQuery: value,
          };
        } else if (field === ARTICLE_NAME) {
          errors.push({
            row: targetIndex + 1,
            field,
            message: "Pegado ignorado en nombre de artículo. Selecciona el artículo desde ID INTERNO ARTICULO.",
          });
        } else if (isDateField(field)) {
          const coerced = coercePurchaseDateInput(value);
          row = {
            id: row.id,
            data: { ...row.data, [field]: coerced.value },
            selectedArticle: cloneArticle(row.selectedArticle),
            _articleQuery: row._articleQuery,
          };
          if (!coerced.empty && !coerced.ok) {
            errors.push({
              row: targetIndex + 1,
              field,
              message: coerced.message || DATE_ERROR,
            });
          }
        } else {
          row = {
            id: row.id,
            data: { ...row.data, [field]: value },
            selectedArticle: cloneArticle(row.selectedArticle),
            _articleQuery: row._articleQuery,
          };
        }
      }
      next[targetIndex] = row;
    }
    return { rows: next, errors };
  }

  function defaultColumnWidthsPx(headers, tableWidthPx, actionsPx) {
    const cols = visibleColumns(headers);
    const usable = Math.max(320, tableWidthPx - actionsPx);
    let shareSum = 0;
    for (const col of cols) shareSum += DEFAULT_WIDTH_SHARES[col] || 5;
    const widths = {};
    let assigned = 0;
    cols.forEach((col, idx) => {
      const share = (DEFAULT_WIDTH_SHARES[col] || 5) / shareSum;
      let px = Math.floor(usable * share);
      px = Math.max(MIN_COL_PX[col] || 48, px);
      if (idx === cols.length - 1) {
        px = Math.max(MIN_COL_PX[col] || 48, usable - assigned);
      }
      widths[col] = px;
      assigned += px;
    });
    // If mins exceeded usable, keep mins (horizontal scroll allowed).
    return widths;
  }

  function resizeColumn(widths, col, deltaPx, minPx) {
    const next = { ...widths };
    const min = minPx || MIN_COL_PX[col] || 48;
    next[col] = Math.max(min, (next[col] || min) + deltaPx);
    return next;
  }

  function autoFitColumn(widths, col, contentWidthPx) {
    const next = { ...widths };
    const min = MIN_COL_PX[col] || 48;
    next[col] = Math.max(min, Math.min(480, Math.ceil(contentWidthPx + 16)));
    return next;
  }

  function shortLabel(header) {
    return SHORT_LABELS[header] || header;
  }

  function rowIdsUnique(rows) {
    const seen = new Set();
    for (const row of rows) {
      if (seen.has(row.id)) return false;
      seen.add(row.id);
    }
    return true;
  }

  function exportOrder(rows, headers) {
    return rows.map((row) => headers.map((h) => row.data[h] || ""));
  }

  /** Max size for opening a purchase CSV in the browser (bytes). */
  const MAX_OPEN_CSV_BYTES = 8 * 1024 * 1024;

  /**
   * RFC-style CSV record parser (delimiter-aware, quoted fields, embedded newlines).
   * Does NOT use String.split(delimiter) on whole lines.
   */
  function parseCsvRecords(text, delimiter) {
    const delim = delimiter == null ? ";" : delimiter;
    let input = String(text == null ? "" : text);
    if (input.charCodeAt(0) === 0xfeff) input = input.slice(1);
    const records = [];
    let row = [];
    let field = "";
    let i = 0;
    let inQuotes = false;
    while (i < input.length) {
      const c = input[i];
      if (inQuotes) {
        if (c === '"') {
          if (input[i + 1] === '"') {
            field += '"';
            i += 2;
            continue;
          }
          inQuotes = false;
          i += 1;
          continue;
        }
        field += c;
        i += 1;
        continue;
      }
      if (c === '"') {
        inQuotes = true;
        i += 1;
        continue;
      }
      if (c === delim) {
        row.push(field);
        field = "";
        i += 1;
        continue;
      }
      if (c === "\r") {
        if (input[i + 1] === "\n") i += 1;
        row.push(field);
        records.push(row);
        row = [];
        field = "";
        i += 1;
        continue;
      }
      if (c === "\n") {
        row.push(field);
        records.push(row);
        row = [];
        field = "";
        i += 1;
        continue;
      }
      field += c;
      i += 1;
    }
    if (inQuotes) {
      return { ok: false, records: [], error: "CSV malformado: comillas sin cerrar." };
    }
    if (field.length > 0 || row.length > 0) {
      row.push(field);
      records.push(row);
    }
    // Drop a single trailing empty record produced by a final newline.
    if (
      records.length
      && records[records.length - 1].length === 1
      && records[records.length - 1][0] === ""
    ) {
      records.pop();
    }
    return { ok: true, records, error: "" };
  }

  function headersCompatible(actual, expected) {
    const errors = [];
    const exp = expected.slice();
    const act = actual.slice();
    if (act.length !== exp.length) {
      errors.push({
        type: "header_count",
        message: `Se esperaban ${exp.length} columnas y el archivo tiene ${act.length}.`,
        expected: exp,
        actual: act,
      });
    }
    const missing = exp.filter((h) => act.indexOf(h) === -1);
    const unexpected = act.filter((h) => exp.indexOf(h) === -1);
    if (missing.length) {
      errors.push({
        type: "header_missing",
        message: `Faltan encabezados: ${missing.join(", ")}`,
        missing,
      });
    }
    if (unexpected.length) {
      errors.push({
        type: "header_unexpected",
        message: `Encabezados no reconocidos: ${unexpected.join(", ")}`,
        unexpected,
      });
    }
    const seen = new Set();
    const duplicates = [];
    for (const h of act) {
      if (seen.has(h)) duplicates.push(h);
      seen.add(h);
    }
    if (duplicates.length) {
      errors.push({
        type: "header_duplicate",
        message: `Encabezados duplicados: ${duplicates.join(", ")}`,
        duplicates,
      });
    }
    const orderMismatch = [];
    const n = Math.min(act.length, exp.length);
    for (let i = 0; i < n; i += 1) {
      if (act[i] !== exp[i]) {
        orderMismatch.push({ index: i + 1, expected: exp[i], actual: act[i] });
      }
    }
    if (orderMismatch.length && !missing.length && !unexpected.length && act.length === exp.length) {
      errors.push({
        type: "header_order",
        message: "El orden de las columnas no coincide con la plantilla.",
        orderMismatch,
      });
    }
    return { ok: errors.length === 0, errors };
  }

  /**
   * Parse a purchase-template CSV text into row objects keyed by header.
   * Preserves cell text as strings (no numeric coercion). Does not touch the catalog.
   */
  function parsePurchaseCsv(text, expectedHeaders, options) {
    const opts = options || {};
    const delimiter = opts.delimiter == null ? ";" : opts.delimiter;
    const maxRows = opts.maxRows == null ? 5000 : opts.maxRows;
    const parsed = parseCsvRecords(text, delimiter);
    if (!parsed.ok) {
      return {
        ok: false,
        headers: [],
        rows: [],
        errors: [{ type: "parse", message: parsed.error }],
        warnings: [],
        row_count: 0,
      };
    }
    if (!parsed.records.length) {
      return {
        ok: false,
        headers: [],
        rows: [],
        errors: [{ type: "empty", message: "El archivo CSV está vacío." }],
        warnings: [],
        row_count: 0,
      };
    }
    const headers = parsed.records[0].map((h) => String(h == null ? "" : h));
    const compat = headersCompatible(headers, expectedHeaders);
    if (!compat.ok) {
      return {
        ok: false,
        headers,
        rows: [],
        errors: compat.errors,
        warnings: [],
        row_count: 0,
      };
    }
    const dataRecords = parsed.records.slice(1);
    if (dataRecords.length > maxRows) {
      return {
        ok: false,
        headers,
        rows: [],
        errors: [{
          type: "too_many_rows",
          message: `El archivo tiene ${dataRecords.length} filas; el máximo es ${maxRows}.`,
        }],
        warnings: [],
        row_count: 0,
      };
    }
    const warnings = [];
    const rows = [];
    for (let r = 0; r < dataRecords.length; r += 1) {
      const record = dataRecords[r];
      if (record.length !== headers.length) {
        warnings.push({
          type: "row_width",
          row: r + 1,
          message: `La fila ${r + 1} tiene ${record.length} campos; se esperaban ${headers.length}.`,
        });
      }
      const data = {};
      for (let c = 0; c < headers.length; c += 1) {
        // Preserve as text; missing cells become empty string.
        data[headers[c]] = record[c] == null ? "" : String(record[c]);
      }
      rows.push(data);
    }
    return {
      ok: true,
      headers,
      rows,
      errors: [],
      warnings,
      row_count: rows.length,
    };
  }

  /** Build editable grid rows from parsed CSV objects. Keeps order; empty fields allowed. */
  function gridRowsFromCsvObjects(objects, headers, startId) {
    let nextId = startId || 1;
    return objects.map((obj) => {
      const row = emptyRow(headers, nextId);
      nextId += 1;
      for (const header of headers) {
        row.data[header] = obj[header] == null ? "" : String(obj[header]);
      }
      return row;
    });
  }

  function editedDownloadFilename(originalName) {
    let base = String(originalName || "compras").trim() || "compras";
    base = base.split(/[/\\]/).pop() || "compras";
    if (/\.csv$/i.test(base)) base = base.slice(0, -4);
    base = base.replace(/[^\w.\-áéíóúÁÉÍÓÚüÜñÑ ]+/g, "_").trim() || "compras";
    if (base.length > 120) base = base.slice(0, 120);
    return `${base}_editado.csv`;
  }

  return {
    ARTICLE_ID,
    ARTICLE_NAME,
    ARTICLE_COL,
    DATE_FIELDS,
    DATE_FORMAT,
    DATE_ERROR,
    SHORT_LABELS,
    DEFAULT_WIDTH_SHARES,
    MIN_COL_PX,
    emptyRow,
    cloneRow,
    insertAfter,
    duplicateRow,
    applyArticle,
    clearArticle,
    copyFieldFromPrevious,
    fillDown,
    fillDownRemaining,
    articleConsistent,
    parseClipboardTSV,
    visibleColumns,
    plantillaColumns,
    isArticleSearchField,
    isDateField,
    isValidPurchaseDate,
    purchaseDateToIso,
    isoToPurchaseDate,
    dateDigitsOnly,
    maskPurchaseDateDigits,
    maskPurchaseDateInput,
    coercePurchaseDateInput,
    validateDateFields,
    formatPurchaseDate,
    applyPaste,
    defaultColumnWidthsPx,
    resizeColumn,
    autoFitColumn,
    shortLabel,
    rowIdsUnique,
    exportOrder,
    cloneArticle,
    MAX_OPEN_CSV_BYTES,
    parseCsvRecords,
    headersCompatible,
    parsePurchaseCsv,
    gridRowsFromCsvObjects,
    editedDownloadFilename,
  };
});
