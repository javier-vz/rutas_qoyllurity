# Camino inca, tramo Leimebamba – Chachapoyas

La pregunta no es por dónde pasó el camino —eso ya está registrado— sino
**qué variables del terreno explican por dónde pasó, y si son las mismas a lo
largo de todo el tramo**.

Este archivo es cómo correrlo. Las ecuaciones y el porqué de cada decisión
están en [`METODO.md`](METODO.md).

---

## Contenido

1. [Cómo está organizada la carpeta](#1-cómo-está-organizada-la-carpeta)
2. [Instalar el entorno](#2-instalar-el-entorno-una-sola-vez)
3. [La llave de OpenTopography](#3-la-llave-de-opentopography-una-sola-vez)
4. [Correr el estudio](#4-correr-el-estudio)
5. [El camino observado: de dónde sale](#5-el-camino-observado-de-dónde-sale)
6. [Los espacios ceremoniales: el archivo que falta](#6-los-espacios-ceremoniales-el-archivo-que-falta)
7. [Qué mirar en los resultados](#7-qué-mirar-en-los-resultados)
8. [Los parámetros](#8-los-parámetros)
9. [Si algo falla](#9-si-algo-falla)

---

## 1. Cómo está organizada la carpeta

El zip trae dentro una carpeta llamada `leimebamba/`. Descomprímelo **en la
carpeta que la contiene** (`C:\Users\jvera\Documents`), no dentro de
`leimebamba`: así cae encima de la que ya tienes y reemplaza el programa sin
tocar `datos/`, `derivados/` ni `resultados/`.

El zip **sí trae `config.yaml`**, con la caja del estudio ya puesta, así que
al descomprimir queda listo para correr. Eso significa que si lo tenías
editado, se reemplaza.

Lo que importa de verdad es el bbox, y ése está protegido: si el bbox de
`config.yaml` no coincide con los rásteres que hay en `derivados/`, el
programa **se para y lo dice**, con las dos cajas y las dos salidas
posibles. No sigue y no da números medidos con la rejilla equivocada — que
es lo que pasaba antes de ese chequeo, en silencio.

`config.yaml` lleva dentro la versión con que se escribió. Si eliges no
reemplazarlo al descomprimir y le faltan parámetros nuevos, el programa te
avisa al arrancar.

Para comprobar que quedó la versión nueva, cualquier comando imprime ahora
su versión y la carpeta desde la que corre:

```
camino 0.5.0 (2026-10-05)
proyecto: C:\Users\jvera\Documents\leimebamba
```

Si ahí sale otra carpeta, estás corriendo otra copia.

```
leimebamba/
│
├── config.yaml          ← el único archivo que vas a editar
├── environment.yml         receta del entorno de conda
├── README.md               este archivo
├── METODO.md               las ecuaciones
│
├── camino/                 el programa (no hace falta abrirlo)
├── tests/                  las pruebas
│
├── datos/               ← aquí caen las descargas, solas
│   └── gpx/             ← aquí van los .gpx del Garmin, cuando lleguen
├── derivados/           ← aquí caen los rásteres calculados, solos
└── resultados/          ← aquí caen las tablas y las figuras, solas
```

Las tres carpetas de abajo empiezan vacías y **el programa las llena solo**.
No tienes que bajar ni mover ningún archivo a mano, con una excepción: los
`.gpx` del Garmin, que van a `datos/gpx/` cuando Dina vuelva del campo.

---

## 2. Instalar el entorno (una sola vez)

Abre la **consola de Anaconda** (en Windows, *Anaconda Prompt*; búscala en el
menú de inicio). Entra a la carpeta y crea el entorno:

```bash
cd C:\Users\jvera\Documents\leimebamba
conda env create -f environment.yml
conda activate camino
```

Tarda unos minutos la primera vez. Comprueba que quedó bien:

```bash
python -m pytest -q
```

Tienen que pasar **243 pruebas** en dos o tres segundos. Si falla algo aquí,
falla antes de tocar datos, que es cuando conviene.

> **Cada vez que abras la consola de nuevo**, dos cosas: `conda activate
> camino` y `cd` a la carpeta del proyecto. Si Python dice que no encuentra un
> paquete, casi siempre es que falta el `conda activate`.

No hace falta QGIS, ArcGIS, GRASS ni comandos de GDAL. El programa hace la
reproyección, el recorte, la hidrología y el grafo en Python. QGIS sólo sirve
al final, para mirar los resultados en un mapa.

---

## 3. La llave de OpenTopography (una sola vez)

Es gratis e inmediata, y sirve para bajar los modelos de elevación.

1. Entra a <https://portal.opentopography.org/> y créate una cuenta.
2. Ve a **My Account** y pide una *API key*.
3. Dísela a la consola, en la misma ventana donde vas a trabajar:

```bash
set OPENTOPOGRAPHY_API_KEY=pega_aqui_tu_llave          REM Windows
export OPENTOPOGRAPHY_API_KEY=pega_aqui_tu_llave       # Linux / macOS
```

Eso dura mientras la ventana esté abierta; si la cierras, hay que repetirlo.
Se hace así, y no se guarda en un archivo, para que la llave no acabe subida
al repositorio sin querer.

Si te cansa repetirlo, conda la puede guardar **dentro del entorno**, que es
mejor que dejarla suelta en el sistema:

```
conda activate camino
conda env config vars set OPENTOPOGRAPHY_API_KEY=pega_aqui_tu_llave
conda activate camino
```

El segundo `conda activate` no es un error de copia: hace falta para que la
variable entre en la sesión que ya está abierta. Después aparece sola cada
vez que actives `camino`. Se comprueba con `conda env config vars list` y se
quita con `conda env config vars unset OPENTOPOGRAPHY_API_KEY`.

Ojo que en el Anaconda Prompt el valor va **sin comillas** y sin espacios
alrededor del `=`: en cmd las comillas entran como parte del valor y la llave
sale mal.

---

## 4. Correr el estudio

### El orden, de una vez

**Si cambiaste `extension.bbox`** (o es la primera vez), tres comandos:

```bash
python -m camino bajar --forzar    # el DEM de la caja nueva
python -m camino ruta  --forzar    # el recorte del registro, de la caja nueva
python -m camino todo              # el resto, de corrido
```

Los dos `--forzar` son obligatorios y no son opcionales de estilo: cambiar la
caja invalida **todo** lo que hay en `datos/` y `derivados/`. El programa ya
detecta solo el caso del DEM y lo vuelve a bajar avisando, pero con el
`--forzar` no hay nada que detectar.

**Si NO cambiaste la caja**, uno:

```bash
python -m camino todo
```

Salta `bajar` y `ruta` porque los archivos ya están, y rehace el resto.

**Para decidir la caja**, antes de todo lo anterior:

```bash
python -m camino ruta --forzar
python -m camino caja
```

**Nunca** `python -m camino todo --forzar`: vuelve a bajar los DEM sin
necesidad y son varios minutos.

---

Diez pasos, en orden. Cada uno deja su resultado en disco, así que puedes
parar y seguir otro día sin perder nada.

```bash
python -m camino bajar          # 1
python -m camino ruta           # 2
python -m camino preparar       # 3
python -m camino superficies    # 4
python -m camino grafo          # 5
python -m camino revisar        # 6
python -m camino nulos          # 7
python -m camino barrido        # 8
python -m camino validar        # 9
python -m camino resultados     # 10
```

O `python -m camino todo` de corrido.

| # | Paso | Qué hace | Qué escribe | Tarda |
|---|---|---|---|---|
| 1 | `bajar` | los dos modelos de elevación y los cuerpos de agua | `datos/cop30_raw.tif`, `datos/aw3d30_raw.tif`, `datos/agua_osm.json` | minutos, según la conexión |
| 2 | `ruta` | el camino observado (ver §5) | `datos/qn_geocam.gpkg` | segundos |
| 3 | `preparar` | pone los dos modelos en la misma rejilla, recorta el corredor | `derivados/cop30.tif`, `derivados/mascara.tif` | ~1 min |
| 4 | `superficies` | pendiente y aspecto; la rugosidad, como **restricción**, recorta la máscara; el drenaje queda de diagnóstico | `derivados/pendiente_rad.tif`, `rugosidad.tif`, `acumulacion.tif`, `mascara.tif` | 2–5 min |
| 5 | `grafo` | el grafo de tránsito, con una columna por componente | `derivados/grafo.npz` | 1–2 min |
| 6 | `revisar` | traza **un camino por unidad** para que los mires | `resultados/revision_pendiente.gpkg`, `revision_grafo.json` | segundos |
| 7 | `nulos` | el conjunto de control: 500 rutas plausibles por unidad, y los dos nulos (geometría y costo) | `derivados/nulos.npz` | **~2 h 15** |
| 8 | `barrido` | corre **los dos modelos** sobre cada unidad y los compara | `resultados/optimos_por_unidad.json`, `caminos_optimos.gpkg` | ~6 min |
| 9 | `validar` | la prueba que decide: pesos estimados sin un bloque, medidos **en** ese bloque | `resultados/validacion_bloqueada.json` | ~20 min |
| 10 | `resultados` | el perfil de equifinalidad y su gráfico | `resultados/perfil_equifinalidad.png` | segundos |

Los tiempos son **medidos** en la caja del estudio (6.44 M celdas, seis
tramos completos, vecindades de 150 000 a 290 000 nodos) en la laptop de
Javier, octubre 2026.

`nulos` es el caro con diferencia, y no por el tamaño de la caja sino por el
número de Dijkstras: 500 realizaciones × 6 unidades = 3 000, contra 126 del
barrido. Si hay que repetirlo, baja `barrido.m_nulos` — con 200 el piso del
valor *p* sube de 0.002 a 0.005, que para estos resultados sigue sobrando.

Y si enciendes `visibilidad`, el barrido pasa de 21 juegos de pesos a 231:
cuenta con una hora en vez de seis minutos.

Los pasos 8 y 9 necesitan el archivo de espacios ceremoniales (§6). Sin él,
avisan y te dicen qué hacer en vez de reventar.

### Cinco ayudas que no son pasos

No van en el orden: se corren cuando hacen falta.

```bash
python -m camino caja          # qué bbox haría falta para que los tramos
                               # entren completos, y lo que costaría
python -m camino buscar        # encuentra la dirección del servicio de GeoCAM
python -m camino sensibilidad  # repite el barrido con otros cortes (sólo
                               # tiene sentido con 'unidad: sector')
python -m camino red           # el Qhapaq Ñan como RED, no como rejilla:
                               # ¿da el registro para medir centralidad?
python -m camino campo         # desarma la razón de costo por zonas y arma
                               # las estaciones de campo, con su GPX
python -m camino trayectorias  # tracks grabados: separa marcha de permanencia
                               # y dice dónde se va el tiempo
```

`campo` necesita que `revisar` haya corrido antes, porque trabaja sobre las
dos líneas que ése produce. Tarda unos 3 minutos y deja en `resultados/` un
`estaciones.gpx` para el GPS, un `estaciones.gpkg` para QGIS y un
`estaciones.csv`. Lo que hace está en `METODO.md`, §6 quinquies.

`red` lee el registro **nacional sin recortar**, no la caja del estudio: es
otra pregunta y necesita todo el sistema. Tarda unos 20 minutos y necesita
`networkx`.

`trayectorias` es el único paso que no necesita DEM ni red: lee los `.gpx`
**con sello de tiempo** que haya en `datos/trayectorias/` y mide el tiempo,
no la forma. Es para tracks grabados, no para el registro — el registro es
una línea sin reloj y entra por `ruta`. Deja en `resultados/` un
`trayectorias.csv`, un `trayectorias_sensibilidad.csv` y un `paradas.gpkg`
con las paradas como puntos para QGIS. Lo que hace está en `METODO.md`,
§8 bis ter.

Ojo con una cosa: el número principal de ese paso, la fracción de tiempo en
permanencia, **depende de cómo se defina una parada**, y el paso imprime la
tabla de sensibilidad al lado del resultado precisamente por eso. En los
tracks de Qoyllur Rit'i va de 10% a 71% según el criterio. No se reporta un
número sin decir cuál se usó.

La caja que propone deja **`dominio.buffer_corredor` de aire** alrededor de
los extremos de los tramos — no un margen redondo cualquiera. Con menos, la
máscara del corredor queda recortada por el borde de la caja justo donde el
tramo termina, el camino modelado se pega a ese borde y `revisar` lo marca
con `B`; y arreglarlo obliga a ensanchar y volver a correr desde `bajar`. Si
cambias `buffer_corredor`, vuelve a correr `caja`.

`caja` imprime una tabla **acumulada**: añade tramos de más barato a más
caro y te dice, en cada fila, cuántas unidades completas tendrías, cuántas
celdas y cuánta memoria pediría el grafo. Se eligen tramos, no coordenadas —
copias el bbox de la fila que te convenga. Con *n* unidades completas salen
*n(n−1)/2* pares para el perfil de equifinalidad: con 2 hay 1 par (no se
contrasta nada), con 4 hay 6, con 6 hay 15.

### Cuidado con `tramnomb`: no todos los valores son tramos

El registro usa ese campo para dos cosas. Casi todos los valores son tramos
("A – B"), pero también hay **estados de trabajo del Ministerio** (`En
proceso`, y `En Proceso` con otra grafía) y rasgos **sin nombre**. Agrupados
por nombre, dan "tramos" cuya caja envolvente mide mil kilómetros de
diagonal.

Se excluyen **a mano**, por nombre exacto, en `datos.tramos_excluidos`:

```yaml
datos:
  tramos_excluidos:
    - ""
    - "En proceso"
    - "En Proceso"
```

**Y no con una regla automática.** Hubo una —descartar los grupos con más de
150 km de diagonal— y estaba mal: declaró que "no son tramos" Xauxa –
Pachacámac (163 km), La Raya – Desaguadero (293), Pumpu – Pallasca (338) y
Acostambo – Huamachuco (588), que son secciones reales del Qhapaq Ñan, varias
inscritas en la UNESCO. El registro es nacional y hay tramos con nombre de
cientos de kilómetros: ninguna regla geométrica los separa de una etiqueta
con garantías.

Lo que el programa sí hace es **medir y avisar**. Para cada grupo calcula la
razón entre la diagonal de su caja y los kilómetros de línea que contiene. Un
camino, por largo que sea, es al menos tan largo como la recta entre sus
extremos, así que su razón ronda 1 (con los huecos del registro, 2 o 3). Una
etiqueta repartida por el mapa tiene mucha diagonal y poca línea, y la razón
se dispara. Cuando una unidad que **entra al análisis** pasa de 5, lo dice:

```
AVISO: estas unidades parecen ETIQUETAS del registro y no tramos:
  'En proceso' tiene 12.4 km de linea repartidos en una caja de 80 km
  de diagonal (razon 6.5). Eso parece una ETIQUETA del registro y no un
  tramo. Si lo es, anadelo a 'datos.tramos_excluidos' en config.yaml.
```

La decisión es arqueológica y queda escrita en `config.yaml`, no enterrada en
el código.

Si ya corriste `ruta` antes de esto, vuelve a correr
`python -m camino ruta --forzar`.

### Tres cosas sobre el orden

**`revisar` es el paso que no se salta.** Traza un camino por unidad con todo
el peso en el costo físico y los guarda en un GeoPackage, con el observado al
lado. Ábrelo en QGIS encima del modelo de elevación y míralos con ojos de
arqueóloga: ¿pasan por donde pasaría un camino?, ¿cruzan las quebradas por
donde se puede cruzar? Si no son plausibles, ninguno de los siguientes lo
será, y no hay estadística que lo arregle.

La tabla que imprime marca dos cosas, y las dos invalidan el número que está
al lado:

- `*` **la unidad está recortada por la caja** — uno de sus extremos no es un
  destino, es donde cortamos. `python -m camino caja` dice cuánto habría que
  ensanchar el bbox y lo que costaría en celdas y en memoria.
- `B` **el camino se pegó al borde de su vecindad** — es el `buffer_corredor`
  el que está decidiendo, no el terreno. Súbelo y vuelve a correr desde aquí.

La D que imprime `revisar` se mide **en la misma vecindad** que va a usar el
barrido, así que anticipa lo que el barrido va a reportar con
`w_fisico = 1`. Si ahí ya sale mal, no hace falta gastar media hora en nulos.

**`nulos` va antes que `barrido`, y no es intercambiable.** Una unidad cuyo
mejor camino no le gana a terreno aleatorio no tiene pesos que valga la pena
reportar. Al revés, se acaban comparando pesos de unidades donde el modelo no
explica nada, y los números parecen válidos sin serlo.

**`validar` no es opcional, es el resultado.** El paso 8 va a reportar que el
modelo ampliado ajusta mejor que el de referencia. Eso **no significa nada**:
tiene más parámetros, así que ajusta mejor por construcción sobre los mismos
datos con que se estimaron sus pesos. El paso 9 estima los pesos dejando fuera
un pedazo del trazado y los mide sobre ese pedazo, sin recalibrar. Si ahí el
ampliado no gana, la mejora era capacidad de ajuste y la consola lo dice con
esas palabras.

### Los pasos 1, 3 y 4 no necesitan el camino

Si el paso 2 se atasca, sáltatelo y sigue: `bajar`, `preparar` y
`superficies` sólo trabajan con el modelo de elevación. Son los que más
tardan, y dejan todo listo. Cuando `preparar` corre sin camino, usa la caja
entera como dominio y te lo dice. A partir de `grafo` sí hace falta.

---

## 5. El camino observado: de dónde sale

El paso 2 acepta tres fuentes:

```bash
python -m camino ruta                                       # GeoCAM
python -m camino ruta --fuente archivo --archivo X.shp      # un archivo tuyo
python -m camino ruta --fuente osm                          # apaño provisional
```

### GeoCAM, que es lo que corresponde

Es el registro del Ministerio de Cultura, y es la fuente que se cita en un
artículo. El programa entra por **WFS**, el estándar OGC que el propio portal
publica. El endpoint ya viene escrito en `config.yaml`; lo único que falta es
saber qué capa es el camino, y eso lo averigua:

```bash
python -m camino buscar
```

Lista las capas que publica el servidor, las ordena de más a menos probable y
escribe la primera en `config.yaml`. Después, `python -m camino ruta`.

**A octubre de 2026 ese servidor está caído.** Devuelve un *Proxy Error —
Error during SSL Handshake with remote server*, y falla igual desde el
navegador, así que no es nada que puedas arreglar de tu lado. El programa
prueba cuatro rutas del servidor y reintenta; si aun así no responde, está
caído y hay que usar una de las otras dos fuentes mientras tanto.

### Un archivo tuyo — el KMZ del registro

La salida práctica mientras GeoCAM no vuelva, y la que está en uso.

[GEO GPS PERÚ](https://www.geogpsperu.com/2020/10/mapa-del-qhapaq-nan-camino-inca.html)
publica el Qhapaq Ñan nacional en KMZ y shapefile, descarga directa. El KMZ
no es una traza suelta: trae **las categorías con que el Ministerio clasifica
cada segmento**, cada una en su propia capa. Ponlo en `datos/` y:

```bash
python -m camino ruta
```

**No hace falta ninguna opción**: si hay un archivo de geometría en `datos/`,
el programa lo encuentra y lo usa; sólo si no hay ninguno intenta GeoCAM. Si
tienes varios, prefiere el KMZ o KML del registro antes que un GPX de campo.
Para forzar uno concreto: `--fuente archivo --archivo datos/X.kmz`.

El programa lo abre, saca los atributos (que vienen escondidos en una tabla
HTML dentro de cada placemark), imprime el inventario de tramos y se queda
con el que pide `config.yaml`.

**Excluye las capas de «Proyección de Camino»** por Reemplazo, Daños o
Ausencia. Son tramos donde el camino ya no está y la línea la dibujó alguien
infiriendo por dónde iba; ajustar el modelo contra ellas es circular. Está
explicado en `METODO.md`, §8 bis, y se controla con `datos.solo_observadas`.

Lo que hay en la caja del estudio, medido sobre ese KMZ:

| Tramo | rasgos | km | continuo |
|---|---|---|---|
| Leymebamba – Chilchos – Mendoza | 2 | 29.29 | 29.29 |
| La Jalca – Mendoza | 5 | 20.25 | 20.25 |
| Chachapoyas – Jumbilla | 9 | 16.97 | 14.28 |
| Pauja – Santa Cruz | 3 | 14.21 | 14.21 |
| **Chillo – Chachapoyas** | **11** | **23.02** | **12.40** |
| Chachapoyas – Cochamal | 13 | 28.71 | 8.55 |
| Pueblo Viejo – La Jalca Grande | 6 | 13.57 | 7.90 |

**Chillo – Chachapoyas** es el tramo del proyecto, y es el que viene puesto
en `config.yaml`. Para estudiar otro, cambia `datos.tramo`; para usarlos
todos, déjalo vacío.

También entran por aquí un shapefile, un GeoPackage, un GeoJSON, o el `.gpx`
del Garmin de Dina cuando vuelva del campo.

### OpenStreetMap, sólo como apaño

Baja las trazas etiquetadas como `historic` o con «inca» o «qhapaq» en el
nombre. Sirve para que el código corra de punta a punta mientras no hay nada
mejor. Son trazas cargadas por voluntarios, sin control de precisión ni
criterio arqueológico: el programa las marca como `osm_provisional` y te lo
recuerda al terminar. **No valen para publicar.**

---

## 6. Los espacios ceremoniales: el archivo que falta

Es el **único dato de entrada que no se baja solo**, y de él salen las dos
componentes del modelo ampliado. Sin él, los pasos 8 y 9 avisan y paran.

Déjalo en `datos/` con un nombre que empiece por `sitios`:

```
datos/sitios.gpkg      datos/sitios.shp      datos/sitios.csv
datos/sitios.geojson   datos/sitios.kmz
```

Un CSV basta, con una columna de nombre y las coordenadas en grados:

```csv
nombre,lon,lat
Nombre del sitio,-77.925,-6.418
```

Acepta puntos y polígonos; de un polígono se toma su punto representativo (un
recinto, a 30 m de resolución, es un punto). Si están en otro sistema de
coordenadas, el programa lo reproyecta solo. Los sitios pueden caer **fuera de
la caja**: uno a 2 km del borde sigue condicionando las celdas de dentro, y se
usa igual.

### Las dos reglas que hay que aplicar al armarlo

Vienen del proyecto, no son técnicas, y cambian el resultado:

1. **Un sitio que se reconoció *por* el camino no puede explicar el camino.**
   Si la identificación de un lugar dependió principalmente de estar junto a
   la vía, usarlo como predictor es circular. Esto el código **no lo puede
   decidir**: es criterio arqueológico y se filtra al armar el archivo. Es la
   decisión más importante de todo este paso.
2. **Un sitio en el extremo del tramo analizado se excluye de su componente.**
   Esta sí la hace el código, tramo por tramo (`ceremonial.radio_extremos`,
   500 m por omisión), porque si no el modelo recibe como premio acercarse a un
   punto al que tiene que llegar de todas formas. Te dice en la consola
   cuántos quitó.

### Qué pasa si no hay archivo

El paso 8 corre igual con el modelo de referencia, que sólo usa el costo
físico, y los pasos 1 a 7 no lo necesitan para nada. Lo que no se puede hacer
sin él es la pregunta del proyecto.

Si quieres correr todo sin sitios mientras llega el catálogo, quita las
componentes del modelo ampliado en `config.yaml`:

```yaml
costo:
  componentes_ampliado: [fisico]
```

### Los datos de campo no van al repositorio

Los Excel de campo llevan coordenadas exactas de evidencias. **No subas los
crudos.** `datos/` está en `.gitignore` por eso. Lo que se publica son los
resultados, no las ubicaciones.

---

## 7. Qué mirar en los resultados

**Al terminar el paso 2**, el programa imprime cuántos metros de *polilínea
continua* trajo. Es el número que decide el diseño del estudio:

- Con bastante camino continuo, se puede partir en sectores **y** validar en
  bloques: ajustar los pesos en los sectores pares y medir qué tan bien
  predicen los impares.
- Con poco, las dos cosas compiten por los mismos metros y hay que elegir
  una. Esa decisión se toma **antes** de correr el barrido, no después de ver
  los resultados.

Si el tramo continuo más largo baja de unos 15 km, el programa lo avisa.

Para Chillo – Chachapoyas ya está medido: **23.02 km registrados en 3 piezas,
la mayor de 12.40 km**. Con eso, `n_sectores: 4` da 3.10 km por sector (unas
103 celdas de 30 m), que deja margen al camino de mínimo costo dentro de cada
sector y además permite validación bloqueada —ajustar en los pares, medir en
los impares—. Con 6 sectores bajarían a 2.07 km y empezarían a ser demasiado
cortos para que los pesos signifiquen algo.

**Al terminar el paso 8**, `resultados/optimos_por_unidad.json` trae una fila
por unidad con **los dos modelos lado a lado**:

| campo | qué es |
|---|---|
| `D_referencia_m` | distancia media al camino observado, sólo costo físico |
| `D_ampliado_m` | lo mismo, añadiendo el espacio ceremonial |
| `mejora_pct` | cuánto baja — **y no es evidencia de nada, ver abajo** |
| `w_*_ampliado` | los pesos óptimos del ampliado |
| `*_tau10` | el **rango** de cada peso en el conjunto casi-óptimo |
| `frechet_*_m` | la segunda métrica, la peor correspondencia |
| `p_nulo` | contra terreno aleatorio |

El rango es lo que se reporta en el texto: no «w_ceremonial = 0.35» sino
«w_ceremonial entre 0.20 y 0.45». Y `caminos_optimos.gpkg` trae las
geometrías —una por modelo y por unidad, más el observado— para abrirlas en
QGIS y mirarlas encima del terreno.

**`mejora_pct` no es un resultado.** El modelo ampliado tiene más parámetros,
así que ajusta mejor por construcción sobre los mismos datos con que se
estimaron sus pesos. Si se reporta esa cifra como evidencia de que el espacio
ceremonial condiciona el trazado, el argumento es circular.

**Al terminar el paso 9**, `resultados/validacion_bloqueada.json` trae lo que
sí se puede reportar: para cada bloque retenido, `D_ajuste_m` (en los bloques
con que se estimaron los pesos) y `D_retenido_m` (en el bloque que no vio). La
consola resume en una línea **en cuántos bloques retenidos gana el ampliado**.
Si gana en la mitad o menos, el resultado del estudio es que las componentes
añadidas no aportan información espacial — y eso es un resultado publicable,
no un fracaso.

**Al terminar el paso 10**, `resultados/perfil_equifinalidad.png` es la figura
principal: cómo se separan los conjuntos de pesos entre unidades. Dos unidades
cuyas curvas se van abajo y se quedan abajo están gobernadas por variables
distintas. Dos que se solapan no se distinguen con estos datos, y eso también
es un resultado.

---

## 8. Los parámetros

Todos viven en `config.yaml`, cada uno con su comentario. Si un umbral
aparece escrito dentro del código, es un error.

Tres que probablemente toques:

**`unidad`** — qué se compara con qué. Es la decisión de diseño del estudio.

```yaml
barrido:
  unidad: tramo          # o "sector"
  largo_min_unidad: 8000
```

Con `tramo`, cada tramo con nombre del registro es una unidad: el Ministerio
los registró y los nombró de forma independiente, así que comparar pesos
entre ellos compara cosas que existen. Con `sector`, un solo tramo se corta en
`n_sectores` pedazos iguales — sirve para preguntar si algo cambia *a lo
largo* de un tramo, pero el resultado siempre carga con la sospecha de
depender de dónde cayó el corte, y para eso está `python -m camino
sensibilidad`.

**`componentes_referencia` / `componentes_ampliado`** — los dos modelos que se
comparan.

```yaml
costo:
  componentes_referencia: [fisico]
  componentes_ampliado: [fisico, ceremonial]
```

`fisico` es el costo metabólico de Minetti, la única componente anisotrópica
(ir y volver no cuestan lo mismo). `ceremonial` es la proximidad a los
espacios ceremoniales. Para añadir la intervisibilidad con esos mismos
sitios:

```yaml
  componentes_ampliado: [fisico, ceremonial, visibilidad]
```

Con dos componentes son 21 juegos de pesos; con tres, 231, y el barrido pasa
de segundos a media hora. Antes de encender `visibilidad`, lee la sección
`visibilidad` de `config.yaml`: **en este corredor no hay apu documentado**,
así que la componente mide otra cosa que en el proyecto del Coropuna.

La rugosidad y el drenaje **ya no son componentes con peso**. La rugosidad es
restricción (`restricciones.rugosidad_percentil`) y el drenaje es
diagnóstico; así los dos modelos comparten el mismo espacio de tránsito y la
diferencia entre ellos es atribuible a lo que se añadió.

**`buffer_corredor`** — media anchura, en metros, de la franja alrededor del
camino por donde el modelo puede buscar.

```yaml
dominio:
  buffer_corredor: 4000
```

Existe por cómputo: el área completa son tres millones y medio de celdas y no
se pueden barrer. Pero si la franja es estrecha, es ella la que decide el
resultado. Por eso `revisar` comprueba si el camino modelado se pegó al
borde; si avisa, sube este número y vuelve a correr desde `preparar`.

**`umbral_quebrada`** — cuántas celdas de área drenada hacen que una celda
cuente como quebrada.

```yaml
dominio:
  umbral_quebrada: 500
```

500 celdas son 0.45 km² a 30 m. Es el único parámetro de todo el modelo que
el trabajo de campo fija directamente: se calibra contra las quebradas que
realmente haya que cruzar.

### Datos sensibles

Las coordenadas de evidencias arqueológicas sensibles o no publicadas no
entran al repositorio público. El `.gitignore` ya excluye `datos/` y
`derivados/`, y todo lo que hay ahí se regenera corriendo los pasos, así que
no se pierde nada por no versionarlo. Lo que se publique pasa antes por las
restricciones institucionales que correspondan.

---

## 9. Si algo falla

| Lo que dice la consola | Qué pasa |
|---|---|
| `ModuleNotFoundError` | falta `conda activate camino` |
| `Falta la llave de OpenTopography` | el `set OPENTOPOGRAPHY_API_KEY=...` del §3, en esta misma ventana |
| `no se pudo bajar el agua de OpenStreetMap` | Overpass está saturado. **No bloquea nada**: la máscara queda sin excluir lagunas. Reintenta luego con `python -m camino bajar --forzar` |
| `Falta la dirección de GeoCAM` | corre `python -m camino buscar`, o usa otra fuente (§5) |
| `Proxy Error … SSL Handshake` | el servidor del Ministerio está caído. No es tuyo. Usa otra fuente (§5) |
| `Ningún endpoint WFS respondió` | lo mismo; el programa ya probó cuatro rutas, dos veces |
| `ninguna parece ser el camino` | mira la lista que imprime `buscar` y pon a mano la capa en `geocam_capa` |
| `no tiene nada dentro de la caja del tramo` | bajó una capa que no es el camino, o el tramo no está digitalizado ahí |
| `No hay camino entre los extremos` | el dominio está partido. El mensaje dice en qué componente cae cada extremo y qué suele causarlo; mira `derivados/mascara.tif` en QGIS |
| `el camino modelado toca el borde del corredor` | sube `buffer_corredor` y vuelve a correr desde `preparar` |
| `la pieza continua mide X m` | poco camino continuo para tantos sectores: baja `n_sectores` |

---

## Por qué no se usa un GIS para esto

- `r.cost` de GRASS es isotrópico: no distingue subir de bajar.
- `r.walk` sí distingue, pero tiene su función de marcha cableada por dentro
  y no admite pesos elegidos por el usuario.
- `MCP_Geometric` de scikit-image es isotrópico.
- QGIS no trae nada equivalente.

Ninguno permite recorrer sistemáticamente juegos de pesos sobre un costo que
distinga el sentido de la marcha, que es exactamente lo que pide la pregunta.
De ahí el programa: numpy y scipy, sin dependencias raras.
