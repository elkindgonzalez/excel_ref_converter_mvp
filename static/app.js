/* global PurchaseOps */
const Ops = window.PurchaseOps;

const tabCreate = document.getElementById('tabCreate');
const tabCatalog = document.getElementById('tabCatalog');
const panelCreate = document.getElementById('panelCreate');
const panelCatalog = document.getElementById('panelCatalog');
const purchaseHead = document.getElementById('purchaseHead');
const purchaseBody = document.getElementById('purchaseBody');
const purchaseCols = document.getElementById('purchaseCols');
const purchaseTable = document.getElementById('purchaseTable');
const purchaseScroll = document.getElementById('purchaseScroll');
const addRowButton = document.getElementById('addRowButton');
const fillDownButton = document.getElementById('fillDownButton');
const resetWidthsButton = document.getElementById('resetWidthsButton');
const downloadButton = document.getElementById('downloadButton');
const createStatus = document.getElementById('createStatus');
const createErrors = document.getElementById('createErrors');
const createErrorsBody = document.getElementById('createErrorsBody');

const catalogTotal = document.getElementById('catalogTotal');
const catalogForm = document.getElementById('catalogForm');
const catalogFormStatus = document.getElementById('catalogFormStatus');
const catalogSearch = document.getElementById('catalogSearch');
const catalogBody = document.getElementById('catalogBody');
const catalogPrev = document.getElementById('catalogPrev');
const catalogNext = document.getElementById('catalogNext');
const catalogPageInfo = document.getElementById('catalogPageInfo');
const catalogListStatus = document.getElementById('catalogListStatus');
const adminToken = document.getElementById('adminToken');

const importFileInput = document.getElementById('importFileInput');
const importSelectButton = document.getElementById('importSelectButton');
const importDropZone = document.getElementById('importDropZone');
const importFileName = document.getElementById('importFileName');
const importPreviewButton = document.getElementById('importPreviewButton');
const importConfirmButton = document.getElementById('importConfirmButton');
const importErrorsButton = document.getElementById('importErrorsButton');
const importStatus = document.getElementById('importStatus');
const importPreviewCard = document.getElementById('importPreviewCard');

let template = null;
let rows = [];
let rowSeq = 1;
let catalogPage = 1;
const catalogPageSize = 25;
let catalogTotalPages = 1;
let searchTimer = null;
let suggestTimers = new Map();
let importToken = null;
let selectedImportFile = null;

let columnWidths = {};
let visibleCols = [];
let active = { rowIndex: 0, colKey: Ops.ARTICLE_COL };
let selectionEndRow = null;
let clipboardCells = null;
let resizing = null;
let draftByCell = new Map();

const ACTIONS_PX = 78;

function adminHeaders(extra = {}) {
  const headers = { ...extra };
  const token = (adminToken.value || '').trim();
  if (token) headers['X-Admin-Token'] = token;
  return headers;
}

function updateCatalogTotal(total) {
  if (typeof total === 'number') catalogTotal.textContent = String(total);
}

function setActiveTab(which) {
  const create = which === 'create';
  tabCreate.classList.toggle('active', create);
  tabCatalog.classList.toggle('active', !create);
  tabCreate.setAttribute('aria-selected', create ? 'true' : 'false');
  tabCatalog.setAttribute('aria-selected', create ? 'false' : 'true');
  panelCreate.classList.toggle('hidden', !create);
  panelCatalog.classList.toggle('hidden', create);
  if (!create) {
    loadCatalog().catch((error) => {
      catalogListStatus.textContent = error.message;
      catalogListStatus.className = 'status error';
    });
  } else {
    requestAnimationFrame(distributeWidths);
  }
}

function cellKey(rowIndex, colKey) {
  return `${rowIndex}::${colKey}`;
}

function nextRowId() {
  const maxId = rows.reduce((m, r) => Math.max(m, r.id), 0);
  rowSeq = Math.max(rowSeq, maxId + 1);
  return rowSeq++;
}

function makeEmptyRow() {
  return Ops.emptyRow(template.headers, nextRowId());
}

function setStatus(message, kind = '') {
  createStatus.textContent = message || '';
  createStatus.className = kind ? `status ${kind}` : 'status';
}

function distributeWidths() {
  if (!template) return;
  const width = purchaseScroll.clientWidth || window.innerWidth;
  columnWidths = Ops.defaultColumnWidthsPx(template.headers, width, ACTIONS_PX);
  applyColgroup();
}

