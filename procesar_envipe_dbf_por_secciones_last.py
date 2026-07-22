#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Procesa TMod_Vic.dbf de ENVIPE 2011-2025 y genera UN SOLO CSV,
organizado por las secciones del Módulo sobre victimización.

Este script no requiere nada más que Python 3.10+ y su biblioteca
estándar: no hay que instalar dependencias ni preparar los datos a
mano. Si los microdatos de una edición no están en el directorio de
trabajo, el programa los descarga automáticamente desde el sitio del
INEGI antes de procesarlos. Basta con ejecutar:

    python procesar_envipe_dbf_por_secciones.py

y el programa descarga (si hace falta), procesa y genera el CSV.

Cambios de esta versión:
- No genera las columnas "Categoría" ni "Base de referencia del porcentaje".
- Agrega "total_delito", repetido en todas las filas del delito correspondiente.
- Usa las siete secciones observadas en el cuestionario ENVIPE 2016:
  I. Todos los tipos de delito
  II. Robo total de vehículo
  III. Robo en casa habitación, asalto en la calle o transporte público
       o robo distinto de los anteriores
  IV. Fraude
  V. Extorsión
  VI. Secuestro para exigir dinero o bienes
  VII. Hostigamiento, manoseo, exhibicionismo, intento de violación
- Mantiene los desgloses disponibles en el programa original: fraude,
  extorsión y, para ENVIPE 2025, medio de comisión y lugar de la
  extorsión presencial.
- Descarga automáticamente los ZIP de microdatos del INEGI que falten
  en el directorio de trabajo (ver DOWNLOAD_URLS).
- Si una edición falla al procesarse, el programa avisa y continúa con
  las demás en vez de abortar todo el lote (usa --require-all para
  recuperar el comportamiento estricto anterior).
- Permite validar el CSV generado contra un archivo de referencia con
  --validate-against.

La edición ENVIPE N corresponde al año de referencia N-1.
El programa usa FAC_DEL como factor de expansión, procesa los DBF
registro por registro y también puede leer TMod_Vic.dbf dentro de ZIP.
No calcula error estándar, CV ni intervalos de confianza.

Uso:
    # Modo "todo automático": descarga lo que falte y procesa 2011-2025
    python procesar_envipe_dbf_por_secciones.py

    # Usar un directorio propio y un nombre de salida distinto
    python procesar_envipe_dbf_por_secciones.py --dir conjunto_de_datos \
        --salida ENVIPE_DESGLOSE_POR_SECCIONES.csv

    # Solo descargar los ZIP, sin procesar todavía
    python procesar_envipe_dbf_por_secciones.py --only-download

    # No descargar nada; usar solo lo que ya esté en --dir
    python procesar_envipe_dbf_por_secciones.py --no-download

    # Validar el CSV generado contra una versión de referencia
    python procesar_envipe_dbf_por_secciones.py \
        --validate-against ENVIPE_DESGLOSE_POR_SECCIONES_EJEMPLO.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import shutil
import struct
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator


MIN_EDITION = 2011
MAX_EDITION = 2025
TARGET_DBF_NAME = "tmod_vic.dbf"
DEFAULT_OUTPUT = "ENVIPE_DESGLOSE_POR_SECCIONES.csv"
DEFAULT_ENCODING = "latin-1"

# Nombres de las variables del DBF que usa el programa. Centralizados
# aquí para no repetir literales sueltos en process_records/required_fields.
FIELD_CRIME_CODE = "BPCOD"
FIELD_WEIGHT = "FAC_DEL"
FIELD_FRAUD_RESPONSE = "BP4_1"
FIELD_EXTORTION_RESPONSE = "BP5_1"
FIELD_MEDIUM_PREFIX = "BP1_5A_"          # + código de MEDIUM_OPTIONS_2025
FIELD_EXTORTION_PLACE_PREFIX = "BP5_1A_"  # + código de EXTORTION_PLACE_OPTIONS_2025

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

