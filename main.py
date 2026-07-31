#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Genera el CSV reducido de Fraude y Extorsión desde los DBF de ENVIPE.

El archivo conserva las preguntas históricas del módulo de victimización
(Secciones IV y V) para todas las ediciones. Además, para ENVIPE 2025
(delitos ocurridos en 2024), agrega un segundo bloque con la pregunta 1.5a:
"¿El (DELITO) se realizó por medio de...?".

Las dos familias de preguntas se identifican en columnas separadas:

* cuest_modulo_envipe_7: preguntas históricas de Fraude y Extorsión.
* cuest_modulo_envipe2025_2: pregunta 1.5a de ENVIPE 2025.

Cuando una fila no pertenece a una familia de preguntas, la columna
correspondiente contiene "NA".

Salida predeterminada:
  C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE\ENVIPE_FRAUDE_EXTORSION.csv

Columnas:
  anio,seccion,delito,modalidad_comision,cuest_modulo_envipe_7,
  cuest_modulo_envipe2025_2,estimacion,porcentaje,total_delito

Uso:
  python main.py
  python main.py --start-edition 2025 --end-edition 2025 --verbose
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from envipe_core import (
    DEFAULT_DATA_CSV,
    DEFAULT_DBF_DIR,
    MAX_EDITION,
    MIN_EDITION,
    TELECOM_EDITION,
    build_2025_question_1_5a_rows,
    build_reduced_rows,
    discover_sources,
    process_2025_question_1_5a,
    process_source,
    write_reduced_csv,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Procesa TMod_Vic.dbf y genera un CSV de Fraude y Extorsión con "
            "las preguntas históricas y, para ENVIPE 2025, la pregunta 1.5a."
        )
    )
    parser.add_argument("--dir", type=Path, default=DEFAULT_DBF_DIR)
    parser.add_argument("--salida", type=Path, default=DEFAULT_DATA_CSV)
    parser.add_argument("--start-edition", type=int, default=MIN_EDITION)
    parser.add_argument("--end-edition", type=int, default=MAX_EDITION)
    parser.add_argument(
        "--require-all",
        action="store_true",
        help="Detiene el proceso si falta alguna edición del rango.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.start_edition > args.end_edition:
        raise SystemExit("--start-edition no puede ser mayor que --end-edition")

    sources = discover_sources(args.dir, args.start_edition, args.end_edition)
    if not sources:
        raise SystemExit(f"No se encontraron TMod_Vic.dbf ni ZIP válidos en: {args.dir}")

    found = {source.edition for source in sources}
    expected = set(range(args.start_edition, args.end_edition + 1))
    missing = sorted(expected - found)
    if missing:
        message = "Faltan ediciones ENVIPE: " + ", ".join(map(str, missing))
        if args.require_all:
            raise SystemExit(message)
        logging.warning(message)

    rows: list[dict[str, object]] = []

    for source in sources:
        logging.info("Procesando ENVIPE %s: %s", source.edition, source.display_name)

        # 1) Preguntas históricas del módulo (Secciones IV y V).
        historical_result = process_source(source)
        if historical_result.invalid_weights:
            logging.warning(
                "ENVIPE %s: se excluyeron %s registros con FAC_DEL inválido "
                "en las preguntas históricas",
                source.edition,
                historical_result.invalid_weights,
            )
        rows.extend(build_reduced_rows([historical_result]))

        # 2) ENVIPE 2025: pregunta 1.5a de la página 2 del módulo.
        # Se agrega como un bloque adicional; no reemplaza a las preguntas
        # históricas de las Secciones IV y V.
        if source.edition == TELECOM_EDITION:
            counts, invalid_weights = process_2025_question_1_5a(source)
            if invalid_weights:
                logging.warning(
                    "ENVIPE 2025: se excluyeron %s registros objetivo con "
                    "FAC_DEL inválido en la pregunta 1.5a",
                    invalid_weights,
                )
            rows.extend(build_2025_question_1_5a_rows(counts))

    write_reduced_csv(args.salida, rows)

    logging.info("CSV generado: %s", args.salida)
    logging.info("Filas: %s", len(rows))


if __name__ == "__main__":
    main()
