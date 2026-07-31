PROGRAMAS ENVIPE: FRAUDE Y EXTORSIÓN
=====================================

PROPÓSITO
---------
Este proyecto convierte los microdatos del Módulo sobre Victimización de la
Encuesta Nacional de Victimización y Percepción sobre Seguridad Pública
(ENVIPE) en dos archivos reproducibles:

1. ENVIPE_FRAUDE_EXTORSION.csv
   Contiene únicamente Fraude y Extorsión, desglosados por modalidad.

2. VALIDACION_INEGI_ENVIPE.csv
   Compara los resultados calculados con los totales publicados por INEGI y
   conserva la evidencia necesaria para auditar la comparación.

La separación es deliberada:

- main.py realiza el cálculo a partir de los microdatos.
- validar_inegi.py realiza una comprobación externa contra los XLSX oficiales.
- envipe_core.py concentra el lector DBF, los catálogos y las reglas comunes.

Esto evita mezclar el dato calculado con el dato usado para validarlo.


ARCHIVOS Y RUTAS PREDETERMINADAS
--------------------------------
Coloque juntos los siguientes archivos en:

  C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE

  main.py
  validar_inegi.py
  envipe_core.py
  README_ENVIPE.txt

Microdatos:

  C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE\conjunto_de_datos

XLSX oficiales descargados:

  C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE\inegi

CSV principal:

  C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE\ENVIPE_FRAUDE_EXTORSION.csv

CSV de validación:

  C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE\VALIDACION_INEGI_ENVIPE.csv


1. FUENTES EN LAS QUE SE BASA EL PROCESAMIENTO
----------------------------------------------
El procesamiento utiliza tres tipos de fuente, con funciones diferentes.

A. Cuestionarios y diccionarios de datos de INEGI

Sirven para determinar:

- qué significa cada código de BPCOD;
- qué pregunta corresponde a BP4_1 y BP5_1;
- qué códigos de respuesta existen en cada edición;
- cuál es el universo de aplicación de cada pregunta;
- cuándo cambió la estructura del cuestionario.

B. Microdatos TMod_Vic.dbf

Sirven para calcular:

- el número expandido de delitos;
- el total de Fraude y Extorsión;
- la distribución de sus modalidades.

C. Tabulados oficiales XLSX de INEGI

Sirven como control externo para comprobar que los totales calculados con los
microdatos coinciden con las cifras publicadas por INEGI.

Los XLSX no se usan para fabricar o ajustar los resultados del CSV principal.
Primero se procesa el DBF y después se compara el resultado con el tabulado.


2. CÓMO SABEMOS QUE LOS CÓDIGOS Y NOMBRES EXISTEN
-------------------------------------------------
Los archivos DBF almacenan principalmente códigos, no descripciones completas.
Por esa razón, los nombres no se deducen del número ni se inventan a partir de
la frecuencia observada. Se toman de los cuestionarios y catálogos de INEGI.

El programa distingue tres clases de etiqueta:

1. Etiqueta oficial
   Es el texto asociado al código en el cuestionario o diccionario de datos.
   Ejemplos: "Telefónica", "Cobro de piso", "Cheque falso o sin fondos".

2. Etiqueta armonizada
   Es un nombre analítico que agrupa componentes oficiales para poder comparar
   años. Ejemplos: "Fraude" y "Extorsión" como grupos generales.

3. Etiqueta de diagnóstico
   Es un texto agregado por el programa para no ocultar registros que no tienen
   una respuesta utilizable. Ejemplos:

     Sin respuesta en la variable de modalidad
     Código X (sin etiqueta en el catálogo)

Estas etiquetas de diagnóstico no se presentan como categorías oficiales de
INEGI. Su función es hacer visibles los datos faltantes o inesperados.

Las secciones usadas en el CSV también proceden del cuestionario:

  SECCIÓN IV. FRAUDE
  SECCIÓN V. EXTORSIÓN

Por ejemplo, en el cuestionario ENVIPE 2016 los códigos generales son:

  07 Fraude bancario
  08 Fraude al consumidor
  09 Extorsión

El mismo cuestionario ubica los códigos 07 y 08 en la Sección IV y el código 09
en la Sección V. También muestra que la pregunta 4.1 es "¿Qué tipo de fraude
fue?" y la pregunta 5.1 es "¿La extorsión fue...?".


