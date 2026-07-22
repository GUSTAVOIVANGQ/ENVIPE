#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Procesa los microdatos TMod_Vic de ENVIPE 2011-2025 para construir
indicadores nacionales de delitos relacionados con telecomunicaciones.

Principios metodológicos:
1) La edición ENVIPE N describe, para victimización, el año de referencia N-1.
2) FAC_DEL es el factor de expansión de cada delito/incidente en TMod_Vic.
3) La estructura_tmod_vic.csv sirve únicamente para comprobar presencia de
   variables; NO documenta significados ni catálogos.
4) La serie histórica comparable se limita a variables expresamente captadas:
   - fraude por internet/correo electrónico;
   - extorsión telefónica;
   - extorsión por internet/correo electrónico.
5) En ENVIPE 2025 (año de referencia 2024) cambia el instrumento:
   BP5_1 deja de ser el medio de extorsión y aparece BP1_5A_* como pregunta
   multirrespuesta sobre medio de comisión para los delitos.
6) Este programa calcula estimaciones puntuales. Para publicación oficial se
   deben añadir EE, CV e IC con el diseño complejo de cada edición.

Salidas:
- ENVIPE_TELECOM_INDICADORES.csv
- ENVIPE_TELECOM_COBERTURA.csv
- ENVIPE_TELECOM_AUDITORIA.csv

Dependencia: pandas.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd


# -----------------------------------------------------------------------------
# Fuentes oficiales utilizadas para fijar reglas semánticas
# -----------------------------------------------------------------------------
SOURCE_2011_MODULE = (
    "https://www.inegi.org.mx/contenidos/programas/envipe/2011/doc/"
    "cuest_envipe11_modulo.pdf"
)
SOURCE_2012_MANUAL = (
    "https://www.inegi.org.mx/contenido/productos/prod_serv/contenidos/"
    "espanol/bvinegi/productos/metodologias/ENVIPE2012/Manual_ENT/"
    "ENVIPE12_Manual_ENT.pdf"
)
SOURCE_2013_MANUAL = (
    "https://www.inegi.org.mx/contenidos/programas/envipe/2013/doc/"
    "envipe13_manual_ent.pdf"
)
SOURCE_2024_MODULE = (
    "https://www.inegi.org.mx/contenidos/programas/envipe/2024/doc/"
    "cuest_modulo_envipe2024.pdf"
)
SOURCE_2025_STRUCTURE = (
    "https://www.inegi.org.mx/contenidos/programas/envipe/2025/doc/"
    "fd_envipe2025.pdf"
)
SOURCE_2025_DESIGN = (
    "https://www.inegi.org.mx/contenidos/programas/envipe/2025/doc/"
    "889463926689.pdf"
)

OUTPUT_INDICATORS = "ENVIPE_TELECOM_INDICADORES.csv"
OUTPUT_COVERAGE = "ENVIPE_TELECOM_COBERTURA.csv"
OUTPUT_AUDIT = "ENVIPE_TELECOM_AUDITORIA.csv"

REQUIRED_BASE_FIELDS = {"BPCOD", "FAC_DEL", "BP4_1", "BP5_1"}
NEW_MEDIUM_FIELDS = {"BP1_5A_1", "BP1_5A_2", "BP1_5A_3", "BP1_5A_4", "BP1_5A_9"}
READ_FIELDS = REQUIRED_BASE_FIELDS | NEW_MEDIUM_FIELDS | {
    "CONTROL", "VIV_SEL", "HOGAR", "R_SEL", "ND_TIPO",
    "CVE_ENT", "NOM_ENT", "EST", "EST_DIS", "UPM", "UPM_DIS",
}

# BPCOD histórico para años de referencia 2010-2011.
BPCOD_OLD = {
    "fraude_consumidor": {"07"},
    "extorsion": {"08"},
    "amenazas": {"09"},
    "hostigamiento": {"12"},
}

# BPCOD vigente desde el año de referencia 2012.
BPCOD_NEW = {
    "fraude": {"07", "08"},
    "extorsion": {"09"},
    "amenazas": {"10"},
    "hostigamiento": {"13"},
}

CURRENT_BPCOD_ALL = {f"{n:02d}" for n in range(1, 16)}
NEW_MEDIUM_APPLICABLE_BPCODS = frozenset({"07", "08", "09", "10", "13"})


@dataclass(frozen=True)
class SingleChoiceRule:
    indicator_id: str
    indicator_name: str
    crime_name: str
    medium_name: str
    variable: str
    positive_codes: frozenset[str]
    valid_codes: frozenset[str]
    bpcods: frozenset[str]
    series_id: str
    comparable: str
    series_break: str
    source_rule: str
    note: str


