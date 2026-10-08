"""Alineacion de rasteres, mascara del corredor y particion en sectores.

Dos DEM distintos solo son comparables si caen en la MISMA rejilla: mismo
CRS, misma resolucion, mismo origen, misma forma. Aqui se impone eso de una
vez, y todo lo que venga despues asume que se cumple.
"""

from __future__ import annotations

import math
import pathlib

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import reproject, transform_bounds


def rejilla(cfg):
    """Rejilla comun: (transform, ancho, alto), pegada a multiplos de la
    resolucion para que dos corridas cualquiera caigan en las mismas celdas."""
    res = cfg.resolucion
    xmin, ymin, xmax, ymax = transform_bounds("EPSG:4326", cfg.crs, *cfg.bbox,
                                              densify_pts=21)
    xmin = math.floor(xmin / res) * res
    ymin = math.floor(ymin / res) * res
    xmax = math.ceil(xmax / res) * res
    ymax = math.ceil(ymax / res) * res
    ancho = int(round((xmax - xmin) / res))
    alto = int(round((ymax - ymin) / res))
    return from_origin(xmin, ymax, res, res), ancho, alto


def comprueba_rejilla(cfg, nombre: str = "cop30.tif") -> None:
    """Que lo que hay en derivados/ sea de la caja que dice config.yaml.

    Existe por un fallo que no se nota. Si se cambia 'extension.bbox' y no se
    vuelve a correr desde `bajar`, los rasteres de derivados/ siguen siendo
    de la caja vieja: el grafo tiene los nodos de una rejilla y
    `preparar.rejilla(cfg)` devuelve otra, asi que las filas y columnas se
    convierten a coordenadas con el transform equivocado. No falla nada. Las
    distancias salen mal y la tabla parece normal.

    Paso de verdad: al descomprimir una version nueva del paquete se
    sobreescribio config.yaml con el bbox por omision, y la corrida siguiente
    midio los nodos de la caja ancha con la rejilla de la caja angosta.
    """
    ruta = cfg.dir_derivados / nombre
    if not ruta.exists():
        return

    t, ancho, alto = rejilla(cfg)
    with rasterio.open(ruta) as src:
        misma = (src.width == ancho and src.height == alto
                 and all(abs(a - b) < 1e-6 for a, b in
                         zip(tuple(src.transform)[:6], tuple(t)[:6])))
        if misma:
            return
        caja_disco = transform_bounds(src.crs, "EPSG:4326", *src.bounds,
                                      densify_pts=21)
        forma_disco = (src.width, src.height)

    raise SystemExit(
        f"\nLo que hay en derivados/ NO es de la caja que dice config.yaml.\n"
        f"\n  config.yaml  {ancho} x {alto} celdas\n"
        f"               oeste {cfg.bbox[0]}  sur {cfg.bbox[1]}  "
        f"este {cfg.bbox[2]}  norte {cfg.bbox[3]}\n"
        f"  {nombre:12s} {forma_disco[0]} x {forma_disco[1]} celdas\n"
        f"               oeste {caja_disco[0]:.3f}  sur {caja_disco[1]:.3f}  "
        f"este {caja_disco[2]:.3f}  norte {caja_disco[3]:.3f}\n"
        "\nNo se puede seguir: el grafo tiene los nodos de una rejilla y los\n"
        "numeros saldrian medidos con la otra. Elige una:\n"
        "\n  a) si la caja BUENA es la de config.yaml, rehaz los derivados:\n"
        "       python -m camino bajar --forzar\n"
        "       python -m camino ruta  --forzar\n"
        "       python -m camino todo\n"
        "\n  b) si la caja buena es la del disco, pon ESE bbox en "
        "config.yaml:\n"
        f"       oeste: {caja_disco[0]:.3f}\n"
        f"       sur: {caja_disco[1]:.3f}\n"
        f"       este: {caja_disco[2]:.3f}\n"
        f"       norte: {caja_disco[3]:.3f}\n"
        "\n(Si acabas de descomprimir una version nueva del paquete, lo mas\n"
        "probable es que te haya pisado config.yaml: es (b).)")


