#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Procesa TMod_Vic.dbf de ENVIPE 2011-2025 y genera UN SOLO CSV
con los desgloses exactamente alineados con los cuestionarios.

Incluye:
1. Total estimado de cada tipo de delito (BPCOD).
2. Sección IV. Fraude, pregunta BP4_1, con el catálogo específico
   de cada edición.
3. Sección V. Extorsión, pregunta BP5_1, con el catálogo específico
   de cada edición.
4. ENVIPE 2025:
   - pregunta 1.5a, medio de comisión, para BPCOD 07, 08, 09, 10 y 13;
   - pregunta 5.1a, lugar de extorsión presencial.

La edición ENVIPE N corresponde al año de referencia N-1.

Salida predeterminada:
    ENVIPE_DESGLOSE_ENCUESTA.csv

El programa usa FAC_DEL como factor de expansión y procesa los DBF
registro por registro. No calcula error estándar, CV ni intervalos.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import struct
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator


MIN_EDITION = 2011
MAX_EDITION = 2025
TARGET_DBF_NAME = "tmod_vic.dbf"
DEFAULT_OUTPUT = "ENVIPE_DESGLOSE_ENCUESTA.csv"

OUTPUT_FIELDS = [
    "anio",
    "seccion",
    "codigo_delito",
    "delito",
    "pregunta",
    "variable",
    "codigo_respuesta",
    "respuesta",
    "tipo_respuesta",
    "estimacion",
    "muestra",
    "porcentaje_base",
    "base_porcentaje",
]

OLD_CRIMES = {
    "01": "Robo total de vehículo",
    "02": "Robo de accesorios, refacciones o herramientas de vehículo",
    "03": "Robo en casa habitación",
    "04": "Robo o asalto en la calle o transporte público",
    "05": "Robo en forma distinta a los anteriores",
    "06": "Clonación de tarjeta o fraude bancario",
    "07": "Fraude al consumidor",
    "08": "Extorsión",
    "09": "Amenazas verbales",
    "10": "Lesiones por agresión física",
    "11": "Secuestro para exigir dinero o bienes",
    "12": "Hostigamiento, manoseo, exhibicionismo o intento de violación",
    "13": "Violación sexual",
    "14": "Otros delitos",
}

NEW_CRIMES = {
    "01": "Robo total de vehículo",
    "02": "Robo de accesorios, refacciones o herramientas de vehículo",
    "03": "Vandalismo",
    "04": "Robo en casa habitación",
    "05": "Robo o asalto en la calle o transporte público",
    "06": "Robo en forma distinta a la anterior",
    "07": "Fraude bancario",
    "08": "Fraude al consumidor",
    "09": "Extorsión",
    "10": "Amenazas",
    "11": "Lesiones por agresión física",
    "12": "Secuestro para exigir dinero o bienes",
    "13": "Hostigamiento o intimidación sexual",
    "14": "Violación sexual",
    "15": "Otros delitos",
}

HISTORICAL_EXTORTION_OPTIONS = {
    "1": "Telefónica",
    "2": "Laboral",
    "3": "Por internet/correo electrónico",
    "4": "En la calle",
    "5": "En negocio propio o familiar",
    "6": "Cobro de piso",
    "7": "Otro",
}

FRAUD_OPTIONS_BY_EDITION = {
    2011: {
        "1": "Cheque falso",
        "2": "Pago por un servicio/producto no entregado (al consumidor)",
        "3": "Por internet/correo electrónico",
        "4": "Otro",
    },
    2012: {
        "1": "Cheque falso",
        "2": "Pago por un servicio/producto no entregado (al consumidor)",
        "3": "Tarjeta de débito o crédito",
        "4": "Por internet/correo electrónico",
        "5": "Otro",
    },
    2013: {
        "1": "Cheque falso o sin fondos",
        "2": "Dinero falso",
        "3": "Pago por un servicio/producto no entregado (al consumidor)",
        "4": "Tarjeta de débito o crédito",
        "5": "Por internet/correo electrónico",
        "6": "Otro",
    },
}

FRAUD_OPTIONS_2014_ONWARD = {
    "1": "Pago por un servicio/producto no entregado (al consumidor)",
    "2": "Cheque falso o sin fondos",
    "3": "Dinero falso",
    "4": "Tarjeta de débito o crédito",
    "5": "Por internet/correo electrónico",
    "6": "Otro",
}

