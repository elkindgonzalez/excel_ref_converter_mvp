const fileInput = document.getElementById('fileInput');
const selectButton = document.getElementById('selectButton');
const processButton = document.getElementById('processButton');
const dropZone = document.getElementById('dropZone');
const fileName = document.getElementById('fileName');
const status = document.getElementById('status');
const resultCard = document.getElementById('resultCard');
const downloadButton = document.getElementById('downloadButton');
const issuesSection = document.getElementById('issuesSection');
const issuesBody = document.getElementById('issuesBody');
const catalogTotal = document.getElementById('catalogTotal');
const toggleCatalogButton = document.getElementById('toggleCatalogButton');
const catalogPanel = document.getElementById('catalogPanel');
const catalogForm = document.getElementById('catalogForm');
const catalogFormStatus = document.getElementById('catalogFormStatus');
const catalogSearch = document.getElementById('catalogSearch');
const catalogBody = document.getElementById('catalogBody');
const catalogPrev = document.getElementById('catalogPrev');
const catalogNext = document.getElementById('catalogNext');
const catalogPageInfo = document.getElementById('catalogPageInfo');
const catalogListStatus = document.getElementById('catalogListStatus');
const outputFiles = document.getElementById('outputFiles');

let selectedFile = null;
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
    row.dataset.ref = item.ref;

    const refCell = document.createElement('td');
    refCell.textContent = item.ref;
    row.appendChild(refCell);

    const idCell = document.createElement('td');
    idCell.textContent = item.internal_id;
    row.appendChild(idCell);

    const nameCell = document.createElement('td');
    nameCell.textContent = item.name;
    row.appendChild(nameCell);
    catalogBody.appendChild(row);
  }
}

selectButton.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => setFile(fileInput.files[0]));

dropZone.addEventListener('dragover', (event) => {
  event.preventDefault();
  dropZone.classList.add('dragging');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragging'));
dropZone.addEventListener('drop', (event) => {
  event.preventDefault();
  dropZone.classList.remove('dragging');
  setFile(event.dataTransfer.files[0]);
});
dropZone.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    fileInput.click();
  }
});

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
    document.getElementById('recordsCount').textContent =
      Number(summary.processed || 0) + Number(summary.not_found || 0) + Number(summary.already_internal || 0);
    document.getElementById('processedCount').textContent = summary.processed;
    document.getElementById('missingCount').textContent = summary.not_found;
    document.getElementById('generatedFile').textContent = data.filename || '—';
    updateCatalogTotal(data.catalog_total);

    const files = summary.output_files || [];
    outputFiles.textContent = files.length
      ? `Archivos generados: ${files.join(', ')} → ${data.filename}`
      : data.filename;

    issuesBody.innerHTML = '';
    if (summary.issues && summary.issues.length) {
      for (const issue of summary.issues) {
        const row = document.createElement('tr');
        for (const value of [issue.sheet, issue.row, issue.value]) {
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

    status.textContent = summary.not_found
      ? `Archivo procesado correctamente. ${summary.not_found} referencia(s) no encontrada(s).`
      : 'Archivo procesado correctamente.';
    status.className = summary.not_found ? 'status warning' : 'status success';
    resultCard.classList.remove('hidden');
    resultCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (!catalogPanel.classList.contains('hidden')) {
      await loadCatalog();
    }
  } catch (error) {
    status.textContent = error.message;
    status.className = 'status error';
  } finally {
    processButton.disabled = false;
  }
});

toggleCatalogButton.addEventListener('click', async () => {
  const opening = catalogPanel.classList.contains('hidden');
  catalogPanel.classList.toggle('hidden');
  toggleCatalogButton.textContent = opening ? 'Ocultar catálogo' : 'Administrar catálogo';
  if (opening) {
    catalogListStatus.textContent = '';
    try {
      await loadCatalog();
    } catch (error) {
      catalogListStatus.textContent = error.message;
      catalogListStatus.className = 'status error';
    }
  }
});

catalogForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  catalogFormStatus.textContent = 'Guardando...';
  catalogFormStatus.className = 'status';
  try {
    const response = await fetch('/api/catalog', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
