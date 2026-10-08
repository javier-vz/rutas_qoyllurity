"""Distancia entre el camino modelado y el camino observado.

Se reportan DOS numeros, no uno:

  - La distancia media simetrica mide el desacuerdo tipico. Sola, esconde
    que el modelo se fue por otra quebrada y volvio.
  - La distancia de Frechet discreta mide el peor desacuerdo respetando el
    orden del recorrido. Sola, castiga igual un desvio puntual que un error
    sistematico.

El barrido se optimiza con la media simetrica (es la que se puede calcular
miles de veces) y la Frechet se reporta para los optimos.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

# Vertices a los que se remuestrea antes de calcular la Frechet. La
# recursion es O(p*q), asi que comparar a numero fijo de vertices ademas de
# ser barato hace comparables los valores entre caminos de largo distinto.
VERTICES_FRECHET = 250


def remuestrea(P, n: int) -> np.ndarray:
    """Remuestrea una polilinea a `n` vertices equiespaciados en longitud."""
    P = np.asarray(P, dtype=np.float64)
    if P.ndim != 2 or P.shape[0] < 2:
        return P.copy()
    paso = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    if paso[-1] <= 0:
        return np.repeat(P[:1], n, axis=0)
    objetivo = np.linspace(0.0, paso[-1], n)
    return np.column_stack([np.interp(objetivo, paso, P[:, k])
                            for k in range(P.shape[1])])


def distancia_media_simetrica(P, Q) -> float:
    """Media de las distancias al vecino mas cercano, en los dos sentidos.

        D_H(P,Q) = 1/2 ( mean_p min_q |p-q| + mean_q min_p |q-p| )

    En metros, si P y Q estan en una proyeccion metrica (UTM 18S).
    """
    P = np.asarray(P, dtype=np.float64)
    Q = np.asarray(Q, dtype=np.float64)
    if P.size == 0 or Q.size == 0:
        return float("inf")
    dpq, _ = cKDTree(Q).query(P)
    dqp, _ = cKDTree(P).query(Q)
    return float(0.5 * (dpq.mean() + dqp.mean()))


def frechet_discreta(P, Q, vertices: int | None = VERTICES_FRECHET) -> float:
    """Distancia de Frechet discreta (Eiter & Mannila 1994).

        delta(a,b) = max{ d(P_a, Q_b),
                          min{ delta(a-1,b), delta(a-1,b-1), delta(a,b-1) } }
        D_F(P,Q)   = delta(|P|, |Q|)

    Se evalua con una sola fila en memoria, O(min(p,q)) de espacio.
    """
    P = np.asarray(P, dtype=np.float64)
    Q = np.asarray(Q, dtype=np.float64)
    if P.size == 0 or Q.size == 0:
        return float("inf")
    # Las DOS al MISMO numero de vertices, siempre. La Frechet discreta es
    # sensible al muestreo de las polilineas, no solo a su forma: comparar
    # un camino modelado de 1500 celdas con una geometria de GeoCAM de 200
    # vertices sin igualar el muestreo infla la distancia por decenas de
    # metros que no son desacuerdo, son discretizacion.
    if vertices is not None and vertices >= 2:
        P = remuestrea(P, vertices)
        Q = remuestrea(Q, vertices)
    if len(P) < len(Q):          # la fila corre sobre el mas corto
        P, Q = Q, P

    q = len(Q)
    # fila a = 0
    ant = np.maximum.accumulate(np.linalg.norm(P[0] - Q, axis=1))
    act = np.empty(q)
    for a in range(1, len(P)):
        d = np.linalg.norm(P[a] - Q, axis=1)
        act[0] = max(ant[0], d[0])
        for b in range(1, q):
            act[b] = max(min(ant[b], ant[b - 1], act[b - 1]), d[b])
        ant, act = act, ant
    return float(ant[-1])


def longitud(P) -> float:
    """Longitud de una polilinea, en las unidades de sus coordenadas."""
    P = np.asarray(P, dtype=np.float64)
    if P.shape[0] < 2:
        return 0.0
    return float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())


def toca_borde(camino_filcol, mascara, margen: int = 1) -> bool:
    """True si el camino modelado toca el borde del dominio transitable.

    Chequeo de una linea que se olvida siempre: si el camino se pega al
    borde del corredor, es el buffer el que esta decidiendo el resultado y
    hay que ensancharlo antes de creerse nada.
    """
    fc = np.asarray(camino_filcol, dtype=np.int64)
    if fc.size == 0:
        return False
    m = np.asarray(mascara, dtype=bool)
    nf, nc = m.shape
    for f, c in fc:
        for df in range(-margen, margen + 1):
            for dc in range(-margen, margen + 1):
                a, b = f + df, c + dc
                if a < 0 or b < 0 or a >= nf or b >= nc or not m[a, b]:
                    return True
    return False


def sinuosidad(largo, extremos_xy) -> float:
    """Largo recorrido entre distancia en linea recta de extremo a extremo.

    Es 1 para una recta y crece con el rodeo. Sirve para leer una diferencia
    de longitud entre el trazado observado y el modelado: si el observado
    tiene sinuosidad 2.5 y el modelado 1.3, el camino real da una vuelta que
    el modelo no reproduce, y eso es una afirmacion sobre el trazado, no un
    error de medida.
    """
    import numpy as np

    a, b = np.asarray(extremos_xy, dtype=np.float64)
    recta = float(np.hypot(*(b - a)))
    if recta <= 0:
        return float("inf")
    return float(largo) / recta


def autoproximidad(xy, separacion_minima: float = 1000.0) -> float:
    """Distancia minima entre dos puntos de la MISMA linea que esten lejos
    ENTRE SI a lo largo de ella.

    Distingue dos cosas que dan la misma sinuosidad y significan lo
    contrario:

      - un camino que RODEA algo (un cerro, una quebrada) es un arco suave:
        se aleja de si mismo, y su autoproximidad es del orden del diametro
        del rodeo, cientos o miles de metros.

      - una pieza que `linemerge` COSIO de dos ramas distintas con un
        vertice comun vuelve sobre si misma: su autoproximidad baja a
        decenas de metros, porque la linea pasa dos veces casi por el mismo
        sitio.

    Lo segundo no es un camino y no se puede ajustar un modelo de costo
    contra el: los extremos de la "unidad" serian los dos cabos de una Y.
    """
    import numpy as np

    xy = np.asarray(xy, dtype=np.float64)
    if len(xy) < 3:
        return float("inf")

    paso = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
    lejos = np.abs(paso[:, None] - paso[None, :]) >= separacion_minima
    if not lejos.any():
        return float("inf")

    d = np.hypot(xy[:, 0, None] - xy[None, :, 0],
                 xy[:, 1, None] - xy[None, :, 1])
    return float(d[lejos].min())


def giro_maximo(xy) -> float:
    """Angulo de giro maximo entre segmentos consecutivos, en grados.

    Se mide sobre los vertices ORIGINALES, no sobre un remuestreo: un
    remuestreo suaviza justo lo que se busca. Un vertice donde la linea se
    invierte casi 180 grados no es una curva de camino -- ni una herradura
    lo hace-- es donde se unieron dos cosas distintas.
    """
    import numpy as np

    xy = np.asarray(xy, dtype=np.float64)
    if len(xy) < 3:
        return 0.0

    v = np.diff(xy, axis=0)
    n = np.hypot(*v.T)
    bueno = n > 0
    v, n = v[bueno], n[bueno]
    if len(v) < 2:
        return 0.0

    cos = ((v[:-1] * v[1:]).sum(axis=1) / (n[:-1] * n[1:])).clip(-1.0, 1.0)
    return float(np.degrees(np.arccos(cos)).max())
