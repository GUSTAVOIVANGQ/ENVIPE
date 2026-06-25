"""
ENVIPE Pipeline — Procesamiento de Microdatos 2011–2025
=======================================================
Uso:
    python main.py                   # procesa todos los ZIPs en la carpeta
    python main.py --año 2024        # procesa solo un año
    python main.py --solo-resumen    # no regenera CSVs, solo lee los ya procesados

Salidas:
    datos_procesados/
        envipe_{año}_limpio.csv      ← un CSV por año con todas las variables útiles
    resultados/
        panel_todos_años.csv         ← todos los años apilados (para análisis de tendencias)
        resumen_por_medio.csv        ← conteos y estimaciones por medio de comisión
        resumen_por_delito.csv       ← conteos por tipo de delito
        resumen_por_entidad.csv      ← conteos por estado (cuando aplica)
        dashboard_data.json          ← datos para el dashboard HTML
"""

import os
import re
import sys
import json
import zipfile
import argparse
import warnings
from pathlib import Path

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore", category=pd.errors.DtypeWarning)

# Forzar UTF-8 en stdout/stderr para que los símbolos unicode no rompan en Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────────────────────────
# CONFIGURACIÓN GLOBAL
# ─────────────────────────────────────────────────────────────────

BASE_DIR     = Path(__file__).parent          # donde está este script
ZIP_DIR      = BASE_DIR / "conjunto_de_datos" # donde están los ZIPs
OUT_DATA_DIR = BASE_DIR / "datos_procesados"  # CSVs limpios por año
OUT_RES_DIR  = BASE_DIR / "resultados"        # tablas resumen

OUT_DATA_DIR.mkdir(exist_ok=True)
OUT_RES_DIR.mkdir(exist_ok=True)

# ── Catálogo de delitos ────────────────────────────────────────────
BPCOD_LABELS = {
    1:  "Robo total de vehículo",
    2:  "Robo de accesorios de vehículo",
    3:  "Vandalismo / daño a propiedad",
    4:  "Robo a casa habitación",
    5:  "Robo / asalto en calle o transporte",
    6:  "Robo en otra forma",
    7:  "Fraude bancario",
    8:  "Fraude al consumidor",
    9:  "Extorsión",
    10: "Amenazas",
    11: "Lesiones físicas",
    12: "Secuestro",
    13: "Hostigamiento / abuso sexual",
    14: "Violación sexual",
    15: "Otro delito",
}

# ── Categorías de medio de comisión ───────────────────────────────
MEDIOS = {
    "telefono_llamada":    "Teléfono — llamada de voz",
    "telefono_mensaje":    "Teléfono — SMS / WhatsApp",
    "telefono":            "Teléfono (sin detalle)",
    "internet":            "Internet / redes sociales",
    "correo_postal":       "Correo / mensajería física",
    "presencial":          "Presencial (cara a cara)",
    "presencial_digital":  "Presencial + seguimiento digital",
    "otro":                "Otro medio",
    "no_aplica":           "No aplica (delito de hogar)",
    "no_especificado":     "Sin información",
}

MEDIOS_DIGITALES = {
    "telefono_llamada", "telefono_mensaje", "telefono", "internet",
}

# ── Grupos de delito ──────────────────────────────────────────────
DELITOS_HOGAR     = {1, 2, 3, 4}
DELITOS_DIGITALES = {7, 8, 9}   # donde el medio está capturado

# ── Variables sociodemográficas que queremos en el panel ──────────
SEXO_MAP   = {1: "Hombre", 2: "Mujer"}
AREAM_MAP  = {1: "Urbana", 2: "Rural", 14: "Urbana"}  # 14 = área metropolitana

# ─────────────────────────────────────────────────────────────────
# 1. DETECTAR ARCHIVOS ZIP POR AÑO
# ─────────────────────────────────────────────────────────────────

