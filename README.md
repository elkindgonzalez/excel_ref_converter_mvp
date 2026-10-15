# Compras y catálogo — MVP

Aplicación web local (Python 3.10+, sin dependencias externas) con dos módulos:

1. **Crear archivo** — diligencia compras en una tabla editable, selecciona artículos del catálogo y descarga un CSV compatible con la plantilla de destino.
2. **Catálogo de artículos** — consulta, alta manual e importación acumulativa desde Excel/CSV de inventario.

La **única** carga de archivos en la interfaz es la actualización del catálogo. No se cargan archivos de compras para convertir.

## Requisitos

- Windows, macOS o Linux
- Python 3.10 o superior
- Sin librerías de terceros

## Ejecución

### macOS / Linux

```bash
python3 app.py
```

URL: `http://127.0.0.1:8765`

```bash
python3 app.py --host 127.0.0.1 --port 8765 --no-browser
```

### Windows

Doble clic en `iniciar_windows.bat` o:

```powershell
.\iniciar_windows.ps1
```

## Crear archivo

1. Abre la pestaña **Crear archivo**.
2. Usa **Nuevo archivo** o **Abrir CSV existente** (plantilla de 14 columnas) para recuperar un CSV ya generado y seguir editándolo.
3. En `ID INTERNO ARTICULO` escribe la **Ref** comercial o el ID interno. Con Enter/Tab/blur, una coincidencia exacta se convierte al ID y completa el nombre sola.
4. No hace falta digitar `NOMBRE DE ARTICULO` (se rellena desde el catálogo).
5. Completa el resto de campos (`FECHA DE AJUSTE` en `DD/MM/AAAA`).
6. Usa **duplicar**, **copiar ↑**, **Rellenar ↓** / `Ctrl|⌘+D`, pegado desde Excel y **Vista previa del CSV**.
7. Redimensiona columnas arrastrando el borde del encabezado (doble clic = autoajuste).
8. Pulsa **Descargar CSV** (si abriste un archivo, el nombre propuesto es `…_editado.csv`).

Los datos del formulario y los anchos de columna viven solo en la sesión del navegador. El CSV generado se entrega con token temporal en memoria; no se guarda de forma permanente en disco. Abrir un CSV tampoco persiste el archivo en el servidor ni altera el catálogo.

Detalle UX: `docs/ux-diligenciamiento.md`.

### Plantilla CSV

Contrato tomado de `Alexis Compras pruebas.csv`:

- UTF-8 con BOM
- Delimitador `;`
- CRLF
- 14 columnas en orden fijo (incluye el encabezado literal `iDENTIFICAR`)

Detalle: `docs/plantilla-compras.md`.

## Catálogo de artículos

- Búsqueda paginada.
- Alta manual.
- **Actualizar catálogo**: vista previa → confirmación, acumulativa (nunca reemplazo total), con respaldos y detección de conflictos.

Archivo maestro persistente: `$CATALOG_DATA_DIR/catalogo_articulos.csv` (por defecto `data/` en desarrollo). El seed versionado es `data/catalogo_articulos.seed.csv` (metadatos en `data/catalogo_articulos.seed.meta.json`) y **nunca** sobrescribe un catálogo existente. Es la única fuente de bootstrap en instalaciones nuevas (`python app.py` / scripts Windows).

Migración y volumen en producción: `docs/persistencia-catalogo.md`.

## APIs principales

| Método | Ruta | Uso |
|---|---|---|
| `GET` | `/api/purchase/template` | Contrato de plantilla |
| `GET` | `/api/catalog/suggest?q=` | Autocompletado de artículos |
| `GET` | `/api/catalog/resolve?q=` | Resolución exacta Ref/ID (o ambigüedad) |
| `POST` | `/api/purchase/preview` | Vista previa con la misma normalización que el CSV |
| `POST` | `/api/purchase/export` | Valida filas y prepara descarga CSV |
| `GET` | `/api/download?token=` | Descarga temporal |
| `GET` | `/api/catalog` | Lista/busca catálogo |
| `GET` | `/api/catalog/status` | Estado de persistencia (total, fecha, directorio) |
| `POST` | `/api/catalog/import/preview` | Vista previa importación (admin) |
| `POST` | `/api/catalog/import/confirm` | Confirma importación (admin) |

Admin: cabecera `X-Admin-Token` cuando exista `CATALOG_ADMIN_TOKEN`.

Variables de entorno relevantes:

| Variable | Uso |
|---|---|
| `CATALOG_DATA_DIR` | Directorio persistente del catálogo (fuera del código en producción) |
| `CATALOG_ADMIN_TOKEN` | Token para alta/importación remota |

El endpoint legacy `POST /api/process` permanece disponible para CLI/pruebas, pero no aparece en la UI.

## Pruebas

```bash
python3 -m unittest discover -s tests -v
```

Las pruebas usan catálogos temporales; no modifican el catálogo real. Incluyen reinicio/redeploy simulado del catálogo (`tests/test_catalog_persistence.py`).

## Despliegue

MVP local en `127.0.0.1`. Antes de exponer en red: token admin, TLS/auth en proxy, y **`CATALOG_DATA_DIR` en volumen persistente**. No hace falta base de datos para este MVP. Ver `docs/persistencia-catalogo.md` y `docs/decisiones-tecnicas.md`.
