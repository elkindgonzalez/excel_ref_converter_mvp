# Persistencia del catálogo maestro

## Decisión (MVP)

**Usar archivo CSV en un directorio persistente** (`CATALOG_DATA_DIR`), no una base de datos.

| Opción | Cuándo | Veredicto MVP |
|---|---|---|
| Volumen / carpeta persistente + CSV | Un servidor, pocos operadores, catálogo ~miles de filas | **Sí — recomendado** |
| SQLite / Postgres | Multi-instancia, concurrencia alta, auditoría SQL | No aún; solo si el volumen de archivo deja de bastar |

La importación acumulativa, respaldos y escritura atómica ya cubren el requisito de permanencia sin cambiar el modelo de datos.

## Rutas

| Archivo | Rol |
|---|---|
| `$CATALOG_DATA_DIR/catalogo_articulos.csv` | Catálogo **vivo** (permanente) |
| `$CATALOG_DATA_DIR/catalog_meta.json` | Fecha de última actualización y conteo |
| `$CATALOG_DATA_DIR/backups/` | Respaldos automáticos (máx. 20) |
| `data/catalogo_articulos.seed.csv` (en el repo) | Única fuente de bootstrap si el vivo **no existe** |
| `data/catalogo_articulos.seed.meta.json` (en el repo) | Conteo, fecha de preparación y SHA-256 del seed |
| `data/catalogo_articulos.csv` (legado local) | Se migra una vez al `CATALOG_DATA_DIR` si el destino está vacío |

**Regla de oro:** si el catálogo vivo ya existe, **nunca** se reemplaza con el seed del repositorio (ni en reinicio ni en despliegue).

## Configuración

```bash
export CATALOG_DATA_DIR=/var/lib/excel-ref-converter/catalog
python3 app.py --host 0.0.0.0 --port 8765 --no-browser
```

Sin la variable, el MVP usa `./data/` (adecuado solo en desarrollo local).

## Migrar el catálogo actual a producción

1. En el servidor, crear el directorio persistente (fuera del clone de Git):

   ```bash
   sudo mkdir -p /var/lib/excel-ref-converter/catalog
   sudo chown "$USER" /var/lib/excel-ref-converter/catalog
   ```

2. Copiar el catálogo confirmado (desde tu máquina o backup):

   ```bash
   cp /ruta/al/catalogo_articulos.csv /var/lib/excel-ref-converter/catalog/catalogo_articulos.csv
   ```

3. Definir la variable en el servicio (systemd, Docker, etc.):

   ```bash
   CATALOG_DATA_DIR=/var/lib/excel-ref-converter/catalog
   ```

4. Arrancar la app. Verificar en consola o `GET /api/health`:

   - `catalog_total` > 0
   - `catalog_data_dir_configured`: `true`
   - `catalog_updated_at` presente

5. Probar búsqueda / formulario / conversión: deben ver los mismos artículos sin reimportar.

### Docker (ejemplo)

```yaml
services:
  app:
    image: tu-imagen
    environment:
      - CATALOG_DATA_DIR=/data/catalog
    volumes:
      - catalog_data:/data/catalog
    ports:
      - "8765:8765"

volumes:
  catalog_data:
```

El código se actualiza con la imagen; el volumen conserva el CSV.

## Recuperación ante fallos

1. Listar respaldos en `$CATALOG_DATA_DIR/backups/`.
2. Copiar el respaldo deseado sobre `catalogo_articulos.csv`.
3. Reiniciar la app (o llamar de nuevo a cualquier API de catálogo).

## Qué no hace Git

- `data/catalogo_articulos.csv` y `data/catalog_meta.json` están en `.gitignore`.
- Se versionan `data/catalogo_articulos.seed.csv` (catálogo maestro para instalaciones nuevas) y `data/catalogo_articulos.seed.meta.json` (conteo, fecha, SHA-256).
- Los instaladores (`iniciar_windows.bat`, `iniciar_windows.ps1`, `python app.py`) no usan otra ruta de catálogo: el bootstrap es solo vía seed.
- Un `git pull` **no** debe borrar el volumen de producción (está fuera del repo).

## API de estado

- `GET /api/health` — incluye `catalog_total`, `catalog_updated_at`, `catalog_data_dir_configured`
- `GET /api/catalog/status` — detalle del directorio de datos
- `GET /api/catalog` — lista + mismos campos de estado para la UI