3. POR QUÉ LOS CÓDIGOS CAMBIAN ENTRE EDICIONES
----------------------------------------------
No se usa un solo catálogo para todos los años porque el instrumento cambió.
La regla se define explícitamente por edición.

Matriz de códigos generales implementada:

  Edición ENVIPE   Año de hechos   Fraude total       Extorsión
  --------------   -------------   ----------------   ----------
  2011             2010            BPCOD 06 + 07      BPCOD 08
  2012             2011            BPCOD 06 + 07      BPCOD 08
  2013-2025        2012-2024       BPCOD 07 + 08      BPCOD 09

La razón del desplazamiento es el cambio del catálogo general de delitos. En
las ediciones posteriores aparece Vandalismo como BPCOD 03, lo que desplaza
los códigos de varios delitos posteriores.

Por tanto, usar BPCOD 09 para Extorsión en 2010 o usar BPCOD 08 para Extorsión
en 2020 sería metodológicamente incorrecto. El programa evita ese error al
seleccionar los códigos según la edición ENVIPE.


4. CONVENCIÓN ENTRE EDICIÓN Y AÑO DE REFERENCIA
------------------------------------------------
El nombre de la edición es el año de levantamiento/publicación, mientras que el
módulo pregunta por delitos ocurridos en el año calendario anterior.

Por eso se aplica:

  año de referencia = edición ENVIPE - 1

Relación completa usada por el programa:

  ENVIPE 2011 -> hechos de 2010
  ENVIPE 2012 -> hechos de 2011
  ENVIPE 2013 -> hechos de 2012
  ENVIPE 2014 -> hechos de 2013
  ENVIPE 2015 -> hechos de 2014
  ENVIPE 2016 -> hechos de 2015
  ENVIPE 2017 -> hechos de 2016
  ENVIPE 2018 -> hechos de 2017
  ENVIPE 2019 -> hechos de 2018
  ENVIPE 2020 -> hechos de 2019
  ENVIPE 2021 -> hechos de 2020
  ENVIPE 2022 -> hechos de 2021
  ENVIPE 2023 -> hechos de 2022
  ENVIPE 2024 -> hechos de 2023
  ENVIPE 2025 -> hechos de 2024

Ejemplo verificable: el cuestionario ENVIPE 2016 indica que se pregunta por el
delito sufrido en 2015. Por esa razón, el CSV escribe anio=2015 para la edición
2016 y no anio=2016.

Esta distinción debe explicarse siempre al presentar las series. De lo
contrario, se corre el riesgo de desplazar todo el análisis un año.


5. VARIABLES UTILIZADAS
-----------------------
BPCOD

  Código general del tipo de delito. Se usa para identificar qué registros
  pertenecen a Fraude o Extorsión.

FAC_DEL

  Factor de expansión del registro de delito. Cada fila de TMod_Vic.dbf es una
  observación muestral de un delito y FAC_DEL indica cuántos delitos representa
  en la población objetivo.

BP4_1

  Respuesta a la pregunta de la Sección IV sobre tipo de fraude. El catálogo
  cambia entre ediciones.

BP5_1

  Respuesta a la pregunta de la Sección V sobre tipo de extorsión. Su catálogo
  histórico cambia en ENVIPE 2025.

El programa exige que estas variables existan en el DBF. Si falta alguna, se
detiene en lugar de producir un resultado incompleto sin advertencia.


6. CATÁLOGOS DE MODALIDADES DE FRAUDE
-------------------------------------
Los nombres se mantienen por edición porque la numeración no significa lo mismo
en todos los años.

ENVIPE 2011, año de referencia 2010

  BPCOD 06  Clonación de tarjeta o fraude bancario
  BP4_1 1   Cheque falso
  BP4_1 2   Pago por un servicio/producto no entregado (al consumidor)
  BP4_1 3   Por internet/correo electrónico
  BP4_1 4   Otro
  BP4_1 9   No especificado

ENVIPE 2012, año de referencia 2011

  BPCOD 06  Clonación de tarjeta o fraude bancario
  BP4_1 1   Cheque falso
  BP4_1 2   Pago por un servicio/producto no entregado (al consumidor)
  BP4_1 3   Tarjeta de débito o crédito
  BP4_1 4   Por internet/correo electrónico
  BP4_1 5   Otro
  BP4_1 9   No especificado

