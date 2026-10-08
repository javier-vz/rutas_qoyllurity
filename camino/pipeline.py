"""Los pasos del estudio, en orden, cada uno dejando su salida en disco.

El orden NO es decorativo. El paso `nulos` va antes que `barrido_sectores`
porque un sector cuyo mejor camino no le gana a terreno aleatorio no tiene
pesos que reportar, y compararle los pesos a otro sector seria comparar dos
numeros sin contenido.
"""

from __future__ import annotations

import json

import numpy as np

from . import (barrido, costo, descarga, equifinalidad, grafo, hidrologia,
               metricas, nulos, preparar, sitios, superficies, visibilidad)

_DEM = {}


def _dem(cfg):
    """El DEM, leido una sola vez por corrida.

    La visibilidad lo necesita en cada unidad y en cada bloque de la
    validacion; releerlo 24 veces no cambia el resultado pero si el rato que
    uno pasa mirando la consola.
    """
    ruta = cfg.dir_derivados / "cop30.tif"
    clave = (str(ruta), ruta.stat().st_mtime_ns)
    if clave not in _DEM:
        _DEM.clear()
        _DEM[clave] = preparar.lee(ruta)[0]
    return _DEM[clave]


def _guarda_json(cfg, nombre, obj):
    ruta = cfg.dir_resultados / nombre
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=float)
    print(f"  -> {ruta.relative_to(cfg.raiz)}")
    return ruta


# ------------------------------------------------------------- 1. bajar

def bajar(cfg, forzar=False):
    print("DEM (dos fuentes, para tener la banda de incertidumbre):")
    rutas = descarga.dems(cfg, forzar=forzar)
    print("\nCuerpos de agua (OpenStreetMap) -- opcional:")
    descarga.agua(cfg, forzar=forzar)
    print("\nLa red de drenaje no se baja: se deriva del DEM en 'superficies'.")
    return rutas


# --------------------------------------------------------- 2. preparar

def preparar_rasteres(cfg):
    import geopandas as gpd

    print("Alineando los dos DEM a la rejilla comun:")
    salidas = preparar.alinear(cfg, {
        "cop30": cfg.dir_datos / "cop30_raw.tif",
        "aw3d30": cfg.dir_datos / "aw3d30_raw.tif"})

    a, t, _ = preparar.lee(salidas["cop30"])
    b, _, _ = preparar.lee(salidas["aw3d30"])
    banda = preparar.banda_incertidumbre(a, b)
    print(f"  incertidumbre vertical entre fuentes: {banda}")

    ruta_camino = cfg.dir_datos / "qn_geocam.gpkg"
    if ruta_camino.exists():
        print("Mascara del corredor:")
        camino = gpd.read_file(ruta_camino, layer="camino")
        agua_geoms = _agua_geoms(cfg)
        mascara, _ = preparar.mascara_corredor(cfg, camino, agua_geoms)
    else:
        print("Sin camino observado todavia: la mascara es la caja entera.")
        print("  Puedes seguir con 'superficies', que no lo necesita. Para")
        print("  'grafo' en adelante si hace falta: `python -m camino ruta`.")
        mascara = np.isfinite(a)

    preparar.escribe(cfg.dir_derivados / "mascara.tif",
                     mascara.astype(np.float32), t, cfg.crs, nodata=0)
    print(f"  {int(mascara.sum())} celdas transitables de {mascara.size} "
          f"({100 * mascara.mean():.1f}%)")

    _guarda_json(cfg, "incertidumbre_vertical.json", banda)
    return salidas


def _agua_geoms(cfg):
    """Cuerpos de agua que son de verdad INFRANQUEABLES: lagunas.

    Los RIOS NO entran aqui, y es una decision de modelado, no un descuido.
    Un rio enmascarado es un rio que no se puede cruzar en ningun punto, y
    entonces no existe ningun camino entre las dos orillas -- que es
    exactamente lo que pasaba: el grafo quedaba partido en dos y `revisar`
    no encontraba ruta. Los caminos incas cruzaban rios por puentes y vados,
    y no sabemos donde estaban.

    Cruzar un rio no es imposible, es caro, y eso ya lo recoge la componente
    de drenaje: `phi_dren = log10(1 + area acumulada)`, que crece justo con
    el tamano del cauce. El Utcubamba sale carisimo por esa via, sin
    necesidad de prohibirlo.

    Una laguna si es infranqueable, asi que los poligonos cerrados de agua
    se quedan, a partir de un tamano minimo.

    EL ORDEN IMPORTA ademas: Overpass devuelve grados; medir areas o
    ensanchar ahi da resultados en grados cuadrados. Primero se reproyecta.
    """
    ruta = cfg.dir_datos / "agua_osm.json"
    if not ruta.exists():
        return []
    import geopandas as gpd
    from shapely.geometry import LineString, Polygon

    with open(ruta, encoding="utf-8") as f:
        d = json.load(f)

    poligonos, n_rios = [], 0
    for el in d.get("elements", []):
        pts = [(p["lon"], p["lat"]) for p in el.get("geometry", []) or []]
        if len(pts) < 2:
            continue
        cerrado = pts[0] == pts[-1] and len(pts) >= 4
        if el.get("tags", {}).get("natural") == "water" and cerrado:
            poligonos.append(Polygon(pts))
        else:
            n_rios += 1

    if not poligonos:
        print(f"  agua: 0 lagunas; {n_rios} rios, que NO se enmascaran "
              "(cruzarlos es caro, no imposible)")
        return []

    metricos = gpd.GeoSeries(poligonos, crs="EPSG:4326").to_crs(cfg.crs)
    grandes = [g for g in metricos if g.area >= cfg.area_min_laguna]
    print(f"  agua: {len(grandes)} lagunas por encima de "
          f"{cfg.area_min_laguna / 1e4:.0f} ha "
          f"({len(poligonos) - len(grandes)} mas pequenas descartadas); "
          f"{n_rios} rios, que NO se enmascaran")
    return grandes


# ------------------------------------------------------ 3. superficies

def construir_superficies(cfg):
    """Superficies derivadas y la mascara de restricciones geomorfologicas.

    Cambio respecto de la version anterior, y es el que pedia el proyecto:
    rugosidad y drenaje YA NO son componentes ponderadas del costo. La
    rugosidad pasa a RESTRICCION (los farallones y el terreno desmoronado
    no se transitan, no es que sean caros) y el drenaje queda como
    diagnostico. Lo que delimita el espacio de transito no recibe peso ni
    se optimiza: es identico para los dos modelos, que es lo que permite
    atribuir las diferencias a las componentes anadidas.
    """
    preparar.comprueba_rejilla(cfg)
    dem, t, _ = preparar.lee(cfg.dir_derivados / "cop30.tif")
    mascara = preparar.lee(cfg.dir_derivados / "mascara.tif")[0] > 0.5
    mascara &= np.isfinite(dem)
    res = cfg.resolucion

    print("Pendiente y aspecto (Horn, sobre el DEM SIN rellenar):")
    S, A = superficies.pendiente_aspecto(dem, res, valido=mascara)

    print("Rugosidad (VRM) -- como RESTRICCION, no como peso:")
    rug = superficies.vrm(S, A)
    n_antes = int(mascara.sum())
    if cfg.rugosidad_percentil < 100:
        umbral = float(np.nanpercentile(rug[mascara], cfg.rugosidad_percentil))
        mascara &= ~(np.isfinite(rug) & (rug > umbral))
        print(f"  VRM > {umbral:.3f} (percentil {cfg.rugosidad_percentil:g}) "
              f"= intransitable: {n_antes - int(mascara.sum())} celdas fuera")

    print("Hidrologia (el relleno de depresiones se usa SOLO aqui):")
    relleno = hidrologia.rellenar(dem, mascara)
    dirs = hidrologia.d8(relleno, res, valido=mascara)
    acc = hidrologia.acumulacion(dirs, valido=mascara, z_relleno=relleno)
    n_cauce = int(hidrologia.cauces(acc, cfg.umbral_quebrada).sum())
    print(f"  {n_cauce} celdas de quebrada con umbral {cfg.umbral_quebrada:g}"
          "  (diagnostico; no entra en el costo)")

    preparar.escribe(cfg.dir_derivados / "mascara.tif",
                     mascara.astype(np.float32), t, cfg.crs, nodata=0)
    preparar.escribe(cfg.dir_derivados / "pendiente_rad.tif", S, t, cfg.crs)
    preparar.escribe(cfg.dir_derivados / "rugosidad.tif", rug, t, cfg.crs)
    preparar.escribe(cfg.dir_derivados / "acumulacion.tif", acc, t, cfg.crs)
    print(f"  mascara final: {int(mascara.sum())} celdas transitables")
    return {"mascara": mascara}


