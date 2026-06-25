import pandas as pd
import os

# Breadcrumb style route
ruta_tematica = "Programas > ENVIPE > [Año] > Microdatos > dbf"
fuente_base = "INEGI (ENVIPE) https://www.inegi.org.mx/programas/envipe/"

data = [
    ["Tabla de datos: ENVIPE_DELITO_MEDIO_HISTORICO", "", "", "", ""],
    ["Inicio de serie: 2011", "", "", "", ""],
    ["Fuente: INEGI", "", "", "", ""],
    ["Actualización: Anual", "", "", "", ""],
    ["", "", "", "", ""],
    ["Variable", "Tipo", "Descripción", "Fuente", "Ruta temática"],
    ["ANIO", "Numérica", "Año de la encuesta", fuente_base, ruta_tematica],
    ["TIPO_DELITO", "Categórica", "Tipo de delito cometido", fuente_base, ruta_tematica],
    ["MEDIO_COMISION", "Categórica", "Medio de comisión del delito", fuente_base, ruta_tematica],
    ["ESTIMACION_POBLACIONAL", "Numérica", "Estimación poblacional (factor de expansión)", fuente_base, ruta_tematica],
    ["REGISTROS_MUESTRA", "Numérica", "Número de registros en la muestra", fuente_base, ruta_tematica],
    ["", "", "", "", ""],
    ["Para mayor información sobre el procesamiento de datos, consulte el archivo procesar_envipe.py o visite la página oficial de ENVIPE:", "", "", "", ""],
    ["https://www.inegi.org.mx/programas/envipe/", "", "", "", ""]
]

# Create DataFrame
df = pd.DataFrame(data)

# Save as CSV (following the encoding/style of the examples)
# Note: The example had some encoding issues in my preview, so I'll use utf-8-sig for Excel compatibility or latin-1 if it matches better.
# Let's try to match the "Índice de precios.csv" which seemed to be latin-1 or similar based on the characters.
# However, utf-8-sig is safer for modern apps. I'll use utf-8-sig to ensure accents work.
csv_path = "metadatos_envipe.csv"
df.to_csv(csv_path, index=False, header=False, encoding="utf-8-sig")

# Also update the Excel one to be consistent
excel_path = "metadatos_envipe.xlsx"
df.to_excel(excel_path, index=False, header=False)

print(f"Archivos mejorados: {csv_path} y {excel_path}")
