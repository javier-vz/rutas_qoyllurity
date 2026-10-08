"""El Qhapaq Nan como RED, y si el registro da para medirla.

Hay dos grafos en este proyecto y no son intercambiables.

El de `camino/grafo.py` es una REJILLA: un nodo por celda, aristas de
vecindad 16. Sobre eso, el grado es 16 por construccion, el agrupamiento lo
fija la geometria del lattice y el diametro es el tamano de la rejilla.
Calcular centralidad ahi y reportarla como propiedad del Qhapaq Nan seria
describir el raster.

Este modulo construye el otro: nodos = bifurcaciones y cabos del camino,
aristas = tramos entre ellos. Ahi las medidas de red si significan algo.

Y existe sobre todo para contestar una pregunta previa, que es la que
decide si lo demas tiene sentido: DADO EL REGISTRO QUE HAY, se puede medir
centralidad? La respuesta no es obvia y no es gratis, porque convertir
segmentos sueltos en una red exige decidir que huecos se cierran, y esa
decision determina toda la topologia.

Por eso lo que se reporta no es una centralidad: es como cambia la
centralidad al mover esa decision. Si el orden de las aristas por
centralidad aguanta entre 50 m y 2 km de tolerancia, se puede reportar. Si
no, el hallazgo es la inestabilidad, y es un hallazgo sobre lo que el
registro permite afirmar.
"""

from __future__ import annotations

import collections

import numpy as np

TOLERANCIAS = (0.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0)

# Una componente de este tamano ya es un corredor regional: dentro de ella
# las medidas de red significan algo, aunque el sistema entero no se conecte.
KM_GRANDE = 100.0


def cadenas(geometrias):
    """Segmentos sueltos -> cadenas sin bifurcacion, ya nodadas.

    `unary_union` corta en cada interseccion real; `linemerge` cose lo que
    no se bifurca. Los extremos de las cadenas resultantes son los nodos de
    la red: grado >= 3 es una bifurcacion, grado 1 es un cabo suelto.

    Esto se hace ANTES de cualquier tolerancia: es la topologia que el
    registro afirma, sin que nadie cierre nada.
    """
    from shapely import force_2d
    from shapely.ops import linemerge, unary_union

    geoms = [force_2d(g) for g in geometrias
             if g is not None and not g.is_empty
             and g.geom_type in ("LineString", "MultiLineString")]
    if not geoms:
        raise ValueError("no hay ninguna polilinea")

    u = unary_union(geoms)
    unido = linemerge(u) if u.geom_type != "LineString" else u
    return list(unido.geoms) if unido.geom_type == "MultiLineString" else [unido]


def _nodos(cadenas_, tolerancia: float):
    """Agrupa los extremos de las cadenas en nodos.

    Dos extremos a menos de `tolerancia` pasan a ser el mismo nodo. Es LA
    decision del analisis: con 0 m se respeta el registro al pie de la
    letra y cada hueco parte la red; con 2 km se cierran huecos que puede
    que nunca hayan sido camino.
    """
    from scipy.spatial import cKDTree

    extremos = np.array([p for c in cadenas_
                         for p in (c.coords[0], c.coords[-1])],
                        dtype=np.float64)[:, :2]

    if tolerancia <= 0:
        # sin tolerancia, igualdad exacta de coordenadas
        clave = {}
        ids = []
        for p in extremos:
            k = (round(p[0], 6), round(p[1], 6))
            ids.append(clave.setdefault(k, len(clave)))
        return np.array(ids), extremos

    # union-find sobre los pares a menos de la tolerancia
    padre = list(range(len(extremos)))

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    arbol = cKDTree(extremos)
    for a, b in arbol.query_pairs(tolerancia):
        ra, rb = raiz(a), raiz(b)
        if ra != rb:
            padre[ra] = rb

    renombra = {}
    ids = [renombra.setdefault(raiz(i), len(renombra))
           for i in range(len(extremos))]
    return np.array(ids), extremos


def construir(geometrias, tolerancia: float = 0.0):
    """La red: un MultiGraph con el largo de cada tramo como peso.

    MultiGraph y no Graph a proposito: dos lugares pueden estar unidos por
    mas de un camino, y colapsarlos borraria justo la redundancia que
    interesa medir.
    """
    import networkx as nx

    cs = cadenas(geometrias)
    ids, extremos = _nodos(cs, tolerancia)

    G = nx.MultiGraph()
    for k, c in enumerate(cs):
        a, b = int(ids[2 * k]), int(ids[2 * k + 1])
        if a == b:
            continue                      # lazo: no aporta conectividad
        G.add_edge(a, b, largo=float(c.length), cadena=k)
    for n in set(ids.tolist()):
        G.add_node(int(n))

    posicion = {}
    for i, n in enumerate(ids.tolist()):
        posicion.setdefault(int(n), extremos[i])
    for n, p in posicion.items():
        G.nodes[n]["x"], G.nodes[n]["y"] = float(p[0]), float(p[1])

    return G, cs


