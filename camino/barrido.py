"""Barrido exhaustivo de los pesos sobre el simplex.

Se barre en vez de optimizar por tres razones: con K <= 4 sale gratis, no
hay minimos locales de los que preocuparse, y -sobre todo- lo que el
proyecto necesita es EL PAISAJE COMPLETO y no el optimo, porque el resultado
es el conjunto de pesos casi-optimos (ver `equifinalidad.py`).
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np
import scipy.sparse as sp
from joblib import Parallel, delayed
from scipy.sparse.csgraph import dijkstra

from . import grafo as _grafo
from . import metricas


def cuenta_red(k: int, n: int) -> int:
    """Numero de puntos de la red del simplex: C(n + k - 1, k - 1)."""
    return math.comb(n + k - 1, k - 1)


def red_simplex(k: int, n: int) -> np.ndarray:
    """Red regular sobre el simplex con paso h = 1/n.

        Lambda = { w : w_k = m_k / n,  m_k entero >= 0,  sum m_k = n }

    Con n = 20 (h = 0.05): K = 3 da 231 vectores, K = 4 da 1771.
    """
    if k < 1 or n < 1:
        raise ValueError("k y n deben ser >= 1")
    pts = []
    for cortes in combinations(range(n + k - 1), k - 1):
        previo, m = -1, []
        for c in cortes + (n + k - 1,):
            m.append(c - previo - 1)
            previo = c
        pts.append(m)
    red = np.array(pts, dtype=np.float64) / n
    assert red.shape == (cuenta_red(k, n), k)
    return red


def _lote(indices, indptr, L, Phi, n, pesos, origen, destino,
          filcol, transform6, observado):
    """Un bloque de vectores de peso en un proceso.

    Cada proceso arma su propia CSR una vez (sobre arrays que joblib pasa
    como memmap) y despues solo reescribe `data`. Nunca se reconstruye la
    matriz dentro del bucle.
    """
    csr = sp.csr_matrix((np.ones(L.size, dtype=np.float64), indices, indptr),
                        shape=(n, n))
    salida = []
    for w in pesos:
        csr.data[:] = L * (Phi @ w)
        _, pred = dijkstra(csr, directed=True, indices=origen,
                           return_predecessors=True)
        cam = _grafo.recorre(pred, origen, destino)
        if cam.size == 0:
            salida.append((np.inf, np.inf, 0.0, cam))
            continue
        xy = _grafo.xy(filcol[cam], transform6)
        dh = metricas.distancia_media_simetrica(xy, observado)
        salida.append((dh, np.nan, metricas.longitud(xy), cam))
    return salida


def barre(g: _grafo.Grafo, red: np.ndarray, origen: int, destino: int,
          observado, transform6, n_trabajos: int = -1, lote: int = 16):
    """Corre un Dijkstra por cada vector de pesos de `red`.

    Devuelve (D, largos, caminos):
      D        (M,)  distancia media simetrica al camino observado, en metros
      largos   (M,)  longitud de cada camino modelado, en metros
      caminos  lista de arrays de indices de nodo
    """
    red = np.asarray(red, dtype=np.float64)
    if red.shape[1] != len(g.nombres):
        raise ValueError(
            f"la red tiene {red.shape[1]} componentes y el grafo {len(g.nombres)}")
    observado = np.asarray(observado, dtype=np.float64)

    bloques = [red[i:i + lote] for i in range(0, len(red), lote)]
    resultados = Parallel(n_jobs=n_trabajos, prefer="processes")(
        delayed(_lote)(g._csr.indices, g._csr.indptr, g.L, g.Phi, g.n,
                       b, origen, destino, g.filcol, transform6, observado)
        for b in bloques)

    plano = [r for bloque in resultados for r in bloque]
    D = np.array([r[0] for r in plano])
    largos = np.array([r[2] for r in plano])
    caminos = [r[3] for r in plano]
    return D, largos, caminos


def optimo(D: np.ndarray, red: np.ndarray):
    """Indice y vector de pesos que minimizan D.

        w* = argmin_{w in Lambda} D(w)
    """
    D = np.asarray(D, dtype=np.float64)
    if not np.isfinite(D).any():
        raise ValueError("ningun vector de pesos produjo un camino")
    i = int(np.nanargmin(np.where(np.isfinite(D), D, np.nan)))
    return i, red[i]


def tabla_optimo(D, largos, red, nombres, observado_largo=None):
    """Resumen legible del optimo de un sector."""
    i, w = optimo(D, red)
    fila = {n: round(float(v), 3) for n, v in zip(nombres, w)}
    fila["D_media_m"] = round(float(D[i]), 1)
    fila["largo_modelado_km"] = round(float(largos[i]) / 1000, 2)
    if observado_largo is not None:
        fila["largo_observado_km"] = round(float(observado_largo) / 1000, 2)
    return fila
