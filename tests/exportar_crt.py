"""
exportar_crt.py — Tablas limpias para la Comisión Reguladora de Telecomunicaciones
====================================================================================
Lee el panel_todos_años.csv ya generado por main.py y produce:

  resultados/
    CRT_01_medios_por_año.csv          ← Estimación por medio de comisión × año
    CRT_02_delitos_digitales_año.csv   ← Solo delitos digitales (tel + internet) por año
    CRT_03_desglose_delito_medio.csv   ← Cruce delito × medio × año (detalle completo)
    CRT_04_tendencia_digital_año.csv   ← Serie de tiempo: evolución % digital por año
    CRT_05_extorsion_fraude_medio.csv  ← Foco CRT: extorsión y fraudes por medio × año
"""

import sys
import warnings
from pathlib import Path

import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR  = Path(__file__).parent
RES_DIR   = BASE_DIR / "resultados"
PANEL_CSV = RES_DIR / "panel_todos_años.csv"

# ─── Grupos de medio para la CRT ─────────────────────────────────────────────
# Consolidamos los medios detallados en 5 categorías operativas claras

GRUPO_MEDIO = {
    "Teléfono — llamada de voz":        "Teléfono (llamada de voz)",
    "Teléfono — SMS / WhatsApp":        "Teléfono (SMS / WhatsApp / mensaje)",
    "Teléfono (sin detalle)":           "Teléfono (sin especificar tipo)",
    "Internet / redes sociales":        "Internet / redes sociales",
    "Correo / mensajería física":       "Correo / mensajería física",
    "Presencial (cara a cara)":         "Presencial",
    "Presencial + seguimiento digital": "Presencial con seguimiento digital",
    "Otro medio":                       "Otro medio",
    "No aplica (delito de hogar)":      "No aplica (delito de hogar)",
    "Sin información":                  "Sin información",
}

# Categoría para agrupar en tabla de alto nivel
CATEGORIA_MEDIO = {
    "Teléfono — llamada de voz":        "TELEFÓNICO",
    "Teléfono — SMS / WhatsApp":        "TELEFÓNICO",
    "Teléfono (sin detalle)":           "TELEFÓNICO",
    "Internet / redes sociales":        "INTERNET / DIGITAL",
    "Correo / mensajería física":       "OTRO MEDIO",
    "Presencial (cara a cara)":         "PRESENCIAL",
    "Presencial + seguimiento digital": "PRESENCIAL",
    "Otro medio":                       "OTRO MEDIO",
    "No aplica (delito de hogar)":      "NO APLICA (HOGAR)",
    "Sin información":                  "SIN INFORMACIÓN",
}

ES_DIGITAL_CRT = {
    "Teléfono — llamada de voz":        True,
    "Teléfono — SMS / WhatsApp":        True,
    "Teléfono (sin detalle)":           True,
    "Internet / redes sociales":        True,
    "Correo / mensajería física":       False,
    "Presencial (cara a cara)":         False,
    "Presencial + seguimiento digital": False,
    "Otro medio":                       False,
    "No aplica (delito de hogar)":      False,
    "Sin información":                  False,
}

# Delitos de interés para CRT (los que usan medios de telecomunicación)
DELITOS_CRT = {"Fraude bancario", "Fraude al consumidor", "Extorsión"}


def cargar_panel() -> pd.DataFrame:
    print(f"Cargando panel: {PANEL_CSV}")
    df = pd.read_csv(PANEL_CSV, low_memory=False)
    df["FAC_DEL"] = pd.to_numeric(df["FAC_DEL"], errors="coerce").fillna(1)
    df["categoria_medio"] = df["medio_etiqueta"].map(CATEGORIA_MEDIO).fillna("SIN INFORMACIÓN")
    df["es_digital_crt"] = df["medio_etiqueta"].map(ES_DIGITAL_CRT).fillna(False).astype(int)
    print(f"  {len(df):,} registros · años: {sorted(df['año'].unique().tolist())}")
    return df


# ─── TABLA 1: Medios de comisión por año ─────────────────────────────────────