def medidas(G) -> dict:
    """Lo que se puede decir de la red tal como esta."""
    import networkx as nx

    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    grados = [d for _, d in G.degree()]
    mayor = G.subgraph(comps[0]) if comps else G

    # La masa de una red lineal esta en los KILOMETROS, no en los nodos. Un
    # registro con cientos de esquirlas de 3 km tiene casi todos sus NODOS
    # fuera de la componente mayor y aun asi puede tener un corredor de
    # cientos de km dentro de ella. Medir solo nodos confunde "muy
    # fragmentado" con "sin columna vertebral", que no es lo mismo.
    kms = sorted((sum(d["largo"] for *_, d in G.subgraph(c).edges(data=True))
                  / 1000 for c in comps), reverse=True)
    total_km = sum(kms) or 1.0
    grandes = [k for k in kms if k >= KM_GRANDE]

    return {
        "km_en_la_mayor": round(kms[0], 1) if kms else 0.0,
        "fraccion_km_en_la_mayor": round(kms[0] / total_km, 3) if kms else 0.0,
        "componentes_grandes": len(grandes),
        "fraccion_km_en_las_grandes": round(sum(grandes) / total_km, 3),
        "km_mediana_de_componente": round(
            float(np.median(kms)), 2) if kms else 0.0,
        "km_de_las_cinco_mayores": [round(k, 1) for k in kms[:5]],
        # Numero ciclomatico: cuantos caminos alternativos independientes
        # hay. Con cero, entre cada par de puntos existe UNA sola ruta y la
        # betweenness solo mide posicion a lo largo de la linea, no eleccion.
        "ciclos": (G.number_of_edges() - G.number_of_nodes() + len(comps)),
        "nodos": G.number_of_nodes(),
        "aristas": G.number_of_edges(),
        "componentes": len(comps),
        "nodos_en_la_mayor": mayor.number_of_nodes(),
        "fraccion_en_la_mayor": round(
            mayor.number_of_nodes() / max(G.number_of_nodes(), 1), 3),
        "aristas_en_la_mayor": mayor.number_of_edges(),
        "grado_medio": round(float(np.mean(grados)), 2) if grados else 0.0,
        "grado_maximo": int(max(grados)) if grados else 0,
        "fraccion_grado_1": round(
            sum(1 for d in grados if d == 1) / max(len(grados), 1), 3),
        "km_totales": round(
            sum(d["largo"] for *_, d in G.edges(data=True)) / 1000, 1),
    }


def centralidad_por_cadena(G, k: int | None = 400, semilla: int = 0) -> dict:
    """Betweenness de arista, devuelta por indice de cadena.

    Se pondera por el largo, que es lo que hace que el camino mas corto
    entre dos lugares sea el que de verdad recorre menos metros. Con `k`
    se estima sobre una muestra de nodos de origen: en una red de miles de
    nodos el calculo exacto es cuadratico y la estimacion basta para
    ORDENAR, que es lo unico que se necesita aqui.
    """
    import networkx as nx

    if G.number_of_edges() == 0:
        return {}
    k_real = None if k is None else min(k, G.number_of_nodes())
    bc = nx.edge_betweenness_centrality(
        G, k=k_real, weight="largo", seed=semilla)

    # Se recorre el dict por sus LLAVES (u, v, k), no en paralelo con
    # G.edges(): emparejar dos iteradores por posicion asigna la centralidad
    # de una arista a otra en cuanto el orden difiera, y no avisa.
    salida = {}
    for (u, v, llave), valor in bc.items():
        salida[G[u][v][llave]["cadena"]] = float(valor)
    return salida


def por_rasgo(cadenas_, centralidad, geometrias) -> np.ndarray:
    """Lleva la centralidad de las cadenas a los rasgos ORIGINALES.

    Hace falta para la prueba de sensibilidad: al cambiar la tolerancia
    cambian las cadenas, asi que no se pueden comparar entre si. Los rasgos
    del registro, en cambio, son los mismos siempre, y son ademas la unidad
    a la que despues se le puede medir el costo.

    Cada rasgo se asigna a la cadena mas cercana a su punto medio.
    """
    from shapely import force_2d
    from shapely.strtree import STRtree

    arbol = STRtree(cadenas_)
    valores = np.full(len(geometrias), np.nan)
    for i, g in enumerate(geometrias):
        if g is None or g.is_empty:
            continue
        medio = force_2d(g).interpolate(0.5, normalized=True)
        j = int(arbol.nearest(medio))
        valores[i] = centralidad.get(j, np.nan)
    return valores


