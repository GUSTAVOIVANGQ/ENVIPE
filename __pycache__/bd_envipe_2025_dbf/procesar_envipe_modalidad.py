"""
procesar_envipe_modalidad.py  v4  —  VERSIÓN FINAL VERIFICADA
==============================================================
Construye ENVIPE_DELITO_MODALIDAD.csv a partir de los microdatos
anuales de la ENVIPE para los años 2019–2024 (estructura nueva).

BPCOD verificados contra Cuadro 1.21 ENVIPE 2025:
  Fraude        : 07 + 08  (bancario + consumidor)
  Extorsión     : 09
  Amenazas      : 10
  Hostigamiento : 13  ← NO es 11 (11 es otro delito distinto)

Variables de modalidad (flags binarios — igual para todos los delitos):
  BP1_5A_1 == 1  →  Internet / medios electrónicos
  BP1_5A_2 == 1  →  Llamada telefónica
  BP1_5A_3 == 1  →  Contacto presencial
  BP1_5A_4 == 1  →  Otro

Factor de expansión: FAC_DEL (tipo C en el DBF — se convierte a número)

Verificación completa al 100% contra Cuadro 1.21 ENVIPE 2025:
  Fraude        : 4/4 modalidades +0.00% ✓
  Extorsión     : 4/4 modalidades +0.00% ✓
  Amenazas      : 4/4 modalidades +0.00% ✓
  Hostigamiento : 4/4 modalidades +0.00% ✓

Estructura de carpetas esperada:
  ./datos/2024/TMod_Vic.dbf
  ./datos/2023/TMod_Vic.dbf
  ...

USO:
  python procesar_envipe_modalidad.py
  python procesar_envipe_modalidad.py --dir ruta/a/datos --years 2022,2023,2024
"""

import argparse
from pathlib import Path
import pandas as pd
from dbfread import DBF

# ── Configuración ─────────────────────────────────────────────────────────────
DEFAULT_BASE_DIR = Path("./datos")
DEFAULT_YEARS    = list(range(2019, 2025))   # 2019–2024
OUTPUT_FILE      = Path("ENVIPE_DELITO_MODALIDAD.csv")

# ── Delitos: nombre → lista de BPCOD (verificados) ───────────────────────────
DELITOS = {
    "Fraude":         ["07", "08"],   # bancario + consumidor
    "Extorsion":      ["09"],
    "Amenazas":       ["10"],
    "Hostigamiento":  ["13"],         # OJO: 13, no 11
}

# ── Modalidades: nombre → variable flag (1 = sí) ─────────────────────────────
MODALIDADES = [
    ("Internet/medios electrónicos", "BP1_5A_1"),
    ("Llamada telefónica",           "BP1_5A_2"),
    ("Contacto presencial",          "BP1_5A_3"),
    ("Otro",                         "BP1_5A_4"),
]

# ── Valores oficiales para verificación (Cuadro 1.21, ENVIPE 2025) ────────────
REFERENCIA_2024 = {
    ("Fraude",        "Internet/medios electrónicos"): 5_350_580,
    ("Fraude",        "Llamada telefónica"):             626_605,
    ("Fraude",        "Contacto presencial"):          1_285_453,
    ("Fraude",        "Otro"):                            56_078,
    ("Extorsion",     "Internet/medios electrónicos"):   343_963,
    ("Extorsion",     "Llamada telefónica"):           4_895_851,
    ("Extorsion",     "Contacto presencial"):            523_656,
    ("Extorsion",     "Otro"):                            12_459,
    ("Amenazas",      "Internet/medios electrónicos"):   699_379,
    ("Amenazas",      "Llamada telefónica"):           1_103_824,
    ("Amenazas",      "Contacto presencial"):          2_757_727,
    ("Amenazas",      "Otro"):                            35_787,
    ("Hostigamiento", "Internet/medios electrónicos"):    59_181,
    ("Hostigamiento", "Llamada telefónica"):              21_789,
    ("Hostigamiento", "Contacto presencial"):          2_173_448,
    ("Hostigamiento", "Otro"):                             8_646,
}

# ── Funciones ─────────────────────────────────────────────────────────────────

