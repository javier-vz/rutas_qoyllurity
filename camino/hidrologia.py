"""Hidrologia derivada del DEM: relleno de depresiones, D8 y acumulacion.

Todo en numpy y heapq. No hace falta WhiteboxTools, GRASS ni GDAL.

IMPORTANTE: el DEM rellenado se usa SOLO aqui. La pendiente y la rugosidad
se calculan sobre el DEM crudo. Rellenar depresiones borra concavidades
reales del terreno y, si se usa para la pendiente, inventa planicies.
"""

from __future__ import annotations

import heapq

import numpy as np
from scipy import ndimage

# Vecindad 8, en (fila, columna). Fila 0 al norte.
_D8 = ((-1, -1), (-1, 0), (-1, 1),
       (0, -1), (0, 1),
       (1, -1), (1, 0), (1, 1))


def rellenar(z, valido=None, incremento: float = 1e-4):
    """Relleno de depresiones por Priority-Flood (Barnes, Lehman & Mulla 2014).

    Devuelve una superficie sin sumideros y estrictamente descendente hacia
    la salida: el `incremento` impone un gradiente minimo dentro de cada
    depresion rellenada, lo que elimina las planicies. Sin eso, el D8 no
    sabe hacia donde drenar en el fondo de un lago rellenado.

    Complejidad O(n log n). Para 350 000 celdas corre en segundos.
    """
    z = np.asarray(z, dtype=np.float64)
    if valido is None:
        valido = np.isfinite(z)
    valido = np.asarray(valido, dtype=bool) & np.isfinite(z)

    nf, nc = z.shape
    salida = np.full(z.shape, np.inf)
    cerrado = ~valido

    # Semillas: toda celda valida que toque el borde del raster o una celda
    # invalida. Son las salidas posibles del sistema.
    marco = np.zeros(z.shape, dtype=bool)
    marco[0, :] = marco[-1, :] = True
    marco[:, 0] = marco[:, -1] = True
    vecino_invalido = ndimage.binary_dilation(
        ~valido, structure=np.ones((3, 3), dtype=bool))
    semillas = valido & (marco | vecino_invalido)

    fs, cs = np.nonzero(semillas)
    salida[semillas] = z[semillas]
    cerrado |= semillas
    monton: list[tuple[float, int, int]] = [
        (float(z[i, j]), int(i), int(j)) for i, j in zip(fs, cs)]
    heapq.heapify(monton)

    if not monton:
        raise ValueError("no hay ninguna celda de salida: revisa la mascara")

    while monton:
        zc, i, j = heapq.heappop(monton)
        for di, dj in _D8:
            a, b = i + di, j + dj
            if a < 0 or b < 0 or a >= nf or b >= nc or cerrado[a, b]:
                continue
            salida[a, b] = max(z[a, b], zc + incremento)
            cerrado[a, b] = True
            heapq.heappush(monton, (float(salida[a, b]), a, b))

    salida[~valido] = np.nan
    return salida


def d8(z_relleno, dx: float, dy: float | None = None, valido=None):
    """Direcciones de flujo D8: para cada celda, el vecino de maxima bajada.

    Devuelve `destino`, un entero por celda con el indice plano del vecino
    al que drena, o -1 si la celda es una salida (no drena a ninguna celda
    valida). Sobre una superficie ya rellenada con gradiente minimo, cada
    celda interior tiene un destino estricto.
    """
    z = np.asarray(z_relleno, dtype=np.float64)
    dy = dx if dy is None else dy
    if valido is None:
        valido = np.isfinite(z)
    valido = np.asarray(valido, dtype=bool) & np.isfinite(z)

    nf, nc = z.shape
    mejor = np.full(z.shape, -np.inf)
    destino = np.full(z.shape, -1, dtype=np.int64)

    for di, dj in _D8:
        dist = np.hypot(di * dy, dj * dx)
        zv = np.roll(np.roll(z, -di, axis=0), -dj, axis=1)
        vv = np.roll(np.roll(valido, -di, axis=0), -dj, axis=1)

        # las celdas que al desplazarse salen del raster no son vecinas
        dentro = np.ones(z.shape, dtype=bool)
        if di > 0:
            dentro[-di:, :] = False
        elif di < 0:
            dentro[:-di, :] = False
        if dj > 0:
            dentro[:, -dj:] = False
        elif dj < 0:
            dentro[:, :-dj] = False

        with np.errstate(invalid="ignore"):
            caida = (z - zv) / dist
        usable = dentro & vv & valido & np.isfinite(caida) & (caida > 0)
        gana = usable & (caida > mejor)

        mejor = np.where(gana, caida, mejor)
        idx_v = (np.arange(nf)[:, None] + di) * nc + (np.arange(nc)[None, :] + dj)
        destino = np.where(gana, idx_v, destino)

    destino[~valido] = -1
    return destino


def acumulacion(destino, valido=None, z_relleno=None):
    """Area acumulada D8, en numero de celdas (cada celda se cuenta a si misma).

    Se acumula recorriendo las celdas en orden decreciente de elevacion, que
    es un orden topologico valido sobre una superficie estrictamente
    descendente. Exacto, sin iteracion.
    """
    destino = np.asarray(destino, dtype=np.int64)
    forma = destino.shape
    if valido is None:
        valido = destino >= -1
    valido = np.asarray(valido, dtype=bool)

    acc = np.where(valido, 1.0, np.nan).ravel()
    dst = destino.ravel()
    val = valido.ravel()

    if z_relleno is None:
        raise ValueError("hace falta el DEM rellenado para ordenar topologicamente")
    zz = np.asarray(z_relleno, dtype=np.float64).ravel()

    idx = np.flatnonzero(val)
    idx = idx[np.argsort(-zz[idx], kind="stable")]

    for c in idx:
        d = dst[c]
        if d >= 0 and val[d]:
            acc[d] += acc[c]

    return acc.reshape(forma)


def area_especifica(acumulacion_celdas, dx: float, dy: float | None = None):
    """Area de contribucion especifica: area acumulada por unidad de contorno.

        a = A_celdas * dx * dy / dx     (m)

    Es lo que pide el TWI. Con celdas cuadradas se reduce a A_celdas * dx.
    """
    dy = dx if dy is None else dy
    a = np.asarray(acumulacion_celdas, dtype=np.float64)
    return a * (dx * dy) / dx


def cauces(acumulacion_celdas, umbral: float = 500.0):
    """Mascara de quebradas: celdas con area acumulada por encima del umbral.

    El umbral por defecto (500 celdas = 0.45 km2 a 30 m) es lo UNICO de todo
    el modelo que el trabajo de campo fija directamente: se calibra contra
    las quebradas que realmente haya que cruzar en el tramo.
    """
    a = np.asarray(acumulacion_celdas, dtype=np.float64)
    return np.isfinite(a) & (a >= umbral)
