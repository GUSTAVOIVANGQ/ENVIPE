#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Valida ENVIPE_FRAUDE_EXTORSION.csv contra los XLSX oficiales de INEGI.

Flujo:
1. Lee el CSV generado por main.py.
2. Crea la carpeta "inegi".
3. Conserva los XLSX válidos que ya existan y descarga los faltantes.
4. Extrae los totales nacionales de Fraude y Extorsión.
5. Genera VALIDACION_INEGI_ENVIPE.csv con URL, hoja, celda y SHA-256.

Uso normal:
  python validar_inegi.py

Forzar descargas:
  python validar_inegi.py --force-download

Usar únicamente archivos ya descargados:
  python validar_inegi.py --no-download
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import re
import shutil
import ssl
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable
from xml.etree import ElementTree as ET

from envipe_core import (
    DEFAULT_DATA_CSV,
    DEFAULT_DBF_DIR,
    DEFAULT_INEGI_DIR,
    DEFAULT_ROOT,
    DEFAULT_VALIDATION_CSV,
    MAX_EDITION,
    MIN_EDITION,
    NA_VALUE,
    QUESTION_2025_FIELD,
    REDUCED_FIELDS,
    TARGET_CRIMES,
    discover_sources,
    sha256_file,
    sha256_source,
)

METADATA_IDS = {
    2011: 182,
    2012: 179,
    2013: 169,
    2014: 128,
    2015: 153,
    2016: 216,
    2017: 288,
    2018: 384,
    2019: 519,
    2020: 624,
    2021: 698,
    2022: 803,
    2023: 913,
    2024: 1027,
    2025: 1130,
}

VALIDATION_FIELDS = [
    "edicion_envipe",
    "anio_referencia",
    "tipo_validacion",
    "delito",
    "valor_csv",
    "valor_inegi",
    "diferencia",
    "diferencia_porcentual",
    "estatus",
    "filas_modalidad_csv",
    "archivo_csv",
    "sha256_csv",
    "archivo_inegi",
    "hoja_inegi",
    "celda_etiqueta_inegi",
    "celda_valor_inegi",
    "encabezado_valor_inegi",
    "metodo_extraccion_inegi",
    "url_archivo_inegi",
    "sha256_archivo_inegi",
    "estado_descarga_inegi",
    "fuente_microdatos",
    "sha256_microdatos",
    "url_programa_inegi",
    "url_metadatos_inegi",
    "fecha_ejecucion_utc",
    "nota",
]

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": MAIN_NS, "r": DOC_REL_NS, "pr": PKG_REL_NS}


HISTORICAL_GROUP = "PREGUNTAS_HISTÓRICAS"
QUESTION_1_5A_GROUP = "PREGUNTA_1.5A_ENVIPE2025"


@dataclass
class CsvMetrics:
    total_values: set[int]
    modality_sums: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    row_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    row_count: int = 0

    @property
    def total(self) -> int | None:
        return next(iter(self.total_values)) if len(self.total_values) == 1 else None

    @property
    def total_note(self) -> str:
        if not self.total_values:
            return "No hay valores de total_delito."
        if len(self.total_values) > 1:
            return "total_delito no es constante: " + ", ".join(
                map(str, sorted(self.total_values))
            )
        return ""

    def modality_sum(self, group: str) -> int | None:
        return self.modality_sums.get(group)

    def group_row_count(self, group: str) -> int:
        return self.row_counts.get(group, 0)


@dataclass
class DownloadResult:
    path: Path
    url: str
    state: str
    error: str = ""


@dataclass(frozen=True)
class Cell:
    row: int
    col: int
    ref: str
    value: object


@dataclass
class SheetData:
    name: str
    rows: dict[int, dict[int, Cell]]

    @property
    def max_row(self) -> int:
        return max(self.rows, default=0)

    @property
    def max_col(self) -> int:
        return max((max(row, default=0) for row in self.rows.values()), default=0)

    def get(self, row: int, col: int) -> Cell | None:
        return self.rows.get(row, {}).get(col)


@dataclass
class OfficialCandidate:
    label: str
    value: int
    score: int
    sheet: str
    label_cell: str
    value_cell: str
    header: str
    context: str


