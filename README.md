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
2. Busca artículos por Ref, ID interno o nombre (sugerencias desde el servidor; no se descarga el catálogo completo).
3. Al seleccionar, se completan `ID INTERNO ARTICULO` (ID real) y `NOMBRE DE ARTICULO`.
4. Completa el resto de campos de la plantilla.
5. Agrega o elimina filas según necesites.
6. Pulsa **Descargar CSV**.

Los datos del formulario viven solo en la sesión del navegador. El CSV generado se entrega con token temporal en memoria; no se guarda de forma permanente en disco.

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

Archivo maestro: `data/catalogo_articulos.csv` (`ID interno`, `Nombre`, `Ref`).

## APIs principales

| Método | Ruta | Uso |
|---|---|---|
| `GET` | `/api/purchase/template` | Contrato de plantilla |
| `GET` | `/api/catalog/suggest?q=` | Autocompletado de artículos |
| `POST` | `/api/purchase/export` | Valida filas y prepara descarga CSV |
| `GET` | `/api/download?token=` | Descarga temporal |
| `GET` | `/api/catalog` | Lista/busca catálogo |
| `POST` | `/api/catalog/import/preview` | Vista previa importación (admin) |
| `POST` | `/api/catalog/import/confirm` | Confirma importación (admin) |

Admin: cabecera `X-Admin-Token` cuando exista `CATALOG_ADMIN_TOKEN`.

El endpoint legacy `POST /api/process` permanece disponible para CLI/pruebas, pero no aparece en la UI.

## Pruebas

```bash
python3 -m unittest discover -s tests -v
```

Las pruebas usan catálogos temporales; no modifican el catálogo real.

## Despliegue

MVP local en `127.0.0.1`. Antes de exponer en red: token admin, TLS/auth en proxy, volumen persistente para `data/`. Ver `docs/decisiones-tecnicas.md`.
