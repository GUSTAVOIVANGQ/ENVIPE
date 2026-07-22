"""
procesar_envipe_modalidad.py  v12  —  SERIE HISTÓRICA COMPLETA
==================================================================
Genera ENVIPE_DELITO_MODALIDAD.csv con el desglose NATIVO de cada
variable de tipo/medio por delito y año, aplicando las preguntas
específicas (BP4_1, BP5_1, etc.) a TODOS los años donde existan.

CORRECCIONES v12 vs v11:
─────────────────────────────────────────────────────────────────
1. BPCOD histórico (datos ≤ 2011, archivos ZIP ≤ 2012):
   El cuestionario usaba numeración distinta de delitos:
     OLD  06 = Fraude bancario  (clonación de tarjeta)
     OLD  07 = Fraude consumidor (producto/servicio no entregado)
     OLD  08 = Extorsión
     OLD  09 = Amenazas
     OLD  12 = Hostigamiento/manoseo
   A partir de datos 2012 (ZIP 2013+) se adopta la numeración actual:
     NEW  07 = Fraude bancario
     NEW  08 = Fraude consumidor
     NEW  09 = Extorsión
     NEW  10 = Amenazas
     NEW  13 = Hostigamiento

2. Catálogo BP4_1 para fraude en datos ≤ 2011 (edición histórica):
   La pregunta 4.1 se aplicaba SOLO a fraude consumidor (BPCOD=07 OLD).
   Fraude bancario (BPCOD=06 OLD) no tenía pregunta modal → se omite.
   Catálogo OLD BP4_1:
     1 = Cheque falso o robado
     2 = Pago por servicio/producto no entregado (al consumidor)
     3 = Tarjeta de débito o crédito
     4 = Por internet / correo electrónico
     5 = Otro
     9 = No especificado / sin respuesta
   (Nota: en v11 los valores 1 y 2 estaban intercambiados y faltaba
    la separación entre fraude bancario y consumidor.)

3. BP5_1 extorsión en datos 2010-2011:
   En v11, el programa buscaba BPCOD=09 (amenazas en la nomenclatura
   OLD), por lo que BP5_1 aparecía vacía. Con el mapeo OLD correcto
   (BPCOD=08), BP5_1 sí contiene datos y ya NO se requiere ningún
   tratamiento especial para esos años.
"""

import argparse
import re
import struct
import tempfile
import zipfile
from pathlib import Path

import pandas as pd

# ── Configuración ──────────────────────────────────────────────────────────────
DEFAULT_ZIP_DIR = Path("conjunto_de_datos")
OUTPUT_FILE     = Path("ENVIPE_DELITO_MODALIDAD.csv")

FAC_CANDIDATOS = ["FAC_DEL", "FACTOR", "FACTOR_EXP", "FAC_VIC", "POND"]

# ── Año de corte para el cambio de numeración BPCOD ──────────────────────────
# Los archivos ZIP con nombre hasta 2012 inclusive (datos hasta 2011) usan
# la numeración OLD. A partir del ZIP 2013 (datos 2012) se usa la numeración NEW.
BPCOD_BREAK_DATA_YEAR = 2012   # primer año de datos con numeración NEW

# ── BPCOD: Mapeo histórico (datos ≤ 2011) ────────────────────────────────────
# "Fraude" aquí es SOLO fraude consumidor (06=bancario no tiene modal).
DELITOS_OLD = {
    "Fraude":        ["07"],       # fraude consumidor (producto/servicio)
    "FraudeBancario":["06"],       # fraude bancario — sin modal disponible
    "Extorsion":     ["08"],
    "Amenazas":      ["09"],
    "Hostigamiento": ["12"],
}

# ── BPCOD: Mapeo actual (datos ≥ 2012) ───────────────────────────────────────
DELITOS_NEW = {
    "Fraude":        ["07", "08"],
    "Extorsion":     ["09"],
    "Amenazas":      ["10"],
    "Hostigamiento": ["13"],
}

# ── Catálogos de modalidad ────────────────────────────────────────────────────

