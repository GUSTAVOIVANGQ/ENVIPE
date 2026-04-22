"""
procesar_envipe.py
Consolida el procesamiento de la ENVIPE para extraer datos históricos (2011-2025)
clasificando estrictamente por Delito x Medio de Comisión.
Genera un único CSV tabular.
"""

import os
import re
import sys
import zipfile
import argparse
import warnings
from pathlib import Path

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore", category=pd.errors.DtypeWarning)

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR     = Path(__file__).parent
ZIP_DIR      = BASE_DIR / "conjunto_de_datos"
OUT_RES_DIR  = BASE_DIR / "resultados"

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

DELITOS_HOGAR = {1, 2, 3, 4}

# ── Categorías de Medio de Comisión (Reglas CRT) ──────────────────────
GRUPO_MEDIO = {
    "telefono_llamada":    "Teléfono (llamada de voz)",
    "telefono_mensaje":    "Teléfono (SMS / WhatsApp / mensaje)",
    "telefono":            "Teléfono (sin especificar tipo)",
    "internet":            "Internet / redes sociales",
    "correo_postal":       "Correo / mensajería física",
    "presencial":          "Presencial",
    "presencial_digital":  "Presencial con seguimiento digital",
    "otro":                "Otro medio",
    "no_aplica":           "No aplica (delito de hogar)",
    "no_especificado":     "Sin información",
}

CATEGORIA_MEDIO = {
    "telefono_llamada":    "TELEFÓNICO",
    "telefono_mensaje":    "TELEFÓNICO",
    "telefono":            "TELEFÓNICO",
    "internet":            "INTERNET / DIGITAL",
    "correo_postal":       "OTRO MEDIO",
    "presencial":          "PRESENCIAL",
    "presencial_digital":  "PRESENCIAL",
    "otro":                "OTRO MEDIO",
    "no_aplica":           "NO APLICA (HOGAR)",
    "no_especificado":     "SIN INFORMACIÓN",
}

# Columnas alias a través de los años
COLUMN_ALIASES = {
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
}

# ─────────────────────────────────────────────────────────────────
# 1. IDENTIFICAR Y LEER ZIPs
# ─────────────────────────────────────────────────────────────────

def detectar_zips() -> dict[int, Path]:
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

def leer_dbf(fileobj) -> pd.DataFrame:
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
        raise ImportError("Instala dbfread (pip install dbfread) para leer archivos DBF.")

def extraer_tmod_vic(zip_path: Path, año: int) -> pd.DataFrame | None:
    nombre_buscado = ["tmod_vic", "tmodvic", "mod_vic", "modvic"]
    nombre_alternativo = ["victimizacion", "delitos", "bd_envipe"]
    try:
        with zipfile.ZipFile(zip_path) as z:
            archivos = z.namelist()
            candidatos = [a for a in archivos if a.lower().endswith((".dbf", ".csv")) and any(n in a.lower() for n in nombre_buscado)]
            if not candidatos:
                candidatos = [a for a in archivos if a.lower().endswith((".dbf", ".csv")) and any(n in a.lower() for n in nombre_alternativo)]
            if not candidatos:
                print(f"  ⚠ {año}: No se encontró TMod_Vic.")
                return None

            archivo = candidatos[0]
            print(f"  → Leyendo: {archivo}")
            with z.open(archivo) as f:
                if archivo.lower().endswith(".dbf"):
                    df = leer_dbf(f)
                else:
                    df = pd.read_csv(f, low_memory=False)
            df.columns = [c.upper().strip() for c in df.columns]
            return df
    except Exception as e:
        print(f"  ✗ Error en {año}: {e}")
        return None

# ─────────────────────────────────────────────────────────────────
# 2. LIMPIAR Y CLASIFICAR
# ─────────────────────────────────────────────────────────────────

def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col_std, aliases in COLUMN_ALIASES.items():
        if col_std not in df.columns:
            for alias in aliases:
                if alias in df.columns:
                    rename_map[alias] = col_std
                    break
    if rename_map:
        df = df.rename(columns=rename_map)
    for col in ["BPCOD", "BP4_1", "BP5_1", "BP5_1A_1", "BP5_1A_2", "BP5_3", "FAC_DEL"]:
        if col not in df.columns:
            df[col] = np.nan
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