@dataclass
class OfficialValue:
    crime: str
    value: int | None
    sheet: str = ""
    label_cell: str = ""
    value_cell: str = ""
    header: str = ""
    method: str = ""
    note: str = ""


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def relative_path_or_full(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except (ValueError, OSError):
        return str(path)


def normalize_text(value: object) -> str:
    text = str(value or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("\xa0", " ")
    text = re.sub(r"[\s,]", "", text).replace("−", "-")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def parse_int_csv(value: object, field: str, line: int) -> int:
    number = parse_number(value)
    if number is None:
        raise ValueError(f"Línea {line}: {field} no es numérico: {value!r}")
    return int(round(number))


def read_reduced_csv(
    path: Path,
    start_edition: int,
    end_edition: int,
) -> dict[tuple[int, str], CsvMetrics]:
    if not path.is_file():
        raise SystemExit(
            f"No existe el CSV principal: {path}\n"
            "Ejecute primero: python main.py"
        )

    result: dict[tuple[int, str], CsvMetrics] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [field for field in REDUCED_FIELDS if field not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit("Faltan columnas en el CSV principal: " + ", ".join(missing))

        for line, row in enumerate(reader, start=2):
            year = parse_int_csv(row.get("anio"), "anio", line)
            edition = year + 1
            if not (start_edition <= edition <= end_edition):
                continue
            crime = str(row.get("delito") or "").strip()
            if crime not in TARGET_CRIMES:
                continue

            key = (edition, crime)
            metrics = result.setdefault(key, CsvMetrics(total_values=set()))

            question_2025 = str(row.get(QUESTION_2025_FIELD) or "").strip()
            group = (
                QUESTION_1_5A_GROUP
                if question_2025 and question_2025.upper() != NA_VALUE
                else HISTORICAL_GROUP
            )
            metrics.modality_sums[group] += parse_int_csv(
                row.get("estimacion"), "estimacion", line
            )
            metrics.row_counts[group] += 1
            metrics.total_values.add(
                parse_int_csv(row.get("total_delito"), "total_delito", line)
            )
            metrics.row_count += 1

    return result


# ---------------------------------------------------------------------------
# Descarga de XLSX oficiales
# ---------------------------------------------------------------------------

def official_filename(edition: int) -> str:
    if edition == 2011:
        return "III_caracteristicas_victimas_2011_est.xlsx"
    return f"III_denuncia_delito_{edition}_est.xlsx"


def official_url_candidates(edition: int) -> list[str]:
    filename = official_filename(edition)
    base = f"https://www.inegi.org.mx/contenidos/programas/envipe/{edition}"
    urls = [
        f"{base}/tabulados/{filename}",
        f"{base}/Tabulados/{filename}",
    ]
    if edition == 2011:
        urls.extend(
            [
                f"{base}/tabulados/III_denuncia_delito_2011_est.xlsx",
                f"{base}/Tabulados/III_denuncia_delito_2011_est.xlsx",
            ]
        )
    return list(dict.fromkeys(urls))


def is_valid_xlsx(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 1024:
        return False
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            return "[Content_Types].xml" in names and "xl/workbook.xml" in names
    except (OSError, zipfile.BadZipFile):
        return False


def download_xlsx(
    edition: int,
    directory: Path,
    *,
    force: bool,
    timeout: int,
    retries: int,
) -> DownloadResult:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / official_filename(edition)

    if is_valid_xlsx(target) and not force:
        return DownloadResult(target, official_url_candidates(edition)[0], "EXISTENTE")

    if target.exists() and not is_valid_xlsx(target):
        logging.warning("Se elimina un archivo XLSX inválido: %s", target)
        target.unlink(missing_ok=True)

    errors: list[str] = []
    ssl_context = ssl.create_default_context()

    for url in official_url_candidates(edition):
        for attempt in range(1, retries + 1):
            temp_path = target.with_suffix(target.suffix + ".part")
            temp_path.unlink(missing_ok=True)
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                        ),
                        "Accept": (
                            "application/vnd.openxmlformats-officedocument."
                            "spreadsheetml.sheet,application/octet-stream,*/*"
                        ),
                    },
                )
                with urllib.request.urlopen(
                    request, timeout=timeout, context=ssl_context
                ) as response, temp_path.open("wb") as output:
                    shutil.copyfileobj(response, output)

                if not is_valid_xlsx(temp_path):
                    prefix = temp_path.read_bytes()[:80]
                    raise ValueError("La respuesta no es XLSX; inicio=" + repr(prefix))

                os.replace(temp_path, target)
                return DownloadResult(
                    target,
                    url,
                    "REDESCARGADO" if force else "DESCARGADO",
                )
            except (
                OSError,
                ValueError,
                urllib.error.URLError,
                urllib.error.HTTPError,
            ) as exc:
                temp_path.unlink(missing_ok=True)
                message = f"{url} intento {attempt}/{retries}: {exc}"
                errors.append(message)
                logging.warning("ENVIPE %s: %s", edition, message)
                if attempt < retries:
                    time.sleep(min(2 ** (attempt - 1), 5))

    return DownloadResult(
        target,
        official_url_candidates(edition)[0],
        "ERROR DESCARGA",
        " | ".join(errors),
    )


# ---------------------------------------------------------------------------
# Lector XLSX sin dependencias externas
# ---------------------------------------------------------------------------

def column_index_from_ref(reference: str) -> int:
    match = re.match(r"([A-Z]+)", reference.upper())
    if not match:
        raise ValueError(f"Referencia de celda inválida: {reference}")
    result = 0
    for char in match.group(1):
        result = result * 26 + (ord(char) - 64)
    return result


def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    return [
        "".join(node.text or "" for node in si.iter(f"{{{MAIN_NS}}}t"))
        for si in root.findall("m:si", NS)
    ]


def resolve_sheet_path(target: str) -> str:
    target = target.replace("\\", "/")
    if target.startswith("/"):
        target = target.lstrip("/")
    elif not target.startswith("xl/"):
        target = str(PurePosixPath("xl") / target)
    return str(PurePosixPath(target))


def read_workbook_sheets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: resolve_sheet_path(rel.attrib["Target"])
        for rel in rels.findall("pr:Relationship", NS)
        if rel.attrib.get("Type", "").endswith("/worksheet")
    }
    result: list[tuple[str, str]] = []
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        name = sheet.attrib.get("name", "")
        rel_id = sheet.attrib.get(f"{{{DOC_REL_NS}}}id", "")
        path = rel_map.get(rel_id)
        if path:
            result.append((name, path))
    return result