# EXTORSIÓN: BP5_1  (estable en toda la serie)
BP5_1_EXTORSION = {
    "1": "Telefónica",
    "2": "Laboral",
    "3": "Por internet / correo electrónico",
    "4": "En la calle",
    "5": "En negocio propio o familiar",
    "6": "Cobro de piso",
    "7": "Otro",
    "9": "No especificado / sin respuesta",
}

# FRAUDE BP4_1  — datos ≤ 2011 (OLD, aplicado solo a fraude consumidor BPCOD=07)
BP4_1_FRAUDE_OLD = {
    "1": "Cheque falso o robado",
    "2": "Pago por servicio/producto no entregado (al consumidor)",
    "3": "Tarjeta de débito o crédito",
    "4": "Por internet / correo electrónico",
    "5": "Otro",
    "9": "No especificado / sin respuesta",
}

# FRAUDE BP4_1  — datos 2012–2022 (NEW, antes de rediseño 2023)
BP4_1_FRAUDE_HISTORICO = {
    "1": "Pago por un servicio/producto no entregado",
    "2": "Cheque falso o sin fondos",
    "3": "Dinero falso",
    "4": "Tarjeta de débito o crédito (Bancario)",
    "5": "Por internet/correo electrónico",
    "6": "Otro",
    "9": "No especificado / sin respuesta",
}

# FRAUDE BP4_1  — datos 2023+ (rediseño del cuestionario)
BP4_1_FRAUDE_2023 = {
    "1": "Bancario (tarjeta / cuenta)",
    "2": "Dinero falso",
    "3": "Servicios o mercancías no recibidas",
    "4": "Vendedor a domicilio / por internet",
    "5": "Otro fraude electrónico / telefonía",
    "6": "Compraventa de bien o servicio",
    "9": "Otro",
}

# AMENAZAS / HOSTIGAMIENTO — datos ≥ 2023 (nuevas variables detalladas)
BP1_5_AMENAZAS_2023 = {
    "1": "Presencial (persona conocida)",
    "2": "Presencial (persona desconocida)",
    "3": "Llamada telefónica",
    "4": "Internet / correo electrónico / redes sociales",
    "5": "Escrito (carta, recado)",
    "6": "En el trabajo o escuela",
    "7": "En el vecindario / colonia",
    "8": "Por parte de familiar o amigo",
    "9": "Otro",
}

BP7_1_HOSTIGAMIENTO_2023 = {
    "1": "Internet / redes sociales / correo electrónico",
    "2": "Presencial (persona conocida)",
    "3": "En la calle (persona desconocida)",
    "4": "En el trabajo / escuela",
    "9": "Otro",
}