ENVIPE 2013, año de referencia 2012

  BP4_1 1   Cheque falso o sin fondos
  BP4_1 2   Dinero falso
  BP4_1 3   Pago por un servicio/producto no entregado (al consumidor)
  BP4_1 4   Tarjeta de débito o crédito
  BP4_1 5   Por internet/correo electrónico
  BP4_1 6   Otro
  BP4_1 9   No especificado

ENVIPE 2014 a 2025, años de referencia 2013 a 2024

  BP4_1 1   Pago por un servicio/producto no entregado (al consumidor)
  BP4_1 2   Cheque falso o sin fondos
  BP4_1 3   Dinero falso
  BP4_1 4   Tarjeta de débito o crédito
  BP4_1 5   Por internet/correo electrónico
  BP4_1 6   Otro
  BP4_1 9   No especificado

Punto crítico de ENVIPE 2011 y 2012

En esas dos ediciones, el total agregado de Fraude incluye:

  BPCOD 06 = fraude bancario/clonación
  BPCOD 07 = fraude al consumidor

Sin embargo, BP4_1 sólo desglosa el componente BPCOD 07. Por eso la suma de
BP4_1 por sí sola no puede alcanzar el total agregado de Fraude.

La solución implementada no inventa una modalidad de BP4_1. El programa toma
el total expandido de BPCOD 06 y lo incorpora como un componente directo con la
etiqueta:

  Clonación de tarjeta o fraude bancario (BPCOD 06)

Después agrega las respuestas BP4_1 de BPCOD 07. Así se cumple la identidad:

  Fraude total = BPCOD 06 + suma de BP4_1 para BPCOD 07

Esta decisión explica el cierre de Fraude 2010:

  1,010,803 de BPCOD 06
  + 1,003,742 de modalidades BP4_1 de BPCOD 07
  = 2,014,545 de Fraude total

La etiqueta de BPCOD 06 se marca explícitamente con el código para que nadie la
confunda con una opción original de BP4_1.


7. CATÁLOGOS DE MODALIDADES DE EXTORSIÓN
----------------------------------------
ENVIPE 2011 a 2024

  BP5_1 1   Telefónica
  BP5_1 2   Laboral
  BP5_1 3   Por internet/correo electrónico
  BP5_1 4   En la calle
  BP5_1 5   En negocio propio o familiar
  BP5_1 6   Cobro de piso
  BP5_1 7   Otro
  BP5_1 9   No especificado

ENVIPE 2025, año de referencia 2024

  BP5_1 1   Laboral
  BP5_1 2   Cobro de piso
  BP5_1 3   Otro
  BP5_1 9   No especificado

Advertencia de comparabilidad para 2025

En ENVIPE 2025 se reorganiza la medición del medio de comisión. Parte de la
información que antes aparecía directamente como modalidad histórica de BP5_1
se obtiene mediante preguntas adicionales sobre internet, llamada telefónica,
contacto presencial y lugar del contacto.

El CSV conserva las preguntas históricas BP4_1 y BP5_1 y, adicionalmente,
incorpora la pregunta 1.5a de ENVIPE 2025 en un bloque separado. La pregunta
1.5a no sustituye a las Secciones IV y V.

Las dos familias se distinguen con columnas diferentes. Esto permite validar
por separado que cada partición cierre con total_delito y evita sumar ambas
familias entre sí, lo que duplicaría el total de 2024.

Una presentación académica correcta debe señalar esta ruptura con una nota al
pie o separar las dos preguntas en series distintas.


7.1. PREGUNTA 1.5a DE ENVIPE 2025
---------------------------------
Para Fraude se agrupan BPCOD 07 y 08; para Extorsión se usa BPCOD 09.

La pregunta 1.5a es multirrespuesta. Para obtener una partición sin duplicados
se aplica esta prioridad operativa:

  BP1_5A_1  Internet o medios electrónicos
  BP1_5A_2  Llamada telefónica
  BP1_5A_3  Contacto presencial
  BP1_5A_4  Otro medio
  ninguno   Sin medio sustantivo