def tabla_01_medios_por_año(df: pd.DataFrame):
    """
    Filas: cada año × cada medio de comisión
    Columnas: año, medio_comision, categoria, delitos_registrados (muestra),
              estimacion_poblacional, pct_del_total_ese_año
    """
    t = (
        df.groupby(["año", "medio_etiqueta"])
        .agg(
            delitos_muestra=("FAC_DEL", "count"),
            estimacion_poblacional=("FAC_DEL", "sum"),
        )
        .reset_index()
    )

    # Totales por año para calcular %
    totales = df.groupby("año")["FAC_DEL"].sum().rename("total_año")
    t = t.merge(totales, on="año")
    t["pct_del_total"] = (t["estimacion_poblacional"] / t["total_año"] * 100).round(1)

    # Mapeos legibles
    t["medio_etiqueta"] = t["medio_etiqueta"].map(GRUPO_MEDIO).fillna(t["medio_etiqueta"])
    t["categoria_medio"] = t["medio_etiqueta"].map({v: CATEGORIA_MEDIO.get(k, "—")
                                                     for k, v in GRUPO_MEDIO.items()}).fillna("—")

    t = t.rename(columns={
        "año":                  "Año",
        "medio_etiqueta":       "Medio de Comisión",
        "categoria_medio":      "Categoría",
        "delitos_muestra":      "Registros en Muestra",
        "estimacion_poblacional": "Estimación Poblacional",
        "pct_del_total":        "% del Total del Año",
        "total_año":            "Total Estimado del Año",
    })

    t = t.sort_values(["Año", "Estimación Poblacional"], ascending=[True, False])
    t["Estimación Poblacional"] = t["Estimación Poblacional"].round(0).astype(int)
    t["Total Estimado del Año"] = t["Total Estimado del Año"].round(0).astype(int)
    return t


# ─── TABLA 2: Delitos digitales por año (serie de tiempo) ────────────────────

def tabla_02_tendencia_digital(df: pd.DataFrame):
    """
    Una fila por año con totales y subtotales por tipo de canal digital.
    Útil para ver la evolución 2011–2025.
    """
    # Total por año
    total_año = df.groupby("año")["FAC_DEL"].sum().reset_index().rename(
        columns={"FAC_DEL": "total_delitos"}
    )

    # Digital total
    dig = df[df["es_digital_crt"] == 1].groupby("año")["FAC_DEL"].sum().reset_index().rename(
        columns={"FAC_DEL": "digital_total"}
    )

    # Por subcategoría de teléfono / internet
    sub = (
        df[df["es_digital_crt"] == 1]
        .groupby(["año", "medio_etiqueta"])["FAC_DEL"]
        .sum()
        .unstack(fill_value=0)
        .reset_index()
    )
    # Renombrar columnas del unstack
    sub.columns.name = None

    t = total_año.merge(dig, on="año", how="left").fillna(0)
    t = t.merge(sub, on="año", how="left").fillna(0)
    t["pct_digital"] = (t["digital_total"] / t["total_delitos"] * 100).round(1)

    # Redondear estimaciones
    for col in t.columns:
        if col != "año" and col != "pct_digital":
            t[col] = t[col].round(0).astype(int)

    t = t.rename(columns={"año": "Año", "total_delitos": "Total Delitos Estimados",
                           "digital_total": "Total Delitos Digitales (tel+internet)",
                           "pct_digital": "% Digital del Total"})
    return t.sort_values("Año")


# ─── TABLA 3: Desglose delito × medio × año ──────────────────────────────────

def tabla_03_desglose_delito_medio(df: pd.DataFrame):
    """
    Cruce completo: tipo de delito × medio × año.
    Es la tabla más detallada, buena para pivot tables en Excel.
    """
    t = (
        df.groupby(["año", "delito", "medio_etiqueta", "categoria_medio"])
        .agg(
            registros_muestra=("FAC_DEL", "count"),
            estimacion=("FAC_DEL", "sum"),
        )
        .reset_index()
    )

    totales = df.groupby("año")["FAC_DEL"].sum().rename("total_año")
    t = t.merge(totales, on="año")
    t["pct_del_total_año"] = (t["estimacion"] / t["total_año"] * 100).round(2)
    t["estimacion"] = t["estimacion"].round(0).astype(int)
    t["total_año"] = t["total_año"].round(0).astype(int)

    t = t.rename(columns={
        "año":               "Año",
        "delito":            "Tipo de Delito",
        "medio_etiqueta":    "Medio de Comisión",
        "categoria_medio":   "Categoría del Medio",
        "registros_muestra": "Registros en Muestra",
        "estimacion":        "Estimación Poblacional",
        "pct_del_total_año": "% del Total del Año",
        "total_año":         "Total Estimado del Año",
    })
    return t.sort_values(["Año", "Tipo de Delito", "Estimación Poblacional"],
                         ascending=[True, True, False])


# ─── TABLA 4: Categorías de medio agregadas por año (vista ejecutiva) ─────────

def tabla_04_categorias_por_año(df: pd.DataFrame):
    """
    Vista ejecutiva de alto nivel: solo 4 categorías (Telefónico, Internet,
    Presencial, Otro) × año. Lista para presentar en una junta.
    """
    t = (
        df.groupby(["año", "categoria_medio"])
        .agg(
            registros_muestra=("FAC_DEL", "count"),
            estimacion=("FAC_DEL", "sum"),
        )
        .reset_index()
    )

    totales = df.groupby("año")["FAC_DEL"].sum().rename("total_año")
    t = t.merge(totales, on="año")
    t["pct_del_total"] = (t["estimacion"] / t["total_año"] * 100).round(1)
    t["estimacion"] = t["estimacion"].round(0).astype(int)
    t["total_año"] = t["total_año"].round(0).astype(int)

    t = t.rename(columns={
        "año":               "Año",
        "categoria_medio":   "Categoría del Medio",
        "registros_muestra": "Registros en Muestra",
        "estimacion":        "Estimación Poblacional",
        "pct_del_total":     "% del Total del Año",
        "total_año":         "Total Estimado del Año",
    })
    return t.sort_values(["Año", "Estimación Poblacional"], ascending=[True, False])


