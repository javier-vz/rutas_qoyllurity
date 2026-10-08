"""Descarga de los insumos: DEM, camino registrado y cuerpos de agua.

La red de drenaje NO se descarga: se deriva del DEM en `hidrologia.py`.

Las URL se arman con funciones puras (`url_*`, `params_*`) para poder
probarlas sin red. Lo unico que toca internet es `baja()`.
"""

from __future__ import annotations

import math
import pathlib

import requests

OPENTOPOGRAPHY = "https://portal.opentopography.org/API/globaldem"
COPERNICUS_S3 = "https://copernicus-dem-30m.s3.amazonaws.com"

# Los DEM globales que cubren el area y se pueden bajar sin tramites.
DEMS = ("COP30", "AW3D30")


def tiles_copernicus(bbox) -> list[str]:
    """Nombres de los tiles de Copernicus GLO-30 que cubren la caja.

    El nombre lleva la esquina SUROESTE del tile de 1 x 1 grado, asi que
    hay que tomar el piso de cada coordenada. `S07_00_W078_00` cubre
    latitud -7 a -6 y longitud -78 a -77.
    """
    oeste, sur, este, norte = bbox
    nombres = []
    for lat in range(math.floor(sur), math.floor(norte) + 1):
        for lon in range(math.floor(oeste), math.floor(este) + 1):
            ns = "N" if lat >= 0 else "S"
            ew = "E" if lon >= 0 else "W"
            nombres.append(
                f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_"
                f"{ew}{abs(lon):03d}_00_DEM")
    return nombres


def url_opentopography(bbox, demtype: str, api_key: str):
    """URL y parametros del recorte ya hecho por el servicio."""
    oeste, sur, este, norte = bbox
    return OPENTOPOGRAPHY, {
        "demtype": demtype,
        "south": sur, "north": norte, "west": oeste, "east": este,
        "outputFormat": "GTiff",
        "API_Key": api_key,
    }


def url_tile_copernicus(nombre: str) -> str:
    return f"{COPERNICUS_S3}/{nombre}/{nombre}.tif"


def params_geocam(bbox, offset: int = 0, por_pagina: int = 1000) -> dict:
    """Parametros de una consulta espacial a un FeatureServer de ArcGIS.

    OJO con el CRS: con `f=geojson` ArcGIS devuelve SIEMPRE WGS84, se pida
    lo que se pida en `outSR`, porque el formato GeoJSON lo exige. La
    reproyeccion se hace despues, en geopandas.
    """
    oeste, sur, este, norte = bbox
    return {
        "where": "1=1",
        "geometry": f"{oeste},{sur},{este},{norte}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "geojson",
        "resultOffset": int(offset),
        "resultRecordCount": int(por_pagina),
    }


