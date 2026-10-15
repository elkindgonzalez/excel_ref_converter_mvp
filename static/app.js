const tabCreate = document.getElementById('tabCreate');
const tabCatalog = document.getElementById('tabCatalog');
const panelCreate = document.getElementById('panelCreate');
const panelCatalog = document.getElementById('panelCatalog');
const purchaseHead = document.getElementById('purchaseHead');
const purchaseBody = document.getElementById('purchaseBody');
const addRowButton = document.getElementById('addRowButton');
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
let openSuggestRowId = null;

const ARTICLE_ID = 'ID INTERNO ARTICULO';
const ARTICLE_NAME = 'NOMBRE DE ARTICULO';

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
  }
}

function emptyRow() {
  const data = {};
  for (const header of template.headers) data[header] = '';
  return { id: rowSeq++, data, selectedArticle: null };
}

function isRequired(header) {
  return (template.required_fields || []).includes(header);
}

function renderHead() {
  const tr = document.createElement('tr');
  const action = document.createElement('th');
  action.className = 'col-action';
  action.textContent = '';
  tr.appendChild(action);

  const searchTh = document.createElement('th');
  searchTh.className = 'col-article';
  searchTh.textContent = 'Artículo (búsqueda)';
  tr.appendChild(searchTh);

  for (const header of template.headers) {
    if (header === ARTICLE_ID || header === ARTICLE_NAME) continue;
    const th = document.createElement('th');
    th.textContent = isRequired(header) ? `${header} *` : header;
    tr.appendChild(th);
  }

  const idTh = document.createElement('th');
  idTh.textContent = `${ARTICLE_ID} *`;
  tr.appendChild(idTh);
  const nameTh = document.createElement('th');
  nameTh.className = 'col-name';
  nameTh.textContent = `${ARTICLE_NAME} *`;
  tr.appendChild(nameTh);

  purchaseHead.innerHTML = '';
  purchaseHead.appendChild(tr);
}

function closeAllSuggest() {
  openSuggestRowId = null;
  document.querySelectorAll('.suggest-list').forEach((el) => el.classList.add('hidden'));
}

function renderRows() {
  purchaseBody.innerHTML = '';
  for (const row of rows) {
    purchaseBody.appendChild(buildRowElement(row));
  }
}

function buildRowElement(row) {
  const tr = document.createElement('tr');
  tr.dataset.rowId = String(row.id);

  const actionTd = document.createElement('td');
  actionTd.className = 'col-action';
  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'button secondary compact';
  removeBtn.textContent = 'Eliminar';
  removeBtn.addEventListener('click', () => {
    rows = rows.filter((r) => r.id !== row.id);
    if (!rows.length) rows.push(emptyRow());
    renderRows();
    createStatus.textContent = '';
    createErrors.classList.add('hidden');
  });
  actionTd.appendChild(removeBtn);
  tr.appendChild(actionTd);

  const articleTd = document.createElement('td');
  articleTd.className = 'col-article';
  const wrap = document.createElement('div');
  wrap.className = 'suggest-wrap';
  const input = document.createElement('input');
  input.type = 'search';
  input.className = 'cell-input suggest-input';
  input.placeholder = 'Ref, ID o nombre…';
  input.autocomplete = 'off';
  input.value = row.selectedArticle
    ? `${row.selectedArticle.ref} · ${row.selectedArticle.internal_id}`
    : '';
  const list = document.createElement('div');
  list.className = 'suggest-list hidden';
  list.setAttribute('role', 'listbox');

  input.addEventListener('input', () => {
    row.selectedArticle = null;
    row.data[ARTICLE_ID] = '';
    row.data[ARTICLE_NAME] = '';
    tr.querySelector('[data-field="ID INTERNO ARTICULO"]').value = '';
    tr.querySelector('[data-field="NOMBRE DE ARTICULO"]').value = '';
    scheduleSuggest(row.id, input, list);
  });
  input.addEventListener('focus', () => {
    if (input.value.trim()) scheduleSuggest(row.id, input, list);
  });
  wrap.appendChild(input);
  wrap.appendChild(list);
  articleTd.appendChild(wrap);
  tr.appendChild(articleTd);

  for (const header of template.headers) {
    if (header === ARTICLE_ID || header === ARTICLE_NAME) continue;
    const td = document.createElement('td');
    const cell = document.createElement('input');
    cell.type = 'text';
    cell.className = 'cell-input';
    cell.dataset.field = header;
    cell.value = row.data[header] || '';
    cell.addEventListener('input', () => {
      row.data[header] = cell.value;
    });
    td.appendChild(cell);
    tr.appendChild(td);
  }

  const idTd = document.createElement('td');
  const idInput = document.createElement('input');
  idInput.type = 'text';
  idInput.className = 'cell-input readonly';
  idInput.dataset.field = ARTICLE_ID;
  idInput.value = row.data[ARTICLE_ID] || '';
  idInput.readOnly = true;
  idInput.title = 'Se completa al seleccionar un artículo';
  idTd.appendChild(idInput);
  tr.appendChild(idTd);

  const nameTd = document.createElement('td');
  nameTd.className = 'col-name';
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.className = 'cell-input readonly';
  nameInput.dataset.field = ARTICLE_NAME;
  nameInput.value = row.data[ARTICLE_NAME] || '';
  nameInput.readOnly = true;
  nameInput.title = 'Se completa al seleccionar un artículo';
  nameTd.appendChild(nameInput);
  tr.appendChild(nameTd);

  return tr;
}

