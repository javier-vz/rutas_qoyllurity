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

FUENTES = ("auto", "geocam", "archivo", "osm")

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
        if ext in EXTENSIONES:
            candidatos.append((EXTENSIONES.index(ext), p.name, p))
    if not candidatos:
        return None
    return sorted(candidatos)[0][2]


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
        else:
            print("  no hay ningun archivo de geometria en datos/; pruebo GeoCAM")
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
