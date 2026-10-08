"""Busca solo la direccion del servicio de GeoCAM, sin abrir el navegador.

GeoCAM corre sobre ArcGIS Server, y ArcGIS Server publica un directorio de
servicios que se puede recorrer: `<raiz>?f=json` devuelve las carpetas y los
servicios, cada servicio devuelve sus capas. Esto recorre ese arbol, puntua
las capas por su nombre y su geometria, y te dice cual pegar en config.yaml.

Si el directorio esta cerrado (algunos despliegues lo deshabilitan), no hay
nada que hacer desde aqui y toca el camino manual del README.
"""

from __future__ import annotations

import json
import pathlib
import re

import requests

HOSTS = ("geocam.cultura.gob.pe",)

# Las rutas donde suele vivir el directorio REST de ArcGIS Server, en orden
# de probabilidad.
SUFIJOS = ("server/rest/services", "arcgis/rest/services", "rest/services",
           "geocam/rest/services", "gis/rest/services")

SERVIBLES = ("MapServer", "FeatureServer")

# Palabras que delatan la capa que buscamos, con su peso.
CLAVES = {
    "qhapaq": 10, "qapaq": 10, "capac": 8, "nan": 6, "ñan": 8,
    "camino": 8, "inca": 6, "inka": 6, "vial": 5, "tramo": 4,
    "red": 2, "arqueo": 3, "monument": 2, "patrimon": 2, "sitio": 1,
}

# Lo que NO buscamos, para que no gane una capa de limites o de catastro.
RUIDO = {"limite": -4, "distrito": -4, "provincia": -4, "departamento": -4,
         "catastro": -3, "predio": -3, "curva": -3, "hidro": -2,
         "centro_poblado": -3, "via_nacional": -2, "red_vial_nacional": -3}


def _normaliza(s: str) -> str:
    return re.sub(r"[^a-zñ]+", " ", str(s).lower())


def puntua(nombre: str, geometria: str | None = None) -> int:
    """Puntuacion de una capa por su nombre y su tipo de geometria.

    Una capa de lineas con 'qhapaq' en el nombre gana; una de poligonos de
    limites distritales pierde.
    """
    t = _normaliza(nombre)
    p = sum(peso for clave, peso in CLAVES.items() if clave in t)
    p += sum(peso for clave, peso in RUIDO.items() if clave in _normaliza(nombre))
    if geometria:
        g = str(geometria).lower()
        if "polyline" in g or "line" in g:
            p += 4          # el camino es una linea
        elif "point" in g:
            p += 1          # podrian ser los tambos o los sitios
        elif "polygon" in g:
            p -= 1
    return p


def raices(hosts=HOSTS) -> list[str]:
    """Las URL del directorio REST que vale la pena probar."""
    return [f"https://{h}/{s}" for h in hosts for s in SUFIJOS]


def _pide(sesion, url: str, timeout: int = 25):
    """GET que devuelve el JSON o None, sin levantar excepciones."""
    from . import wfs
    try:
        r = sesion.get(url, params={"f": "json"}, timeout=timeout,
                       headers=wfs.CABECERAS)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        d = r.json()
    except ValueError:
        return None
    return d if isinstance(d, dict) and "error" not in d else None


def recorre(raiz: str, sesion=None, max_carpetas: int = 40) -> list[dict]:
    """Lista los servicios de un directorio REST, entrando en sus carpetas.

    Devuelve [{'url': ..., 'nombre': ..., 'tipo': ...}, ...]. Lista vacia si
    el directorio no responde o esta cerrado.
    """
    sesion = sesion or requests.Session()
    base = _pide(sesion, raiz)
    if base is None:
        return []

    pendientes = [raiz]
    for carpeta in (base.get("folders") or [])[:max_carpetas]:
        pendientes.append(f"{raiz}/{carpeta}")

    servicios = []
    for ruta in pendientes:
        d = base if ruta == raiz else _pide(sesion, ruta)
        if d is None:
            continue
        for s in d.get("services") or []:
            tipo = s.get("type")
            if tipo not in SERVIBLES:
                continue
            # el nombre puede venir ya con la carpeta delante
            nombre = str(s.get("name", ""))
            servicios.append({
                "url": f"{raiz}/{nombre}/{tipo}",
                "nombre": nombre.rsplit("/", 1)[-1],
                "tipo": tipo,
            })
    return servicios


