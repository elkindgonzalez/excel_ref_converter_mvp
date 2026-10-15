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
      updated = {
        id: current.id,
        data: { ...current.data, [field]: prev.data[field] || "" },
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
          data: { ...next[i].data, [field]: source.data[field] || "" },
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
   * Normaliza entradas de fecha a DD/MM/AAAA cuando es posible (ISO, D/M/AAAA).
   * Si no se puede normalizar a una fecha existente, devuelve el texto limpio
   * para que la UI muestre el error de validación.
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
  };
});