Con esta regla, para 2024 cada bloque cierra por separado:

  Fraude:    5,350,580 + 546,180 + 1,254,166 + 53,145 + 51,618 = 7,255,689
  Extorsión:   343,963 + 4,835,160 +   497,338 + 10,803 + 32,717 = 5,719,981

La columna cuest_modulo_envipe_7 contiene NA en estas filas. La columna
cuest_modulo_envipe2025_2 contiene la pregunta 1.5a. En las filas históricas
ocurre lo contrario.


8. CÓMO SE LEEN LOS DBF Y ZIP
-----------------------------
El programa busca recursivamente en conjunto_de_datos.

Reglas de descubrimiento:

- reconoce TMod_Vic.dbf sin distinguir mayúsculas y minúsculas;
- también abre archivos ZIP y busca dentro un archivo con ese nombre;
- obtiene la edición a partir del año presente en la ruta o nombre del archivo;
- si existe un DBF directo y un ZIP para la misma edición, prioriza el DBF;
- si existen dos DBF directos o dos ZIP candidatos para la misma edición, se
  detiene para evitar elegir una fuente de manera arbitraria;
- con --require-all se exige la presencia de todas las ediciones solicitadas.

El lector DBF:

- interpreta el encabezado, número de registros, longitud de registro y
  descriptores de campo;
- decodifica texto con latin-1, compatible con los DBF históricos;
- ignora registros marcados como eliminados en el archivo DBF;
- lee BPCOD, FAC_DEL, BP4_1 y BP5_1; para ENVIPE 2025 también lee
  BP1_5A_1, BP1_5A_2, BP1_5A_3 y BP1_5A_4;
- procesa registro por registro, por lo que no necesita cargar toda la base en
  memoria.

Normalización de códigos:

- BPCOD 7, 07 y 7.0 se normalizan como 07;
- una respuesta 1.000000 se normaliza como 1;
- no se cambia el significado del código, sólo su representación textual.

Tratamiento del factor:

- FAC_DEL vacío, no numérico, infinito o negativo se considera inválido;
- el registro se excluye y el número de exclusiones se informa en la consola;
- FAC_DEL=0 es aceptado porque no altera la estimación.


9. UNIDAD DE ANÁLISIS Y SIGNIFICADO ECONÓMICO
---------------------------------------------
La unidad procesada es el registro de delito del módulo TMod_Vic, no una persona
única y no un hogar único.

Por lo tanto:

- estimacion representa un número expandido de delitos o eventos;
- no debe interpretarse automáticamente como número de víctimas únicas;
- una misma persona puede haber reportado más de un delito;
- el total no es una tasa por cada 100,000 habitantes;
- el porcentaje es composición interna del delito, no prevalencia poblacional.

Para un economista, esta distinción es central: el resultado mide el volumen
expandido de eventos clasificados, sujeto al diseño y al universo de ENVIPE.


10. FÓRMULAS DE CÁLCULO
-----------------------
Para una edición e y un delito d:

  Total_exacto(e,d) = suma de FAC_DEL de todos los registros de d

Para una modalidad m:

  Estimacion_exacta(e,d,m) = suma de FAC_DEL de los registros de d y m

El porcentaje se calcula como:

  Porcentaje(e,d,m) =
      Estimacion_exacta(e,d,m) / Total_exacto(e,d) * 100

Salida:

- estimacion se redondea al entero más cercano;
- total_delito se redondea al entero más cercano;
- porcentaje se redondea a cuatro decimales;
- total_delito se repite en cada fila del mismo año y delito.

El cálculo del porcentaje usa los valores exactos acumulados antes del redondeo,
no los enteros ya escritos en el CSV.

Consecuencia del redondeo

Cada modalidad se redondea de manera independiente. Por ello, la suma de los
enteros visibles puede diferir por unas pocas unidades del total_delito, aunque
las sumas exactas internas cierren. Una diferencia grande no se explica por
redondeo; una diferencia pequeña debe evaluarse según el número de filas.


11. CONTENIDO DEL CSV PRINCIPAL
-------------------------------
Ejecución:

  python main.py

Columnas exactas:

  anio
  seccion
  delito
  modalidad_comision
  cuest_modulo_envipe_7
  cuest_modulo_envipe2025_2
  estimacion
  porcentaje
  total_delito

Sólo contiene:

  Fraude
  Extorsión

Interpretación:

