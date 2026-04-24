# DATERRA 2.0 — Contexto completo para Claude

## ¿Qué es este proyecto?
Entorno de desarrollo y pruebas independiente de DATERRA (producción).
Cualquier cambio aquí NO afecta la app original en producción.

## Repositorios y URLs

| Entorno | GitHub | Cloudflare | URL |
|---|---|---|---|
| **Producción** | `ivvisaac/microdataMX` | `daterra-coeza` | `daterra-coeza.pages.dev` |
| **DATERRA 2.0** | `ivvisaac/DATERRA-2.0` | `daterra-v2` | `daterra-v2.isar1596.workers.dev` |

**Deploy automático:** push a `main` → Cloudflare Pages despliega en ~1 min (integración directa GitHub ↔ Cloudflare, sin GitHub Actions ni tokens).

## Estructura de archivos

```
DATERRA-2.0/
├── deploy/               ← TODO lo que se publica en Cloudflare
│   ├── index.html        ← APP COMPLETA (único archivo ~5,400 líneas)
│   ├── productos.html    ← Visor de productos inmobiliarios por AGEB
│   ├── favicon.png
│   ├── wrangler.toml
│   └── data/
│       ├── 01_aguascalientes.json … 32_zacatecas.json  ← GeoJSON por estado
│       ├── bboxes.json             ← Bounding boxes de municipios
│       ├── indice.json             ← Índice de estados
│       ├── zm_monterrey_productos.geojson   ← Scoring productos ZM MTY
│       └── zm_torreon_productos.geojson     ← Scoring productos ZM TRN
├── scripts/
│   └── score_productos.py   ← Script Python que genera los GeoJSON de productos
├── .github/workflows/
│   └── disabled/            ← Workflow de GH Actions desactivado (no se usa)
├── .gitignore
└── CLAUDE.md               ← Este archivo
```

## La app (deploy/index.html)

**Single-file app** — toda la lógica en un solo HTML+CSS+JS.
- ~5,400 líneas
- No hay framework, no hay build step, no hay dependencias npm
- Las librerías se cargan por CDN (Leaflet, html2canvas, jsPDF, IBM Plex Mono)

### Stack técnico
- **Leaflet.js** — mapa interactivo con polígonos GeoJSON por AGEB
- **html2canvas + jsPDF** — generación de reportes PDF de 13 páginas
- **CartoCDN** — tiles de mapa (dark matter / voyager)
- **INEGI Census 2020** — datos demográficos por AGEB

### Datos disponibles por AGEB (67 variables)
```
Identidad:    CVEGEO, estado, municipio, ageb, cve_ent, cve_mun
Población:    pob_total, pob_2010, pob_fem, pob_mas
Edad:         pob_0_14, pob_15_24, pob_25_59, pob_60mas
              pct_0_14, pct_15_24, pct_25_59, pct_60mas
Vivienda:     hog_total, viv_habitadas, viv_deshabitadas
              vph_1dor, vph_2mas_dor, vph_3mas_cuartos
Economía:     pea, pe_inac, desocupados, pct_pea
Educación:    escolaridad
Crecimiento:  crec_abs_pob, crec_pct_pob, crec_abs_hog, crec_pct_hog
              crec_abs_viv, pob_2030
NSE (AMAI):   nse_ab, nse_cmas, nse_c, nse_cmenos, nse_dmas, nse_d, nse_e
              nse_predominante, nse_viviendas
```

**IMPORTANTE:** `nse_predominante` usa `"A/B"` (con diagonal), NO `"AB"`.

### Variables NSE en el código
```javascript
var NSE_COLORS = {'A/B':'#6d28d9','C+':'#1d4ed8','C':'#0891b2',
                  'C-':'#16a34a','D+':'#ca8a04','D':'#ea580c','E':'#dc2626'};
var NSE_ORDER  = ['A/B','C+','C','C-','D+','D','E'];
var NSE_LABELS = {'A/B':'A/B – Alto', 'C+':'C+ – Medio-Alto', ...};
```

