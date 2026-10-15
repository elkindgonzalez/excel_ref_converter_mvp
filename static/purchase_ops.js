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
    [ARTICLE_COL]: 11,
    "ID SUBSIDIARIA": 5,
    iDENTIFICAR: 8,
    "FECHA DE AJUSTE": 6,
    "TIPO DE AJUSTE": 4,
    "UBICACIÓN DE AJUSTE": 5,
    NOTA: 9,
    "AJUSTE DE CANTIDAD": 5,
    ESTADO: 6,
    "CENTRO DE COSTOS": 5,
    "SUBCENTRO DE COSTOS": 5,
    AREA: 5,
    SOLICITANTE: 6,
    "ID INTERNO ARTICULO": 5,
    "NOMBRE DE ARTICULO": 15,
  };

  const MIN_COL_PX = {
    [ARTICLE_COL]: 120,
    "ID SUBSIDIARIA": 56,
    iDENTIFICAR: 80,
    "FECHA DE AJUSTE": 78,
    "TIPO DE AJUSTE": 48,
    "UBICACIÓN DE AJUSTE": 56,
    NOTA: 80,
    "AJUSTE DE CANTIDAD": 56,
    ESTADO: 64,
    "CENTRO DE COSTOS": 56,
    "SUBCENTRO DE COSTOS": 56,
    AREA: 56,
    SOLICITANTE: 72,
    "ID INTERNO ARTICULO": 64,
    "NOMBRE DE ARTICULO": 140,
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

  function visibleColumns(headers) {
    // Artículo (búsqueda) es helper UI; las 14 columnas siguen el orden exacto de la plantilla.
    return [ARTICLE_COL].concat(headers);
  }

  /** Las 14 columnas de plantilla en orden de contrato (sin el helper de búsqueda). */
  function plantillaColumns(headers) {
    return headers.slice();
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
        if (field === ARTICLE_COL) {
          // Paste into article search clears selection unless value matches id/ref pattern later resolved by UI.
          row = clearArticle(row);
          row = {
            ...row,
            data: { ...row.data },
            _articleQuery: value,
          };
        } else if (field === ARTICLE_ID || field === ARTICLE_NAME) {
          // Readonly fields: ignore direct paste to avoid inconsistency; report.
          errors.push({
            row: targetIndex + 1,
            field,
            message: "Pegado ignorado en campo de artículo derivado. Usa la búsqueda de artículo.",
          });
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
    if (header === ARTICLE_COL) return "Artículo";
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
