"""
procesar_envipe_modalidad.py  v8  —  INTEGRACIÓN TOTAL 2023
===========================================================
Genera las modalidades de todos los años e integra proxies 
metodológicos para el año 2023, permitiendo un CSV unificado.
"""

import argparse
import io
import re
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
from dbfread import DBF

# ── Configuración ─────────────────────────────────────────────────────────────
DEFAULT_ZIP_DIR = Path(".")
OUTPUT_FILE     = Path("ENVIPE_DELITO_MODALIDAD.csv")
OUTPUT_EXT_2023 = Path("ENVIPE_EXTORSION_TIPO_2023.csv")

# ── Catálogos ────────────────────────────────────────────────────────────────
DELITOS = {
    "Fraude":         ["07", "08"],
    "Extorsion":      ["09"],
    "Amenazas":       ["10"],
    "Hostigamiento":  ["13"],
}

MODALIDADES = [
    ("Internet/medios electrónicos", "BP1_5A_1"),
    ("Llamada telefónica",           "BP1_5A_2"),
    ("Contacto presencial",          "BP1_5A_3"),
    ("Otro",                         "BP1_5A_4"),
]

EXTORSION_TIPOS_5_1 = {
    "1": "Telefónica", "2": "Laboral", "3": "Por internet/correo electrónico",
    "4": "En la calle", "5": "En negocio propio o familiar", "6": "Cobro de piso", "7": "Otro"
}

FAC_CANDIDATOS = ["FAC_DEL", "FACTOR", "FACTOR_EXP", "FAC_VIC", "POND"]

def year_from_zip(zip_path: Path) -> int | None:
    m4 = re.search(r"(20\d{2})", zip_path.name)
    if m4: return int(m4.group(1))
    m2 = re.search(r"envipe_?(\d{2})", zip_path.name, re.IGNORECASE)
    if m2: return 2000 + int(m2.group(1))
    return None

def find_tmod_entry(zf: zipfile.ZipFile) -> str | None:
    for name in zf.namelist():
        if Path(name).name.lower() == "tmod_vic.dbf":
            return name
    return None

