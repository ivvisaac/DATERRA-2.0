#!/usr/bin/env python3
"""
COEZA — Score de productos inmobiliarios por AGEB
Genera GeoJSON con variables binarias (0/1) para tres perfiles de comprador,
calculadas con percentiles internos de cada Zona Metropolitana.

Productos:
  prod_nido_vacio   — Pareja sin hijos en casa, vivienda grande, busca liquidez
  prod_retiro_libre — Adulto mayor independiente, financiar retiro, activo inmobiliario
  prod_nuevo_hogar  — Familia joven creciendo, busca segunda (mejor) vivienda
"""

import json, math, sys, os
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "deploy" / "data"
OUT_DIR  = Path(__file__).parent.parent / "deploy" / "data"

# ──────────────────────────────────────────────────────────────────────────────
# ZM DEFINITIONS
# ──────────────────────────────────────────────────────────────────────────────
ZM_MONTERREY = {
    "label": "ZM Monterrey",
    "sources": [("19_nuevo_leon.json", {
        "Apodaca","Cadereyta Jiménez","Ciénega de Flores","Doctor González",
        "El Carmen","García","General Escobedo","General Zuazua","Guadalupe",
        "Juárez","Marín","Monterrey","Pesquería","Salinas Victoria",
        "San Nicolás de los Garza","San Pedro Garza García",
        "Santa Catarina","Santiago",
    })],
}

ZM_TORREON = {
    "label": "ZM Torreón",
    "sources": [
        ("05_coahuila_de_zaragoza.json", {"Torreón","Matamoros"}),
        ("10_durango.json",              {"Gómez Palacio","Lerdo"}),
    ],
}

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def safe_div(a, b, default=0.0):
    return a / b if b and b > 0 else default

def percentile_val(values, p):
    """Percentile p (0-100) of a sorted list."""
    s = sorted(v for v in values if v is not None and not math.isnan(v))
    if not s:
        return 0.0
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (k - lo) * (s[hi] - s[lo])

def add_derived(props):
    """Add computed metrics to a properties dict (in-place)."""
    pob = props.get("pob_total") or 0
    viv = props.get("viv_habitadas") or 0
    nse_viv = props.get("nse_viviendas") or 0

    # NSE alto: hogares AB + C+  como % del total NSE capturado
    nse_alto_n = (props.get("nse_ab") or 0) + (props.get("nse_cmas") or 0)
    props["pct_nse_alto"] = safe_div(nse_alto_n * 100, nse_viv)

    # % viviendas con 3+ cuartos (proxy vivienda grande)
    props["pct_vph3"] = safe_div((props.get("vph_3mas_cuartos") or 0) * 100, viv)

    # Ratios de edad ya existen como pct_60mas, pct_0_14, pct_25_59, pct_pea

    return props

# ──────────────────────────────────────────────────────────────────────────────
# LOAD & FILTER
# ──────────────────────────────────────────────────────────────────────────────
def load_zm(zm_def):
    feats = []
    for filename, muns in zm_def["sources"]:
        path = DATA_DIR / filename
        with open(path, encoding="utf-8") as f:
            gj = json.load(f)
        for ft in gj["features"]:
            if ft["properties"].get("municipio") in muns:
                if (ft["properties"].get("pob_total") or 0) >= 50:
                    add_derived(ft["properties"])
                    feats.append(ft)
    print(f"  {zm_def['label']}: {len(feats)} AGEBs cargados")
    return feats

# ──────────────────────────────────────────────────────────────────────────────
# PERCENTILE THRESHOLDS
# ──────────────────────────────────────────────────────────────────────────────
def compute_thresholds(feats):
    def vals(key):
        return [ft["properties"].get(key) or 0 for ft in feats]

    return {
        # Nido Vacío thresholds
        "nv_nse":    percentile_val(vals("pct_nse_alto"), 60),   # NSE alto: top 40%
        "nv_60":     percentile_val(vals("pct_60mas"),    50),   # adultos 60+ : top 50%
        "nv_014":    percentile_val(vals("pct_0_14"),     45),   # pocos niños: bottom 45%
        "nv_vph3":   percentile_val(vals("pct_vph3"),     45),   # casas grandes: top 55%

        # Retiro Libre thresholds
        "rl_nse":    percentile_val(vals("pct_nse_alto"), 60),
        "rl_60":     percentile_val(vals("pct_60mas"),    70),   # seniors fuerte: top 30%
        "rl_esc":    percentile_val(vals("escolaridad"),  50),
        "rl_vph3":   percentile_val(vals("pct_vph3"),     50),

        # Nuevo Hogar thresholds
        "nh_nse":    percentile_val(vals("pct_nse_alto"), 45),
        "nh_2559":   percentile_val(vals("pct_25_59"),    50),
        "nh_pea":    percentile_val(vals("pct_pea"),      50),
        "nh_014":    percentile_val(vals("pct_0_14"),     40),   # familias con hijos: top 60%
    }

