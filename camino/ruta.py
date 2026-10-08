"""De donde sale el camino observado.

GeoCAM es la fuente que corresponde, pero su servidor se cae, y cuando se
cae no hay nada que hacer desde aqui. El resto del estudio no tiene por que
quedarse parado por eso: esta parte acepta la geometria desde tres sitios.

    geocam    el servidor del Ministerio (WFS o ArcGIS REST). Lo correcto.
    archivo   un archivo tuyo: el GPX del Garmin de Dina, un KML, un
              shapefile, un GeoPackage, lo que tengas.
    osm       OpenStreetMap, como APAÑO PROVISIONAL para poder desarrollar
              y probar mientras GeoCAM no vuelve.

La de `osm` NO es el registro oficial y no puede sustituirlo en un
resultado publicable: son trazas cargadas por voluntarios, sin control de
precision ni criterio arqueologico. Sirve para que el codigo corra de punta
a punta y para ver si el modelo hace algo sensato; los numeros finales
salen de GeoCAM o de los tracks de campo.
"""

from __future__ import annotations

import json
import pathlib

import requests

FUENTES = ("auto", "geocam", "archivo", "osm", "trayectorias")

# Extensiones de geometria que se reconocen en datos/, por orden de
# preferencia: el KMZ/KML del registro trae las categorias del Ministerio y
# es lo mejor que puede haber; el GPX del Garmin es lo ultimo porque es una
# traza de campo, no el registro.
EXTENSIONES = (".kmz", ".kml", ".gpkg", ".shp", ".geojson", ".json", ".gpx")

# Archivos que produce el propio programa: no son fuentes de camino.
PROPIOS = ("qn_geocam.gpkg", "agua_osm.json", "tracks.gpkg")

# Extensiones que geopandas abre sin ayuda. El GPX trae varias capas y hay
# que decirle cual.
CAPAS_GPX = ("tracks", "routes", "track_points")


def desde_archivo(cfg, ruta):
    """Lee el camino de un archivo local y lo deja en el CRS de trabajo."""
    import geopandas as gpd
    import pandas as pd

    from . import registro

    ruta = pathlib.Path(ruta)
    if not ruta.exists():
        raise SystemExit(f"No encuentro el archivo: {ruta}")

    if ruta.suffix.lower() in (".kmz", ".kml"):
        return registro.lee(ruta, cfg.crs,
                            solo_observadas=cfg.solo_observadas,
                            capas_pedidas=cfg.capas_camino or None)

    if ruta.suffix.lower() == ".gpx":
        trozos = []
        for capa in CAPAS_GPX:
            try:
                g = gpd.read_file(ruta, layer=capa)
            except Exception:
                continue
            if len(g):
                g["capa_gpx"] = capa
                trozos.append(g)
            if capa in ("tracks", "routes") and trozos:
                break            # con lineas basta; los puntos son el plan B
        if not trozos:
            raise SystemExit(f"{ruta.name} no tiene ni tracks ni rutas")
        gdf = gpd.GeoDataFrame(pd.concat(trozos, ignore_index=True),
                               crs=trozos[0].crs)
    else:
        gdf = gpd.read_file(ruta)

    if gdf.crs is None:
        print("  AVISO: el archivo no dice en que CRS esta; asumo EPSG:4326")
        gdf = gdf.set_crs("EPSG:4326")
    return gdf.to_crs(cfg.crs)


def consulta_osm(bbox) -> str:
    """La consulta de Overpass para trazas que puedan ser el camino."""
    from . import osm
    return osm.consulta_camino(bbox)


def desde_osm(cfg, sesion=None):
    """Trazas de OpenStreetMap, como apano provisional."""
    from . import osm

    d = osm.consulta(osm.consulta_camino(cfg.bbox), sesion=sesion)
    g = osm.lineas(d, cfg.crs)

    if g.empty:
        raise SystemExit(
            "OpenStreetMap no tiene ninguna traza etiquetada como camino inca\n"
            "en esa caja. Queda importar un archivo propio:\n"
            "  python -m camino ruta --fuente archivo --archivo mi_camino.gpx")

    g["fuente"] = "osm_provisional"
    return g


def hay_trayectorias(cfg) -> bool:
    """Si hay tracks grabados en datos/trayectorias/."""
    carpeta = cfg.dir_datos / "trayectorias"
    return carpeta.is_dir() and any(carpeta.glob("*.gpx"))


