const fileInput = document.getElementById('fileInput');
const selectButton = document.getElementById('selectButton');
const processButton = document.getElementById('processButton');
const dropZone = document.getElementById('dropZone');
const fileName = document.getElementById('fileName');
const status = document.getElementById('status');
const resultCard = document.getElementById('resultCard');
const downloadButton = document.getElementById('downloadButton');
const issuesDownloadButton = document.getElementById('issuesDownloadButton');
const issuesSection = document.getElementById('issuesSection');
const issuesBody = document.getElementById('issuesBody');
const catalogTotal = document.getElementById('catalogTotal');
const catalogForm = document.getElementById('catalogForm');
const catalogFormStatus = document.getElementById('catalogFormStatus');
const catalogSearch = document.getElementById('catalogSearch');
const catalogBody = document.getElementById('catalogBody');
const catalogPrev = document.getElementById('catalogPrev');
const catalogNext = document.getElementById('catalogNext');
const catalogPageInfo = document.getElementById('catalogPageInfo');
const catalogListStatus = document.getElementById('catalogListStatus');
const outputFiles = document.getElementById('outputFiles');
const tabConvert = document.getElementById('tabConvert');
const tabCatalog = document.getElementById('tabCatalog');
const panelConvert = document.getElementById('panelConvert');
const panelCatalog = document.getElementById('panelCatalog');
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

let selectedFile = null;
let selectedImportFile = null;
let importToken = null;
let catalogPage = 1;
const catalogPageSize = 25;
let catalogTotalPages = 1;
let searchTimer = null;

function fileTypeLabel(name) {
  const lower = name.toLowerCase();
  if (lower.endsWith('.csv')) return 'CSV';
  if (lower.endsWith('.xlsx')) return 'Excel';
  return 'Desconocido';
}

function adminHeaders(extra = {}) {
  const headers = { ...extra };
  const token = (adminToken.value || '').trim();
  if (token) headers['X-Admin-Token'] = token;
  return headers;
}

function setActiveTab(which) {
  const convert = which === 'convert';
  tabConvert.classList.toggle('active', convert);
  tabCatalog.classList.toggle('active', !convert);
  tabConvert.setAttribute('aria-selected', convert ? 'true' : 'false');
  tabCatalog.setAttribute('aria-selected', convert ? 'false' : 'true');
  panelConvert.classList.toggle('hidden', !convert);
  panelCatalog.classList.toggle('hidden', convert);
  if (!convert) {
    loadCatalog().catch((error) => {
      catalogListStatus.textContent = error.message;
      catalogListStatus.className = 'status error';
    });
  }
}

function setFile(file) {
  if (!file) return;
  const lower = file.name.toLowerCase();
  if (!(lower.endsWith('.xlsx') || lower.endsWith('.csv'))) {
    selectedFile = null;
    fileName.textContent = '';
    processButton.disabled = true;
    status.textContent = 'Selecciona un archivo con extensión .xlsx o .csv.';
    status.className = 'status error';
    return;
  }
  selectedFile = file;
  const sizeMb = (file.size / 1024 / 1024).toFixed(2);
  fileName.textContent = `${file.name} · Tipo: ${fileTypeLabel(file.name)} · ${sizeMb} MB`;
  processButton.disabled = false;
  status.textContent = '';
  resultCard.classList.add('hidden');
}

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
  const sizeMb = (file.size / 1024 / 1024).toFixed(2);
  importFileName.textContent = `${file.name} · ${sizeMb} MB`;
  importPreviewButton.disabled = false;
  importStatus.textContent = '';
}

function updateCatalogTotal(total) {
  if (typeof total === 'number') {
    catalogTotal.textContent = String(total);
  }
}

async function loadCatalog() {
  const query = new URLSearchParams({
    q: catalogSearch.value.trim(),
    page: String(catalogPage),
    page_size: String(catalogPageSize),
  });
  const response = await fetch(`/api/catalog?${query.toString()}`);
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.error || 'No fue posible cargar el catálogo.');
  }

  updateCatalogTotal(data.catalog_total);
  catalogTotalPages = data.total_pages || 1;
  catalogPageInfo.textContent = `Página ${data.page} de ${catalogTotalPages} · ${data.total} resultado(s)`;
  catalogPrev.disabled = data.page <= 1;
  catalogNext.disabled = data.page >= catalogTotalPages;

  catalogBody.innerHTML = '';
  for (const item of data.items) {
    const row = document.createElement('tr');
    for (const value of [item.ref, item.internal_id, item.name]) {
      const cell = document.createElement('td');
      cell.textContent = value;
      row.appendChild(cell);
    }
    catalogBody.appendChild(row);
  }
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

tabConvert.addEventListener('click', () => setActiveTab('convert'));
tabCatalog.addEventListener('click', () => setActiveTab('catalog'));

selectButton.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => setFile(fileInput.files[0]));
bindDropZone(dropZone, fileInput, setFile);

importSelectButton.addEventListener('click', () => importFileInput.click());
importFileInput.addEventListener('change', () => setImportFile(importFileInput.files[0]));
bindDropZone(importDropZone, importFileInput, setImportFile);

