"""
procesar_envipe_v2.py
=====================
Consolida el procesamiento de la ENVIPE para extraer datos históricos (2012-2025)
clasificando por Delito x Medio de Comisión usando telecomunicaciones como canal.

CORRECCIONES vs v1:
  - 2011 EXCLUIDO: TMod_Vic de 2011 no contiene BP4_1 ni FAC_DEL; estructura
    incompatible con los años posteriores. No se pueden obtener estimaciones
    poblacionales confiables.
  - Codificación real de BP5_1 para extorsión (BPCOD=09), válida 2012-2024:
        1 = Telefónica          ← TELECOM
        2 = Laboral             ← NO telecom (era el error principal)
        3 = Internet / correo   ← TELECOM
        4 = En persona          ← NO telecom
        5 = Otra forma          ← otro
        9 = NS / NR             ← no_especificado
  - 2025 tiene nueva estructura: BP5_1 solo 1-3 con subcolumnas BP5_1A_1/A_2/A_3/A_4
    para desagregar el tipo de llamada/mensaje telefónico.
  - Codificación de BP4_1 para fraude (BPCOD=07,08), válida 2012-2025:
        1 = Presencial          ← NO telecom
        2 = Correo/mensajería   ← NO telecom
        3 = Correo electrónico  ← internet
        4 = Teléfono            ← TELECOM
        5 = Internet            ← internet
        6 = Otra forma          ← otro
        9 = NS / NR             ← no_especificado
  - BPCOD en todos los años viene como string de 2 dígitos ('01','09', etc.)
  - FAC_DEL viene como string con ceros a la izquierda en varios años;
    pd.to_numeric con errors='coerce' lo maneja correctamente.
  - Secuestro REMOVIDO de delitos_telecom (no corresponde metodológicamente).
  - Se agrega columna REGISTROS_MUESTRA al output.
  - Se agrega log de registros descartados por año para auditoría.

FUENTE: INEGI - Encuesta Nacional de Victimización y Percepción sobre
        Seguridad Pública (ENVIPE), microdatos anuales.
        https://www.inegi.org.mx/programas/envipe/
"""

import os
import re
import sys
import zipfile
import tempfile
import shutil
import warnings
from pathlib import Path

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore", category=pd.errors.DtypeWarning)

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR    = Path(__file__).parent
ZIP_DIR     = BASE_DIR / "conjunto_de_datos"
OUT_RES_DIR = BASE_DIR / "resultados"
OUT_RES_DIR.mkdir(exist_ok=True)

# ── Catálogo de delitos ────────────────────────────────────────────────────────
# BPCOD viene como string de 2 dígitos en todos los años ('01', '09', etc.)
BPCOD_LABELS = {
    "01": "Robo total de vehículo",
    "02": "Robo de accesorios de vehículo",
    "03": "Vandalismo / daño a propiedad",
    "04": "Robo a casa habitación",
    "05": "Robo / asalto en calle o transporte",
    "06": "Robo en otra forma",
    "07": "Fraude bancario",
    "08": "Fraude al consumidor",
    "09": "Extorsión",
    "10": "Amenazas",
    "11": "Lesiones físicas",
    "12": "Secuestro",
    "13": "Hostigamiento / abuso sexual",
    "14": "Violación sexual",
    "15": "Otro delito",
}

# Delitos de hogar (no aplica medio de comisión personal)
DELITOS_HOGAR = {"01", "02", "03", "04"}

# ── Categorías de Medio de Comisión ───────────────────────────────────────────
GRUPO_MEDIO = {
    "telefono_llamada":   "Teléfono (llamada de voz)",
    "telefono_mensaje":   "Teléfono (SMS / WhatsApp / mensaje)",
    "telefono":           "Teléfono (sin especificar tipo)",
    "internet":           "Internet / redes sociales",
    "correo_postal":      "Correo / mensajería física",
    "presencial":         "Presencial",
    "laboral":            "Laboral (sin medio digital)",
    "otro":               "Otro medio",
    "no_aplica":          "No aplica (delito de hogar)",
    "no_especificado":    "Sin información",
}

