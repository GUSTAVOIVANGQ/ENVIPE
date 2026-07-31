#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Funciones compartidas para procesar TMod_Vic.dbf de ENVIPE.

Este módulo no se ejecuta directamente. Lo importan:
- main_procesar_envipe.py
- validar_envipe_inegi.py

Sólo procesa Fraude y Extorsión, usando FAC_DEL como factor de expansión.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import math
import re
import struct
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterator

MIN_EDITION = 2011
MAX_EDITION = 2025
TARGET_DBF_NAME = "tmod_vic.dbf"
TARGET_CRIMES = ("Fraude", "Extorsión")

DEFAULT_ROOT = Path(r"C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE")
DEFAULT_DBF_DIR = DEFAULT_ROOT / "conjunto_de_datos"
DEFAULT_DATA_CSV = DEFAULT_ROOT / "ENVIPE_FRAUDE_EXTORSION.csv"
DEFAULT_VALIDATION_CSV = DEFAULT_ROOT / "VALIDACION_INEGI_ENVIPE.csv"
DEFAULT_INEGI_DIR = DEFAULT_ROOT / "inegi"

REDUCED_FIELDS = [
    "anio",
    "seccion",
    "delito",
    "modalidad_comision",
    "cuest_modulo_envipe_7",
    "cuest_modulo_envipe2025_2",
    "estimacion",
    "porcentaje",
    "total_delito",
]

NA_VALUE = "NA"
HISTORICAL_QUESTION_FIELD = "cuest_modulo_envipe_7"
QUESTION_2025_FIELD = "cuest_modulo_envipe2025_2"

HISTORICAL_FRAUD_QUESTION = "4.1 ¿Qué tipo de fraude fue?"
HISTORICAL_EXTORTION_QUESTION = "5.1 ¿La extorsión fue...?"
HISTORICAL_EXTORTION_QUESTION_2025 = "5.1 ¿La extorsión fue de tipo...?"
QUESTION_1_5A_2025 = "1.5a ¿El (DELITO) se realizó por medio de...?"

ALL_CRIMES_SECTION = "SECCIÓN I. TODOS LOS TIPOS DE DELITO"
TELECOM_EDITION = 2025

SECTION_BY_CRIME = {
    "Fraude": "SECCIÓN IV. FRAUDE",
    "Extorsión": "SECCIÓN V. EXTORSIÓN",
}

# Catálogos de respuesta de BP4_1.
FRAUD_OPTIONS_BY_EDITION: dict[int, dict[str, str]] = {
    2011: {
        "1": "Cheque falso",
        "2": "Pago por un servicio/producto no entregado (al consumidor)",
        "3": "Por internet/correo electrónico",
        "4": "Otro",
        "9": "No especificado",
    },
    2012: {
        "1": "Cheque falso",
        "2": "Pago por un servicio/producto no entregado (al consumidor)",
        "3": "Tarjeta de débito o crédito",
        "4": "Por internet/correo electrónico",
        "5": "Otro",
        "9": "No especificado",
    },
    2013: {
        "1": "Cheque falso o sin fondos",
        "2": "Dinero falso",
        "3": "Pago por un servicio/producto no entregado (al consumidor)",
        "4": "Tarjeta de débito o crédito",
        "5": "Por internet/correo electrónico",
        "6": "Otro",
        "9": "No especificado",
    },
}

FRAUD_OPTIONS_2014_ONWARD = {
    "1": "Pago por un servicio/producto no entregado (al consumidor)",
    "2": "Cheque falso o sin fondos",
    "3": "Dinero falso",
    "4": "Tarjeta de débito o crédito",
    "5": "Por internet/correo electrónico",
    "6": "Otro",
    "9": "No especificado",
}

EXTORTION_OPTIONS_HISTORICAL = {
    "1": "Telefónica",
    "2": "Laboral",
    "3": "Por internet/correo electrónico",
    "4": "En la calle",
    "5": "En negocio propio o familiar",
    "6": "Cobro de piso",
    "7": "Otro",
    "9": "No especificado",
}

EXTORTION_OPTIONS_2025 = {
    "1": "Laboral",
    "2": "Cobro de piso",
    "3": "Otro",
    "9": "No especificado",
}

HISTORICAL_BANK_FRAUD_KEY = "BPCOD_06"
MISSING_RESPONSE_KEY = "__SIN_RESPUESTA__"