def parse_sheet(
    zf: zipfile.ZipFile,
    name: str,
    path: str,
    shared_strings: list[str],
) -> SheetData:
    root = ET.fromstring(zf.read(path))
    rows: dict[int, dict[int, Cell]] = defaultdict(dict)

    for node in root.findall(".//m:sheetData/m:row/m:c", NS):
        reference = node.attrib.get("r", "")
        row_match = re.search(r"(\d+)$", reference)
        if not reference or not row_match:
            continue
        col = column_index_from_ref(reference)
        row = int(row_match.group(1))
        cell_type = node.attrib.get("t", "")
        value: object = ""

        if cell_type == "inlineStr":
            inline = node.find("m:is", NS)
            if inline is not None:
                value = "".join(
                    text.text or "" for text in inline.iter(f"{{{MAIN_NS}}}t")
                )
        else:
            value_node = node.find("m:v", NS)
            raw = value_node.text if value_node is not None else ""
            if cell_type == "s":
                try:
                    value = shared_strings[int(raw)]
                except (ValueError, IndexError):
                    value = raw
            elif cell_type in {"str", "e"}:
                value = raw
            elif cell_type == "b":
                value = raw == "1"
            elif raw == "":
                value = ""
            else:
                try:
                    number = float(raw)
                    value = int(number) if number.is_integer() else number
                except ValueError:
                    value = raw

        rows[row][col] = Cell(row, col, reference, value)

    return SheetData(name=name, rows=dict(rows))


def read_xlsx(path: Path) -> list[SheetData]:
    with zipfile.ZipFile(path, "r") as zf:
        shared_strings = read_shared_strings(zf)
        return [
            parse_sheet(zf, name, sheet_path, shared_strings)
            for name, sheet_path in read_workbook_sheets(zf)
        ]


def is_exact_label(value: object, label: str) -> bool:
    text = normalize_text(value)
    target = normalize_text(label)
    pattern = (
        rf"^(?:\d+[.)-]?\s*)?{re.escape(target)}"
        rf"(?:\s*[\\/*-]?\s*\d+|\s*\*+)?$"
    )
    return re.fullmatch(pattern, text) is not None