# ------------------------------------------------------------ 4. grafo

def construir_grafo(cfg):
    """El grafo, con una columna de Phi por componente del costo.

    'fisico' se calcula por arista (es la unica anisotropica). Las demas se
    dejan en un valor neutro y se rellenan por unidad: la proximidad
    ceremonial excluye los sitios de los extremos del tramo, asi que su
    superficie depende de la unidad analizada.
    """
    preparar.comprueba_rejilla(cfg)
    dem, t, _ = preparar.lee(cfg.dir_derivados / "cop30.tif")
    mascara = preparar.lee(cfg.dir_derivados / "mascara.tif")[0] > 0.5

    neutro = np.full(dem.shape, 0.5, dtype=np.float64)
    comps = {c: neutro for c in cfg.componentes_simetricas}

    print(f"Grafo con vecindad {cfg.vecindad} y g_max = {cfg.g_max}:")
    g = grafo.construir(dem, mascara, comps, cfg.resolucion,
                        g_max=cfg.g_max, vecinos=cfg.vecinos)
    # la componente de pendiente se llama 'fisico' en el vocabulario del
    # proyecto; el resto del codigo la conoce por el nombre de la config
    g.nombres = cfg.componentes
    print(f"  {g.n} nodos, {g.e} aristas ({g.e / g.n:.1f} por nodo)")
    print(f"  componentes: {g.nombres}")
    print(f"  modelos: {dict(cfg.modelos)}")

    ruta = cfg.dir_derivados / "grafo.npz"
    g.guardar(ruta)
    print(f"  -> {ruta.relative_to(cfg.raiz)}")
    return g


def revisar_grafo(cfg):
    """Un camino por unidad, con todo el peso en el costo fisico, para mirarlo.

    Si ESTOS caminos no son plausibles sobre el terreno, nada de lo que sigue
    lo es. Es el paso que no se salta, y sale antes de los nulos porque
    cuesta segundos y los nulos cuestan un cuarto de hora.

    DOS COSAS QUE ESTABAN MAL AQUI, y las dos daban numeros enganosos:

    1. Corria UN Dijkstra sobre el corredor ENTERO. El corredor es la union
       de los buffers de los 142 km de camino registrado, en 28 pedazos, asi
       que el camino modelado podia irse por el buffer de otro tramo y la
       distancia resultante no era comparable con nada. El barrido no hace
       eso: restringe cada unidad a SU vecindad (`_contexto`). Ahora esto
       usa el mismo subgrafo, y por eso el numero que imprime si anticipa lo
       que va a reportar el barrido.

    2. Revisaba la unidad mas LARGA, que en esta caja resulta ser una de las
       cuatro que el bbox recorta. Un tramo recortado tiene un extremo
       inventado -- no es un destino, es donde cortamos-- asi que es el peor
       candidato posible para una comprobacion de cordura. Ahora se revisan
       TODAS y las recortadas salen marcadas.
    """
    import geopandas as gpd
    from scipy.sparse.csgraph import dijkstra
    from shapely.geometry import LineString

    g, t, uds = _carga_unidades(cfg)
    # sin volver a imprimir el aviso: `preparar.unidades` ya lo dio
    recortadas = {n for n, geom in uds
                  if preparar.recortada_por_la_caja(cfg, geom)}
    origen = _origen_de_las_unidades(cfg)

    w = np.zeros(len(g.nombres))
    w[0] = 1.0

    filas, geoms = [], []
    for nombre, linea in uds:
        sub, o, d, obs, t6 = _contexto(cfg, g, t, linea,
                                       con_componentes=False)
        costos = sub.costos(w)
        dist, pred = dijkstra(costos, directed=True, indices=o,
                              return_predecessors=True)
        cam = grafo.recorre(pred, o, d)
        if cam.size == 0:
            _explica_corte(cfg, sub, costos, o, d, nombre)

        xy = grafo.xy(sub.filcol[cam], t6)
        # El borde que importa es el de la VECINDAD de esta unidad, que es
        # donde el barrido va a poder buscar, no el del corredor completo.
        vecindad = np.zeros(sub.forma, dtype=bool)
        vecindad[sub.filcol[:, 0], sub.filcol[:, 1]] = True

        extremos = np.array([linea.coords[0][:2],
                             linea.coords[-1][:2]])
        largo_mod = metricas.longitud(xy)
        costo_obs, celdas = costo_de_seguir_el_trazado(
            cfg, g, t6, linea, w, extremos[0], extremos[1])
        costo_opt = float(dist[d])

        fila = {
            "unidad": nombre,
            "origen": origen.get(nombre, "registro"),
            "recortada_por_la_caja": nombre in recortadas,
            "nodos_vecindad": int(sub.n),
            "largo_observado_km": round(linea.length / 1000, 2),
            "largo_modelado_km": round(largo_mod / 1000, 2),
            "largo_recto_km": round(
                float(np.hypot(*(extremos[1] - extremos[0]))) / 1000, 2),
            "sinuosidad_observada": round(
                metricas.sinuosidad(linea.length, extremos), 2),
            "sinuosidad_modelada": round(
                metricas.sinuosidad(largo_mod, extremos), 2),
            "distancia_media_m": round(
                metricas.distancia_media_simetrica(xy, obs), 1),
            "frechet_m": round(metricas.frechet_discreta(xy, obs), 1),
            "razon_de_costo": (round(costo_obs / costo_opt, 3)
                               if costo_opt > 0 and np.isfinite(costo_obs)
                               else None),
            # Es un camino, o dos ramas cosidas? Una sinuosidad alta no lo
            # dice: un rodeo y una horquilla dan la misma.
            "autoproximidad_m": round(
                metricas.autoproximidad(obs, 1000.0), 1),
            "giro_maximo_grados": round(metricas.giro_maximo(
                np.asarray(linea.coords, dtype=np.float64)[:, :2]), 1),
            "franja_celdas": celdas,
            "toca_borde_de_la_vecindad": bool(
                metricas.toca_borde(sub.filcol[cam], vecindad)),
        }
        filas.append(fila)
        geoms.append({"unidad": nombre, "clase": "modelado",
                      "distancia_media_m": fila["distancia_media_m"],
                      "geometry": LineString(xy)})
        geoms.append({"unidad": nombre, "clase": "observado",
                      "distancia_media_m": 0.0, "geometry": linea})

    _tabla_revision(filas)

    ruta = cfg.dir_resultados / "revision_pendiente.gpkg"
    gpd.GeoDataFrame(geoms, crs=cfg.crs).to_file(
        ruta, layer="revision", driver="GPKG")
    print(f"\n  -> {ruta.relative_to(cfg.raiz)}  (modelado y observado, "
          "por unidad)")
    print("  Abrelo en QGIS sobre derivados/cop30.tif y MIRALO: pasa por")
    print("  donde pasaria un camino? cruza las quebradas por donde se")
    print("  puede cruzar? Eso no lo dice ninguna tabla.")
    _guarda_json(cfg, "revision_grafo.json", filas)
    return filas


