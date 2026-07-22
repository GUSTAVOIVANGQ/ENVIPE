# Metodología propuesta: delitos relacionados con telecomunicaciones en ENVIPE

## 1. Unidad temporal

La edición ENVIPE **N** reporta victimización del año **N−1**. Por tanto, los archivos ENVIPE 2011–2025 generan una serie de años de referencia **2010–2024**. En el CSV deben conservarse ambas columnas: `edicion_envipe` y `anio_referencia`.

## 2. Unidad de análisis y ponderador

La tabla `TMod_Vic` contiene las experiencias delictivas registradas en el módulo. La estimación nacional de incidentes se obtiene con:

`estimación = suma(FAC_DEL)` para los registros que cumplen el filtro.

`FAC_DEL` debe usarse de forma explícita. No se recomienda sustituirlo automáticamente por otros factores.

## 3. Definición operativa recomendada

No conviene mezclar tres conceptos distintos:

1. **Medio de comisión:** teléfono, internet, correo electrónico o medios electrónicos.
2. **Bien afectado:** por ejemplo, robo de teléfono celular o equipo electrónico.
3. **Canal de denuncia:** denuncia telefónica, web, correo o SMS.

La serie principal debe limitarse al primer concepto. Los otros dos pueden publicarse como familias separadas, nunca sumados como si fueran el mismo fenómeno.

## 4. Reglas históricas verificadas

### Fraude por internet/correo electrónico

- Año de referencia 2010, ENVIPE 2011: BPCOD 07 y `BP4_1=3`.
- Año de referencia 2011, ENVIPE 2012: BPCOD 07 y `BP4_1=4`.
- Años de referencia 2012–2024: BPCOD 07/08 y `BP4_1=5`.

El BPCOD 06 histórico, fraude bancario, no debe suponerse clasificable por `BP4_1` en 2010–2011.

### Extorsión por medios de telecomunicaciones

- Años de referencia 2010–2011: BPCOD 08.
- Años de referencia 2012–2023: BPCOD 09.
- `BP5_1=1`: telefónica.
- `BP5_1=3`: internet/correo electrónico.
- Para el total telecom de extorsión debe usarse `BP5_1 in {1,3}`, no sumar porcentajes ya redondeados.

En el año de referencia 2024 existe una ruptura: `BP5_1` pasa a clasificar extorsión laboral, cobro de piso u otra. Por ello no debe aplicarse el catálogo anterior.

### Nueva pregunta de medio de comisión, año de referencia 2024

ENVIPE 2025 incorpora una pregunta multirrespuesta:

- `BP1_5A_1=1`: internet o medios electrónicos.
- `BP1_5A_2=1`: llamada telefónica.
- `BP1_5A_3=1`: contacto presencial.
- `BP1_5A_4=1`: otro.
- `BP1_5A_9=1`: no sabe/no responde.

Para contar incidentes telecom únicos debe usarse:

`BP1_5A_1=1 OR BP1_5A_2=1`.

No debe sumarse internet + teléfono para obtener el total, porque un mismo incidente puede marcar ambas opciones.

## 5. Amenazas y hostigamiento

Antes del año de referencia 2024 no hay una variable general que permita identificar de forma directa si amenazas u hostigamiento se cometieron por teléfono o internet. `BP1_5` describe el **lugar** del delito y `BP7_1` describe el **tipo de ofensa sexual**; no son variables de medio de comisión. En consecuencia, esos indicadores deben declararse “no captados” en 2010–2023, no imputarse ni reconstruirse.

## 6. Cálculos que debe publicar el anuario

Para cada indicador y año:

- estimación de incidentes: `Σ FAC_DEL` del numerador;
- número de registros muestrales del numerador;
- total estimado del delito;
- porcentaje sobre todos los incidentes del delito;
- base estimada de respuestas válidas;
- porcentaje sobre respuestas válidas;
- edición ENVIPE y año de referencia;
- variable, BPCOD y código usados;
- estado de comparabilidad y ruptura de serie;
- URL de la edición y del documento que sustenta la regla;
- huella SHA-256 del ZIP procesado.

No debe conservarse únicamente el porcentaje. El absoluto, el denominador y la definición son necesarios para reproducibilidad.

## 7. Precisión estadística

El script adjunto calcula estimaciones puntuales. Antes de publicar en un anuario oficial deben calcularse error estándar, coeficiente de variación e intervalo de confianza con el diseño complejo de cada edición, utilizando el estrato y la UPM disponibles (`EST_DIS`/`UPM_DIS` o sus nombres históricos) y `FAC_DEL`.

Para encuestas de hogares, INEGI clasifica la precisión por CV como alta `[0%,15%)`, moderada `[15%,30%)` y baja `>=30%`. Las estimaciones de baja precisión deben identificarse claramente y puede ser preferible no presentarlas en desagregaciones pequeñas.

## 8. Uso de `estructura_tmod_vic.csv`

Este archivo es útil para auditar que una variable existe y revisar cambios de longitud/tipo. No es una referencia semántica suficiente: no contiene pregunta, concepto, universo ni catálogo de códigos. La fuente normativa para cada regla debe ser el cuestionario, manual, estructura de base o diccionario oficial de INEGI de la edición correspondiente.

## 9. Fuentes oficiales principales

- ENVIPE 2011, módulo sobre victimización: https://www.inegi.org.mx/contenidos/programas/envipe/2011/doc/cuest_envipe11_modulo.pdf
- ENVIPE 2012, manual del entrevistador: https://www.inegi.org.mx/contenido/productos/prod_serv/contenidos/espanol/bvinegi/productos/metodologias/ENVIPE2012/Manual_ENT/ENVIPE12_Manual_ENT.pdf
- ENVIPE 2013, manual del entrevistador: https://www.inegi.org.mx/contenidos/programas/envipe/2013/doc/envipe13_manual_ent.pdf
- ENVIPE 2024, módulo sobre victimización: https://www.inegi.org.mx/contenidos/programas/envipe/2024/doc/cuest_modulo_envipe2024.pdf
- ENVIPE 2025, estructura de la base de datos: https://www.inegi.org.mx/contenidos/programas/envipe/2025/doc/fd_envipe2025.pdf
- ENVIPE 2025, diseño muestral: https://www.inegi.org.mx/contenidos/programas/envipe/2025/doc/889463926689.pdf
- Página de cada edición: `https://www.inegi.org.mx/programas/envipe/AÑO/`

## 10. Ejecución

```bash
python procesar_envipe_telecom.py \
  --dir conjunto_de_datos \
  --estructura estructura_tmod_vic.csv \
  --out-dir salida_envipe_telecom \
  --start-edition 2011 \
  --end-edition 2025 \
  --strict
```

Prueba interna sin microdatos:

```bash
python procesar_envipe_telecom.py --self-test
```