def capas(servicio: dict, sesion=None) -> list[dict]:
    """Las capas de un servicio, cada una con su puntuacion."""
    sesion = sesion or requests.Session()
    d = _pide(sesion, servicio["url"])
    if d is None:
        return []
    salida = []
    for capa in d.get("layers") or []:
        if capa.get("subLayerIds"):
            continue                       # es un grupo, no una capa
        nombre = str(capa.get("name", ""))
        geom = capa.get("geometryType")
        salida.append({
            "url": f"{servicio['url']}/{capa.get('id')}",
            "servicio": servicio["nombre"],
            "capa": nombre,
            "geometria": str(geom).replace("esriGeometry", "") if geom else "?",
            "puntos": puntua(f"{servicio['nombre']} {nombre}", geom),
        })
    return salida


def candidatas(hosts=HOSTS, sesion=None, limite: int = 12) -> list[dict]:
    """Recorre los directorios y devuelve las capas mejor puntuadas."""
    sesion = sesion or requests.Session()
    todas: list[dict] = []
    for raiz in raices(hosts):
        servicios = recorre(raiz, sesion)
        if not servicios:
            continue
        print(f"  {raiz}: {len(servicios)} servicios")
        for s in servicios:
            todas.extend(capas(s, sesion))
        if todas:
            break                          # con un directorio que responda basta
    todas.sort(key=lambda c: -c["puntos"])
    return todas[:limite]


def guarda_en_config(ruta_config, valor: str, clave: str = "geocam_servicio") -> None:
    """Escribe un valor en una linea de config.yaml sin tocar nada mas.

    Se edita la linea con una expresion regular en vez de reescribir el YAML,
    para no perder los comentarios del archivo.
    """
    ruta_config = pathlib.Path(ruta_config)
    texto = ruta_config.read_text(encoding="utf-8")
    nuevo, n = re.subn(rf'(?m)^(\s*{re.escape(clave)}\s*:\s*).*$',
                       lambda m: f'{m.group(1)}"{valor}"', texto, count=1)
    if n != 1:
        raise ValueError(f"no encontre la linea '{clave}:' en config.yaml")
    ruta_config.write_text(nuevo, encoding="utf-8")


def capas_wfs(sesion=None, endpoints=None, rondas: int = 2,
              registro=None) -> tuple[str, str, list[dict]]:
    """Las capas publicadas por el WFS, puntuadas. Via preferida.

    Devuelve (endpoint, version, capas). El endpoint es vacio si ninguno
    responde: el proxy del Ministerio de Cultura falla de forma intermitente
    con un 500 ('Error during SSL Handshake'), asi que se prueban varias
    rutas y cada una con reintentos.
    """
    from . import wfs

    sesion = sesion or wfs.sesion_nueva()
    eps = endpoints or wfs.ENDPOINTS_GEOCAM
    base, version, xml = wfs.busca_endpoint(sesion, eps, rondas=rondas,
                                            registro=registro)
    if not base:
        return "", "", []

    salida = []
    for c in wfs.lee_capabilities(xml):
        texto = f"{c['nombre']} {c['titulo']} {c.get('resumen', '')}"
        salida.append({
            "fuente": "wfs",
            "url": base,
            "capa": c["nombre"],
            "titulo": c["titulo"],
            "crs": c.get("crs", ""),
            "puntos": puntua(texto),
        })
    salida.sort(key=lambda c: -c["puntos"])
    return base, version, salida