function applyColgroup() {
  purchaseCols.innerHTML = '';
  const actionCol = document.createElement('col');
  actionCol.style.width = `${ACTIONS_PX}px`;
  purchaseCols.appendChild(actionCol);
  let total = ACTIONS_PX;
  for (const col of visibleCols) {
    const c = document.createElement('col');
    const w = columnWidths[col] || 80;
    c.style.width = `${w}px`;
    c.dataset.col = col;
    purchaseCols.appendChild(c);
    total += w;
  }
  purchaseTable.style.width = `${total}px`;
  purchaseTable.style.minWidth = '100%';
}

function renderHead() {
  visibleCols = Ops.visibleColumns(template.headers);
  const tr = document.createElement('tr');

  const action = document.createElement('th');
  action.className = 'col-action';
  action.innerHTML = '<span class="sr-only">Acciones</span>';
  tr.appendChild(action);

  for (const col of visibleCols) {
    const th = document.createElement('th');
    th.dataset.col = col;
    th.title = col === Ops.ARTICLE_COL ? 'Búsqueda de artículo' : col;
    const label = document.createElement('span');
    label.className = 'th-label';
    const required = col !== Ops.ARTICLE_COL && (template.required_fields || []).includes(col);
    label.textContent = required ? `${Ops.shortLabel(col)} *` : Ops.shortLabel(col);
    th.appendChild(label);
    const handle = document.createElement('span');
    handle.className = 'col-resize';
    handle.title = 'Arrastrar para redimensionar · Doble clic: ajustar';
    handle.addEventListener('mousedown', (event) => startResize(event, col));
    handle.addEventListener('dblclick', (event) => {
      event.preventDefault();
      event.stopPropagation();
      autoFit(col);
    });
    th.appendChild(handle);
    tr.appendChild(th);
  }

  purchaseHead.innerHTML = '';
  purchaseHead.appendChild(tr);
  applyColgroup();
}

function startResize(event, col) {
  event.preventDefault();
  event.stopPropagation();
  resizing = { col, startX: event.clientX, startW: columnWidths[col] || 80 };
  document.body.classList.add('col-resizing');
}

function onResizeMove(event) {
  if (!resizing) return;
  const delta = event.clientX - resizing.startX;
  columnWidths = Ops.resizeColumn(columnWidths, resizing.col, delta, Ops.MIN_COL_PX[resizing.col]);
  resizing.startX = event.clientX;
  resizing.startW = columnWidths[resizing.col];
  applyColgroup();
}

function onResizeEnd() {
  if (!resizing) return;
  resizing = null;
  document.body.classList.remove('col-resizing');
}

function autoFit(col) {
  const cells = purchaseBody.querySelectorAll(`[data-col="${CSS.escape(col)}"]`);
  let max = Ops.MIN_COL_PX[col] || 48;
  const probe = document.createElement('span');
  probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;font:12px/1.3 system-ui,sans-serif;';
  document.body.appendChild(probe);
  const headerLabel = Ops.shortLabel(col);
  probe.textContent = headerLabel;
  max = Math.max(max, probe.offsetWidth);
  cells.forEach((el) => {
    const input = el.querySelector('input');
    probe.textContent = input ? input.value : el.textContent;
    max = Math.max(max, probe.offsetWidth);
  });
  probe.remove();
  columnWidths = Ops.autoFitColumn(columnWidths, col, max);
  applyColgroup();
}

function closeAllSuggest() {
  document.querySelectorAll('.suggest-list').forEach((el) => el.classList.add('hidden'));
}

function renderRows({ focus } = {}) {
  const scrollLeft = purchaseScroll.scrollLeft;
  const scrollTop = purchaseScroll.scrollTop;
  purchaseBody.innerHTML = '';
  rows.forEach((row, index) => {
    purchaseBody.appendChild(buildRowElement(row, index));
  });
  purchaseScroll.scrollLeft = scrollLeft;
  purchaseScroll.scrollTop = scrollTop;
  paintSelection();
  if (focus) {
    focusCell(focus.rowIndex, focus.colKey, { select: focus.select !== false });
  }
}