processButton.addEventListener('click', async () => {
  if (!selectedFile) return;

  processButton.disabled = true;
  status.textContent = 'Procesando archivo...';
  status.className = 'status';
  resultCard.classList.add('hidden');

  try {
    const formData = new FormData();
    formData.append('file', selectedFile);
    const response = await fetch('/api/process', { method: 'POST', body: formData });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'No fue posible procesar el archivo.');
    }

    const summary = data.summary;
    const received = Number(summary.total_rows || 0)
      || (Number(summary.converted || summary.processed || 0)
        + Number(summary.not_found || 0)
        + Number(summary.blank_ref || 0)
        + Number(summary.errors || 0)
        + Number(summary.skipped_blank || 0));

    document.getElementById('recordsCount').textContent = received;
    document.getElementById('processedCount').textContent = summary.converted ?? summary.processed ?? 0;
    document.getElementById('missingCount').textContent = summary.not_found || 0;
    document.getElementById('blankCount').textContent = summary.blank_ref || 0;
    document.getElementById('errorCount').textContent = summary.errors || 0;
    document.getElementById('conversionPct').textContent = `${summary.conversion_pct ?? 0}%`;
    updateCatalogTotal(data.catalog_total);

    const files = summary.output_files || [];
    outputFiles.textContent = files.length
      ? `Archivos generados: ${files.join(', ')} → ${data.filename}`
      : data.filename;

    issuesBody.innerHTML = '';
    if (summary.issues && summary.issues.length) {
      for (const issue of summary.issues) {
        const row = document.createElement('tr');
        for (const value of [issue.sheet, issue.row, issue.value, issue.reason || '']) {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.appendChild(cell);
        }
        issuesBody.appendChild(row);
      }
      issuesSection.classList.remove('hidden');
    } else {
      issuesSection.classList.add('hidden');
    }

    downloadButton.href = data.downloadUrl;
    downloadButton.setAttribute('download', data.filename);
    downloadButton.textContent = data.filename.toLowerCase().endsWith('.zip')
      ? 'Descargar ZIP'
      : 'Descargar CSV';

    if (data.issuesDownloadUrl) {
      issuesDownloadButton.href = data.issuesDownloadUrl;
      issuesDownloadButton.classList.remove('hidden');
    } else {
      issuesDownloadButton.classList.add('hidden');
    }

    status.textContent = summary.not_found
      ? `Archivo procesado. ${summary.converted ?? summary.processed} convertidos, ${summary.not_found} pendientes.`
      : 'Archivo procesado correctamente.';
    status.className = summary.not_found ? 'status warning' : 'status success';
    resultCard.classList.remove('hidden');
    resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    status.textContent = error.message;
    status.className = 'status error';
  } finally {
    processButton.disabled = false;
  }
});

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
      const row = document.createElement('tr');
      const before = sample.before
        ? `${sample.before.ref || ''} / ${sample.before.name || ''}`
        : '—';
      const after = `${sample.after.ref || ''} / ${sample.after.name || ''}`;
      for (const value of [sample.kind, sample.internal_id, before, after]) {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.appendChild(cell);
      }
      samplesBody.appendChild(row);
    }
    samplesSection.classList.remove('hidden');
  } else {
    samplesSection.classList.add('hidden');
  }

  const conflictsBody = document.getElementById('importConflictsBody');
  conflictsBody.innerHTML = '';
  const conflicts = [...(data.conflicts || []), ...(data.invalid || [])];
  const conflictsSection = document.getElementById('importConflictsSection');
  if (conflicts.length) {
    for (const item of conflicts) {
      const row = document.createElement('tr');
      for (const value of [item.sheet, item.row, item.internal_id, item.ref, item.reason]) {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.appendChild(cell);
      }
      conflictsBody.appendChild(row);
    }
    conflictsSection.classList.remove('hidden');
  } else {
    conflictsSection.classList.add('hidden');
  }

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
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'No fue posible analizar el inventario.');
    }
    importToken = data.token;
    updateCatalogTotal(data.catalog_total);
    renderImportPreview(data);
    importConfirmButton.disabled = !data.apply_ready;
    if (data.errorsDownloadUrl && (data.conflict_count || data.invalid_count)) {
      importErrorsButton.href = data.errorsDownloadUrl;
      importErrorsButton.classList.remove('hidden');
    } else {
      importErrorsButton.classList.add('hidden');
    }
    importStatus.textContent = data.apply_ready
      ? 'Vista previa lista. Revisa los cambios y confirma para aplicarlos.'
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
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'No fue posible confirmar la actualización.');
    }
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
    if (!response.ok || !data.ok) {
      throw new Error(data.error || 'No fue posible agregar el artículo.');
    }
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

catalogSearch.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    catalogPage = 1;
    try {
      await loadCatalog();
    } catch (error) {
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

fetch('/api/health')
  .then((response) => response.json())
  .then((data) => updateCatalogTotal(data.catalog_total || 0))
  .catch(() => updateCatalogTotal(0));