def escribe(ruta, datos, transform, crs, nodata=np.nan):
    """Guarda un raster float32 comprimido, con el mismo perfil siempre."""
    datos = np.asarray(datos, dtype=np.float32)
    perfil = dict(driver="GTiff", height=datos.shape[0], width=datos.shape[1],
                  count=1, dtype="float32", crs=crs, transform=transform,
                  nodata=nodata, compress="deflate", predictor=2, tiled=True)
    with rasterio.open(ruta, "w", **perfil) as dst:
        dst.write(datos, 1)
    return pathlib.Path(ruta)


def lee(ruta):
    """Devuelve (datos float64 con nodata como nan, transform, crs)."""
    with rasterio.open(ruta) as src:
        a = src.read(1, masked=True).astype(np.float64).filled(np.nan)
        return a, src.transform, src.crs


def alinear(cfg, entradas: dict[str, str | pathlib.Path]) -> dict[str, pathlib.Path]:
    """Reproyecta y recorta cada entrada a la rejilla comun.

    `bilinear` se usa SOLO aqui, sobre el DEM. Nunca se remuestrea una
    superficie derivada: se remuestrea el DEM y se vuelve a derivar.
    """
    transform, ancho, alto = rejilla(cfg)
    salidas = {}
    for nombre, ruta in entradas.items():
        destino = cfg.dir_derivados / f"{nombre}.tif"
        with rasterio.open(ruta) as src:
            out = np.full((alto, ancho), np.nan, dtype=np.float32)
            reproject(source=rasterio.band(src, 1), destination=out,
                      src_transform=src.transform, src_crs=src.crs,
                      src_nodata=src.nodata,
                      dst_transform=transform, dst_crs=cfg.crs,
                      dst_nodata=np.nan, resampling=Resampling.bilinear)
        salidas[nombre] = escribe(destino, out, transform, cfg.crs)
        print(f"  {nombre}: {alto} x {ancho} celdas a {cfg.resolucion:g} m")
    return salidas


def banda_incertidumbre(a, b) -> dict:
    """Diferencia entre los dos DEM: la incertidumbre vertical, gratis.

    No es un chequeo de calidad, es un numero que va en el articulo: dice
    cuanta de la variacion del costo de pendiente es terreno y cuanta es el
    DEM que elegiste.
    """
    d = np.abs(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64))
    d = d[np.isfinite(d)]
    if d.size == 0:
        return {}
    return {"mediana_m": round(float(np.median(d)), 2),
            "p90_m": round(float(np.percentile(d, 90)), 2),
            "p99_m": round(float(np.percentile(d, 99)), 2),
            # El maximo lo fija siempre un pixel suelto (un vacio de datos,
            # un borde, una pared vertical donde 30 m de desfase horizontal
            # son cientos de metros verticales). El numero que va en el
            # articulo es el p90; el maximo solo dice que hay outliers.
            "max_m": round(float(d.max()), 2),
            "pct_sobre_50m": round(100 * float((d > 50).mean()), 3)}


# -------------------------------------------------------------- corredor

def lineas_unidas(camino):
    """Une las polilineas del camino registrado en el menor numero de piezas.

    Pasa por `unary_union` antes de coser. El registro llega como
    MultiLineString por rasgo, y `linemerge` sobre esa lista no junta los
    segmentos que se tocan entre rasgos distintos: sin este paso, el camino
    disponible se subestima -- en el tramo Chillo-Chachapoyas, 7.96 km en
    vez de los 12.40 km reales.
    """
    from shapely import force_2d
    from shapely.ops import linemerge, unary_union

    geoms = [g for g in camino.geometry
             if g is not None and not g.is_empty
             and g.geom_type in ("LineString", "MultiLineString")]
    if not geoms:
        raise ValueError("el camino registrado no tiene ninguna polilinea")
    # FUERA LA Z. El KMZ del registro trae coordenadas en 3D, y entonces
    # `linea.coords[0]` devuelve (x, y, z). Todo lo que despues trate esos
    # extremos como un par se rompe o, peor, no se rompe: np.hypot(x, y, z)
    # toma el tercero como array de salida, y restarle un punto 2D a uno 3D
    # falla al difundir. La altura ya esta en el DEM; en la geometria estorba.
    geoms = [force_2d(g) for g in geoms]
    u = unary_union(geoms)
    unido = linemerge(u) if u.geom_type != "LineString" else u
    piezas = list(unido.geoms) if unido.geom_type == "MultiLineString" else [unido]
    return sorted(piezas, key=lambda g: g.length, reverse=True)