EXTORTION_OPTIONS_2025 = {
    "1": "Laboral",
    "2": "Cobro de piso",
    "3": "Otro",
}

MEDIUM_OPTIONS_2025 = {
    "1": "Internet o medios electrónicos (redes sociales, correo electrónico, banca electrónica, etcétera)",
    "2": "Llamada telefónica",
    "3": "Contacto presencial",
    "4": "Otro",
    "9": "No sabe / no responde",
}

EXTORTION_PLACE_OPTIONS_2025 = {
    "1": "En su casa",
    "2": "En la calle",
    "3": "En negocio propio o familiar",
    "4": "Otro lugar",
}

MEDIUM_APPLICABLE_CRIMES_2025 = ("07", "08", "09", "10", "13")


@dataclass(frozen=True)
class InputSource:
    edition: int
    path: Path
    kind: str
    zip_entry: str | None = None

    @property
    def display_name(self) -> str:
        if self.kind == "zip" and self.zip_entry:
            return f"{self.path}::{self.zip_entry}"
        return str(self.path)


@dataclass(frozen=True)
class DBFField:
    name: str
    position: int
    length: int


@dataclass
class WeightedCount:
    estimate: float = 0.0
    sample: int = 0

    def add(self, weight: float) -> None:
        self.estimate += weight
        self.sample += 1


def crime_catalog(data_year: int) -> dict[str, str]:
    return OLD_CRIMES if data_year <= 2011 else NEW_CRIMES


def fraud_options(edition: int) -> dict[str, str]:
    if edition in FRAUD_OPTIONS_BY_EDITION:
        return FRAUD_OPTIONS_BY_EDITION[edition]
    if 2014 <= edition <= 2025:
        return FRAUD_OPTIONS_2014_ONWARD
    raise ValueError(f"No hay catálogo de fraude para ENVIPE {edition}")


def fraud_crime_codes(edition: int) -> tuple[str, ...]:
    return ("07",) if edition <= 2012 else ("07", "08")


def extortion_crime_code(edition: int) -> str:
    return "08" if edition <= 2012 else "09"


def required_fields(edition: int) -> set[str]:
    fields = {"BPCOD", "FAC_DEL", "BP4_1", "BP5_1"}
    if edition == 2025:
        fields.update(
            {
                "BP1_5A_1",
                "BP1_5A_2",
                "BP1_5A_3",
                "BP1_5A_4",
                "BP1_5A_9",
                "BP5_1A_1",
                "BP5_1A_2",
                "BP5_1A_3",
                "BP5_1A_4",
            }
        )
    return fields


def normalize_code(value: object, width: int | None = None) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"([+-]?\d+)\.0+", text)
    if match:
        text = match.group(1)
    if width is not None and text:
        text = text.zfill(width)
    return text


def parse_weight(value: object) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        weight = float(text)
    except ValueError:
        return None
    return weight if weight >= 0 else None


def is_selected_multi(value: object) -> bool:
    """
    En las variables multirrespuesta de ENVIPE 2025 cada columna representa
    una opción y el valor 1 indica que fue seleccionada. Se aceptan también
    representaciones numéricas con decimales.
    """
    return normalize_code(value) == "1"


def parse_edition_from_text(text: str) -> int | None:
    normalized = text.replace("\\", "/")
    matches = re.findall(
        r"envipe[^0-9]{0,8}(20\d{2}|\d{2})(?!\d)",
        normalized,
        flags=re.IGNORECASE,
    )
    for value in reversed(matches):
        edition = int(value) if len(value) == 4 else 2000 + int(value)
        if MIN_EDITION <= edition <= MAX_EDITION:
            return edition

    years = [
        int(value)
        for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", normalized)
        if MIN_EDITION <= int(value) <= MAX_EDITION
    ]
    return years[-1] if years else None


def find_tmod_entry(zf: zipfile.ZipFile) -> str | None:
    matches = [
        name
        for name in zf.namelist()
        if Path(name).name.lower() == TARGET_DBF_NAME
    ]
    if len(matches) > 1:
        raise ValueError(
            "El ZIP contiene más de un TMod_Vic.dbf: " + ", ".join(matches)
        )
    return matches[0] if matches else None