# URL oficial del ZIP de microdatos de cada edición en inegi.org.mx.
# La edición ENVIPE N corresponde al año de referencia N-1 (ver docstring).
DOWNLOAD_URLS: dict[int, str] = {
    2011: "https://www.inegi.org.mx/contenidos/programas/envipe/2011/microdatos/base_de_datos_envipe_2011_dbf.zip",
    2012: "https://www.inegi.org.mx/contenidos/programas/envipe/2012/microdatos/base_de_datos_envipe_2012_dbf.zip",
    2013: "https://www.inegi.org.mx/contenidos/programas/envipe/2013/microdatos/bd_envipe13_dbf.zip",
    2014: "https://www.inegi.org.mx/contenidos/programas/envipe/2014/microdatos/bd_envipe2014_dbf.zip",
    2015: "https://www.inegi.org.mx/contenidos/programas/envipe/2015/microdatos/bd_envipe2015_dbf.zip",
    2016: "https://www.inegi.org.mx/contenidos/programas/envipe/2016/microdatos/bd_envipe2016_dbf.zip",
    2017: "https://www.inegi.org.mx/contenidos/programas/envipe/2017/microdatos/bd_envipe2017_dbf.zip",
    2018: "https://www.inegi.org.mx/contenidos/programas/envipe/2018/microdatos/bd_envipe2018_dbf.zip",
    2019: "https://www.inegi.org.mx/contenidos/programas/envipe/2019/Microdatos/bd_envipe2019_dbf.zip",
    2020: "https://www.inegi.org.mx/contenidos/programas/envipe/2020/microdatos/bd_envipe_2020_dbf.zip",
    2021: "https://www.inegi.org.mx/contenidos/programas/envipe/2021/microdatos/bd_envipe_2021_dbf.zip",
    2022: "https://www.inegi.org.mx/contenidos/programas/envipe/2022/microdatos/bd_envipe_2022_dbf.zip",
    2023: "https://www.inegi.org.mx/contenidos/programas/envipe/2023/microdatos/bd_envipe_2023_dbf.zip",
    2024: "https://www.inegi.org.mx/contenidos/programas/envipe/2024/microdatos/bd_envipe_2024_dbf.zip",
    2025: "https://www.inegi.org.mx/contenidos/programas/envipe/2025/microdatos/bd_envipe_2025_dbf.zip",
}

DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (compatible; ENVIPE-procesador/1.0; "
    "script de procesamiento de microdatos publicos)"
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
    fields = {
        FIELD_CRIME_CODE,
        FIELD_WEIGHT,
        FIELD_FRAUD_RESPONSE,
        FIELD_EXTORTION_RESPONSE,
    }
    if edition == 2025:
        fields.update(
            f"{FIELD_MEDIUM_PREFIX}{option}" for option in MEDIUM_OPTIONS_2025
        )
        fields.update(
            f"{FIELD_EXTORTION_PLACE_PREFIX}{option}"
            for option in EXTORTION_PLACE_OPTIONS_2025
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


# ---------------------------------------------------------------------------
# Descarga automática de microdatos desde el INEGI
# ---------------------------------------------------------------------------
#
# Este bloque permite que el programa se ejecute "de cero": si el ZIP de una
# edición no existe en el directorio de trabajo, se descarga desde la URL
# oficial en DOWNLOAD_URLS antes de procesarla. No es necesario preparar los
# datos a mano ni instalar nada fuera de la biblioteca estándar de Python.


def local_zip_name(edition: int) -> str:
    """Nombre de archivo local y canónico para el ZIP de una edición.

    Se usa siempre este nombre (en vez del nombre original de INEGI, que
    varía de edición a edición) para que discover_sources() reconozca la
    edición de forma inequívoca a partir del nombre del archivo.
    """
    return f"envipe_{edition}.zip"


def download_zip(
    edition: int,
    dest_dir: Path,
    *,
    force: bool = False,
    timeout: float = 180.0,
    retries: int = 3,
) -> Path:
    """Descarga el ZIP de microdatos de una edición desde el INEGI.

    Reintenta ante errores de red, valida que lo descargado sea un ZIP
    válido que contenga TMod_Vic.dbf, y descarga a un archivo temporal
    para no dejar un ZIP a medias si el proceso se interrumpe.
    """
    url = DOWNLOAD_URLS.get(edition)
    if not url:
        raise ValueError(
            f"No hay URL de descarga registrada para ENVIPE {edition}"
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / local_zip_name(edition)

    if dest_path.exists() and not force:
        if zipfile.is_zipfile(dest_path):
            logging.info(
                "ENVIPE %s: ya existe %s, no se vuelve a descargar",
                edition,
                dest_path,
            )
            return dest_path
        logging.warning(
            "ENVIPE %s: %s existe pero no es un ZIP válido; se descarga de nuevo",
            edition,
            dest_path,
        )

    tmp_path = dest_path.with_suffix(".zip.part")
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": DOWNLOAD_USER_AGENT}
            )
            logging.info(
                "ENVIPE %s: descargando (intento %d/%d) %s",
                edition,
                attempt,
                retries,
                url,
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                with tmp_path.open("wb") as out_file:
                    shutil.copyfileobj(response, out_file, length=1024 * 1024)

            if not zipfile.is_zipfile(tmp_path):
                raise ValueError("el archivo descargado no es un ZIP válido")
            with zipfile.ZipFile(tmp_path) as zf:
                if not find_tmod_entry(zf):
                    raise ValueError(
                        "el ZIP descargado no contiene TMod_Vic.dbf"
                    )

            tmp_path.replace(dest_path)
            logging.info("ENVIPE %s: descarga completa (%s)", edition, dest_path)
            return dest_path

        except (
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            OSError,
            zipfile.BadZipFile,
        ) as exc:
            last_error = exc
            tmp_path.unlink(missing_ok=True)
            logging.warning(
                "ENVIPE %s: intento %d/%d falló (%s)",
                edition,
                attempt,
                retries,
                exc,
            )
            if attempt < retries:
                time.sleep(min(2**attempt, 30))

    raise RuntimeError(
        f"no se pudo descargar ENVIPE {edition} tras {retries} intento(s): "
        f"{last_error}"
    ) from last_error


def ensure_local_sources(
    root: Path,
    start_edition: int,
    end_edition: int,
    *,
    auto_download: bool,
    force_download: bool,
    timeout: float,
    retries: int,
) -> tuple[list["InputSource"], dict[int, str]]:
    """Descubre los archivos ya presentes y, si hace falta, descarga el resto.

    Devuelve la lista de fuentes utilizables y un diccionario con los
    errores de descarga por edición (vacío si todo salió bien o si la
    descarga automática está desactivada).
    """
    root.mkdir(parents=True, exist_ok=True)
    sources = discover_sources(root, start_edition, end_edition)
    found = {source.edition for source in sources}
    expected = set(range(start_edition, end_edition + 1))
    missing = sorted(expected - found)

    download_errors: dict[int, str] = {}

    if force_download or (auto_download and missing):
        targets = sorted(expected) if force_download else missing
        for edition in targets:
            if edition not in DOWNLOAD_URLS:
                download_errors[edition] = "sin URL de descarga registrada"
                continue
            try:
                download_zip(
                    edition,
                    root,
                    force=force_download,
                    timeout=timeout,
                    retries=retries,
                )
            except Exception as exc:
                download_errors[edition] = str(exc)
                logging.error(
                    "ENVIPE %s: no se pudo descargar (%s)", edition, exc
                )

        sources = discover_sources(root, start_edition, end_edition)

    return sources, download_errors


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
    encoding: str = DEFAULT_ENCODING,
) -> Iterator[dict[str, str]]:
    record_count, record_size, fields, all_names = read_dbf_layout(
        fh, selected_columns
    )

    missing = sorted(selected_columns - all_names)
    if missing:
        raise ValueError("Faltan variables en el DBF: " + ", ".join(missing))

    read_count = 0
    for _ in range(record_count):
        record = fh.read(record_size)
        if not record or record[0:1] == b"\x1a":
            break
        if len(record) < record_size:
            raise ValueError("Registro DBF truncado")
        read_count += 1
        if record[0:1] == b"*":
            continue

        yield {
            field.name: record[
                field.position : field.position + field.length
            ].decode(encoding, errors="replace").strip()
            for field in fields
        }

    if read_count < record_count:
        logging.warning(
            "El DBF declara %d registros pero solo se leyeron %d "
            "(posible archivo truncado o marca de fin de archivo temprana)",
            record_count,
            read_count,
        )


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
        weight = parse_weight(row.get(FIELD_WEIGHT, ""))
        if weight is None:
            invalid_weights += 1
            continue

        crime = normalize_code(row.get(FIELD_CRIME_CODE, ""), width=2)
        if crime not in crimes:
            continue

        crimes[crime].add(weight)

        if crime in fraud_codes:
            response = normalize_code(row.get(FIELD_FRAUD_RESPONSE, ""))
            if response in fraud_counts:
                fraud_counts[response].add(weight)

        if crime == extortion_code:
            response = normalize_code(row.get(FIELD_EXTORTION_RESPONSE, ""))
            if response in extortion_counts:
                extortion_counts[response].add(weight)

        if edition == 2025 and crime in MEDIUM_APPLICABLE_CRIMES_2025:
            for option in MEDIUM_OPTIONS_2025:
                field = f"{FIELD_MEDIUM_PREFIX}{option}"
                if is_selected_multi(row.get(field, "")):
                    medium_counts[(crime, option)].add(weight)

            if crime == "09" and is_selected_multi(
                row.get(f"{FIELD_MEDIUM_PREFIX}3", "")
            ):
                extortion_presential_base.add(weight)
                for option in EXTORTION_PLACE_OPTIONS_2025:
                    field = f"{FIELD_EXTORTION_PLACE_PREFIX}{option}"
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

def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Validación contra un CSV de referencia (control de calidad opcional)
# ---------------------------------------------------------------------------
#
# No sustituye una comparación formal contra los tabulados publicados por
# el INEGI, pero permite detectar rápidamente si una edición nueva del
# programa (o una corrida contra datos actualizados) se desvía de un
# resultado previamente validado.

ROW_KEY_FIELDS = (
    "anio",
    "seccion",
    "codigo_delito",
    "pregunta",
    "modalidad_comision",
)


def row_key(row: dict[str, object]) -> tuple[str, ...]:
    return tuple(str(row[field]) for field in ROW_KEY_FIELDS)


def load_reference_rows(path: Path) -> dict[tuple[str, ...], dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing_columns = set(OUTPUT_FIELDS) - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(
                "El archivo de referencia no tiene las columnas esperadas: "
                + ", ".join(sorted(missing_columns))
            )
        return {row_key(row): row for row in reader}


def validate_against_reference(
    rows: list[dict[str, object]],
    reference_path: Path,
    tolerance_pct: float,
) -> None:
    """Compara 'estimacion' fila por fila contra un CSV de referencia.

    Registra advertencias (no interrumpe la ejecución) si hay filas que
    solo existen en uno de los dos archivos, o si 'estimacion' difiere
    más de tolerance_pct por ciento entre ambos.
    """
    reference = load_reference_rows(reference_path)
    generated = {row_key(row): row for row in rows}

    only_reference = sorted(set(reference) - set(generated))
    only_generated = sorted(set(generated) - set(reference))
    common = sorted(set(reference) & set(generated))

    mismatches: list[tuple[tuple[str, ...], float, float, float]] = []
    for key in common:
        try:
            ref_value = float(reference[key]["estimacion"])
            gen_value = float(generated[key]["estimacion"])
        except (KeyError, ValueError):
            continue
        base = max(abs(ref_value), 1.0)
        diff_pct = abs(gen_value - ref_value) / base * 100
        if diff_pct > tolerance_pct:
            mismatches.append((key, ref_value, gen_value, diff_pct))

    logging.info(
        "Validación: %d filas de referencia, %d filas generadas, %d en común",
        len(reference),
        len(generated),
        len(common),
    )
    if only_reference:
        logging.warning(
            "%d filas están en la referencia pero no en lo generado "
            "(ejemplo: %s)",
            len(only_reference),
            only_reference[0],
        )
    if only_generated:
        logging.warning(
            "%d filas están en lo generado pero no en la referencia "
            "(ejemplo: %s)",
            len(only_generated),
            only_generated[0],
        )
    if mismatches:
        logging.warning(
            "%d filas superan la tolerancia de %.2f%% en 'estimacion':",
            len(mismatches),
            tolerance_pct,
        )
        for key, ref_value, gen_value, diff_pct in mismatches[:20]:
            logging.warning(
                "  %s -> referencia=%.0f generado=%.0f (%.2f%% de diferencia)",
                key,
                ref_value,
                gen_value,
                diff_pct,
            )
        if len(mismatches) > 20:
            logging.warning(
                "  ... y %d fila(s) más con diferencias", len(mismatches) - 20
            )
    elif not only_reference and not only_generated:
        logging.info(
            "Validación OK: todas las filas coinciden dentro de la tolerancia."
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

    # DOWNLOAD_URLS debe cubrir exactamente el rango de ediciones soportado,
    # y el nombre de archivo local canónico debe parsear de vuelta a la
    # misma edición (esto no requiere red).
    assert set(DOWNLOAD_URLS) == set(range(MIN_EDITION, MAX_EDITION + 1)), (
        "DOWNLOAD_URLS no cubre exactamente MIN_EDITION..MAX_EDITION"
    )
    for edition, url in DOWNLOAD_URLS.items():
        assert url.startswith("https://www.inegi.org.mx/"), (
            f"URL sospechosa para ENVIPE {edition}: {url}"
        )
        parsed = parse_edition_from_text(local_zip_name(edition))
        assert parsed == edition, (
            f"local_zip_name({edition}) no se reconoce como esa edición"
        )

    print("Self-test OK")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Procesa TMod_Vic.dbf de ENVIPE y genera un CSV por secciones, "
            "con total_delito repetido en las filas correspondientes. "
            "Por defecto, descarga automáticamente del INEGI las ediciones "
            "que falten en --dir: no requiere preparación manual de datos."
        )
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("conjunto_de_datos"),
        help="Directorio con DBF/ZIP de ENVIPE (se crea si no existe).",
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
        help=(
            "Detiene el proceso si falta o falla alguna edición, en vez "
            "de continuar con las demás."
        ),
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="No descargar nada; usar solo lo que ya esté en --dir.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Descargar de nuevo todas las ediciones, aunque ya existan.",
    )
    parser.add_argument(
        "--only-download",
        action="store_true",
        help="Descargar los ZIP que falten y salir, sin procesar.",
    )
    parser.add_argument(
        "--download-timeout",
        type=float,
        default=180.0,
        help="Tiempo máximo (segundos) por intento de descarga.",
    )
    parser.add_argument(
        "--download-retries",
        type=int,
        default=3,
        help="Reintentos por edición ante errores de descarga.",
    )
    parser.add_argument(
        "--encoding",
        default=DEFAULT_ENCODING,
        help=f"Codificación de texto del DBF. Predeterminada: {DEFAULT_ENCODING}",
    )
    parser.add_argument(
        "--validate-against",
        type=Path,
        default=None,
        help="CSV de referencia contra el cual comparar el resultado generado.",
    )
    parser.add_argument(
        "--validate-tolerance",
        type=float,
        default=0.5,
        help="Tolerancia (%%) para la validación. Predeterminada: 0.5",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.self_test:
        run_self_test()
        return

    try:
        sources, download_errors = ensure_local_sources(
            args.dir,
            args.start_edition,
            args.end_edition,
            auto_download=not args.no_download,
            force_download=args.force_download,
            timeout=args.download_timeout,
            retries=args.download_retries,
        )
    except Exception as exc:
        raise SystemExit(f"Error al buscar o descargar archivos: {exc}") from exc

    if args.only_download:
        if download_errors:
            for edition, message in sorted(download_errors.items()):
                logging.error("ENVIPE %s: %s", edition, message)
            raise SystemExit(
                f"Fallaron {len(download_errors)} descarga(s). "
                "Revisa tu conexión o descarga esas ediciones a mano en "
                "https://www.inegi.org.mx/programas/envipe/ y colócalas "
                f"en {args.dir}."
            )
        print(f"Descarga completa en: {args.dir}")
        return

    if not sources:
        details = ""
        if download_errors:
            details = " Errores de descarga: " + "; ".join(
                f"{edition} ({message})"
                for edition, message in sorted(download_errors.items())
            )
        raise SystemExit(
            "No se encontraron archivos TMod_Vic.dbf ni fue posible "
            "descargarlos automáticamente." + details
        )

    found = {source.edition for source in sources}
    expected = set(range(args.start_edition, args.end_edition + 1))
    missing = sorted(expected - found)
    if missing:
        reasons = "; ".join(
            f"{edition} ({download_errors[edition]})"
            if edition in download_errors
            else str(edition)
            for edition in missing
        )
        message = f"Faltan ediciones: {reasons}"
        if args.require_all:
            raise SystemExit(message)
        logging.warning(message)

    output_rows: list[dict[str, object]] = []
    failed_editions: dict[int, str] = {}

    for source in sources:
        logging.info(
            "Procesando ENVIPE %s: %s",
            source.edition,
            source.display_name,
        )
        try:
            with open_source(source) as fh:
                records = iter_selected_records(
                    fh, required_fields(source.edition), encoding=args.encoding
                )
                processed = process_records(source.edition, records)
            edition_rows = build_output_rows(source, processed)
        except Exception as exc:
            failed_editions[source.edition] = str(exc)
            logging.error(
                "ENVIPE %s: error de procesamiento (%s)", source.edition, exc
            )
            if args.require_all:
                raise SystemExit(
                    f"Error en ENVIPE {source.edition}: {exc}"
                ) from exc
            continue

        invalid = processed[-1]
        if invalid:
            logging.warning(
                "ENVIPE %s: se excluyeron %s registros con FAC_DEL inválido",
                source.edition,
                invalid,
            )

        output_rows.extend(edition_rows)

    if failed_editions:
        logging.warning(
            "No se pudieron procesar %d edición(es): %s",
            len(failed_editions),
            "; ".join(
                f"{edition} ({message})"
                for edition, message in sorted(failed_editions.items())
            ),
        )

    if not output_rows:
        raise SystemExit(
            "No se generó ninguna fila; revisa los errores anteriores."
        )

    output_rows.sort(
        key=lambda row: (
            int(row["anio"]),
            SECTION_ORDER.get(str(row["seccion"]), 99),
            str(row["codigo_delito"]),
            str(row["pregunta"]),
            str(row["modalidad_comision"]),
        )
    )

    write_csv(args.salida, output_rows)
    print(f"Archivo generado: {args.salida}")
    print(f"Filas: {len(output_rows)}")
    if missing or failed_editions:
        omitidas = sorted(set(missing) | set(failed_editions))
        print(f"Ediciones omitidas (revisa los WARNING arriba): {omitidas}")

    if args.validate_against is not None:
        try:
            validate_against_reference(
                output_rows, args.validate_against, args.validate_tolerance
            )
        except Exception as exc:
            raise SystemExit(f"Error al validar contra referencia: {exc}") from exc


if __name__ == "__main__":
    main()
