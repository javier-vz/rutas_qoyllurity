"""Visibilidad: que fraccion de los puntos pertinentes se ve desde cada celda.

La componente mide intervisibilidad, y acepta los puntos por dos vias que se
suman:

    'ceremonial.archivo'    los espacios ceremoniales del catalogo
    'visibilidad.puntos'    cumbres o referentes con nombre, en la config

Las dos entran a la misma cuenta. Cual de las dos tiene sentido en un area
dada NO lo decide este modulo: es una decision del estudio y vive en su
`config.yaml`, al lado de las coordenadas, porque depende de lo que la
documentacion de esa zona describa.

LA DIRECCION DE LA MIRADA NO ES LA MISMA EN TODAS PARTES, y conviene tenerlo
presente al rellenar la config. Donde hay un apu con nombre, con culto
registrado y con santuario de altura, "ver el cerro" es una variable bien
definida y se calcula desde un punto: ese caso va en 'visibilidad.puntos'.
Donde la documentacion no describe ningun cerro tutelar sino una relacion
con el paisaje en conjunto -- sitios sobre afloramientos y farallones
prominentes, muy visibles desde lejos, o estructuras funerarias en cornisas
visibles de un lado a otro del valle-- lo que se hace visible es el SITIO y
no la montana, y entonces lo que sirve es la intervisibilidad con los
propios espacios ceremoniales.

Esta componente usa el mismo archivo de entrada que la proximidad, y las dos
preguntan cosas distintas sobre el mismo dato: si lo que condiciona el
trazado es pasar CERCA de un sitio o pasar DONDE SE VE. Por eso pueden
entrar las dos al modelo ampliado sin ser redundantes -- y por eso conviene
mirar si sus pesos se reparten o si una se come a la otra.

LIMITE QUE HAY QUE DECIR EN EL TEXTO, NO ESCONDER: una cuenca visual sobre
un DEM de 30 m es visibilidad POTENCIAL SOBRE TERRENO DESNUDO Y CON BUEN
TIEMPO. El modelo no tiene vegetacion ni nubes, y en una ceja de selva con
bosque de neblina cerrado buena parte del ano eso es mucho suponer, igual
que en alta montana con el nevado tapado media manana. Es una idealizacion,
como el resto del modelo, y se enmarca como "una hipotesis de modelamiento y
no como evidencia directa de intencionalidad historica".
"""

from __future__ import annotations

import numpy as np

R_TIERRA = 6371000.0        # m, radio medio
K_REFRACCION = 0.13         # refraccion atmosferica estandar en topografia


def indices_fraccionarios(t6, x, y):
    """(fila, columna) fraccionarias, en coordenadas de CENTRO de pixel.

    Centro y no esquina: `grafo.xy` devuelve centros, asi que el nodo (i, j)
    tiene que caer exactamente en (i, j) y no en (i+0.5, j+0.5).
    """
    a, b, c, d, e, f = (float(v) for v in t6)
    if b or d:
        raise ValueError("solo rejillas alineadas con los ejes")
    return (y - f) / e - 0.5, (x - c) / a - 0.5


def bilineal(dem, fil, col):
    """DEM interpolado bilinealmente. Fuera del raster devuelve NaN."""
    dem = np.asarray(dem, dtype=np.float64)
    h, w = dem.shape
    fil = np.asarray(fil, dtype=np.float64)
    col = np.asarray(col, dtype=np.float64)

    dentro = (fil >= 0) & (fil <= h - 1) & (col >= 0) & (col <= w - 1)
    f0 = np.clip(np.floor(fil), 0, h - 2).astype(np.int64)
    c0 = np.clip(np.floor(col), 0, w - 2).astype(np.int64)
    tf = np.clip(fil - f0, 0.0, 1.0)
    tc = np.clip(col - c0, 0.0, 1.0)

    z = ((1 - tf) * ((1 - tc) * dem[f0, c0] + tc * dem[f0, c0 + 1])
         + tf * ((1 - tc) * dem[f0 + 1, c0] + tc * dem[f0 + 1, c0 + 1]))
    return np.where(dentro, z, np.nan)


def elevacion_de(dem, t6, xy):
    """Elevacion en unas coordenadas proyectadas; NaN si cae fuera."""
    xy = np.atleast_2d(np.asarray(xy, dtype=np.float64))
    fil, col = indices_fraccionarios(t6, xy[:, 0], xy[:, 1])
    return bilineal(dem, fil, col)