function buildRowElement(row, index) {
  const tr = document.createElement('tr');
  tr.dataset.rowId = String(row.id);
  tr.dataset.rowIndex = String(index);

  const actionTd = document.createElement('td');
  actionTd.className = 'col-action';
  const actions = document.createElement('div');
  actions.className = 'row-actions';

  const dupBtn = document.createElement('button');
  dupBtn.type = 'button';
  dupBtn.className = 'icon-btn';
  dupBtn.title = 'Duplicar registro';
  dupBtn.setAttribute('aria-label', 'Duplicar registro');
  dupBtn.textContent = '⧉';
  dupBtn.addEventListener('click', (event) => {
    event.stopPropagation();
    duplicateAt(index);
  });

  const delBtn = document.createElement('button');
  delBtn.type = 'button';
  delBtn.className = 'icon-btn danger';
  delBtn.title = 'Eliminar';
  delBtn.setAttribute('aria-label', 'Eliminar fila');
  delBtn.textContent = '×';
  delBtn.addEventListener('click', (event) => {
    event.stopPropagation();
    rows = rows.filter((r) => r.id !== row.id);
    if (!rows.length) rows.push(makeEmptyRow());
    if (active.rowIndex >= rows.length) active.rowIndex = rows.length - 1;
    selectionEndRow = null;
    renderRows();
    setStatus('');
    createErrors.classList.add('hidden');
  });

  actions.appendChild(dupBtn);
  actions.appendChild(delBtn);
  actionTd.appendChild(actions);
  tr.appendChild(actionTd);

  for (const col of visibleCols) {
    tr.appendChild(buildCell(row, index, col));
  }
  return tr;
}

function buildCell(row, index, col) {
  const td = document.createElement('td');
  td.dataset.col = col;
  td.dataset.rowIndex = String(index);
  td.className = 'grid-cell';

  if (col === Ops.ARTICLE_COL) {
    const wrap = document.createElement('div');
    wrap.className = 'suggest-wrap';
    const input = document.createElement('input');
    input.type = 'search';
    input.className = 'cell-input suggest-input';
    input.placeholder = 'Buscar…';
    input.autocomplete = 'off';
    input.dataset.col = col;
    input.dataset.rowIndex = String(index);
    input.value = row.selectedArticle
      ? `${row.selectedArticle.ref}`
      : (row._articleQuery || '');
    const list = document.createElement('div');
    list.className = 'suggest-list hidden';
    wireCellInput(input, row, index, col, {
      onInput: () => {
        rows[index] = Ops.clearArticle(rows[index]);
        rows[index]._articleQuery = input.value;
        const idInput = trField(index, Ops.ARTICLE_ID);
        const nameInput = trField(index, Ops.ARTICLE_NAME);
        if (idInput) idInput.value = '';
        if (nameInput) nameInput.value = '';
        scheduleSuggest(index, input, list);
      },
    });
    wrap.appendChild(input);
    wrap.appendChild(list);
    td.appendChild(wrap);
  } else {
    const readonly = col === Ops.ARTICLE_ID || col === Ops.ARTICLE_NAME;
    const input = document.createElement('input');
    input.type = 'text';
    input.className = readonly ? 'cell-input readonly' : 'cell-input';
    input.readOnly = readonly;
    input.dataset.col = col;
    input.dataset.rowIndex = String(index);
    input.value = row.data[col] || '';
    input.title = col;
    wireCellInput(input, row, index, col, {
      onInput: () => {
        if (readonly) return;
        rows[index] = {
          ...rows[index],
          data: { ...rows[index].data, [col]: input.value },
        };
      },
    });
    td.appendChild(input);
  }

  if (index > 0) {
    const copyPrev = document.createElement('button');
    copyPrev.type = 'button';
    copyPrev.className = 'copy-prev';
    copyPrev.title = 'Copiar desde fila anterior';
    copyPrev.textContent = '↑';
    copyPrev.addEventListener('mousedown', (event) => event.preventDefault());
    copyPrev.addEventListener('click', (event) => {
      event.stopPropagation();
      const result = Ops.copyFieldFromPrevious(rows, index, col);
      if (!result.ok) {
        setStatus(result.reason, 'warning');
        return;
      }
      rows = result.rows;
      renderRows({ focus: { rowIndex: index, colKey: col } });
      setStatus('Valor copiado desde la fila anterior.');
    });
    td.appendChild(copyPrev);
  }

  return td;
}

function trField(rowIndex, col) {
  return purchaseBody.querySelector(
    `tr[data-row-index="${rowIndex}"] input[data-col="${CSS.escape(col)}"]`
  );
}

function wireCellInput(input, _row, index, col, { onInput }) {
  input.addEventListener('focus', () => {
    active = { rowIndex: index, colKey: col };
    if (selectionEndRow == null) selectionEndRow = index;
    draftByCell.set(cellKey(index, col), input.value);
    paintSelection();
  });
  input.addEventListener('click', (event) => {
    if (event.shiftKey) {
      selectionEndRow = index;
      active = { rowIndex: active.rowIndex, colKey: col };
      paintSelection();
    } else {
      active = { rowIndex: index, colKey: col };
      selectionEndRow = index;
      paintSelection();
    }
  });
  input.addEventListener('input', onInput);
  input.addEventListener('keydown', (event) => onCellKeydown(event, index, col, input));
}