def mascara_corredor(cfg, camino, agua_geoms=None):
    """Mascara booleana: corredor alrededor del camino, menos el agua.

    El corredor existe por computo: la caja completa son millones de celdas
    y no se barren. Pero un buffer estrecho DECIDE el resultado, asi que
    despues de cada corrida hay que comprobar que el camino modelado no
    toque el borde (`metricas.toca_borde`).
    """
    from rasterio.features import geometry_mask

    transform, ancho, alto = rejilla(cfg)
    piezas = lineas_unidas(camino)
    buffer = [p.buffer(cfg.buffer_corredor) for p in piezas]

    dentro = ~geometry_mask(buffer, out_shape=(alto, ancho), transform=transform,
                            invert=False, all_touched=True)
    n_corredor = int(dentro.sum())
    if n_corredor == 0:
        raise ValueError(
            "El corredor no toca la rejilla. Suele ser que el camino quedo "
            "fuera de la caja del estudio: revisa 'extension.bbox' y "
            "'datos.tramo' en config.yaml.")

    if agua_geoms:
        agua = ~geometry_mask(list(agua_geoms), out_shape=(alto, ancho),
                              transform=transform, all_touched=True)
        quita = int((dentro & agua).sum())
        if quita > 0.5 * n_corredor:
            # Senal de que las geometrias de agua vienen mal: lo normal es
            # que los rios se lleven un porcentaje pequeno del corredor.
            raise ValueError(
                f"El agua se llevaria {100 * quita / n_corredor:.0f}% del "
                f"corredor ({quita} de {n_corredor} celdas), lo que no es "
                "creible. Revisa que las geometrias de agua esten en metros "
                "y no en grados, o borra datos/agua_osm.json y sigue sin "
                "ellas: es un insumo opcional.")
        dentro &= ~agua

    return dentro, transform


def unidades(cfg, camino):
    """Las unidades que se comparan entre si: tramos con nombre o sectores.

    Dos formas de partir el problema, y la eleccion importa:

    'tramo'   cada tramo del registro es una unidad. Son unidades REALES:
              el Ministerio las registro y las nombro de forma
              independiente, con su propia campana de prospeccion. Comparar
              pesos entre ellas compara cosas que existen.

    'sector'  un tramo se corta en n pedazos iguales. Los cortes no
              corresponden a nada del terreno: son una raya que ponemos
              nosotros. Sirve para preguntar si algo cambia A LO LARGO de un
              tramo, pero un resultado por sectores siempre carga con la
              sospecha de depender de donde cayo el corte.

    Devuelve [(nombre, LineString)], con la pieza CONTINUA mayor de cada
    unidad: un ajuste contra una linea con agujeros no significa nada.
    """
    if cfg.unidad == "sector":
        return sectores(camino, cfg.n_sectores)
    if cfg.unidad != "tramo":
        raise ValueError("'unidad' tiene que ser 'tramo' o 'sector'")

    if "tramnomb" not in camino.columns:
        raise SystemExit(
            "La fuente del camino no trae tramos con nombre (un GPX o unas "
            "trazas de OSM no los traen).\nPon 'unidad: sector' en "
            "config.yaml, o usa el KMZ del registro.")

    from . import registro

    salida, avisos = [], []
    for nombre, g in camino.groupby(camino["tramnomb"].fillna("(sin nombre)")):
        try:
            piezas = lineas_unidas(g)
        except ValueError:
            continue
        mayor = piezas[0]
        if mayor.length >= cfg.largo_min_unidad:
            salida.append((str(nombre), mayor))
            # Una etiqueta del registro con suficiente linea dentro de la
            # caja entraria al analisis como si fuera un camino, y sus pesos
            # se compararian con los de un camino. Aqui no se excluye nada
            # -- el criterio es arqueologico-- pero se dice.
            aviso = registro.avisa_si_parece_etiqueta(g, str(nombre))
            if aviso:
                avisos.append(aviso)

    if not salida:
        raise SystemExit(
            f"Ningun tramo llega a {cfg.largo_min_unidad / 1000:.1f} km "
            "continuos.\nBaja 'largo_min_unidad' en config.yaml, o usa "
            "'unidad: sector'.")
    if avisos:
        print("\n  AVISO: estas unidades parecen ETIQUETAS del registro y no "
              "tramos:")
        for a in avisos:
            print(f"    {a}")

    salida = sorted(salida, key=lambda u: -u[1].length)
    avisa_recortadas(cfg, salida)
    return salida