def discover_sources(
    root: Path,
    start_edition: int,
    end_edition: int,
) -> list[InputSource]:
    candidates: dict[int, list[InputSource]] = defaultdict(list)

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if path.name.lower() == TARGET_DBF_NAME:
            edition = parse_edition_from_text(str(path))
            if edition and start_edition <= edition <= end_edition:
                candidates[edition].append(
                    InputSource(edition, path, "dbf")
                )

        elif path.suffix.lower() == ".zip":
            edition = parse_edition_from_text(str(path))
            if not edition or not (start_edition <= edition <= end_edition):
                continue
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    entry = find_tmod_entry(zf)
            except (OSError, zipfile.BadZipFile) as exc:
                logging.warning("ZIP inválido %s: %s", path, exc)
                continue
            if entry:
                candidates[edition].append(
                    InputSource(edition, path, "zip", entry)
                )

    selected: list[InputSource] = []
    for edition in sorted(candidates):
        direct = [item for item in candidates[edition] if item.kind == "dbf"]
        zipped = [item for item in candidates[edition] if item.kind == "zip"]

        if len(direct) > 1:
            raise ValueError(
                f"Hay más de un DBF para ENVIPE {edition}: "
                + ", ".join(str(item.path) for item in direct)
            )
        if direct:
            selected.append(direct[0])
            continue

        if len(zipped) > 1:
            raise ValueError(
                f"Hay más de un ZIP para ENVIPE {edition}: "
                + ", ".join(str(item.path) for item in zipped)
            )
        if zipped:
            selected.append(zipped[0])

    return selected


@contextmanager
def open_source(source: InputSource) -> Iterator[BinaryIO]:
    if source.kind == "dbf":
        with source.path.open("rb") as fh:
            yield fh
        return

    if source.kind == "zip" and source.zip_entry:
        with zipfile.ZipFile(source.path, "r") as zf:
            with zf.open(source.zip_entry, "r") as fh:
                yield fh
        return

    raise ValueError(f"Fuente no soportada: {source}")


def read_dbf_layout(
    fh: BinaryIO,
    selected_columns: set[str],
) -> tuple[int, int, list[DBFField], set[str]]:
    header = fh.read(32)
    if len(header) < 32:
        raise ValueError("Encabezado DBF incompleto")

    record_count = struct.unpack("<I", header[4:8])[0]
    header_size = struct.unpack("<H", header[8:10])[0]
    record_size = struct.unpack("<H", header[10:12])[0]

    position = 1
    selected_fields: list[DBFField] = []
    all_names: set[str] = set()

    while True:
        first = fh.read(1)
        if not first:
            raise ValueError("Descriptor DBF incompleto")
        if first == b"\x0d":
            break

        remainder = fh.read(31)
        if len(remainder) < 31:
            raise ValueError("Descriptor de campo DBF incompleto")
        descriptor = first + remainder

        name = descriptor[0:11].rstrip(b"\x00").decode("latin-1").upper()
        length = descriptor[16]
        all_names.add(name)
        if name in selected_columns:
            selected_fields.append(DBFField(name, position, length))
        position += length

    current = fh.tell()
    if current > header_size:
        raise ValueError("El encabezado DBF excede el tamaño declarado")
    remaining = header_size - current
    if remaining and len(fh.read(remaining)) < remaining:
        raise ValueError("Encabezado DBF truncado")

    return record_count, record_size, selected_fields, all_names


def iter_selected_records(
    fh: BinaryIO,
    selected_columns: set[str],
) -> Iterator[dict[str, str]]:
    record_count, record_size, fields, all_names = read_dbf_layout(
        fh, selected_columns
    )

    missing = sorted(selected_columns - all_names)
    if missing:
        raise ValueError("Faltan variables en el DBF: " + ", ".join(missing))

    for _ in range(record_count):
        record = fh.read(record_size)
        if not record or record[0:1] == b"\x1a":
            break
        if len(record) < record_size:
            raise ValueError("Registro DBF truncado")
        if record[0:1] == b"*":
            continue

        yield {
            field.name: record[
                field.position : field.position + field.length
            ].decode("latin-1", errors="replace").strip()
            for field in fields
        }