function paintSelection() {
  purchaseBody.querySelectorAll('.grid-cell').forEach((td) => td.classList.remove('selected', 'active-cell'));
  const start = Math.min(active.rowIndex, selectionEndRow == null ? active.rowIndex : selectionEndRow);
  const end = Math.max(active.rowIndex, selectionEndRow == null ? active.rowIndex : selectionEndRow);
  for (let i = start; i <= end; i += 1) {
    const td = purchaseBody.querySelector(`tr[data-row-index="${i}"] td[data-col="${CSS.escape(active.colKey)}"]`);
    if (td) td.classList.add('selected');
  }
  const activeTd = purchaseBody.querySelector(
    `tr[data-row-index="${active.rowIndex}"] td[data-col="${CSS.escape(active.colKey)}"]`
  );
  if (activeTd) activeTd.classList.add('active-cell');
}

function focusCell(rowIndex, colKey, { select = true } = {}) {
  const input = trField(rowIndex, colKey);
  if (!input) return;
  active = { rowIndex, colKey };
  if (selectionEndRow == null) selectionEndRow = rowIndex;
  input.focus();
  if (select && !input.readOnly) input.select();
  paintSelection();
}

function duplicateAt(index) {
  const result = Ops.duplicateRow(rows, index, nextRowId());
  rows = result.rows;
  active = { rowIndex: result.newIndex, colKey: visibleCols[0] || Ops.ARTICLE_COL };
  selectionEndRow = result.newIndex;
  renderRows({ focus: { rowIndex: result.newIndex, colKey: firstEditableCol() } });
  setStatus(`Registro duplicado (fila ${result.newIndex + 1}).`);
}

function firstEditableCol() {
  for (const col of visibleCols) {
    if (col !== Ops.ARTICLE_ID && col !== Ops.ARTICLE_NAME) return col;
  }
  return Ops.ARTICLE_COL;
}

function scheduleSuggest(rowIndex, input, list) {
  const prev = suggestTimers.get(rowIndex);
  if (prev) clearTimeout(prev);
  suggestTimers.set(rowIndex, setTimeout(() => runSuggest(rowIndex, input, list), 180));
}

