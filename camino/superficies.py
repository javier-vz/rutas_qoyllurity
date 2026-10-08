"""Superficies derivadas del DEM: pendiente, aspecto y rugosidad.

Convencion de ejes en todo el modulo: el raster tiene la fila 0 al NORTE
(orientacion habitual de un GeoTIFF), `dx` crece hacia el ESTE y `dy` hacia
el SUR. Los gradientes que devolvemos estan en el marco (Este, Norte).

La pendiente del raster NO entra en el costo. Entra el gradiente dirigido de
cada arista, que calcula `grafo.py`: un raster de pendiente no sabe en que
direccion vas, y subir no cuesta lo mismo que bajar. La pendiente de aqui
sirve para el VRM y para el TWI.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

# Nucleos de Horn (1981), la ventana 3x3 que usa gdaldem.
#   z1 z2 z3      fila norte
#   z4 z5 z6
#   z7 z8 z9      fila sur
_HORN_E = np.array([[-1.0, 0.0, 1.0],
                    [-2.0, 0.0, 2.0],
                    [-1.0, 0.0, 1.0]]) / 8.0
_HORN_N = np.array([[1.0, 2.0, 1.0],
                    [0.0, 0.0, 0.0],
                    [-1.0, -2.0, -1.0]]) / 8.0


def _correlaciona(z, nucleo, valido):
    """Correlacion 3x3 que ignora las celdas invalidas y renormaliza.

    Sin esto, un nodata al borde del corredor contamina una franja de tres
    celdas hacia adentro.
    """
    zz = np.where(valido, z, 0.0)
    num = ndimage.correlate(zz, nucleo, mode="nearest")
    # peso efectivo recuperado: cuanto del nucleo cayo sobre celdas validas
    peso = ndimage.correlate(valido.astype(np.float64),
                             np.abs(nucleo), mode="nearest")
    peso_total = np.abs(nucleo).sum()
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(peso > 0, num * (peso_total / np.maximum(peso, 1e-12)), np.nan)
    return out


def gradientes(z, dx: float, dy: float | None = None, valido=None):
    """Gradientes de Horn en el marco (Este, Norte), adimensionales.

        dz/dE = ((z3 + 2 z6 + z9) - (z1 + 2 z4 + z7)) / (8 dx)
        dz/dN = ((z1 + 2 z2 + z3) - (z7 + 2 z8 + z9)) / (8 dy)
    """
    z = np.asarray(z, dtype=np.float64)
    dy = dx if dy is None else dy
    if valido is None:
        valido = np.isfinite(z)
    valido = np.asarray(valido, dtype=bool) & np.isfinite(z)

    dz_dE = _correlaciona(z, _HORN_E, valido) / dx
    dz_dN = _correlaciona(z, _HORN_N, valido) / dy
    dz_dE[~valido] = np.nan
    dz_dN[~valido] = np.nan
    return dz_dE, dz_dN


def pendiente_aspecto(z, dx: float, dy: float | None = None, valido=None):
    """Pendiente en radianes y aspecto en radianes (azimut desde el norte).

        S = arctan( sqrt( (dz/dE)^2 + (dz/dN)^2 ) )
        A = atan2( -dz/dE , -dz/dN )      (direccion de maxima bajada)

    El aspecto queda en [0, 2pi), medido en sentido horario desde el norte.
    """
    dz_dE, dz_dN = gradientes(z, dx, dy, valido)
    S = np.arctan(np.hypot(dz_dE, dz_dN))
    A = np.mod(np.arctan2(-dz_dE, -dz_dN), 2.0 * np.pi)
    return S, A


def vrm(S, A, ventana: int = 3):
    """Vector Ruggedness Measure (Sappington, Longshore & Thompson 2007).

        n   = ( sin S sin A ,  sin S cos A ,  cos S )
        VRM = 1 - || sum_{c in W} n_c || / |W|

    VRM en [0, 1]: 0 es plano *o* inclinado pero uniforme; cerca de 1,
    terreno quebrado.

    Se usa esto y no el TRI a proposito. El TRI es casi una funcion de la
    pendiente, asi que como componente aparte haria que dos de los pesos
    midieran lo mismo y el optimo dejaria de ser unico.
    """
    S = np.asarray(S, dtype=np.float64)
    A = np.asarray(A, dtype=np.float64)
    ok = np.isfinite(S) & np.isfinite(A)

    sinS = np.sin(S)
    comp = (sinS * np.sin(A), sinS * np.cos(A), np.cos(S))

    k = np.ones((ventana, ventana))
    cuenta = ndimage.correlate(ok.astype(np.float64), k, mode="nearest")
    sumas = [ndimage.correlate(np.where(ok, c, 0.0), k, mode="nearest")
             for c in comp]

    r = np.sqrt(sumas[0] ** 2 + sumas[1] ** 2 + sumas[2] ** 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = 1.0 - r / np.maximum(cuenta, 1e-12)
    out = np.clip(out, 0.0, 1.0)
    out[~ok] = np.nan
    return out


def twi(sca, S, minimo_tan: float = 1e-3):
    """Indice topografico de humedad.

        TWI = ln( a / (tan S + eps) )

    `sca` es el area de contribucion especifica (area por unidad de
    contorno, m), `S` la pendiente en radianes. El `eps` evita dividir por
    cero en lo plano.

    En bosque de neblina esta es la variable que la pendiente no ve: donde se
    acumula agua y el suelo se anega, el camino no pasa aunque sea llano.
    """
    sca = np.asarray(sca, dtype=np.float64)
    S = np.asarray(S, dtype=np.float64)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.log(np.maximum(sca, 1e-6) / (np.tan(S) + minimo_tan))
    out[~np.isfinite(sca) | ~np.isfinite(S)] = np.nan
    return out


def phi_drenaje(acumulacion_celdas):
    """Componente de costo por cruzar un drenaje.

        phi_dren = log10( 1 + A_celdas )

    Crece con el area que drena por la celda: cruzar una quebrada grande
    cuesta mas que cruzar un surco.
    """
    a = np.asarray(acumulacion_celdas, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        out = np.log10(1.0 + np.maximum(a, 0.0))
    out[~np.isfinite(a)] = np.nan
    return out


def proximidad(puntos_xy, filcol_xy, forma, saturacion: float = 5000.0):
    """Distancia euclidiana al sitio mas cercano, normalizada a [0,1].

    `puntos_xy`  (m, 2) coordenadas de los sitios, en el CRS de trabajo.
    `filcol_xy`  (n, 2) coordenadas del centro de cada celda transitable.
    `forma`      forma del raster de salida.

    Se usa un arbol de vecinos y no una transformada de distancia porque
    los sitios pueden caer FUERA de la caja: un santuario a 2 km del borde
    sigue condicionando las celdas de dentro, y la transformada solo
    propaga desde semillas que esten en la rejilla.

    Satura a `saturacion` metros: mas alla da igual estar mas lejos, y sin
    saturar un sitio aislado domina la superficie de medio corredor.

    Valores MAYORES = mas separacion = mas penalizacion, que es el sentido
    que le da el proyecto.
    """
    from scipy.spatial import cKDTree

    puntos_xy = np.asarray(puntos_xy, dtype=np.float64)
    if puntos_xy.size == 0:
        raise ValueError("no hay ningun sitio ceremonial que usar")

    d, _ = cKDTree(puntos_xy).query(np.asarray(filcol_xy, dtype=np.float64))
    return np.clip(d / float(saturacion), 0.0, 1.0)