# ── Detección de ZIPs ──────────────────────────────────────────────────────────
def detectar_zips() -> dict[int, Path]:
    patron = re.compile(r'envipe[_]?(20)?(\d{2,4})', re.IGNORECASE)
    zips = {}
    for f in sorted(ZIP_DIR.glob("*.zip")):
        m = patron.search(f.name)
        if not m:
            continue
        raw = ''.join(filter(str.isdigit, m.group(0).lower().replace("envipe", "").replace("_", "")))
        if len(raw) == 2:
            año = 2000 + int(raw)
        elif len(raw) == 4:
            año = int(raw)
        else:
            continue
        if 2012 <= año <= 2030:   # 2011 excluido por estructura incompatible
            zips[año] = f
    return zips

# ── Lectura de DBF ─────────────────────────────────────────────────────────────
def leer_dbf(fileobj) -> pd.DataFrame:
    try:
        from dbfread import DBF
    except ImportError:
        raise ImportError("Instala dbfread: pip install dbfread")
    with tempfile.NamedTemporaryFile(suffix=".dbf", delete=False) as tmp:
        shutil.copyfileobj(fileobj, tmp)
        tmp_path = tmp.name
    try:
        tabla = DBF(tmp_path, encoding="latin-1", load=True)
        df = pd.DataFrame(iter(tabla))
        return df
    finally:
        os.unlink(tmp_path)

def extraer_tmod_vic(zip_path: Path, año: int) -> pd.DataFrame | None:
    nombres_buscados = ["tmod_vic", "tmodvic", "mod_vic", "modvic"]
    try:
        with zipfile.ZipFile(zip_path) as z:
            candidatos = [
                a for a in z.namelist()
                if a.lower().endswith((".dbf", ".csv"))
                and any(n in a.lower().split("/")[-1] for n in nombres_buscados)
            ]
            if not candidatos:
                print(f"  ⚠ {año}: No se encontró TMod_Vic.")
                return None
            archivo = candidatos[0]
            print(f"  → {archivo}")
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

# ── Clasificación del medio de comisión ───────────────────────────────────────
# Lógica separada por año porque 2025 tiene estructura diferente en BP5_1

def clasificar_medio_2012_2024(row: pd.Series) -> str:
    """
    Clasificación para 2012–2024.

    BP4_1 (fraude bancario BPCOD=07, fraude consumidor BPCOD=08):
        1=Presencial  2=Correo postal  3=Correo electrónico
        4=Teléfono    5=Internet       6=Otra forma  9=NS/NR

    BP5_1 (extorsión BPCOD=09):
        1=Telefónica  2=Laboral  3=Internet/correo
        4=En persona  5=Otra     9=NS/NR
    """
    bpcod = str(row.get("BPCOD", "")).strip().zfill(2)

    if bpcod in DELITOS_HOGAR:
        return "no_aplica"

    # ── Fraude bancario y al consumidor ──────────────────────────
    if bpcod in ("07", "08"):
        bp4 = row.get("BP4_1")
        if pd.isna(bp4):
            return "no_especificado"
        try:
            bp4 = int(float(bp4))
        except (ValueError, TypeError):
            return "no_especificado"
        return {
            1: "presencial",
            2: "correo_postal",
            3: "internet",       # correo electrónico → internet
            4: "telefono",       # teléfono
            5: "internet",       # internet
            6: "otro",
            9: "no_especificado",
        }.get(bp4, "no_especificado")

    # ── Extorsión ─────────────────────────────────────────────────
    if bpcod == "09":
        bp5 = row.get("BP5_1")
        if pd.isna(bp5):
            return "no_especificado"
        try:
            bp5 = int(float(bp5))
        except (ValueError, TypeError):
            return "no_especificado"
        return {
            1: "telefono",       # telefónica
            2: "laboral",        # laboral  ← CORRECCIÓN (antes se mapeaba a internet)
            3: "internet",       # internet / correo electrónico
            4: "presencial",     # en persona
            5: "otro",           # otra forma
            9: "no_especificado",
        }.get(bp5, "no_especificado")

    # Todos los demás delitos personales → presencial por defecto
    return "presencial"