def busca_archivo(cfg):
    """El mejor archivo de geometria que haya en datos/, o None.

    Existe para que no haya que acordarse de una opcion: si dejaste el KMZ
    del registro en la carpeta, el programa lo usa.
    """
    candidatos = []
    for p in sorted(cfg.dir_datos.iterdir()):
        if not p.is_file() or p.name in PROPIOS:
            continue
        ext = p.suffix.lower()
        if ext not in EXTENSIONES:
            continue
        if ext == ".gpx" and not _tiene_traza(p):
            # Un GPX de solo waypoints NO es un camino: son puntos sueltos.
            # Pasa de verdad -- los favoritos del GPS con las estaciones
            # planificadas viven en datos/-- y sin esto se tomaria como
            # geometria del camino observado y el estudio entero mediria
            # una nube de puntos.
            print(f"  ({p.name} solo trae waypoints, no es un camino)")
            continue
        candidatos.append((EXTENSIONES.index(ext), p.name, p))
    if not candidatos:
        return None
    return sorted(candidatos)[0][2]


def _tiene_traza(p) -> bool:
    """Si un GPX trae puntos de track o de ruta, y no solo waypoints."""
    import xml.etree.ElementTree as ET
    try:
        raiz = ET.parse(p).getroot()
    except ET.ParseError:
        return False
    gpx = "{http://www.topografix.com/GPX/1/1}"
    for etiqueta in (gpx + "trkpt", gpx + "rtept", "trkpt", "rtept"):
        if next(raiz.iter(etiqueta), None) is not None:
            return True
    return False


def filtra_tramo(cfg, qn):
    """Se queda con el tramo del registro que pide config.yaml.

    Antes de filtrar imprime el inventario completo, porque la decision de
    que tramo estudiar se toma mirando cuanto camino CONTINUO tiene cada
    uno, no cuantos kilometros suma.
    """
    from . import registro

    if "tramnomb" not in qn.columns:
        return qn                      # la fuente no trae tramos (GPX, OSM)

    inventario = registro.tramos(qn)
    if inventario:
        print("\n  --- tramos del registro dentro de la caja ---")
        print(f"  {'tramo':34s} {'rasgos':>6s} {'km':>8s} {'continuo':>9s}")
        for nombre, n, km, mayor in inventario:
            if cfg.unidad == "tramo":
                marca = " <--" if mayor >= cfg.largo_min_unidad else ""
            else:
                marca = " <--" if cfg.tramo and nombre == cfg.tramo else ""
            print(f"  {nombre[:34]:34s} {n:6d} {km:8.2f} {mayor:9.2f}{marca}")

    if cfg.unidad == "tramo":
        print("\n  unidad de analisis: TRAMO -- se comparan entre si los "
              f"tramos\n  con al menos {cfg.largo_min_unidad / 1000:.0f} km "
              "continuos. No se filtra a uno solo.")
        return qn

    if not cfg.tramo:
        return qn

    sel = qn[qn["tramnomb"] == cfg.tramo]
    if sel.empty:
        nombres = sorted({str(x) for x in qn["tramnomb"].dropna()})
        raise SystemExit(
            f"\nEl tramo '{cfg.tramo}' no aparece en la caja.\n"
            f"Los que hay: {nombres}\n"
            "Cambia 'tramo' en config.yaml, o dejalo vacio para usarlos todos.")
    print(f"\n  Filtrado al tramo '{cfg.tramo}': {len(sel)} rasgos")
    return sel.copy()