def _ve(dem, t6, origen, z_origen, destinos, z_destinos, n_muestras):
    """True donde la linea de vista entre origen y cada destino esta libre.

    La correccion por curvatura y refraccion se aplica a la CUERDA entre los
    dos extremos, que es la formulacion simetrica. El terreno intermedio SUBE
    (1-k)*dp*(d-dp)/(2R) respecto de la recta -- sube y no baja: la cuerda
    entre dos puntos de la esfera pasa por DENTRO, asi que el suelo de en
    medio se interpone. Es algebraicamente lo mismo que restarle
    (1-k)*d^2/(2R) a la elevacion del objetivo, que es como lo escriben
    GRASS y ArcGIS; se puede comprobar: con dos puntos a cota 0 sobre llano,
    el despeje queda (1-k)*dp*(d-dp)/(2R) > 0, o sea tapado, que es lo
    correcto -- dos puntos al nivel del mar no se ven.

    A 8 km de cuerda eso es 1.1 m en el punto medio; a 15 km, 3.8 m. Pequeno,
    pero del mismo orden que el error vertical del DEM, asi que no se tira.
    Y para un observador de 1.65 m sobre terreno llano fija el horizonte en
    unos 4.9 km, que es el numero clasico.

    Los dos extremos quedan FUERA del maximo: ahi el terreno coincide por
    construccion con la linea y una celda propia tapandose a si misma daria
    siempre invisible.
    """
    dx = destinos[:, 0] - origen[0]
    dy = destinos[:, 1] - origen[1]
    d = np.hypot(dx, dy)

    s = (np.arange(1, n_muestras + 1, dtype=np.float64)
         / (n_muestras + 1))[None, :]

    xs = origen[0] + dx[:, None] * s
    ys = origen[1] + dy[:, None] * s
    fil, col = indices_fraccionarios(t6, xs, ys)
    z_terreno = bilineal(dem, fil, col)

    dp = d[:, None] * s
    sagita = (1.0 - K_REFRACCION) * dp * (d[:, None] - dp) / (2.0 * R_TIERRA)
    z_linea = z_origen + (z_destinos[:, None] - z_origen) * s

    exceso = z_terreno + sagita - z_linea
    # NaN = fuera del raster o sin dato: no obstruye. Es la eleccion
    # permisiva, y hay que saberlo: un hueco del DEM no crea visibilidad
    # donde no la hay, pero tampoco la quita.
    exceso = np.where(np.isfinite(exceso), exceso, -np.inf)
    return exceso.max(axis=1) <= 0.0


def fraccion_visible(dem, t6, puntos_xy, nodos_xy, radio: float,
                     h_observador: float = 1.65, h_objetivo: float = 0.0,
                     bloque: int = 4096) -> tuple[np.ndarray, dict]:
    """Fraccion de los sitios que se ven desde cada nodo, en [0, 1].

    `radio` es el alcance maximo que se acredita. Mas alla no se cuenta como
    visible: en ceja de selva una cuenca visual de 40 km es un artefacto del
    DEM, no una relacion que nadie haya tenido.

    Devuelve tambien un resumen con los sitios que quedaron fuera del raster
    (no se les puede calcular elevacion, asi que no entran).
    """
    dem = np.asarray(dem, dtype=np.float64)
    puntos_xy = np.atleast_2d(np.asarray(puntos_xy, dtype=np.float64))
    nodos_xy = np.atleast_2d(np.asarray(nodos_xy, dtype=np.float64))
    if puntos_xy.size == 0:
        raise ValueError("no hay ningun sitio desde el que calcular la cuenca")

    z_sitios = elevacion_de(dem, t6, puntos_xy)
    usables = np.isfinite(z_sitios)
    if not usables.any():
        raise ValueError(
            "ninguno de los sitios cae dentro del DEM: no se puede calcular "
            "la cuenca visual (la proximidad si funciona, esta no)")

    z_nodos = elevacion_de(dem, t6, nodos_xy) + h_observador
    res = abs(float(t6[0]))
    n_muestras = max(2, int(np.ceil(radio / (res / 2.0))))

    cuenta = np.zeros(len(nodos_xy), dtype=np.float64)
    for p, z in zip(puntos_xy[usables], z_sitios[usables]):
        d = np.hypot(nodos_xy[:, 0] - p[0], nodos_xy[:, 1] - p[1])
        cerca = np.flatnonzero(d <= radio)
        for i in range(0, len(cerca), bloque):
            idx = cerca[i:i + bloque]
            ve = _ve(dem, t6, p, z + h_objetivo,
                     nodos_xy[idx], z_nodos[idx], n_muestras)
            cuenta[idx] += ve

    n = int(usables.sum())
    frac = cuenta / n
    return frac, {
        "sitios_usados": n,
        "sitios_fuera_del_dem": int((~usables).sum()),
        "muestras_por_linea": n_muestras,
        "radio_m": float(radio),
        "nodos_con_algun_sitio_visible": int((frac > 0).sum()),
        "fraccion_media": float(frac.mean()),
    }


def costo(frac_visible) -> np.ndarray:
    """De fraccion visible a COSTO: ver sale barato, no ver sale caro.

    La componente ceremonial mide separacion (mas lejos = mas penalizacion);
    esta tiene que ir en el mismo sentido para que los pesos del simplex
    signifiquen lo mismo en las dos.
    """
    return 1.0 - np.clip(np.asarray(frac_visible, dtype=np.float64), 0.0, 1.0)