TELECOM_REQUIRED_FIELDS = {
    "BPCOD",
    "FAC_DEL",
    "BP1_5A_1",  # Internet o medios electrónicos
    "BP1_5A_2",  # Llamada telefónica
    "BP1_5A_3",  # Contacto presencial
    "BP1_5A_4",  # Otro medio
}

INTERNET_CATEGORY = "Internet o medios electrónicos"
PHONE_CATEGORY = "Llamada telefónica"
IN_PERSON_CATEGORY = "Contacto presencial"
OTHER_CATEGORY = "Otro medio"
UNSPECIFIED_CATEGORY = "Sin medio sustantivo"

QUESTION_1_5A_CATEGORY_ORDER = (
    INTERNET_CATEGORY,
    PHONE_CATEGORY,
    IN_PERSON_CATEGORY,
    OTHER_CATEGORY,
    UNSPECIFIED_CATEGORY,
)


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


@dataclass
class CrimeResult:
    total: WeightedCount
    modalities: dict[str, WeightedCount]


@dataclass
class EditionResult:
    edition: int
    source: InputSource
    crimes: dict[str, CrimeResult]
    invalid_weights: int


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
    if not math.isfinite(weight) or weight < 0:
        return None
    return weight


def parse_edition_from_text(text: str) -> int | None:
    normalized = text.replace("\\", "/")
    matches = re.findall(
        r"envipe[^0-9]{0,12}(20\d{2}|\d{2})(?!\d)",
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
        if PurePosixPath(name).name.lower() == TARGET_DBF_NAME
    ]
    if len(matches) > 1:
        raise ValueError(
            "El ZIP contiene más de un TMod_Vic.dbf: " + ", ".join(matches)
        )
    return matches[0] if matches else None


def discover_sources(
    root: Path,
    start_edition: int = MIN_EDITION,
    end_edition: int = MAX_EDITION,
) -> list[InputSource]:
    """Encuentra un TMod_Vic.dbf por edición, suelto o dentro de ZIP."""
    candidates: dict[int, list[InputSource]] = defaultdict(list)
    if not root.exists():
        return []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if path.name.lower() == TARGET_DBF_NAME:
            edition = parse_edition_from_text(str(path))
            if edition and start_edition <= edition <= end_edition:
                candidates[edition].append(InputSource(edition, path, "dbf"))

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
                candidates[edition].append(InputSource(edition, path, "zip", entry))

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


def sha256_source(source: InputSource) -> str:
    digest = hashlib.sha256()
    with open_source(source) as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def fraud_total_codes(edition: int) -> tuple[str, ...]:
    # ENVIPE 2011-2012: BPCOD 06 = fraude bancario y 07 = consumidor.
    return ("06", "07") if edition <= 2012 else ("07", "08")


def extortion_code(edition: int) -> str:
    return "08" if edition <= 2012 else "09"


def fraud_options(edition: int) -> dict[str, str]:
    if edition in FRAUD_OPTIONS_BY_EDITION:
        return FRAUD_OPTIONS_BY_EDITION[edition]
    return FRAUD_OPTIONS_2014_ONWARD


def extortion_options(edition: int) -> dict[str, str]:
    return EXTORTION_OPTIONS_2025 if edition == 2025 else EXTORTION_OPTIONS_HISTORICAL


def process_source(source: InputSource) -> EditionResult:
    """Calcula totales y modalidades de Fraude y Extorsión para una edición."""
    required = {"BPCOD", "FAC_DEL", "BP4_1", "BP5_1"}
    totals = {crime: WeightedCount() for crime in TARGET_CRIMES}
    modalities: dict[str, dict[str, WeightedCount]] = {
        crime: defaultdict(WeightedCount) for crime in TARGET_CRIMES
    }
    invalid_weights = 0

    fraud_codes = set(fraud_total_codes(source.edition))
    ext_code = extortion_code(source.edition)

    with open_source(source) as fh:
        for row in iter_selected_records(fh, required):
            weight = parse_weight(row.get("FAC_DEL", ""))
            if weight is None:
                invalid_weights += 1
                continue

            crime_code = normalize_code(row.get("BPCOD", ""), width=2)

            if crime_code in fraud_codes:
                totals["Fraude"].add(weight)
                if source.edition <= 2012 and crime_code == "06":
                    # BP4_1 no se aplica a BPCOD 06. Se integra como una
                    # modalidad directa para que el desglose cierre al total.
                    modalities["Fraude"][HISTORICAL_BANK_FRAUD_KEY].add(weight)
                else:
                    response = normalize_code(row.get("BP4_1", ""))
                    key = response or MISSING_RESPONSE_KEY
                    modalities["Fraude"][key].add(weight)

            if crime_code == ext_code:
                totals["Extorsión"].add(weight)
                response = normalize_code(row.get("BP5_1", ""))
                key = response or MISSING_RESPONSE_KEY
                modalities["Extorsión"][key].add(weight)

    crimes = {
        crime: CrimeResult(total=totals[crime], modalities=dict(modalities[crime]))
        for crime in TARGET_CRIMES
    }
    return EditionResult(
        edition=source.edition,
        source=source,
        crimes=crimes,
        invalid_weights=invalid_weights,
    )