def informe_wfs(cfg, guardar: bool = True) -> list[dict]:
    """Prueba el WFS y, si responde, guarda endpoint y capa en config.yaml."""
    from . import wfs

    print("Probando el WFS de GeoCAM (estandar OGC)...")
    registro: list = []
    base, version, enc = capas_wfs(registro=registro)

    if not base:
        print("\n  Ningun endpoint WFS respondio. Esto dijo cada uno:\n")
        for endpoint, lineas in registro:
            print(f"  {endpoint}")
            for linea in lineas or ["sin detalle"]:
                print(f"      {linea}")
        print("\n  Como leerlo:")
        print("    '500 Proxy Error'  -> el servidor del Ministerio esta caido")
        print("                          ahora mismo. No es tuyo. Reintenta.")
        print("    '403' o '406'      -> el servidor rechaza al cliente.")
        print("    'ConnectionError'  -> no hay salida a internet, o un")
        print("                          cortafuegos corta la conexion.")
        print("    'SSLError'         -> el certificado del servidor; si estas")
        print("                          en una red institucional, puede ser")
        print("                          su proxy el que se mete en medio.")
        print("\n  Comprueba si el servidor esta vivo pegando esto en el")
        print("  navegador. Si sale XML, esta vivo y el problema es de aqui:")
        print("    https://geoservicios.cultura.gob.pe/geoserver/wfs"
              "?service=WFS&version=1.1.0&request=GetCapabilities")
        return []

    print(f"\n  Responde: {base}  (WFS {version}, {len(enc)} capas)\n")
    for i, c in enumerate(enc[:12], 1):
        print(f"  {i:2d}. [{c['puntos']:+3d}] {c['capa']}")
        if c["titulo"] and c["titulo"] != c["capa"]:
            print(f"      {c['titulo']}")

    ruta = cfg.raiz / "config.yaml"
    if guardar:
        guarda_en_config(ruta, base, clave="geocam_wfs")
        if enc and enc[0]["puntos"] > 0:
            guarda_en_config(ruta, enc[0]["capa"], clave="geocam_capa")
            print(f"\n  Guardado en {ruta.name}:")
            print(f"    geocam_wfs:  {base}")
            print(f"    geocam_capa: {enc[0]['capa']}")
            print("\n  Ahora corre:  python -m camino geocam")
        else:
            print(f"\n  Guardado el endpoint en {ruta.name}, pero ninguna capa")
            print("  tiene pinta de ser el camino. Mira la lista de arriba y")
            print("  pon a mano la que reconozcas en la linea 'geocam_capa'.")
    return enc


def informe(cfg, guardar: bool = True) -> list[dict]:
    """Busca la direccion de GeoCAM: primero por WFS, luego por ArcGIS REST."""
    enc = informe_wfs(cfg, guardar)
    if enc:
        return enc

    print("\n" + "-" * 60)
    print("Probando la otra via: el directorio de ArcGIS REST...")
    enc = candidatas()

    if not enc:
        print("\n  No pude leer el directorio de servicios.")
        print("  Puede estar cerrado, caido, o bloqueando peticiones de fuera")
        print("  del navegador. Toca el camino manual: README.md, paso 3.")
        return []

    print(f"\n  {len(enc)} capas candidatas, de mas a menos probable:\n")
    for i, c in enumerate(enc, 1):
        print(f"  {i:2d}. [{c['puntos']:+3d}] {c['capa']}  ({c['geometria']})")
        print(f"      servicio: {c['servicio']}")
        print(f"      {c['url']}")

    mejor = enc[0]
    if mejor["puntos"] <= 0:
        print("\n  Ninguna tiene pinta de ser el camino. Mira la lista y pega")
        print("  a mano la que reconozcas en config.yaml, en geocam_servicio.")
        return enc

    ruta = cfg.raiz / "config.yaml"
    if guardar:
        guarda_en_config(ruta, mejor["url"])
        print(f"\n  Guardada la nº 1 en {ruta.name}:")
        print(f"    {mejor['url']}")
        print("\n  Ahora corre:  python -m camino geocam")
        print("  Si trae pocos rasgos o ninguno, era otra capa: pega a mano")
        print("  la nº 2 o la nº 3 de la lista y vuelve a correrlo.")
    return enc


def guardar_json(cfg, enc) -> pathlib.Path:
    ruta = cfg.dir_resultados / "capas_geocam.json"
    ruta.write_text(json.dumps(enc, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return ruta