def _tabla_revision(filas) -> None:
    """La tabla que se mira antes de gastar media hora en nulos."""
    print(f"\n  {'unidad':31s} {'obs':>6s} {'mod':>6s} {'recto':>6s} "
          f"{'sinu':>9s} {'D':>7s} {'Frechet':>8s} {'costo':>6s}")
    for f in filas:
        marcas = ("*" if f["recortada_por_la_caja"] else " ") \
            + ("B" if f["toca_borde_de_la_vecindad"] else " ")
        razon = f["razon_de_costo"]
        print(f"  {f['unidad'][:31]:31s} {f['largo_observado_km']:6.2f} "
              f"{f['largo_modelado_km']:6.2f} {f['largo_recto_km']:6.2f} "
              f"{f['sinuosidad_observada']:4.2f}/{f['sinuosidad_modelada']:4.2f} "
              f"{f['distancia_media_m']:7.1f} {f['frechet_m']:8.1f} "
              f"{'  n/d' if razon is None else f'{razon:6.2f}'}  {marcas}")
    print("  (km, km, km, obs/mod, metros, metros, razon)")

    print("\n  'recto'  distancia en linea recta entre los dos extremos.")
    print("  'sinu'   largo entre esa recta, observado / modelado. Si el")
    print("           observado da mucha mas vuelta que el modelado, el")
    print("           camino real rodea algo que el modelo no ve.")
    print("  'costo'  LO QUE DECIDE COMO LEER LA D: cuanto cuesta, para este")
    print("           modelo, seguir el trazado observado, dividido por lo que")
    print("           cuesta su propio optimo.")
    print("             ~1.0  el modelo NO distingue las dos rutas: cuestan")
    print("                   casi lo mismo. La D grande mide la anchura del")
    print("                   valle, no un error. Es equifinalidad espacial,")
    print("                   y el remedio no es otro modelo sino decirlo.")
    print("             >>1   el camino real pasa por donde este modelo lo")
    print("                   considera caro. Ahi si falta algo.")

    if any(f["recortada_por_la_caja"] for f in filas):
        print("\n  *  recortada por la caja: uno de sus extremos no es un")
        print("     destino sino donde cortamos. Su D vale menos que la de")
        print("     una unidad completa.")
    if any(f["toca_borde_de_la_vecindad"] for f in filas):
        print("\n  B  el camino modelado se pego al borde de su vecindad: es")
        print("     el buffer el que esta decidiendo, no el terreno. Sube")
        print("     'dominio.buffer_corredor' y vuelve a correr desde aqui.")

    print(f"\n  --- es UN camino, o dos ramas cosidas? ---")
    print(f"  {'unidad':31s} {'autoprox':>9s} {'giro max':>9s}")
    for f in filas:
        prox = f["autoproximidad_m"]
        print(f"  {f['unidad'][:31]:31s} "
              f"{'   > 1 km' if prox > 1000 else f'{prox:8.0f} m'} "
              f"{f['giro_maximo_grados']:8.0f} g")
    print("  autoprox  lo mas cerca que pasa la linea de SI MISMA, entre")
    print("            puntos separados por mas de 1 km de recorrido. Un")
    print("            rodeo real se aleja de si mismo (cientos de metros o")
    print("            mas); una horquilla cosida por `linemerge` vuelve")
    print("            sobre si misma y baja a decenas de metros.")
    print("  giro max  el giro mas brusco entre segmentos. Ni una herradura")
    print("            pasa de 150 grados: mas que eso es una inversion, o")
    print("            sea donde se unieron dos cosas distintas.")

    _avisa_de_la_geometria(filas)

    completas = [f for f in filas if not f["recortada_por_la_caja"]
                 and not f["toca_borde_de_la_vecindad"]]
    if completas:
        d = np.array([f["distancia_media_m"] for f in completas])
        print(f"\n  En las {len(completas)} unidad(es) limpias, D mediana = "
              f"{np.median(d):.0f} m "
              f"({np.median(d) / 30:.1f} celdas de 30 m).")
    else:
        print("\n  NINGUNA unidad esta limpia: todas estan recortadas por la")
        print("  caja o pegadas al borde de su vecindad. Arregla eso antes")
        print("  de interpretar pesos.")


def _avisa_de_la_geometria(filas, cerca_m: float = 150.0,
                           giro_max: float = 150.0) -> list[str]:
    """Senala las unidades cuyo trazado puede no ser UN camino.

    `preparar.unidades` toma la pieza continua mayor que devuelve
    `linemerge`, y linemerge cose por vertices compartidos. Si un tramo del
    registro tiene una horquilla, la "pieza mayor" puede ser una rama que
    sube y otra que baja unidas por un vertice: los dos extremos de la
    unidad serian los dos cabos de una Y, y ajustar un modelo de costo
    contra eso no significa nada.

    No se excluye nada: se dice, y se mira en QGIS. Puede ser un rodeo real,
    que es un hallazgo, o una union espuria, que es un problema del dato.
    """
    avisos = []
    for f in filas:
        # UN RECORRIDO GRABADO NO ESTA COSIDO POR NADIE.
        #
        # Esta comprobacion busca uniones espurias de `linemerge`: en el
        # registro, la "pieza mayor" de un tramo con horquilla puede ser una
        # rama de ida pegada a una de vuelta, y ajustar un costo contra eso no
        # significa nada. Un track grabado no tiene ese problema: viene en
        # orden de tiempo y cada vertice se piso de verdad.
        #
        # Y ahi una inversion de 176 grados es un DATO, no un defecto: la
        # gente se devolvio. El circuito de Qoyllur Rit'i da justo eso, y sin
        # esta salida el aviso suena en cada corrida sobre la unidad principal
        # -- que es la peor manera de tener un aviso, porque se aprende a
        # ignorarlo.
        if f.get("origen") == "trayectoria":
            if f["giro_maximo_grados"] > giro_max:
                print(f"\n  {f['unidad'][:44]} se devuelve sobre si misma "
                      f"({f['giro_maximo_grados']:.0f} grados de giro,")
                print(f"  pasa a {f['autoproximidad_m']:.0f} m de si misma). "
                      "En un recorrido grabado eso no es")
                print("  un defecto de geometria: es parte del recorrido, y "
                      "vale preguntarse donde")
                print("  y por que se devolvio.")
            continue
        motivos = []
        if f["autoproximidad_m"] < cerca_m:
            motivos.append(
                f"pasa a {f['autoproximidad_m']:.0f} m de si misma entre "
                "puntos separados por mas de 1 km de recorrido")
        if f["giro_maximo_grados"] > giro_max:
            motivos.append(
                f"tiene un giro de {f['giro_maximo_grados']:.0f} grados, o "
                "sea una inversion")
        if motivos:
            avisos.append(f"{f['unidad']}: " + "; ".join(motivos))

    if avisos:
        print("\n  AVISO DE GEOMETRIA -- puede que esto no sea UN camino:")
        for a in avisos:
            print(f"    {a}")
        print("    `linemerge` cose por vertices compartidos, asi que la")
        print("    pieza mayor de un tramo con horquilla puede ser una rama")
        print("    de ida y otra de vuelta. Miralo en QGIS antes de creerte")
        print("    su sinuosidad o su razon de costo.")
    return avisos


def _origen_de_las_unidades(cfg) -> dict:
    """De donde salio el camino de cada unidad: 'registro' o 'trayectoria'.

    Varios diagnosticos solo tienen sentido para uno de los dos casos, y
    hacerlos depender de la geometria seria adivinar. La columna la pone
    `trayectoria.como_camino`.
    """
    import geopandas as gpd

    ruta = cfg.dir_datos / "qn_geocam.gpkg"
    if not ruta.exists():
        return {}
    try:
        qn = gpd.read_file(ruta, layer="camino")
    except Exception:
        return {}
    if "origen" not in qn.columns or "tramnomb" not in qn.columns:
        return {}
    return {str(k): str(v) for k, v in
            zip(qn["tramnomb"], qn["origen"].fillna("registro"))}