def modality_label(edition: int, crime: str, key: str) -> str:
    if key == HISTORICAL_BANK_FRAUD_KEY:
        return "Clonación de tarjeta o fraude bancario (BPCOD 06)"
    if key == MISSING_RESPONSE_KEY:
        return "Sin respuesta en la variable de modalidad"

    catalog = fraud_options(edition) if crime == "Fraude" else extortion_options(edition)
    return catalog.get(key, f"Código {key} (sin etiqueta en el catálogo)")


def modality_sort_key(edition: int, crime: str, key: str) -> tuple[int, int, str]:
    if key == HISTORICAL_BANK_FRAUD_KEY:
        return (0, 0, key)
    if key == MISSING_RESPONSE_KEY:
        return (3, 9999, key)
    try:
        number = int(key)
    except ValueError:
        number = 9998
    known = key in (fraud_options(edition) if crime == "Fraude" else extortion_options(edition))
    return (1 if known else 2, number, key)


def historical_question_label(edition: int, crime: str, key: str) -> str:
    """Pregunta histórica que originó la modalidad de una fila.

    Los registros de fraude bancario BPCOD 06 de ENVIPE 2011-2012 no
    provienen de BP4_1; se incorporan directamente para cerrar el total y,
    por indicación metodológica, se identifican con NA en esta columna.
    """
    if key == HISTORICAL_BANK_FRAUD_KEY:
        return NA_VALUE
    if crime == "Fraude":
        return HISTORICAL_FRAUD_QUESTION
    if edition == TELECOM_EDITION:
        return HISTORICAL_EXTORTION_QUESTION_2025
    return HISTORICAL_EXTORTION_QUESTION


def build_reduced_rows(results: list[EditionResult]) -> list[dict[str, object]]:
    """Construye las filas de las preguntas históricas del módulo."""
    rows: list[dict[str, object]] = []

    for result in sorted(results, key=lambda item: item.edition):
        year = result.edition - 1
        for crime in TARGET_CRIMES:
            crime_result = result.crimes[crime]
            total_exact = crime_result.total.estimate
            total_rounded = int(round(total_exact))

            for key in sorted(
                crime_result.modalities,
                key=lambda item: modality_sort_key(result.edition, crime, item),
            ):
                count = crime_result.modalities[key]
                if count.estimate == 0:
                    continue
                percentage = (
                    round(count.estimate / total_exact * 100, 4)
                    if total_exact > 0
                    else ""
                )
                rows.append(
                    {
                        "anio": year,
                        "seccion": SECTION_BY_CRIME[crime],
                        "delito": crime,
                        "modalidad_comision": modality_label(result.edition, crime, key),
                        HISTORICAL_QUESTION_FIELD: historical_question_label(
                            result.edition, crime, key
                        ),
                        QUESTION_2025_FIELD: NA_VALUE,
                        "estimacion": int(round(count.estimate)),
                        "porcentaje": percentage,
                        "total_delito": total_rounded,
                    }
                )

    return rows


def is_yes(row: dict[str, str], field: str) -> bool:
    """True únicamente cuando la opción multirrespuesta está marcada."""
    return normalize_code(row.get(field, "")) == "1"


def crime_from_2025_code(value: object) -> str | None:
    """Agrupa BPCOD 07 y 08 como Fraude, y BPCOD 09 como Extorsión."""
    code = normalize_code(value, width=2)
    if code in {"07", "08"}:
        return "Fraude"
    if code == "09":
        return "Extorsión"
    return None


