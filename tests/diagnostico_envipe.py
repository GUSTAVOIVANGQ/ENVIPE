"""
diagnostico_envipe.py
=====================
Inspecciona las columnas y valores clave de TMod_Vic.DBF
para cada año de la ENVIPE, sin extraer archivos a disco.

Ejecutar:
    python diagnostico_envipe.py

Requiere:
    pip install dbfread

El script imprime, para cada ZIP encontrado:
  - Columnas disponibles en TMod_Vic
  - Valores únicos de BPCOD (códigos de delito)
  - Valores únicos y conteos de BP4_1 / BP5_1 (si existen o sus variantes)
  - Presencia de FAC_DEL y sus variantes
"""

import os
import re
import sys
import zipfile
import tempfile
import shutil
from pathlib import Path

try:
    from dbfread import DBF
    import pandas as pd
except ImportError:
    print("ERROR: Instala las dependencias:")
    print("  pip install dbfread pandas")
    sys.exit(1)

# ── Ajusta esta ruta a donde tienes los ZIPs ─────────────────────
BASE_DIR = Path(__file__).parent
ZIP_DIR  = BASE_DIR / "conjunto_de_datos"
# ─────────────────────────────────────────────────────────────────

NOMBRES_TMOD = ["tmod_vic", "tmodvic", "mod_vic", "modvic"]

def detectar_zips(zip_dir: Path) -> dict:
    patron = re.compile(r'(?:envipe[_]?)(20)?(\d{2,4})', re.IGNORECASE)
    zips = {}
    for f in sorted(zip_dir.glob("*.zip")):
        m = patron.search(f.name)
        if not m:
            continue
        año_raw = ''.join(filter(str.isdigit, m.group(0).replace("envipe","").replace("_","")))
        if len(año_raw) == 2:
            año = 2000 + int(año_raw)
        elif len(año_raw) == 4:
            año = int(año_raw)
        else:
            continue
        if 2011 <= año <= 2030:
            zips[año] = f
    return zips

def leer_dbf_desde_zip(zip_path: Path, nombre_interno: str) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as z:
        with z.open(nombre_interno) as f:
            with tempfile.NamedTemporaryFile(suffix=".dbf", delete=False) as tmp:
                shutil.copyfileobj(f, tmp)
                tmp_path = tmp.name
    try:
        tabla = DBF(tmp_path, encoding="latin-1", load=True)
        df = pd.DataFrame(iter(tabla))
        df.columns = [c.upper().strip() for c in df.columns]
        return df
    finally:
        os.unlink(tmp_path)

def encontrar_tmod_vic(zip_path: Path) -> str | None:
    with zipfile.ZipFile(zip_path) as z:
        for nombre in z.namelist():
            nombre_base = nombre.split("/")[-1].lower()
            if nombre_base.endswith(".dbf") and any(n in nombre_base for n in NOMBRES_TMOD):
                return nombre
    return None