- anio: año de referencia de los hechos, no año de edición;
- seccion: sección oficial del cuestionario;
- delito: agregado analítico Fraude o Extorsión;
- modalidad_comision: respuesta o categoría de la pregunta;
- cuest_modulo_envipe_7: texto de la pregunta histórica de Fraude o Extorsión;
  contiene NA cuando la fila no proviene de esa pregunta;
- cuest_modulo_envipe2025_2: texto de la pregunta 1.5a sólo para ENVIPE 2025;
  contiene NA en todas las demás filas;
- estimacion: suma expandida de FAC_DEL para la modalidad;
- porcentaje: participación de la modalidad dentro del total_delito;
- total_delito: total expandido del delito, repetido para facilitar análisis.

No se incluyen deliberadamente columnas de categoría general, base textual del
porcentaje, muestra ni variables técnicas, porque se solicitó un CSV reducido.


12. DESCARGA Y VALIDACIÓN CONTRA XLSX OFICIALES
-----------------------------------------------
Ejecución:

  python validar_inegi.py

El programa crea la carpeta inegi y busca el XLSX oficial de cada edición.

Comportamiento de descarga:

- utiliza URL directa del dominio www.inegi.org.mx;
- no depende del visor de Office Online;
- prueba las variantes tabulados y Tabulados porque INEGI ha usado ambas;
- conserva un XLSX ya existente si su estructura es válida;
- un XLSX se considera válido si es un archivo ZIP de Office con
  [Content_Types].xml y xl/workbook.xml;
- si el archivo está incompleto o no es XLSX, lo elimina e intenta descargarlo;
- --force-download obliga a descargar nuevamente;
- --no-download usa únicamente los archivos ya presentes.

Nombre especial de 2011

Para 2011 se intenta primero:

  III_caracteristicas_victimas_2011_est.xlsx

Para 2012-2025 se usa:

  III_denuncia_delito_AAAA_est.xlsx

El programa conserva en el CSV la URL realmente utilizada.


13. CÓMO SE EXTRAE EL TOTAL DE INEGI DEL XLSX
---------------------------------------------
El XLSX se lee directamente desde sus archivos XML internos. No se depende de
Excel, pandas ni openpyxl.

Procedimiento:

1. Se leen las hojas y cadenas compartidas del libro.
2. Se normaliza el texto para comparar sin diferencias de acentos, mayúsculas,
   espacios o notas al pie.
3. Se buscan renglones cuya etiqueta sea exactamente Fraude o Extorsión.
4. Se examinan las celdas numéricas ubicadas a la derecha de la etiqueta.
5. Cada candidato recibe una puntuación.

Elementos que aumentan la confianza del candidato:

- hoja cuyo nombre se relaciona con la tabla 3.1;
- contexto con la frase "delitos ocurridos por tipo";
- contexto con "condición de denuncia";
- encabezado que contiene "Total";
- primera columna numérica a la derecha de la etiqueta;
- magnitud compatible con un total nacional de delitos.

Elementos que reducen la confianza:

- encabezados de porcentaje;
- coeficiente de variación;
- error estándar;
- límites inferior o superior;
- tasas;
- valores demasiado pequeños para ser un total nacional.

Si dos candidatos cercanos tienen valores distintos, o la puntuación es baja,
el programa no elige arbitrariamente. Registra:

  NO EXTRAÍDO DEL XLSX

Fraude puede aparecer de dos maneras en los tabulados:

- como un renglón agregado llamado Fraude; o
- como dos renglones: Fraude bancario y Fraude al consumidor.

El validador primero busca el agregado. Si no existe, suma los dos componentes
y registra en metodo_extraccion_inegi que se usó esa suma.

Para Extorsión se busca el renglón agregado Extorsión.


14. PRUEBAS DE VALIDACIÓN
-------------------------
Para cada edición y delito se generan al menos dos comparaciones.

A. TOTAL_DELITO CSV CONTRA INEGI

Compara el valor repetido en total_delito con el total nacional extraído del
XLSX oficial.

B. SUMA MODALIDADES PREGUNTAS HISTÓRICAS CONTRA INEGI

Suma únicamente las filas de las preguntas históricas del módulo y compara el
resultado con el mismo total oficial.

C. SUMA MODALIDADES PREGUNTA 1.5A ENVIPE 2025 CONTRA INEGI

