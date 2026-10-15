# Decisiones técnicas

## Arquitectura

Se conserva el servidor HTTP nativo de la biblioteca estándar (`ThreadingHTTPServer`) y el parser XLSX basado en `zipfile` + `xml.etree`.

**Por qué:** el MVP no justifica aún FastAPI/Flask ni openpyxl. Añadir dependencias aumentaría fricción de instalación en Windows de usuarios finales sin aportar capacidad crítica en esta etapa.

**Cuándo migrar:** si aparecen autenticación multi-usuario, colas de proceso, despliegue containerizado con varios workers o Excel legacy `.xls`.

## Identidad del catálogo

La identidad del artículo es el **ID interno**. El índice por `Ref` se usa solo para conversión.

**Por qué:** el inventario puede corregir la referencia comercial de un mismo artículo; la clave estable es el ID interno.

## Conversión Ref → ID

`ID INTERNO ARTICULO` en archivos de compras contiene la referencia comercial. La coincidencia es exacta sobre `Ref`. No hay fuzzy matching.

**Por qué:** una coincidencia aproximada puede asignar el artículo incorrecto en inventario/facturación.

Si todas las filas elegibles fallan, la operación se considera error. Un “éxito” sin conversiones ocultaría un catálogo desactualizado.

## Importación acumulativa en dos fases

Vista previa + confirmación con huella SHA-256 del catálogo, lock en memoria, respaldo y escritura atómica (`os.replace`).

**Por qué:** evita actualizaciones parciales y condiciones de carrera entre operadores concurrentes en el mismo proceso.

## Autorización administrativa

- Sin `CATALOG_ADMIN_TOKEN`: mutaciones solo desde clientes locales.
- Con token: se exige cabecera `X-Admin-Token`.

**Por qué (deber ser):** cualquier endpoint que muta el maestro de artículos debe autenticarse antes de exposición pública. En MVP local el bind a `127.0.0.1` mitiga el riesgo; en despliegue el token (o un proxy con auth) es obligatorio.

## Normalización de referencias

Se preservan ceros a la izquierda y texto alfanumérico. La notación científica solo se convierte cuando el entero resultante es exacto y acotado.

**Por qué:** Excel suele serializar números largos o con ceros de forma destructiva; el convertidor no debe empeorar la pérdida de información.
