"""Cliente WFS: la via estandar para bajar la geometria de GeoCAM.

GeoCAM publica sus capas bajo el estandar OGC (WMS, WFS, KML). El WFS es el
que devuelve los vectores, asi que es por aqui por donde hay que entrar: es
una interfaz documentada y estable, no una URL interna sacada del trafico del
navegador.

Dos operaciones bastan:

    GetCapabilities  -> que capas hay, con que nombre y en que CRS
    GetFeature       -> la geometria de una capa

El XML de capabilities se lee ignorando los espacios de nombres, porque la
version 1.1.0 y la 2.0.0 usan distintos y no vale la pena adivinar cual sirve
cada servidor.
"""

from __future__ import annotations

import io
import time
import xml.etree.ElementTree as ET

import requests

VERSIONES = ("2.0.0", "1.1.0", "1.0.0")

# El GeoServer del Ministerio de Cultura, detras de un proxy que falla a
# ratos con "Error during SSL Handshake with remote server" (un 500 que no
# es culpa de la peticion). Se prueban varias rutas porque la del workspace
# puede caerse mientras la global contesta, y al reves.
ENDPOINTS_GEOCAM = (
    "https://geoservicios.cultura.gob.pe/geoserver/wfs",
    "https://geoservicios.cultura.gob.pe/geoserver/ows",
    "https://geoservicios.cultura.gob.pe/geoserver/cultura/wfs",
    "https://geoservicios.cultura.gob.pe/geoserver/cultura/ows",
)

# Codigos que merecen reintento: son del proxy, no de la peticion.
TRANSITORIOS = (500, 502, 503, 504, 408, 429)

# Muchos portales del Estado rechazan o maltratan a los clientes que no se
# presentan como navegador: el mismo URL que funciona en Chrome devuelve 500
# o 403 desde `python-requests/2.x`. Presentarse como navegador no es un
# truco sucio, es pedir lo mismo que pide la pestana del navegador.
CABECERAS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "text/xml,application/xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}


def sesion_nueva():
    """Una sesion de requests que se presenta como navegador."""
    s = requests.Session()
    s.headers.update(CABECERAS)
    return s


def diagnostico(r, error=None) -> str:
    """Una linea que dice que paso de verdad, para no esconder el fallo."""
    if error is not None:
        return f"{type(error).__name__}: {str(error)[:90]}"
    if r is None:
        return "sin respuesta"
    cuerpo = (r.text or "")[:200].replace("\n", " ")
    if r.status_code == 200:
        return f"200, pero sin capas ({cuerpo[:70]}...)"
    if "SSL Handshake" in cuerpo:
        return f"{r.status_code} Proxy Error (SSL Handshake con su backend)"
    return f"{r.status_code} {cuerpo[:70]}"

# Como se llama el parametro del limite de rasgos en cada version. En 2.0.0
# cambio de nombre, y usar el que no toca hace que el servidor lo ignore.
LIMITE = {"2.0.0": "count", "1.1.0": "maxFeatures", "1.0.0": "maxFeatures"}

# Formatos de salida que geopandas lee directo, de mejor a peor.
FORMATOS_JSON = ("application/json", "application/geo+json", "geojson",
                 "json", "application/vnd.geo+json")


