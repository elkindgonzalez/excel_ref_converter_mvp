# Decisiones técnicas

## Arquitectura

Se conserva el servidor HTTP nativo (`ThreadingHTTPServer`) y el parser XLSX con `zipfile` + `xml.etree`.

**Por qué:** el MVP no justifica FastAPI/Flask ni openpyxl en esta etapa.

**Cuándo migrar:** autenticación multi-usuario, colas, Excel `.xls` legacy o despliegue multi-worker.

## Flujo principal: diligenciamiento directo

La UI ya no convierte archivos de compras cargados. El usuario crea el CSV desde un formulario editable.

**Por qué:** el dolor real era rellenar IDs/nombres correctos; cargar un Excel con referencias para “convertir” añadía fricción y errores. El destino espera ID interno real + nombre completo.

La conversión legacy (`process_*` / `POST /api/process`) se mantiene para CLI y pruebas de regresión del catálogo, pero no se expone en la navegación.

## Copia inteligente y tabla compacta

La lógica pura de filas vive en `static/purchase_ops.js` (duplicar, copiar↑, rellenar↓, pegado TSV, anchos). Se prueba con Node sin DOM.

**Por qué:** permite validar integridad de artículos y orden de exportación sin dependencias UI, y mantiene el navegador ligero (sin grids de terceros).

Redimensionado de columnas solo en sesión: arrastre / doble clic / restablecer. Sin `localStorage` ni servidor.

## Contrato de plantilla

Los encabezados, el delimitador `;`, UTF-8-BOM y CRLF se tomaron del archivo real `Alexis Compras pruebas.csv`. No se inventaron columnas.

`ID INTERNO ARTICULO` en el CSV de salida es el **ID interno del catálogo**, no la referencia comercial.

## Búsqueda de artículos

`GET /api/catalog/suggest` devuelve como máximo 20–50 coincidencias priorizando exactas y prefijos. El navegador no descarga el catálogo completo.

**Por qué:** con >20.000 artículos, cargar todo en el cliente sería lento y frágil; el filtrado en servidor escala lo suficiente para este MVP.

## Persistencia

- Formulario: solo memoria del navegador (sesión).
- CSV exportado: token en memoria del servidor con TTL; sin escritura permanente de compras.
- Catálogo: CSV + `catalog_meta.json` en `CATALOG_DATA_DIR` (por defecto `data/`), con respaldos y escritura atómica.
- Seed del repo (`catalogo_articulos.seed.csv`) solo inicializa si el vivo no existe; nunca lo reemplaza.
- **Decisión MVP:** volumen/archivo persistente, no BD. Detalle: `docs/persistencia-catalogo.md`.

## Identidad e importación del catálogo

Sin cambios conceptuales respecto a la rama de importación: identidad por ID interno, importación acumulativa, conflictos por Ref, token admin / localhost.
