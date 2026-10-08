"""Equifinalidad: el conjunto de pesos casi-optimos, no el optimo puntual.

Esta es la respuesta a la pregunta del proyecto. El optimo de un sector es
un punto en el simplex y, con datos reales, ese punto es ruido: muchos
vectores de pesos distintos producen caminos practicamente iguales. Lo que
se puede sostener es el CONJUNTO de pesos que explican el camino observado
casi igual de bien, y si ese conjunto cambia de un sector a otro.

    S_s(tau) = { w en Lambda : D_s(w) <= (1 + tau) D*_s }
    J_st(tau) = |S_s ∩ S_t| / |S_s ∪ S_t|

Dos sectores cuyos conjuntos se separan (J baja y se queda baja al crecer
tau) estan gobernados por variables distintas. Dos cuyos conjuntos se
solapan incluso con tau pequeno no se distinguen con estos datos -- y eso
tambien es un resultado, no un fracaso.
"""

from __future__ import annotations

import itertools

import numpy as np


def conjunto_casi_optimo(D, tau: float) -> np.ndarray:
    """Mascara booleana de los puntos de la red dentro del margen `tau`.

    `tau` es relativo: 0.10 significa "hasta 10% peor que el optimo".
    """
    D = np.asarray(D, dtype=np.float64)
    fin = np.isfinite(D)
    if not fin.any():
        return np.zeros(D.shape, dtype=bool)
    optimo = float(np.min(D[fin]))
    return fin & (D <= (1.0 + tau) * optimo)


def jaccard(a, b) -> float:
    """Indice de Jaccard entre dos mascaras sobre la misma red."""
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    union = int((a | b).sum())
    if union == 0:
        return float("nan")
    return float((a & b).sum() / union)


def perfil_jaccard(D_por_sector: dict[str, np.ndarray], taus=None):
    """Perfil J_st(tau) para cada par de sectores.

    Devuelve (taus, {(s, t): array}). Graficar esto contra tau es el
    resultado principal: no el mapa de un camino, sino como se separan los
    conjuntos de pesos entre sectores.
    """
    if taus is None:
        taus = np.linspace(0.0, 0.5, 26)
    taus = np.asarray(taus, dtype=np.float64)

    nombres = list(D_por_sector)
    perfiles: dict[tuple[str, str], np.ndarray] = {}
    for s, t in itertools.combinations(nombres, 2):
        vals = [jaccard(conjunto_casi_optimo(D_por_sector[s], tau),
                        conjunto_casi_optimo(D_por_sector[t], tau))
                for tau in taus]
        perfiles[(s, t)] = np.array(vals, dtype=np.float64)
    return taus, perfiles


def centroide(red, mascara) -> np.ndarray:
    """Centro de masa del conjunto casi-optimo en el simplex.

    Reportar esto junto con el optimo puntual: si el centroide y el optimo
    estan lejos, el optimo no es representativo del conjunto.
    """
    red = np.asarray(red, dtype=np.float64)
    mascara = np.asarray(mascara, dtype=bool)
    if not mascara.any():
        return np.full(red.shape[1], np.nan)
    return red[mascara].mean(axis=0)


def extension(red, mascara) -> np.ndarray:
    """Rango [min, max] de cada peso dentro del conjunto casi-optimo.

    Es lo que se reporta en el texto: no "w_pendiente = 0.60" sino
    "w_pendiente entre 0.45 y 0.70 con tau = 0.10".
    """
    red = np.asarray(red, dtype=np.float64)
    mascara = np.asarray(mascara, dtype=bool)
    if not mascara.any():
        return np.full((red.shape[1], 2), np.nan)
    sub = red[mascara]
    return np.column_stack([sub.min(axis=0), sub.max(axis=0)])