def process_records(
    edition: int,
    records: Iterable[dict[str, str]],
) -> tuple[
    dict[str, WeightedCount],
    dict[str, WeightedCount],
    dict[str, WeightedCount],
    dict[tuple[str, str], WeightedCount],
    dict[str, WeightedCount],
    WeightedCount,
    int,
]:
    data_year = edition - 1
    crimes = {
        code: WeightedCount()
        for code in crime_catalog(data_year)
    }
    fraud_counts = {
        code: WeightedCount()
        for code in fraud_options(edition)
    }
    extortion_options = (
        EXTORTION_OPTIONS_2025
        if edition == 2025
        else HISTORICAL_EXTORTION_OPTIONS
    )
    extortion_counts = {
        code: WeightedCount()
        for code in extortion_options
    }
    medium_counts = {
        (crime, option): WeightedCount()
        for crime in MEDIUM_APPLICABLE_CRIMES_2025
        for option in MEDIUM_OPTIONS_2025
    }
    extortion_place_counts = {
        option: WeightedCount()
        for option in EXTORTION_PLACE_OPTIONS_2025
    }
    extortion_presential_base = WeightedCount()
    invalid_weights = 0

    fraud_codes = set(fraud_crime_codes(edition))
    extortion_code = extortion_crime_code(edition)

    for row in records:
        weight = parse_weight(row.get("FAC_DEL", ""))
        if weight is None:
            invalid_weights += 1
            continue

        crime = normalize_code(row.get("BPCOD", ""), width=2)
        if crime not in crimes:
            continue

        crimes[crime].add(weight)

        if crime in fraud_codes:
            response = normalize_code(row.get("BP4_1", ""))
            if response in fraud_counts:
                fraud_counts[response].add(weight)

        if crime == extortion_code:
            response = normalize_code(row.get("BP5_1", ""))
            if response in extortion_counts:
                extortion_counts[response].add(weight)

        if edition == 2025 and crime in MEDIUM_APPLICABLE_CRIMES_2025:
            for option in MEDIUM_OPTIONS_2025:
                field = f"BP1_5A_{option}"
                if is_selected_multi(row.get(field, "")):
                    medium_counts[(crime, option)].add(weight)

            if crime == "09" and is_selected_multi(row.get("BP1_5A_3", "")):
                extortion_presential_base.add(weight)
                for option in EXTORTION_PLACE_OPTIONS_2025:
                    field = f"BP5_1A_{option}"
                    if is_selected_multi(row.get(field, "")):
                        extortion_place_counts[option].add(weight)

    return (
        crimes,
        fraud_counts,
        extortion_counts,
        medium_counts,
        extortion_place_counts,
        extortion_presential_base,
        invalid_weights,
    )


def pct(numerator: float, denominator: float) -> str:
    if denominator <= 0:
        return ""
    return f"{numerator / denominator * 100:.4f}"


def result_row(
    *,
    year: int,
    section: str,
    crime_code: str,
    crime_name: str,
    question: str,
    variable: str,
    response_code: str,
    response: str,
    response_type: str,
    count: WeightedCount,
    denominator: float,
    base_label: str,
) -> dict[str, object]:
    return {
        "anio": year,
        "seccion": section,
        "codigo_delito": crime_code,
        "delito": crime_name,
        "pregunta": question,
        "variable": variable,
        "codigo_respuesta": response_code,
        "respuesta": response,
        "tipo_respuesta": response_type,
        "estimacion": round(count.estimate),
        "muestra": count.sample,
        "porcentaje_base": pct(count.estimate, denominator),
        "base_porcentaje": base_label,
    }