def detectar_zips() -> dict[int, Path]:
    """
    Busca todos los ZIPs en ZIP_DIR y los mapea a su año.
    Soporta los distintos formatos de nombre que usa INEGI:
        base_de_datos_envipe_2011_dbf.zip
        bd_envipe13_dbf.zip
        bd_envipe_2024_dbf.zip
    """
    patron = re.compile(r'(?:envipe[_]?)(20)?(\d{2,4})', re.IGNORECASE)
    zips = {}
    for f in sorted(ZIP_DIR.glob("*.zip")):
        m = patron.search(f.name)
        if not m:
            continue
        año_str = m.group(0).replace("envipe", "").replace("_", "").upper()
        año_raw = ''.join(filter(str.isdigit, año_str))
        if len(año_raw) == 2:
            año = 2000 + int(año_raw)
        elif len(año_raw) == 4:
            año = int(año_raw)
        else:
            continue
        if 2011 <= año <= 2030:
            zips[año] = f
    return zips


# ─────────────────────────────────────────────────────────────────
# 2. EXTRAER LA TABLA TMod_Vic DE UN ZIP
# ─────────────────────────────────────────────────────────────────

def extraer_tmod_vic(zip_path: Path, año: int) -> pd.DataFrame | None:
    """
    Abre el ZIP y extrae TMod_Vic (o su equivalente en años anteriores).
    En años previos el archivo puede llamarse de otra forma.
    """
    nombre_buscado = ["tmod_vic", "tmodvic", "mod_vic", "modvic"]
    # Para años muy anteriores el archivo de módulo de delitos tiene otro nombre
    nombre_alternativo = ["victimizacion", "delitos", "bd_envipe"]

    try:
        with zipfile.ZipFile(zip_path) as z:
            archivos = z.namelist()
            # Buscar DBF o CSV con nombre que coincida
            candidatos = [
                a for a in archivos
                if a.lower().endswith((".dbf", ".csv"))
                and any(n in a.lower() for n in nombre_buscado)
            ]
            if not candidatos:
                candidatos = [
                    a for a in archivos
                    if a.lower().endswith((".dbf", ".csv"))
                    and any(n in a.lower() for n in nombre_alternativo)
                ]
            if not candidatos:
                print(f"  ⚠ {año}: No se encontró TMod_Vic. Archivos en ZIP: {archivos[:5]}")
                return None

            archivo = candidatos[0]
            print(f"  → Leyendo: {archivo}")

            with z.open(archivo) as f:
                if archivo.lower().endswith(".dbf"):
                    df = leer_dbf(f)
                else:
                    df = pd.read_csv(f, low_memory=False)

            # Normalizar nombres de columnas a mayúsculas
            df.columns = [c.upper().strip() for c in df.columns]
            return df

    except Exception as e:
        print(f"  ✗ Error en {año}: {e}")
        return None


def leer_dbf(fileobj) -> pd.DataFrame:
    """Lee un .dbf. Requiere dbfread (pip install dbfread)."""
    try:
        from dbfread import DBF
        import tempfile, shutil
        with tempfile.NamedTemporaryFile(suffix=".dbf", delete=False) as tmp:
            shutil.copyfileobj(fileobj, tmp)
            tmp_path = tmp.name
        tabla = DBF(tmp_path, encoding="latin-1", load=True)
        df = pd.DataFrame(iter(tabla))
        os.unlink(tmp_path)
        return df
    except ImportError:
        raise ImportError(
            "Instala dbfread para leer archivos DBF:\n"
            "    pip install dbfread\n"
            "O descarga los archivos en formato CSV desde INEGI."
        )


# ─────────────────────────────────────────────────────────────────
# 3. LIMPIAR Y ESTANDARIZAR COLUMNAS
# ─────────────────────────────────────────────────────────────────