Se genera sólo para ENVIPE 2025. Suma las cinco categorías mutuamente
excluyentes de la pregunta 1.5a. No se suma junto con el bloque histórico.

La primera prueba comprueba la selección de BPCOD y el uso de FAC_DEL. Las
otras dos comprueban por separado que cada desglose no haya perdido registros.

Estatus principales:

  COINCIDE
  NO COINCIDE
  SIN ARCHIVO INEGI
  NO EXTRAÍDO DEL XLSX
  TOTAL INCONSISTENTE EN CSV
  SIN DATO EN CSV

La tolerancia predeterminada es una unidad:

  python validar_inegi.py --tolerance 1

La tolerancia sólo atiende diferencias mínimas por redondeo. No debe utilizarse
para ocultar diferencias sustantivas.


15. TRAZABILIDAD
----------------
VALIDACION_INEGI_ENVIPE.csv conserva:

- edición ENVIPE y año de referencia;
- tipo de validación;
- valor del CSV y valor de INEGI;
- diferencia absoluta y porcentual;
- estatus;
- número de filas de modalidad;
- nombre y SHA-256 del CSV principal;
- nombre, hoja, celda de etiqueta y celda de valor del XLSX;
- encabezado de la columna seleccionada;
- método de extracción;
- URL del XLSX;
- SHA-256 del XLSX;
- estado de descarga;
- ubicación exacta del DBF, incluso dentro de un ZIP;
- SHA-256 del DBF;
- URL del programa ENVIPE;
- URL del catálogo de metadatos;
- fecha y hora UTC de ejecución;
- notas de errores o ambigüedades.

El SHA-256 no prueba por sí mismo que una fuente sea correcta, pero sí permite
probar que el archivo revisado por otra persona es exactamente el mismo que se
usó en el cálculo.


16. QUÉ SÍ DEMUESTRA LA VALIDACIÓN Y QUÉ NO
-------------------------------------------
Sí demuestra:

- que el total calculado con FAC_DEL puede reproducir el total oficial;
- que se utilizó un archivo oficial identificable;
- que existe una ruta auditable desde DBF hasta CSV y XLSX;
- que el cierre de modalidades puede revisarse;
- que los cambios de código están programados explícitamente.

No demuestra por sí sola:

- que cada etiqueta de modalidad sea correcta en todos los años;
- que dos modalidades con nombres parecidos sean conceptualmente comparables;
- que la estimación tenga determinada precisión estadística;
- que el resultado sea una tasa, prevalencia o número de víctimas únicas;
- que no existan cambios adicionales de universo en una edición.

Por eso la defensa completa combina tres evidencias:

  cuestionario/diccionario + microdatos + tabulado oficial


17. LIMITACIONES ESTADÍSTICAS
-----------------------------
El proyecto utiliza FAC_DEL para producir estimaciones puntuales, pero no
implementa el diseño muestral completo.

No calcula:

- errores estándar;
- intervalos de confianza;
- coeficientes de variación;
- efectos de diseño;
- pruebas de hipótesis;
- significancia de cambios entre años.

Por tanto, es adecuado para reproducir totales puntuales y composiciones, pero
no para afirmar que una diferencia entre años es estadísticamente significativa.

También debe considerarse que las modalidades pueden tener cambios de redacción,
universo o estructura. La comparabilidad debe evaluarse antes de construir una
serie homogénea.


18. PROPUESTAS PARA DEFENDER EL PROCESAMIENTO
---------------------------------------------
Las siguientes prácticas fortalecen una exposición ante un profesor, revisor o
equipo técnico.

1. Presentar la cadena de evidencia

   Mostrar un ejemplo completo:

     cuestionario -> código BPCOD/BP4_1/BP5_1 -> registro DBF -> FAC_DEL
     -> suma del CSV -> celda del XLSX oficial

2. Conservar los archivos originales

   No editar los ZIP, DBF ni XLSX. Guardarlos en carpetas de sólo lectura y usar
   los SHA-256 del CSV de validación.

3. Versionar el código

   Guardar main.py, validar_inegi.py, envipe_core.py y README en Git. Etiquetar
   la versión usada para la entrega y registrar el identificador del commit.