def _local(tag: str) -> str:
    """Nombre de etiqueta sin su espacio de nombres."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _texto(elem, *nombres) -> str:
    for hijo in elem:
        if _local(hijo.tag) in nombres and hijo.text:
            return hijo.text.strip()
    return ""


def url_capabilities(base: str, version: str = "2.0.0",
                     solo_capas: bool = False):
    """Parametros de un GetCapabilities.

    Con `solo_capas`, pide unicamente la seccion FeatureTypeList. El
    documento completo de GeoServer trae antes toda la lista de funciones de
    filtrado y pesa megas; la seccion sola pesa unos kilobytes, y es lo unico
    que hace falta para saber que capas hay.
    """
    p = {"service": "WFS", "version": version, "request": "GetCapabilities"}
    if solo_capas and version.startswith("2."):
        p["sections"] = "FeatureTypeList"
    return base, p


def pide(sesion, url, params, timeout=60, intentos=3, espera=2.0,
         registro=None):
    """GET con reintentos ante fallos del proxy.

    El proxy del Ministerio devuelve 500 de forma intermitente. Reintentar
    con una espera creciente resuelve buena parte de esos fallos, y lo que
    no, al menos no se confunde con "la capa no existe".
    """
    ultima, ultimo_error = None, None
    for intento in range(max(1, intentos)):
        try:
            r = sesion.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            ultimo_error = e          # de red: se reintenta
        else:
            ultima, ultimo_error = r, None
            if r.status_code == 200 or r.status_code not in TRANSITORIOS:
                if registro is not None and r.status_code != 200:
                    registro.append(diagnostico(r))
                return r              # bien, o mal de una forma definitiva
        if intento < intentos - 1:
            time.sleep(espera * (intento + 1))
    if registro is not None:
        registro.append(diagnostico(ultima, ultimo_error))
    return ultima                     # None solo si todos los intentos fallaron


def lee_capabilities(xml_texto: str) -> list[dict]:
    """Las capas publicadas, leidas del XML de GetCapabilities."""
    try:
        raiz = ET.fromstring(xml_texto)
    except ET.ParseError:
        return []

    capas = []
    for elem in raiz.iter():
        if _local(elem.tag) != "FeatureType":
            continue
        nombre = _texto(elem, "Name")
        if not nombre:
            continue
        capas.append({
            "nombre": nombre,
            "titulo": _texto(elem, "Title") or nombre,
            "resumen": _texto(elem, "Abstract"),
            "crs": _texto(elem, "DefaultCRS", "DefaultSRS", "SRS"),
        })
    return capas


def formatos_salida(xml_texto: str) -> list[str]:
    """Los valores admitidos de `outputFormat`, segun el propio servidor."""
    try:
        raiz = ET.fromstring(xml_texto)
    except ET.ParseError:
        return []
    salida = []
    for elem in raiz.iter():
        if _local(elem.tag) != "Parameter":
            continue
        if elem.get("name") != "outputFormat":
            continue
        for hijo in elem.iter():
            if _local(hijo.tag) == "Value" and hijo.text:
                salida.append(hijo.text.strip())
    return salida


def formato_json(formatos) -> str | None:
    """El primer formato de la lista que geopandas pueda leer como JSON."""
    bajos = {f.lower(): f for f in formatos}
    for preferido in FORMATOS_JSON:
        if preferido in bajos:
            return bajos[preferido]
    for bajo, original in bajos.items():
        if "json" in bajo:
            return original
    return None


def url_getfeature(base: str, capa: str, version: str = "2.0.0",
                   formato: str | None = None, srs: str | None = None,
                   limite: int | None = None):
    """Parametros de un GetFeature.

    Deliberadamente SIN `bbox`. El orden de los ejes del bbox cambio entre
    la version 1.1.0 y la 2.0.0 (lon/lat frente a lat/lon) y cada servidor lo
    interpreta a su manera, asi que un bbox mal entendido devuelve cero
    rasgos sin avisar. Se baja la capa entera y se recorta despues con
    geopandas, que sabe exactamente en que CRS esta cada cosa.
    """
    tipo = "typeNames" if version.startswith("2.") else "typeName"
    p = {"service": "WFS", "version": version, "request": "GetFeature",
         tipo: capa}
    if formato:
        p["outputFormat"] = formato
    if srs:
        p["srsName"] = srs
    if limite:
        p[LIMITE.get(version, "count")] = int(limite)
    return base, p


def capabilities(base: str, sesion=None, timeout: int = 60,
                 intentos: int = 1, espera: float = 0.0, registro=None):
    """Prueba las versiones de WFS y devuelve (version, xml) de la primera
    que conteste con capas. (None, "") si ninguna contesta.

    Por omision NO reintenta: son hasta cinco peticiones (tres versiones, y
    en la 2.0.0 tambien el documento completo), y reintentar cada una con
    espera creciente convierte un servidor caido en minutos de bloqueo. El
    reintento ante el proxy averiado lo hace `busca_endpoint`, que repite el
    barrido entero, y `descarga_capa`, que si insiste sobre una sola URL.
    """
    sesion = sesion or sesion_nueva()
    for version in VERSIONES:
        # la seccion corta primero; si el servidor la ignora, el documento
        # completo
        for solo in (True, False):
            if solo and not version.startswith("2."):
                continue
            url, p = url_capabilities(base, version, solo_capas=solo)
            propio = []
            r = pide(sesion, url, p, timeout=timeout,
                     intentos=intentos, espera=espera, registro=propio)
            if r is not None and r.status_code == 200 and r.text:
                if lee_capabilities(r.text):
                    return version, r.text
                propio = propio or [diagnostico(r)]
            if registro is not None and propio:
                registro.append(f"WFS {version}: {propio[0]}")
    return None, ""


def busca_endpoint(sesion=None, endpoints=ENDPOINTS_GEOCAM, timeout: int = 60,
                   rondas: int = 2, espera: float = 5.0, registro=None):
    """El primer endpoint de la lista que conteste con capas.

    Devuelve (endpoint, version, xml) o (None, None, ""). Se prueban varias
    rutas porque el proxy del Ministerio tumba unas y deja otras en pie, y
    el barrido entero se repite `rondas` veces porque el fallo es
    intermitente: lo que no contesta ahora puede contestar en diez segundos.
    """
    sesion = sesion or sesion_nueva()
    for ronda in range(max(1, rondas)):
        for base in endpoints:
            propio = []
            version, xml = capabilities(base, sesion, timeout, registro=propio)
            if version:
                return base, version, xml
            if registro is not None and ronda == 0:
                registro.append((base, propio))
        if ronda < rondas - 1:
            time.sleep(espera)
    return None, None, ""


def descarga_capa(base: str, capa: str, version: str, formato: str | None,
                  crs_destino: str, sesion=None, timeout: int = 600,
                  limite: int | None = None):
    """Baja una capa completa y la devuelve como GeoDataFrame reproyectado."""
    import geopandas as gpd

    sesion = sesion or sesion_nueva()
    url, p = url_getfeature(base, capa, version, formato, limite=limite)
    r = pide(sesion, url, p, timeout=timeout, intentos=4)
    if r is None:
        raise RuntimeError(
            f"no hubo respuesta del WFS en {base} despues de 4 intentos")
    r.raise_for_status()

    if r.text.lstrip().startswith("<") and "ExceptionReport" in r.text[:2000]:
        raise RuntimeError(f"el servidor WFS devolvio un error:\n{r.text[:500]}")

    # GeoJSON si lo hay; si no, GML, que geopandas lee por OGR.
    gdf = gpd.read_file(io.BytesIO(r.content))
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf.to_crs(crs_destino)