# ──────────────────────────────────────────────────────────────────────────────
# SCORING
# ──────────────────────────────────────────────────────────────────────────────
def score_feature(props, thr):
    p = props

    # ── Producto 1: Nido Vacío ─────────────────────────────────────────────
    # Pareja 50-65, vivienda grande, sin hijos, NSE C+/AB, busca liquidez.
    # Criterios: NSE alto + 60+ presentes + pocos niños + casa grande
    crit_nv = [
        p.get("pct_nse_alto", 0) >= thr["nv_nse"],   # NSE calificado
        p.get("pct_60mas",    0) >= thr["nv_60"],    # adultos maduros
        p.get("pct_0_14",     0) <= thr["nv_014"],   # pocos niños en zona
        p.get("pct_vph3",     0) >= thr["nv_vph3"],  # casas grandes disponibles
    ]
    props["prod_nido_vacio"] = 1 if all(crit_nv) else 0

    # ── Producto 2: Retiro Libre ───────────────────────────────────────────
    # Adulto 65+, NSE C+/AB, vivienda grande, escolaridad alta, quiere
    # monetizar su propiedad para financiar retiro.
    crit_rl = [
        p.get("pct_nse_alto", 0) >= thr["rl_nse"],
        p.get("pct_60mas",    0) >= thr["rl_60"],    # fuerte presencia senior
        p.get("escolaridad",  0) >= thr["rl_esc"],   # perfil financieramente capaz
        p.get("pct_vph3",     0) >= thr["rl_vph3"],  # activo inmobiliario grande
    ]
    props["prod_retiro_libre"] = 1 if all(crit_rl) else 0

    # ── Producto 3: Nuevo Hogar ────────────────────────────────────────────
    # Familia 28-45, ya tiene primera propiedad, quiere mejorar + crecer.
    # NSE C+/AB, adultos trabajando, crecimiento positivo, hijos presentes.
    crec_hog = (p.get("crec_abs_hog") or 0) > 0 or (p.get("crec_pct_hog") or 0) > 0
    crit_nh = [
        p.get("pct_nse_alto", 0) >= thr["nh_nse"],
        p.get("pct_25_59",    0) >= thr["nh_2559"],
        p.get("pct_pea",      0) >= thr["nh_pea"],
        crec_hog,
        p.get("pct_0_14",     0) >= thr["nh_014"],
    ]
    props["prod_nuevo_hogar"] = 1 if all(crit_nh) else 0

# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────
def process_zm(zm_def, out_name):
    print(f"\n{'='*60}")
    print(f"Procesando: {zm_def['label']}")
    feats = load_zm(zm_def)
    thr   = compute_thresholds(feats)

    print(f"  Umbrales internos de la ZM:")
    for k, v in thr.items():
        print(f"    {k:12s}: {v:.2f}")

    for ft in feats:
        score_feature(ft["properties"], thr)

    # Estadísticas de cobertura
    n1 = sum(1 for ft in feats if ft["properties"]["prod_nido_vacio"]  == 1)
    n2 = sum(1 for ft in feats if ft["properties"]["prod_retiro_libre"]== 1)
    n3 = sum(1 for ft in feats if ft["properties"]["prod_nuevo_hogar"] == 1)
    print(f"  AGEBs calificados:")
    print(f"    Nido Vacío     (prod_nido_vacio):   {n1:4d} / {len(feats)}  ({n1/len(feats)*100:.1f}%)")
    print(f"    Retiro Libre   (prod_retiro_libre): {n2:4d} / {len(feats)}  ({n2/len(feats)*100:.1f}%)")
    print(f"    Nuevo Hogar    (prod_nuevo_hogar):  {n3:4d} / {len(feats)}  ({n3/len(feats)*100:.1f}%)")

    out = {"type": "FeatureCollection", "features": feats}
    out_path = OUT_DIR / out_name
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = out_path.stat().st_size / 1024
    print(f"  → Guardado: {out_name}  ({size_kb:.0f} KB)")
    return thr, feats

if __name__ == "__main__":
    thr_mty, feats_mty = process_zm(ZM_MONTERREY, "zm_monterrey_productos.geojson")
    thr_trn, feats_trn = process_zm(ZM_TORREON,   "zm_torreon_productos.geojson")
    print("\n✓ Proceso completado.")