def parse_edition_from_name(name: str) -> int | None:
    """Extrae la edición ENVIPE de nombres como envipe_2025 o envipe13."""
    m4 = re.search(r"(20\d{2})", name)
    if m4:
        return int(m4.group(1))
    m2 = re.search(r"envipe[_-]?(\d{2})(?!\d)", name, re.IGNORECASE)
    if m2:
        return 2000 + int(m2.group(1))
    return None


def edition_page(edition: int) -> str:
    return f"https://www.inegi.org.mx/programas/envipe/{edition}/"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def find_tmod_entry(zf: zipfile.ZipFile) -> str | None:
    for name in zf.namelist():
        if Path(name).name.lower() == "tmod_vic.dbf":
            return name
    return None


def read_dbf_selected(data: bytes, selected_columns: set[str]) -> pd.DataFrame:
    """Lee sólo columnas seleccionadas de un DBF para reducir memoria."""
    fh = io.BytesIO(data)
    header = fh.read(32)
    if len(header) < 32:
        raise ValueError("Encabezado DBF incompleto")

    num_records = struct.unpack("<I", header[4:8])[0]
    header_size = struct.unpack("<H", header[8:10])[0]
    record_size = struct.unpack("<H", header[10:12])[0]

    fields: list[tuple[str, int, int]] = []  # nombre, posición, longitud
    position = 1  # primer byte: marca de borrado
    while True:
        descriptor = fh.read(32)
        if not descriptor:
            raise ValueError("Descriptor DBF incompleto")
        if descriptor[0] == 0x0D:
            break
        if len(descriptor) < 32:
            raise ValueError("Descriptor de campo DBF incompleto")
        name = descriptor[0:11].rstrip(b"\x00").decode("latin-1").upper()
        length = descriptor[16]
        if name in selected_columns:
            fields.append((name, position, length))
        position += length

    fh.seek(header_size)
    rows: list[dict[str, str]] = []
    for _ in range(num_records):
        record = fh.read(record_size)
        if not record or record[0:1] == b"\x1a":
            break
        if len(record) < record_size:
            logging.warning("Registro DBF truncado; se detiene la lectura")
            break
        if record[0:1] == b"*":
            continue
        row = {
            name: record[pos : pos + length].decode("latin-1", errors="replace").strip()
            for name, pos, length in fields
        }
        rows.append(row)

    return pd.DataFrame.from_records(rows, columns=[f[0] for f in fields])


def normalize_code(series: pd.Series, width: int | None = None) -> pd.Series:
    """Normaliza códigos DBF sin perder ceros significativos de BPCOD.

    Algunas ediciones recientes almacenan respuestas categóricas como N(19,15),
    por ejemplo ``5.000000000000000``. La versión anterior sólo eliminaba
    exactamente ``.0`` y por ello no encontraba ningún código en 2024-2025.
    """
    out = series.fillna("").astype(str).str.strip()
    out = out.str.replace(r"^([+-]?\d+)\.0+$", r"\1", regex=True)
    if width is not None:
        nonempty = out.ne("")
        out.loc[nonempty] = out.loc[nonempty].str.zfill(width)
    return out


def prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    if "BPCOD" not in df.columns or "FAC_DEL" not in df.columns:
        missing = sorted({"BPCOD", "FAC_DEL"} - set(df.columns))
        raise ValueError(f"Faltan variables indispensables: {missing}")

    result = df.copy()
    result["BPCOD"] = normalize_code(result["BPCOD"], width=2)
    result["FAC_DEL"] = pd.to_numeric(
        result["FAC_DEL"].fillna("").astype(str).str.strip(), errors="coerce"
    )
    invalid_weights = result["FAC_DEL"].isna() | (result["FAC_DEL"] < 0)
    if invalid_weights.any():
        logging.warning(
            "Se excluyen %s registros con FAC_DEL inválido/negativo",
            int(invalid_weights.sum()),
        )
        result = result.loc[~invalid_weights].copy()
    result["FAC_DEL"] = result["FAC_DEL"].astype(float)

    for column in set(result.columns) - {"FAC_DEL"}:
        result[column] = normalize_code(result[column])
    return result