def corredores(G, km_min: float | None = None):
    """Las componentes que ya son corredor, de mayor a menor, como subgrafos.

    Debajo de `km_min` una componente no es red: es una esquirla del
    registro, y cualquier medida que se le calcule describe su tamano.
    """
    import networkx as nx

    km_min = KM_GRANDE if km_min is None else km_min
    salida = []
    for c in nx.connected_components(G):
        sub = G.subgraph(c)
        km = sum(d["largo"] for *_, d in sub.edges(data=True)) / 1000
        if km >= km_min:
            salida.append((km, sub))
    return [sub for _, sub in sorted(salida, key=lambda x: -x[0])]


def centralidad_en_corredores(G, k: int | None = 400, semilla: int = 0,
                              km_min: float | None = None) -> dict:
    """Betweenness calculada DENTRO de cada corredor, por separado.

    Por dos razones, y la primera invalida la version global.

    Una: entre componentes no hay ningun camino, asi que una betweenness
    global le asigna cero a casi todas las aristas, y el orden que sale
    queda dominado por empates en cero. Correlacionar esos ordenes entre
    tolerancias no mide si los tramos centrales son los mismos; mide que
    los aislados siguen aislados. Con 917 componentes eso es casi todo.

    Dos: normalizada dentro de cada corredor, la cifra contesta "que tan de
    paso es este tramo EN SU corredor", que es la unica pregunta que el
    registro permite hacer.

    Las cadenas que no caen en ningun corredor quedan FUERA del dict, no en
    cero: no es que sean poco centrales, es que no hay red donde medirlas, y
    un cero ahi seria una afirmacion que no se tiene.
    """
    import networkx as nx

    salida = {}
    for sub in corredores(G, km_min):
        if sub.number_of_edges() < 2:
            continue
        k_real = None if k is None else min(k, sub.number_of_nodes())
        bc = nx.edge_betweenness_centrality(
            sub, k=k_real, weight="largo", seed=semilla, normalized=True)
        for (u, v, llave), valor in bc.items():
            salida[sub[u][v][llave]["cadena"]] = float(valor)
    return salida


def sensibilidad(geometrias, tolerancias=TOLERANCIAS, k: int | None = 400,
                 km_min: float | None = None):
    """Como cambia la red, y el ORDEN de los tramos, al mover la tolerancia.

    Es el resultado que decide si se puede hablar de centralidad con este
    registro. La correlacion de Spearman entre tolerancias consecutivas
    mide lo unico que importa: si el ORDEN de los tramos por centralidad se
    mantiene. Los valores absolutos de betweenness no son comparables entre
    redes distintas; el orden si.

    Se devuelven DOS correlaciones y solo la segunda es defendible:

        spearman_con_la_anterior  sobre la centralidad global. Con cientos
                                  de componentes queda dominada por los
                                  miles de rasgos aislados, que reciben
                                  cifras diminutas pero finitas. Se reporta
                                  para que se vea el contraste.
        spearman_en_corredores    solo sobre los rasgos que caen en un
                                  corredor en las dos tolerancias, con la
                                  betweenness medida dentro de el. Esta es
                                  la que contesta la pregunta, y viene con
                                  su propio n en `rasgos_comparables`.
    """
    from scipy.stats import spearmanr

    def rho_de(a, b):
        """Spearman sobre los rasgos con valor en LAS DOS tolerancias."""
        if a is None or b is None:
            return np.nan, 0
        bueno = np.isfinite(a) & np.isfinite(b)
        n = int(bueno.sum())
        if n <= 2 or np.nanstd(a[bueno]) == 0:
            return np.nan, n
        return float(spearmanr(a[bueno], b[bueno]).statistic), n

    filas = []
    previa_global = previa_corr = None
    for tol in tolerancias:
        # el grafo se arma UNA vez por tolerancia y se mide dos veces
        G, cs = construir(geometrias, tol)
        m = medidas(G)

        v_global = por_rasgo(cs, centralidad_por_cadena(G, k=k), geometrias)
        v_corr = por_rasgo(
            cs, centralidad_en_corredores(G, k=k, km_min=km_min), geometrias)

        rho_g, _ = rho_de(v_global, previa_global)
        rho_c, comunes = rho_de(v_corr, previa_corr)
        previa_global, previa_corr = v_global, v_corr

        filas.append({
            "tolerancia_m": tol, **m,
            "corredores": len(corredores(G, km_min)),
            "rasgos_con_centralidad": int(np.isfinite(v_corr).sum()),
            "rasgos_comparables": comunes,
            "spearman_con_la_anterior": (None if np.isnan(rho_g)
                                         else round(rho_g, 3)),
            "spearman_en_corredores": (None if np.isnan(rho_c)
                                       else round(rho_c, 3)),
        })
    return filas