def _explica_corte(cfg, sub, costos, o, d, nombre) -> None:
    """Por que no hay camino, con el diagnostico en la mano."""
    from scipy.sparse.csgraph import connected_components

    n_comp, etiqueta = connected_components(costos, directed=True,
                                            connection="weak")
    tamanos = np.bincount(etiqueta)
    co, cd = int(etiqueta[o]), int(etiqueta[d])
    raise SystemExit(
        f"No hay camino entre los extremos de '{nombre}'.\n"
        f"  la vecindad tiene {sub.n} nodos en {n_comp} componentes conexas\n"
        f"  origen  -> componente {co} ({tamanos[co]} nodos)\n"
        f"  destino -> componente {cd} ({tamanos[cd]} nodos)\n"
        + ("\nEstan en COMPONENTES DISTINTAS: el dominio esta partido y no "
           "hay\nmanera de ir de uno a otro. Causas habituales:\n"
           "  - una laguna enmascarada que corta el corredor de lado a lado\n"
           "  - g_max demasiado bajo: un cuello de roca donde todas las "
           "aristas\n    superan la pendiente maxima\n"
           "  - el corredor demasiado estrecho en un paso: sube "
           "'buffer_corredor'\n"
           if co != cd else
           "\nEstan en la MISMA componente, asi que el corte no es de "
           "conectividad.\nRevisa que los extremos no caigan sobre celdas "
           "enmascaradas.\n")
        + "\nMira derivados/mascara.tif en QGIS: se ve de un vistazo donde "
          "se corta.")


def _contexto(cfg, g, t, geometria, puntos_sitios=None,
              con_componentes: bool = True):
    """Prepara una unidad: subgrafo, extremos, camino observado.

    El subgrafo es la clave. Cada unidad se analiza en SU vecindad, no sobre
    el corredor entero: el nulo de un tramo tiene que preguntar "una ruta
    cualquiera POR AQUI, se habria parecido tanto?", y ademas un Dijkstra
    cuesta con el tamano del grafo.

    Aqui tambien se rellenan las componentes que dependen de la unidad. La
    regla del proyecto es la misma para las dos componentes de sitios:
    excluir los que caen en los extremos del tramo, porque si no el modelo
    recibe como premio acercarse (o ver) un punto al que tiene que llegar de
    todas formas, y la componente mide el enunciado en vez del paisaje.
    """
    t6 = tuple(t)[:6]
    nodos = g.nodos_cerca_de(geometria, t6, cfg.buffer_corredor)
    sub = g.subconjunto(nodos)

    # El nulo reescribe TODOS los costos de arista, asi que no necesita
    # las componentes: pedirlas ahi solo obligaria a tener sitios para
    # correr un test que no los usa.
    de_sitios = [c for c in ("ceremonial", "visibilidad") if c in sub.nombres]
    if con_componentes and de_sitios:
        if puntos_sitios is None or len(puntos_sitios) == 0:
            raise SystemExit(
                f"El modelo ampliado incluye {de_sitios} pero no hay sitios.\n"
                "Deja un archivo que empiece por 'sitios' en datos/ (shapefile,"
                "\nGeoPackage, KMZ o CSV con lon/lat), o quita esas componentes"
                "\nde 'costo.componentes_ampliado' en config.yaml.")
        usables, quitados = sitios.sin_los_extremos(
            puntos_sitios, geometria, cfg.ceremonial_radio_extremos)
        if len(usables) == 0:
            raise SystemExit(
                "Al excluir los sitios de los extremos no queda ninguno para "
                "esta unidad.")
        if quitados:
            print(f"      ({quitados} sitio(s) en los extremos, excluidos)")

        xy_nodos = sub.xy_nodos(t6)
        if "ceremonial" in de_sitios:
            prox = superficies.proximidad(usables, xy_nodos, sub.forma,
                                          cfg.ceremonial_saturacion)
            sub.fija_componente("ceremonial", prox + cfg.epsilon)
        if "visibilidad" in de_sitios:
            objetivos = np.vstack([usables, sitios.puntos_de_config(cfg)])
            frac, info = visibilidad.fraccion_visible(
                _dem(cfg), t6, objetivos, xy_nodos, cfg.visibilidad_radio,
                cfg.altura_observador, cfg.altura_objetivo)
            sub.fija_componente("visibilidad",
                                visibilidad.costo(frac) + cfg.epsilon)
            print(f"      visibilidad: {info['sitios_usados']} objetivos, "
                  f"{100 * info['fraccion_media']:.1f}% visible en promedio")

    fc = preparar.filcol_de_xy(
        np.array([geometria.coords[0], geometria.coords[-1]]), t)
    o = sub.nodo_mas_cercano(*fc[0])
    d = sub.nodo_mas_cercano(*fc[1])
    obs = preparar.vertices(geometria, paso=cfg.resolucion)
    return sub, o, d, obs, t6


def _exige_sitios_o_explica(cfg) -> None:
    """Para ANTES del bucle si falta el archivo de sitios.

    Antes reventaba dentro de la primera unidad, despues de haber cargado el
    grafo y empezado a trabajar. El error era el mismo pero llegaba tarde.

    Y dice lo que de verdad conviene hacer, que no es poner
    'componentes_ampliado: [fisico]': con una sola componente el simplex es
    un punto, el barrido es un unico Dijkstra, y ese numero ya lo imprimio
    `revisar` en la columna D. No aporta nada.
    """
    de_sitios = [c for c in cfg.componentes_ampliado
                 if c in ("ceremonial", "visibilidad")]
    if not de_sitios:
        return
    raise SystemExit(
        f"\nEl modelo ampliado incluye {de_sitios} y no hay archivo de "
        "sitios.\n"
        "\nDeja en datos/ un archivo que empiece por 'sitios' (.gpkg, .shp,\n"
        ".geojson, .kmz o .csv con columnas lon/lat). Con eso corre.\n"
        "\nLo que NO conviene es quitar las componentes para que pase:\n"
        "con una sola componente el simplex es un punto, el barrido es un\n"
        "unico Dijkstra, y ese numero ya esta en la columna D de `revisar`.\n"
        "El barrido sin sitios no aporta nada que no tengas.\n"
        "\nLo que ya tienes cerrado SIN los sitios: la tabla de `revisar` y\n"
        "el nulo de costo de `nulos`. Eso es un resultado completo sobre el\n"
        "costo fisico. Lo que falta es la pregunta del espacio ceremonial,\n"
        "y esa necesita el catalogo.")


def _modelos_iguales(cfg) -> bool:
    """True si los dos modelos son el mismo, y lo dice.

    Pasa cuando se deja 'componentes_ampliado: [fisico]' para probar la
    cadena sin archivo de sitios. Es legitimo, pero entonces comparar los
    dos modelos no significa nada, y hay que decirlo: si no, `validar`
    imprime "no hay evidencia de que las componentes anadidas aporten" --
    que es cierto y enganoso a la vez, porque no se anadio ninguna.
    """
    iguales = set(cfg.componentes_referencia) == set(cfg.componentes_ampliado)
    if iguales:
        print("\n  OJO: los dos modelos tienen las MISMAS componentes "
              f"({list(cfg.componentes_referencia)}),")
        print("  asi que son el mismo modelo y compararlos no dice nada. Esto")
        print("  sirve para probar la cadena, no para responder la pregunta.")
        print("  Para el modelo ampliado de verdad, anade 'ceremonial' (y si")
        print("  quieres 'visibilidad') a costo.componentes_ampliado y deja un")
        print("  archivo de sitios en datos/.")
    return iguales


