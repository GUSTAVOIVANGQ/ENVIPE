"""
diagnostico_bp5_1.py
Corre este script en la carpeta donde tienes los ZIPs de ENVIPE.
Inspecciona BP5_1 y BP1_5 en el DBF del ZIP 2024 (datos 2023).

USO:
  python diagnostico_bp5_1.py
  python diagnostico_bp5_1.py --dir ruta/a/zips
"""
import argparse, re, tempfile, zipfile
from pathlib import Path
import pandas as pd
from dbfread import DBF

FAC_CANDIDATOS = ["FAC_DEL", "FACTOR", "FACTOR_EXP", "FAC_VIC", "POND"]

def year_from_zip(p):
    m = re.search(r"(20\d{2})", p.name)
    return int(m.group(1)) if m else None

def read_dbf_from_bytes(data):
    with tempfile.NamedTemporaryFile(suffix=".dbf", delete=False) as tmp:
        tmp.write(data); tmp_path = tmp.name
    try:
        records = list(DBF(tmp_path, encoding="latin-1", ignore_missing_memofile=True))
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    df = pd.DataFrame(records)
    df.columns = [c.upper() for c in df.columns]
    return df

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=".")
    args = parser.parse_args()
    zip_dir = Path(args.dir)

    # Busca el ZIP de año 2024
    zips_2024 = [p for p in zip_dir.glob("*.zip") if year_from_zip(p) == 2024]
    if not zips_2024:
        print("❌  No se encontró ningún ZIP con '2024' en el nombre")
        return

    zip_path = zips_2024[0]
    print(f"ZIP: {zip_path.name}  (datos año 2023)")

    with zipfile.ZipFile(zip_path) as zf:
        entry = next((n for n in zf.namelist()
                      if Path(n).name.lower() == "tmod_vic.dbf"), None)
        if not entry:
            print("❌  TMod_Vic.dbf no encontrado dentro del ZIP"); return
        print(f"DBF: {entry}")
        data = zf.read(entry)

    df = read_dbf_from_bytes(data)
    df["BPCOD"] = df["BPCOD"].astype(str).str.strip().str.zfill(2)
    fac_col = next((c for c in FAC_CANDIDATOS if c in df.columns), None)

    print(f"\nTotal registros en DBF : {len(df):,}")
    print(f"Registros extorsión (09): {(df['BPCOD']=='09').sum():,}")
    print(f"Factor de expansión    : {fac_col}")

    ext = df[df["BPCOD"] == "09"].copy()
    if fac_col:
        ext[fac_col] = pd.to_numeric(
            ext[fac_col].astype(str).str.strip(), errors="coerce").fillna(0)

    # ── Inspección BP5_1 ─────────────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print("Columna BP5_1:")
    if "BP5_1" in df.columns:
        raw = ext["BP5_1"].astype(str).str.strip()
        print(f"  Valores únicos encontrados (registros extorsión):")
        print(raw.value_counts(dropna=False).sort_index().to_string())

        if fac_col:
            total = ext[fac_col].sum()
            print(f"\n  Ponderado con {fac_col} (total extorsión = {round(total):,}):")
            for cod, desc in [("1","Telefónica"),("2","Laboral"),
                               ("3","Internet/correo"),("4","Calle"),
                               ("5","Negocio propio"),("6","Cobro de piso"),("7","Otro")]:
                val = ext.loc[raw == cod, fac_col].sum()
                pct = val/total*100 if total else 0
                print(f"    {cod} {desc:<30} {round(val):>12,}  ({pct:.2f}%)")
    else:
        print("  ⚠  BP5_1 NO existe en este DBF")

    # ── Inspección BP1_5 (la que usa el script para reconstruir modalidades) ─
    print(f"\n{'═'*60}")
    print("Columna BP1_5 (usada para reconstruir modalidades):")
    if "BP1_5" in df.columns:
        raw15 = ext["BP1_5"].astype(str).str.strip()
        print(f"  Valores únicos en registros de extorsión (BPCOD=09):")
        print(raw15.value_counts(dropna=False).sort_index().to_string())
        print(f"\n  Valores únicos en TODOS los registros del DBF:")
        print(df["BP1_5"].astype(str).str.strip()
              .value_counts(dropna=False).sort_index().to_string())
    else:
        print("  ⚠  BP1_5 NO existe en este DBF")

    # ── Muestra primeras filas de extorsión con columnas relevantes ──────────
    print(f"\n{'═'*60}")
    cols_show = [c for c in
                 ["BPCOD", fac_col, "BP5_1", "BP1_5", "BP1_5A_1"]
                 if c and c in df.columns]
    print(f"Primeras 15 filas de extorsión — columnas: {cols_show}")
    print(ext[cols_show].head(15).to_string())

if __name__ == "__main__":
    main()
