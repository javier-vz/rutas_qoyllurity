"""Espacios ceremoniales: la componente que el proyecto pone frente al costo fisico.

El proyecto define la variable como la distancia euclidiana al lugar
ceremonial pertinente mas proximo, y le pone dos reglas que no son
tecnicas sino de diseno, y que cambian el resultado:

1. Los lugares cuya identificacion dependa principalmente DEL PROPIO
   CAMINO no sirven como predictores. Si un sitio se reconocio porque esta
   junto a la via, usarlo para explicar por donde va la via es circular.
   Esto no lo puede decidir el codigo: se filtra en el archivo de entrada,
   con criterio arqueologico.

2. Un espacio ceremonial que coincida con el INICIO O EL TERMINO del tramo
   analizado se excluye de su componente. Si no, el modelo recibe como
   premio acercarse a un punto al que de todas formas tiene que llegar, y
   la componente mide el enunciado del problema en vez del paisaje. Esto si
   lo hace el codigo, por unidad.

Por eso la superficie de proximidad no es global: se recalcula para cada
unidad. Lo que si se mantiene constante entre unidades es la REGLA de
transformacion (la distancia de saturacion), que es lo que el proyecto
exige para que los pesos sean comparables.
"""

from __future__ import annotations

import pathlib

import numpy as np

EXTENSIONES = (".gpkg", ".shp", ".geojson", ".json", ".kmz", ".kml", ".csv")


def busca_archivo(cfg) -> pathlib.Path | None:
    """El archivo de sitios: el que diga la config, o `datos/sitios*`."""
    if cfg.ceremonial_archivo:
        ruta = pathlib.Path(cfg.ceremonial_archivo)
        if not ruta.is_absolute():
            ruta = cfg.raiz / ruta
        if not ruta.exists():
            raise SystemExit(f"No encuentro el archivo de sitios: {ruta}")
        return ruta

    candidatos = [p for p in sorted(cfg.dir_datos.iterdir())
                  if p.is_file() and p.name.lower().startswith("sitios")
                  and p.suffix.lower() in EXTENSIONES]
    return candidatos[0] if candidatos else None


def carga(cfg, ruta=None):
    """Los sitios como (n, 2) de coordenadas en el CRS de trabajo.

    Acepta puntos y poligonos; de un poligono se toma su centroide. Un
    recinto ceremonial a escala de 30 m es un punto.
    """
    import geopandas as gpd
    import pandas as pd

    ruta = ruta or busca_archivo(cfg)
    if ruta is None:
        return np.empty((0, 2)), []

    ruta = pathlib.Path(ruta)
    if ruta.suffix.lower() == ".csv":
        df = pd.read_csv(ruta)
        cols = {c.lower(): c for c in df.columns}
        lon = cols.get("lon") or cols.get("longitud") or cols.get("x")
        lat = cols.get("lat") or cols.get("latitud") or cols.get("y")
        if not lon or not lat:
            raise SystemExit(
                f"{ruta.name} no tiene columnas de coordenadas reconocibles "
                "(lon/lat, longitud/latitud o x/y)")
        g = gpd.GeoDataFrame(
            df, geometry=gpd.points_from_xy(df[lon], df[lat]),
            crs="EPSG:4326")
    elif ruta.suffix.lower() in (".kmz", ".kml"):
        from . import registro
        g = gpd.read_file(registro.abrir_kmz(ruta))
    else:
        g = gpd.read_file(ruta)

    if g.crs is None:
        g = g.set_crs("EPSG:4326")
    g = g.to_crs(cfg.crs)
    g = g[~g.geometry.isna() & ~g.geometry.is_empty]
    if g.empty:
        return np.empty((0, 2)), []

    puntos = g.geometry.representative_point()
    nombres = []
    for col in ("nombre", "Name", "name", "NOMBRE", "sitio"):
        if col in g.columns:
            nombres = [str(v) for v in g[col]]
            break
    if not nombres:
        nombres = [f"sitio_{i}" for i in range(len(g))]

    return np.column_stack([puntos.x.values, puntos.y.values]), nombres


def puntos_de_config(cfg):
    """Puntos sueltos escritos a mano en la config, en "lat,lon".

    Para el dia que haya un cerro tutelar documentado para este corredor: se
    anade ahi y entra a la componente de visibilidad junto con los sitios,
    sin tocar el codigo. Hoy la lista esta vacia a proposito.
    """
    import geopandas as gpd

    crudos = cfg.visibilidad_puntos
    if not crudos:
        return np.empty((0, 2))

    latlon = []
    for s in crudos:
        try:
            lat, lon = (float(v) for v in str(s).split(","))
        except ValueError:
            raise SystemExit(
                f"'{s}' no es un punto: se escribe \"lat,lon\", por ejemplo "
                '"-6.42,-77.87"')
        latlon.append((lon, lat))

    g = gpd.GeoSeries(gpd.points_from_xy(*zip(*latlon)),
                      crs="EPSG:4326").to_crs(cfg.crs)
    return np.column_stack([g.x.values, g.y.values])


def sin_los_extremos(puntos, geometria, radio: float):
    """Quita los sitios que caen en los extremos del tramo analizado.

    Es la regla 2 del encabezado. Sin ella, la componente premia acercarse
    a un punto al que el camino tiene que llegar de todas formas, y mide el
    enunciado en vez del paisaje.
    """
    puntos = np.asarray(puntos, dtype=np.float64)
    if puntos.size == 0:
        return puntos, 0
    # [:2] por la Z del KMZ: sin eso, restar un punto 2D de uno 3D falla
    extremos = np.array([geometria.coords[0][:2], geometria.coords[-1][:2]],
                        dtype=np.float64)
    d = np.sqrt(((puntos[:, None, :] - extremos[None, :, :]) ** 2).sum(-1))
    fuera = d.min(axis=1) > radio
    return puntos[fuera], int((~fuera).sum())


def resumen(puntos, nombres, cfg) -> dict:
    from shapely.geometry import box
    import geopandas as gpd

    caja = gpd.GeoSeries([box(*cfg.bbox)], crs="EPSG:4326").to_crs(cfg.crs)[0]
    dentro = sum(1 for x, y in puntos
                 if caja.contains(__import__("shapely").geometry.Point(x, y)))
    return {"sitios": int(len(puntos)), "dentro_de_la_caja": int(dentro)}
