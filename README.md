# Procesamiento ENVIPE: delitos por tipo y forma de comisión

## Objetivo

`procesar_envipe_dbf_desglose_encuesta.py` procesa los archivos
`TMod_Vic.dbf` de las ediciones ENVIPE 2011–2025 y genera un solo archivo:

```text
ENVIPE_DESGLOSE_ENCUESTA.csv
```

El resultado presenta estimaciones nacionales por:

- tipo de delito;
- tipo de fraude;
- tipo de extorsión;
- medio de comisión disponible en el cuestionario.

La edición ENVIPE **N** reporta los delitos ocurridos en el año **N−1**.
Por ejemplo, ENVIPE 2011 pregunta por delitos de 2010 y ENVIPE 2025 por
delitos de 2024.

## Datos utilizados

El programa toma únicamente variables de la tabla `TMod_Vic`:

| Variable | Uso |
|---|---|
| `BPCOD` | Código del tipo de delito. |
| `FAC_DEL` | Factor de expansión del incidente. |
| `BP4_1` | Respuesta a “¿Qué tipo de fraude fue?”. |
| `BP5_1` | Respuesta a “¿La extorsión fue...?”. |
| `BP1_5A_1` a `BP1_5A_4`, `BP1_5A_9` | Medio de comisión en ENVIPE 2025: internet, llamada, contacto presencial, otro o no sabe. |
| `BP5_1A_1` a `BP5_1A_4` | Lugar de la extorsión presencial en ENVIPE 2025. |

La estimación de cada categoría se calcula como:

```text
estimación = suma de FAC_DEL de los registros que cumplen el filtro
```

`muestra` es el número de registros sin expandir. `porcentaje_base` compara
cada categoría con el total del delito o de la sección correspondiente.

## Criterios de clasificación

Los nombres, códigos y opciones se tomaron de los cuestionarios oficiales
de cada edición. Los catálogos cambian entre años, por lo que el programa
no aplica una sola clasificación a toda la serie.

Ejemplos:

- En ENVIPE 2011, fraude por internet corresponde a `BP4_1 = 3`.
- Desde ENVIPE 2014, fraude usa seis categorías y
  “Por internet/correo electrónico” corresponde a `BP4_1 = 5`.
- Hasta ENVIPE 2024, extorsión se divide en telefónica, laboral,
  internet/correo, calle, negocio propio o familiar, cobro de piso y otro.
- ENVIPE 2025 separa el tipo de extorsión del medio de comisión e incorpora
  una pregunta multirrespuesta aplicable a fraude bancario, fraude al
  consumidor, extorsión, amenazas y hostigamiento sexual.

El archivo `CATALOGO_ENVIPE_DESGLOSES_POR_ANIO.csv` documenta las
categorías aplicadas en cada año.

## Ejecución

```bash
python procesar_envipe_dbf_desglose_encuesta.py \
  --dir conjunto_de_datos \
  --salida ENVIPE_DESGLOSE_ENCUESTA.csv \
  --require-all
```

El directorio puede contener `TMod_Vic.dbf` directamente o dentro de los
ZIP originales de INEGI.

## Limitaciones

Las cifras son estimaciones puntuales. El programa no calcula error
estándar, coeficiente de variación ni intervalos de confianza. Las
respuestas multirrespuesta de ENVIPE 2025 pueden sumar más de 100 %.

## Referencias oficiales

- INEGI, *ENVIPE 2011. Módulo sobre victimización*:  
  https://www.inegi.org.mx/contenidos/programas/envipe/2011/doc/cuest_envipe11_modulo.pdf
- INEGI, *ENVIPE 2024. Módulo sobre victimización*:  
  https://www.inegi.org.mx/contenidos/programas/envipe/2024/doc/cuest_modulo_envipe2024.pdf
- INEGI, *ENVIPE 2025. Módulo sobre victimización*:  
  https://www.inegi.org.mx/contenidos/programas/envipe/2025/doc/cuest_modulo_envipe2025.pdf
- INEGI, *ENVIPE 2025. Estructura de la base de datos*:  
  https://www.inegi.org.mx/contenidos/programas/envipe/2025/doc/fd_envipe2025.pdf
- Portal oficial de ENVIPE:  
  https://www.inegi.org.mx/programas/envipe/