async function runSuggest(rowIndex, input, list) {
  const q = input.value.trim();
  if (q.length < 1) {
    list.classList.add('hidden');
    list.innerHTML = '';
    return;
  }
  try {
    const params = new URLSearchParams({ q, limit: '20' });
    const response = await fetch(`/api/catalog/suggest?${params}`);
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Búsqueda fallida');
    list.innerHTML = '';
    if (!data.items.length) {
      list.innerHTML = '<div class="suggest-empty">Sin coincidencias</div>';
      list.classList.remove('hidden');
      return;
    }
    for (const item of data.items) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'suggest-item';
      btn.innerHTML = `<strong>${escapeHtml(item.ref)}</strong> · ID ${escapeHtml(item.internal_id)}`
        + `<span>${escapeHtml(item.name)}</span>`;
      btn.addEventListener('mousedown', (event) => event.preventDefault());
      btn.addEventListener('click', () => {
        rows[rowIndex] = Ops.applyArticle(rows[rowIndex], item);
        delete rows[rowIndex]._articleQuery;
        list.classList.add('hidden');
        renderRows({ focus: { rowIndex, colKey: 'ID SUBSIDIARIA' } });
      });
      list.appendChild(btn);
    }
    list.classList.remove('hidden');
  } catch (error) {
    list.innerHTML = `<div class="suggest-empty">${escapeHtml(error.message)}</div>`;
    list.classList.remove('hidden');
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function isEditingText(input) {
  if (!input || input.tagName !== 'INPUT') return false;
  if (input.readOnly) return false;
  const start = input.selectionStart;
  const end = input.selectionEnd;
  if (start == null || end == null) return false;
  return start !== end || document.activeElement === input;
}

function onCellKeydown(event, index, col, input) {
  const mod = event.metaKey || event.ctrlKey;

  if (mod && event.key.toLowerCase() === 'd') {
    event.preventDefault();
    doFillDown();
    return;
  }

  if (event.key === 'Escape') {
    const key = cellKey(index, col);
    if (draftByCell.has(key)) {
      input.value = draftByCell.get(key);
      if (col !== Ops.ARTICLE_COL && col !== Ops.ARTICLE_ID && col !== Ops.ARTICLE_NAME) {
        rows[index].data[col] = input.value;
      }
      draftByCell.delete(key);
    }
    input.blur();
    return;
  }

  if (event.key === 'Enter') {
    event.preventDefault();
    const nextRow = Math.min(rows.length - 1, index + 1);
    if (nextRow === index) {
      rows.push(makeEmptyRow());
      renderRows({ focus: { rowIndex: index + 1, colKey: col } });
    } else {
      focusCell(nextRow, col);
    }
    return;
  }

  if (event.key === 'Tab') {
    event.preventDefault();
    const cols = visibleCols.filter((c) => c !== Ops.ARTICLE_ID && c !== Ops.ARTICLE_NAME || c === Ops.ARTICLE_COL);
    // Navigate all visible including readonly for review, but skip readonly on tab for speed
    const editable = visibleCols.filter((c) => c !== Ops.ARTICLE_ID && c !== Ops.ARTICLE_NAME);
    const pos = editable.indexOf(col);
    if (event.shiftKey) {
      if (pos > 0) focusCell(index, editable[pos - 1]);
      else if (index > 0) focusCell(index - 1, editable[editable.length - 1]);
    } else if (pos >= 0 && pos < editable.length - 1) {
      focusCell(index, editable[pos + 1]);
    } else if (index < rows.length - 1) {
      focusCell(index + 1, editable[0]);
    } else {
      rows.push(makeEmptyRow());
      renderRows({ focus: { rowIndex: index + 1, colKey: editable[0] } });
    }
    return;
  }

  if (event.shiftKey && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
    event.preventDefault();
    const delta = event.key === 'ArrowDown' ? 1 : -1;
    const next = Math.max(0, Math.min(rows.length - 1, (selectionEndRow == null ? index : selectionEndRow) + delta));
    selectionEndRow = next;
    paintSelection();
    return;
  }

  if (!mod && (event.key === 'ArrowDown' || event.key === 'ArrowUp') && !isEditingText(input)) {
    // Only navigate if caret at edge / no selection change needed — keep simple: arrow moves rows when not composing text selection intent
    if (input.selectionStart === input.selectionEnd) {
      const atStart = input.selectionStart === 0;
      const atEnd = input.selectionStart === input.value.length;
      if ((event.key === 'ArrowUp' && atStart) || (event.key === 'ArrowDown' && atEnd) || input.readOnly) {
        event.preventDefault();
        const next = Math.max(0, Math.min(rows.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
        active = { rowIndex: next, colKey: col };
        selectionEndRow = next;
        focusCell(next, col, { select: false });
      }
    }
  }
}

function doFillDown() {
  const from = active.rowIndex;
  const to = selectionEndRow == null ? rows.length - 1 : selectionEndRow;
  if (from === to && to === rows.length - 1 && from < rows.length - 1) {
    rows = Ops.fillDownRemaining(rows, active.colKey, from);
  } else if (from === to) {
    rows = Ops.fillDownRemaining(rows, active.colKey, from);
  } else {
    rows = Ops.fillDown(rows, active.colKey, from, to);
  }
  renderRows({ focus: { rowIndex: from, colKey: active.colKey } });
  setStatus('Valores rellenados hacia abajo.');
}

function selectionHasText(input) {
  return input && typeof input.selectionStart === 'number' && input.selectionStart !== input.selectionEnd;
}

function onCopy(event) {
  const input = document.activeElement;
  if (input && input.classList.contains('cell-input') && selectionHasText(input)) {
    return; // native text copy
  }
  if (!template || !rows.length) return;
  const start = Math.min(active.rowIndex, selectionEndRow == null ? active.rowIndex : selectionEndRow);
  const end = Math.max(active.rowIndex, selectionEndRow == null ? active.rowIndex : selectionEndRow);
  const lines = [];
  for (let i = start; i <= end; i += 1) {
    const row = rows[i];
    let value = '';
    if (active.colKey === Ops.ARTICLE_COL) {
      value = row.selectedArticle ? row.selectedArticle.ref : (row._articleQuery || '');
    } else {
      value = row.data[active.colKey] || '';
    }
    lines.push(value);
  }
  const text = lines.join('\n');
  clipboardCells = {
    colKey: active.colKey,
    values: lines,
    articles: rows.slice(start, end + 1).map((r) => Ops.cloneArticle(r.selectedArticle)),
  };
  event.clipboardData.setData('text/plain', text);
  event.preventDefault();
  setStatus(`Copiado (${lines.length}).`);
}

function onPaste(event) {
  const input = document.activeElement;
  if (input && input.classList.contains('cell-input') && !input.readOnly && selectionHasText(input)) {
    // Let browser replace selected text; sync on input event.
    return;
  }
  if (input && input.classList.contains('cell-input') && !input.readOnly && input === document.activeElement) {
    // If caret editing single cell without multi-line paste intent, allow native unless TSV/multi-line
    const text = event.clipboardData.getData('text/plain');
    if (!text.includes('\t') && !text.includes('\n') && !text.includes('\r')) {
      return;
    }
  }

  event.preventDefault();
  const text = event.clipboardData.getData('text/plain');
  const grid = Ops.parseClipboardTSV(text);
  if (!grid.length) return;

  // Single-column clipboard from our copy with article integrity
  if (clipboardCells && clipboardCells.colKey === active.colKey && grid.length >= 1 && grid[0].length === 1) {
    const start = active.rowIndex;
    let next = rows.slice();
    for (let i = 0; i < clipboardCells.values.length; i += 1) {
      const target = start + i;
      while (target >= next.length) next.push(makeEmptyRow());
      if (active.colKey === Ops.ARTICLE_COL || active.colKey === Ops.ARTICLE_ID || active.colKey === Ops.ARTICLE_NAME) {
        next[target] = Ops.applyArticle(next[target], clipboardCells.articles[i]);
      } else {
        next[target] = {
          ...next[target],
          data: { ...next[target].data, [active.colKey]: clipboardCells.values[i] },
        };
      }
    }
    rows = next;
    renderRows({ focus: { rowIndex: active.rowIndex, colKey: active.colKey } });
    setStatus('Pegado aplicado.');
    return;
  }

  const result = Ops.applyPaste(rows, active.rowIndex, active.colKey, grid, template.headers);
  rows = result.rows;
  // Ensure ids unique / seq
  rowSeq = rows.reduce((m, r) => Math.max(m, r.id), 0) + 1;
  renderRows({ focus: { rowIndex: active.rowIndex, colKey: active.colKey } });
  if (result.errors.length) {
    createErrorsBody.innerHTML = '';
    for (const err of result.errors) {
      const tr = document.createElement('tr');
      for (const value of [err.row, err.field, err.message]) {
        const td = document.createElement('td');
        td.textContent = value;
        tr.appendChild(td);
      }
      createErrorsBody.appendChild(tr);
    }
    createErrors.classList.remove('hidden');
    setStatus('Pegado parcial con advertencias.', 'warning');
  } else {
    createErrors.classList.add('hidden');
    setStatus('Pegado aplicado.');
  }
}

function collectRowsPayload() {
  return rows.map((row) => {
    const payload = {};
    for (const header of template.headers) payload[header] = row.data[header] || '';
    return payload;
  });
}

async function initTemplate() {
  const response = await fetch('/api/purchase/template');
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || 'No se pudo cargar la plantilla.');
  template = data;
  rows = [makeEmptyRow()];
  renderHead();
  distributeWidths();
  renderRows({ focus: { rowIndex: 0, colKey: Ops.ARTICLE_COL, select: false } });
}

addRowButton.addEventListener('click', () => {
  rows.push(makeEmptyRow());
  active = { rowIndex: rows.length - 1, colKey: firstEditableCol() };
  selectionEndRow = active.rowIndex;
  renderRows({ focus: { rowIndex: active.rowIndex, colKey: active.colKey } });
});

fillDownButton.addEventListener('click', () => doFillDown());
resetWidthsButton.addEventListener('click', () => {
  distributeWidths();
  setStatus('Anchos restablecidos.');
});

downloadButton.addEventListener('click', async () => {
  for (const row of rows) {
    if (!Ops.articleConsistent(row) && ((row.data[Ops.ARTICLE_ID] || row.data[Ops.ARTICLE_NAME]))) {
      setStatus('Hay artículos inconsistentes. Selecciona el artículo desde la búsqueda.', 'error');
      return;
    }
  }
  downloadButton.disabled = true;
  setStatus('Validando y generando CSV…');
  createErrors.classList.add('hidden');
  try {
    const response = await fetch('/api/purchase/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows: collectRowsPayload() }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      if (data.errors && data.errors.length) {
        createErrorsBody.innerHTML = '';
        for (const err of data.errors) {
          const tr = document.createElement('tr');
          for (const value of [err.row, err.field || '', err.message]) {
            const td = document.createElement('td');
            td.textContent = value;
            tr.appendChild(td);
          }
          createErrorsBody.appendChild(tr);
        }
        createErrors.classList.remove('hidden');
      }
      throw new Error(data.error || 'No fue posible generar el archivo.');
    }
    const link = document.createElement('a');
    link.href = data.downloadUrl;
    link.download = data.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setStatus(`CSV generado (${data.rows} fila(s)): ${data.filename}`, 'success');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    downloadButton.disabled = false;
  }
});

document.addEventListener('click', (event) => {
  if (!event.target.closest('.suggest-wrap')) closeAllSuggest();
});
document.addEventListener('mousemove', onResizeMove);
document.addEventListener('mouseup', onResizeEnd);
document.addEventListener('copy', onCopy);
document.addEventListener('paste', onPaste);
window.addEventListener('resize', () => {
  // Keep custom widths; only grow table min width context
  applyColgroup();
});

tabCreate.addEventListener('click', () => setActiveTab('create'));
tabCatalog.addEventListener('click', () => setActiveTab('catalog'));

async function loadCatalog() {
  const query = new URLSearchParams({
    q: catalogSearch.value.trim(),
    page: String(catalogPage),
    page_size: String(catalogPageSize),
  });
  const response = await fetch(`/api/catalog?${query}`);
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || 'No fue posible cargar el catálogo.');
  updateCatalogTotal(data.catalog_total);
  catalogTotalPages = data.total_pages || 1;
  catalogPageInfo.textContent = `Página ${data.page} de ${catalogTotalPages} · ${data.total} resultado(s)`;
  catalogPrev.disabled = data.page <= 1;
  catalogNext.disabled = data.page >= catalogTotalPages;
  catalogBody.innerHTML = '';
  for (const item of data.items) {
    const tr = document.createElement('tr');
    for (const value of [item.ref, item.internal_id, item.name]) {
      const td = document.createElement('td');
      td.textContent = value;
      tr.appendChild(td);
    }
    catalogBody.appendChild(tr);
  }
}