def clasificar_medio_2025(row: pd.Series) -> str:
    """
    Clasificación para 2025.
    BP5_1 en 2025 tiene nueva codificación:
        1 = Telefónica  (subtipos en BP5_1A_1 llamada, BP5_1A_2 mensaje,
                         BP5_1A_3 WhatsApp/redes, BP5_1A_4 otra app)
        2 = Internet / redes sociales
        3 = En persona / presencial
    BP4_1 mantiene misma codificación que años anteriores.
    """
    bpcod = str(row.get("BPCOD", "")).strip().zfill(2)

    if bpcod in DELITOS_HOGAR:
        return "no_aplica"

    if bpcod in ("07", "08"):
        bp4 = row.get("BP4_1")
        if pd.isna(bp4):
            return "no_especificado"
        try:
            bp4 = int(float(bp4))
        except (ValueError, TypeError):
            return "no_especificado"
        return {
            1: "presencial",
            2: "correo_postal",
            3: "internet",
            4: "telefono",
            5: "internet",
            6: "otro",
            9: "no_especificado",
        }.get(bp4, "no_especificado")

    if bpcod == "09":
        bp5 = row.get("BP5_1")
        if pd.isna(bp5):
            return "no_especificado"
        try:
            bp5 = int(float(bp5))
        except (ValueError, TypeError):
            return "no_especificado"

        if bp5 == 1:
            # Desagregar subtipo telefónico con BP5_1A_1 (llamada) y BP5_1A_2 (mensaje)
            def safe_int(val):
                if pd.isna(val) or val == "":
                    return 0
                try:
                    return int(float(val))
                except (ValueError, TypeError):
                    return 0
            
            a1 = safe_int(row.get("BP5_1A_1"))
            a2 = safe_int(row.get("BP5_1A_2"))
            if a1 and a2:
                return "telefono"          # ambos → genérico
            if a1:
                return "telefono_llamada"
            if a2:
                return "telefono_mensaje"
            return "telefono"              # marcó teléfono pero sin subtipo

        if bp5 == 2:
            return "internet"
        if bp5 == 3:
            return "presencial"
        return "no_especificado"

    return "presencial"


# ── Procesamiento por año ──────────────────────────────────────────────────────
def procesar_año(año: int, zip_path: Path) -> pd.DataFrame | None:
    print(f"\n[{año}] {zip_path.name}")
    df = extraer_tmod_vic(zip_path, año)
    if df is None:
        return None

    total_registros = len(df)

    # Normalizar BPCOD a string de 2 dígitos
    df["BPCOD"] = df["BPCOD"].astype(str).str.strip().str.zfill(2)

    # Factor de expansión
    col_fac = next(
        (c for c in ["FAC_DEL", "FACTOR_D", "FAC_DELI", "FACTORD"] if c in df.columns),
        None
    )
    if col_fac is None:
        print(f"  ✗ No se encontró columna FAC_DEL — año {año} omitido.")
        return None

    df["FAC_DEL_N"] = pd.to_numeric(df[col_fac].astype(str).str.strip(), errors="coerce")
    sin_factor = df["FAC_DEL_N"].isna().sum()
    if sin_factor > 0:
        print(f"  ⚠ {sin_factor:,} registros sin factor de expansión válido (se excluyen).")
    df = df[df["FAC_DEL_N"].notna() & (df["FAC_DEL_N"] > 0)].copy()

    # Tipo de delito
    df["TIPO_DELITO"] = df["BPCOD"].map(BPCOD_LABELS).fillna("Desconocido")

    # Clasificar medio según año
    if año == 2025:
        df["MEDIO_KEY"] = df.apply(clasificar_medio_2025, axis=1)
    else:
        df["MEDIO_KEY"] = df.apply(clasificar_medio_2012_2024, axis=1)

    df["MEDIO_COMISION"] = df["MEDIO_KEY"].map(GRUPO_MEDIO).fillna("Sin información")

    # Log de cobertura
    clasificados = df[df["MEDIO_KEY"] != "no_especificado"].shape[0]
    pct = clasificados / len(df) * 100 if len(df) > 0 else 0
    print(f"  Registros totales: {total_registros:,} → con FAC_DEL válido: {len(df):,}")
    print(f"  Clasificados con medio identificado: {clasificados:,} ({pct:.1f}%)")

    df["ANIO"] = año
    return df[["ANIO", "TIPO_DELITO", "MEDIO_COMISION", "MEDIO_KEY", "FAC_DEL_N"]]