function scheduleSuggest(rowId, input, list) {
  const prev = suggestTimers.get(rowId);
  if (prev) clearTimeout(prev);
  suggestTimers.set(rowId, setTimeout(() => runSuggest(rowId, input, list), 180));
}

async function runSuggest(rowId, input, list) {
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
      const empty = document.createElement('div');
      empty.className = 'suggest-empty';
      empty.textContent = 'Sin coincidencias';
      list.appendChild(empty);
      list.classList.remove('hidden');
      openSuggestRowId = rowId;
      return;
    }
    for (const item of data.items) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'suggest-item';
      btn.setAttribute('role', 'option');
      btn.innerHTML = `<strong>${escapeHtml(item.ref)}</strong> · ID ${escapeHtml(item.internal_id)}`
        + `<span>${escapeHtml(item.name)}</span>`;
      btn.addEventListener('click', () => selectArticle(rowId, item, input, list));
      list.appendChild(btn);
    }
    list.classList.remove('hidden');
    openSuggestRowId = rowId;
  } catch (error) {
    list.innerHTML = `<div class="suggest-empty">${escapeHtml(error.message)}</div>`;
    list.classList.remove('hidden');
  }
}

function selectArticle(rowId, item, input, list) {
  const row = rows.find((r) => r.id === rowId);
  if (!row) return;
  row.selectedArticle = item;
  row.data[ARTICLE_ID] = item.internal_id;
  row.data[ARTICLE_NAME] = item.name;
  input.value = `${item.ref} · ${item.internal_id}`;
  list.classList.add('hidden');
  list.innerHTML = '';
  const tr = purchaseBody.querySelector(`tr[data-row-id="${rowId}"]`);
  if (tr) {
    tr.querySelector('[data-field="ID INTERNO ARTICULO"]').value = item.internal_id;
    tr.querySelector('[data-field="NOMBRE DE ARTICULO"]').value = item.name;
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function collectRowsPayload() {
  return rows.map((row) => {
    const payload = {};
    for (const header of template.headers) {
      payload[header] = row.data[header] || '';
    }
    return payload;
  });
}

async function initTemplate() {
  const response = await fetch('/api/purchase/template');
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || 'No se pudo cargar la plantilla.');
  template = data;
  renderHead();
  rows = [emptyRow()];
  renderRows();
}

addRowButton.addEventListener('click', () => {
  rows.push(emptyRow());
  renderRows();
  createStatus.textContent = '';
  createErrors.classList.add('hidden');
});

downloadButton.addEventListener('click', async () => {
  downloadButton.disabled = true;
  createStatus.textContent = 'Validando y generando CSV…';
  createStatus.className = 'status';
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
    // Temporary download link — server token expires; nothing persisted client-side.
    const link = document.createElement('a');
    link.href = data.downloadUrl;
    link.download = data.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    createStatus.textContent = `CSV generado (${data.rows} fila(s)): ${data.filename}`;
    createStatus.className = 'status success';
  } catch (error) {
    createStatus.textContent = error.message;
    createStatus.className = 'status error';
  } finally {
    downloadButton.disabled = false;
  }
});

document.addEventListener('click', (event) => {
  if (!event.target.closest('.suggest-wrap')) closeAllSuggest();
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

initTemplate().catch((error) => {
  createStatus.textContent = error.message;
  createStatus.className = 'status error';
});