def nearby_text(
    sheet: SheetData,
    row_start: int,
    row_end: int,
    col_start: int,
    col_end: int,
) -> str:
    values: list[str] = []
    for row in range(max(row_start, 1), min(row_end, sheet.max_row) + 1):
        for col in range(max(col_start, 1), min(col_end, sheet.max_col) + 1):
            cell = sheet.get(row, col)
            if cell and isinstance(cell.value, str) and cell.value.strip():
                values.append(cell.value.strip())
    return " | ".join(values)


def column_header(sheet: SheetData, row: int, col: int) -> str:
    labels: list[str] = []
    for current_row in range(max(1, row - 20), row):
        for current_col in range(max(1, col - 1), min(sheet.max_col, col + 1) + 1):
            cell = sheet.get(current_row, current_col)
            if cell and isinstance(cell.value, str) and cell.value.strip():
                labels.append(cell.value.strip())
    return " | ".join(labels[-8:])


def sheet_context(sheet: SheetData, label_row: int) -> str:
    top = nearby_text(sheet, 1, min(label_row - 1, 25), 1, min(sheet.max_col, 14))
    local = nearby_text(
        sheet,
        max(1, label_row - 8),
        label_row,
        1,
        min(sheet.max_col, 14),
    )
    return f"{top} | {local}".strip(" |")


def score_candidate(
    sheet: SheetData,
    label_cell: Cell,
    numeric_cell: Cell,
    value: float,
    header: str,
    context: str,
    first_numeric_col: int,
) -> int:
    score = 100
    sheet_name = normalize_text(sheet.name)
    header_n = normalize_text(header)
    context_n = normalize_text(context)

    if re.search(r"(^|\D)3[._ -]?1(\D|$)", sheet_name):
        score += 90
    if "delitos ocurridos por tipo" in context_n:
        score += 100
    elif "delitos ocurridos" in context_n:
        score += 60
    if "condicion de denuncia" in context_n:
        score += 35
    if "total" in header_n:
        score += 45
    if "delitos ocurridos" in header_n:
        score += 35
    if numeric_cell.col == first_numeric_col:
        score += 35
    if 100_000 <= value <= 100_000_000:
        score += 20
    if float(value).is_integer():
        score += 5

    if any(
        term in header_n
        for term in (
            "porcentaje",
            "coeficiente",
            "error estandar",
            "limite inferior",
            "limite superior",
            "tasa",
        )
    ):
        score -= 120
    if "tasa" in context_n and "delitos ocurridos" not in context_n:
        score -= 80
    if value <= 1000:
        score -= 150

    score -= max(numeric_cell.col - label_cell.col - 8, 0) * 2
    return score


def find_candidates(sheets: Iterable[SheetData], label: str) -> list[OfficialCandidate]:
    candidates: list[OfficialCandidate] = []
    for sheet in sheets:
        for row_number, row_cells in sheet.rows.items():
            for label_cell in row_cells.values():
                if not is_exact_label(label_cell.value, label):
                    continue

                numeric_cells: list[tuple[Cell, float]] = []
                for col in range(
                    label_cell.col + 1,
                    min(sheet.max_col, label_cell.col + 30) + 1,
                ):
                    cell = sheet.get(row_number, col)
                    if not cell:
                        continue
                    number = parse_number(cell.value)
                    if number is not None and number >= 1000:
                        numeric_cells.append((cell, number))

                if not numeric_cells:
                    continue

                first_numeric_col = numeric_cells[0][0].col
                context = sheet_context(sheet, row_number)
                for numeric_cell, number in numeric_cells:
                    header = column_header(sheet, row_number, numeric_cell.col)
                    candidates.append(
                        OfficialCandidate(
                            label=label,
                            value=int(round(number)),
                            score=score_candidate(
                                sheet,
                                label_cell,
                                numeric_cell,
                                number,
                                header,
                                context,
                                first_numeric_col,
                            ),
                            sheet=sheet.name,
                            label_cell=label_cell.ref,
                            value_cell=numeric_cell.ref,
                            header=header,
                            context=context,
                        )
                    )

    return sorted(candidates, key=lambda item: (-item.score, item.sheet, item.value_cell))