catalogSearch.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    catalogPage = 1;
    try { await loadCatalog(); }
    catch (error) {
      catalogListStatus.textContent = error.message;
      catalogListStatus.className = 'status error';
    }
  }, 250);
});

catalogPrev.addEventListener('click', async () => {
  if (catalogPage <= 1) return;
  catalogPage -= 1;
  await loadCatalog();
});

catalogNext.addEventListener('click', async () => {
  if (catalogPage >= catalogTotalPages) return;
  catalogPage += 1;
  await loadCatalog();
});

catalogForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  catalogFormStatus.textContent = 'Guardando...';
  catalogFormStatus.className = 'status';
  try {
    const response = await fetch('/api/catalog', {
      method: 'POST',
      headers: adminHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        internal_id: document.getElementById('newInternalId').value,
        ref: document.getElementById('newRef').value,
        name: document.getElementById('newName').value,
      }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'No fue posible agregar el artículo.');
    updateCatalogTotal(data.catalog_total);
    catalogForm.reset();
    catalogFormStatus.textContent = data.message || 'Artículo agregado.';
    catalogFormStatus.className = 'status success';
    catalogPage = 1;
    await loadCatalog();
  } catch (error) {
    catalogFormStatus.textContent = error.message;
    catalogFormStatus.className = 'status error';
  }
});

