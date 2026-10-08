"""El nulo: campos gaussianos con el mismo espectro que el terreno real.

Esto va ANTES de comparar pesos entre sectores. Un sector cuyo mejor camino
no le gana a terreno aleatorio no tiene pesos que reportar, y decir "aqui
manda la rugosidad" sobre un sector asi es decir nada.

El nulo no es ruido blanco. Un camino de minimo costo sobre ruido blanco es
facil de ganar y el test saldria significativo siempre. El nulo correcto
conserva la autocorrelacion espacial de la superficie real y solo destruye
su relacion con el terreno: campos gaussianos con el mismo exponente
espectral.
"""

from __future__ import annotations

import numpy as np


def beta_espectral(x, mascara=None, k_min: float = 0.02, k_max: float = 0.4) -> float:
    """Exponente del espectro de potencias radial: P(k) ~ k^(-beta).

    Se ajusta por minimos cuadrados en log-log sobre la banda intermedia de
    frecuencias, dejando fuera las muy bajas (dominadas por la tendencia
    regional) y las muy altas (dominadas por el ruido del DEM).
    """
    x = np.asarray(x, dtype=np.float64)
    if mascara is None:
        mascara = np.isfinite(x)
    mascara = np.asarray(mascara, dtype=bool) & np.isfinite(x)
    z = np.where(mascara, x, np.nan)
    z = np.nan_to_num(z - np.nanmean(z), nan=0.0)

    # ventana de Hann separable, para que el borde no meta potencia falsa
    nf, nc = z.shape
    z = z * np.hanning(nf)[:, None] * np.hanning(nc)[None, :]

    P = np.abs(np.fft.fft2(z)) ** 2
    ky = np.fft.fftfreq(nf)[:, None]
    kx = np.fft.fftfreq(nc)[None, :]
    k = np.hypot(ky, kx)

    sel = (k >= k_min) & (k <= k_max) & (P > 0)
    if sel.sum() < 32:
        return 2.0
    pend = np.polyfit(np.log(k[sel]), np.log(P[sel]), 1)[0]
    return float(-pend)


def campo_gaussiano(forma, beta: float, rng) -> np.ndarray:
    """Campo aleatorio gaussiano con espectro P(k) ~ k^(-beta).

        g^(k) = N(0,1) * ||k||^(-beta/2)

    Sintesis espectral: se filtra ruido blanco en el dominio de Fourier.
    Sale normalizado a media 0 y desviacion 1.
    """
    nf, nc = forma
    ky = np.fft.fftfreq(nf)[:, None]
    kx = np.fft.fftfreq(nc)[None, :]
    k = np.hypot(ky, kx)
    k[0, 0] = 1.0

    amp = k ** (-beta / 2.0)
    amp[0, 0] = 0.0                       # sin componente continua

    campo = np.fft.ifft2(np.fft.fft2(rng.standard_normal(forma)) * amp).real
    s = campo.std()
    return campo / s if s > 0 else campo


def superficie_nula(forma, beta: float, rng, epsilon: float = 0.01,
                    percentiles=(5.0, 95.0)) -> np.ndarray:
    """Un campo nulo escalado al mismo rango que una componente de costo."""
    g = campo_gaussiano(forma, beta, rng)
    lo, hi = np.percentile(g, percentiles)
    if hi <= lo:
        return np.full(forma, epsilon)
    return np.clip((g - lo) / (hi - lo), 0.0, 1.0) + epsilon


def p_empirico(d_observado: float, d_nulos) -> float:
    """Valor p de una sola cola, con el nulo de Monte Carlo.

        p = ( 1 + #{ m : D_m <= D* } ) / ( M + 1 )

    El piso es 1/(M+1): con M = 500 no se puede reportar "p < 0.002", se
    reporta "p = 0.002 con M = 500".
    """
    d = np.asarray(d_nulos, dtype=np.float64)
    d = d[np.isfinite(d)]
    m = d.size
    if m == 0:
        return float("nan")
    return float((1 + int((d <= d_observado).sum())) / (m + 1))


def piso_p(m: int) -> float:
    """El menor valor p alcanzable con M nulos."""
    return 1.0 / (m + 1)