def extract_label_value(sheets: list[SheetData], label: str) -> OfficialValue:
    candidates = find_candidates(sheets, label)
    if not candidates:
        return OfficialValue(
            crime=label,
            value=None,
            method="Etiqueta exacta + cifra en la misma fila",
            note=f"No se encontró una fila agregada con la etiqueta {label!r}.",
        )

    best = candidates[0]
    if best.score < 120:
        return OfficialValue(
            crime=label,
            value=None,
            method="Etiqueta exacta + puntuación estructural",
            note=(
                f"Candidato insuficiente: {best.sheet}!{best.value_cell}="
                f"{best.value}, puntuación {best.score}."
            ),
        )

    if len(candidates) > 1:
        second = candidates[1]
        if second.value != best.value and second.score >= best.score - 8:
            return OfficialValue(
                crime=label,
                value=None,
                method="Etiqueta exacta + puntuación estructural",
                note=(
                    "Extracción ambigua: "
                    f"{best.sheet}!{best.value_cell}={best.value} ({best.score}) y "
                    f"{second.sheet}!{second.value_cell}={second.value} ({second.score})."
                ),
            )

    return OfficialValue(
        crime=label,
        value=best.value,
        sheet=best.sheet,
        label_cell=best.label_cell,
        value_cell=best.value_cell,
        header=re.sub(r"\s+", " ", best.header)[:250],
        method="Etiqueta exacta; cifra en la misma fila; prioridad a hoja 3.1 y columna Total",
        note="Contexto: " + re.sub(r"\s+", " ", best.context)[:300],
    )


def extract_fraud_value(sheets: list[SheetData]) -> OfficialValue:
    aggregate = extract_label_value(sheets, "Fraude")
    if aggregate.value is not None:
        aggregate.crime = "Fraude"
        return aggregate

    bank_candidates = [
        "Fraude bancario",
        "Clonación de tarjeta o fraude bancario",
    ]
    bank: OfficialValue | None = None
    for label in bank_candidates:
        candidate = extract_label_value(sheets, label)
        if candidate.value is not None:
            bank = candidate
            break
    consumer = extract_label_value(sheets, "Fraude al consumidor")

    if bank and bank.value is not None and consumer.value is not None:
        return OfficialValue(
            crime="Fraude",
            value=bank.value + consumer.value,
            sheet=f"{bank.sheet} + {consumer.sheet}",
            label_cell=f"{bank.label_cell} + {consumer.label_cell}",
            value_cell=f"{bank.value_cell} + {consumer.value_cell}",
            header=f"{bank.header} | {consumer.header}",
            method="Suma de las filas oficiales de fraude bancario y fraude al consumidor",
            note=(
                f"Fraude bancario={bank.value}; fraude al consumidor={consumer.value}."
            ),
        )

    notes = [aggregate.note]
    if bank:
        notes.append(bank.note)
    notes.append(consumer.note)
    return OfficialValue(
        crime="Fraude",
        value=None,
        method="Fraude agregado o suma de sus dos componentes",
        note=" ".join(note for note in notes if note),
    )


def extract_official_totals(path: Path) -> dict[str, OfficialValue]:
    sheets = read_xlsx(path)
    extortion = extract_label_value(sheets, "Extorsión")
    extortion.crime = "Extorsión"
    return {
        "Fraude": extract_fraud_value(sheets),
        "Extorsión": extortion,
    }


# ---------------------------------------------------------------------------
# CSV de validación
# ---------------------------------------------------------------------------

def difference_pct(value: int | None, official: int | None) -> str:
    if value is None or official in (None, 0):
        return ""
    return f"{(value - official) / official * 100:.6f}"


def validation_status(
    value: int | None,
    official: int | None,
    tolerance: int,
    *,
    csv_note: str,
    download_state: str,
) -> str:
    if csv_note:
        return "TOTAL INCONSISTENTE EN CSV"
    if value is None:
        return "SIN DATO EN CSV"
    if download_state in {"ERROR DESCARGA", "NO DESCARGADO"}:
        return "SIN ARCHIVO INEGI"
    if official is None:
        return "NO EXTRAÍDO DEL XLSX"
    return "COINCIDE" if abs(value - official) <= tolerance else "NO COINCIDE"