def diagnosticar_año(año: int, zip_path: Path):
    sep = "=" * 65
    print(f"\n{sep}")
    print(f"  AÑO {año}  —  {zip_path.name}")
    print(sep)

    nombre_interno = encontrar_tmod_vic(zip_path)
    if nombre_interno is None:
        print("  ✗ No se encontró TMod_Vic en este ZIP.")
        return

    print(f"  Archivo interno: {nombre_interno}")

    try:
        df = leer_dbf_desde_zip(zip_path, nombre_interno)
    except Exception as e:
        print(f"  ✗ Error al leer: {e}")
        return

    cols = list(df.columns)
    print(f"\n  Total registros : {len(df):,}")
    print(f"  Total columnas  : {len(cols)}")
    print(f"\n  COLUMNAS DISPONIBLES:")
    # Imprimir en grupos de 6
    for i in range(0, len(cols), 6):
        print("    " + "  ".join(f"{c:<12}" for c in cols[i:i+6]))

    # ── Columnas de interés ──────────────────────────────────────
    INTERES = {
        "BPCOD":    ["BPCOD", "COD_DEL", "TIPODEL"],
        "BP4_1":    ["BP4_1", "BP4A_1", "P4_1", "BP4"],
        "BP5_1":    ["BP5_1", "BP5A_1", "P5_1", "BP5"],
        "BP5_1A_1": ["BP5_1A_1", "BP51A1", "P5_1A1"],
        "BP5_1A_2": ["BP5_1A_2", "BP51A2", "P5_1A2"],
        "BP5_2_1":  ["BP5_2_1", "BP52_1", "BP5_2"],
        "BP5_3":    ["BP5_3", "P5_3"],
        "FAC_DEL":  ["FAC_DEL", "FACTOR_D", "FAC_DELI", "FACTORD", "FAC_ELE"],
    }

    print(f"\n  COLUMNAS CLAVE (presencia y valores únicos):")
    for etiqueta, candidatos in INTERES.items():
        encontrada = next((c for c in candidatos if c in df.columns), None)
        if encontrada:
            vals = df[encontrada].dropna().unique()
            vals_num = sorted([v for v in vals if str(v).strip() not in ("", "None")])[:20]
            print(f"    {etiqueta:12} → encontrada como '{encontrada}'")
            print(f"                   valores: {vals_num}")
        else:
            # Buscar columnas que empiecen con el prefijo como pista
            prefijo = etiqueta[:3].upper()
            similares = [c for c in cols if c.startswith(prefijo)]
            print(f"    {etiqueta:12} → NO ENCONTRADA  (columnas con '{prefijo}': {similares})")

    # ── Conteo de BPCOD ──────────────────────────────────────────
    col_bpcod = next((c for c in ["BPCOD", "COD_DEL", "TIPODEL"] if c in df.columns), None)
    if col_bpcod:
        print(f"\n  CONTEO por {col_bpcod} (código de delito):")
        conteo = df[col_bpcod].value_counts().sort_index()
        for cod, n in conteo.items():
            print(f"    {str(cod):>4}: {n:>8,}")

    # ── Muestra de BP5_1 (extorsión) si existe ──────────────────
    col_bp5 = next((c for c in ["BP5_1", "BP5A_1", "P5_1", "BP5"] if c in df.columns), None)
    if col_bp5 and col_bpcod:
        extorsion_mask = df[col_bpcod].astype(str).str.strip() == "9"
        df_ext = df[extorsion_mask]
        if len(df_ext) > 0:
            print(f"\n  VALORES de {col_bp5} para BPCOD=9 (extorsión):")
            conteo_bp5 = df_ext[col_bp5].value_counts().sort_index()
            for val, n in conteo_bp5.items():
                print(f"    {str(val):>4}: {n:>6,}")

    # ── Muestra de BP4_1 (fraude) si existe ─────────────────────
    col_bp4 = next((c for c in ["BP4_1", "BP4A_1", "P4_1", "BP4"] if c in df.columns), None)
    if col_bp4 and col_bpcod:
        fraude_mask = df[col_bpcod].astype(str).str.strip().isin(["7", "8"])
        df_frau = df[fraude_mask]
        if len(df_frau) > 0:
            print(f"\n  VALORES de {col_bp4} para BPCOD=7,8 (fraude):")
            conteo_bp4 = df_frau[col_bp4].value_counts().sort_index()
            for val, n in conteo_bp4.items():
                print(f"    {str(val):>4}: {n:>6,}")

    print()

def main():
    if not ZIP_DIR.exists():
        print(f"ERROR: No se encontró el directorio: {ZIP_DIR}")
        print("Ajusta la variable ZIP_DIR en el script.")
        sys.exit(1)

    zips = detectar_zips(ZIP_DIR)
    if not zips:
        print(f"No se encontraron ZIPs en: {ZIP_DIR}")
        sys.exit(1)

    print(f"Directorio: {ZIP_DIR}")
    print(f"ZIPs encontrados: {sorted(zips.keys())}")

    for año, zip_path in sorted(zips.items()):
        diagnosticar_año(año, zip_path)

    print("\n" + "=" * 65)
    print("DIAGNÓSTICO COMPLETO")
    print("=" * 65)
    print("Pega el output completo de este script para continuar.")

if __name__ == "__main__":
    main()