def _lee_las_dos(cfg):
    """Lee el registro nacional con sus DOS categorias, y las separa.

    El pipeline normal lee solo las capas 'observado', y hace bien: para la
    optimizacion inversa la curva que hay que explicar tiene que ser camino
    relevado, no inferido. Aqui conviene exactamente lo contrario. Las capas
    'proyeccion de camino' son la interpolacion que hace el PROPIO registro
    de por donde iba el camino entre los pedazos relevados, o sea justo el
    tejido conectivo de la red. Medir conectividad despues de haberlo
    quitado mide una decision nuestra, no el registro.

    Por eso este paso corre dos veces y reporta las dos.

    Devuelve (geoms_observado, geoms_todo, resumen, gdf).
    """
    from . import registro, ruta as _ruta

    fuente = _ruta.busca_archivo(cfg)
    if fuente is None:
        raise SystemExit(
            "No hay archivo de geometria en datos/. Deja ahi el KMZ del\n"
            "registro: esta prueba se hace sobre el registro NACIONAL sin\n"
            "recortar, no sobre la caja del estudio.")
    if fuente.suffix.lower() not in (".kmz", ".kml"):
        raise SystemExit(
            f"Este paso necesita el KMZ/KML del registro y encontre\n"
            f"{fuente.name}. El KMZ es el unico que trae las CATEGORIAS\n"
            "(observado / proyectado), y la comparacion es entre esas dos.")

    print(f"  leyendo SIN recortar: {fuente.name}")
    if cfg.capas_camino:
        print("  (datos.capas_camino esta puesto en config.yaml; aqui se\n"
              "   ignora, porque fijar las capas a mano saltearia justo la\n"
              "   distincion observado / proyectado que se quiere comparar)")

    qn = registro.lee(fuente, cfg.crs, solo_observadas=False)
    qn, _ = registro.aplica_exclusiones(cfg, qn)

    cat = qn["categoria"].fillna("otro")
    obs = [g for g, c in zip(qn.geometry, cat) if c == "observado"]
    proy = [g for g, c in zip(qn.geometry, cat) if c == "proyectado"]

    def km(gs):
        return sum(g.length for g in gs if g is not None) / 1000

    resumen = {
        "rasgos_observado": len(obs), "km_observado": round(km(obs), 1),
        "rasgos_proyectado": len(proy), "km_proyectado": round(km(proy), 1),
    }
    total_km = resumen["km_observado"] + resumen["km_proyectado"]
    resumen["fraccion_km_inferida"] = round(
        resumen["km_proyectado"] / total_km, 3) if total_km else 0.0

    print(f"\n  solo observado : {len(obs):5d} rasgos, "
          f"{resumen['km_observado']:8.0f} km   (relevado en campo)")
    if proy:
        print(f"  + proyectado   : {len(obs) + len(proy):5d} rasgos, "
              f"{total_km:8.0f} km   (+{len(proy)} rasgos, "
              f"+{resumen['km_proyectado']:.0f} km inferidos por el registro"
              f" = {100 * resumen['fraccion_km_inferida']:.0f}% del total)")
    else:
        print("  + proyectado   : no hay ninguna capa 'proyeccion de camino'"
              " en este KMZ,\n                   asi que solo se puede medir"
              " lo observado.")

    # `todo` va en el ORDEN DEL GDF, no como obs + proy: mas abajo los
    # tramos se nombran por posicion contra el gdf, y concatenar las dos
    # categorias desplazaria cada nombre sin que nada avise.
    return obs, list(qn.geometry), resumen, qn


ANCHO = 31          # ancho de cada bloque de columnas de la tabla


def _fila_corta(f) -> str:
    rho = f["spearman_con_la_anterior"]
    return (f"{f['componentes']:5d} {f['km_en_la_mayor']:7.0f} "
            f"{f['componentes_grandes']:5d} "
            f"{f['fraccion_km_en_las_grandes']:5.2f} "
            f"{'     -' if rho is None else f'{rho:6.2f}'}")


def _tabla(filas_obs, filas_todo) -> None:
    """Las dos corridas lado a lado, solo con las columnas que deciden."""
    cab = (f"{'comp':>5s} {'kmMay':>7s} {'g100':>5s} {'%km':>5s} "
           f"{'rho':>6s}")
    print("\n  --- la red segun que huecos se cierren ---")
    if filas_todo:
        print("  " + " " * 7 + "solo observado".center(ANCHO)
              + "   " + "mas lo proyectado".center(ANCHO))
    print("  " + f"{'tol':>7s}" + cab + ("   " + cab if filas_todo else ""))

    for i, f in enumerate(filas_obs):
        linea = f"  {f['tolerancia_m']:6.0f}m" + _fila_corta(f)
        if filas_todo:
            linea += "   " + _fila_corta(filas_todo[i])
        print(linea)