def make_row(
    *,
    edition: int,
    validation_type: str,
    crime: str,
    csv_value: int | None,
    csv_metrics: CsvMetrics | None,
    csv_row_count: int,
    official: OfficialValue,
    download: DownloadResult,
    csv_path: Path,
    csv_sha256: str,
    xlsx_sha256: str,
    dbf_source: str,
    dbf_sha256: str,
    tolerance: int,
    root: Path,
    execution_time: str,
    extra_note: str,
) -> dict[str, object]:
    official_value = official.value
    difference = (
        csv_value - official_value
        if csv_value is not None and official_value is not None
        else ""
    )
    csv_note = csv_metrics.total_note if csv_metrics else "No hay filas para el delito y año."
    status = validation_status(
        csv_value,
        official_value,
        tolerance,
        csv_note=csv_note if validation_type.startswith("TOTAL_DELITO") else "",
        download_state=download.state,
    )

    notes = [extra_note]
    if csv_note:
        notes.append(csv_note)
    if official.note:
        notes.append(official.note)
    if download.error:
        notes.append("Descarga: " + download.error)

    metadata_id = METADATA_IDS.get(edition)
    return {
        "edicion_envipe": edition,
        "anio_referencia": edition - 1,
        "tipo_validacion": validation_type,
        "delito": crime,
        "valor_csv": csv_value if csv_value is not None else "",
        "valor_inegi": official_value if official_value is not None else "",
        "diferencia": difference,
        "diferencia_porcentual": difference_pct(csv_value, official_value),
        "estatus": status,
        "filas_modalidad_csv": csv_row_count,
        "archivo_csv": relative_path_or_full(csv_path, root),
        "sha256_csv": csv_sha256,
        "archivo_inegi": (
            relative_path_or_full(download.path, root) if download.path.exists() else ""
        ),
        "hoja_inegi": official.sheet,
        "celda_etiqueta_inegi": official.label_cell,
        "celda_valor_inegi": official.value_cell,
        "encabezado_valor_inegi": official.header,
        "metodo_extraccion_inegi": official.method,
        "url_archivo_inegi": download.url,
        "sha256_archivo_inegi": xlsx_sha256,
        "estado_descarga_inegi": download.state,
        "fuente_microdatos": dbf_source,
        "sha256_microdatos": dbf_sha256,
        "url_programa_inegi": f"https://www.inegi.org.mx/programas/envipe/{edition}/",
        "url_metadatos_inegi": (
            f"https://www.inegi.org.mx/rnm/index.php/catalog/{metadata_id}"
            if metadata_id
            else ""
        ),
        "fecha_ejecucion_utc": execution_time,
        "nota": " ".join(note for note in notes if note),
    }