def build_output_rows(
    source: InputSource,
    processed: tuple[
        dict[str, WeightedCount],
        dict[str, WeightedCount],
        dict[str, WeightedCount],
        dict[tuple[str, str], WeightedCount],
        dict[str, WeightedCount],
        WeightedCount,
        int,
    ],
) -> list[dict[str, object]]:
    (
        crimes,
        fraud_counts,
        extortion_counts,
        medium_counts,
        extortion_place_counts,
        extortion_presential_base,
        _invalid_weights,
    ) = processed

    edition = source.edition
    year = edition - 1
    catalog = crime_catalog(year)
    rows: list[dict[str, object]] = []

    # Totales por cada tipo de delito.
    for crime_code, crime_name in catalog.items():
        count = crimes[crime_code]
        rows.append(
            result_row(
                year=year,
                section="I. Todos los tipos de delito",
                crime_code=crime_code,
                crime_name=crime_name,
                question="Total por tipo de delito",
                variable="BPCOD",
                response_code="",
                response="Total",
                response_type="Total",
                count=count,
                denominator=count.estimate,
                base_label="Total del mismo delito",
            )
        )

    # Sección IV. Fraude.
    fraud_codes = fraud_crime_codes(edition)
    fraud_total = sum(crimes[code].estimate for code in fraud_codes)
    fraud_label = "Fraude"
    fraud_code_label = "-".join(fraud_codes)
    for response_code, response in fraud_options(edition).items():
        rows.append(
            result_row(
                year=year,
                section="IV. Fraude",
                crime_code=fraud_code_label,
                crime_name=fraud_label,
                question="4.1 ¿Qué tipo de fraude fue?",
                variable="BP4_1",
                response_code=response_code,
                response=response,
                response_type="Única",
                count=fraud_counts[response_code],
                denominator=fraud_total,
                base_label="Total de fraudes incluidos en la sección IV",
            )
        )

    # Sección V. Extorsión.
    extortion_code = extortion_crime_code(edition)
    extortion_total = crimes[extortion_code].estimate
    extortion_options = (
        EXTORTION_OPTIONS_2025
        if edition == 2025
        else HISTORICAL_EXTORTION_OPTIONS
    )
    extortion_question = (
        "5.1 ¿La extorsión fue de tipo...?"
        if edition == 2025
        else "5.1 ¿La extorsión fue...?"
    )
    for response_code, response in extortion_options.items():
        rows.append(
            result_row(
                year=year,
                section="V. Extorsión",
                crime_code=extortion_code,
                crime_name="Extorsión",
                question=extortion_question,
                variable="BP5_1",
                response_code=response_code,
                response=response,
                response_type="Única",
                count=extortion_counts[response_code],
                denominator=extortion_total,
                base_label="Total de extorsiones",
            )
        )

    # Nueva pregunta de medio de comisión, solamente en ENVIPE 2025.
    if edition == 2025:
        for crime_code in MEDIUM_APPLICABLE_CRIMES_2025:
            crime_name = catalog[crime_code]
            denominator = crimes[crime_code].estimate
            for response_code, response in MEDIUM_OPTIONS_2025.items():
                rows.append(
                    result_row(
                        year=year,
                        section="I. Todos los tipos de delito",
                        crime_code=crime_code,
                        crime_name=crime_name,
                        question="1.5a ¿El (DELITO) se realizó por medio de...?",
                        variable=f"BP1_5A_{response_code}",
                        response_code=response_code,
                        response=response,
                        response_type="Múltiple",
                        count=medium_counts[(crime_code, response_code)],
                        denominator=denominator,
                        base_label=f"Total de {crime_name.lower()}",
                    )
                )

        for response_code, response in EXTORTION_PLACE_OPTIONS_2025.items():
            rows.append(
                result_row(
                    year=year,
                    section="V. Extorsión",
                    crime_code="09",
                    crime_name="Extorsión",
                    question="5.1a ¿La extorsión sucedió en...?",
                    variable=f"BP5_1A_{response_code}",
                    response_code=response_code,
                    response=response,
                    response_type="Múltiple",
                    count=extortion_place_counts[response_code],
                    denominator=extortion_presential_base.estimate,
                    base_label="Extorsiones con contacto presencial",
                )
            )

    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def run_self_test() -> None:
    records_2011 = [
        {"BPCOD": "07", "FAC_DEL": "100", "BP4_1": "1", "BP5_1": ""},
        {"BPCOD": "07", "FAC_DEL": "50", "BP4_1": "3", "BP5_1": ""},
        {"BPCOD": "08", "FAC_DEL": "200", "BP4_1": "", "BP5_1": "1"},
        {"BPCOD": "08", "FAC_DEL": "75", "BP4_1": "", "BP5_1": "6"},
    ]
    result = process_records(2011, records_2011)
    crimes, fraud, extortion, *_ = result
    assert crimes["07"].estimate == 150
    assert fraud["1"].estimate == 100
    assert fraud["3"].estimate == 50
    assert extortion["1"].estimate == 200
    assert extortion["6"].estimate == 75

    records_2025 = [
        {
            "BPCOD": "09",
            "FAC_DEL": "100",
            "BP4_1": "",
            "BP5_1": "1.000000000000000",
            "BP1_5A_1": "1.000000000000000",
            "BP1_5A_2": "1.000000000000000",
            "BP1_5A_3": "0.000000000000000",
            "BP1_5A_4": "0.000000000000000",
            "BP1_5A_9": "0.000000000000000",
            "BP5_1A_1": "0.000000000000000",
            "BP5_1A_2": "0.000000000000000",
            "BP5_1A_3": "0.000000000000000",
            "BP5_1A_4": "0.000000000000000",
        },
        {
            "BPCOD": "09",
            "FAC_DEL": "50",
            "BP4_1": "",
            "BP5_1": "3.000000000000000",
            "BP1_5A_1": "0.000000000000000",
            "BP1_5A_2": "0.000000000000000",
            "BP1_5A_3": "1.000000000000000",
            "BP1_5A_4": "0.000000000000000",
            "BP1_5A_9": "0.000000000000000",
            "BP5_1A_1": "0.000000000000000",
            "BP5_1A_2": "1.000000000000000",
            "BP5_1A_3": "1.000000000000000",
            "BP5_1A_4": "0.000000000000000",
        },
        {
            "BPCOD": "07",
            "FAC_DEL": "80",
            "BP4_1": "5.000000000000000",
            "BP5_1": "",
            "BP1_5A_1": "1.000000000000000",
            "BP1_5A_2": "0.000000000000000",
            "BP1_5A_3": "0.000000000000000",
            "BP1_5A_4": "0.000000000000000",
            "BP1_5A_9": "0.000000000000000",
            "BP5_1A_1": "0.000000000000000",
            "BP5_1A_2": "0.000000000000000",
            "BP5_1A_3": "0.000000000000000",
            "BP5_1A_4": "0.000000000000000",
        },
    ]
    result = process_records(2025, records_2025)
    (
        crimes,
        fraud,
        extortion,
        medium,
        places,
        presencial_base,
        invalid,
    ) = result
    assert invalid == 0
    assert crimes["09"].estimate == 150
    assert fraud["5"].estimate == 80
    assert extortion["1"].estimate == 100
    assert extortion["3"].estimate == 50
    assert medium[("09", "1")].estimate == 100
    assert medium[("09", "2")].estimate == 100
    assert medium[("09", "3")].estimate == 50
    assert presencial_base.estimate == 50
    assert places["2"].estimate == 50
    assert places["3"].estimate == 50
    print("Self-test OK")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Procesa TMod_Vic.dbf de ENVIPE y genera un CSV con los "
            "desgloses exactos de fraude, extorsión y medio de comisión."
        )
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("conjunto_de_datos"),
        help="Directorio con DBF o ZIP de ENVIPE.",
    )
    parser.add_argument(
        "--salida",
        type=Path,
        default=Path(DEFAULT_OUTPUT),
        help=f"CSV de salida. Predeterminado: {DEFAULT_OUTPUT}",
    )
    parser.add_argument("--start-edition", type=int, default=MIN_EDITION)
    parser.add_argument("--end-edition", type=int, default=MAX_EDITION)
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Detiene el proceso si falta alguna edición.",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.self_test:
        run_self_test()
        return

    if not args.dir.is_dir():
        raise SystemExit(f"No existe el directorio: {args.dir}")

    try:
        sources = discover_sources(
            args.dir, args.start_edition, args.end_edition
        )
    except Exception as exc:
        raise SystemExit(f"Error al buscar archivos: {exc}") from exc

    if not sources:
        raise SystemExit("No se encontraron archivos TMod_Vic.dbf.")

    found = {source.edition for source in sources}
    expected = set(range(args.start_edition, args.end_edition + 1))
    missing = sorted(expected - found)
    if missing:
        message = "Faltan ediciones: " + ", ".join(map(str, missing))
        if args.require_all:
            raise SystemExit(message)
        logging.warning(message)

    output_rows: list[dict[str, object]] = []

    for source in sources:
        logging.info(
            "Procesando ENVIPE %s: %s",
            source.edition,
            source.display_name,
        )
        try:
            with open_source(source) as fh:
                records = iter_selected_records(
                    fh, required_fields(source.edition)
                )
                processed = process_records(source.edition, records)
        except Exception as exc:
            raise SystemExit(
                f"Error en ENVIPE {source.edition}: {exc}"
            ) from exc

        invalid = processed[-1]
        if invalid:
            logging.warning(
                "ENVIPE %s: se excluyeron %s registros con FAC_DEL inválido",
                source.edition,
                invalid,
            )

        output_rows.extend(build_output_rows(source, processed))

    section_order = {
        "I. Todos los tipos de delito": 1,
        "IV. Fraude": 4,
        "V. Extorsión": 5,
    }
    output_rows.sort(
        key=lambda row: (
            int(row["anio"]),
            section_order.get(str(row["seccion"]), 99),
            str(row["codigo_delito"]),
            str(row["pregunta"]),
            str(row["codigo_respuesta"]),
        )
    )

    write_csv(args.salida, output_rows)
    print(f"Archivo generado: {args.salida}")
    print(f"Filas: {len(output_rows)}")


if __name__ == "__main__":
    main()
