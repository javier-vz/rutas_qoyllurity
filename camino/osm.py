"""Cliente de Overpass, la API de consulta de OpenStreetMap.

Tres cosas que Overpass exige y que es facil hacer mal:

1. La consulta va por POST, en el cuerpo. Por GET en la URL funciona a
   veces, pero varios espejos devuelven 406 Not Acceptable, que es
   exactamente lo que parece: "asi no te acepto la peticion".
2. Hay que identificarse con un User-Agent de verdad. Overpass es un
   servicio gratuito y limita a los clientes anonimos.
3. Se satura. El 429 (demasiadas peticiones) y el 504 (se acabo el tiempo)
   son normales y se resuelven reintentando o cambiando de espejo.
"""

from __future__ import annotations

import time

import requests

# Espejos publicos, en orden. El primero es el principal; los otros son
# independientes y suelen estar libres cuando el principal se satura.
ESPEJOS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)

CABECERAS = {
    "User-Agent": ("camino-leimebamba/0.1 "
                   "(investigacion arqueologica; contacto por el repositorio)"),
    "Accept": "application/json",
}

# Codigos que merecen reintentar o cambiar de espejo.
TRANSITORIOS = (429, 500, 502, 503, 504, 406)


def consulta(q: str, sesion=None, espejos=ESPEJOS, intentos: int = 2,
             espera: float = 5.0, timeout: int = 300) -> dict:
    """Corre una consulta de Overpass y devuelve el JSON.

    Prueba cada espejo, y si todos fallan por algo transitorio, repite la
    ronda. Levanta RuntimeError con el detalle si no hay manera.
    """
    sesion = sesion or requests.Session()
    fallos = []

    for intento in range(max(1, intentos)):
        for url in espejos:
            try:
                r = sesion.post(url, data={"data": q}, headers=CABECERAS,
                                timeout=timeout)
            except requests.RequestException as e:
                fallos.append(f"{url}: {type(e).__name__}")
                continue

            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    fallos.append(f"{url}: respondio algo que no es JSON")
                    continue

            fallos.append(f"{url}: HTTP {r.status_code}")
            if r.status_code not in TRANSITORIOS:
                break
        if intento < intentos - 1:
            time.sleep(espera)

    raise RuntimeError("Overpass no respondio en ningun espejo:\n  "
                       + "\n  ".join(fallos[-6:]))


def caja(bbox) -> str:
    """La caja en el orden que usa Overpass: sur, oeste, norte, este."""
    oeste, sur, este, norte = bbox
    return f"{sur},{oeste},{norte},{este}"


def consulta_agua(bbox) -> str:
    """Rios y cuerpos de agua permanentes."""
    c = caja(bbox)
    return ("[out:json][timeout:180];"
            f'(way["waterway"="river"]({c});'
            f' way["waterway"="stream"]({c});'
            f' way["natural"="water"]({c});'
            f' relation["natural"="water"]({c}););'
            "out geom;")


def consulta_camino(bbox) -> str:
    """Trazas que puedan ser el camino inca.

    Se piden las vias con etiqueta `historic` y las que llevan 'inca',
    'qhapaq' o 'camino' en el nombre. No se piden todos los senderos: en los
    Andes hay miles y ninguno dice de cual se trata.
    """
    c = caja(bbox)
    return ("[out:json][timeout:180];"
            f'(way["historic"]({c});'
            f' way["name"~"[Ii]nca|[Qq]hapaq|[Cc]amino|[Ññ]an"]({c});'
            f' relation["route"="hiking"]({c});'
            f' way["highway"="path"]["name"~"[Ii]nca|[Qq]hapaq"]({c}););'
            "out geom;")


def lineas(d: dict, crs_destino: str):
    """Convierte la respuesta de Overpass en un GeoDataFrame de lineas."""
    import geopandas as gpd
    from shapely.geometry import LineString

    filas, geoms = [], []
    for el in d.get("elements", []):
        pts = [(p["lon"], p["lat"]) for p in el.get("geometry", []) or []]
        if len(pts) < 2:
            continue
        tags = el.get("tags", {})
        filas.append({"osm_id": el.get("id"),
                      "nombre": tags.get("name", ""),
                      "historic": tags.get("historic", ""),
                      "highway": tags.get("highway", ""),
                      "waterway": tags.get("waterway", ""),
                      "natural": tags.get("natural", "")})
        geoms.append(LineString(pts))

    if not geoms:
        return gpd.GeoDataFrame({"osm_id": []}, geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame(filas, geometry=geoms,
                            crs="EPSG:4326").to_crs(crs_destino)