# ── Lectura de Archivos ────────────────────────────────────────────────────────
def year_from_zip(zip_path: Path) -> int | None:
    m4 = re.search(r"(20\d{2})", zip_path.name)
    if m4:
        return int(m4.group(1))
    m2 = re.search(r"envipe_?(\d{2})", zip_path.name, re.IGNORECASE)
    if m2:
        return 2000 + int(m2.group(1))
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
        return _parse_dbf(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

def _parse_dbf(path: str) -> pd.DataFrame:
    with open(path, "rb") as f:
        header = f.read(32)
        num_records = struct.unpack("<I", header[4:8])[0]
        header_size = struct.unpack("<H", header[8:10])[0]
        record_size = struct.unpack("<H", header[10:12])[0]

        fields = []
        while True:
            fd = f.read(32)
            if not fd or fd[0] == 0x0D or len(fd) < 32:
                break
            name   = fd[0:11].rstrip(b"\x00").decode("latin-1")
            length = fd[16]
            fields.append((name, length))

        f.seek(header_size)
        records = []
        for _ in range(num_records):
            rec = f.read(record_size)
            if not rec or rec[0:1] == b"\x1a":
                break
            if rec[0:1] == b"*":
                continue
            row, pos = {}, 1
            for name, length in fields:
                row[name] = rec[pos : pos + length].decode("latin-1").strip()
                pos += length
            records.append(row)

    df = pd.DataFrame(records)
    df.columns = [c.upper() for c in df.columns]
    return df

def preparar_df(df: pd.DataFrame, year: int):
    if "BPCOD" not in df.columns:
        return df, None

    df = df.copy()
    df["BPCOD"] = df["BPCOD"].astype(str).str.strip().str.zfill(2)

    fac_col = next((c for c in FAC_CANDIDATOS if c in df.columns), None)
    if fac_col is None:
        return df, None
    df[fac_col] = pd.to_numeric(
        df[fac_col].astype(str).str.strip(), errors="coerce"
    ).fillna(0)

    return df, fac_col

# ── Extracción Dinámica ───────────────────────────────────────────────────────
def calcular_year(df: pd.DataFrame, year: int, fac_col: str) -> list[dict]:
    """
    Selecciona el mapeo BPCOD correcto según el año de datos y llama
    al extractor de modalidad para cada delito relevante.
    """
    rows = []
    usar_old = (year < BPCOD_BREAK_DATA_YEAR)

    if usar_old:
        # ── Edición histórica (datos ≤ 2011) ──────────────────────────
        # Fraude consumidor: solo BPCOD=07 (bancario=06 no tiene modal)
        fra_cons = df[df["BPCOD"] == "07"].copy()
        if not fra_cons.empty:
            total = float(fra_cons[fac_col].sum())
            rows.extend(_extraer_con_catalogo(
                fra_cons, "Fraude", "BP4_1", BP4_1_FRAUDE_OLD,
                fac_col, total, year,
                nota="solo fraude consumidor (BPCOD=07 OLD)"
            ))

        # Extorsión: BPCOD=08 en nomenclatura OLD
        ext = df[df["BPCOD"] == "08"].copy()
        if not ext.empty:
            total = float(ext[fac_col].sum())
            rows.extend(_extraer_con_catalogo(
                ext, "Extorsion", "BP5_1", BP5_1_EXTORSION,
                fac_col, total, year
            ))

        # Amenazas: BPCOD=09 en nomenclatura OLD (sin modal específico)
        # No se genera desglose de modalidad para amenazas en datos OLD
        # porque no existía la pregunta de canal; se registra solo el total.
        ame = df[df["BPCOD"] == "09"].copy()
        if not ame.empty:
            total = float(ame[fac_col].sum())
            rows.append({
                "Anio":            year,
                "Delito":          "Amenazas",
                "Variable_fuente": "N/A",
                "Tipo_cod":        "N/A",
                "Tipo_desc":       "Sin desglose (pregunta no captada antes de 2012)",
                "Delitos_total":   round(total),
                "Absolutos":       round(total),
                "Porcentaje":      100.0,
            })

        # Hostigamiento: BPCOD=12 en nomenclatura OLD (sin modal específico)
        hos = df[df["BPCOD"] == "12"].copy()
        if not hos.empty:
            total = float(hos[fac_col].sum())
            rows.append({
                "Anio":            year,
                "Delito":          "Hostigamiento",
                "Variable_fuente": "N/A",
                "Tipo_cod":        "N/A",
                "Tipo_desc":       "Sin desglose (pregunta no captada antes de 2012)",
                "Delitos_total":   round(total),
                "Absolutos":       round(total),
                "Porcentaje":      100.0,
            })

    else:
        # ── Edición actual (datos ≥ 2012) ─────────────────────────────
        for delito, bpcods in DELITOS_NEW.items():
            subset = df[df["BPCOD"].isin(bpcods)].copy()
            if subset.empty:
                continue
            total = float(subset[fac_col].sum())
            rows.extend(_extraer_modalidad(subset, delito, fac_col, total, year))

    return rows


def _extraer_modalidad(subset: pd.DataFrame, delito: str, fac_col: str,
                       total: float, year: int) -> list[dict]:
    """Determina variable y catálogo para edición actual (datos ≥ 2012)."""
    if delito == "Extorsion":
        var, catalogo = "BP5_1", BP5_1_EXTORSION

    elif delito == "Fraude":
        var = "BP4_1"
        catalogo = BP4_1_FRAUDE_2023 if year >= 2023 else BP4_1_FRAUDE_HISTORICO

    elif delito == "Amenazas":
        if year >= 2023:
            var, catalogo = "BP1_5", BP1_5_AMENAZAS_2023
        else:
            # 2012–2022: no existía pregunta de canal para amenazas → total sin desglose
            return [{
                "Anio":            year,
                "Delito":          "Amenazas",
                "Variable_fuente": "N/A",
                "Tipo_cod":        "N/A",
                "Tipo_desc":       "Sin desglose (pregunta no captada antes de 2023)",
                "Delitos_total":   round(total),
                "Absolutos":       round(total),
                "Porcentaje":      100.0,
            }]

    elif delito == "Hostigamiento":
        if year >= 2023:
            var, catalogo = "BP7_1", BP7_1_HOSTIGAMIENTO_2023
        else:
            return [{
                "Anio":            year,
                "Delito":          "Hostigamiento",
                "Variable_fuente": "N/A",
                "Tipo_cod":        "N/A",
                "Tipo_desc":       "Sin desglose (pregunta no captada antes de 2023)",
                "Delitos_total":   round(total),
                "Absolutos":       round(total),
                "Porcentaje":      100.0,
            }]
    else:
        return []

    return _extraer_con_catalogo(subset, delito, var, catalogo, fac_col, total, year)


def _extraer_con_catalogo(subset: pd.DataFrame, delito: str, var: str,
                           catalogo: dict, fac_col: str, total: float,
                           year: int, nota: str = "") -> list[dict]:
    """
    Extrae la distribución de una variable según el catálogo dado.
    Si la variable no existe en el DBF, devuelve lista vacía (no hay datos).
    """
    if var not in subset.columns:
        return []

    subset = subset.copy()
    subset["_cod_"] = (
        pd.to_numeric(subset[var].astype(str).str.strip(), errors="coerce")
        .apply(lambda x: str(int(x)) if pd.notna(x) else "")
    )

    results = []
    for cod, desc in catalogo.items():
        abs_val = float(subset.loc[subset["_cod_"] == cod, fac_col].sum())
        results.append({
            "Anio":            year,
            "Delito":          delito,
            "Variable_fuente": var,
            "Tipo_cod":        cod,
            "Tipo_desc":       desc,
            "Delitos_total":   round(total),
            "Absolutos":       round(abs_val),
            "Porcentaje":      round((abs_val / total * 100) if total > 0 else 0, 6),
        })
    return results


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir",        default=str(DEFAULT_ZIP_DIR))
    parser.add_argument("--out",        default=str(OUTPUT_FILE))
    parser.add_argument("--start-year", type=int, default=2010)
    args = parser.parse_args()

    zip_dir = Path(args.dir)
    zips = sorted(
        [
            p for p in zip_dir.glob("*.zip")
            if year_from_zip(p) is not None
            and (year_from_zip(p) - 1) >= args.start_year
        ],
        key=lambda p: year_from_zip(p),
    )

    if not zips:
        print(f"No se encontraron ZIPs de ENVIPE en '{zip_dir}'.")
        return

    all_rows = []

    for zip_path in zips:
        year_zip  = year_from_zip(zip_path)
        year_data = year_zip - 1   # el ZIP de N contiene datos del año N-1
        print(f"Procesando datos de {year_data} desde {zip_path.name} ...")

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                entry = find_tmod_entry(zf)
                if not entry:
                    print(f"  [!] No se encontró TMod_Vic.dbf en {zip_path.name}")
                    continue
                data = zf.read(entry)
            df_raw = read_dbf_from_bytes(data)
        except Exception as e:
            print(f"  [X] Error en {zip_path.name}: {e}")
            continue

        df, fac_col = preparar_df(df_raw, year_data)
        if fac_col is None:
            print(f"  [!] No se encontró columna de factor en {zip_path.name}")
            continue

        modo = "OLD (BPCOD histórico <=2011)" if year_data < BPCOD_BREAK_DATA_YEAR else "NEW (BPCOD actual)"
        rows = calcular_year(df, year_data, fac_col)
        all_rows.extend(rows)
        print(f"  [OK] {len(rows)} filas generadas  [{modo}]")

    if not all_rows:
        print("No se generaron datos.")
        return

    df_out = (
        pd.DataFrame(all_rows)
        .sort_values(["Anio", "Delito", "Variable_fuente", "Tipo_cod"])
        .reset_index(drop=True)
    )

    out_path = Path(args.out)
    df_out.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n[OK] ¡Éxito! CSV guardado en {out_path} ({len(df_out)} filas)")

if __name__ == "__main__":
    main()