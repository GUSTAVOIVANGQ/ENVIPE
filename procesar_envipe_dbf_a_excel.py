#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Procesa directamente los archivos TMod_Vic.dbf de ENVIPE y genera un
libro Excel (.xlsx), sin crear primero un CSV.

El libro contiene una hoja de desglose completo, una hoja para cada
sección I a VII del cuestionario y una hoja de notas metodológicas.

La salida elimina las columnas Categoría y Base de referencia del
porcentaje, y agrega total_delito repetido en las filas correspondientes.
Lee DBF sueltos o TMod_Vic.dbf contenidos dentro de archivos ZIP y usa
FAC_DEL como factor de expansión.

La edición ENVIPE N corresponde al año de referencia N-1.

Ruta predeterminada de entrada:
    C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE\conjunto_de_datos

Salida predeterminada:
    C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE\ENVIPE_DESGLOSE_POR_SECCIONES.xlsx

Uso normal:
    python procesar_envipe_dbf_a_excel.py

Uso con rutas distintas:
    python procesar_envipe_dbf_a_excel.py --dir "D:\datos" --salida "D:\resultado.xlsx"

No requiere openpyxl ni pandas: el XLSX se escribe con la biblioteca
estándar de Python.
"""

from __future__ import annotations

import argparse
import logging
import re
import struct
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape, quoteattr
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator


MIN_EDITION = 2011
MAX_EDITION = 2025
TARGET_DBF_NAME = "tmod_vic.dbf"
DEFAULT_INPUT_DIR = Path(
    r"C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE\conjunto_de_datos"
)
DEFAULT_OUTPUT = DEFAULT_INPUT_DIR.parent / "ENVIPE_DESGLOSE_POR_SECCIONES.xlsx"

OUTPUT_FIELDS = [
    "anio",
    "seccion",
    "codigo_delito",
    "delito",
    "pregunta",
    "modalidad_comision",
    "estimacion",
    "muestra",
    "porcentaje",
    "total_delito",
]

HEADER_LABELS = {
    "anio": "Año",
    "seccion": "Sección",
    "codigo_delito": "Código del delito",
    "delito": "Delito",
    "pregunta": "Pregunta",
    "modalidad_comision": "Modalidad / medio de comisión",
    "estimacion": "Estimación",
    "muestra": "Muestra",
    "porcentaje": "Porcentaje",
    "total_delito": "Total del delito",
}

DATA_COLUMN_TYPES = [
    "year",
    "text",
    "text",
    "text",
    "text",
    "text",
    "integer",
    "integer",
    "percent",
    "integer",
]

DATA_COLUMN_WIDTHS = [10, 58, 16, 42, 52, 58, 16, 12, 14, 18]

SECTION_I = "SECCIÓN I. TODOS LOS TIPOS DE DELITO"
SECTION_II = "SECCIÓN II. ROBO TOTAL DE VEHÍCULO"
SECTION_III = (
    "SECCIÓN III. ROBO EN CASA HABITACIÓN, ASALTO EN LA CALLE O "
    "TRANSPORTE PÚBLICO O ROBO DISTINTO DE LOS ANTERIORES"
)
SECTION_IV = "SECCIÓN IV. FRAUDE"
SECTION_V = "SECCIÓN V. EXTORSIÓN"
SECTION_VI = "SECCIÓN VI. SECUESTRO PARA EXIGIR DINERO O BIENES"
SECTION_VII = (
    "SECCIÓN VII. HOSTIGAMIENTO, MANOSEO, EXHIBICIONISMO, "
    "INTENTO DE VIOLACIÓN"
)

SECTION_ORDER = {
    SECTION_I: 1,
    SECTION_II: 2,
    SECTION_III: 3,
    SECTION_IV: 4,
    SECTION_V: 5,
    SECTION_VI: 6,
    SECTION_VII: 7,
}

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


def principal_section(edition: int, crime_code: str) -> str:
    """Devuelve la sección específica del cuestionario para el delito.

    Los códigos cambiaron cuando se incorporó vandalismo. Para las
    ediciones 2011-2012 se usa el catálogo anterior; desde ENVIPE 2013
    se usa el catálogo nuevo. Los delitos sin una sección específica
    permanecen en la Sección I.
    """
    old_catalog = edition <= 2012

    if crime_code == "01":
        return SECTION_II
    if crime_code in (("03", "04", "05") if old_catalog else ("04", "05", "06")):
        return SECTION_III
    if crime_code in (("06", "07") if old_catalog else ("07", "08")):
        return SECTION_IV
    if crime_code == ("08" if old_catalog else "09"):
        return SECTION_V
    if crime_code == ("11" if old_catalog else "12"):
        return SECTION_VI
    if crime_code == ("12" if old_catalog else "13"):
        return SECTION_VII
    return SECTION_I


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
    modality: str,
    count: WeightedCount,
    denominator: float,
    crime_total: float,
) -> dict[str, object]:
    return {
        "anio": year,
        "seccion": section,
        "codigo_delito": crime_code,
        "delito": crime_name,
        "pregunta": question,
        "modalidad_comision": modality,
        "estimacion": round(count.estimate),
        "muestra": count.sample,
        "porcentaje": pct(count.estimate, denominator),
        "total_delito": round(crime_total),
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

    # Total de cada delito. El total se asigna a su sección específica;
    # los delitos que no tienen sección propia permanecen en la Sección I.
    for crime_code, crime_name in catalog.items():
        count = crimes[crime_code]
        rows.append(
            result_row(
                year=year,
                section=principal_section(edition, crime_code),
                crime_code=crime_code,
                crime_name=crime_name,
                question="Total por tipo de delito",
                modality="Total",
                count=count,
                denominator=count.estimate,
                crime_total=count.estimate,
            )
        )

    # Sección IV. Fraude. Las modalidades se calculan sobre el total de
    # los códigos de fraude incluidos por la edición.
    fraud_codes = fraud_crime_codes(edition)
    fraud_total = sum(crimes[code].estimate for code in fraud_codes)
    fraud_code_label = "-".join(fraud_codes)
    for response_code, response in fraud_options(edition).items():
        rows.append(
            result_row(
                year=year,
                section=SECTION_IV,
                crime_code=fraud_code_label,
                crime_name="Fraude",
                question="4.1 ¿Qué tipo de fraude fue?",
                modality=response,
                count=fraud_counts[response_code],
                denominator=fraud_total,
                crime_total=fraud_total,
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
                section=SECTION_V,
                crime_code=extortion_code,
                crime_name="Extorsión",
                question=extortion_question,
                modality=response,
                count=extortion_counts[response_code],
                denominator=extortion_total,
                crime_total=extortion_total,
            )
        )

    # Pregunta 1.5a, disponible solamente en ENVIPE 2025.
    if edition == 2025:
        for crime_code in MEDIUM_APPLICABLE_CRIMES_2025:
            crime_name = catalog[crime_code]
            crime_total = crimes[crime_code].estimate
            for response_code, response in MEDIUM_OPTIONS_2025.items():
                rows.append(
                    result_row(
                        year=year,
                        section=SECTION_I,
                        crime_code=crime_code,
                        crime_name=crime_name,
                        question="1.5a ¿El (DELITO) se realizó por medio de...?",
                        modality=response,
                        count=medium_counts[(crime_code, response_code)],
                        denominator=crime_total,
                        crime_total=crime_total,
                    )
                )

        # El porcentaje conserva como denominador las extorsiones con
        # contacto presencial, pero total_delito siempre muestra el total
        # completo de extorsiones, como solicitó el usuario.
        for response_code, response in EXTORTION_PLACE_OPTIONS_2025.items():
            rows.append(
                result_row(
                    year=year,
                    section=SECTION_V,
                    crime_code="09",
                    crime_name="Extorsión",
                    question="5.1a ¿La extorsión sucedió en...?",
                    modality=response,
                    count=extortion_place_counts[response_code],
                    denominator=extortion_presential_base.estimate,
                    crime_total=extortion_total,
                )
            )

    return rows


def _clean_xml_text(value: object) -> str:
    """Elimina caracteres no permitidos por XML 1.0 y escapa el texto."""
    text = str(value if value is not None else "")
    text = "".join(
        char
        for char in text
        if char in "\t\n\r" or ord(char) >= 0x20
    )
    return escape(text)


def _column_letter(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _string_cell(reference: str, value: object, style: int = 4) -> str:
    text = _clean_xml_text(value)
    return (
        f'<c r="{reference}" s="{style}" t="inlineStr">'
        f'<is><t xml:space="preserve">{text}</t></is></c>'
    )


def _number_cell(reference: str, value: object, style: int) -> str:
    if value in (None, ""):
        return f'<c r="{reference}" s="{style}"/>'
    return f'<c r="{reference}" s="{style}"><v>{value}</v></c>'


def _worksheet_xml(
    headers: list[str],
    rows: list[list[object]],
    column_types: list[str],
    column_widths: list[float],
) -> str:
    if not headers:
        raise ValueError("Una hoja de Excel debe tener al menos una columna")
    if len(headers) != len(column_types) or len(headers) != len(column_widths):
        raise ValueError("Encabezados, tipos y anchos deben tener la misma longitud")

    last_col = _column_letter(len(headers))
    last_row = max(len(rows) + 1, 1)
    row_xml: list[str] = []

    header_cells = "".join(
        _string_cell(f"{_column_letter(index)}1", header, style=1)
        for index, header in enumerate(headers, start=1)
    )
    row_xml.append(
        f'<row r="1" ht="32" customHeight="1">{header_cells}</row>'
    )

    for row_number, values in enumerate(rows, start=2):
        if len(values) != len(headers):
            raise ValueError(
                f"La fila {row_number} tiene {len(values)} valores; "
                f"se esperaban {len(headers)}"
            )
        cells: list[str] = []
        for column_number, (value, kind) in enumerate(
            zip(values, column_types), start=1
        ):
            reference = f"{_column_letter(column_number)}{row_number}"
            if kind == "percent":
                if value in (None, ""):
                    cells.append(_number_cell(reference, "", style=3))
                else:
                    cells.append(
                        _number_cell(reference, float(value) / 100.0, style=3)
                    )
            elif kind == "integer":
                cells.append(_number_cell(reference, int(value or 0), style=2))
            elif kind == "year":
                cells.append(_number_cell(reference, int(value or 0), style=5))
            else:
                cells.append(_string_cell(reference, value, style=4))
        row_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    cols_xml = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(column_widths, start=1)
    )

    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:{last_col}{last_row}"/>
  <sheetViews>
    <sheetView tabSelected="0" workbookViewId="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
      <selection pane="bottomLeft" activeCell="A2" sqref="A2"/>
    </sheetView>
  </sheetViews>
  <sheetFormatPr defaultRowHeight="18"/>
  <cols>{cols_xml}</cols>
  <sheetData>{''.join(row_xml)}</sheetData>
  <autoFilter ref="A1:{last_col}{last_row}"/>
  <pageMargins left="0.3" right="0.3" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>
  <pageSetup orientation="landscape" fitToWidth="1" fitToHeight="0"/>
</worksheet>'''


def _styles_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="2">
    <numFmt numFmtId="164" formatCode="#,##0"/>
    <numFmt numFmtId="165" formatCode="0.00%"/>
  </numFmts>
  <fonts count="2">
    <font><sz val="10"/><name val="Calibri"/><family val="2"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Calibri"/><family val="2"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1F4E5F"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="FFD9E1E5"/></left>
      <right style="thin"><color rgb="FFD9E1E5"/></right>
      <top style="thin"><color rgb="FFD9E1E5"/></top>
      <bottom style="thin"><color rgb="FFD9E1E5"/></bottom>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="6">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="top"/></xf>
    <xf numFmtId="165" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="top"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
  <dxfs count="0"/>
  <tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>
</styleSheet>'''


def _workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name={quoteattr(name)} sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <bookViews><workbookView xWindow="0" yWindow="0" windowWidth="24000" windowHeight="12000"/></bookViews>
  <sheets>{sheets}</sheets>
  <calcPr calcId="191029"/>
</workbook>'''


def _workbook_rels_xml(sheet_count: int) -> str:
    relationships = "".join(
        f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    )
    relationships += (
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{relationships}</Relationships>'''


def _content_types_xml(sheet_count: int) -> str:
    sheet_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  {sheet_overrides}
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''


def _root_rels_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''


def _core_properties_xml() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>ENVIPE - Desglose por secciones</dc:title>
  <dc:creator>Procesador ENVIPE</dc:creator>
  <cp:lastModifiedBy>Procesador ENVIPE</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>
</cp:coreProperties>'''


def _app_properties_xml(sheet_names: list[str]) -> str:
    titles = "".join(
        f"<vt:lpstr>{_clean_xml_text(name)}</vt:lpstr>"
        for name in sheet_names
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Python</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs><vt:vector size="2" baseType="variant"><vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant><vt:variant><vt:i4>{len(sheet_names)}</vt:i4></vt:variant></vt:vector></HeadingPairs>
  <TitlesOfParts><vt:vector size="{len(sheet_names)}" baseType="lpstr">{titles}</vt:vector></TitlesOfParts>
  <Company></Company>
  <LinksUpToDate>false</LinksUpToDate>
  <SharedDoc>false</SharedDoc>
  <HyperlinksChanged>false</HyperlinksChanged>
  <AppVersion>16.0300</AppVersion>
</Properties>'''


def write_xlsx(
    path: Path,
    rows: list[dict[str, object]],
    start_edition: int,
    end_edition: int,
    input_directory: Path,
) -> None:
    """Escribe el libro XLSX directamente, sin CSV intermedio."""
    path.parent.mkdir(parents=True, exist_ok=True)

    data_headers = [HEADER_LABELS[field] for field in OUTPUT_FIELDS]

    def values_for(items: list[dict[str, object]]) -> list[list[object]]:
        return [[row[field] for field in OUTPUT_FIELDS] for row in items]

    section_specs = [
        ("Sección I", SECTION_I),
        ("Sección II", SECTION_II),
        ("Sección III", SECTION_III),
        ("Sección IV", SECTION_IV),
        ("Sección V", SECTION_V),
        ("Sección VI", SECTION_VI),
        ("Sección VII", SECTION_VII),
    ]

    sheets: list[
        tuple[str, list[str], list[list[object]], list[str], list[float]]
    ] = [
        (
            "Desglose completo",
            data_headers,
            values_for(rows),
            DATA_COLUMN_TYPES,
            DATA_COLUMN_WIDTHS,
        )
    ]

    for sheet_name, section_name in section_specs:
        subset = [row for row in rows if row["seccion"] == section_name]
        sheets.append(
            (
                sheet_name,
                data_headers,
                values_for(subset),
                DATA_COLUMN_TYPES,
                DATA_COLUMN_WIDTHS,
            )
        )

    notes = [
        ["Directorio procesado", str(input_directory)],
        ["Ediciones solicitadas", f"ENVIPE {start_edition} a {end_edition}"],
        [
            "Convención de año",
            "La edición ENVIPE N corresponde al año de referencia N-1.",
        ],
        [
            "Estimación",
            "Suma ponderada con FAC_DEL, redondeada al entero más cercano.",
        ],
        [
            "Muestra",
            "Número de registros no ponderados que sostienen la estimación.",
        ],
        ["Porcentaje", "Se guarda como porcentaje nativo de Excel."],
        [
            "Total del delito",
            "Se repite en todas las filas del delito o grupo correspondiente.",
        ],
        [
            "Estructura",
            "Incluye una hoja completa y hojas separadas para las secciones I a VII.",
        ],
    ]
    sheets.append(
        (
            "Notas",
            ["Nota", "Detalle"],
            notes,
            ["text", "text"],
            [34, 105],
        )
    )

    sheet_names = [spec[0] for spec in sheets]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as xlsx:
        xlsx.writestr("[Content_Types].xml", _content_types_xml(len(sheets)))
        xlsx.writestr("_rels/.rels", _root_rels_xml())
        xlsx.writestr("docProps/core.xml", _core_properties_xml())
        xlsx.writestr("docProps/app.xml", _app_properties_xml(sheet_names))
        xlsx.writestr("xl/workbook.xml", _workbook_xml(sheet_names))
        xlsx.writestr(
            "xl/_rels/workbook.xml.rels",
            _workbook_rels_xml(len(sheets)),
        )
        xlsx.writestr("xl/styles.xml", _styles_xml())

        for index, (_, headers, data, types, widths) in enumerate(
            sheets, start=1
        ):
            xlsx.writestr(
                f"xl/worksheets/sheet{index}.xml",
                _worksheet_xml(headers, data, types, widths),
            )
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

    fake_source = InputSource(2025, Path("TMod_Vic.dbf"), "dbf")
    rows = build_output_rows(fake_source, result)
    vehicle_total = next(
        row for row in rows
        if row["codigo_delito"] == "01"
        and row["pregunta"] == "Total por tipo de delito"
    )
    harassment_total = next(
        row for row in rows
        if row["codigo_delito"] == "13"
        and row["pregunta"] == "Total por tipo de delito"
    )
    extortion_detail = next(
        row for row in rows
        if row["pregunta"] == "5.1 ¿La extorsión fue de tipo...?"
    )
    assert vehicle_total["seccion"] == SECTION_II
    assert harassment_total["seccion"] == SECTION_VII
    assert extortion_detail["total_delito"] == 150
    assert "base_porcentaje" not in extortion_detail
    assert "categoria" not in extortion_detail
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as temporary_directory:
        test_path = Path(temporary_directory) / "prueba.xlsx"
        write_xlsx(
            test_path,
            rows,
            2025,
            2025,
            Path(temporary_directory),
        )
        with zipfile.ZipFile(test_path, "r") as workbook_zip:
            names = set(workbook_zip.namelist())
            assert "xl/workbook.xml" in names
            assert "xl/worksheets/sheet1.xml" in names
            assert len(
                [
                    name
                    for name in names
                    if name.startswith("xl/worksheets/sheet")
                ]
            ) == 9

    print("Self-test OK")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Procesa TMod_Vic.dbf de ENVIPE y genera un Excel por secciones, "
            "con total_delito repetido en las filas correspondientes."
        )
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directorio con DBF o ZIP de ENVIPE. Predeterminado: {DEFAULT_INPUT_DIR}",
    )
    parser.add_argument(
        "--salida",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Excel de salida. Predeterminado: {DEFAULT_OUTPUT}",
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

    output_rows.sort(
        key=lambda row: (
            int(row["anio"]),
            SECTION_ORDER.get(str(row["seccion"]), 99),
            str(row["codigo_delito"]),
            str(row["pregunta"]),
            str(row["modalidad_comision"]),
        )
    )

    write_xlsx(
        args.salida,
        output_rows,
        args.start_edition,
        args.end_edition,
        args.dir,
    )
    print(f"Excel generado: {args.salida}")
    print(f"Filas en Desglose completo: {len(output_rows)}")
    print("Hojas: Desglose completo, Sección I a Sección VII y Notas")


if __name__ == "__main__":
    main()