def _glosario() -> None:
    print("\n  tol     cuanto hueco se cierra: dos extremos a menos de esa")
    print("          distancia pasan a ser el mismo nodo.")
    print("  comp    componentes desconectadas. Con muchas, no hay caminos")
    print("          entre la mayoria de los pares y la centralidad no mide")
    print("          nada.")
    print("  kmMay   KILOMETROS de camino en la componente mayor. Es la")
    print("          columna vertebral: lo mas largo que se puede recorrer")
    print("          sin salirse de lo que el registro conecta.")
    print(f"  g100    componentes de {KM_GRANDE:.0f} km o mas. Cada una es un")
    print("          corredor regional, medible por dentro.")
    print("  %km     fraccion de TODOS los km que cae en esas componentes")
    print("          grandes. Mide cuanto del sistema es red y cuanto es")
    print("          esquirla suelta.")
    print("  rho     correlacion de Spearman del ORDEN de los tramos por")
    print("          centralidad, contra la tolerancia anterior. ES LO QUE")
    print("          DECIDE: si se mantiene alto, el orden no depende de")
    print("          donde se puso el umbral y se puede reportar. Si baja,")
    print("          la centralidad que se midiera seria la del umbral.")


def _columna_vertebral(filas, etiqueta: str) -> None:
    """Las cinco componentes mayores, en km, sin cerrar ningun hueco.

    Es la cifra honesta: a tolerancia 0 nadie unio nada que el registro no
    une. Si ahi ya hay un corredor de cientos de km, existe aunque el
    sistema entero no se conecte.
    """
    f = filas[0]
    assert f["tolerancia_m"] == 0.0, "la primera fila tiene que ser tol 0"
    cinco = ", ".join(f"{k:.0f}" for k in f["km_de_las_cinco_mayores"])
    print(f"\n  {etiqueta}, sin cerrar ningun hueco (tol 0 m):")
    print(f"    las 5 componentes mayores: {cinco} km")
    print(f"    mediana de componente: {f['km_mediana_de_componente']:.1f} km"
          f"   |   componentes de >={KM_GRANDE:.0f} km: "
          f"{f['componentes_grandes']} "
          f"({100 * f['fraccion_km_en_las_grandes']:.0f}% de los km)")


def alfa(G) -> float:
    """Indice alfa de Garrison y Marble: ciclos observados / posibles.

    Mide cuanta REDUNDANCIA tiene la red: 0 es un arbol (una sola ruta entre
    cada par de puntos) y 1 es una malla completamente conectada. Es la
    medida que de verdad describe estos grafos, porque no depende de ninguna
    tolerancia ni de ningun umbral: se lee directo del conteo de nodos y
    aristas.

    Importa sobre todo para saber si la betweenness significa algo. En un
    arbol todos los caminos son forzados, asi que la betweenness de una
    arista es su posicion en la linea y nada mas; solo donde hay ciclos hay
    rutas alternativas y por tanto algo que elegir.
    """
    n, m = G.number_of_nodes(), G.number_of_edges()
    if n <= 2:
        return 0.0
    import networkx as nx
    ciclos = m - n + nx.number_connected_components(G)
    return ciclos / (2 * n - 5)