# Mapa de columnas equivalentes en distintos años
# Algunas variables cambiaron de nombre entre ediciones
COLUMN_ALIASES = {
    # Columna estándar → posibles nombres alternativos en ediciones antiguas
    "BPCOD":   ["BPCOD", "COD_DEL", "TIPODEL"],
    "BP4_1":   ["BP4_1", "BP4A_1", "P4_1"],
    "BP5_1":   ["BP5_1", "BP5A_1", "P5_1"],
    "BP5_1A_1":["BP5_1A_1", "BP51A1", "P5_1A1"],
    "BP5_1A_2":["BP5_1A_2", "BP51A2", "P5_1A2"],
    "BP5_1A_3":["BP5_1A_3", "BP51A3", "P5_1A3"],
    "BP5_1A_4":["BP5_1A_4", "BP51A4"],
    "BP5_2_1": ["BP5_2_1", "BP52_1"],
    "BP5_3":   ["BP5_3", "P5_3"],
    "FAC_DEL": ["FAC_DEL", "FACTOR_D", "FAC_DELI", "FACTORD"],
    "FAC_DEL_AM":["FAC_DEL_AM", "FAC_DELAM"],
    "SEXO":    ["SEXO", "SEXO_INF"],
    "EDAD":    ["EDAD", "EDAD_INF"],
    "CVE_ENT": ["CVE_ENT", "ENT", "ENTIDAD"],
    "NOM_ENT": ["NOM_ENT", "NOM_ENTIDAD"],
    "DOMINIO": ["DOMINIO", "DOM"],
}