# ── Consolidación y guardado ───────────────────────────────────────────────────
def main():
    zips = detectar_zips()
    if not zips:
        print(f"⚠ No se encontraron ZIPs en: {ZIP_DIR}")
        return

    print(f"ZIPs encontrados (2011 excluido por estructura incompatible):")
    print(f"  Años a procesar: {sorted(zips.keys())}")
    print("-" * 60)

    frames = []
    for año, zip_path in sorted(zips.items()):
        df_año = procesar_año(año, zip_path)
        if df_año is not None:
            frames.append(df_año)

    if not frames:
        print("No se extrajeron datos.")
        return

    print("\n" + "-" * 60)
    print("Consolidando datos históricos...")
    panel = pd.concat(frames, ignore_index=True)

    # ── Filtros de relevancia telecom ─────────────────────────────────────────
    medios_telecom = {
        "telefono_llamada",
        "telefono_mensaje",
        "telefono",
        "internet",
    }

    # Delitos donde el medio telecom es metodológicamente relevante
    # Secuestro REMOVIDO: la ENVIPE no captura medio de comisión de la misma
    # forma para secuestro y el IFT/CRT no lo incluye en estadísticas de delitos
    # por telecomunicaciones.
    delitos_relevantes = {
        "07",   # Fraude bancario
        "08",   # Fraude al consumidor
        "09",   # Extorsión
        "10",   # Amenazas
        "13",   # Hostigamiento / abuso sexual
    }

    panel_bpcod = panel["TIPO_DELITO"].map({v: k for k, v in BPCOD_LABELS.items()})
    mask = (
        panel["MEDIO_KEY"].isin(medios_telecom) &
        panel_bpcod.isin(delitos_relevantes)
    )

    # Log de descarte
    total_panel = len(panel)
    descartados = total_panel - mask.sum()
    print(f"Registros totales consolidados: {total_panel:,}")
    print(f"Registros fuera de scope (no telecom / delito no relevante): {descartados:,}")
    print(f"Registros en scope: {mask.sum():,}")

    panel_filtrado = panel[mask].copy()

    # ── Agregación ───────────────────────────────────────────────────────────
    agrupado = (
        panel_filtrado
        .groupby(["ANIO", "TIPO_DELITO", "MEDIO_COMISION"])
        .agg(
            ESTIMACION_POBLACIONAL=("FAC_DEL_N", "sum"),
            REGISTROS_MUESTRA=("FAC_DEL_N", "count"),
        )
        .reset_index()
    )

    # Porcentaje dentro de cada combinación Año × Delito
    totales = (
        agrupado.groupby(["ANIO", "TIPO_DELITO"])["ESTIMACION_POBLACIONAL"]
        .sum()
        .reset_index()
        .rename(columns={"ESTIMACION_POBLACIONAL": "TOTAL_GRUPO"})
    )
    agrupado = agrupado.merge(totales, on=["ANIO", "TIPO_DELITO"])
    agrupado["PORCENTAJE"] = (
        agrupado["ESTIMACION_POBLACIONAL"] / agrupado["TOTAL_GRUPO"] * 100
    ).round(2)
    agrupado.drop(columns=["TOTAL_GRUPO"], inplace=True)

    agrupado.sort_values(
        ["ANIO", "TIPO_DELITO", "ESTIMACION_POBLACIONAL"],
        ascending=[True, True, False],
        inplace=True,
    )
    agrupado["ESTIMACION_POBLACIONAL"] = (
        agrupado["ESTIMACION_POBLACIONAL"].round(0).astype(int)
    )
    agrupado["REGISTROS_MUESTRA"] = agrupado["REGISTROS_MUESTRA"].astype(int)

    # ── Guardar ───────────────────────────────────────────────────────────────
    out_file = OUT_RES_DIR / "ENVIPE_DELITO_MEDIO_HISTORICO.csv"
    agrupado.to_csv(out_file, index=False, encoding="utf-8-sig")

    print("\n" + "=" * 60)
    print("PROCESO TERMINADO CON ÉXITO")
    print("=" * 60)
    print(f"Archivo: {out_file.resolve()}")
    print(f"Registros exportados: {len(agrupado):,}")
    print(f"Columnas: {list(agrupado.columns)}")
    print()
    print("Nota metodológica:")
    print("  - 2011 excluido: TMod_Vic sin BP4_1 ni FAC_DEL (estructura incompatible).")
    print("  - BP5_1=2 (extorsión laboral) correctamente excluido de medios telecom.")
    print("  - 2025: desagregación telefónica vía BP5_1A_1/A_2.")
    print("  - Secuestro excluido del análisis telecom.")

if __name__ == "__main__":
    main()