def _tabla_de_cada_corredor(geoms, tol: float = 0.0,
                            cuantos: int = 24) -> dict:
    """Corredor por corredor: tamano, estructura y si tiene alternativas."""
    import networkx as nx

    G, _ = construir(geoms, tol)
    grandes = corredores(G)
    if not grandes:
        print("\n  (no hay corredores que describir)")
        return {}

    print(f"\n  --- cada corredor de >={KM_GRANDE:.0f} km, uno por uno "
          f"(tol {tol:.0f} m) ---")
    print(f"  {'km':>7s} {'nodos':>6s} {'aristas':>8s} {'ciclos':>7s} "
          f"{'alfa':>6s}")

    km_arbol = km_total = 0.0
    arboles = 0
    for sub in grandes[:cuantos]:
        n, m = sub.number_of_nodes(), sub.number_of_edges()
        km = sum(d["largo"] for *_, d in sub.edges(data=True)) / 1000
        ciclos = m - n + nx.number_connected_components(sub)
        print(f"  {km:7.1f} {n:6d} {m:8d} {ciclos:7d} {alfa(sub):6.3f}")
    for sub in grandes:
        n, m = sub.number_of_nodes(), sub.number_of_edges()
        km = sum(d["largo"] for *_, d in sub.edges(data=True)) / 1000
        km_total += km
        if m - n + nx.number_connected_components(sub) <= 0:
            arboles += 1
            km_arbol += km
    if len(grandes) > cuantos:
        print(f"  ... y {len(grandes) - cuantos} corredores mas")

    print("\n  ciclos  caminos alternativos independientes. CERO quiere")
    print("          decir que entre cada par de puntos hay una sola ruta.")
    print("  alfa    ciclos observados sobre los posibles (Garrison y")
    print("          Marble). 0 = arbol, 1 = malla. No depende de ninguna")
    print("          tolerancia: sale del conteo de nodos y aristas.")

    frac = km_arbol / km_total if km_total else 0.0
    print(f"\n  {arboles} de los {len(grandes)} corredores son ARBOLES "
          f"(ningun ciclo):")
    print(f"  {km_arbol:.0f} de {km_total:.0f} km, el "
          f"{100 * frac:.0f}% de los kilometros en corredor. Ahi la")
    print("  betweenness no mide eleccion de ruta, mide posicion en la "
          "linea.")

    return {"corredores": len(grandes), "arboles": arboles,
            "km_en_corredor": round(km_total, 1),
            "km_en_arboles": round(km_arbol, 1),
            "fraccion_km_sin_alternativas": round(frac, 3)}


def _tabla_corredores(filas, etiqueta: str) -> None:
    """El contraste que se puede defender, con su propio tamano de muestra."""
    print(f"\n  --- centralidad DENTRO de los corredores ({etiqueta}) ---")
    print(f"  {'tol':>6s} {'corr':>5s} {'rasgos':>7s} {'comunes':>8s} "
          f"{'rho':>6s}")
    for f in filas:
        rho = f["spearman_en_corredores"]
        print(f"  {f['tolerancia_m']:5.0f}m {f['corredores']:5d} "
              f"{f['rasgos_con_centralidad']:7d} "
              f"{f['rasgos_comparables']:8d} "
              f"{'     -' if rho is None else f'{rho:6.2f}'}")
    print(f"\n  corr     corredores de >={KM_GRANDE:.0f} km, donde se midio.")
    print("  rasgos   rasgos del registro que cayeron en alguno y por tanto")
    print("           TIENEN centralidad. Los demas no valen cero: no hay")
    print("           red donde medirlos.")
    print("  comunes  rasgos con valor en esta tolerancia Y en la anterior.")
    print("           Es el n de la correlacion. Si es chico, el rho no")
    print("           dice nada por alto que salga.")
    print("  rho      Spearman del orden, solo sobre esos comunes. ESTE es")
    print("           el contraste honesto: el de la primera tabla esta")
    print("           dominado por los miles de rasgos aislados.")


def _mas_centrales(geoms, gdf, tol: float = 0.0, cuantos: int = 10,
                   k: int | None = 400) -> None:
    """Los tramos mas de paso del corredor mayor, por nombre del registro.

    Agrupado por `tramnomb` y no por cadena: el registro parte un mismo
    tramo en decenas de rasgos, asi que un top de cadenas devuelve diez
    pedazos del mismo tramo con la misma cifra y no dice nada. La unidad
    que le sirve a un arqueologo es el tramo.

    A tolerancia 0 y dentro de un solo corredor: es la afirmacion mas chica
    que los datos sostienen, sin pedirle a nadie que acepte huecos cerrados
    a dedo.
    """
    import collections

    G, cs = construir(geoms, tol)
    grandes = corredores(G)
    if not grandes:
        print("\n  (no hay ningun corredor de >=100 km: nada que ordenar)")
        return

    mayor = grandes[0]
    km_corr = sum(d["largo"] for *_, d in mayor.edges(data=True)) / 1000
    v = por_rasgo(cs, centralidad_en_corredores(mayor, k=k, km_min=0.0), geoms)

    nombres = (gdf["tramnomb"].fillna("(sin nombre)").tolist()
               if "tramnomb" in gdf.columns else ["(sin nombre)"] * len(geoms))
    if len(nombres) != len(geoms):
        raise ValueError(
            f"el gdf trae {len(nombres)} filas y las geometrias son "
            f"{len(geoms)}: los nombres saldrian desplazados")

    por_tramo = collections.defaultdict(list)
    for i, valor in enumerate(v):
        if np.isfinite(valor):
            por_tramo[nombres[i]].append((valor, geoms[i].length / 1000))

    filas = []
    for nombre, pares in por_tramo.items():
        bcs = np.array([x for x, _ in pares])
        kms = np.array([x for _, x in pares])
        filas.append((float(bcs.max()), float(np.median(bcs)),
                      float(kms.sum()), len(pares), nombre))
    filas.sort(reverse=True)

    print(f"\n  --- los tramos mas de paso DEL CORREDOR MAYOR "
          f"({km_corr:.0f} km, tol 0 m) ---")
    print(f"  {'bc max':>7s} {'bc med':>7s} {'km':>7s} {'rasgos':>7s}  tramo")
    for bc_max, bc_med, km, n, nombre in filas[:cuantos]:
        print(f"  {bc_max:7.3f} {bc_med:7.3f} {km:7.1f} {n:7d}  {nombre}")
    if len(filas) > cuantos:
        print(f"  ... y {len(filas) - cuantos} tramos mas en este corredor")

    print("\n  bc  betweenness de arista normalizada dentro del corredor:")
    print("      fraccion de los caminos mas cortos entre pares de nodos del")
    print("      corredor que pasan por ahi. Alto = cuello de botella. Se da")
    print("      el maximo y la mediana de los rasgos del tramo, porque un")
    print("      tramo largo puede ser de paso en un pedazo y no en otro.")


