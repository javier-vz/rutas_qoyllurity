"""Lectura del registro del Qhapaq Nan en KML/KMZ.

El KMZ del registro no es una traza suelta: trae las CATEGORIAS con que el
Ministerio clasifica cada segmento, cada una en su propia capa.

    Trazo de Camino                       camino fisico, observado
    Camino Registrado                     observado y formalmente registrado
    Camino Identificado                   observado, identificado en campo
    Camino Afectado                       observado, con danos
    Proyeccion de Camino por Reemplazo    INFERIDO: lo tapo una carretera
    Proyeccion de Camino por Danos        INFERIDO: el tramo se destruyo
    Proyeccion de Camino por Ausencia     INFERIDO: no se encontro en campo

La distincion no es burocratica, decide el estudio. Las tres de "Proyeccion"
son tramos donde el camino YA NO ESTA y la linea la dibujo alguien
infiriendo por donde iba. Ajustar un modelo de costo contra una linea
proyectada es circular: lo que se recupera son los supuestos de quien la
proyecto, no el comportamiento de quien construyo el camino. Por eso el
valor por omision solo incluye las cuatro capas observadas.

Los atributos (tramnomb, dptonomb, provnomb, distnomb, TipoCamino) no vienen
como campos: vienen dentro de una tabla HTML en el campo `description`, que
es como Google Earth guarda las tablas de atributos. Hay que extraerlos.
"""

from __future__ import annotations

import math
import pathlib
import re
import tempfile
import zipfile

OBSERVADAS = ("Trazo de Camino", "Camino Registrado",
              "Camino Identificado", "Camino Afectado")

PROYECTADAS = ("Proyeccion de Camino por Reemplazo",
               "Proyeccion de Camino por Danos",
               "Proyeccion de Camino por Ausencia")

# Campos que el registro guarda dentro del HTML de `description`.
CAMPOS = ("tramnomb", "longitud", "dptonomb", "provnomb", "distnomb",
          "ubigeo", "ccppprox", "TipoCamino")

_PAR = re.compile(r"<td>([^<>]+)</td>\s*\n*\s*<td>(.*?)</td>", re.S)
_ETIQUETA = re.compile(r"<[^>]+>")


def sin_tildes(s: str) -> str:
    """Compara nombres de capa sin depender de tildes ni mayusculas."""
    tabla = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
    return str(s).translate(tabla).strip().lower()


def atributos(html) -> dict:
    """Saca los pares campo/valor de la tabla HTML de `description`."""
    if not isinstance(html, str) or "<td>" not in html:
        return {}
    return {k.strip(): _ETIQUETA.sub("", v).strip() for k, v in _PAR.findall(html)}


def abrir_kmz(ruta) -> pathlib.Path:
    """Un KMZ es un ZIP con un doc.kml dentro. Devuelve la ruta al KML."""
    ruta = pathlib.Path(ruta)
    if ruta.suffix.lower() != ".kmz":
        return ruta
    destino = pathlib.Path(tempfile.mkdtemp(prefix="kmz_"))
    with zipfile.ZipFile(ruta) as z:
        kmls = [n for n in z.namelist() if n.lower().endswith(".kml")]
        if not kmls:
            raise SystemExit(f"{ruta.name} no tiene ningun .kml dentro")
        z.extract(kmls[0], destino)
    return destino / kmls[0]


def capas(ruta) -> list[str]:
    """Nombres de las capas de un KML/KMZ."""
    import pyogrio
    return [str(c[0]) for c in pyogrio.list_layers(str(abrir_kmz(ruta)))]


def diagonal(gdf) -> float:
    """Diagonal de la caja envolvente de un grupo, en metros del CRS."""
    xmin, ymin, xmax, ymax = gdf.total_bounds
    return float(math.hypot(xmax - xmin, ymax - ymin))


def dispersion(gdf) -> tuple[float, float, float]:
    """(diagonal, largo total, razon) de un grupo de 'tramnomb'.

    La razon es el discriminante util. Un camino, por largo que sea, es al
    menos tan largo como la recta entre sus extremos, asi que su razon ronda
    1; con los huecos del registro sube a 2 o 3. Una ETIQUETA repartida por
    el mapa tiene una diagonal enorme y poca linea: la razon se dispara.

    OJO, aqui esto solo INFORMA, no excluye. Un umbral automatico sobre esto
    seria otra version del error que se cometio antes: se puso un limite
    absoluto de 150 km a la diagonal, sacado de los tramos vecinos a la caja
    de Amazonas, y descarto como "no es un tramo" a Xauxa - Pachacamac (163
    km), La Raya - Desaguadero (293 km), Pumpu - Pallasca (338 km) y
    Acostambo - Huamachuco (588 km), que son secciones reales del Qhapaq
    Nan, varias de ellas inscritas en la UNESCO. El registro es nacional: hay
    tramos con nombre de cientos de kilometros, y ninguna regla geometrica
    los distingue de una etiqueta con garantias.

    Quien decide es la arqueologa, y la decision queda escrita en
    'datos.tramos_excluidos'. El codigo mide y avisa.
    """
    d = diagonal(gdf)
    largo = float(gdf.geometry.length.sum())
    razon = d / largo if largo > 0 else float("inf")
    return d, largo, razon