def importar(cfg, fuente: str = "auto", archivo=None, forzar: bool = False):
    """Deja el camino observado en datos/qn_geocam.gpkg, venga de donde venga."""
    from . import descarga

    destino = cfg.dir_datos / "qn_geocam.gpkg"
    if destino.exists() and not forzar:
        print(f"  ya esta: {destino.name}  (usa --forzar para rehacerlo)")
        return destino

    if fuente == "auto" and not archivo:
        hallado = busca_archivo(cfg)
        if hallado is not None:
            print(f"  encontrado en datos/: {hallado.name}")
            fuente, archivo = "archivo", hallado
        elif hay_trayectorias(cfg):
            # Si no hay archivo de geometria pero si hay tracks grabados, el
            # camino observado son ellos: es un proyecto de recorrido y no de
            # registro. Se dice en voz alta porque cambia QUE se compara.
            print("  no hay archivo de geometria, pero si datos/"
                  "trayectorias/:")
            print("  el camino observado sale de los tracks grabados")
            fuente = "trayectorias"
        else:
            print("  no hay ningun archivo de geometria en datos/; pruebo "
                  "GeoCAM")
            fuente = "geocam"
    elif fuente == "auto":
        fuente = "archivo"

    if fuente == "geocam":
        return descarga.camino_registrado(cfg, forzar=forzar)

    if fuente == "archivo":
        if not archivo:
            raise SystemExit("falta --archivo con la ruta del archivo a importar")
        print(f"  importando {archivo}")
        qn = desde_archivo(cfg, archivo)
    elif fuente == "osm":
        print("  bajando trazas de OpenStreetMap (APANO PROVISIONAL)")
        qn = desde_osm(cfg)
    elif fuente == "trayectorias":
        # Los tracks grabados COMO camino observado. Salen ya agrupados en
        # trechos continuos y con 'tramnomb', asi que de aqui en adelante el
        # pipeline no distingue este caso del registro.
        from . import trayectoria
        qn = trayectoria.camino_observado(cfg)
    else:
        raise SystemExit(f"fuente desconocida: {fuente}. Usa una de {FUENTES}")

    # ANTES de recortar: la dispersion de un grupo solo se ve en la geometria
    # completa. Una vez cortado por la caja, un grupo repartido por el pais
    # parece local.
    from . import registro as _registro
    qn, _ = _registro.aplica_exclusiones(cfg, qn)
    if qn.empty:
        raise SystemExit(
            "despues de aplicar 'datos.tramos_excluidos' no quedo nada")

    if fuente == "trayectorias":
        # UN RECORRIDO GRABADO NO SE RECORTA.
        #
        # Dos razones. La primera es de sentido: no se puede quitar un pedazo
        # de por donde camino alguien y seguir llamandolo su recorrido. Si una
        # parte cae fuera de la caja, el problema es la caja y hay que decirlo,
        # no cortar la linea en silencio.
        #
        # La segunda es tecnica y muerde fuerte: `gpd.clip` interseca, y la
        # interseccion de una polilinea NO SIMPLE con un rectangulo la NODIFICA
        # -- la parte en cada autointerseccion-- aunque el rectangulo la
        # contenga entera. Un recorrido que vuelve a pasar por un sitio es no
        # simple por definicion. En el circuito de Qoyllur Rit'i eso devolvia
        # tres piezas de 7.3, 0.0 y 13.2 km en lugar de una de 20.5, y
        # `unidades` se quedaba con la mayor.
        _avisa_si_sale_de_la_caja(cfg, qn)
    else:
        qn = descarga.recorta(qn, cfg)
        if qn.empty:
            raise SystemExit("no quedo nada dentro de la caja del tramo")

    qn = filtra_tramo(cfg, qn)
    qn.to_file(destino, layer="camino", driver="GPKG")
    descarga.resumen(qn)

    if fuente == "osm":
        print("\n  RECUERDA: esto es un apano para que el codigo corra.")
        print("  No es el registro del Ministerio y no vale para publicar.")
    return destino


def _avisa_si_sale_de_la_caja(cfg, qn) -> None:
    """Dice si algun trecho grabado se sale de la caja del estudio.

    No corta: avisa. Un trecho que se sale tiene un extremo o un pedazo sin
    terreno debajo, asi que su ruta optima se calcula contra un DEM con
    agujero y su razon de costo no vale. La decision es ensanchar la caja,
    y esa no la toma el codigo.
    """
    import geopandas as gpd
    from shapely.geometry import box

    caja = gpd.GeoSeries([box(*cfg.bbox)], crs="EPSG:4326").to_crs(cfg.crs)[0]
    malos = []
    for _, fila in qn.iterrows():
        fuera = fila.geometry.difference(caja)
        if not fuera.is_empty and fuera.length > cfg.resolucion:
            malos.append((str(fila.get("tramnomb", "?")), fuera.length))
    if not malos:
        return
    print("\n  AVISO: estos trechos se salen de la caja del estudio:")
    for nombre, largo in sorted(malos, key=lambda r: -r[1]):
        print(f"    {nombre[:38]:40s} {largo / 1000:6.2f} km fuera")
    print("  No se recortan -- recortar un recorrido grabado no significa")
    print("  nada-- pero ahi no hay terreno debajo y la razon de costo de")
    print("  esos trechos no vale. Ensancha el bbox y vuelve a correr desde")
    print("  'bajar', o quita esos tracks de datos/trayectorias/.")
