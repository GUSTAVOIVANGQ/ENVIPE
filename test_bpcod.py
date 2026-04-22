import pandas as pd
from procesar_envipe import extraer_tmod_vic, normalizar_columnas
from pathlib import Path

zips = list(Path("conjunto_de_datos").glob("*.zip"))
for z in zips[:2]:
    print(z.name)
    df = extraer_tmod_vic(z, 2011)
    df = normalizar_columnas(df)
    print("BPCOD dtypes:", df["BPCOD"].dtype)
    print("Unique BPCOD:", df["BPCOD"].dropna().unique()[:5])