def red_del_modelo(cfg, nombres, componentes):
    """Red del simplex de un modelo, expandida a las K columnas del grafo.

    Un modelo que no usa una componente la lleva con peso 0. Asi los dos
    modelos comparten exactamente el mismo grafo y el mismo espacio de
    transito, y el de referencia es literalmente el caso restringido del
    ampliado.
    """
    idx = [nombres.index(c) for c in componentes]
    chica = barrido.red_simplex(len(idx), cfg.n_simplex)
    red = np.zeros((len(chica), len(nombres)), dtype=np.float64)
    red[:, idx] = chica
    return red


def _carga_unidades(cfg):
    """Grafo, transform y la lista de unidades a comparar."""
    import geopandas as gpd
    preparar.comprueba_rejilla(cfg)
    g = grafo.Grafo.cargar(cfg.dir_derivados / "grafo.npz")
    t = preparar.rejilla(cfg)[0]
    camino = gpd.read_file(cfg.dir_datos / "qn_geocam.gpkg", layer="camino")
    uds = preparar.unidades(cfg, camino)
    print(f"  unidad de analisis: {cfg.unidad} ({len(uds)})")
    for nombre, geom in uds:
        print(f"    {nombre[:38]:38s} {geom.length / 1000:6.2f} km")
    return g, t, uds


# ------------------------------------------- 5. nulos, antes del barrido

def correr_nulos(cfg):
    """Un nulo por unidad, con el espectro de la superficie real.

    Sale ANTES del barrido: las unidades que no le ganan al nulo quedan
    fuera del analisis de pesos y se reportan como tales.

    DOS NULOS, no uno, porque hay dos preguntas distintas:

    1. GEOMETRIA. Las M rutas aleatorias, cuanto se parecen al trazado
       observado? Es la distribucion de D con la que se compara la D del
       modelo. Responde "el modelo acierta la posicion mejor que el azar?".

    2. COSTO. Esas mismas M rutas -- que son el conjunto de control de rutas
       fisicamente plausibles que pide el proyecto, generadas sobre terreno
       con la misma autocorrelacion que el real-- cuanto cuestan PARA EL
       MODELO DE REFERENCIA? Responde la pregunta que la razon de costo deja
       abierta: 1.45 es mucho o poco? Si las rutas plausibles cuestan 3 o 4
       veces el optimo, que el camino real cueste 1.45 dice algo; si tambien
       cuestan 1.4, no dice nada.

    El segundo sale casi gratis: las rutas ya estan generadas, solo hay que
    evaluarles el costo real a lo largo.
    """
    from scipy.sparse.csgraph import dijkstra

    g, t, uds = _carga_unidades(cfg)
    # El exponente espectral se estima sobre una superficie de TERRENO
    # real (la rugosidad), no sobre una componente del costo: lo que el
    # nulo tiene que conservar es la autocorrelacion espacial del paisaje.
    ref = preparar.lee(cfg.dir_derivados / "rugosidad.tif")[0]
    beta = nulos.beta_espectral(ref)
    print(f"  exponente espectral de la superficie real: beta = {beta:.2f}")

    w_ref = np.zeros(len(g.nombres))
    w_ref[0] = 1.0

    rng = np.random.default_rng(cfg.semilla)
    salida, razones_nulas, razones_obs = {}, {}, {}
    for nombre, geom in uds:
        sub, o, d, obs, t6 = _contexto(cfg, g, t, geom, con_componentes=False)

        # El modelo de referencia sobre esta unidad: su optimo y lo que
        # cuesta seguir el trazado observado. Se guarda ANTES de que el
        # bucle del nulo pise `sub._csr.data`.
        reales = sub.costos(w_ref).copy()
        optimo = float(dijkstra(reales, directed=True, indices=o)[d])
        extremos = np.array([geom.coords[0][:2], geom.coords[-1][:2]])
        costo_obs, _ = costo_de_seguir_el_trazado(
            cfg, g, t6, geom, w_ref, extremos[0], extremos[1])
        razones_obs[nombre] = (costo_obs / optimo if optimo > 0 else np.nan)

        ds = np.full(cfg.m_nulos, np.inf)
        rs = np.full(cfg.m_nulos, np.nan)
        for m in range(cfg.m_nulos):
            sub._csr.data[:] = sub.L * _nulo_por_arista(sub, beta, rng, cfg)
            _, pred = dijkstra(sub._csr, directed=True, indices=o,
                               return_predecessors=True)
            cam = grafo.recorre(pred, o, d)
            if cam.size:
                # lo que esa ruta plausible le cuesta al modelo REAL
                if optimo > 0:
                    rs[m] = grafo.costo_a_lo_largo(reales, cam) / optimo
                ds[m] = metricas.distancia_media_simetrica(
                    grafo.xy(sub.filcol[cam], t6), obs)
        salida[nombre] = ds
        razones_nulas[nombre] = rs
        print(f"    {nombre[:38]:38s} nulo mediano {np.nanmedian(ds):6.0f} m "
              f"({sub.n} nodos)")

    _tabla_nulo_de_costo(razones_obs, razones_nulas)

    np.savez_compressed(
        cfg.dir_derivados / "nulos.npz", beta=beta, **salida,
        **{f"razon__{k}": v for k, v in razones_nulas.items()},
        **{f"razonobs__{k}": np.array([v]) for k, v in razones_obs.items()})
    return salida


def _tabla_nulo_de_costo(razones_obs, razones_nulas) -> dict:
    """El nulo de COSTO: el camino real es barato entre lo plausible?

    Da la referencia que la razon de costo no tiene por si sola. Si las
    rutas plausibles cuestan 3 veces el optimo y el camino real cuesta 1.45,
    el camino real es barato. Si tambien cuestan 1.4, la razon no informa.

    El valor p es la fraccion de rutas plausibles que cuestan IGUAL O MENOS
    que el trazado observado, con el (+1)/(M+1) de rigor. p chico = el
    camino real es mas barato que casi cualquier alternativa, o sea el
    trazado es sensible al costo fisico.
    """
    print("\n  --- nulo de COSTO: el trazado real es barato entre las rutas "
          "plausibles? ---")
    print(f"  {'unidad':31s} {'r_obs':>6s} {'nulo p25/med/p75':>20s} "
          f"{'p':>7s}")
    salida = {}
    for nombre, r_obs in razones_obs.items():
        rs = razones_nulas[nombre]
        buenas = rs[np.isfinite(rs)]
        if not np.isfinite(r_obs) or buenas.size == 0:
            print(f"  {nombre[:31]:31s} {'n/d':>6s}")
            continue
        q = np.percentile(buenas, [25, 50, 75])
        p = (int((buenas <= r_obs).sum()) + 1) / (buenas.size + 1)
        salida[nombre] = {"r_observada": float(r_obs),
                          "nulo_p25": float(q[0]), "nulo_mediana": float(q[1]),
                          "nulo_p75": float(q[2]), "p": float(p),
                          "m_validos": int(buenas.size)}
        print(f"  {nombre[:31]:31s} {r_obs:6.2f} "
              f"{q[0]:6.2f}/{q[1]:5.2f}/{q[2]:5.2f} {p:7.4f}")

    print("\n  r_obs  lo que cuesta seguir el trazado real, entre lo que")
    print("         cuesta el optimo del modelo de referencia.")
    print("  nulo   lo mismo para las rutas aleatorias sobre terreno con la")
    print("         misma autocorrelacion: el conjunto de control.")
    print("  p      fraccion de rutas plausibles que cuestan igual o menos")
    print("         que la real. p chico = el trazado real es barato, o sea")
    print("         sensible al costo fisico. p alto = no se distingue de")
    print("         una ruta cualquiera por aqui.")
    return salida


