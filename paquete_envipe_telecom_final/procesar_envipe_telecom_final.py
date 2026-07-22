#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Resumen Analítico de Delitos por Medio de Comisión (ENVIPE)

Este script toma el CSV general generado a partir de los microdatos DBF
y produce un nuevo CSV resumido. Filtra los delitos físicos, agrupa por 
tipo de delito y calcula los totales históricos de comisión por internet, 
llamada telefónica y el total de telecomunicaciones sin doble conteo.

Uso:
    python resumir_envipe_telecom.py --entrada ENVIPE_TELECOM_PUBLICACION.csv --salida RESUMEN_TELECOM_ENVIPE.csv
"""

import argparse
import pandas as pd
from pathlib import Path

DEFAULT_INPUT = "ENVIPE_TELECOM_PUBLICACION.csv"
DEFAULT_OUTPUT = "RESUMEN_TELECOM_ENVIPE.csv"

def procesar_resumen_telecom(archivo_entrada: Path, archivo_salida: Path) -> None:
    print(f"Leyendo datos desde: {archivo_entrada}")
    
    try:
        # Cargar los datos
        df = pd.read_csv(archivo_entrada)
    except FileNotFoundError:
        raise SystemExit(f"Error: No se encontró el archivo de entrada '{archivo_entrada}'.")
    except Exception as e:
        raise SystemExit(f"Error al leer el archivo CSV: {e}")

    # 1. Filtrar solo los registros donde se capturó algún medio de comisión
    # Esto elimina automáticamente los delitos como robo de vehículo, vandalismo, etc.
    filtro_telecom = (df['estatus_internet'] == 'Captado') | (df['estatus_llamada_telefonica'] == 'Captado')
    df_util = df[filtro_telecom].copy()
    
    # Si el DataFrame está vacío después de filtrar
    if df_util.empty:
        print("Advertencia: No se encontraron registros con estatus 'Captado' para internet o llamada.")
        return

    # 2. Seleccionar las columnas necesarias
    columnas_clave = [
        'anio_referencia', 
        'tipo_delito', 
        'total_delito_estimado',
        'internet_estimado', 
        'llamada_telefonica_estimada',
        'total_telecom_sin_doble_conteo_estimado'
    ]
    df_limpio = df_util[columnas_clave].copy()
    
    # 3. Llenar los valores nulos (NaN) con 0 para poder sumar correctamente
    df_limpio.fillna(0, inplace=True)
    
    # 4. Agrupar por 'tipo_delito' y sumar las estimaciones
    print("Agrupando y calculando totales por tipo de delito...")
    resumen = df_limpio.groupby('tipo_delito').agg(
        total_historico_delito=('total_delito_estimado', 'sum'),
        comision_internet=('internet_estimado', 'sum'),
        comision_llamada=('llamada_telefonica_estimada', 'sum'),
        total_telecomunicaciones=('total_telecom_sin_doble_conteo_estimado', 'sum')
    ).reset_index()
    
    # 5. Calcular la proporción del delito que se comete por vías de telecomunicación
    # Se evita la división por cero usando un condicional o manejando el infinito
    resumen['porcentaje_impacto_telecom'] = (
        (resumen['total_telecomunicaciones'] / resumen['total_historico_delito']) * 100
    ).fillna(0)
    
    # 6. Ordenar los resultados por el mayor volumen de uso de telecomunicaciones
    resumen = resumen.sort_values(by='total_telecomunicaciones', ascending=False)
    
    # 7. Redondear los valores para mayor legibilidad en la presentación final
    columnas_redondeo = [
        'total_historico_delito', 
        'comision_internet', 
        'comision_llamada', 
        'total_telecomunicaciones'
    ]
    resumen[columnas_redondeo] = resumen[columnas_redondeo].round(0).astype(int)
    resumen['porcentaje_impacto_telecom'] = resumen['porcentaje_impacto_telecom'].round(2)
    
    # 8. Exportar el resultado
    try:
        # Asegurar que el directorio de salida exista
        archivo_salida.parent.mkdir(parents=True, exist_ok=True)
        resumen.to_csv(archivo_salida, index=False, encoding='utf-8-sig')
        print(f"Éxito. Archivo de resumen generado en: {archivo_salida}")
        
        # Imprimir una pequeña previsualización en la terminal
        print("\nPrevisualización de los datos procesados:")
        print("-" * 75)
        print(resumen.to_string(index=False))
        print("-" * 75)
        
    except Exception as e:
        raise SystemExit(f"Error al guardar el archivo CSV de salida: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="Genera un resumen seccionado de delitos por medios electrónicos y llamadas a partir de datos ENVIPE procesados."
    )
    parser.add_argument(
        "--entrada",
        type=Path,
        default=Path(DEFAULT_INPUT),
        help=f"Ruta del CSV general procesado. Predeterminado: {DEFAULT_INPUT}"
    )
    parser.add_argument(
        "--salida",
        type=Path,
        default=Path(DEFAULT_OUTPUT),
        help=f"Ruta del CSV de resumen a generar. Predeterminado: {DEFAULT_OUTPUT}"
    )
    
    args = parser.parse_args()
    procesar_resumen_telecom(args.entrada, args.salida)

if __name__ == "__main__":
    main()