def fraud_internet_rule(data_year: int) -> SingleChoiceRule:
    if data_year == 2010:
        positive = frozenset({"3"})
        valid = frozenset({"1", "2", "3", "4"})
        bpcods = frozenset(BPCOD_OLD["fraude_consumidor"])
        source = SOURCE_2011_MODULE
        note = "ENVIPE 2011: BP4_1=3 es internet/correo; no incluye fraude bancario BPCOD=06."
    elif data_year == 2011:
        positive = frozenset({"4"})
        valid = frozenset({"1", "2", "3", "4", "5"})
        bpcods = frozenset(BPCOD_OLD["fraude_consumidor"])
        source = SOURCE_2012_MANUAL
        note = "ENVIPE 2012: BP4_1=4 es internet/correo; BPCOD=07 histórico."
    else:
        positive = frozenset({"5"})
        valid = frozenset({"1", "2", "3", "4", "5", "6"})
        bpcods = frozenset(BPCOD_NEW["fraude"])
        source = SOURCE_2013_MANUAL if data_year == 2012 else (
            SOURCE_2025_STRUCTURE if data_year == 2024 else SOURCE_2024_MODULE
        )
        note = "Desde datos 2012: fraude BPCOD=07/08 y BP4_1=5 es internet/correo electrónico."

    return SingleChoiceRule(
        indicator_id="FRAUDE_INTERNET_CORREO",
        indicator_name="Fraudes por internet o correo electrónico",
        crime_name="Fraude",
        medium_name="Internet/correo electrónico",
        variable="BP4_1",
        positive_codes=positive,
        valid_codes=valid,
        bpcods=bpcods,
        series_id="SERIE_HISTORICA_MODALIDAD",
        comparable="Condicionada: desde 2012 cambia la clasificación y cobertura del fraude",
        series_break="No",
        source_rule=source,
        note=note,
    )


def extortion_rule(data_year: int, medium: str) -> SingleChoiceRule | None:
    if data_year > 2023:
        return None
    bpcods = BPCOD_OLD["extorsion"] if data_year <= 2011 else BPCOD_NEW["extorsion"]
    if medium == "telefono":
        indicator_id = "EXTORSION_TELEFONICA"
        indicator_name = "Extorsiones telefónicas"
        medium_name = "Llamada telefónica"
        positive = frozenset({"1"})
    elif medium == "internet":
        indicator_id = "EXTORSION_INTERNET_CORREO"
        indicator_name = "Extorsiones por internet o correo electrónico"
        medium_name = "Internet/correo electrónico"
        positive = frozenset({"3"})
    elif medium == "telecom_union":
        indicator_id = "EXTORSION_MEDIOS_TELECOM"
        indicator_name = "Extorsiones por teléfono o internet/correo electrónico"
        medium_name = "Teléfono o internet/correo electrónico (unión)"
        positive = frozenset({"1", "3"})
    else:
        raise ValueError(f"Medio de extorsión desconocido: {medium}")

    source = SOURCE_2011_MODULE if data_year == 2010 else (
        SOURCE_2012_MANUAL if data_year == 2011 else SOURCE_2024_MODULE
    )
    return SingleChoiceRule(
        indicator_id=indicator_id,
        indicator_name=indicator_name,
        crime_name="Extorsión",
        medium_name=medium_name,
        variable="BP5_1",
        positive_codes=positive,
        valid_codes=frozenset({"1", "2", "3", "4", "5", "6", "7"}),
        bpcods=frozenset(bpcods),
        series_id="SERIE_HISTORICA_MODALIDAD",
        comparable="Sí hasta el año de referencia 2023",
        series_break="Sí en 2024: BP5_1 cambia de significado",
        source_rule=source,
        note="BP5_1 clasifica el medio/tipo de extorsión hasta ENVIPE 2024 (datos 2023).",
    )


