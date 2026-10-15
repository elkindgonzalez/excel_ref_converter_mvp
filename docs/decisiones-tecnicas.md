# Decisiones técnicas

## Arquitectura

Se conserva el servidor HTTP nativo (`ThreadingHTTPServer`) y el parser XLSX con `zipfile` + `xml.etree`.

**Por qué:** el MVP no justifica FastAPI/Flask ni openpyxl en esta etapa.

**Cuándo migrar:** autenticación multi-usuario, colas, Excel `.xls` legacy o despliegue multi-worker.

## Flujo principal: diligenciamiento directo

La UI ya no convierte archivos de compras cargados. El usuario crea el CSV desde un formulario editable.

**Por qué:** el dolor real era rellenar IDs/nombres correctos; cargar un Excel con referencias para “convertir” añadía fricción y errores. El destino espera ID interno real + nombre completo.

La conversión legacy (`process_*` / `POST /api/process`) se mantiene para CLI y pruebas de regresión del catálogo, pero no se expone en la navegación.

## Contrato de plantilla

Los encabezados, el delimitador `;`, UTF-8-BOM y CRLF se tomaron del archivo real `Alexis Compras pruebas.csv`. No se inventaron columnas.

`ID INTERNO ARTICULO` en el CSV de salida es el **ID interno del catálogo**, no la referencia comercial.

## Búsqueda de artículos

`GET /api/catalog/suggest` devuelve como máximo 20–50 coincidencias priorizando exactas y prefijos. El navegador no descarga el catálogo completo.

**Por qué:** con >20.000 artículos, cargar todo en el cliente sería lento y frágil; el filtrado en servidor escala lo suficiente para este MVP.

## Persistencia

- Formulario: solo memoria del navegador (sesión).
- CSV exportado: token en memoria del servidor con TTL; sin escritura permanente de compras.
- Catálogo: CSV en `data/` con respaldos y escritura atómica.

## Identidad e importación del catálogo

Sin cambios conceptuales respecto a la rama de importación: identidad por ID interno, importación acumulativa, conflictos por Ref, token admin / localhost.
