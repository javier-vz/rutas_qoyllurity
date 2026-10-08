# Qoyllur Rit'i — proyecto nuevo, carpeta aparte

Peregrinación de Qoyllur Rit'i: valle de Sinakara – Ausangate, Cusco.
Misma maquinaria que Leimebamba, proyecto distinto. **No mezclar las dos
carpetas**: el bbox, el CRS y los derivados son otros, y el programa se para
si el bbox no coincide con los rásteres de `derivados/`.

Paquete `camino` 0.21.0.

---

## Lo que ya corre, sin DEM

```
conda activate camino
python -m camino trayectorias
```

Eso funciona ahora mismo, contra los doce tracks que están en
`datos/trayectorias/`. No necesita red ni raster. Es el paso nuevo: lee los
GPX con sello de tiempo, separa marcha de permanencia, clasifica el modo de
viaje y escribe tres cosas en `resultados/`:

| archivo | qué trae |
| --- | --- |
| `trayectorias.csv` | una fila por track: modo, horas de marcha, horas de parada, km, desnivel, número de paradas, duración mediana |
| `trayectorias_sensibilidad.csv` | la fracción de tiempo parado en función de los dos parámetros que la definen |
| `paradas.gpkg` | las paradas como puntos, capa `paradas`, para abrir en QGIS |

El `paradas.gpkg` es el que importa mirar primero. Si el recorrido está
organizado por estaciones, las paradas tienen que caer sobre ellas — y eso
se ve cargándolo en QGIS junto a `datos/favoritos_qoyllurity_2026.gpx`,
antes de modelar nada.

### Lo que salió

De las doce trazas, ocho son a pie (36.5 km) y cuatro en camión (121 km). El
modo no está puesto a mano: sale del percentil 95 de la velocidad durante la
marcha, que da entre 0.9 y 1.8 m/s a pie y entre 10.3 y 14.0 en camión.

El número grande, la fracción de tiempo en permanencia, **depende de cómo se
defina una parada**, y mucho: va de 10% a 71%. Con el criterio del propio
receptor (velocidad Doppler cero) da 10–15%; con el de dispersión (todos los
fijos dentro de 20 m durante al menos 2 minutos) da 40–70%. La diferencia no
es un defecto del cálculo: son dos cosas distintas. El receptor marca la
detención; la dispersión marca además el desplazarse despacio dentro de una
estación. Lo que hay que reportar es el par, no uno de los dos.

Lo que **no** se mueve con los parámetros es el orden entre tramos. La
subida a Colque Punku sale siempre como el tramo más estático del recorrido
(78% con los parámetros por omisión: 2 km y 414 m de desnivel entre las
23:53 y las 04:36), y el descenso final siempre como el más fluido. Eso es
lo que sostiene cualquier comparación interna.

---

## Bajar el DEM

Lo demás necesita el raster. Son dos pasos y los dos están automatizados; lo
único que hace falta es la llave de OpenTopography.

### 1. La llave

**Regenera la llave antes de usarla.** La que pegaste en el chat hay que
darla por comprometida. Se saca en
`https://portal.opentopography.org/myopentopo` (hay que entrar con la
cuenta), y en la misma página se revoca la anterior.

Después la pones en el entorno, **no** en `config.yaml`. En el
**Anaconda Prompt**, con el entorno activado:

```
conda activate camino
conda env config vars set OPENTOPOGRAPHY_API_KEY=la_llave_nueva
conda activate camino
```

Esa es la forma buena en conda: la variable queda guardada **dentro del
entorno `camino`**, así que aparece cada vez que lo actives y no anda
suelta por el sistema. El segundo `conda activate` no es un error de copia
— hace falta para que la variable entre en la sesión actual.

Para comprobar que está:

```
conda env config vars list
echo %OPENTOPOGRAPHY_API_KEY%
```

Si alguna vez quieres sacarla:

```
conda env config vars unset OPENTOPOGRAPHY_API_KEY
```

Y si sólo la quieres para un rato, sin guardarla, en el Anaconda Prompt
basta `set`:

```
set OPENTOPOGRAPHY_API_KEY=la_llave_nueva
```

Ojo que con `set` va **sin comillas** y sin espacios alrededor del `=`: en
cmd las comillas entran como parte del valor y la llave sale mal.

