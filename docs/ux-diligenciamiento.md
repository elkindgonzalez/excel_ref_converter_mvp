# UX de diligenciamiento — copia inteligente y tabla compacta

## Acciones de fila

| Acción | Comportamiento |
|---|---|
| Duplicar (`⧉`) | Copia todos los campos y la selección de artículo; inserta debajo; foco en el primer campo editable. |
| Eliminar (`×`) | Quita la fila sin confirmación. |
| Copiar ↑ | Visible al enfocar/hover de celda (no en la primera fila). Copia solo esa columna desde la fila anterior. Si la columna es de artículo, copia ID + nombre + selección. |
| Rellenar ↓ | Botón de barra o `Ctrl/⌘+D`. Replica el valor de la celda activa hacia el rango seleccionado (`Shift+↑/↓` o clic con Shift) o hacia todas las filas siguientes. |

## Portapapeles

- `Ctrl/⌘+C` / `Ctrl/⌘+V` entre celdas.
- Si hay texto seleccionado dentro del input, se respeta el comportamiento nativo del navegador.
- Pegado TSV (Excel): tabulaciones y saltos de línea.
- No se permite pegar libremente sobre ID/nombre derivados (evita inconsistencias); usar búsqueda de artículo.

## Tabla compacta

- Ancho de página al 100 % del viewport.
- Etiquetas cortas en encabezados; `title` conserva el nombre exacto de la plantilla.
- `table-layout: fixed` + anchos iniciales proporcionales.
- Desplazamiento horizontal solo si la suma de anchos (o mínimos) supera el espacio.

## Redimensionamiento (estilo Excel)

- Arrastrar el borde derecho del encabezado.
- Doble clic en el separador: autoajuste al contenido.
- «Restablecer anchos»: redistribuye según el ancho actual del contenedor.
- Preferencias solo en sesión (sin servidor ni `localStorage`).

## Validación visual (medición local)

Medición vía DevTools (`purchaseScroll.scrollWidth` vs `clientWidth`) tras «Restablecer anchos»:

| Resolución | Resultado |
|---|---|
| 1920×1080 | Sin scroll horizontal (`scrollWidth === clientWidth`). 14 columnas de plantilla + acciones. La búsqueda de artículo vive dentro de `ID INTERNO ARTICULO` (sin columna auxiliar). |
| 1440×900 | Sin scroll horizontal. |
| 1366×768 | Sin scroll horizontal con anchos por defecto; al ensanchar columnas manualmente aparece scroll. |

Limitación: con nombres de artículo largos y anchos personalizados elevados, el scroll horizontal es intencional. En viewports < ~1100px la legibilidad manda sobre “todo visible a la vez”.

## Resolución de artículo (ID INTERNO)

- Escribe Ref o ID en la columna `ID INTERNO ARTICULO`.
- Durante la escritura solo se sugieren coincidencias (debounce); no se convierte un prefijo parcial.
- Enter, Tab o blur con coincidencia exacta y única → muestra el ID interno y completa el nombre.
- Ambigüedad Ref vs ID → lista de opciones; no se elige sola.
- `NOMBRE DE ARTICULO` es de solo lectura y no obligatorio en el formulario.

## Vista previa del CSV

Botón «Vista previa del CSV»: misma normalización que `/api/purchase/export` (sin archivo temporal). 14 columnas en orden de plantilla.

## Qué no cambia

Contrato CSV (14 columnas, `;`, UTF-8-BOM, CRLF, `iDENTIFICAR`), catálogo, importación acumulativa, ausencia de borradores.