def _nulo_por_arista(g, beta, rng, cfg):
    """Una superficie nula convertida a costo por arista.

    El campo se genera sobre la rejilla completa y se promedia entre los dos
    extremos de cada arista, igual que una componente simetrica real: asi el
    nulo tiene la misma estructura que lo que se esta probando.
    """
    campo = nulos.superficie_nula(g.forma, beta, rng, cfg.epsilon, cfg.percentiles)
    plano = campo.ravel()
    org = g.filcol[:, 0] * g.forma[1] + g.filcol[:, 1]
    valor = np.empty(g.n)
    valor[:] = plano[org]
    filas = np.repeat(np.arange(g.n), np.diff(g._csr.indptr))
    return 0.5 * (valor[filas] + valor[g._csr.indices])


# -------------------------------------------------------- 6. el barrido

def barrer(cfg):
    """Corre los DOS modelos sobre cada unidad y los compara.

    El de referencia es el caso restringido: solo costo fisico. El ampliado
    anade las componentes extra. Mismo grafo, mismos extremos, mismas
    restricciones -- la unica diferencia son las componentes, que es lo que
    permite atribuirle a ellas lo que cambie.

    Aviso que el proyecto hace explicito: que el ampliado ajuste mejor
    sobre los MISMOS datos con que se estimaron sus pesos no es evidencia.
    Tiene mas parametros, asi que ajustara mejor por construccion. La
    prueba esta en `validar`, sobre bloques retenidos.
    """
    import geopandas as gpd
    from shapely.geometry import LineString

    g, t, uds = _carga_unidades(cfg)
    _modelos_iguales(cfg)
    puntos, nombres_sitios = sitios.carga(cfg)
    if len(puntos):
        print(f"  sitios ceremoniales: {len(puntos)}")
    else:
        _exige_sitios_o_explica(cfg)

    redes = {m: red_del_modelo(cfg, g.nombres, comps)
             for m, comps in cfg.modelos.items()}
    for m, red in redes.items():
        print(f"  {m}: {list(cfg.modelos[m])} -> {len(red)} vectores de peso")

    nul = {}
    ruta_nulos = cfg.dir_derivados / "nulos.npz"
    if ruta_nulos.exists():
        nul = dict(np.load(ruta_nulos))

    D_por_unidad, tablas, geoms = {}, [], []
    for nombre, geom in uds:
        print(f"\n  {nombre}  ({geom.length / 1000:.2f} km)")
        sub, o, d, obs, t6 = _contexto(cfg, g, t, geom, puntos)
        fila = {"unidad": nombre, "largo_km": round(geom.length / 1000, 2)}

        for modelo, red in redes.items():
            D, largos, caminos = barrido.barre(sub, red, o, d, obs, t6,
                                               n_trabajos=cfg.n_trabajos)
            i_opt, w = barrido.optimo(D, red)
            fila[f"D_{modelo}_m"] = round(float(D[i_opt]), 1)
            for nom, v in zip(g.nombres, w):
                if v > 0 or modelo == "ampliado":
                    fila[f"w_{nom}_{modelo}"] = round(float(v), 2)
            # la Frechet del optimo: la segunda metrica que pide el proyecto
            cam = caminos[i_opt]
            if cam.size >= 2:
                xy = grafo.xy(sub.filcol[cam], t6)
                fila[f"frechet_{modelo}_m"] = round(
                    metricas.frechet_discreta(xy, obs), 1)
                geoms.append({"unidad": nombre, "modelo": modelo,
                              "D_media_m": round(float(D[i_opt]), 1),
                              "geometry": LineString(xy)})
            if modelo == "ampliado":
                D_por_unidad[nombre] = D
                m10 = equifinalidad.conjunto_casi_optimo(D, 0.10)
                fila["casi_optimos_tau10"] = int(m10.sum())
                for k, nom in enumerate(g.nombres):
                    lo, hi = equifinalidad.extension(red, m10)[k]
                    fila[f"{nom}_tau10"] = f"{lo:.2f}-{hi:.2f}"
            if nombre in nul and modelo == "referencia":
                fila["p_nulo"] = round(nulos.p_empirico(
                    float(np.nanmin(D)), nul[nombre]), 4)

        ref, amp = fila.get("D_referencia_m"), fila.get("D_ampliado_m")
        if ref and amp:
            fila["mejora_pct"] = round(100 * (ref - amp) / ref, 1)
        geoms.append({"unidad": nombre, "modelo": "observado",
                      "D_media_m": 0.0, "geometry": geom})
        tablas.append(fila)
        print(f"    {fila}")

    np.savez_compressed(cfg.dir_derivados / "barrido.npz",
                        red=redes["ampliado"], **D_por_unidad)
    _guarda_json(cfg, "optimos_por_unidad.json", tablas)

    if geoms:
        ruta = cfg.dir_resultados / "caminos_optimos.gpkg"
        gpd.GeoDataFrame(geoms, crs=cfg.crs).to_file(
            ruta, layer="caminos", driver="GPKG")
        print(f"\n  -> {ruta.relative_to(cfg.raiz)}  "
              "(modelado por modelo, mas el observado)")
    print("\n  OJO: la mejora del ampliado sobre estos mismos datos NO es")
    print("  evidencia -- tiene mas parametros. Corre:  python -m camino validar")
    return D_por_unidad, redes["ampliado"]


def validar(cfg, n_bloques: int | None = None):
    """Validacion espacial bloqueada: la prueba que decide.

    Los pesos se estiman excluyendo un bloque contiguo del trazado y se
    evaluan SOBRE ESE BLOQUE RETENIDO, sin recalibrar. Se repite para cada
    bloque.

    Por que asi y no con una particion aleatoria: puntos espacialmente
    proximos comparten terreno, asi que repartirlos al azar entre ajuste y
    prueba filtra informacion y el modelo parece generalizar cuando solo
    esta recordando. Los bloques tienen que ser contiguos.

    Y por que importa: el modelo ampliado tiene mas parametros, asi que
    ajusta mejor sobre los datos con que se estimo POR CONSTRUCCION. Si no
    gana tambien en los bloques retenidos, la mejora era capacidad de
    ajuste y no informacion espacial.
    """
    from shapely.ops import substring

    n_bloques = cfg.n_bloques if n_bloques is None else n_bloques
    iguales = _modelos_iguales(cfg)
    puntos, _ = sitios.carga(cfg)
    if not len(puntos):
        # Sin esto va omitiendo bloque por bloque y acaba en "ninguna unidad
        # dio para validar", que no dice cual es el problema.
        _exige_sitios_o_explica(cfg)
    g, t, uds = _carga_unidades(cfg)
    redes = {m: red_del_modelo(cfg, g.nombres, comps)
             for m, comps in cfg.modelos.items()}

    filas = []
    for nombre, geom in uds:
        largo = geom.length
        if largo / n_bloques < cfg.largo_min_bloque:
            print(f"  {nombre}: {largo/1000:.1f} km no dan para {n_bloques} "
                  f"bloques de {cfg.largo_min_bloque:g} m; se omite")
            continue
        bloques = [substring(geom, largo * k / n_bloques,
                             largo * (k + 1) / n_bloques)
                   for k in range(n_bloques)]
        print(f"\n  {nombre}: {n_bloques} bloques de "
              f"{largo/n_bloques/1000:.2f} km")

        contextos = []
        for b in bloques:
            try:
                contextos.append(_contexto(cfg, g, t, b, puntos))
            except SystemExit as e:
                print(f"    bloque omitido: {e}")
                contextos.append(None)

        for modelo, red in redes.items():
            # D[bloque, peso]
            D = np.full((len(bloques), len(red)), np.nan)
            for k, ctx in enumerate(contextos):
                if ctx is None:
                    continue
                sub, o, d, obs, t6 = ctx
                D[k], _, _ = barrido.barre(sub, red, o, d, obs, t6,
                                           n_trabajos=cfg.n_trabajos)
            for k in range(len(bloques)):
                otros = [x for x in range(len(bloques)) if x != k]
                if np.isnan(D[k]).all() or np.isnan(D[otros]).all():
                    continue
                # pesos estimados SIN el bloque k
                medio = np.nanmean(D[otros], axis=0)
                i_opt = int(np.nanargmin(medio))
                filas.append({
                    "unidad": nombre, "modelo": modelo, "bloque": k + 1,
                    "D_ajuste_m": round(float(medio[i_opt]), 1),
                    "D_retenido_m": round(float(D[k, i_opt]), 1),
                    **{f"w_{n}": round(float(v), 2)
                       for n, v in zip(g.nombres, red[i_opt])},
                })

    if not filas:
        raise SystemExit("ninguna unidad dio para validar en bloques")

    _guarda_json(cfg, "validacion_bloqueada.json", filas)
    _resumen_validacion(filas, comparables=not iguales)
    return filas