def classify_question_1_5a_2025(row: dict[str, str]) -> str:
    """Asigna una categoría única para la pregunta multirrespuesta 1.5a.

    Para reproducir la partición que cierra exactamente con el total del
    delito se aplica la prioridad operativa acordada:

        internet > llamada > contacto presencial > otro.

    Si ninguno de los cuatro campos sustantivos está marcado, el registro se
    clasifica como "Sin medio sustantivo". La prioridad evita duplicar un
    delito cuando hay más de una respuesta marcada.
    """
    if is_yes(row, "BP1_5A_1"):
        return INTERNET_CATEGORY
    if is_yes(row, "BP1_5A_2"):
        return PHONE_CATEGORY
    if is_yes(row, "BP1_5A_3"):
        return IN_PERSON_CATEGORY
    if is_yes(row, "BP1_5A_4"):
        return OTHER_CATEGORY
    return UNSPECIFIED_CATEGORY


def process_2025_question_1_5a(
    source: InputSource,
) -> tuple[dict[str, dict[str, WeightedCount]], int]:
    """Procesa la pregunta 1.5a de ENVIPE 2025 sin sustituir BP4_1/BP5_1."""
    if source.edition != TELECOM_EDITION:
        raise ValueError(
            f"La pregunta 1.5a sólo se procesa para ENVIPE {TELECOM_EDITION}."
        )

    counts: dict[str, dict[str, WeightedCount]] = {
        crime: defaultdict(WeightedCount) for crime in TARGET_CRIMES
    }
    invalid_weights = 0

    with open_source(source) as fh:
        for row in iter_selected_records(fh, TELECOM_REQUIRED_FIELDS):
            crime = crime_from_2025_code(row.get("BPCOD", ""))
            if crime is None:
                continue

            weight = parse_weight(row.get("FAC_DEL", ""))
            if weight is None:
                invalid_weights += 1
                continue

            category = classify_question_1_5a_2025(row)
            counts[crime][category].add(weight)

    return counts, invalid_weights


def build_2025_question_1_5a_rows(
    counts: dict[str, dict[str, WeightedCount]],
) -> list[dict[str, object]]:
    """Construye el bloque adicional de la pregunta 1.5a para el año 2024."""
    rows: list[dict[str, object]] = []
    reference_year = TELECOM_EDITION - 1

    for crime in TARGET_CRIMES:
        crime_counts = counts[crime]
        total_exact = sum(item.estimate for item in crime_counts.values())
        total_rounded = int(round(total_exact))

        rounded_by_category = {
            category: int(round(crime_counts.get(category, WeightedCount()).estimate))
            for category in QUESTION_1_5A_CATEGORY_ORDER
        }

        # El ajuste sólo resuelve diferencias por redondeo de ponderadores
        # decimales; no altera la clasificación de los registros.
        rounding_difference = total_rounded - sum(rounded_by_category.values())
        if rounding_difference:
            rounded_by_category[UNSPECIFIED_CATEGORY] += rounding_difference
            logging.warning(
                "ENVIPE 2025 %s: ajuste de redondeo de %+d aplicado a '%s'",
                crime,
                rounding_difference,
                UNSPECIFIED_CATEGORY,
            )

        for category in QUESTION_1_5A_CATEGORY_ORDER:
            count = crime_counts.get(category, WeightedCount())
            estimate = rounded_by_category[category]
            percentage = (
                round(count.estimate / total_exact * 100, 4)
                if total_exact > 0
                else ""
            )
            rows.append(
                {
                    "anio": reference_year,
                    "seccion": ALL_CRIMES_SECTION,
                    "delito": crime,
                    "modalidad_comision": category,
                    HISTORICAL_QUESTION_FIELD: NA_VALUE,
                    QUESTION_2025_FIELD: QUESTION_1_5A_2025,
                    "estimacion": estimate,
                    "porcentaje": percentage,
                    "total_delito": total_rounded,
                }
            )

        written_total = sum(rounded_by_category.values())
        if written_total != total_rounded:
            raise RuntimeError(
                f"ENVIPE 2025 {crime}: la pregunta 1.5a suma {written_total:,}, "
                f"pero total_delito es {total_rounded:,}."
            )

        logging.info(
            "ENVIPE 2025 %s, pregunta 1.5a: internet=%s, llamada=%s, "
            "presencial=%s, otro=%s, sin_medio=%s, total=%s",
            crime,
            f"{rounded_by_category[INTERNET_CATEGORY]:,}",
            f"{rounded_by_category[PHONE_CATEGORY]:,}",
            f"{rounded_by_category[IN_PERSON_CATEGORY]:,}",
            f"{rounded_by_category[OTHER_CATEGORY]:,}",
            f"{rounded_by_category[UNSPECIFIED_CATEGORY]:,}",
            f"{total_rounded:,}",
        )

    return rows


def write_reduced_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=REDUCED_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