def read_dbf_from_bytes(data: bytes) -> pd.DataFrame:
    with tempfile.NamedTemporaryFile(suffix=".dbf", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        records = list(DBF(tmp_path, encoding="latin-1", ignore_missing_memofile=True))
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    df = pd.DataFrame(records)
    df.columns = [c.upper() for c in df.columns]
    return df

def preparar_df(df: pd.DataFrame, year: int) -> tuple[pd.DataFrame, str | None]:
    if "BPCOD" not in df.columns: return df, None
    df["BPCOD"] = df["BPCOD"].astype(str).str.strip().str.zfill(2)

    fac_col = next((cand for cand in FAC_CANDIDATOS if cand in df.columns), None)
    if fac_col is None: return df, None
    df[fac_col] = pd.to_numeric(df[fac_col].astype(str).str.strip(), errors="coerce").fillna(0)

    # Reconstrucción de modalidades clásicas para años <= 2022
    if "BP1_5A_1" not in df.columns and year != 2023:
        old_col = next((c for c in ["BP1_5", "BP1_4", "BP1_6"] if c in df.columns), None)
        if old_col:
            df["BP1_5A_1"] = (df[old_col].astype(str).str.strip() == "1").astype(int)
            df["BP1_5A_2"] = (df[old_col].astype(str).str.strip() == "2").astype(int)
            df["BP1_5A_3"] = (df[old_col].astype(str).str.strip() == "3").astype(int)
            df["BP1_5A_4"] = df[old_col].astype(str).str.strip().isin(["4", "5", "6", "7", "8", "9"]).astype(int)

    # Inicializar a 0 para que no fallen los cálculos estándar
    for _, var in MODALIDADES:
        if var in df.columns:
            df[var] = pd.to_numeric(df[var], errors="coerce").fillna(0)
        else:
            df[var] = 0

    return df, fac_col

# ── Calcula delitos × modalidad para un año ───────────────────────────────────
def calcular_year(df: pd.DataFrame, year: int, fac_col: str) -> list[dict]:
    rows = []
    
    # ── LÓGICA ESPECIAL PARA 2023 (MAPEO DE SECCIONES A 4 CATEGORÍAS) ──
    if year == 2023:
        for delito, bpcods in DELITOS.items():
            subset = df[df["BPCOD"].isin(bpcods)].copy()
            if subset.empty: continue
            
            total = subset[fac_col].sum()
            mod_sums = {
                "Internet/medios electrónicos": 0, "Llamada telefónica": 0, 
                "Contacto presencial": 0, "Otro": 0
            }

            if delito == "Extorsion" and "BP5_1" in df.columns:
                subset["BP5_1"] = pd.to_numeric(subset["BP5_1"], errors="coerce").fillna(0).astype(int).astype(str)
                mod_sums["Llamada telefónica"] = subset.loc[subset["BP5_1"] == "1", fac_col].sum()
                mod_sums["Internet/medios electrónicos"] = subset.loc[subset["BP5_1"] == "3", fac_col].sum()
                mod_sums["Contacto presencial"] = subset.loc[subset["BP5_1"].isin(["2","4","5","6"]), fac_col].sum()
                mod_sums["Otro"] = subset.loc[~subset["BP5_1"].isin(["1","2","3","4","5","6"]), fac_col].sum()

            elif delito == "Fraude" and "BP4_1" in df.columns:
                subset["BP4_1"] = pd.to_numeric(subset["BP4_1"], errors="coerce").fillna(0).astype(int).astype(str)
                mod_sums["Internet/medios electrónicos"] = subset.loc[subset["BP4_1"].isin(["4", "5"]), fac_col].sum()
                mod_sums["Contacto presencial"] = subset.loc[subset["BP4_1"].isin(["1", "2", "3"]), fac_col].sum()
                mod_sums["Otro"] = subset.loc[~subset["BP4_1"].isin(["1","2","3","4","5"]), fac_col].sum()

            elif delito == "Hostigamiento":
                mod_sums["Contacto presencial"] = total  # Mayoría física/presencial
            else:
                mod_sums["Otro"] = total  # Amenazas u otros

            for mod_nombre in [m[0] for m in MODALIDADES]:
                abs_val = mod_sums[mod_nombre]
                rows.append({
                    "Anio": year, "Delito": delito, "Modalidad": mod_nombre,
                    "Delitos_total": round(total), "Absolutos": round(abs_val),
                    "Porcentaje": round((abs_val / total * 100) if total > 0 else 0, 6)
                })
        return rows

    # ── LÓGICA ESTÁNDAR PARA EL RESTO DE LOS AÑOS ──
    for delito, bpcods in DELITOS.items():
        subset = df[df["BPCOD"].isin(bpcods)]
        if subset.empty: continue
        total = subset[fac_col].sum()

        for mod_nombre, var in MODALIDADES:
            abs_val = subset.loc[subset[var] == 1, fac_col].sum()
            rows.append({
                "Anio": year, "Delito": delito, "Modalidad": mod_nombre,
                "Delitos_total": round(total), "Absolutos": round(abs_val),
                "Porcentaje": round((abs_val / total * 100) if total > 0 else 0, 6)
            })
    return rows

# ── Extorsión Desglosada para 2023 (Sección V) ──
def calcular_extorsion_tipo_bp5_1(df: pd.DataFrame, year: int, fac_col: str, output_path: Path) -> list[dict]:
    VAR = "BP5_1"
    if VAR not in df.columns: return []

    ext = df[df["BPCOD"] == "09"].copy()
    if ext.empty: return []

    ext[VAR] = pd.to_numeric(ext[VAR].astype(str).str.strip(), errors="coerce").apply(lambda x: str(int(x)) if pd.notna(x) else "")
    ext[fac_col] = pd.to_numeric(ext[fac_col].astype(str).str.strip(), errors="coerce").fillna(0)

    total = ext[fac_col].sum()
    rows = []
    if total > 0:
        for cod, nombre in EXTORSION_TIPOS_5_1.items():
            abs_val = ext.loc[ext[VAR] == cod, fac_col].sum()
            rows.append({
                "Anio": year, "Delito": "Extorsion", "Tipo_BP5_1_cod": cod,
                "Tipo_BP5_1_desc": nombre, "Delitos_total": round(total),
                "Delitos_tipo": round(abs_val), "Porcentaje": round((abs_val / total * 100), 6)
            })
        pd.DataFrame(rows).to_csv(output_path, index=False, encoding="utf-8-sig")
    return rows

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=str(DEFAULT_ZIP_DIR))
    parser.add_argument("--out", default=str(OUTPUT_FILE))
    parser.add_argument("--out-ext2023", default=str(OUTPUT_EXT_2023))
    parser.add_argument("--start-year", type=int, default=2010)
    args = parser.parse_args()

    zip_dir = Path(args.dir)
    zips = sorted([p for p in zip_dir.glob("*.zip") if year_from_zip(p) is not None and (year_from_zip(p) - 1) >= args.start_year], key=lambda p: year_from_zip(p))

    all_rows = []
    
    for zip_path in zips:
        year_zip = year_from_zip(zip_path)
        year_data = year_zip - 1
        print(f"Procesando {year_data} desde {zip_path.name}...")

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                entry = find_tmod_entry(zf)
                if not entry: continue
                data = zf.read(entry)
            df_raw = read_dbf_from_bytes(data)
        except Exception as e:
            print(f"Error en {zip_path.name}: {e}")
            continue

        df, fac_col = preparar_df(df_raw, year_data)
        if fac_col is None: continue

        rows = calcular_year(df, year_data, fac_col)
        all_rows.extend(rows)

        if year_zip == 2024 and "BP5_1" in df.columns:
            calcular_extorsion_tipo_bp5_1(df, year_data, fac_col, Path(args.out_ext2023))

    if all_rows:
        df_out = pd.DataFrame(all_rows).sort_values(["Anio", "Delito", "Modalidad"])
        df_out.to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"\n¡Listo! Datos guardados en {args.out}")

if __name__ == "__main__":
    main()