def _resumen_validacion(filas, comparables: bool = True) -> dict:
    """Compara los modelos SOBRE LOS BLOQUES RETENIDOS, que es lo que vale."""
    print("\n  --- sobre los bloques retenidos (sin recalibrar) ---")
    por_modelo = {}
    for f in filas:
        por_modelo.setdefault(f["modelo"], []).append(f["D_retenido_m"])
    for modelo, ds in por_modelo.items():
        a = np.array(ds, dtype=float)
        print(f"  {modelo:12s} mediana {np.median(a):7.1f} m   "
              f"media {a.mean():7.1f} m   n = {len(a)}")

    if not comparables:
        print("\n  Los dos modelos son el mismo, asi que no hay comparacion")
        print("  que hacer. Las dos filas de arriba tienen que coincidir; si")
        print("  no coinciden, hay un bug.")
        return por_modelo

    if {"referencia", "ampliado"} <= set(por_modelo):
        pares = {}
        for f in filas:
            pares.setdefault((f["unidad"], f["bloque"]), {})[f["modelo"]] = \
                f["D_retenido_m"]
        comparables = [(v["referencia"], v["ampliado"]) for v in pares.values()
                       if {"referencia", "ampliado"} <= set(v)]
        if comparables:
            gana = sum(1 for r, a in comparables if a < r)
            print(f"\n  el ampliado gana en {gana} de {len(comparables)} "
                  "bloques retenidos")
            if gana <= len(comparables) / 2:
                print("  -> NO hay evidencia de que las componentes anadidas")
                print("     aporten informacion espacial. La mejora sobre los")
                print("     datos de ajuste era capacidad de ajuste.")
    return por_modelo


def sensibilidad_sectores(cfg, valores=(3, 4, 5, 6)):
    """Repite el barrido cortando el camino en distinto numero de sectores.

    Los sectores son cortes ARBITRARIOS de una linea continua: no
    corresponden a nada del terreno. Si "aqui manda la rugosidad" depende de
    donde cayo el corte, no es un hallazgo. Esta prueba es barata -- el
    barrido tarda menos de un minuto -- y es la que decide si la estructura
    por sectores se puede defender.

    Cada sector se situa por su POSICION a lo largo del camino (0 = inicio,
    1 = final), que es comparable entre particiones distintas; la etiqueta
    's3' no lo es.
    """
    import geopandas as gpd

    if cfg.unidad != "sector":
        raise SystemExit(
            "Esta prueba solo tiene sentido con 'unidad: sector'.\n"
            "Los tramos con nombre no los cortamos nosotros, asi que no hay "
            "corte\ndel que puedan depender: son unidades del registro.")

    g = grafo.Grafo.cargar(cfg.dir_derivados / "grafo.npz")
    t = preparar.rejilla(cfg)[0]
    camino = gpd.read_file(cfg.dir_datos / "qn_geocam.gpkg", layer="camino")
    red = barrido.red_simplex(len(g.nombres), cfg.n_simplex)

    filas = []
    for n in valores:
        try:
            secs = preparar.sectores(camino, n)
        except ValueError as e:
            print(f"  {n} sectores: {e}")
            continue
        print(f"  {n} sectores:", end=" ", flush=True)
        for k, (nombre, trozo) in enumerate(secs):
            sub, o, d, obs, t6 = _contexto(cfg, g, t, trozo)
            D, largos, _ = barrido.barre(sub, red, o, d, obs, t6,
                                         n_trabajos=cfg.n_trabajos)
            i, w = barrido.optimo(D, red)
            dominante = g.nombres[int(np.argmax(w))]
            filas.append({
                "n_sectores": n, "sector": nombre,
                "centro": round((k + 0.5) / n, 3),
                "desde": round(k / n, 3), "hasta": round((k + 1) / n, 3),
                "D_media_m": round(float(D[i]), 1),
                "dominante": dominante,
                **{nom: float(v) for nom, v in zip(g.nombres, w)},
            })
            print(dominante[:4], end=" ", flush=True)
        print()

    _guarda_json(cfg, "sensibilidad_sectores.json", filas)
    _figura_sensibilidad(cfg, filas, g.nombres)
    return filas


def _figura_sensibilidad(cfg, filas, nombres):
    from . import figuras
    ruta = figuras.sensibilidad(
        cfg.dir_resultados / "sensibilidad_sectores.png", filas, nombres,
        "La estructura por sectores NO sobrevive a recortar de otra manera"
        if _inestable(filas) else
        "La estructura por sectores se mantiene con otros cortes")
    print(f"  -> {ruta.relative_to(cfg.raiz)}")
    return ruta


def _inestable(filas, umbral: float = 0.75) -> bool:
    """True si las particiones discrepan sobre quien manda en cada sitio.

    El titulo de la figura dice lo que la figura muestra, no una pregunta.
    Para eso hay que mirar el dato: en cada posicion, que fraccion de las
    particiones coincide con la mayoria.
    """
    ns = sorted({f["n_sectores"] for f in filas})
    if len(ns) < 2:
        return False
    acuerdos = []
    for pos in np.linspace(0.001, 0.999, 200):
        votos = [f["dominante"] for n in ns for f in filas
                 if f["n_sectores"] == n and f["desde"] <= pos < f["hasta"]]
        if votos:
            acuerdos.append(max(votos.count(v) for v in set(votos)) / len(votos))
    return float(np.mean(acuerdos)) < umbral


def resultados(cfg):
    """El perfil de Jaccard: la respuesta a la pregunta del proyecto."""
    ruta = cfg.dir_derivados / "barrido.npz"
    if not ruta.exists():
        raise SystemExit(
            "Falta derivados/barrido.npz: este paso dibuja lo que el barrido\n"
            "calculo, y el barrido no ha terminado.\n"
            "\nCorre antes:  python -m camino barrido")
    d = np.load(ruta)
    red = d["red"]
    D_por_unidad = {k: d[k] for k in d.files if k != "red"}

    taus = np.linspace(0.0, cfg.tau_max, 26)
    taus, perfiles = equifinalidad.perfil_jaccard(D_por_unidad, taus)

    salida = {"taus": taus.tolist(), "pares": {}}
    for (s, t), j in perfiles.items():
        salida["pares"][f"{s}|{t}"] = j.tolist()
        print(f"  J({s},{t}): tau=0.05 -> {j[2]:.2f}   tau=0.25 -> {j[13]:.2f}")

    salida["centroides"] = {
        s: equifinalidad.centroide(
            red, equifinalidad.conjunto_casi_optimo(D, 0.10)).tolist()
        for s, D in D_por_unidad.items()}

    _guarda_json(cfg, "perfil_equifinalidad.json", salida)
    _figura_perfil(cfg, taus, perfiles)
    return salida


def _figura_perfil(cfg, taus, perfiles):
    from . import figuras
    ruta = figuras.perfil_jaccard(
        cfg.dir_resultados / "perfil_equifinalidad.png", taus, perfiles,
        f"Separacion de los conjuntos de pesos entre {cfg.unidad}s")
    print(f"  -> {ruta.relative_to(cfg.raiz)}")
    return ruta