def _compara(filas_obs, filas_todo, resumen) -> str:
    """Cuanto de la red es inferencia del registro y no observacion de campo.

    Se mide en kilometros y sobre las componentes grandes, no en nodos: lo
    que interesa es si lo proyectado agranda la columna vertebral, no si
    mueve un estadistico de percolacion.
    """
    def mejor(filas, clave):
        return max(f[clave] for f in filas)

    col_obs = filas_obs[0]["km_en_la_mayor"]
    col_todo = filas_todo[0]["km_en_la_mayor"]
    g_obs = filas_obs[0]["componentes_grandes"]
    g_todo = filas_todo[0]["componentes_grandes"]
    km_obs = filas_obs[0]["fraccion_km_en_las_grandes"]
    km_todo = filas_todo[0]["fraccion_km_en_las_grandes"]
    pct = 100 * resumen["fraccion_km_inferida"]

    print("\n  --- que compra lo proyectado (a tolerancia 0, sin cerrar nada)"
          " ---")
    print(f"  componente mayor:            {col_obs:7.0f} km -> "
          f"{col_todo:7.0f} km")
    print(f"  componentes de >={KM_GRANDE:.0f} km:       "
          f"{g_obs:7d}    -> {g_todo:7d}")
    print(f"  % de km en esas componentes: {100 * km_obs:6.0f}%    -> "
          f"{100 * km_todo:6.0f}%")
    print(f"  precio:                      +{resumen['km_proyectado']:.0f} km"
          f" inferidos, {pct:.0f}% del total")

    crece = col_todo / col_obs if col_obs else float("inf")
    if crece >= 1.3 or km_todo - km_obs >= 0.1:
        v = (f"Lo proyectado SI aporta topologia, y se puede decir cuanta: la "
             f"columna\n  vertebral pasa de {col_obs:.0f} a {col_todo:.0f} km"
             f" ({crece:.1f}x) y las componentes grandes\n  de "
             f"{100 * km_obs:.0f}% a {100 * km_todo:.0f}% de los km, pagando "
             f"{pct:.0f}% de km inferidos. Es decir que esa\n  parte de la "
             "conectividad no esta observada: la infiere el registro, y "
             "quien\n  reporte centralidad esta reportando, en esa "
             "proporcion, la interpolacion.")
    else:
        v = ("Lo proyectado casi no agranda la columna vertebral. La "
             "fragmentacion no es\n  un sesgo de nuestro filtro por "
             "categoria: es del registro. El resultado\n  se puede afirmar "
             "del Qhapaq Nan registrado, no solo de lo relevado.")
    print(f"\n  LECTURA: {v}")
    return v


def informe(cfg) -> dict:
    """`python -m camino red`: construye la red y mide si es medible.

    Corre la prueba de sensibilidad dos veces -- solo con lo observado y
    anadiendo lo proyectado -- porque el filtro por categoria es nuestro y
    podria estar fabricando la fragmentacion que despues reportamos.
    """
    obs, todo, resumen, gdf = _lee_las_dos(cfg)

    filas_obs = sensibilidad(obs)
    filas_todo = None
    if resumen["rasgos_proyectado"]:
        print("  (ahora la misma pasada con lo proyectado dentro; "
              "tarda otro tanto)")
        filas_todo = sensibilidad(todo)

    _tabla(filas_obs, filas_todo)
    _glosario()

    _columna_vertebral(filas_obs, "solo observado")
    if filas_todo:
        _columna_vertebral(filas_todo, "mas lo proyectado")

    # El contraste restringido ya viene en las mismas filas; se muestra
    # aparte porque es el que decide y el otro esta ahi solo de contraste.
    _tabla_corredores(filas_obs, "solo observado")
    if filas_todo:
        _tabla_corredores(filas_todo, "mas lo proyectado")

    geoms, g = ((todo, gdf) if filas_todo else
                (obs, gdf[gdf["categoria"].fillna("otro") == "observado"]))
    estructura = _tabla_de_cada_corredor(geoms)
    _mas_centrales(geoms, g)

    if filas_todo:
        _veredicto(filas_obs, "solo observado")
        _veredicto(filas_todo, "mas lo proyectado", estructura)
        _compara(filas_obs, filas_todo, resumen)
    else:
        _veredicto(filas_obs, "solo observado", estructura)

    return {"resumen": resumen, "observado": filas_obs,
            "con_proyectado": filas_todo}


