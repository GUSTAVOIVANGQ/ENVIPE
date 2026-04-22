# Metadatos: Procesamiento de Datos para la CRT (Comisión Reguladora de Telecomunicaciones)

## Descripción General
El script `exportar_crt.py` procesa el panel consolidado de datos históricos de la ENVIPE (`panel_todos_años.csv`) para generar tabulados analíticos diseñados específicamente para la **Comisión Reguladora de Telecomunicaciones (CRT)**. Su objetivo principal es dimensionar e identificar la prevalencia de los distintos **medios de comisión** de delitos, con un enfoque particular en el uso indebido de canales de telecomunicaciones e internet.

## Lógica y Funcionalidad del Script (`exportar_crt.py`)
1. **Datos de Entrada:** Consume el archivo `resultados/panel_todos_años.csv`, el cual contiene la base de datos limpia de las encuestas ENVIPE de 2011 a 2025.
2. **Estandarización de Medios:** Consolida las respuestas originales de la encuesta sobre cómo se cometió el delito en agrupaciones más útiles para la CRT:
   - **TELEFÓNICO:** Incluye llamadas de voz, SMS, WhatsApp y contactos telefónicos sin especificar.
   - **INTERNET / DIGITAL:** Abarca redes sociales y medios puramente web.
   - **PRESENCIAL:** Contacto directo cara a cara.
   - **OTRO MEDIO:** Correo, mensajería física, entre otros.
   - **NO APLICA / SIN INFORMACIÓN:** Delitos del hogar o encuestas sin respuesta.
3. **Indicador Digital:** Crea una bandera booleana (`es_digital_crt`) para aislar los incidentes delictivos que dependen de infraestructura de telecomunicaciones.
4. **Filtro de Delitos Prioritarios:** Limita el análisis profundo a los delitos de mayor impacto en el sector: *Fraude bancario, Fraude al consumidor y Extorsión*.
5. **Estimación Poblacional:** Transforma los registros de la muestra (encuestas individuales) en estimaciones representativas a nivel nacional utilizando la variable del factor de expansión (`FAC_DEL`).

## Archivos CSV de Resultado Generados
El script deposita **5 archivos CSV** en el directorio `resultados/`, cada uno concebido para un escenario de análisis distinto:

### 1. `CRT_01_medios_por_año.csv` (Estimación General por Medios)
- **Propósito:** Vista general para directivos.
- **Contenido:** Cuantifica la estimación poblacional de los delitos según cada medio de comisión específico para cada año evaluado.
- **Campos Clave:** `Año`, `Medio de Comisión`, `Categoría`, `Estimación Poblacional`, `% del Total del Año`.

### 2. `CRT_02_tendencia_digital_año.csv` (Serie de Tiempo Digital)
- **Propósito:** Medición de crecimiento histórico.
- **Contenido:** Serie de tiempo que contrasta el volumen de delitos que utilizaron canales estrictamente digitales (teléfono + internet) frente al volumen total de delitos.
- **Campos Clave:** `Año`, `Total Delitos Estimados`, `Total Delitos Digitales (tel+internet)`, `% Digital del Total`, y subtotales por medio digital.

### 3. `CRT_03_desglose_delito_medio.csv` (Cruce Detallado)
- **Propósito:** Herramienta analítica para minería de datos.
- **Contenido:** Es la tabla con mayor granularidad. Cruza cada tipo individual de delito con el medio de comisión utilizado, año por año.
- **Campos Clave:** `Año`, `Tipo de Delito`, `Medio de Comisión`, `Categoría del Medio`, `Estimación Poblacional`. 
- **Ideal para:** Creación de Tablas Dinámicas (Pivot Tables) en Excel o Power BI.

### 4. `CRT_04_categorias_ejecutivo.csv` (Resumen Ejecutivo)
- **Propósito:** Presentación de resultados consolidados.
- **Contenido:** Resume la información agrupándola exclusivamente en las 4 macro-categorías (Telefónico, Internet, Presencial, Otro).
- **Campos Clave:** `Año`, `Categoría del Medio`, `Estimación Poblacional`, `% del Total del Año`.

### 5. `CRT_05_foco_extorsion_fraude.csv` (Análisis de Delitos de Telecomunicaciones)
- **Propósito:** Informe especializado para la regulación del sector.
- **Contenido:** Aísla los tres delitos más vinculados a las telecomunicaciones (Extorsión, Fraude bancario, Fraude al consumidor) y detalla qué medio específico se utilizó para cometerlos a lo largo del tiempo.
- **Campos Clave:** `Año`, `Tipo de Delito`, `Medio de Comisión`, `Estimación Poblacional`, `% Dentro del Delito`, `Total Delitos Relevantes CRT ese Año`.