def recortada_por_la_caja(cfg, geometria, margen_celdas: int = 2) -> bool:
    """True si la unidad llega al borde de la caja del estudio.

    Importa mas de lo que parece. Un tramo cortado por la caja tiene un
    extremo INVENTADO: el modelo tiene que reproducir una ruta hasta un
    punto que no es un destino, sino donde pusimos el limite. Y el corredor
    tambien queda cortado ahi, asi que el camino puede ir forzado.
    """
    import geopandas as gpd
    from shapely.geometry import box

    # Se mide contra la caja donde se RECORTO la geometria (bbox en grados,
    # reproyectada), no contra la rejilla: la rejilla se redondea hacia
    # afuera a multiplos de la resolucion, asi que queda un poco mas grande
    # y el borde real cae dentro de ella.
    caja = gpd.GeoSeries([box(*cfg.bbox)], crs="EPSG:4326").to_crs(cfg.crs)[0]
    margen = margen_celdas * cfg.resolucion
    return geometria.distance(caja.exterior) <= margen


def avisa_recortadas(cfg, unidades_) -> list[str]:
    """Avisa de las unidades que tocan el borde de la caja."""
    tocadas = [n for n, geom in unidades_ if recortada_por_la_caja(cfg, geom)]
    if tocadas:
        print("\n  AVISO: estas unidades llegan al borde de la caja, asi que")
        print("  uno de sus extremos no es un destino sino donde cortamos:")
        for n in tocadas:
            print(f"    - {n}")
        print("  Opciones: ensanchar 'extension.bbox' para que entren")
        print("  completas, o sacarlas del analisis. Mientras tanto, sus")
        print("  pesos valen menos que los de las unidades completas.")
    return tocadas


def sectores(camino, n: int):
    """Parte la pieza continua mas larga en `n` sectores de igual longitud.

    Se usa la pieza MAS LARGA, no todas: un sector que mezcla dos piezas
    separadas por un vacio de registro no es un sector, es un artefacto.
    """
    from shapely.ops import substring

    linea = lineas_unidas(camino)[0]
    largo = linea.length
    if n < 1:
        raise ValueError("hace falta al menos un sector")
    if largo / n < 500:
        raise ValueError(
            f"la pieza continua mide {largo:.0f} m: partirla en {n} sectores "
            f"deja {largo / n:.0f} m cada uno, menos de 20 celdas. "
            f"Usa menos sectores o valida en bloques, pero no las dos cosas.")

    salida = []
    for i in range(n):
        trozo = substring(linea, largo * i / n, largo * (i + 1) / n)
        salida.append((f"s{i + 1}", trozo))
    return salida


def filcol_de_xy(xy, transform):
    """Fila y columna de coordenadas proyectadas (inverso de grafo.xy)."""
    inv = ~transform
    xy = np.asarray(xy, dtype=np.float64)
    cols, fils = inv @ (xy[:, 0], xy[:, 1])
    return np.column_stack([np.floor(np.asarray(fils)).astype(np.int64),
                            np.floor(np.asarray(cols)).astype(np.int64)])


def vertices(geom, paso=None):
    """Vertices de una polilinea como array (n, 2); remuestrea si se da paso."""
    from shapely import get_coordinates
    if paso:
        n = max(2, int(math.ceil(geom.length / paso)) + 1)
        pts = [geom.interpolate(geom.length * k / (n - 1)) for k in range(n)]
        return np.array([[p.x, p.y] for p in pts])
    return get_coordinates(geom)