def baja(url: str, destino: pathlib.Path, params=None, forzar: bool = False,
         timeout: int = 900) -> pathlib.Path:
    """Descarga con escritura en bloques y salto si el archivo ya esta."""
    destino = pathlib.Path(destino)
    if destino.exists() and destino.stat().st_size > 0 and not forzar:
        print(f"  ya esta: {destino.name} "
              f"({destino.stat().st_size / 1e6:.1f} MB)")
        return destino

    print(f"  bajando: {destino.name}", flush=True)
    parcial = destino.with_suffix(destino.suffix + ".parcial")
    with requests.get(url, params=params, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(parcial, "wb") as f:
            for trozo in r.iter_content(1 << 20):
                f.write(trozo)
    parcial.replace(destino)
    print(f"           {destino.stat().st_size / 1e6:.1f} MB")
    return destino


# ------------------------------------------------------------------ pasos

def cubre_la_caja(ruta, bbox, margen_grados: float = 0.005) -> bool:
    """True si un raster ya bajado cubre la caja que pide la config.

    Hace falta por una trampa silenciosa: si se ensancha
    'extension.bbox' y se corre `bajar` sin --forzar, el archivo viejo ya
    existe y se da por bueno. Despues `preparar` lo alinea a la rejilla
    NUEVA y el pedazo que falta queda como nodata -- o sea, un agujero en
    el DEM justo en la parte que se acaba de anadir. Nada falla; el estudio
    simplemente se corre sobre un DEM incompleto.
    """
    import rasterio
    from rasterio.warp import transform_bounds

    ruta = pathlib.Path(ruta)
    if not ruta.exists() or ruta.stat().st_size == 0:
        return False
    try:
        with rasterio.open(ruta) as src:
            o, s, e, n = transform_bounds(src.crs, "EPSG:4326", *src.bounds,
                                          densify_pts=21)
    except Exception:
        return False
    return (o <= bbox[0] + margen_grados and s <= bbox[1] + margen_grados
            and e >= bbox[2] - margen_grados and n >= bbox[3] - margen_grados)


def dems(cfg, forzar: bool = False) -> dict[str, pathlib.Path]:
    """Baja los dos DEM recortados. Devuelve {nombre: ruta}.

    Bajar dos no es redundancia: la diferencia entre ellos ES la banda de
    incertidumbre vertical del modelo, y no cuesta nada tenerla.
    """
    llave = cfg.exige_llave()
    salida = {}
    for dem in DEMS:
        destino = cfg.dir_datos / f"{dem.lower()}_raw.tif"
        rehacer = forzar
        if not forzar and destino.exists() and \
                not cubre_la_caja(destino, cfg.bbox):
            print(f"  {destino.name} es de una caja MAS CHICA que la de "
                  "config.yaml:")
            print("  lo vuelvo a bajar. (Si no, 'preparar' lo alinearia a la")
            print("  rejilla nueva y el pedazo que falta quedaria como hueco.)")
            rehacer = True
        url, params = url_opentopography(cfg.bbox, dem, llave)
        salida[dem] = baja(url, destino, params=params, forzar=rehacer)
    return salida


def tile_copernicus(cfg, forzar: bool = False) -> list[pathlib.Path]:
    """Alternativa sin llave: los tiles completos desde el bucket publico."""
    return [baja(url_tile_copernicus(t), cfg.dir_datos / f"{t}.tif",
                 forzar=forzar)
            for t in tiles_copernicus(cfg.bbox)]


def agua(cfg, forzar: bool = False) -> pathlib.Path | None:
    """Cuerpos de agua permanentes, de OpenStreetMap.

    Es un insumo OPCIONAL: sin el, la mascara simplemente no excluye lagunas
    ni el cauce de los rios grandes. Si Overpass no responde, se avisa y se
    sigue; no se tumba la corrida entera por esto.
    """
    import json

    from . import osm

    destino = cfg.dir_datos / "agua_osm.json"
    if destino.exists() and destino.stat().st_size > 0 and not forzar:
        print(f"  ya esta: {destino.name}")
        return destino

    print("  consultando Overpass (OpenStreetMap)", flush=True)
    try:
        d = osm.consulta(osm.consulta_agua(cfg.bbox))
    except RuntimeError as e:
        print(f"\n  AVISO: no se pudo bajar el agua de OpenStreetMap.\n  {e}")
        print("\n  No es grave y no bloquea nada: es un insumo opcional. La")
        print("  mascara quedara sin excluir lagunas ni cauces grandes. Para")
        print("  reintentarlo mas tarde:  python -m camino bajar --forzar")
        return None

    destino.write_text(json.dumps(d), encoding="utf-8")
    n = len(d.get("elements", []))
    print(f"  {n} elementos de agua")
    return destino


def camino_registrado(cfg, forzar: bool = False) -> pathlib.Path:
    """Trae el camino de GeoCAM a un GeoPackage, por WFS o por ArcGIS REST.

    Al final imprime el numero que decide el diseno del estudio: cuantos
    metros de polilinea CONTINUA hay. Si el tramo continuo mas largo es
    corto, sectores y validacion bloqueada compiten por los mismos metros y
    hay que elegir una de las dos.
    """
    import geopandas as gpd

    destino = cfg.dir_datos / "qn_geocam.gpkg"
    if destino.exists() and not forzar:
        print(f"  ya esta: {destino.name}")
        return destino

    clase, url = cfg.fuente_geocam()
    qn = _por_wfs(cfg, url) if clase == "wfs" else _por_rest(cfg, url)

    qn = recorta(qn, cfg)
    if qn.empty:
        raise SystemExit(
            "La capa se bajo bien, pero no tiene nada dentro de la caja del\n"
            "tramo. O es otra capa, o el tramo no esta digitalizado ahi.")

    qn.to_file(destino, layer="camino", driver="GPKG")
    resumen(qn)
    return destino


def recorta(qn, cfg):
    """Corta la geometria por la caja del tramo.

    Se CORTA, no se seleccionan los rasgos que la tocan: el DEM solo cubre
    la caja, asi que un trozo de camino fuera de ella no se puede modelar, y
    dejarlo dentro inflaria los kilometros y podria poner el extremo de un
    sector fuera del raster.
    """
    import geopandas as gpd
    from shapely.geometry import box

    caja = gpd.GeoSeries([box(*cfg.bbox)], crs="EPSG:4326").to_crs(qn.crs)[0]
    dentro = qn[qn.geometry.intersects(caja)]
    if dentro.empty:
        return dentro.copy()
    cortado = gpd.clip(dentro, caja)
    return cortado[~cortado.geometry.is_empty].copy()


def _por_wfs(cfg, base: str):
    """Baja la capa por WFS, el estandar OGC que publica el propio portal."""
    from . import buscar, wfs

    sesion = requests.Session()
    print(f"  WFS: {base}")
    version, xml = wfs.capabilities(base, sesion)
    if not version:
        raise SystemExit(
            f"El WFS de {base} no respondio.\n"
            "El proxy del Ministerio devuelve 500 de forma intermitente\n"
            "('Error during SSL Handshake with remote server'): no es un error\n"
            "de tu peticion y no hay nada que puedas arreglar de tu lado.\n"
            "\n"
            "QUE HACER AHORA. El camino puede entrar por otras dos puertas:\n"
            "\n"
            "  1) Seguir hoy mismo con OpenStreetMap, como apano provisional:\n"
            "       python -m camino ruta --fuente osm\n"
            "     Sirve para correr todo de punta a punta y ver si el modelo\n"
            "     hace algo sensato. NO vale para publicar.\n"
            "\n"
            "  2) Un archivo tuyo (lo que corresponde mientras GeoCAM no vuelva).\n"
            "     DEJALO EN datos/ Y YA ESTA: el programa lo encuentra solo.\n"
            "     Vale .kmz, .kml, .shp, .gpkg, .geojson o el .gpx del Garmin.\n"
            "     Hay un Qhapaq Nan nacional en shapefile aqui:\n"
            "     https://www.geogpsperu.com/2020/10/mapa-del-qhapaq-nan-camino-inca.html\n"
            "\n"
            "  3) Reintentar GeoCAM mas tarde:  python -m camino buscar")

    capas = wfs.lee_capabilities(xml)
    capa = cfg.geocam_capa
    if not capa:
        puntuadas = sorted(
            capas,
            key=lambda c: -buscar.puntua(f"{c['nombre']} {c['titulo']}"))
        if not puntuadas or buscar.puntua(
                f"{puntuadas[0]['nombre']} {puntuadas[0]['titulo']}") <= 0:
            raise SystemExit(
                f"El WFS publica {len(capas)} capas pero ninguna parece ser el\n"
                "camino. Corre `python -m camino buscar` para ver la lista y\n"
                "pon la que reconozcas en config.yaml, en 'geocam_capa'.")
        capa = puntuadas[0]["nombre"]
        print(f"  capa elegida automaticamente: {capa}")
    else:
        print(f"  capa: {capa}")

    formato = wfs.formato_json(wfs.formatos_salida(xml))
    print(f"  WFS {version}, formato {formato or 'GML (por defecto)'}")
    return wfs.descarga_capa(base, capa, version, formato, cfg.crs, sesion)


def _por_rest(cfg, servicio: str):
    """Alternativa: la capa de ArcGIS REST, pagina por pagina."""
    import geopandas as gpd
    import pandas as pd

    trozos, offset = [], 0
    while True:
        r = requests.get(f"{servicio}/query",
                         params=params_geocam(cfg.bbox, offset), timeout=300)
        r.raise_for_status()
        j = r.json()
        if "error" in j:
            raise SystemExit(f"GeoCAM devolvio un error: {j['error']}")
        rasgos = j.get("features", [])
        print(f"  offset {offset}: {len(rasgos)} rasgos")
        if not rasgos:
            break
        trozos.append(gpd.GeoDataFrame.from_features(rasgos, crs="EPSG:4326"))
        if len(rasgos) < 1000:
            break
        offset += len(rasgos)

    if not trozos:
        raise SystemExit("GeoCAM no devolvio ningun rasgo en esa caja")

    return gpd.GeoDataFrame(pd.concat(trozos, ignore_index=True),
                            crs="EPSG:4326").to_crs(cfg.crs)


def continuo_mayor(qn) -> tuple[float, int]:
    """Longitud de la pieza continua mas larga, en metros, y cuantas piezas.

    Cose primero lo que se toca. Medir el rasgo mas largo por separado
    subestima el camino disponible: el registro llega partido en segmentos
    que son contiguos sobre el terreno, y para el modelo cuentan como uno.
    """
    from shapely.ops import linemerge, unary_union

    geoms = [g for g in qn.geometry if g is not None and not g.is_empty]
    if not geoms:
        return 0.0, 0

    # Un recorrido grabado ya viene cosido y en orden de tiempo, y puede
    # volver a pasar por un sitio. `unary_union` lo partiria ahi y este
    # inventario diria que el trecho es mas corto de lo que es -- 13.2 km en
    # vez de 20.5 en el circuito de Qoyllur Rit'i-- justo en la tabla que se
    # mira para decidir si hay camino suficiente.
    if "origen" in getattr(qn, "columns", []) and \
            (qn["origen"] == "trayectoria").all():
        return float(max(g.length for g in geoms)), len(geoms)

    u = unary_union(geoms)
    m = linemerge(u) if u.geom_type != "LineString" else u
    piezas = list(m.geoms) if m.geom_type == "MultiLineString" else [m]
    return float(max(p.length for p in piezas)), len(piezas)


def resumen(qn) -> dict:
    """El diagnostico que hay que mirar antes de modelar nada."""
    lineas = qn[qn.geometry.geom_type.isin(["LineString", "MultiLineString"])]
    largos = lineas.geometry.length
    mayor, piezas = continuo_mayor(lineas)
    info = {
        "rasgos": int(len(qn)),
        "lineas": int(len(lineas)),
        "largo_total_km": round(float(largos.sum()) / 1000, 2) if len(lineas) else 0.0,
        "piezas_continuas": piezas,
        "continuo_max_km": round(mayor / 1000, 2),
        "tipos": qn.geometry.geom_type.value_counts().to_dict(),
        "campos": [c for c in qn.columns if c != "geometry"],
    }
    print("\n  --- lo primero que hay que mirar ---")
    for k, v in info.items():
        print(f"  {k}: {v}")
    if info["continuo_max_km"] < 15:
        print("\n  AVISO: con menos de ~15 km continuos, partir en sectores y")
        print("  validar en bloques compiten por los mismos metros. Hay que")
        print("  elegir una de las dos ANTES de correr el barrido.")
    return info