### Funciones clave del index.html

| Función | Descripción |
|---|---|
| `cargarEstado(cve)` | Carga GeoJSON del estado, procesa features, dibuja mapa |
| `dibujar()` | Renderiza polígonos en Leaflet según variable activa (`varAct`) |
| `actualizarLeyenda()` | Actualiza barra de colores (gradiente normal o categórico NSE) |
| `generarReporte()` | Inicia pipeline PDF: lanza mapas async → espera → clona DOM |
| `buildHTML(...)` | Construye HTML de 13 páginas del reporte |
| `imprimirReporte()` | html2canvas → jsPDF → descarga/abre PDF |
| `generarHeatmapRpt(...)` | Renderiza mapa de calor en canvas offscreen para PDF |
| `generarHeatmapNseRpt(...)` | Mapa de calor NSE (colores categóricos) para PDF |
| `cargarTilesRpt(...)` | Carga tiles CartoCDN con cache-buster para canvas PDF |
| `_hexRgba(hex, a)` | Convierte `#RRGGBB` → `rgba(r,g,b,a)` para Canvas API |

### Flujo PDF (importante — hay race condition resuelta)
```
generarReporte()
  ├── Llama 4 funciones async de mapa (capturarMapaRpt, generarHeatmapRpt x2, generarHeatmapNseRpt)
  ├── tryRebuild() cuenta callbacks (done++) — cuando done>=4 setea _daterraMapsDone=true
  └── _cargarLibsPDF(callback)
        └── _procederConRender() — espera _daterraMapsDone antes de clonar DOM
```

### Estructura del reporte PDF (13 páginas)
1. Mapa de zona
2. Resumen ejecutivo
3. Crecimiento comparativo
4. Vivienda
5. Distribución de edad
6. Parque habitacional
7. Actividad económica + distribución NSE
8. Estructura familiar
9. Heatmap hogares
10. Heatmap crecimiento hogares
11. **Heatmap NSE** (nuevo)
12. Conclusiones
13. Soluciones COEZA

## Productos inmobiliarios (productos.html + score_productos.py)

Tres variables binarias (0/1) por AGEB, calculadas con percentiles internos de cada ZM:

| Variable | Perfil target | Criterios |
|---|---|---|
| `prod_nido_vacio` | Pareja 50-65 sin hijos, casa grande, busca liquidez | NSE≥P60 · 60+≥P50 · 0-14≤P45 · vph3≥P45 |
| `prod_retiro_libre` | Adulto 65+, monetiza vivienda para retiro | NSE≥P60 · 60+≥P70 · escolaridad≥P50 · vph3≥P50 |
| `prod_nuevo_hogar` | Familia 28-45, mejora y crece | NSE≥P45 · 25-59≥P50 · PEA≥P50 · crec>0 · 0-14≥P40 |

ZM Monterrey: 2041 AGEBs · ZM Torreón: 632 AGEBs

## Workflow de desarrollo

```bash
# Trabajar en DATERRA 2.0 (este repo)
cd "/Users/isaacamadorreyes/Documents/COEZA/coeza proyectos/coeza red/DATERRA-2.0"

# Ver cambios
git diff deploy/index.html

# Subir cambios → Cloudflare despliega automáticamente
git add deploy/index.html
git commit -m "feat: descripción del cambio"
git push origin main

# URL de preview: https://daterra-v2.isar1596.workers.dev
```

## Usuario
- **Isaac** — COEZA Consulting, Torreón
- Nivel avanzado en HTML/JS/CSS
- Comunicación en español

## Notas importantes
- El archivo principal es SIEMPRE `deploy/index.html` — nunca crear archivos JS/CSS separados
- Siempre hacer push al terminar un cambio
- Los GeoJSON de datos están en `deploy/data/` — son solo lectura, no modificar
- El script `scripts/score_productos.py` regenera `zm_*_productos.geojson` si se necesita