def costo_de_seguir_el_trazado(cfg, g, t6, geometria, w, o_xy, d_xy,
                               anchos=(2, 3, 5, 8)):
    """Costo del modelo a lo largo del trazado OBSERVADO.

    Es la pieza que faltaba para interpretar la distancia geometrica. Una
    ruta puede estar lejos del optimo y costar casi lo mismo -- hay muchas
    maneras de cruzar un paisaje por un precio parecido-- o puede estar
    lejos y costar mucho mas. Las dos cosas dan la misma D y significan lo
    contrario:

      razon ~ 1    el modelo NO distingue el trazado real del suyo. El
                   terreno no decide por donde va el camino en esa unidad:
                   equifinalidad espacial, no un modelo equivocado. La D
                   grande mide la anchura del valle, no un error.

      razon >> 1   el camino real pasa por donde este modelo lo considera
                   caro. Ahi si falta algo: otra componente, o el trazado
                   responde a algo que no es el terreno.

    Se calcula como el camino de minimo costo RESTRINGIDO a una franja
    estrecha alrededor del trazado observado, que es la manera limpia de
    preguntar "cuanto cuesta ir por ahi" sin tener que resolver a que arista
    del grafo corresponde cada vertice del registro. Si la franja de una
    celda no conecta los extremos (el trazado pasa entre dos celdas, o roza
    una celda enmascarada), se ensancha y se reporta con cuanto se logro.
    """
    from scipy.sparse.csgraph import dijkstra
    from shapely.geometry import LineString

    # DENSIFICAR primero. `nodos_cerca_de` mide la distancia a los VERTICES
    # de la geometria, y las lineas del registro traen vertices cada cientos
    # de metros: sin remuestrear, la "franja" sale como islas alrededor de
    # cada vertice en vez de una banda continua, y no conecta nunca.
    denso = LineString(preparar.vertices(geometria, paso=cfg.resolucion / 2))

    for celdas in anchos:
        radio = celdas * cfg.resolucion
        nodos = g.nodos_cerca_de(denso, t6, radio)
        if len(nodos) < 2:
            continue
        franja = g.subconjunto(nodos)
        fc = preparar.filcol_de_xy(np.array([o_xy, d_xy]),
                                   __import__("rasterio").Affine(*t6))
        o = franja.nodo_mas_cercano(*fc[0])
        d = franja.nodo_mas_cercano(*fc[1])
        dist = dijkstra(franja.costos(w), directed=True, indices=o)
        if np.isfinite(dist[d]):
            return float(dist[d]), celdas
    return float("nan"), 0


# ------------------------------------------- la razon de costo y su franja

def razon_por_franja(cfg, anchos=(2, 3, 5, 8, 12)):
    """La razon de costo de cada unidad, en funcion del ANCHO DE LA FRANJA.

    `revisar` informa UNA razon por unidad, y lo hace con la franja mas
    estrecha que logre conectar los dos extremos: empieza en 2 celdas y
    ensancha solo si hace falta. Eso esta bien como numero unico, pero
    esconde que el numero depende del ancho, y el ancho no es neutral.

    Por que depende. La razon compara el costo de ir POR DONDE VA EL TRAZADO
    con el optimo libre. "Por donde va el trazado" se calcula resolviendo el
    optimo dentro de una franja alrededor de la linea observada, asi que:

      - franja estrecha -> el camino esta obligado a seguir el trazado de
        cerca, incluido su serpenteo, y la razon sale ALTA;
      - franja ancha -> el camino puede cortar las curvas por dentro, se
        parece cada vez mas al optimo libre, y la razon BAJA hacia 1.

    O sea el ancho es la escala a la que se pregunta. Una razon alta con
    franja ancha es un desvio de verdad: ni dandole 360 m de margen el
    modelo encuentra como pasar por ahi barato. Una razon que se desploma al
    ensanchar era serpenteo o un rodeo local.

    Esto importa especialmente con trazados GRABADOS. Una linea del registro
    viene digitalizada sobre imagen y es lisa; un track de GPS con un fix
    cada 16 s y hdop 3 baila, y ese baile sube la razon sin que corresponda
    a ninguna decision de quien caminaba. La tabla separa las dos cosas.

    Y tambien avisa de lo contrario: si una unidad NO conecta con 2 celdas
    pero si con 5, su razon de `revisar` se midio con una franja mas ancha
    que las demas y es, por construccion, mas baja. Comparar esa con las
    otras subestima su desvio.
    """
    import csv

    g, t, uds = _carga_unidades(cfg)
    w = np.zeros(len(g.nombres))
    w[0] = 1.0

    print(f"\n  La razon se mide resolviendo el optimo dentro de una franja")
    print(f"  alrededor del trazado. Franja de n celdas = {cfg.resolucion:g}n "
          "m de margen a cada lado.")

    filas = []
    for nombre, linea in uds:
        from scipy.sparse.csgraph import dijkstra
        sub, o, d, obs, t6 = _contexto(cfg, g, t, linea,
                                       con_componentes=False)
        dist = dijkstra(sub.costos(w), directed=True, indices=o)
        opt = float(dist[d])
        extremos = (np.array(linea.coords[0][:2]),
                    np.array(linea.coords[-1][:2]))
        fila = {"unidad": nombre, "largo_km": round(linea.length / 1000, 2),
                "optimo": round(opt, 1)}
        for n in anchos:
            c, usado = costo_de_seguir_el_trazado(
                cfg, g, t6, linea, w, extremos[0], extremos[1], anchos=(n,))
            fila[f"razon_{n}"] = (round(c / opt, 3)
                                  if usado and opt > 0 and np.isfinite(c)
                                  else None)
        filas.append(fila)

    cab = "  ".join(f"{'f' + str(n):>7s}" for n in anchos)
    print(f"\n  {'unidad':30s} {'km':>6s}   {cab}")
    for f in filas:
        vals = "  ".join(
            ("      -" if f[f'razon_{n}'] is None
             else f"{f[f'razon_{n}']:7.2f}") for n in anchos)
        print(f"  {f['unidad'][:30]:30s} {f['largo_km']:6.2f}   {vals}")

    print(f"\n  f{anchos[0]} es la franja mas estrecha; f{anchos[-1]} da "
          f"{cfg.resolucion * anchos[-1]:.0f} m de margen a cada lado.")
    print("  Un '-' quiere decir que con esa franja los extremos no se")
    print("  conectan: el trazado roza celda enmascarada o pasa entre dos.")

    estables, blandas = [], []
    for f in filas:
        v = [f[f"razon_{n}"] for n in anchos if f[f"razon_{n}"] is not None]
        if len(v) >= 2:
            caida = (v[0] - v[-1]) / v[0] if v[0] else 0.0
            (blandas if caida > 0.20 else estables).append(
                (f["unidad"], v[0], v[-1], caida))
    if estables:
        print("\n  AGUANTAN el ensanchado (menos de 20% de caida): el desvio")
        print("  es del recorrido y no de la escala.")
        for n, a, b, c in sorted(estables, key=lambda r: -r[2]):
            print(f"    {n[:34]:36s} {a:5.2f} -> {b:5.2f}  "
                  f"({100*c:+5.1f}%)")
    if blandas:
        print("\n  SE DESPLOMAN al ensanchar: ahi la razon alta era serpenteo")
        print("  del trazado o un rodeo local, no un desvio sostenido.")
        for n, a, b, c in sorted(blandas, key=lambda r: -r[3]):
            print(f"    {n[:34]:36s} {a:5.2f} -> {b:5.2f}  "
                  f"({100*c:+5.1f}%)")

    destino = cfg.dir_resultados / "razon_por_franja.csv"
    with open(destino, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(filas[0].keys()))
        wr.writeheader()
        wr.writerows(filas)
    print(f"\n  -> {destino.relative_to(cfg.raiz)}")
    _guarda_json(cfg, "razon_por_franja.json", filas)
    return filas