def write_validation_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=VALIDATION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Valida el CSV reducido de ENVIPE contra XLSX oficiales de INEGI."
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_DATA_CSV)
    parser.add_argument("--salida", type=Path, default=DEFAULT_VALIDATION_CSV)
    parser.add_argument("--inegi-dir", type=Path, default=DEFAULT_INEGI_DIR)
    parser.add_argument("--dbf-dir", type=Path, default=DEFAULT_DBF_DIR)
    parser.add_argument("--start-edition", type=int, default=MIN_EDITION)
    parser.add_argument("--end-edition", type=int, default=MAX_EDITION)
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--tolerance", type=int, default=1)
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.start_edition > args.end_edition:
        raise SystemExit("--start-edition no puede ser mayor que --end-edition")

    args.inegi_dir.mkdir(parents=True, exist_ok=True)
    metrics = read_reduced_csv(args.csv, args.start_edition, args.end_edition)
    csv_sha256 = sha256_file(args.csv)
    execution_time = utc_now_text()

    sources = discover_sources(args.dbf_dir, args.start_edition, args.end_edition)
    source_by_edition = {source.edition: source for source in sources}

    rows: list[dict[str, object]] = []
    for edition in range(args.start_edition, args.end_edition + 1):
        logging.info("Validando ENVIPE %s", edition)

        if args.no_download:
            target = args.inegi_dir / official_filename(edition)
            download = DownloadResult(
                path=target,
                url=official_url_candidates(edition)[0],
                state="EXISTENTE" if is_valid_xlsx(target) else "NO DESCARGADO",
            )
        else:
            download = download_xlsx(
                edition,
                args.inegi_dir,
                force=args.force_download,
                timeout=args.timeout,
                retries=args.retries,
            )

        official_values = {
            crime: OfficialValue(
                crime=crime,
                value=None,
                method="No ejecutado",
                note="No hay un XLSX oficial válido disponible.",
            )
            for crime in TARGET_CRIMES
        }
        xlsx_sha256 = ""
        if is_valid_xlsx(download.path):
            try:
                xlsx_sha256 = sha256_file(download.path)
                official_values = extract_official_totals(download.path)
            except Exception as exc:
                logging.exception("Error leyendo el XLSX ENVIPE %s", edition)
                official_values = {
                    crime: OfficialValue(
                        crime=crime,
                        value=None,
                        method="Error al leer XLSX",
                        note=str(exc),
                    )
                    for crime in TARGET_CRIMES
                }

        source = source_by_edition.get(edition)
        dbf_source = source.display_name if source else ""
        dbf_sha256 = sha256_source(source) if source else ""

        for crime in TARGET_CRIMES:
            csv_metrics = metrics.get((edition, crime))
            if args.require_all and csv_metrics is None:
                raise SystemExit(
                    f"Faltan filas en el CSV para ENVIPE {edition}, {crime}."
                )

            total_value = csv_metrics.total if csv_metrics else None
            official = official_values[crime]

            rows.append(
                make_row(
                    edition=edition,
                    validation_type="TOTAL_DELITO CSV CONTRA INEGI",
                    crime=crime,
                    csv_value=total_value,
                    csv_metrics=csv_metrics,
                    csv_row_count=csv_metrics.row_count if csv_metrics else 0,
                    official=official,
                    download=download,
                    csv_path=args.csv,
                    csv_sha256=csv_sha256,
                    xlsx_sha256=xlsx_sha256,
                    dbf_source=dbf_source,
                    dbf_sha256=dbf_sha256,
                    tolerance=args.tolerance,
                    root=DEFAULT_ROOT,
                    execution_time=execution_time,
                    extra_note=(
                        "Compara el total_delito constante del CSV con el total "
                        "nacional del XLSX oficial."
                    ),
                )
            )

            historical_sum = (
                csv_metrics.modality_sum(HISTORICAL_GROUP) if csv_metrics else None
            )
            rows.append(
                make_row(
                    edition=edition,
                    validation_type=(
                        "SUMA MODALIDADES PREGUNTAS HISTÓRICAS CONTRA INEGI"
                    ),
                    crime=crime,
                    csv_value=historical_sum,
                    csv_metrics=csv_metrics,
                    csv_row_count=(
                        csv_metrics.group_row_count(HISTORICAL_GROUP)
                        if csv_metrics
                        else 0
                    ),
                    official=official,
                    download=download,
                    csv_path=args.csv,
                    csv_sha256=csv_sha256,
                    xlsx_sha256=xlsx_sha256,
                    dbf_source=dbf_source,
                    dbf_sha256=dbf_sha256,
                    tolerance=args.tolerance,
                    root=DEFAULT_ROOT,
                    execution_time=execution_time,
                    extra_note=(
                        "Suma únicamente las modalidades de las preguntas "
                        "históricas de las Secciones IV y V."
                    ),
                )
            )

            question_1_5a_rows = (
                csv_metrics.group_row_count(QUESTION_1_5A_GROUP)
                if csv_metrics
                else 0
            )
            if question_1_5a_rows:
                rows.append(
                    make_row(
                        edition=edition,
                        validation_type=(
                            "SUMA MODALIDADES PREGUNTA 1.5A ENVIPE 2025 CONTRA INEGI"
                        ),
                        crime=crime,
                        csv_value=(
                            csv_metrics.modality_sum(QUESTION_1_5A_GROUP)
                            if csv_metrics
                            else None
                        ),
                        csv_metrics=csv_metrics,
                        csv_row_count=question_1_5a_rows,
                        official=official,
                        download=download,
                        csv_path=args.csv,
                        csv_sha256=csv_sha256,
                        xlsx_sha256=xlsx_sha256,
                        dbf_source=dbf_source,
                        dbf_sha256=dbf_sha256,
                        tolerance=args.tolerance,
                        root=DEFAULT_ROOT,
                        execution_time=execution_time,
                        extra_note=(
                            "Suma sólo las cinco categorías mutuamente "
                            "excluyentes de la pregunta 1.5a."
                        ),
                    )
                )

    write_validation_csv(args.salida, rows)
    logging.info("Validación generada: %s", args.salida)
    logging.info("Carpeta de XLSX oficiales: %s", args.inegi_dir)


if __name__ == "__main__":
    main()