def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """Renombra columnas a sus nombres estándar si usan alias."""
    rename_map = {}
    for col_std, aliases in COLUMN_ALIASES.items():
        if col_std not in df.columns:
            for alias in aliases:
                if alias in df.columns:
                    rename_map[alias] = col_std
                    break
    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def asegurar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega columnas faltantes como NaN para que el pipeline no rompa."""
    columnas_necesarias = [
        "BPCOD", "BP4_1", "BP5_1",
        "BP5_1A_1", "BP5_1A_2", "BP5_1A_3", "BP5_1A_4",
        "BP5_2_1", "BP5_2_2", "BP5_2_3", "BP5_3",
        "FAC_DEL", "FAC_DEL_AM",
        "SEXO", "EDAD", "CVE_ENT", "NOM_ENT", "DOMINIO",
    ]
    for col in columnas_necesarias:
        if col not in df.columns:
            df[col] = np.nan
    return df


# ─────────────────────────────────────────────────────────────────
# 4. CLASIFICAR MEDIO DE COMISIÓN
# ─────────────────────────────────────────────────────────────────

def clasificar_medio(row: pd.Series) -> str:
    bpcod = row.get("BPCOD")

    # Delitos de hogar → el medio no se captura en el cuestionario
    if bpcod in DELITOS_HOGAR:
        return "no_aplica"

    # ── Fraude bancario (7) y fraude al consumidor (8) ──────────
    if bpcod in (7, 8):
        bp4 = row.get("BP4_1")
        if pd.isna(bp4):
            return "no_especificado"
        bp4 = int(bp4)
        return {
            1: "presencial",
            2: "correo_postal",
            3: "correo_postal",
            4: "telefono",
            5: "internet",
            6: "otro",
            9: "no_especificado",
        }.get(bp4, "no_especificado")

    # ── Extorsión (9) ────────────────────────────────────────────
    if bpcod == 9:
        bp5 = row.get("BP5_1")
        if pd.isna(bp5):
            return "no_especificado"
        bp5 = int(bp5)

        if bp5 == 1:   # Teléfono
            a1 = row.get("BP5_1A_1", 0) or 0   # llamada de voz
            a2 = row.get("BP5_1A_2", 0) or 0   # mensaje / WhatsApp
            if a1 and a2:
                return "telefono"
            if a2:
                return "telefono_mensaje"
            return "telefono_llamada"

        if bp5 == 2:
            return "internet"

        if bp5 == 3:
            # Presencial — revisar si hubo seguimiento digital
            bp5_3 = row.get("BP5_3")
            if not pd.isna(bp5_3):
                bp5_3 = int(bp5_3)
                if bp5_3 in (1, 2):
                    return "presencial_digital"
            return "presencial"

        return "no_especificado"

    # ── Todos los demás delitos → presenciales por definición ────
    return "presencial"


def es_digital(medio: str) -> int:
    return 1 if medio in MEDIOS_DIGITALES else 0


# ─────────────────────────────────────────────────────────────────
# 5. ENRIQUECER CON ETIQUETAS LEGIBLES
# ─────────────────────────────────────────────────────────────────

def enriquecer(df: pd.DataFrame, año: int) -> pd.DataFrame:
    df = df.copy()
    df["año"]            = año
    df["delito"]         = df["BPCOD"].map(BPCOD_LABELS).fillna("Desconocido")
    df["medio_comision"] = df.apply(clasificar_medio, axis=1)
    df["medio_etiqueta"] = df["medio_comision"].map(MEDIOS).fillna("Sin etiqueta")
    df["es_digital"]     = df["medio_comision"].apply(es_digital)
    df["sexo_label"]     = df["SEXO"].map(SEXO_MAP).fillna("No especificado")
    df["area_label"]     = df["DOMINIO"].map({
        "U": "Urbana", "R": "Rural", 1: "Urbana", 2: "Rural"
    }).fillna("No especificado")

    # Grupo de edad
    def grupo_edad(e):
        try:
            e = int(e)
        except (TypeError, ValueError):
            return "No especificado"
        if e < 18:  return "Menor de 18"
        if e < 30:  return "18–29"
        if e < 45:  return "30–44"
        if e < 60:  return "45–59"
        return "60 o más"

    df["grupo_edad"] = df["EDAD"].apply(grupo_edad)
    return df


# ─────────────────────────────────────────────────────────────────
# 6. PROCESAR UN AÑO COMPLETO
# ─────────────────────────────────────────────────────────────────

COLS_SALIDA = [
    "año", "BPCOD", "delito", "medio_comision", "medio_etiqueta",
    "es_digital", "sexo_label", "grupo_edad", "area_label",
    "CVE_ENT", "NOM_ENT",
    "FAC_DEL", "FAC_DEL_AM",
    "BP4_1", "BP5_1", "BP5_1A_1", "BP5_1A_2", "BP5_1A_3", "BP5_1A_4",
    "BP5_3", "ID_DEL",
]


def procesar_año(año: int, zip_path: Path) -> pd.DataFrame | None:
    print(f"\n[{año}] {zip_path.name}")

    df = extraer_tmod_vic(zip_path, año)
    if df is None:
        return None

    df = normalizar_columnas(df)
    df = asegurar_columnas(df)
    df = enriquecer(df, año)

    # Seleccionar columnas que existen
    cols = [c for c in COLS_SALIDA if c in df.columns]
    df_out = df[cols].copy()

    # Guardar CSV limpio por año
    ruta = OUT_DATA_DIR / f"envipe_{año}_limpio.csv"
    df_out.to_csv(ruta, index=False, encoding="utf-8-sig")
    print(f"  ✓ Guardado: {ruta.name}  ({len(df_out):,} registros)")
    return df_out


# ─────────────────────────────────────────────────────────────────
# 7. GENERAR TABLAS RESUMEN
# ─────────────────────────────────────────────────────────────────

def tabla_por_medio(panel: pd.DataFrame) -> pd.DataFrame:
    """Estimación poblacional ponderada por medio de comisión y año."""
    return (
        panel.groupby(["año", "medio_etiqueta"])
        .agg(
            registros=("FAC_DEL", "count"),
            estimacion=("FAC_DEL", "sum"),
        )
        .reset_index()
        .sort_values(["año", "estimacion"], ascending=[True, False])
    )


def tabla_por_delito(panel: pd.DataFrame) -> pd.DataFrame:
    return (
        panel.groupby(["año", "delito", "medio_etiqueta"])
        .agg(
            registros=("FAC_DEL", "count"),
            estimacion=("FAC_DEL", "sum"),
        )
        .reset_index()
        .sort_values(["año", "delito", "estimacion"], ascending=[True, True, False])
    )


def tabla_por_entidad(panel: pd.DataFrame) -> pd.DataFrame:
    if "NOM_ENT" not in panel.columns or panel["NOM_ENT"].isna().all():
        return pd.DataFrame()
    return (
        panel.groupby(["año", "NOM_ENT", "delito"])
        .agg(estimacion=("FAC_DEL", "sum"))
        .reset_index()
        .sort_values(["año", "estimacion"], ascending=[True, False])
    )


def tabla_digital_tendencia(panel: pd.DataFrame) -> pd.DataFrame:
    """Serie de tiempo: ¿cómo evolucionan los delitos digitales año a año?"""
    return (
        panel[panel["es_digital"] == 1]
        .groupby(["año", "delito", "medio_etiqueta"])
        .agg(estimacion=("FAC_DEL", "sum"))
        .reset_index()
        .sort_values(["delito", "año"])
    )


# ─────────────────────────────────────────────────────────────────
# 8. GENERAR JSON PARA EL DASHBOARD
# ─────────────────────────────────────────────────────────────────

def generar_json_dashboard(panel: pd.DataFrame) -> dict:
    """Estructura de datos para dashboard_envipe.html"""

    años = sorted(panel["año"].unique().tolist())

    # Totales por año
    totales_año = (
        panel.groupby("año")["FAC_DEL"]
        .sum()
        .reset_index()
        .rename(columns={"FAC_DEL": "total"})
    )

    # Digitales por año
    digitales_año = (
        panel[panel["es_digital"] == 1]
        .groupby("año")["FAC_DEL"]
        .sum()
        .reset_index()
        .rename(columns={"FAC_DEL": "digital"})
    )

    # Merge
    serie = totales_año.merge(digitales_año, on="año", how="left").fillna(0)
    serie["pct_digital"] = (serie["digital"] / serie["total"] * 100).round(1)

    # Medio por año
    medio_por_año = (
        panel.groupby(["año", "medio_etiqueta"])["FAC_DEL"]
        .sum()
        .reset_index()
        .rename(columns={"FAC_DEL": "estimacion"})
        .sort_values(["año", "estimacion"], ascending=[True, False])
    )

    # Delito por año
    delito_por_año = (
        panel.groupby(["año", "delito"])["FAC_DEL"]
        .sum()
        .reset_index()
        .rename(columns={"FAC_DEL": "estimacion"})
        .sort_values(["año", "estimacion"], ascending=[True, False])
    )

    # Extorsión por medio y año
    ext_por_año = (
        panel[panel["BPCOD"] == 9]
        .groupby(["año", "medio_etiqueta"])["FAC_DEL"]
        .sum()
        .reset_index()
        .rename(columns={"FAC_DEL": "estimacion"})
        .sort_values(["año", "estimacion"], ascending=[True, False])
    )

    # Breakdown por año (Delito x Medio)
    breakdown_por_año = (
        panel.groupby(["año", "delito", "medio_etiqueta"])["FAC_DEL"]
        .sum()
        .reset_index()
        .rename(columns={"FAC_DEL": "estimacion"})
        .sort_values(["año", "estimacion"], ascending=[True, False])
    )

    ultimo_año = max(años)

    return {
        "años": [int(a) for a in años],
        "ultimo_año": int(ultimo_año),
        "serie_anual": serie.to_dict(orient="records"),
        "medio_por_año": medio_por_año.to_dict(orient="records"),
        "delito_por_año": delito_por_año.to_dict(orient="records"),
        "extorsion_por_año": ext_por_año.to_dict(orient="records"),
        "breakdown_por_año": breakdown_por_año.to_dict(orient="records"),
    }


# ─────────────────────────────────────────────────────────────────
# 9. PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ENVIPE Pipeline")
    parser.add_argument("--año",          type=int, help="Procesar solo este año")
    parser.add_argument("--solo-resumen", action="store_true",
                        help="No re-procesar ZIPs, solo leer CSVs ya generados")
    args = parser.parse_args()

    # ── A) Cargar datos ──────────────────────────────────────────
    frames = []

    if args.solo_resumen:
        # Leer CSVs ya procesados
        print("Cargando CSVs procesados...")
        for csv in sorted(OUT_DATA_DIR.glob("envipe_*_limpio.csv")):
            df = pd.read_csv(csv, low_memory=False)
            frames.append(df)
            print(f"  {csv.name}: {len(df):,} registros")
    else:
        # Procesar desde ZIPs
        zips = detectar_zips()
        if not zips:
            print("⚠ No se encontraron archivos ZIP en:", ZIP_DIR)
            print("  Asegúrate de que los ZIPs estén en la misma carpeta que main.py")
            return

        if args.año:
            if args.año not in zips:
                print(f"✗ No se encontró ZIP para el año {args.año}")
                return
            zips = {args.año: zips[args.año]}

        print(f"ZIPs encontrados: {sorted(zips.keys())}")
        for año, zip_path in sorted(zips.items()):
            df = procesar_año(año, zip_path)
            if df is not None:
                frames.append(df)

    if not frames:
        print("No se procesó ningún dato.")
        return

    # ── B) Panel consolidado ─────────────────────────────────────
    print("\nConsolidando panel de todos los años...")
    panel = pd.concat(frames, ignore_index=True)
    panel["FAC_DEL"] = pd.to_numeric(panel["FAC_DEL"], errors="coerce").fillna(1)
    panel.to_csv(OUT_RES_DIR / "panel_todos_años.csv", index=False, encoding="utf-8-sig")
    print(f"  panel_todos_años.csv: {len(panel):,} registros")

    # ── C) Tablas resumen ────────────────────────────────────────
    print("\nGenerando tablas resumen...")

    t_medio = tabla_por_medio(panel)
    t_medio.to_csv(OUT_RES_DIR / "resumen_por_medio.csv", index=False, encoding="utf-8-sig")
    print(f"  resumen_por_medio.csv: {len(t_medio)} filas")

    t_delito = tabla_por_delito(panel)
    t_delito.to_csv(OUT_RES_DIR / "resumen_por_delito.csv", index=False, encoding="utf-8-sig")
    print(f"  resumen_por_delito.csv: {len(t_delito)} filas")

    t_ent = tabla_por_entidad(panel)
    if not t_ent.empty:
        t_ent.to_csv(OUT_RES_DIR / "resumen_por_entidad.csv", index=False, encoding="utf-8-sig")
        print(f"  resumen_por_entidad.csv: {len(t_ent)} filas")

    t_dig = tabla_digital_tendencia(panel)
    t_dig.to_csv(OUT_RES_DIR / "tendencia_digital.csv", index=False, encoding="utf-8-sig")
    print(f"  tendencia_digital.csv: {len(t_dig)} filas")

    # ── D) JSON para dashboard ───────────────────────────────────
    print("\nGenerando datos para el dashboard...")
    datos_dash = generar_json_dashboard(panel)
    
    # Guardar como JSON
    json_path = OUT_RES_DIR / "dashboard_data.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(datos_dash, f, ensure_ascii=False, indent=2)
    print(f"  dashboard_data.json generado")

    # Guardar como JS para evitar problemas de CORS al abrir el HTML localmente
    js_path = OUT_RES_DIR / "dashboard_data.js"
    with open(js_path, "w", encoding="utf-8") as f:
        f.write("const DASHBOARD_DATA = ")
        json.dump(datos_dash, f, ensure_ascii=False, indent=2)
        f.write(";\n")
    print(f"  dashboard_data.js generado")

    # ── E) Resumen en consola ────────────────────────────────────
    print("\n" + "=" * 60)
    print("RESUMEN FINAL")
    print("=" * 60)
    print(f"  Años procesados    : {sorted(panel['año'].unique().tolist())}")
    print(f"  Total de registros : {len(panel):,}")

    cobertura = panel["medio_comision"].value_counts()
    total = len(panel)
    clasificados = total - cobertura.get("no_especificado", 0) - cobertura.get("no_aplica", 0)
    print(f"  Clasificados       : {clasificados:,} ({clasificados/total:.1%})")

    print("\n  Distribución por medio (último año disponible):")
    ult = panel[panel["año"] == panel["año"].max()]
    dist = (
        ult.groupby("medio_etiqueta")["FAC_DEL"]
        .sum()
        .sort_values(ascending=False)
    )
    for medio, val in dist.items():
        print(f"    {medio:<35} {val:>15,.0f}")

    print(f"\n✓ Resultados en: {OUT_RES_DIR.resolve()}")
    print("  Abre dashboard_envipe.html en tu navegador para visualizar.")


if __name__ == "__main__":
    main()