El programa la toma primero del entorno y sólo después del archivo,
justamente para que no acabe en el control de versiones.

### 2. Bajarlo

```
conda activate camino
cd <esta carpeta>
python -m camino bajar
```

Baja **dos** modelos de elevación para la misma caja — Copernicus GLO-30 y
ALOS AW3D30 — y los alinea a una rejilla común. Son dos y no uno a propósito:
la diferencia entre ellos es la banda de incertidumbre vertical, y el paso la
imprime.

La caja es `-71.425 / -13.824 / -71.185 / -13.5`, o sea 25.6 × 36.0 km, un
millón de celdas. Es **seis veces más chica** que la de Leimebamba (6.44
millones), así que esto baja en un par de minutos y no en media hora.

Si falla con error de llave, el mensaje lo dice. Si falla por red, reintenta:
el portal de OpenTopography se cae a ratos.

### 3. Y lo que sigue

```
python -m camino preparar       # alinea los dos DEM, arma la máscara
python -m camino superficies    # pendiente, rugosidad, drenaje
python -m camino grafo          # el grafo de vecindad 16 y la matriz Phi
```

Todo desde el Anaconda Prompt con `camino` activado. Si el entorno no está
creado todavía, se crea una sola vez desde la carpeta del paquete:

```
conda env create -f environment.yml
conda activate camino
```

Con 1.02 M de celdas el grafo pide unos 0.09 GB a K = 1, así que entra sin
problema en memoria.

A partir de ahí ya se puede:

- **recalcular la pendiente de las trayectorias desde el ráster** en lugar
  del altímetro del aparato, que es el límite que tiene hoy la tabla de
  velocidad contra pendiente;
- **calcular rutas de mínimo costo** entre los extremos que los propios
  tracks marcan, y compararlas con lo caminado;
- **calcular la cuenca visual del Ausangate**, que ya está puesto en
  `visibilidad.puntos` del `config.yaml` con su coordenada de cumbre y un
  radio de 30 km.

---

## Lo que falta y no lo puede hacer el programa

**El catálogo de espacios ceremoniales.** `ceremonial.archivo` está vacío a
propósito, y mientras lo esté el modelo ampliado se para con un mensaje —
que es lo correcto.

Las estaciones están en `datos/favoritos_qoyllurity_2026.gpx` como
waypoints: santuario, Colque Punku, Sinakara, Tayankani, Yanacancha,
Mahuayani. Tres tienen identificador de Wikidata (Ausangate Q777794, Colque
Punku Q13190737, Sinakara Q13190788).

Pero un catálogo ceremonial no es una lista de puntos marcados en el GPS.
Hace falta decir de qué fuente sale cada uno, qué es (estación de la
procesión, santuario, apu, cruz) y si la posición es la relevada o la del
lugar. Eso se escribe a mano con la bibliografía al lado, y es la pieza que
decide si la segunda pregunta del proyecto se puede plantear.

---

## Dos cosas que conviene saber del CRS y de los datos

**Va en EPSG:32719, no 32718.** Leimebamba está en la zona 18S y Amazonas cae
ahí; Qoyllur Rit'i está a −71.2°, o sea en la **zona 19S**. Usar 32718 aquí
proyecta a 408 km del meridiano central en vez de 241, y las distancias
salen infladas: los ocho tracks dan 36.987 km en 32718 y 36.941 en 32719. Es
un 0.12%, poco, pero gratis de arreglar y de los errores que nadie revisa
después.

**Los cuatro tramos en camión quedan fuera de la caja.** Meterlos llevaría el
borde hasta −71.6 y triplicaría el raster, y el acercamiento por carretera no
es parte de lo que se modela: no se camina y su trazado es ingeniería vial
moderna. Los archivos están en `datos/trayectorias/` y `trayectorias` los
mide igual, porque eso no necesita DEM.

---

## Lo que no va al repositorio público

Los GPX traen waypoints personales: tu casa, el cementerio de Paucartambo, la
casa de Mariano Martínez. Y traen el glaciar y Colque Punku, que es un lugar
de acceso restringido dentro de una práctica religiosa viva.

Eso es distinto de una coordenada arqueológica sensible y pide su propio
criterio, no el mismo. Antes de publicar cualquier cosa de esto habría que
decidir qué se publica, con qué permiso y de quién.
