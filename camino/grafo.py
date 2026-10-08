"""Grafo de transito sobre el raster, y la matriz de componentes.

El truco que hace factible el barrido: la topologia del grafo y las
componentes phi NO dependen de los pesos. Se precalculan una vez la matriz
Phi (E x K) y el vector L (E), y por cada vector de pesos lo unico que se
recalcula es el vector de datos de la matriz dispersa:

    csr.data[:] = L * (Phi @ w)

Si se reconstruye la matriz dentro del bucle, ahi se va el 95% del tiempo.

Trampa que arruina esto si no se cuida: `csr_matrix((data, (rows, cols)))`
reordena las aristas y suma duplicados, asi que `csr.data` NO queda en el
orden en que se le pasaron. Aqui se resuelve con un mapa de posiciones
explicito (`_permutacion_csr`), no suponiendo nada del orden interno de scipy.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import scipy.sparse as sp

from . import costo

# Vecindad 8: los caminos solo pueden girar en pasos de 45 grados y se
# alargan hasta 8.2% (1/cos 22.5).
VECINOS_8 = ((-1, -1), (-1, 0), (-1, 1),
             (0, -1), (0, 1),
             (1, -1), (1, 0), (1, 1))

# Vecindad 16: los 8 anteriores mas los saltos de caballo. El sesgo de
# cuantizacion angular baja a 2.8% (1/cos 13.3).
VECINOS_16 = VECINOS_8 + ((-1, -2), (-1, 2), (1, -2), (1, 2),
                          (-2, -1), (-2, 1), (2, -1), (2, 1))


def intermedias(di: int, dj: int) -> tuple[tuple[int, int], ...]:
    """Celdas por las que pasa un salto de caballo.

    Un paso (+-1, +-2) o (+-2, +-1) cruza por encima de dos celdas. Si no se
    comprueba que esas celdas sean transitables, el camino se salta
    acantilados y rios. Es el error clasico de la vecindad 16.
    """
    if abs(di) == 1 and abs(dj) == 2:
        return ((0, dj // 2), (di, dj // 2))
    if abs(di) == 2 and abs(dj) == 1:
        return ((di // 2, 0), (di // 2, dj))
    return ()


def _vistas(forma, di: int, dj: int):
    """Pares de rebanadas (origen, destino) para el desplazamiento (di, dj)."""
    nf, nc = forma
    i0, i1 = max(0, -di), nf - max(0, di)
    j0, j1 = max(0, -dj), nc - max(0, dj)
    org = (slice(i0, i1), slice(j0, j1))
    dst = (slice(i0 + di, i1 + di), slice(j0 + dj, j1 + dj))
    return org, dst


@dataclasses.dataclass
class Grafo:
    """Grafo dirigido listo para barrer pesos."""

    n: int                      # numero de nodos
    forma: tuple[int, int]      # forma del raster
    indice: np.ndarray          # raster int64: nodo de cada celda, -1 si no
    filcol: np.ndarray          # (n, 2) fila y columna de cada nodo
    L: np.ndarray               # (E,) longitud de cada arista, en metros
    Phi: np.ndarray             # (E, K) componentes, ya normalizadas
    nombres: tuple[str, ...]    # orden de las columnas de Phi
    _csr: sp.csr_matrix         # estructura fija, datos reescribibles

    @property
    def e(self) -> int:
        return int(self.L.size)

    def costos(self, w) -> sp.csr_matrix:
        """Matriz de costos para el vector de pesos `w`. Reusa la estructura."""
        w = np.asarray(w, dtype=np.float64)
        if w.shape != (len(self.nombres),):
            raise ValueError(f"w debe tener {len(self.nombres)} componentes")
        if w.min() < 0:
            raise ValueError("los pesos no pueden ser negativos")
        if not np.isclose(w.sum(), 1.0):
            raise ValueError("los pesos deben sumar 1 (viven en el simplex)")
        self._csr.data[:] = self.L * (self.Phi @ w)
        return self._csr

    def guardar(self, ruta) -> None:
        """Guarda el grafo ya permutado, para no reconstruirlo cada vez."""
        np.savez_compressed(
            ruta,
            indices=self._csr.indices, indptr=self._csr.indptr,
            L=self.L.astype(np.float32), Phi=self.Phi.astype(np.float32),
            filcol=self.filcol.astype(np.int32), indice=self.indice,
            nombres=np.array(self.nombres), forma=np.array(self.forma),
            n=np.array([self.n]))

    @classmethod
    def cargar(cls, ruta) -> "Grafo":
        d = np.load(ruta, allow_pickle=False)
        n = int(d["n"][0])
        L = d["L"].astype(np.float64)
        csr = sp.csr_matrix((np.ones(L.size, dtype=np.float64),
                             d["indices"], d["indptr"]), shape=(n, n))
        return cls(n=n, forma=tuple(int(v) for v in d["forma"]),
                   indice=d["indice"], filcol=d["filcol"].astype(np.int64),
                   L=L, Phi=d["Phi"].astype(np.float64),
                   nombres=tuple(str(s) for s in d["nombres"]), _csr=csr)

    def subconjunto(self, nodos) -> "Grafo":
        """Un grafo restringido a `nodos`, con los indices renumerados.

        Hace falta para analizar cada unidad (sector o tramo) en SU PROPIA
        vecindad. Si el nulo de un tramo se corriera sobre el corredor
        entero, estaria preguntando algo distinto -- y tardaria horas: el
        coste de un Dijkstra crece con el grafo, no con el trozo que
        interesa.
        """
        nodos = np.unique(np.asarray(nodos, dtype=np.int64))
        if nodos.size == 0:
            raise ValueError("el subconjunto no tiene ningun nodo")

        renum = np.full(self.n, -1, dtype=np.int64)
        renum[nodos] = np.arange(nodos.size, dtype=np.int64)

        filas = np.repeat(np.arange(self.n, dtype=np.int64),
                          np.diff(self._csr.indptr))
        cols = self._csr.indices.astype(np.int64)
        viva = (renum[filas] >= 0) & (renum[cols] >= 0)
        if not viva.any():
            raise ValueError("el subconjunto no deja ninguna arista")

        f2, c2 = renum[filas[viva]], renum[cols[viva]]
        L2, Phi2 = self.L[viva], self.Phi[viva]

        perm, indices, indptr = _permutacion_csr(f2, c2, nodos.size)
        csr = sp.csr_matrix((np.ones(L2.size, dtype=np.float64), indices, indptr),
                            shape=(nodos.size, nodos.size))

        indice = np.full(self.forma, -1, dtype=np.int64)
        fc = self.filcol[nodos]
        indice[fc[:, 0], fc[:, 1]] = np.arange(nodos.size)

        return Grafo(n=int(nodos.size), forma=self.forma, indice=indice,
                     filcol=fc, L=np.ascontiguousarray(L2[perm]),
                     Phi=np.ascontiguousarray(Phi2[perm]),
                     nombres=self.nombres, _csr=csr)

    def fija_componente(self, nombre: str, por_nodo) -> None:
        """Reescribe una columna de Phi desde un valor por nodo.

        Hace falta porque hay componentes que NO son globales. La
        proximidad ceremonial, por ejemplo, excluye los sitios que caen en
        los extremos del tramo analizado -- es regla del proyecto -- asi que
        su superficie depende de la unidad y se recalcula sobre el subgrafo.
        La regla de transformacion (la saturacion) si es comun: lo que
        cambia es el conjunto de sitios, no la escala.
        """
        if nombre not in self.nombres:
            raise ValueError(f"'{nombre}' no es una componente de este grafo")
        k = self.nombres.index(nombre)
        v = np.asarray(por_nodo, dtype=np.float64)
        if v.shape != (self.n,):
            raise ValueError(f"se esperaba un valor por nodo ({self.n})")
        filas = np.repeat(np.arange(self.n, dtype=np.int64),
                          np.diff(self._csr.indptr))
        self.Phi[:, k] = 0.5 * (v[filas] + v[self._csr.indices])

    def xy_nodos(self, transform6):
        """Coordenadas del centro de cada nodo."""
        return xy(self.filcol, transform6)

    def nodos_cerca_de(self, geometria, transform, radio: float) -> np.ndarray:
        """Nodos a menos de `radio` metros de una geometria."""
        from scipy.spatial import cKDTree
        from shapely import get_coordinates

        pts = get_coordinates(geometria)
        if pts.size == 0:
            raise ValueError("la geometria no tiene vertices")
        xy_nodos = xy(self.filcol, transform)
        d, _ = cKDTree(pts).query(xy_nodos)
        return np.flatnonzero(d <= radio)

    def nodo(self, fila: int, col: int) -> int:
        v = int(self.indice[fila, col])
        if v < 0:
            raise ValueError(f"la celda ({fila}, {col}) esta enmascarada")
        return v

    def nodo_mas_cercano(self, fila: int, col: int) -> int:
        """El nodo valido mas cercano a una celda, por si cae en la mascara."""
        if self.indice[fila, col] >= 0:
            return int(self.indice[fila, col])
        d2 = ((self.filcol[:, 0] - fila) ** 2 + (self.filcol[:, 1] - col) ** 2)
        return int(np.argmin(d2))

    def coordenadas(self, nodos, transform6=None):
        """Filas/columnas de una lista de nodos, o coordenadas proyectadas."""
        fc = self.filcol[np.asarray(nodos, dtype=np.int64)]
        return fc if transform6 is None else xy(fc, transform6)


def xy(filcol, transform6):
    """Coordenadas del centro de pixel, con un transform afin (a,b,c,d,e,f).

    Es el `tuple(src.transform)[:6]` de rasterio, pasado como tupla para que
    este modulo no dependa de rasterio y se pueda serializar a los procesos
    del barrido.
    """
    a, b, c, d, e, f = (float(v) for v in transform6)
    fc = np.asarray(filcol, dtype=np.float64)
    col = fc[:, 1] + 0.5
    fil = fc[:, 0] + 0.5
    return np.column_stack([c + a * col + b * fil, f + d * col + e * fil])


def _permutacion_csr(filas, cols, n):
    """Mapa posicion-CSR -> indice de arista de entrada.

    Se construye una matriz con las aristas numeradas 1..E como datos; al
    convertir a CSR, `data[s]` dice que arista quedo en la posicion `s`.
    Asi no hay que suponer nada sobre el orden interno de scipy.
    """
    e = filas.size
    marca = sp.csr_matrix(
        (np.arange(1, e + 1, dtype=np.int64), (filas, cols)), shape=(n, n))
    if marca.nnz != e:
        raise RuntimeError(
            f"hay aristas duplicadas: {e} construidas, {marca.nnz} en la matriz")
    return marca.data - 1, marca.indices, marca.indptr


def construir(z, mascara, componentes: dict[str, np.ndarray], dx: float,
              dy: float | None = None, g_max: float = costo.G_MAX,
              vecinos=VECINOS_16) -> Grafo:
    """Construye el grafo dirigido y la matriz de componentes.

    `z`            DEM crudo (sin rellenar), en metros.
    `mascara`      booleano: celdas transitables.
    `componentes`  rasters ya normalizados a [eps, 1+eps], uno por componente
                   simetrica (rugosidad, drenaje, humedad). La pendiente NO
                   va aqui: se calcula por arista.
    `g_max`        borde de validez de Minetti. Las aristas con |g| > g_max se
                   ELIMINAN, no se recortan: recortarlas convierte un
                   acantilado en una cuesta transitable.
    """
    z = np.asarray(z, dtype=np.float64)
    mascara = np.asarray(mascara, dtype=bool) & np.isfinite(z)
    dy = dx if dy is None else dy
    forma = z.shape

    for nombre, c in componentes.items():
        if np.asarray(c).shape != forma:
            raise ValueError(f"la componente '{nombre}' no tiene la forma del DEM")

    indice = np.full(forma, -1, dtype=np.int64)
    indice[mascara] = np.arange(int(mascara.sum()), dtype=np.int64)
    n = int(mascara.sum())
    if n == 0:
        raise ValueError("la mascara no deja ninguna celda transitable")
    ff, cc = np.nonzero(mascara)
    filcol = np.column_stack([ff, cc]).astype(np.int64)

    nombres = ("pendiente",) + tuple(componentes.keys())
    trozos_f, trozos_c, trozos_L, trozos_phi = [], [], [], []

    for di, dj in vecinos:
        org, dst = _vistas(forma, di, dj)
        if org[0].stop <= org[0].start or org[1].stop <= org[1].start:
            continue

        ok = mascara[org] & mascara[dst]
        largo = float(np.hypot(di * dy, dj * dx))

        for ei, ej in intermedias(di, dj):
            # la celda intermedia vista desde el origen
            inter = (slice(org[0].start + ei, org[0].stop + ei),
                     slice(org[1].start + ej, org[1].stop + ej))
            ok &= mascara[inter]

            # Y SU PENDIENTE, no solo que sea transitable. Un salto de
            # caballo mide 67 m y el gradiente MEDIO de la arista puede estar
            # dentro del rango escondiendo un escalon en el medio: comprobar
            # solo la mascara deja pasar aristas que suben un acantilado y
            # bajan al otro lado, y el modelo entonces encuentra atajos por
            # donde no se puede caminar. Se exige que los dos tramos del
            # salto, origen->intermedia e intermedia->destino, esten cada uno
            # dentro del rango.
            l1 = float(np.hypot(ei * dy, ej * dx))
            l2 = float(np.hypot((di - ei) * dy, (dj - ej) * dx))
            with np.errstate(invalid="ignore"):
                g1 = (z[inter] - z[org]) / l1
                g2 = (z[dst] - z[inter]) / l2
            ok &= (np.isfinite(g1) & (np.abs(g1) <= g_max)
                   & np.isfinite(g2) & (np.abs(g2) <= g_max))

        if not ok.any():
            continue

        with np.errstate(invalid="ignore"):
            g = (z[dst] - z[org]) / largo
        ok &= np.isfinite(g) & (np.abs(g) <= g_max)
        if not ok.any():
            continue

        io = indice[org][ok]
        id_ = indice[dst][ok]
        gg = g[ok]

        cols_phi = [costo.minetti(gg) / costo.C_PLANO]
        for c in componentes.values():
            c = np.asarray(c, dtype=np.float64)
            cols_phi.append(0.5 * (c[org][ok] + c[dst][ok]))
        phi = np.column_stack(cols_phi)

        fino = np.isfinite(phi).all(axis=1)
        trozos_f.append(io[fino])
        trozos_c.append(id_[fino])
        trozos_L.append(np.full(int(fino.sum()), largo))
        trozos_phi.append(phi[fino])

    if not trozos_f:
        raise ValueError("no quedo ninguna arista: revisa g_max y la mascara")

    filas = np.concatenate(trozos_f)
    cols = np.concatenate(trozos_c)
    L = np.concatenate(trozos_L)
    Phi = np.vstack(trozos_phi)

    perm, indices, indptr = _permutacion_csr(filas, cols, n)
    L = np.ascontiguousarray(L[perm])
    Phi = np.ascontiguousarray(Phi[perm])

    csr = sp.csr_matrix(
        (np.ones(L.size, dtype=np.float64), indices, indptr), shape=(n, n))

    return Grafo(n=n, forma=forma, indice=indice, filcol=filcol,
                 L=L, Phi=Phi, nombres=nombres, _csr=csr)


def recorre(predecesores, origen: int, destino: int) -> np.ndarray:
    """Reconstruye el camino origen -> destino del arbol de Dijkstra.

    Devuelve los indices de nodo en orden. Array vacio si no hay camino.
    """
    pred = np.asarray(predecesores)
    camino = [int(destino)]
    v = int(destino)
    limite = pred.size + 1
    while v != origen:
        v = int(pred[v])
        if v < 0 or len(camino) > limite:
            return np.empty(0, dtype=np.int64)
        camino.append(v)
    return np.array(camino[::-1], dtype=np.int64)


def costo_a_lo_largo(csr, nodos) -> float:
    """Costo total de recorrer una secuencia de nodos ADYACENTES.

    Sirve para preguntarle a un modelo cuanto cuesta una ruta que no es la
    suya: la observada, o una generada por un nulo. Sin esto solo se puede
    comparar geometria, y la geometria no distingue "esta ruta es otra" de
    "esta ruta es peor".

    Vectorizado a proposito. Se llama una vez por realizacion del nulo (500
    por unidad, seis unidades), y un bucle de Python sobre los nodos de cada
    camino anadia minutos a un paso que ya tarda un cuarto de hora. Los
    indices de cada fila de un CSR canonico estan ordenados y el grado
    maximo es 16, asi que se busca el destino en una ventana de ancho fijo.
    """
    nodos = np.asarray(nodos, dtype=np.int64)
    if nodos.size < 2:
        return 0.0

    a, b = nodos[:-1], nodos[1:]
    ini, fin = csr.indptr[a], csr.indptr[a + 1]
    k = int(np.diff(csr.indptr).max())
    pos = ini[:, None] + np.arange(k)[None, :]
    dentro = pos < fin[:, None]
    seguro = np.clip(pos, 0, len(csr.indices) - 1)
    acierta = dentro & (csr.indices[seguro] == b[:, None])

    if not acierta.any(axis=1).all():
        return float("nan")        # la secuencia no es un camino del grafo
    j = np.argmax(acierta, axis=1)
    return float(csr.data[seguro[np.arange(len(a)), j]].sum())