4. Ejecutar con cobertura completa

     python main.py --require-all
     python validar_inegi.py --require-all

   Así el proceso falla si falta una edición, en vez de entregar una serie
   incompleta sin advertencia.

5. Hacer revisiones manuales de años de quiebre

   Como mínimo revisar:

   - ENVIPE 2011: primer catálogo y corrección BPCOD 06 + BP4_1;
   - ENVIPE 2012: segundo catálogo histórico;
   - ENVIPE 2013: cambio de códigos generales;
   - ENVIPE 2016: ejemplo documental visible en el cuestionario;
   - ENVIPE 2025: cambio de estructura de Extorsión.

6. Separar validación de etiquetas y validación de totales

   El XLSX valida el total. El cuestionario/diccionario valida el nombre de cada
   código. No afirmar que una sola de esas fuentes prueba ambas cosas.

7. Reportar códigos inesperados

   No borrar silenciosamente respuestas vacías o no catalogadas. Mantener las
   etiquetas diagnósticas y revisar su peso expandido.

8. Documentar redondeo

   Mostrar que el porcentaje se calcula con valores exactos y que los enteros
   visibles se redondean al final. Si la suma visible difiere por pocas unidades,
   reportar la diferencia y no modificar manualmente una fila para forzar cierre.

9. Agregar pruebas automatizadas

   Recomendaciones para una versión de producción:

   - prueba de que total exacto = suma exacta de modalidades;
   - prueba de que BPCOD 06 se incorpora sólo en ENVIPE 2011-2012;
   - prueba de catálogos por edición;
   - prueba de detección de duplicados de fuente;
   - prueba de descarga y validación de XLSX;
   - prueba de ambigüedad en la extracción de celdas;
   - prueba de que anio = edicion - 1.

10. Crear un anexo de catálogo

    Para una defensa formal, conviene producir una tabla por edición con:

      edición, año, variable, código, etiqueta, universo, fuente y página

    Esto permite que un tercero revise cada nombre sin leer el código Python.

11. Conservar un registro de ejecución

    Guardar la salida de consola, fecha, versión de Python, comando utilizado y
    hashes. Así se puede repetir exactamente la corrida entregada.

12. Revisión independiente

    Pedir a otra persona que ejecute el proyecto desde una carpeta limpia y
    compare los hashes de salida. La replicación independiente es una defensa
    más fuerte que una captura de pantalla.


19. ARGUMENTO METODOLÓGICO RESUMIDO
-----------------------------------
Una formulación defendible es:

"Los totales se calcularon directamente a partir del archivo TMod_Vic.dbf de
cada edición ENVIPE, sumando el factor de expansión FAC_DEL sobre los códigos de
delito definidos en los cuestionarios y diccionarios de INEGI. Los nombres de
modalidad provienen de los catálogos BP4_1 y BP5_1 específicos de cada edición;
no se aplicó un catálogo único a toda la serie. La edición ENVIPE se convirtió
al año de referencia restando una unidad porque el módulo pregunta por delitos
ocurridos en el año anterior. Los resultados se validaron de manera independiente
contra los tabulados XLSX oficiales, conservando URL, hoja, celda y huellas
SHA-256. Los cambios de cuestionario, en especial Fraude 2011-2012 y Extorsión
2025, se documentaron expresamente y no se ocultaron mediante ajustes manuales."


20. EJECUCIÓN
-------------
Desde PowerShell o CMD:

  cd C:\Users\gustavo.garcia\Documents\GitHub\ENVIPE
  python main.py --require-all
  python validar_inegi.py --require-all

Forzar descarga de XLSX:

  python validar_inegi.py --force-download

Validar sin internet:

  python validar_inegi.py --no-download

Cambiar rutas:

  python main.py --dir "D:\datos" --salida "D:\resultado.csv"

  python validar_inegi.py --csv "D:\resultado.csv" \
    --inegi-dir "D:\inegi" --salida "D:\validacion.csv"

Cambiar tolerancia:

  python validar_inegi.py --tolerance 0


21. DEPENDENCIAS
----------------
El proyecto utiliza únicamente la biblioteca estándar de Python.

No requiere:

- pandas;
- openpyxl;
- dbfread;
- Microsoft Excel.

La lectura de DBF y XLSX se implementa directamente para reducir dependencias y
hacer más transparente la lógica de extracción.
