# Convertidor de artículos — MVP

Aplicación web local para transformar referencias de artículos en IDs internos y exportar CSV.

## Qué hace

1. Recibe un `.xlsx` o `.csv`.
2. Busca cada `ID INTERNO ARTICULO` contra el catálogo interno `data/catalogo_articulos.csv` (`Ref`).
3. Reemplaza por `ID interno` y actualiza `NOMBRE DE ARTICULO`.
4. Genera:
   - un `.csv` si hay una sola hoja/archivo;
   - un `.zip` con un CSV por hoja si el Excel tiene varias hojas procesables.

La pestaña `Lista` ya no es obligatoria. Si aparece en un Excel antiguo, se ignora y no modifica el catálogo.

## Requisitos

- Windows, macOS o Linux.
- Python 3.10 o superior.
- Sin librerías de terceros.

## Ejecutar en Windows

Doble clic en `iniciar_windows.bat`

URL local:

`http://127.0.0.1:8765`

## APIs

- `POST /api/process` — procesa Excel/CSV y prepara descarga CSV/ZIP
- `GET /api/download?token=...` — descarga el resultado
- `GET /api/catalog?q=&page=&page_size=` — lista/busca catálogo
- `POST /api/catalog` — agrega artículo
- `PUT /api/catalog/{ref}` — edita ID interno y Nombre

## Seguridad del MVP

- El archivo original nunca se sobrescribe.
- El servidor escucha en `127.0.0.1` por defecto.
- El catálogo persiste en disco local con backups al agregar/editar.
- Los archivos cargados no pueden modificar el catálogo maestro.
- No se envían archivos a servicios externos.
