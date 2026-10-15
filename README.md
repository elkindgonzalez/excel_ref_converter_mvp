# Convertidor de artículos — MVP

Aplicación web local (Python 3.10+, sin dependencias externas) para:

1. **Convertir** archivos de compras Excel/CSV: reemplaza la referencia comercial en `ID INTERNO ARTICULO` por el ID interno del catálogo y completa `NOMBRE DE ARTICULO`.
2. **Actualizar el catálogo maestro** de forma acumulativa desde exportaciones de inventario (`.xlsx` / `.csv`).

## Requisitos

- Windows, macOS o Linux
- Python 3.10 o superior
- Sin librerías de terceros

## Ejecución

### macOS / Linux

```bash
python3 app.py
```

Abrirá `http://127.0.0.1:8765` (usa `--no-browser` para no abrir el navegador).

```bash
python3 app.py --host 127.0.0.1 --port 8765 --no-browser
```

### Windows

Doble clic en `iniciar_windows.bat` o:

```powershell
.\iniciar_windows.ps1
```

### Procesamiento por consola

```bash
python3 app.py --process archivo.xlsx --output resultado.csv
```

## Funcionalidades

### Conversión de archivos

1. Carga un `.xlsx` o `.csv` con columnas `ID INTERNO ARTICULO` y `NOMBRE DE ARTICULO`.
2. Interpreta `ID INTERNO ARTICULO` como **referencia comercial** (`Ref` del catálogo), nunca como ID interno.
3. Busca coincidencia **exacta** en el catálogo.
4. Escribe el `ID interno` y el `Nombre` completo.
5. Conserva el resto de columnas y el orden de filas.
6. Genera CSV (una hoja) o ZIP (varias hojas).
7. Reporta inconsistencias y permite descargarlas en CSV.

Si ninguna referencia elegible se convierte, la operación se reporta como error (no como éxito vacío).

### Catálogo de artículos

- Consulta y búsqueda paginada.
- Alta manual de artículos.
- **Actualizar catálogo de artículos**: importación acumulativa desde inventario.

Columnas esperadas del inventario:

| Columna origen | Uso en catálogo |
|---|---|
| `ID interno` | Identidad del artículo |
| `Nombre` | Descripción completa |
| `Nombre para mostrar` | `Ref` (referencia comercial) |

Si falta la referencia, se intenta extraer del patrón inequívoco `REF-<código>` en el nombre.

## Estructura del catálogo

Archivo: `data/catalogo_articulos.csv`

| Campo | Descripción |
|---|---|
| `ID interno` | Identificador definitivo |
| `Nombre` | Descripción completa |
| `Ref` | Referencia comercial |

Respaldos automáticos en `data/backups/` (máximo 20).

## Reglas de actualización del catálogo

- El Excel **no reemplaza** el catálogo completo.
- ID nuevo → agregar.
- ID existente con datos distintos → actualizar (campos vacíos conservan el valor actual).
- Ausentes del Excel → conservar.
- Referencia ya asignada a otro ID → conflicto; no se modifica.
- Referencias duplicadas contradictorias en el archivo → rechazo.
- Nunca elimina registros en una importación.
- Flujo en dos etapas: **vista previa** → **confirmación**.
- Antes de escribir: respaldo, verificación de huella del catálogo, revalidación y escritura atómica.

## Manejo de errores

- Archivos > 50 MB, ZIP maliciosos o Excel inválidos se rechazan.
- Referencias no encontradas se conservan y se listan en el reporte.
- Fallos al guardar restauran el respaldo cuando es posible.
- Operaciones de administración del catálogo requieren cliente local o el token `CATALOG_ADMIN_TOKEN`.

## Pruebas

```bash
python3 -m unittest tests.test_catalog_and_conversion -v
```

Las pruebas usan catálogos temporales aislados; **no modifican** `data/catalogo_articulos.csv`.

## APIs

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/health` | Estado y total del catálogo |
| `POST` | `/api/process` | Convierte Excel/CSV |
| `GET` | `/api/download?token=` | Descarga resultado o reportes |
| `GET` | `/api/catalog` | Lista/busca catálogo |
| `POST` | `/api/catalog` | Agrega artículo (admin) |
| `POST` | `/api/catalog/import/preview` | Vista previa de importación (admin) |
| `POST` | `/api/catalog/import/confirm` | Confirma importación (admin) |

Cabecera admin: `X-Admin-Token: <token>` cuando `CATALOG_ADMIN_TOKEN` está definido.

## Consideraciones para despliegue

**Etapa actual (MVP local):** ejecutar solo en `127.0.0.1` es suficiente.

**Antes de exposición en red / producción:**

1. Definir `CATALOG_ADMIN_TOKEN` y no exponer mutaciones del catálogo sin él.
2. Mantener el bind en localhost detrás de un reverse proxy con TLS y autenticación, o no publicar el puerto.
3. Persistir `data/` en volumen con backups externos periódicos.
4. No montar el servicio como escritura pública anónima.
5. Revisar límites de tamaño y cuota de disco para respaldos.

Decisión técnica detallada: `docs/decisiones-tecnicas.md`.

## Seguridad del MVP

- El archivo original nunca se sobrescribe.
- La conversión **no modifica** el catálogo maestro.
- Procesamiento 100 % local; no se envían archivos a servicios externos.