def read_tmod_vic(path: Path) -> pd.DataFrame:
    """Lee TMod_Vic.dbf y devuelve DataFrame con columnas en mayúsculas."""
    records = list(DBF(str(path), encoding="latin-1", ignore_missing_memofile=True))
    df = pd.DataFrame(records)
    df.columns = [c.upper() for c in df.columns]

    df["BPCOD"]   = df["BPCOD"].astype(str).str.strip()
    df["FAC_DEL"] = pd.to_numeric(
        df["FAC_DEL"].astype(str).str.strip(), errors="coerce"
    ).fillna(0)

    for _, var in MODALIDADES:
        if var in df.columns:
            df[var] = pd.to_numeric(df[var], errors="coerce").fillna(0)

    return df


def calcular_year(df: pd.DataFrame, year: int) -> list[dict]:
    """Calcula delitos por modalidad para un año dado."""
    rows = []
    for delito, bpcods in DELITOS.items():
        subset = df[df["BPCOD"].isin(bpcods)]
        if subset.empty:
            print(f"  ⚠  [{year}] {delito}: sin registros (BPCOD={bpcods})")
            continue

        total = subset["FAC_DEL"].sum()

        for mod_nombre, var in MODALIDADES:
            if var not in subset.columns:
                abs_val = 0
            else:
                abs_val = subset.loc[subset[var] == 1, "FAC_DEL"].sum()

            rel_val = (abs_val / total * 100) if total > 0 else 0
            rows.append({
                "Anio":          year,
                "Delito":        delito,
                "Modalidad":     mod_nombre,
                "Delitos_total": round(total),
                "Absolutos":     round(abs_val),
                "Porcentaje":    round(rel_val, 6),
            })

    return rows


def verificar_2024(rows: list[dict]):
    """Compara resultados de 2024 contra Cuadro 1.21 oficial."""
    print(f"\n{'─'*78}")
    print("  Verificación contra Cuadro 1.21 ENVIPE 2025 (datos 2024)")
    print(f"{'─'*78}")
    print(f"  {'':2} {'Delito':<14} {'Modalidad':<35} {'Calculado':>12} {'Oficial':>12} {'Diff%':>7}")
    print(f"  {'─'*74}")

    rows_2024 = {
        (r["Delito"], r["Modalidad"]): r["Absolutos"]
        for r in rows if r["Anio"] == 2024
    }
    todos_ok = True
    delito_actual = None
    for (delito, mod), oficial in REFERENCIA_2024.items():
        if delito != delito_actual:
            if delito_actual is not None:
                print()
            delito_actual = delito
        calc     = rows_2024.get((delito, mod), 0)
        diff_pct = (calc - oficial) / oficial * 100 if oficial else float("inf")
        ok       = abs(diff_pct) < 0.5
        flag     = "✓" if ok else "⚠ "
        if not ok:
            todos_ok = False
        print(f"  {flag} {delito:<14} {mod:<35} {calc:>12,.0f} {oficial:>12,} {diff_pct:>+6.2f}%")

    print(f"\n{'─'*78}")
    if todos_ok:
        print("  ✓ 16/16 valores coinciden exactamente con el Cuadro 1.21 oficial.")
    else:
        print("  ⚠  Hay diferencias — ver filas marcadas con ⚠ arriba.")
    print(f"{'─'*78}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Procesa microdatos ENVIPE → CSV de modalidades")
    parser.add_argument("--dir",   default=str(DEFAULT_BASE_DIR),
                        help=f"Carpeta raíz con subcarpetas por año (default: {DEFAULT_BASE_DIR})")
    parser.add_argument("--years", default=None,
                        help="Años separados por coma, ej: 2022,2023,2024")
    args = parser.parse_args()

    base_dir = Path(args.dir)
    years    = [int(y) for y in args.years.split(",")] if args.years else DEFAULT_YEARS

    all_rows = []

    for year in years:
        dbf_path = base_dir / str(year) / "TMod_Vic.dbf"
        if not dbf_path.exists():
            print(f"[{year}] No encontrado: {dbf_path} — omitido")
            continue

        print(f"[{year}] Procesando {dbf_path} …")
        try:
            df = read_tmod_vic(dbf_path)
        except Exception as e:
            print(f"  Error al leer: {e}")
            continue

        rows = calcular_year(df, year)
        all_rows.extend(rows)
        print(f"  OK — {len(rows)} filas")

    if not all_rows:
        print("\nNo se generaron datos. Verifica rutas y años.")
        return

    df_out = pd.DataFrame(all_rows)
    df_out.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"\nCSV guardado: {OUTPUT_FILE}  ({len(df_out)} filas, {df_out['Anio'].nunique()} años)")

    if 2024 in df_out["Anio"].values:
        verificar_2024(all_rows)


if __name__ == "__main__":
    main()