function setImportFile(file) {
  if (!file) return;
  const lower = file.name.toLowerCase();
  if (!(lower.endsWith('.xlsx') || lower.endsWith('.csv'))) {
    selectedImportFile = null;
    importFileName.textContent = '';
    importPreviewButton.disabled = true;
    importConfirmButton.disabled = true;
    importStatus.textContent = 'Selecciona un archivo .xlsx o .csv.';
    importStatus.className = 'status error';
    return;
  }
  selectedImportFile = file;
  importToken = null;
  importConfirmButton.disabled = true;
  importPreviewCard.classList.add('hidden');
  importErrorsButton.classList.add('hidden');
  importFileName.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
  importPreviewButton.disabled = false;
  importStatus.textContent = '';
}

function bindDropZone(zone, input, onFile) {
  zone.addEventListener('dragover', (event) => {
    event.preventDefault();
    zone.classList.add('dragging');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragging'));
  zone.addEventListener('drop', (event) => {
    event.preventDefault();
    zone.classList.remove('dragging');
    onFile(event.dataTransfer.files[0]);
  });
  zone.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      input.click();
    }
  });
}

importSelectButton.addEventListener('click', () => importFileInput.click());
importFileInput.addEventListener('change', () => setImportFile(importFileInput.files[0]));
bindDropZone(importDropZone, importFileInput, setImportFile);