def _veredicto(filas, etiqueta: str = "", estructura=None) -> str:
    """Que se puede afirmar con este registro, sin adornos.

    La pregunta no es si el sistema entero es una red -- no lo es, y eso ya
    se sabe -- sino si hay DENTRO de el componentes bastante grandes como
    para que una medida de red signifique algo, y si el orden que esas
    medidas producen aguanta mover el umbral.
    """
    # El rho que decide es el de DENTRO de los corredores. El global esta
    # dominado por los rasgos aislados y diria "inestable" siempre.
    rhos = [f["spearman_en_corredores"] for f in filas
            if f["spearman_en_corredores"] is not None]
    n_min = min((f["rasgos_comparables"] for f in filas
                 if f["spearman_en_corredores"] is not None), default=0)

    # Todas las cifras del veredicto salen de la MISMA fila, la de
    # tolerancia 0: mezclar el conteo de una tolerancia con el porcentaje de
    # otra da una frase que suena bien y no describe ninguna corrida.
    base = filas[0]
    km_grandes = base["fraccion_km_en_las_grandes"]
    columna = base["km_en_la_mayor"]
    cuantas = base["componentes_grandes"]
    techo = max(f["fraccion_km_en_las_grandes"] for f in filas)
    tol_techo = max(f["tolerancia_m"] for f in filas)
    hasta = (f"\n  (cerrando huecos de hasta {tol_techo:.0f} m llega a "
             f"{100 * techo:.0f}% de los km.)" if techo > km_grandes + 0.02
             else "")

    if max(km_grandes, techo) < 0.25:
        v = ("Ni una cuarta parte de los kilometros cae en componentes "
             "grandes: son\n  esquirlas. No hay red que medir, y no es "
             "cuestion de afinar el umbral.")
    elif not rhos or min(rhos) < 0.7 or n_min < 50:
        v = (f"NO hay una red: hay {cuantas} corredores de >={KM_GRANDE:.0f}"
             f" km (el mayor, {columna:.0f} km)\n  que juntan "
             f"{100 * km_grandes:.0f}% de los kilometros, sin cerrar ningun "
             f"hueco.{hasta}\n  Medir centralidad ahi dentro tiene sentido, "
             "pero el ORDEN que sale CAMBIA\n  al mover el umbral, asi que "
             "reportarlo seria reportar el umbral. Eso --\n  la "
             "inestabilidad -- es el resultado publicable tal como estan los "
             "datos.")
    else:
        v = (f"NO hay una red global, pero si {cuantas} corredores de "
             f">={KM_GRANDE:.0f} km (el mayor,\n  {columna:.0f} km) con "
             f"{100 * km_grandes:.0f}% de los kilometros sin cerrar ningun "
             f"hueco.{hasta} El orden por\n  centralidad aguanta mover el "
             "umbral, asi que es reportable DENTRO de cada\n  corredor, y "
             "tiene sentido cruzarlo con la razon de costo de cada tramo.")
    # El aviso que mas limita lo que se puede decir: donde el corredor es un
    # arbol, la betweenness es posicion y no eleccion de ruta.
    if estructura and estructura.get("fraccion_km_sin_alternativas", 0) > 0.3:
        v += (f"\n  PERO {estructura['arboles']} de los "
              f"{estructura['corredores']} corredores no tienen ningun ciclo "
              f"({100 * estructura['fraccion_km_sin_alternativas']:.0f}% de "
              f"los km\n  en corredor): ahi la betweenness no mide eleccion "
              "de ruta porque no hay\n  ninguna que elegir. La centralidad "
              "solo dice algo en los corredores con\n  ciclos, y el indice "
              "alfa es la medida que los distingue.")

    cual = f" ({etiqueta})" if etiqueta else ""
    print(f"\n  VEREDICTO{cual}: {v}")
    return v
