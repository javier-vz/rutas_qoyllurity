"""Costo de locomocion en funcion de la pendiente dirigida.

La unica ecuacion del modelo es el costo de cruzar de una celda a su vecina:

    c_ij(w) = L_ij * sum_k w_k * phi_k(i, j)

Este modulo cubre la componente de pendiente, que es la unica anisotropica
(g_ij = -g_ji). Las demas componentes son propiedades de la celda y se
promedian entre los dos extremos de la arista; eso lo hace `grafo.py`.
"""

from __future__ import annotations

import numpy as np

# Minetti, Moia, Roi, Susta & Ferretti (2002), J Appl Physiol 93:1039-1046.
# Costo metabolico de caminar, en J kg^-1 m^-1, ajustado con R^2 = 0.999
# sobre gradientes de -0.45 a +0.45. Orden: g^5, g^4, g^3, g^2, g^1, g^0.
COEF_MINETTI = (280.5, -58.7, -76.8, 51.9, 19.6, 2.5)

# Borde de validez del ajuste de Minetti. NO es un umbral estetico: fuera de
# este rango la polinomial se dispara y deja de significar nada, asi que las
# aristas con |g| > G_MAX se eliminan del grafo en vez de recortarse.
G_MAX = 0.45

# Costo en terreno plano, usado para normalizar la componente a 1.
C_PLANO = COEF_MINETTI[-1]  # = 2.5 J kg^-1 m^-1


def minetti(g):
    """Costo metabolico de caminar, J kg^-1 m^-1, para gradiente `g`.

    `g` es adimensional (desnivel / distancia recorrida), positivo subiendo.
    No se recorta nada: la validez la impone `valido()`.
    """
    g = np.asarray(g, dtype=np.float64)
    return np.polyval(COEF_MINETTI, g)


def valido(g, g_max: float = G_MAX):
    """Mascara de gradientes dentro del rango ajustado por Minetti."""
    return np.abs(np.asarray(g, dtype=np.float64)) <= g_max


def phi_pendiente(g, g_max: float = G_MAX):
    """Componente de pendiente, normalizada a 1 en terreno plano.

        phi_pend(i,j) = C_w(g_ij) / C_w(0)

    Devuelve `nan` fuera del rango de validez, para que quien construya el
    grafo tenga que decidir explicitamente que hacer con esas aristas.
    """
    g = np.asarray(g, dtype=np.float64)
    out = np.full(g.shape, np.nan)
    ok = valido(g, g_max)
    out[ok] = minetti(g[ok]) / C_PLANO
    return out


def tobler(g):
    """Funcion de marcha de Tobler (1993), en m/s.

        v(g) = 1.662 * exp(-3.5 * |g + 0.05|)

    Se incluye solo como MODELO ALTERNO para contrastar, nunca como una
    componente adicional de la suma: Tobler es velocidad y Minetti es
    energia, y sumarlos deja un numero sin unidades que no se interpreta.
    """
    g = np.asarray(g, dtype=np.float64)
    return 1.662 * np.exp(-3.5 * np.abs(g + 0.05))


def phi_tobler(g):
    """Costo por metro segun Tobler, normalizado a 1 en terreno plano."""
    g = np.asarray(g, dtype=np.float64)
    return tobler(0.0) / tobler(g)


def normaliza(x, mascara=None, percentiles=(5.0, 95.0), epsilon: float = 0.01):
    """Escala un raster a [epsilon, 1 + epsilon] por percentiles.

    Percentiles y no minimo-maximo: un solo pixel de ruido en el DEM no debe
    fijar la escala de toda la superficie.

    El `epsilon` no es cosmetico. Con aristas de costo cero, Dijkstra
    devuelve caminos degenerados que recorren kilometros gratis.
    """
    x = np.asarray(x, dtype=np.float64)
    if mascara is None:
        mascara = np.isfinite(x)
    else:
        mascara = np.asarray(mascara, dtype=bool) & np.isfinite(x)
    if not mascara.any():
        raise ValueError("la mascara no deja ningun pixel valido")

    lo, hi = np.percentile(x[mascara], percentiles)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        # superficie constante (o casi): la componente no aporta informacion
        out = np.full(x.shape, epsilon)
        out[~mascara] = np.nan
        return out

    out = np.clip((x - lo) / (hi - lo), 0.0, 1.0) + epsilon
    out[~mascara] = np.nan
    return out