function renderImportPreview(data) {
  document.getElementById('importAnalyzed').textContent = data.analyzed_rows || 0;
  document.getElementById('importNew').textContent = data.new_count || 0;
  document.getElementById('importUpdate').textContent = data.update_count || 0;
  document.getElementById('importUnchanged').textContent = data.unchanged_count || 0;
  document.getElementById('importConflicts').textContent = data.conflict_count || 0;
  document.getElementById('importInvalid').textContent = data.invalid_count || 0;

  const samplesBody = document.getElementById('importSamplesBody');
  samplesBody.innerHTML = '';
  const samples = data.samples || [];
  const samplesSection = document.getElementById('importSamplesSection');
  if (samples.length) {
    for (const sample of samples) {
      const tr = document.createElement('tr');
      const before = sample.before ? `${sample.before.ref || ''} / ${sample.before.name || ''}` : '—';
      const after = `${sample.after.ref || ''} / ${sample.after.name || ''}`;
      for (const value of [sample.kind, sample.internal_id, before, after]) {
        const td = document.createElement('td');
        td.textContent = value;
        tr.appendChild(td);
      }
      samplesBody.appendChild(tr);
    }
    samplesSection.classList.remove('hidden');
  } else samplesSection.classList.add('hidden');

  const conflictsBody = document.getElementById('importConflictsBody');
  conflictsBody.innerHTML = '';
  const conflicts = [...(data.conflicts || []), ...(data.invalid || [])];
  const conflictsSection = document.getElementById('importConflictsSection');
  if (conflicts.length) {
    for (const item of conflicts) {
      const tr = document.createElement('tr');
      for (const value of [item.sheet, item.row, item.internal_id, item.ref, item.reason]) {
        const td = document.createElement('td');
        td.textContent = value;
        tr.appendChild(td);
      }
      conflictsBody.appendChild(tr);
    }
    conflictsSection.classList.remove('hidden');
  } else conflictsSection.classList.add('hidden');

  importPreviewCard.classList.remove('hidden');
}

importPreviewButton.addEventListener('click', async () => {
  if (!selectedImportFile) return;
  importPreviewButton.disabled = true;
  importConfirmButton.disabled = true;
  importStatus.textContent = 'Analizando inventario...';
  importStatus.className = 'status';
  try {
    const formData = new FormData();
    formData.append('file', selectedImportFile);
    const response = await fetch('/api/catalog/import/preview', {
      method: 'POST',
      headers: adminHeaders(),
      body: formData,
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'No fue posible analizar el inventario.');
    importToken = data.token;
    updateCatalogTotal(data.catalog_total);
    renderImportPreview(data);
    importConfirmButton.disabled = !data.apply_ready;
    if (data.errorsDownloadUrl && (data.conflict_count || data.invalid_count)) {
      importErrorsButton.href = data.errorsDownloadUrl;
      importErrorsButton.classList.remove('hidden');
    } else importErrorsButton.classList.add('hidden');
    importStatus.textContent = data.apply_ready
      ? 'Vista previa lista. Confirma para aplicar.'
      : 'Vista previa lista. No hay cambios aplicables.';
    importStatus.className = data.apply_ready ? 'status success' : 'status warning';
  } catch (error) {
    importStatus.textContent = error.message;
    importStatus.className = 'status error';
  } finally {
    importPreviewButton.disabled = false;
  }
});

importConfirmButton.addEventListener('click', async () => {
  if (!importToken) return;
  importConfirmButton.disabled = true;
  importStatus.textContent = 'Aplicando actualización...';
  importStatus.className = 'status';
  try {
    const response = await fetch('/api/catalog/import/confirm', {
      method: 'POST',
      headers: adminHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ token: importToken }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'No fue posible confirmar.');
    updateCatalogTotal(data.catalog_total);
    importToken = null;
    importStatus.textContent =
      `${data.message} Nuevos: ${data.applied_new}. Actualizados: ${data.applied_update}.`
      + (data.backup ? ` Respaldo: ${data.backup}.` : '');
    importStatus.className = 'status success';
    await loadCatalog();
  } catch (error) {
    importStatus.textContent = error.message;
    importStatus.className = 'status error';
    importConfirmButton.disabled = false;
  }
});

fetch('/api/health')
  .then((r) => r.json())
  .then((data) => updateCatalogTotal(data.catalog_total || 0))
  .catch(() => updateCatalogTotal(0));

initTemplate().catch((error) => setStatus(error.message, 'error'));
