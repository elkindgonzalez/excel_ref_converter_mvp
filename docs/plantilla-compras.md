# Contrato de plantilla de compras

Fuente de verdad inspeccionada: `Alexis Compras pruebas.csv` (Downloads del entorno de desarrollo).

## Formato

| Propiedad | Valor |
|---|---|
| Codificación | UTF-8 con BOM |
| Delimitador | `;` |
| Fin de línea | CRLF (`\r\n`) |
| Columnas | 14 (orden fijo) |

## Encabezados exactos

1. `ID SUBSIDIARIA`
2. `iDENTIFICAR` *(capitalización literal del archivo original)*
3. `FECHA DE AJUSTE`
4. `TIPO DE AJUSTE`
5. `UBICACIÓN DE AJUSTE`
6. `NOTA`
7. `ID INTERNO ARTICULO`
8. `NOMBRE DE ARTICULO`
9. `AJUSTE DE CANTIDAD`
10. `ESTADO`
11. `CENTRO DE COSTOS`
12. `SUBCENTRO DE COSTOS`
13. `AREA`
14. `SOLICITANTE`

## Campos obligatorios (módulo Crear archivo)

- `ID SUBSIDIARIA`
- `iDENTIFICAR`
- `FECHA DE AJUSTE` (`DD/MM/AAAA`, fecha de calendario existente; p. ej. `30/09/2026`. Se exporta igual, sin ISO.)
- `TIPO DE AJUSTE`
- `UBICACIÓN DE AJUSTE`
- `ID INTERNO ARTICULO` (puede escribirse como **Ref** comercial o como ID interno; el sistema resuelve y exporta siempre el ID interno)
- `AJUSTE DE CANTIDAD` (número, puede ser negativo)
- `ESTADO`

Opcionales: `NOTA`, `NOMBRE DE ARTICULO`, `CENTRO DE COSTOS`, `SUBCENTRO DE COSTOS`, `AREA`, `SOLICITANTE`.

`NOMBRE DE ARTICULO` **no** se pide al usuario: se completa automáticamente desde el catálogo al resolver el artículo. Si se envía un nombre distinto al del catálogo, la exportación falla.

## Resolución de artículos

- Coincidencia exacta de Ref → ID interno + nombre.
- Coincidencia exacta de ID interno → mismo resultado.
- Si el código es Ref de un artículo e ID de otro → ambigüedad; el usuario debe elegir.
- Prefijos parciales no se convierten solos (solo sugieren); la resolución ocurre con Enter, Tab o al salir del campo.

## Nota sobre el flujo anterior

En el archivo de prueba original, `ID INTERNO ARTICULO` contenía la **referencia comercial** y `NOMBRE DE ARTICULO` venía vacío. El módulo **Crear archivo** acepta la Ref en el formulario, la convierte al ID interno real y rellena el nombre del catálogo en la exportación.