def safe_pct(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator * 100.0


def weighted_row(
    df: pd.DataFrame,
    *,
    edition: int,
    data_year: int,
    indicator_id: str,
    indicator_name: str,
    crime_name: str,
    medium_name: str,
    series_id: str,
    variable_source: str,
    bpcod_filter: Sequence[str],
    value_filter: str,
    crime_mask: pd.Series,
    positive_mask: pd.Series,
    valid_response_mask: pd.Series,
    comparable: str,
    series_break: str,
    is_multiresponse: bool,
    source_rule: str,
    note: str,
    zip_path: Path,
    dbf_entry: str,
    zip_sha256: str,
) -> dict:
    weight = df["FAC_DEL"]
    numerator_mask = crime_mask & positive_mask
    valid_mask = crime_mask & valid_response_mask

    numerator = float(weight.loc[numerator_mask].sum())
    total = float(weight.loc[crime_mask].sum())
    valid_total = float(weight.loc[valid_mask].sum())

    return {
        "edicion_envipe": edition,
        "anio_referencia": data_year,
        "ambito": "Nacional",
        "unidad_medida": "Incidentes delictivos estimados",
        "serie_id": series_id,
        "indicador_id": indicator_id,
        "indicador": indicator_name,
        "delito": crime_name,
        "medio_comision": medium_name,
        "estatus": "estimado",
        "variable_fuente": variable_source,
        "bpcod_filtro": "|".join(sorted(bpcod_filter)),
        "valor_filtro": value_filter,
        "estimacion_incidentes": numerator,
        "estimacion_incidentes_redondeada": round(numerator),
        "n_muestra_numerador": int(numerator_mask.sum()),
        "estimacion_total_delito": total,
        "n_muestra_total_delito": int(crime_mask.sum()),
        "porcentaje_sobre_total_delito": safe_pct(numerator, total),
        "estimacion_respuestas_validas": valid_total,
        "n_muestra_respuestas_validas": int(valid_mask.sum()),
        "porcentaje_sobre_respuestas_validas": safe_pct(numerator, valid_total),
        "factor_expansion": "FAC_DEL",
        "multirrespuesta": "Sí" if is_multiresponse else "No",
        "los_componentes_pueden_traslaparse": "Sí" if is_multiresponse else "No",
        "comparabilidad_historica": comparable,
        "ruptura_serie": series_break,
        "precision_calculada": "No",
        "publicar_sin_cv_ee_ic": "No recomendado",
        "archivo_zip": zip_path.name,
        "archivo_dbf": dbf_entry,
        "sha256_zip": zip_sha256,
        "url_edicion_inegi": edition_page(edition),
        "url_documento_regla": source_rule,
        "url_diseno_muestral": SOURCE_2025_DESIGN,
        "nota_metodologica": note,
    }


def calculate_single_choice(
    df: pd.DataFrame,
    rule: SingleChoiceRule,
    *,
    edition: int,
    data_year: int,
    zip_path: Path,
    dbf_entry: str,
    zip_sha256: str,
) -> dict:
    if rule.variable not in df.columns:
        raise ValueError(f"No existe {rule.variable} para {edition}")
    values = normalize_code(df[rule.variable])
    crime_mask = df["BPCOD"].isin(rule.bpcods)
    positive_mask = values.isin(rule.positive_codes)
    valid_mask = values.isin(rule.valid_codes)
    return weighted_row(
        df,
        edition=edition,
        data_year=data_year,
        indicator_id=rule.indicator_id,
        indicator_name=rule.indicator_name,
        crime_name=rule.crime_name,
        medium_name=rule.medium_name,
        series_id=rule.series_id,
        variable_source=rule.variable,
        bpcod_filter=sorted(rule.bpcods),
        value_filter="|".join(sorted(rule.positive_codes)),
        crime_mask=crime_mask,
        positive_mask=positive_mask,
        valid_response_mask=valid_mask,
        comparable=rule.comparable,
        series_break=rule.series_break,
        is_multiresponse=False,
        source_rule=rule.source_rule,
        note=rule.note,
        zip_path=zip_path,
        dbf_entry=dbf_entry,
        zip_sha256=zip_sha256,
    )


def calculate_historical_aggregate(
    df: pd.DataFrame,
    *,
    edition: int,
    data_year: int,
    zip_path: Path,
    dbf_entry: str,
    zip_sha256: str,
) -> dict | None:
    if data_year > 2023:
        return None

    fraud = fraud_internet_rule(data_year)
    ext = extortion_rule(data_year, "telecom_union")
    assert ext is not None

    fraud_values = normalize_code(df[fraud.variable])
    ext_values = normalize_code(df[ext.variable])
    fraud_crime = df["BPCOD"].isin(fraud.bpcods)
    ext_crime = df["BPCOD"].isin(ext.bpcods)
    crime_mask = fraud_crime | ext_crime
    positive = (
        (fraud_crime & fraud_values.isin(fraud.positive_codes))
        | (ext_crime & ext_values.isin(ext.positive_codes))
    )
    valid = (
        (fraud_crime & fraud_values.isin(fraud.valid_codes))
        | (ext_crime & ext_values.isin(ext.valid_codes))
    )

    return weighted_row(
        df,
        edition=edition,
        data_year=data_year,
        indicator_id="TOTAL_FRAUDE_EXTORSION_TELECOM_ARMONIZADO",
        indicator_name=(
            "Total armonizado: fraude por internet/correo y extorsión por "
            "teléfono o internet/correo"
        ),
        crime_name="Fraude + extorsión",
        medium_name="Medios de telecomunicaciones definidos por preguntas históricas",
        series_id="SERIE_HISTORICA_ARMONIZADA",
        variable_source=f"{fraud.variable}+{ext.variable}",
        bpcod_filter=sorted(set(fraud.bpcods) | set(ext.bpcods)),
        value_filter=(
            f"{fraud.variable}={','.join(sorted(fraud.positive_codes))};"
            f"{ext.variable}={','.join(sorted(ext.positive_codes))}"
        ),
        crime_mask=crime_mask,
        positive_mask=positive,
        valid_response_mask=valid,
        comparable="Armonizada, no estrictamente comparable; ruptura conceptual en 2012",
        series_break="No estimable con la misma definición en 2024",
        is_multiresponse=False,
        source_rule=f"{fraud.source_rule} | {ext.source_rule}",
        note=(
            "Suma sin doble conteo porque fraude y extorsión son BPCOD distintos. "
            "No incluye amenazas ni hostigamiento antes de 2024 porque el instrumento "
            "no captaba su medio de comisión."
        ),
        zip_path=zip_path,
        dbf_entry=dbf_entry,
        zip_sha256=zip_sha256,
    )


def new_medium_valid_mask(df: pd.DataFrame) -> pd.Series:
    # Respuesta sustantiva: al menos un medio 1-4 seleccionado. BP1_5A_9 es NS/NR.
    return pd.concat(
        [normalize_code(df[c]).eq("1") for c in ["BP1_5A_1", "BP1_5A_2", "BP1_5A_3", "BP1_5A_4"]],
        axis=1,
    ).any(axis=1)


def calculate_new_medium_rows(
    df: pd.DataFrame,
    *,
    edition: int,
    data_year: int,
    zip_path: Path,
    dbf_entry: str,
    zip_sha256: str,
) -> list[dict]:
    if data_year != 2024:
        return []
    missing = sorted(NEW_MEDIUM_FIELDS - set(df.columns))
    if missing:
        raise ValueError(f"Faltan variables nuevas de medio de comisión: {missing}")

    internet = normalize_code(df["BP1_5A_1"]).eq("1")
    phone = normalize_code(df["BP1_5A_2"]).eq("1")
    any_telecom = internet | phone
    valid = new_medium_valid_mask(df)

    groups = {
        "TODOS": ("Delitos con aplicación de la pregunta 1.5a", NEW_MEDIUM_APPLICABLE_BPCODS),
        "FRAUDE": ("Fraude", BPCOD_NEW["fraude"]),
        "EXTORSION": ("Extorsión", BPCOD_NEW["extorsion"]),
        "AMENAZAS": ("Amenazas verbales", BPCOD_NEW["amenazas"]),
        "HOSTIGAMIENTO": (
            "Hostigamiento, manoseo, exhibicionismo o intento de violación",
            BPCOD_NEW["hostigamiento"],
        ),
    }
    media = {
        "INTERNET_ELECTRONICO": (
            "Internet o medios electrónicos",
            internet,
            "BP1_5A_1=1",
        ),
        "LLAMADA_TELEFONICA": ("Llamada telefónica", phone, "BP1_5A_2=1"),
        "TELECOM_UNION": (
            "Internet/medios electrónicos o llamada telefónica (unión)",
            any_telecom,
            "BP1_5A_1=1 OR BP1_5A_2=1",
        ),
    }

    rows: list[dict] = []
    for group_id, (crime_name, bpcods) in groups.items():
        crime_mask = df["BPCOD"].isin(bpcods)
        for medium_id, (medium_name, positive_mask, filter_text) in media.items():
            rows.append(
                weighted_row(
                    df,
                    edition=edition,
                    data_year=data_year,
                    indicator_id=f"NUEVO_MEDIO_{group_id}_{medium_id}",
                    indicator_name=f"{crime_name}: {medium_name}",
                    crime_name=crime_name,
                    medium_name=medium_name,
                    series_id="SERIE_NUEVA_MEDIO_COMISION_2024",
                    variable_source="BP1_5A_1|BP1_5A_2|BP1_5A_3|BP1_5A_4|BP1_5A_9",
                    bpcod_filter=sorted(bpcods),
                    value_filter=filter_text,
                    crime_mask=crime_mask,
                    positive_mask=positive_mask,
                    valid_response_mask=valid,
                    comparable="No comparable directamente con la serie histórica",
                    series_break="Nueva pregunta multirrespuesta en ENVIPE 2025",
                    is_multiresponse=True,
                    source_rule=SOURCE_2025_STRUCTURE,
                    note=(
                        "La pregunta 1.5a se aplica únicamente a BPCOD 07, 08, 09, 10 y 13. "
                        "La suma de internet y teléfono puede exceder la unión porque un "
                        "incidente puede declarar más de un medio. La fila TELECOM_UNION "
                        "cuenta cada incidente una sola vez."
                    ),
                    zip_path=zip_path,
                    dbf_entry=dbf_entry,
                    zip_sha256=zip_sha256,
                )
            )
    return rows


def coverage_rows_for_year(edition: int, data_year: int) -> list[dict]:
    rows = [
        {
            "edicion_envipe": edition,
            "anio_referencia": data_year,
            "indicador_id": "FRAUDE_INTERNET_CORREO",
            "estatus_teorico": "Disponible",
            "razon": "BP4_1 capta explícitamente internet/correo electrónico.",
        }
    ]
    for indicator_id in [
        "EXTORSION_TELEFONICA",
        "EXTORSION_INTERNET_CORREO",
        "EXTORSION_MEDIOS_TELECOM",
        "TOTAL_FRAUDE_EXTORSION_TELECOM_ARMONIZADO",
    ]:
        rows.append(
            {
                "edicion_envipe": edition,
                "anio_referencia": data_year,
                "indicador_id": indicator_id,
                "estatus_teorico": "Disponible" if data_year <= 2023 else "No comparable",
                "razon": (
                    "BP5_1 conserva la clasificación histórica."
                    if data_year <= 2023
                    else "En ENVIPE 2025 BP5_1 cambia a laboral/cobro de piso/otro."
                ),
            }
        )
    for crime in ["TODOS", "FRAUDE", "EXTORSION", "AMENAZAS", "HOSTIGAMIENTO"]:
        rows.append(
            {
                "edicion_envipe": edition,
                "anio_referencia": data_year,
                "indicador_id": f"NUEVO_MEDIO_{crime}_*",
                "estatus_teorico": "Disponible" if data_year == 2024 else "No captado",
                "razon": (
                    "BP1_5A_* capta el medio de comisión como pregunta multirrespuesta; "
                    "la pregunta 1.5a aplica a BPCOD 07, 08, 09, 10 y 13."
                    if data_year == 2024
                    else "Antes de ENVIPE 2025 no existe BP1_5A_*; BP1_5 es lugar, no medio."
                ),
            }
        )
    return rows


def load_structure_inventory(path: Path | None) -> dict[int, set[str]]:
    if path is None:
        return {}
    structure = pd.read_csv(path, dtype=str)
    required = {"zip_file", "field_name"}
    if not required.issubset(structure.columns):
        raise ValueError(f"El inventario de estructura requiere columnas {sorted(required)}")
    structure = structure.copy()
    structure["edition"] = structure["zip_file"].map(parse_edition_from_name)
    structure["field_name"] = structure["field_name"].str.upper().str.strip()
    inventory: dict[int, set[str]] = {}
    for edition, group in structure.dropna(subset=["edition"]).groupby("edition"):
        inventory[int(edition)] = set(group["field_name"])
    return inventory


def validate_inventory(edition: int, inventory: dict[int, set[str]]) -> tuple[str, str]:
    if not inventory:
        return "No proporcionado", ""
    if edition not in inventory:
        return "Edición ausente", f"No hay inventario para ENVIPE {edition}"
    expected = set(REQUIRED_BASE_FIELDS)
    if edition == 2025:
        expected |= NEW_MEDIUM_FIELDS
    missing = sorted(expected - inventory[edition])
    if missing:
        return "Faltan variables", "|".join(missing)
    return "Correcto", ""


def validate_indicator_bases(rows: list[dict], data_year: int) -> None:
    """Evita publicar ceros causados por códigos mal normalizados.

    Si el total del delito es positivo, las preguntas clave deben producir una
    base válida positiva. Una base igual a cero en toda la pregunta suele indicar
    cambio de tipo/formato en el DBF, no ausencia real de delitos.
    """
    required_ids = {"FRAUDE_INTERNET_CORREO"}
    if data_year <= 2023:
        required_ids.add("EXTORSION_TELEFONICA")
    if data_year == 2024:
        required_ids.add("NUEVO_MEDIO_TODOS_TELECOM_UNION")

    suspicious = []
    for row in rows:
        if row.get("indicador_id") not in required_ids:
            continue
        total = float(row.get("estimacion_total_delito") or 0)
        valid = float(row.get("estimacion_respuestas_validas") or 0)
        if total > 0 and valid <= 0:
            suspicious.append(str(row.get("indicador_id")))
    if suspicious:
        raise ValueError(
            "Base válida igual a cero en indicadores clave: "
            + ", ".join(sorted(suspicious))
            + ". Revise la normalización de códigos y el tipo de campo DBF."
        )


def process_zip(
    zip_path: Path,
    inventory: dict[int, set[str]],
) -> tuple[list[dict], list[dict], dict]:
    edition = parse_edition_from_name(zip_path.name)
    if edition is None:
        raise ValueError(f"No se pudo extraer la edición de {zip_path.name}")
    data_year = edition - 1
    digest = sha256_file(zip_path)

    with zipfile.ZipFile(zip_path, "r") as zf:
        entry = find_tmod_entry(zf)
        if entry is None:
            raise ValueError("No se encontró TMod_Vic.dbf")
        dbf_bytes = zf.read(entry)

    raw = read_dbf_selected(dbf_bytes, READ_FIELDS)
    df = prepare_df(raw)

    rows: list[dict] = []
    rows.append(
        calculate_single_choice(
            df,
            fraud_internet_rule(data_year),
            edition=edition,
            data_year=data_year,
            zip_path=zip_path,
            dbf_entry=entry,
            zip_sha256=digest,
        )
    )
    for medium in ["telefono", "internet", "telecom_union"]:
        rule = extortion_rule(data_year, medium)
        if rule is not None:
            rows.append(
                calculate_single_choice(
                    df,
                    rule,
                    edition=edition,
                    data_year=data_year,
                    zip_path=zip_path,
                    dbf_entry=entry,
                    zip_sha256=digest,
                )
            )
    aggregate = calculate_historical_aggregate(
        df,
        edition=edition,
        data_year=data_year,
        zip_path=zip_path,
        dbf_entry=entry,
        zip_sha256=digest,
    )
    if aggregate is not None:
        rows.append(aggregate)
    rows.extend(
        calculate_new_medium_rows(
            df,
            edition=edition,
            data_year=data_year,
            zip_path=zip_path,
            dbf_entry=entry,
            zip_sha256=digest,
        )
    )

    validate_indicator_bases(rows, data_year)

    inventory_status, inventory_missing = validate_inventory(edition, inventory)
    audit = {
        "edicion_envipe": edition,
        "anio_referencia": data_year,
        "archivo_zip": str(zip_path),
        "archivo_dbf": entry,
        "sha256_zip": digest,
        "registros_tmod_vic": len(df),
        "suma_fac_del_todos_registros": float(df["FAC_DEL"].sum()),
        "variables_leidas": "|".join(sorted(df.columns)),
        "campo_estrato_detectado": next((c for c in ["EST_DIS", "EST"] if c in df.columns), ""),
        "campo_upm_detectado": next((c for c in ["UPM_DIS", "UPM"] if c in df.columns), ""),
        "inventario_estructura_estado": inventory_status,
        "inventario_estructura_faltantes": inventory_missing,
        "precision_calculada": "No",
        "advertencia": (
            "Estimaciones puntuales: calcular EE, CV e IC con diseño complejo antes de publicar."
        ),
    }
    return rows, coverage_rows_for_year(edition, data_year), audit


def discover_zips(directory: Path, start_edition: int, end_edition: int) -> list[Path]:
    candidates: dict[int, list[Path]] = {}
    for path in directory.rglob("*.zip"):
        edition = parse_edition_from_name(path.name)
        if edition is None or not (start_edition <= edition <= end_edition):
            continue
        candidates.setdefault(edition, []).append(path)

    selected: list[Path] = []
    for edition in sorted(candidates):
        paths = sorted(candidates[edition])
        if len(paths) > 1:
            raise ValueError(
                f"Hay más de un ZIP para ENVIPE {edition}: "
                + ", ".join(str(p) for p in paths)
            )
        selected.append(paths[0])
    return selected


def write_outputs(
    output_dir: Path,
    indicators: list[dict],
    coverage: list[dict],
    audit: list[dict],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    indicators_df = pd.DataFrame(indicators).sort_values(
        ["anio_referencia", "serie_id", "indicador_id"]
    )
    coverage_df = pd.DataFrame(coverage).sort_values(
        ["anio_referencia", "indicador_id"]
    )
    audit_df = pd.DataFrame(audit).sort_values("anio_referencia")

    indicators_df.to_csv(
        output_dir / OUTPUT_INDICATORS, index=False, encoding="utf-8-sig"
    )
    coverage_df.to_csv(
        output_dir / OUTPUT_COVERAGE, index=False, encoding="utf-8-sig"
    )
    audit_df.to_csv(output_dir / OUTPUT_AUDIT, index=False, encoding="utf-8-sig")


def run_self_test() -> None:
    # 2010: fraude internet BP4_1=3; extorsión teléfono/internet BP5_1=1/3.
    df2010 = prepare_df(
        pd.DataFrame(
            {
                "BPCOD": ["07", "07", "08", "08", "08"],
                "BP4_1": ["3", "1", "", "", ""],
                "BP5_1": ["", "", "1", "3", "2"],
                "FAC_DEL": [10, 20, 30, 40, 50],
            }
        )
    )
    fake = Path("base_de_datos_envipe_2011_dbf.zip")
    row = calculate_single_choice(
        df2010,
        fraud_internet_rule(2010),
        edition=2011,
        data_year=2010,
        zip_path=fake,
        dbf_entry="tmod_vic.dbf",
        zip_sha256="test",
    )
    assert row["estimacion_incidentes"] == 10
    ext = calculate_single_choice(
        df2010,
        extortion_rule(2010, "telecom_union"),  # type: ignore[arg-type]
        edition=2011,
        data_year=2010,
        zip_path=fake,
        dbf_entry="tmod_vic.dbf",
        zip_sha256="test",
    )
    assert ext["estimacion_incidentes"] == 70

    # 2011: internet cambia a BP4_1=4.
    df2011 = prepare_df(
        pd.DataFrame(
            {"BPCOD": ["07", "07"], "BP4_1": ["4", "3"], "BP5_1": ["", ""], "FAC_DEL": [11, 22]}
        )
    )
    row2011 = calculate_single_choice(
        df2011,
        fraud_internet_rule(2011),
        edition=2012,
        data_year=2011,
        zip_path=Path("base_de_datos_envipe_2012_dbf.zip"),
        dbf_entry="tmod_vic.dbf",
        zip_sha256="test",
    )
    assert row2011["estimacion_incidentes"] == 11

    # 2024: pregunta nueva multirrespuesta; la unión no duplica.
    df2024 = prepare_df(
        pd.DataFrame(
            {
                "BPCOD": ["09", "10", "13"],
                "BP4_1": ["", "", ""],
                "BP5_1": ["1.000000000000000", "", ""],
                "BP1_5A_1": ["1.000000000000000", "1.000000000000000", "0.000000000000000"],
                "BP1_5A_2": ["1.000000000000000", "0.000000000000000", "1.000000000000000"],
                "BP1_5A_3": ["0.000000000000000", "0.000000000000000", "0.000000000000000"],
                "BP1_5A_4": ["0.000000000000000", "0.000000000000000", "0.000000000000000"],
                "BP1_5A_9": ["0.000000000000000", "0.000000000000000", "0.000000000000000"],
                "FAC_DEL": [100, 200, 300],
            }
        )
    )
    assert normalize_code(pd.Series(["5.000000000000000", "1.000000000000000"])).tolist() == ["5", "1"]

    rows2024 = calculate_new_medium_rows(
        df2024,
        edition=2025,
        data_year=2024,
        zip_path=Path("bd_envipe_2025_dbf.zip"),
        dbf_entry="tmod_vic.dbf",
        zip_sha256="test",
    )
    all_union = next(r for r in rows2024 if r["indicador_id"] == "NUEVO_MEDIO_TODOS_TELECOM_UNION")
    assert all_union["estimacion_incidentes"] == 600
    all_internet = next(r for r in rows2024 if r["indicador_id"] == "NUEVO_MEDIO_TODOS_INTERNET_ELECTRONICO")
    all_phone = next(r for r in rows2024 if r["indicador_id"] == "NUEVO_MEDIO_TODOS_LLAMADA_TELEFONICA")
    assert all_internet["estimacion_incidentes"] == 300
    assert all_phone["estimacion_incidentes"] == 400
    print("Self-test OK")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Procesa TMod_Vic de ENVIPE para indicadores telecom."
    )
    parser.add_argument("--dir", type=Path, default=Path("conjunto_de_datos"))
    parser.add_argument("--out-dir", type=Path, default=Path("salida_envipe_telecom"))
    parser.add_argument("--estructura", type=Path, default=None)
    parser.add_argument("--start-edition", type=int, default=2011)
    parser.add_argument("--end-edition", type=int, default=2025)
    parser.add_argument("--strict", action="store_true", help="Detiene ante cualquier error anual")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.self_test:
        run_self_test()
        return

    if not args.dir.exists():
        raise SystemExit(f"No existe el directorio: {args.dir}")
    if args.estructura is not None and not args.estructura.exists():
        raise SystemExit(f"No existe el inventario de estructura: {args.estructura}")

    inventory = load_structure_inventory(args.estructura)
    zips = discover_zips(args.dir, args.start_edition, args.end_edition)
    if not zips:
        raise SystemExit("No se encontraron ZIP de ENVIPE en el rango solicitado")

    all_indicators: list[dict] = []
    all_coverage: list[dict] = []
    all_audit: list[dict] = []

    found_editions = {parse_edition_from_name(p.name) for p in zips}
    expected_editions = set(range(args.start_edition, args.end_edition + 1))
    missing_editions = sorted(expected_editions - found_editions)
    if missing_editions:
        logging.warning("Faltan ediciones ZIP: %s", missing_editions)

    for zip_path in zips:
        edition = parse_edition_from_name(zip_path.name)
        logging.info(
            "Procesando ENVIPE %s (año de referencia %s): %s",
            edition,
            edition - 1 if edition else "?",
            zip_path.name,
        )
        try:
            indicators, coverage, audit = process_zip(zip_path, inventory)
            all_indicators.extend(indicators)
            all_coverage.extend(coverage)
            all_audit.append(audit)
        except Exception as exc:
            logging.exception("Error en %s: %s", zip_path.name, exc)
            if args.strict:
                raise
            all_audit.append(
                {
                    "edicion_envipe": edition,
                    "anio_referencia": edition - 1 if edition else None,
                    "archivo_zip": str(zip_path),
                    "advertencia": f"ERROR: {exc}",
                }
            )

    if not all_indicators:
        raise SystemExit("No se generaron indicadores")

    write_outputs(args.out_dir, all_indicators, all_coverage, all_audit)
    logging.info("Salidas guardadas en %s", args.out_dir)


if __name__ == "__main__":
    main()
