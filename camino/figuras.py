"""Las figuras del estudio.

Dos reglas que se siguen aqui y conviene no perder:

- El color codifica IDENTIDAD (que componente), nunca magnitud ni orden. Las
  tres componentes llevan siempre el mismo color en todas las figuras.
- El texto va en tinta, nunca del color de la serie. El color lo lleva la
  marca; la etiqueta lo acompana.

La paleta esta validada para daltonismo en las tres primeras ranuras, que es
justo lo que hace falta: pendiente, rugosidad y drenaje.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

# Paleta categorica, ranuras 1-3 (validadas para todos los pares).
COLOR = {
    "pendiente": "#2a78d6",
    "rugosidad": "#eb6834",
    "drenaje": "#1baf7a",
    "humedad": "#eda100",
}
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300")

SUPERFICIE = "#fcfcfb"
TINTA = "#0b0b0b"
TINTA2 = "#52514e"
MUDO = "#898781"
REJILLA = "#e1e0d9"
EJE = "#c3c2b7"

plt.rcParams.update({
    "font.family": ["DejaVu Sans"],
    "figure.facecolor": SUPERFICIE,
    "axes.facecolor": SUPERFICIE,
    "axes.edgecolor": EJE,
    "axes.labelcolor": TINTA2,
    "text.color": TINTA,
    "xtick.color": MUDO,
    "ytick.color": MUDO,
    "axes.titlesize": 11,
    "axes.labelsize": 9,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "legend.fontsize": 8.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
})


def _limpia(eje, rejilla="y"):
    eje.grid(axis=rejilla, color=REJILLA, lw=0.6, zorder=0)
    eje.set_axisbelow(True)
    for lado in ("left", "bottom"):
        eje.spines[lado].set_linewidth(0.8)


# ---------------------------------------------------------- equifinalidad

def perfil_jaccard(ruta, taus, perfiles, titulo=None):
    """Como se separan los conjuntos de pesos entre unidades, segun tau.

    Seis pares de lineas. La leyenda va ordenada por el valor final, asi que
    su orden vertical coincide con el de las lineas en el borde derecho: es
    etiquetado directo sin colisiones.
    """
    taus = np.asarray(taus, dtype=float)
    orden = sorted(perfiles.items(), key=lambda kv: -np.nanmax(kv[1][-3:]))

    fig, eje = plt.subplots(figsize=(7.6, 4.3), dpi=200)
    _limpia(eje)

    eje.axhline(0.5, color=EJE, lw=0.9, ls=(0, (4, 3)), zorder=1)
    eje.text(taus[-1], 0.515, "mitad del conjunto compartida", ha="right",
             va="bottom", fontsize=7.5, color=MUDO)

    for i, ((a, b), j) in enumerate(orden):
        eje.plot(taus, np.asarray(j, dtype=float), lw=2.0,
                 color=SERIES[i % len(SERIES)], solid_capstyle="round",
                 label=f"{a} vs {b}", zorder=3)

    eje.set_xlim(taus.min(), taus.max())
    eje.set_ylim(-0.02, 1.02)
    eje.set_xlabel("margen sobre el optimo  (tau)")
    eje.set_ylabel("conjuntos de pesos compartidos  (Jaccard)")
    if titulo:
        eje.set_title(titulo, loc="left", color=TINTA, pad=10)
    eje.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False,
               handlelength=1.6, labelcolor=TINTA2)

    fig.tight_layout()
    fig.savefig(ruta, bbox_inches="tight")
    plt.close(fig)
    return ruta


# ------------------------------------------------------- sensibilidad

def sensibilidad(ruta, filas, nombres, titulo=None):
    """Componente dominante en cada posicion del camino, por particion.

    La pregunta es si la estructura sobrevive a recortar el camino de otra
    manera, y eso es una comparacion de IDENTIDAD entre filas: una banda por
    particion, el color dice que componente manda. Si las bandas no se
    alinean en vertical, la estructura era del corte.

    Debajo, cuantas particiones coinciden en cada posicion. Va en gris a
    proposito: no es otra categoria, es una medida de acuerdo.
    """
    ns = sorted({f["n_sectores"] for f in filas})
    if not ns:
        raise ValueError("no hay nada que dibujar")

    fig, (arriba, abajo) = plt.subplots(
        2, 1, figsize=(7.8, 1.05 * len(ns) + 2.4), dpi=200,
        gridspec_kw={"height_ratios": [len(ns), 1.5], "hspace": 0.28},
        sharex=True)

    alto = 0.74
    for y, n in enumerate(ns):
        sub = sorted((f for f in filas if f["n_sectores"] == n),
                     key=lambda f: f["desde"])
        for f in sub:
            dom = f["dominante"]
            x0, x1 = f["desde"], f["hasta"]
            # 2px de hueco entre bloques: separa sin inventar un borde
            arriba.add_patch(Rectangle(
                (x0 + 0.002, y - alto / 2), (x1 - x0) - 0.004, alto,
                facecolor=COLOR.get(dom, MUDO), edgecolor="none", zorder=2))
            arriba.text((x0 + x1) / 2, y, f"{f[dom]:.2f}", ha="center",
                        va="center", fontsize=8.5, color="white",
                        fontweight="bold", zorder=3)

    arriba.set_ylim(len(ns) - 0.5, -0.5)
    arriba.set_yticks(range(len(ns)))
    arriba.set_yticklabels([f"{n} sectores" for n in ns], color=TINTA2)
    arriba.set_xlim(0, 1)
    arriba.grid(False)
    for lado in ("left", "bottom"):
        arriba.spines[lado].set_visible(False)
    arriba.tick_params(length=0)
    if titulo:
        arriba.set_title(titulo, loc="left", color=TINTA, pad=30,
                         fontsize=11.5)

    manijas = [Rectangle((0, 0), 1, 1, facecolor=COLOR[c]) for c in nombres
               if c in COLOR]
    arriba.legend(manijas, [c for c in nombres if c in COLOR],
                  loc="lower left", bbox_to_anchor=(0, 1.02), ncol=len(nombres),
                  frameon=False, handlelength=1.1, handleheight=1.1,
                  labelcolor=TINTA2, columnspacing=1.4)

    # --- acuerdo entre particiones
    x = np.linspace(0.0005, 0.9995, 400)
    acuerdo = np.zeros_like(x)
    for k, pos in enumerate(x):
        votos = []
        for n in ns:
            for f in filas:
                if f["n_sectores"] == n and f["desde"] <= pos < f["hasta"]:
                    votos.append(f["dominante"])
                    break
        acuerdo[k] = max((votos.count(v) for v in set(votos)), default=0)

    _limpia(abajo)
    abajo.fill_between(x, 0, acuerdo, step="mid", color=REJILLA, zorder=2)
    abajo.plot(x, acuerdo, drawstyle="steps-mid", lw=1.6, color=MUDO, zorder=3)
    abajo.axhline(len(ns), color=EJE, lw=0.9, ls=(0, (4, 3)), zorder=1)
    abajo.text(0.995, len(ns) + 0.06, "unanime", ha="right", va="bottom",
               fontsize=7.5, color=MUDO)
    abajo.set_ylim(0, len(ns) + 0.45)
    abajo.set_yticks(range(1, len(ns) + 1))
    abajo.set_xlim(0, 1)
    abajo.set_ylabel("particiones\nde acuerdo")
    abajo.set_xlabel("posicion a lo largo del camino   "
                     "(0 = inicio, 1 = final)")

    fig.savefig(ruta, bbox_inches="tight")
    plt.close(fig)
    return ruta
