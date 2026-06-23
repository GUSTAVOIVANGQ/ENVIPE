# Procesamiento Histórico ENVIPE (INEGI)

Este proyecto contiene las herramientas necesarias para procesar y unificar los microdatos históricos (2011-2025) de la Encuesta Nacional de Victimización y Percepción sobre Seguridad Pública (ENVIPE) del INEGI.

El objetivo principal es extraer, limpiar y clasificar los datos de victimización centrándose estrictamente en el cruce de **Tipo de Delito** por **Medio de Comisión**, agrupándolos en un formato listo para el análisis, particularmente útil para los reportes a la Comisión Reguladora de Telecomunicaciones (CRT).

## Archivos Principales

### 1. `procesar_envipe.py`
Es el script consolidado que realiza todo el trabajo de extracción y limpieza. Sus funciones principales son:
- **Carga automatizada**: Lee automáticamente todos los archivos `.zip` (que contienen los `.dbf` o `.csv` de victimización) ubicados en la carpeta `conjunto_de_datos`.
- **Estandarización histórica**: A lo largo de los años, el INEGI ha cambiado los nombres de ciertas variables (ej. de `COD_DEL` a `BPCOD`). Este script homologa todas estas diferencias para poder apilar 15 años de encuestas sin errores.
- **Clasificación de Medios de Comisión**: Aplica un conjunto de reglas basadas en el cuestionario de victimización para determinar si un delito se cometió de forma *Presencial*, vía *Teléfono* (voz o SMS), o por *Internet*.
- **Agrupación**: Agrega millones de registros individuales a nivel nacional, sumando el factor de expansión (`FAC_DEL`) para obtener la estimación poblacional y contando los registros en la muestra.

#### Uso:
```bash
pip install pandas dbfread
python procesar_envipe.py
```

### 2. `resultados/ENVIPE_DELITO_MEDIO_HISTORICO.csv`
Es el producto final generado por el script. Es un archivo de formato largo (tabular), diseñado para que gerentes y analistas puedan importarlo directamente a **Excel, Power BI o Tableau** en cuestión de segundos y generar tablas dinámicas.

**Estructura del CSV:**
- `ANIO`: El año de la encuesta (2011 a 2025).
- `TIPO_DELITO`: El nombre descriptivo del delito (ej. Fraude bancario, Extorsión, etc.).
- `MEDIO_COMISION`: El canal detallado por el cual se perpetró el delito (ej. *Teléfono (llamada de voz)*).
- `CATEGORIA_MEDIO`: Agrupación de alto nivel para reportes ejecutivos (*TELEFÓNICO, INTERNET / DIGITAL, PRESENCIAL, OTRO MEDIO*).
- `ESTIMACION_POBLACIONAL`: El número total de delitos estimados en la población mexicana.
- `REGISTROS_MUESTRA`: La cantidad de encuestados físicos que reportaron el caso (útil para validar la significancia estadística).

## Organización de Carpetas
- `/conjunto_de_datos`: Directorio donde se deben colocar los archivos `.zip` originales descargados desde el portal de microdatos del INEGI.
- `/resultados`: Directorio donde se guardará automáticamente el archivo `ENVIPE_DELITO_MEDIO_HISTORICO.csv` tras la ejecución del script.