def aplica_exclusiones(cfg, qn):
    """Quita los grupos de 'tramnomb' que la config excluye, por nombre exacto.

    Por nombre exacto y a mano, no por una regla automatica: ver `dispersion`.
    El registro usa este campo para dos cosas -- la mayoria de los valores son
    tramos ("A - B"), pero tambien aparecen estados de trabajo del Ministerio
    ("En proceso", "En Proceso") y el nombre vacio, que agrupados por nombre
    dan "tramos" de mil kilometros de diagonal.

    Devuelve (qn_limpio, [(nombre, razon)]).
    """
    if "tramnomb" not in qn.columns:
        return qn, []

    nombres = qn["tramnomb"].fillna("")
    pedidos = set(cfg.tramos_excluidos)
    fuera = sorted({str(n) for n in nombres.unique() if str(n) in pedidos})
    if not fuera:
        return qn, []

    print("\n  --- grupos de 'tramnomb' excluidos por config.yaml ---")
    for nombre in fuera:
        sub = qn[nombres == nombre]
        d, largo, razon = dispersion(sub)
        etiqueta = nombre or "(nombre vacio)"
        print(f"  '{etiqueta}': {len(sub)} rasgos, {largo / 1000:.1f} km de "
              f"linea en una caja de {d / 1000:.0f} km de diagonal "
              f"(razon {razon:.1f})")
    print("  Se quitan del registro (datos.tramos_excluidos).")
    return qn[~nombres.isin(fuera)].copy(), [(n, "excluido en config") for n in fuera]


def avisa_si_parece_etiqueta(gdf, nombre, razon_max: float = 5.0) -> str:
    """Aviso, sin excluir, cuando un grupo parece una etiqueta y no un tramo.

    Se usa sobre las unidades que SI entran al analisis: si una de ellas
    resulta ser un estado de trabajo con suficiente linea dentro de la caja,
    hay que verlo antes de comparar sus pesos con los de un camino.
    """
    d, largo, razon = dispersion(gdf)
    if razon <= razon_max:
        return ""
    return (f"'{nombre}' tiene {largo / 1000:.1f} km de linea repartidos en "
            f"una caja de {d / 1000:.0f} km de diagonal (razon {razon:.1f}). "
            "Eso parece una ETIQUETA del registro y no un tramo. Si lo es, "
            "anadelo a 'datos.tramos_excluidos' en config.yaml.")


def clasifica(nombre: str) -> str:
    """'observado', 'proyectado' u 'otro', segun el nombre de la capa."""
    n = sin_tildes(nombre)
    if any(sin_tildes(c) == n for c in OBSERVADAS):
        return "observado"
    if n.startswith("proyeccion de camino"):
        return "proyectado"
    return "otro"


def lee(ruta, crs_destino: str, solo_observadas: bool = True,
        capas_pedidas=None):
    """Lee un KML/KMZ del registro y devuelve un GeoDataFrame con atributos.

    Anade tres columnas propias: `capa` (la capa de origen), `categoria`
    ('observado' / 'proyectado') y los campos del registro extraidos del
    HTML.
    """
    import geopandas as gpd
    import pandas as pd

    kml = abrir_kmz(ruta)
    disponibles = capas(ruta)

    if capas_pedidas:
        pedidas = {sin_tildes(c) for c in capas_pedidas}
        elegidas = [c for c in disponibles if sin_tildes(c) in pedidas]
    elif solo_observadas:
        elegidas = [c for c in disponibles if clasifica(c) == "observado"]
    else:
        elegidas = [c for c in disponibles if clasifica(c) != "otro"]

    if not elegidas:
        raise SystemExit(
            f"Ninguna capa util en {pathlib.Path(ruta).name}.\n"
            f"Tiene: {disponibles}\n"
            "Si es un KMZ de otro sitio, pasa las capas a mano en config.yaml,"
            " en datos.capas_camino.")

    trozos = []
    for nombre in elegidas:
        g = gpd.read_file(kml, layer=nombre)
        g = g[~g.geometry.isna() & (g.geometry.geom_type
                                    .isin(["LineString", "MultiLineString"]))]
        if not len(g):
            continue
        at = pd.DataFrame([atributos(d) for d in g.get("description", [])],
                          index=g.index)
        salida = g[["geometry"]].copy()
        if "Name" in g:
            salida["nombre"] = g["Name"]
        for campo in CAMPOS:
            salida[campo] = at.get(campo)
        salida["capa"] = nombre
        salida["categoria"] = clasifica(nombre)
        trozos.append(salida)

    if not trozos:
        raise SystemExit("las capas elegidas no tienen ninguna polilinea")

    out = gpd.GeoDataFrame(pd.concat(trozos, ignore_index=True), crs=g.crs)
    return out.to_crs(crs_destino)


def tramos(gdf) -> "list[tuple[str, int, float, float]]":
    """Resumen por tramo: (nombre, rasgos, km totales, continuo mayor en km)."""
    from shapely.ops import linemerge, unary_union

    filas = []
    for nombre, g in gdf.groupby(gdf["tramnomb"].fillna("(sin nombre)")):
        geoms = [x for x in g.geometry if x is not None and not x.is_empty]
        if not geoms:
            continue
        u = unary_union(geoms)
        m = linemerge(u) if u.geom_type != "LineString" else u
        piezas = list(m.geoms) if m.geom_type == "MultiLineString" else [m]
        filas.append((str(nombre), len(g),
                      float(g.geometry.length.sum()) / 1000,
                      float(max(p.length for p in piezas)) / 1000))
    return sorted(filas, key=lambda f: -f[3])
