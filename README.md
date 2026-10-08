# Qoyllur Rit'i — el recorrido de la peregrinación

Valle de Sinakara – Ausangate, provincia de Quispicanchi, Cusco.

Paquete `camino` 0.21.0 · esta carpeta se armó el 8 de octubre de 2026.

Es una carpeta de proyecto completa: el bbox, el CRS y los derivados son
suyos, y el programa se para si el bbox no coincide con los rásteres de
`derivados/`. Si usas el paquete para otra zona, hazlo en otra carpeta.

---

## Contenido

1. [La pregunta](#1-la-pregunta)
2. [Cómo está organizada la carpeta](#2-cómo-está-organizada-la-carpeta)
3. [El entorno y la llave](#3-el-entorno-y-la-llave)
4. [Correr el estudio](#4-correr-el-estudio)
5. [Lo que ya salió](#5-lo-que-ya-salió)
6. [Los parámetros](#6-los-parámetros)
7. [Lo que falta](#7-lo-que-falta)
8. [Qué no se publica](#8-qué-no-se-publica)

---

## 1. La pregunta

**Qué sostiene la forma de una peregrinación.**

Una peregrinación es movimiento colectivo que se reproduce cada año, con
decenas de miles de personas, sin que nadie la haya diseñado y sin que nadie
la administre. Tiene una forma reconocible y la mantiene. Hay etnografía
abundante de Qoyllur Rit'i —lo que significa, quiénes van, qué se hace— y no
hay una descripción de cómo se mueve: dónde se va el tiempo, qué fija el
ritmo, por qué el recorrido tiene la geometría que tiene.

La hipótesis de partida es que **una peregrinación no es una ruta, es un
horario con lugares**: hay sitios que hay que tocar y horas a las que hay que
tocarlos, y caminar es lo que conecta los sitios, no el propósito. Si eso es
así, una ruta de mínimo costo no puede producir el recorrido, porque una
curva que minimiza $\int C\,\mathrm{d}s$ no tiene reloj.

Para contestarlo se miden tres cosas:

1. **Dónde se va el tiempo** — marcha contra permanencia, por trecho, por
   hora del día y por altitud.
2. **Cuánto se aparta el recorrido del óptimo físico** — y, sobre todo, si el
   costo llega a distinguir las dos cosas.
3. **Si el recorrido está organizado respecto del Ausangate** — visibilidad
   del nevado desde la ruta y desde las estaciones.

El dato es un registro GPS de la peregrinación de junio de 2026: doce tracks
de OsmAnd, un punto cada 15–16 s, con `hdop` y con la velocidad que declara
el propio receptor.

---

## 2. Cómo está organizada la carpeta

```
<esta carpeta>/
├── camino/                     el paquete (el codigo)
├── config.yaml                 los parámetros del estudio
├── datos/
│   ├── trayectorias/           los doce .gpx grabados, con sello de tiempo
│   ├── favoritos_qoyllurity_2026.gpx    los waypoints marcados en el GPS
│   ├── qn_geocam.gpkg          el camino observado, que arma 'ruta'
│   ├── cop30_raw.tif           lo que baja 'bajar'
│   └── aw3d30_raw.tif
├── derivados/                  lo que arman 'preparar' y 'superficies'
├── resultados/                 las salidas
├── environment.yml
├── METODO.md                   las ecuaciones
└── README.md                   esto
```

**No trae el banco de pruebas.** Varios tests llevan geometrias de prueba en
el corredor del Utcubamba y se apoyan en el `config.yaml` del proyecto, asi
que con esta caja caen fuera y fallan. Es una costura del banco de pruebas
--deberian usar una config sintetica propia-- y vale arreglarla, pero no
tiene sentido arrastrar aqui diez fallos que no dicen nada del codigo. El
`camino/` de esta carpeta es byte por byte el mismo que pasa los 423.

`datos/trayectorias/` es la entrada del paso nuevo y, a través de `ruta`, la
fuente del camino observado: **aquí el recorrido grabado hace de camino**, no
hay una línea de registro aparte.

---

## 3. El entorno y la llave

Todo desde el **Anaconda Prompt**.

```
conda env create -f environment.yml
conda activate camino
```

Para la llave de OpenTopography, lo más cómodo es que conda la guarde dentro
del entorno:

```
conda activate camino
conda env config vars set OPENTOPOGRAPHY_API_KEY=pega_aqui_tu_llave
conda activate camino
```

El segundo `conda activate` no es un error de copia: hace falta para que la
variable entre en la ventana que ya está abierta. Se comprueba con
`conda env config vars list`.

En el Anaconda Prompt el valor va **sin comillas** y sin espacios alrededor
del `=`: en cmd las comillas entran como parte del valor y la llave sale mal,
y el error que devuelve el portal después no dice eso, dice que la llave es
inválida.

Si prefieres no guardarla, `set OPENTOPOGRAPHY_API_KEY=...` dura lo que dure
la ventana.

---

## 4. Correr el estudio

### El paso que no necesita nada

```
python -m camino trayectorias
```

Funciona sin DEM, sin red y sin llave. Lee los `.gpx`, separa marcha de
permanencia, clasifica el modo de viaje y escribe en `resultados/`:

| archivo | qué trae |
| --- | --- |
| `trayectorias.csv` | una fila por track: modo, horas de marcha, horas de parada, km, desnivel, número de paradas, duración mediana |
| `trayectorias_sensibilidad.csv` | la fracción de tiempo parado según los dos parámetros que la definen |
| `paradas.gpkg` | las paradas como puntos, capa `paradas`, para QGIS |

### Recalcular todo, de cero

Esta carpeta viene con `derivados/` y `resultados/` **vacios** a proposito.
Todo se vuelve a calcular con estos pasos, en este orden:

```
python -m camino bajar          # COP30 y AW3D30 de la caja
python -m camino preparar       # los alinea, arma la máscara
python -m camino superficies    # pendiente, rugosidad, drenaje
python -m camino grafo          # el grafo de vecindad 16 y la matriz Phi
python -m camino ruta           # los tracks COMO camino observado
python -m camino revisar        # un óptimo por trecho, para mirarlos
python -m camino razon          # la razón de costo según el ancho de franja
```

La caja es de 878 × 1204 celdas, un millón de nodos: baja en un par de
minutos y el grafo pide unos 0.09 GB.

`ruta` detecta sola que el camino observado son los tracks, porque hay
`datos/trayectorias/` y no hay archivo de geometría. Los agrupa en **trechos**
continuos: dos tracks consecutivos son el mismo trecho si empalman a menos de
100 m y menos de 4 h. Esa regla salió de los datos y hace falta — hay un
empalme de 1888 m con 5.15 h de hueco que no es continuación de nada.

`preparar` avisa de que la máscara es la caja entera, y está bien: no hay
corredor al que restringirse, y los óptimos entre los extremos de los tracks
tienen que poder irse por donde quieran.

### Lo que todavía se para

`nulos`, `barrido`, `validar` y `resultados` necesitan el catálogo ceremonial,
que está por armar (§7).

---

## 5. Lo que ya salió

### Dónde se va el tiempo

De las doce trazas, ocho son a pie (36.5 km) y cuatro en camión (121 km). El
modo no está puesto a mano: sale del percentil 95 de la velocidad durante la
marcha, que da entre 0.9 y 1.8 m/s a pie y entre 10.3 y 14.0 en camión.

La fracción de tiempo en permanencia **depende de cómo se defina una parada**,
y mucho: va de 10% a 71%. Con el criterio del propio receptor (velocidad
Doppler cero) da 10–15%; con el de dispersión (todos los fijos dentro de 20 m
durante al menos 2 minutos) da 40–70%. No es que uno esté mal: miden cosas
distintas, la detención y el desplazarse despacio dentro de una estación. Hay
que reportar el par.

Lo que **no** se mueve con los parámetros es el orden entre trechos. La
subida a Colque Punku sale siempre como el más estático —2 km y 414 m de
desnivel entre las 23:53 y las 04:36— y el descenso final como el más fluido.

### El costo no distingue el recorrido de su propio óptimo

| trecho | km | separación mediana | Fréchet | **razón de costo** |
| --- | --- | --- | --- | --- |
| el circuito de retorno | 20.5 | 463 m | 1792 m | **1.07** |
| Mahuayani – Santuario | 8.7 | 71 m | 305 m | **1.03** |

Y es estable: ensanchando la franja de 60 a 360 m, el circuito pasa de 1.07 a
1.03 y la subida de 1.03 a 1.00.

**En la subida el modelo acierta.** Las dos líneas van encimadas los 8.7 km,
con 71 m de separación mediana y sólo el 4% del recorrido a más de 250 m del
óptimo. Quien sube a un lugar conocido toma el camino barato, y el modelo lo
reproduce.

**En el circuito las dos rutas van por sitios distintos y cuestan casi lo
mismo.** El óptimo corre a 463 m de media del recorrido, con 1792 m de
Fréchet y el 63% del trayecto a más de 250 m — y cuesta un 7% menos. Se ve en
`resultados/dos_rutas.png`: el óptimo cruza alto por la ladera mientras lo
caminado baja al valle, y vuelven a juntarse.

Eso es **equifinalidad**: hay muchas maneras de cruzar ese paisaje por un
precio parecido. Y es un resultado más fuerte que una razón alta. Si el
circuito costara 1.6 la conclusión sería «lo ceremonial cuesta caro»; lo que
sale es que **el costo físico no puede explicar la forma del recorrido ni
descartarla**. La explicación tiene que venir de las estaciones y del horario,
y la componente ceremonial tiene algo concreto que hacer: dar cuenta de los
463 m de geometría, no del 7% de costo.

De paso, eso asciende la tercera pregunta —ruta o horario— de especulativa a
principal, porque el costo acaba de quedar mostrado como poco informativo
aquí.

### Las paradas señalan estaciones que no están marcadas

De las 68 paradas, sólo 12 caen a menos de 300 m de un waypoint del GPS; la
mediana a la estación marcada más cercana es 1123 m.

Eso no refuta nada: los 13 waypoints son los que se alcanzaron a marcar, no un
catálogo. Lo que dice es lo contrario, y es útil: **las paradas son evidencia
de dónde están las estaciones**. La más larga —123 minutos a 4611 m, durante
la marcha nocturna— está a 2.7 km del waypoint más próximo. Ahí hay una
estación que no está en la lista.

Ese cruce es lo primero que hay que mirar. Hay dos archivos para eso:

- **`resultados/qoyllur_qgis.gpkg`** — las cuatro capas juntas para QGIS:
  `recorrido`, `optimo`, `paradas` y `estaciones`. Se arrastra y salen todas.
- **`resultados/qoyllur_rit_i_2026.kmz`** — lo mismo para Google Earth. Abre
  en la versión web y en la de escritorio. Los ocho tramos van numerados y
  con su hora de salida y llegada, así que la secuencia se lee sin barra de
  tiempo.
- **`resultados/qoyllur_rit_i_2026_animado.kmz`** — sólo Google Earth Pro de
  escritorio. Además lleva el recorrido como `gx:Track` y las paradas con
  `TimeSpan`: con la barra de tiempo encendida la peregrinación avanza con
  sus horas reales, incluida la marcha nocturna. **Google Earth Web no lee
  ninguna de esas dos cosas** y da error si se le abre este archivo.

Los iconos van dentro del KMZ, no en una URL: así no dependen de que un
servidor ajeno siga vivo ni de que haya internet.

Los dos salen de `resultados/` y llevan sólo los waypoints del estudio.

### La calidad del DEM

La discrepancia entre Copernicus y ALOS es de 1.0–1.4 m de mediana por debajo
de 4800 m, y sube a 3.5 m sobre 5000, 6.3 sobre 5200 y 9.0 sobre 5500. De las
293 celdas con más de 100 m de diferencia, el **82% está a menos de 3 km de la
cumbre del Ausangate** y **ninguna** a menos de 3 km del santuario o de Colque
Punku.

Es casi lo mejor que podía pasar: el terreno donde se camina está bien sujeto
y la incertidumbre se concentra en el objetivo de la visibilidad, donde no
muerde — ±100 m en una cumbre de 6317 m vista desde 27 km cambia el ángulo de
elevación 0.21°.

El grafo tiene 13.4 millones de aristas, 13.1 por nodo —el límite de ±45%
quitó el 18.2% de las 16 posibles— y 855 componentes conexas, de las que la
mayor tiene el 99.74% de los nodos. Los 16 extremos de los tracks están todos
dentro de ella.

**Una cosa a revisar:** el percentil 99.9 de la pendiente da 89.6°, o sea una
pared vertical. Es casi seguro un artefacto del ráster y conviene mirarlo
antes de usarlo.

### Un hallazgo del propio dato

Entre el track del amanecer y el del descenso final hay **1888 m y 5.15 h sin
grabar**; los otros tres empalmes del circuito son de 78, 10 y 12 m. Ese
último track no es continuación: es un segmento aparte, y pegarlo dibujaría
una recta de 2 km por terreno del que no hay dato. La regla de trechos lo
separa sola.

---

## 6. Los parámetros

El detalle completo, con sus razones, está en los comentarios de
`config.yaml`. Lo que conviene saber de memoria:

| parámetro | valor | por qué |
| --- | --- | --- |
| `crs` | EPSG:32719 | el estudio está a −71.2°, o sea en la zona **19S**. La 18S proyectaría a 408 km del meridiano central en vez de 241 |
| `bbox` | −71.425 / −13.824 / −71.185 / −13.5 | los ocho tracks a pie **más el Ausangate**, con 4 km de aire |
| `visibilidad.puntos` | la cumbre del Ausangate | es el apu documentado (Wikidata Q777794), y toda la peregrinación ocurre en su campo visual |
| `visibilidad.radio` | 30 000 m | del valle de Sinakara al nevado hay 27 km, y la pregunta es si se ve desde ahí |
| `largo_min_unidad` | 2 000 m | las unidades son los trechos entre estaciones; el más corto tiene 1.2 km |
| `g_max` | 0.45 | el rango en que se midió el polinomio de Minetti. El 26.7% del área lo pasa |

El Ausangate entra a la caja aunque ningún track lo pise: una cuenca visual
necesita el terreno **del objetivo** y todo el que haya en medio, y el ángulo
de elevación por sí solo no dice si se ve, porque puede haber una cresta.

Los cuatro tramos en camión quedan **fuera** de la caja a propósito: meterlos
la llevaría hasta −71.6 y la triplicaría, y el acercamiento por carretera no
es lo que se modela. `trayectorias` los mide igual, porque eso no necesita
DEM; `ruta` no los convierte en camino, porque una carretera moderna está
trazada buscando ahorro con maquinaria y su razón de costo mide la ingeniería
vial de hoy.

---

## 7. Lo que falta

**El catálogo de espacios ceremoniales.** `ceremonial.archivo` está vacío a
propósito, y mientras lo esté el modelo ampliado se para con un mensaje — que
es lo correcto. Las estaciones están en `datos/favoritos_qoyllurity_2026.gpx`
como waypoints, y tres tienen identificador de Wikidata (Ausangate Q777794,
Colque Punku Q13190737, Sinakara Q13190788). Pero un catálogo ceremonial no es
una lista de puntos marcados en el GPS: hace falta decir de qué fuente sale
cada uno, qué es (estación de la procesión, santuario, apu, cruz) y si la
posición es la relevada o la del lugar. Eso se escribe a mano con la
bibliografía al lado, y **las 68 paradas son la mejor pista de dónde buscar**.

**La pendiente de las trayectorias desde el ráster.** Hoy sale del altímetro
del aparato, con ruido de orden del metro: sobre un paso de 30 m son unos 3
puntos de pendiente. Con el DEM en disco se puede tomar del ráster, y el
módulo ya devuelve las coordenadas de cada paso para eso.

**El horizonte de las paradas nocturnas**, si se quiere probar lo del
amanecer. Necesita perfil de horizonte por acimut, que no está escrito.

**n = 1.** Es un caminante y un año. Se puede decir qué hizo él, no qué hizo
la multitud. Para la hipótesis de que el ritmo lo fija la densidad de gente
hace falta otra fuente —conteos, fotos, bibliografía— o varios tracks, y eso
no se puede aumentar hasta el año que viene. Va adelante en el texto, no al
final.

---

## 8. Qué no se publica

Los GPX traen waypoints personales: una casa particular, el cementerio de
Paucartambo, la casa de una persona con nombre y apellido. Esos nueve
waypoints quedan fuera de la capa `estaciones` del GeoPackage a propósito.

Y traen el glaciar y Colque Punku, que es un lugar de acceso restringido
dentro de una práctica religiosa viva. Eso pide su propio criterio: antes de
publicar cualquier cosa hay que decidir qué se publica, con qué permiso y de
quién.

Para el `.gitignore`: fuera `datos/`, `derivados/` y `resultados/*.gpkg`.
`paradas.gpkg` y `qoyllur_qgis.gpkg` en particular, que son precisamente el
cruce entre horarios y lugares.
