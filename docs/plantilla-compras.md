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
- `FECHA DE AJUSTE` (`DD/MM/AAAA`)
- `TIPO DE AJUSTE`
- `UBICACIÓN DE AJUSTE`
- `ID INTERNO ARTICULO` (ID real del catálogo, no la referencia comercial)
- `NOMBRE DE ARTICULO` (debe coincidir con el catálogo)
- `AJUSTE DE CANTIDAD` (número, puede ser negativo)
- `ESTADO`

Opcionales: `NOTA`, `CENTRO DE COSTOS`, `SUBCENTRO DE COSTOS`, `AREA`, `SOLICITANTE`.

## Nota sobre el flujo anterior

En el archivo de prueba original, `ID INTERNO ARTICULO` contenía la **referencia comercial** y `NOMBRE DE ARTICULO` venía vacío. El nuevo módulo **Crear archivo** escribe directamente el ID interno real y el nombre del catálogo, que es el formato exigido por el destino.