def clasificar_medio(row: pd.Series) -> str:
    bpcod = row.get("BPCOD")
    if bpcod in DELITOS_HOGAR:
        return "no_aplica"

    if bpcod in (7, 8):
        bp4 = row.get("BP4_1")
        if pd.isna(bp4): return "no_especificado"
        return {1: "presencial", 2: "correo_postal", 3: "correo_postal", 4: "telefono", 5: "internet", 6: "otro", 9: "no_especificado"}.get(int(bp4), "no_especificado")

    if bpcod == 9:
        bp5 = row.get("BP5_1")
        if pd.isna(bp5): return "no_especificado"
        bp5 = int(bp5)
        if bp5 == 1:
            a1 = row.get("BP5_1A_1", 0) or 0
            a2 = row.get("BP5_1A_2", 0) or 0
            if a1 and a2: return "telefono"
            if a2: return "telefono_mensaje"
            return "telefono_llamada"
        if bp5 == 2: return "internet"
        if bp5 == 3:
            bp5_3 = row.get("BP5_3")
            if not pd.isna(bp5_3) and int(bp5_3) in (1, 2): return "presencial_digital"
            return "presencial"
        return "no_especificado"

    return "presencial"

def procesar_año(año: int, zip_path: Path) -> pd.DataFrame | None:
    print(f"[{año}] Procesando {zip_path.name}...")
    df = extraer_tmod_vic(zip_path, año)
    if df is None: return None

    df = normalizar_columnas(df)
    
    # Construir variables
    df["ANIO"] = año
    df["TIPO_DELITO"] = df["BPCOD"].map(BPCOD_LABELS).fillna("Desconocido")
    
    medios_raw = df.apply(clasificar_medio, axis=1)
    df["MEDIO_COMISION"] = medios_raw.map(GRUPO_MEDIO).fillna("Sin información")
    df["CATEGORIA_MEDIO"] = medios_raw.map(CATEGORIA_MEDIO).fillna("SIN INFORMACIÓN")
    
    df["FAC_DEL"] = pd.to_numeric(df["FAC_DEL"], errors="coerce").fillna(1)
    
    # Dejar solo las columnas necesarias para no gastar RAM
    return df[["ANIO", "TIPO_DELITO", "MEDIO_COMISION", "CATEGORIA_MEDIO", "FAC_DEL"]]

# ─────────────────────────────────────────────────────────────────
# 3. CONSOLIDAR Y GUARDAR
# ─────────────────────────────────────────────────────────────────

def main():
    zips = detectar_zips()
    if not zips:
        print("⚠ No se encontraron archivos ZIP en:", ZIP_DIR)
        return

    frames = []
    print(f"Archivos ZIP encontrados para los años: {sorted(zips.keys())}")
    print("-" * 40)
    
    for año, zip_path in sorted(zips.items()):
        df_año = procesar_año(año, zip_path)
        if df_año is not None:
            frames.append(df_año)
            
    if not frames:
        print("No se extrajeron datos.")
        return

    print("-" * 40)
    print("Consolidando y agregando datos históricos...")
    panel = pd.concat(frames, ignore_index=True)
    
    # Agrupar por las dimensiones requeridas
    agrupado = panel.groupby(["ANIO", "TIPO_DELITO", "MEDIO_COMISION", "CATEGORIA_MEDIO"]).agg(
        ESTIMACION_POBLACIONAL=("FAC_DEL", "sum"),
        REGISTROS_MUESTRA=("FAC_DEL", "count")
    ).reset_index()
    
    agrupado = agrupado.sort_values(["ANIO", "TIPO_DELITO", "ESTIMACION_POBLACIONAL"], ascending=[True, True, False])
    agrupado["ESTIMACION_POBLACIONAL"] = agrupado["ESTIMACION_POBLACIONAL"].round(0).astype(int)
    
    out_file = OUT_RES_DIR / "ENVIPE_DELITO_MEDIO_HISTORICO.csv"
    agrupado.to_csv(out_file, index=False, encoding="utf-8-sig")
    
    print("\n" + "="*60)
    print("PROCESO TERMINADO CON ÉXITO")
    print("="*60)
    print(f"Archivo generado: {out_file.resolve()}")
    print(f"Registros exportados: {len(agrupado):,}")
    print("Columnas:", list(agrupado.columns))

if __name__ == "__main__":
    main()