# ─── TABLA 5: Extorsión y fraudes (foco CRT) por medio × año ─────────────────

def tabla_05_foco_crt(df: pd.DataFrame):
    """
    Solo los 3 delitos que directamente usan telecomunicaciones:
    Extorsión, Fraude bancario, Fraude al consumidor.
    Desglosados por medio y año.
    """
    df_crt = df[df["delito"].isin(DELITOS_CRT)].copy()

    t = (
        df_crt.groupby(["año", "delito", "medio_etiqueta"])
        .agg(
            registros_muestra=("FAC_DEL", "count"),
            estimacion=("FAC_DEL", "sum"),
        )
        .reset_index()
    )

    # Total de esos 3 delitos por año
    total_crt = df_crt.groupby("año")["FAC_DEL"].sum().rename("total_delitos_crt")
    t = t.merge(total_crt, on="año")
    t["pct_dentro_del_delito"] = None

    # % dentro de cada delito por año
    total_por_delito = df_crt.groupby(["año", "delito"])["FAC_DEL"].sum().rename("total_del_delito")
    t = t.merge(total_por_delito.reset_index(), on=["año", "delito"])
    t["pct_dentro_del_delito"] = (t["estimacion"] / t["total_del_delito"] * 100).round(1)

    t["estimacion"] = t["estimacion"].round(0).astype(int)
    t["total_del_delito"] = t["total_del_delito"].round(0).astype(int)
    t["total_delitos_crt"] = t["total_delitos_crt"].round(0).astype(int)

    t = t.rename(columns={
        "año":                    "Año",
        "delito":                 "Tipo de Delito",
        "medio_etiqueta":         "Medio de Comisión",
        "registros_muestra":      "Registros en Muestra",
        "estimacion":             "Estimación Poblacional",
        "pct_dentro_del_delito":  "% Dentro del Delito",
        "total_del_delito":       "Total del Delito ese Año",
        "total_delitos_crt":      "Total Delitos Relevantes CRT ese Año",
    })
    return t.sort_values(["Año", "Tipo de Delito", "Estimación Poblacional"],
                         ascending=[True, True, False])


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    if not PANEL_CSV.exists():
        print(f"ERROR: No existe {PANEL_CSV}")
        print("Ejecuta primero:  python main.py")
        return

    df = cargar_panel()

    archivos = [
        ("CRT_01_medios_por_año.csv",        tabla_01_medios_por_año,      "Medios por año"),
        ("CRT_02_tendencia_digital_año.csv",  tabla_02_tendencia_digital,   "Tendencia digital"),
        ("CRT_03_desglose_delito_medio.csv",  tabla_03_desglose_delito_medio, "Desglose delito × medio"),
        ("CRT_04_categorias_ejecutivo.csv",   tabla_04_categorias_por_año,  "Categorías ejecutivo"),
        ("CRT_05_foco_extorsion_fraude.csv",  tabla_05_foco_crt,            "Foco CRT"),
    ]

    print("\nGenerando CSVs para CRT...\n")
    for nombre, func, desc in archivos:
        t = func(df)
        ruta = RES_DIR / nombre
        t.to_csv(ruta, index=False, encoding="utf-8-sig")
        print(f"  [{desc}]")
        print(f"    Archivo : {nombre}")
        print(f"    Filas   : {len(t):,}")
        print(f"    Columnas: {list(t.columns)}")
        print()

    print("=" * 65)
    print("ARCHIVOS GENERADOS EN:")
    print(f"  {RES_DIR.resolve()}")
    print()
    print("DESCRIPCION DE CADA ARCHIVO:")
    print()
    print("  CRT_01  Estimacion poblacional por MEDIO DE COMISION y año")
    print("          → Vista principal para el manager")
    print()
    print("  CRT_02  Serie de tiempo: evolucion de delitos DIGITALES 2011-2025")
    print("          → Cuantos delitos por telefono/internet cada año")
    print()
    print("  CRT_03  Cruce completo DELITO x MEDIO x AÑO")
    print("          → Tabla detallada para Excel / pivot table")
    print()
    print("  CRT_04  Vista EJECUTIVA: 4 categorias (Telefonico, Internet,")
    print("          Presencial, Otro) x año")
    print("          → Una pagina, listo para presentacion")
    print()
    print("  CRT_05  Foco CRT: Extorsion, Fraude bancario, Fraude al consumidor")
    print("          desglosados por medio y año")
    print("          → Los delitos que mas usan telecomunicaciones")


if __name__ == "__main__":
    main()
