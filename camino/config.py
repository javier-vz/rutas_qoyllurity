"""Parametros del proyecto, leidos de config.yaml.

Todo numero que se pueda discutir vive aqui y en ningun otro sitio. Si un
umbral aparece escrito en el codigo, es un bug.

La llave de OpenTopography se toma primero de la variable de entorno
OPENTOPOGRAPHY_API_KEY y solo despues del archivo, para que no acabe en el
control de versiones.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib

import yaml

from . import grafo

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def _avisa_de_la_version(ruta, d) -> None:
    """Avisa si el config.yaml es de otra version del paquete.

    El paquete trae su config.yaml, asi que al actualizar se reemplaza y
    normalmente no hay desajuste. Esto cubre el caso contrario: que al
    descomprimir se haya elegido NO reemplazarlo, y entonces le falten
    parametros nuevos (que se usan con su valor por omision, pero conviene
    saberlo).

    Lo que de verdad protege no es esto, es `preparar.comprueba_rejilla`: el
    desajuste peligroso es entre el bbox y los rasteres de derivados/, y ese
    no avisa, para.
    """
    from . import __version__

    suya = str((d or {}).get("version") or "")
    if suya and suya != __version__:
        print(f"  (tu {pathlib.Path(ruta).name} dice version {suya} y el "
              f"programa es {__version__};")
        print("   si algo no cuadra, compara con el config.yaml del zip.)")


@dataclasses.dataclass(frozen=True)
class Config:
    raiz: pathlib.Path

    # extension del estudio
    bbox: tuple[float, float, float, float]   # oeste, sur, este, norte (grados)
    crs: str
    resolucion: float

    # acceso a datos
    api_key: str
    geocam_wfs: str          # endpoint WFS (la via preferida)
    geocam_capa: str         # nombre de la capa dentro del WFS, si ya se sabe
    geocam_servicio: str     # alternativa: capa de ArcGIS REST
    solo_observadas: bool    # excluir las capas de "Proyeccion..."
    capas_camino: tuple      # capas concretas, si se quieren fijar
    tramo: str               # tramo del registro a estudiar
    tramos_excluidos: tuple  # grupos de 'tramnomb' que no son tramos

    # modelo de costo: dos modelos con las mismas restricciones
    g_max: float
    epsilon: float
    percentiles: tuple[float, float]
    componentes_referencia: tuple[str, ...]
    componentes_ampliado: tuple[str, ...]
    vecindad: int

    # restricciones geomorfologicas: delimitan, no pesan
    rugosidad_percentil: float
    ceremonial_archivo: str
    ceremonial_saturacion: float
    ceremonial_radio_extremos: float
    visibilidad_radio: float
    visibilidad_puntos: tuple
    altura_observador: float
    altura_objetivo: float

    # dominio
    buffer_corredor: float
    area_min_laguna: float
    umbral_quebrada: float

    # barrido e inferencia
    n_simplex: int
    unidad: str
    largo_min_unidad: float
    n_sectores: int
    n_bloques: int
    largo_min_bloque: float
    m_nulos: int
    tau_max: float
    semilla: int
    n_trabajos: int

    # trayectorias observadas (tracks con sello de tiempo)
    parada_radio: float
    parada_min_s: float
    parada_criterio: str
    trayectoria_paso: float
    trayectoria_hueco_s: float
    v_max_a_pie: float

    @classmethod
    def cargar(cls, ruta: str | pathlib.Path | None = None) -> "Config":
        ruta = pathlib.Path(ruta) if ruta else RAIZ / "config.yaml"
        if not ruta.exists():
            raise SystemExit(
                f"No hay {ruta.name} en {ruta.parent}.\n"
                "El paquete lo trae, asi que o la carpeta no es la del\n"
                "proyecto, o la extraccion se lo llevo. Vuelve a descomprimir\n"
                "el zip encima: trae config.yaml con la caja del estudio.")
        with open(ruta, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f)
        _avisa_de_la_version(ruta, d)

        bbox = d["extension"]["bbox"]
        llave = os.environ.get("OPENTOPOGRAPHY_API_KEY") \
            or d["datos"].get("api_key_opentopography") or ""

        return cls(
            raiz=ruta.resolve().parent,
            bbox=(float(bbox["oeste"]), float(bbox["sur"]),
                  float(bbox["este"]), float(bbox["norte"])),
            crs=str(d["extension"]["crs"]),
            resolucion=float(d["extension"]["resolucion"]),
            api_key=str(llave),
            geocam_wfs=str(d["datos"].get("geocam_wfs") or ""),
            geocam_capa=str(d["datos"].get("geocam_capa") or ""),
            geocam_servicio=str(d["datos"].get("geocam_servicio") or ""),
            solo_observadas=bool(d["datos"].get("solo_observadas", True)),
            capas_camino=tuple(d["datos"].get("capas_camino") or ()),
            tramo=str(d["datos"].get("tramo") or ""),
            tramos_excluidos=tuple(
                "" if x is None else str(x)
                for x in (d["datos"].get("tramos_excluidos") or ())),
            g_max=float(d["costo"]["g_max"]),
            epsilon=float(d["costo"]["epsilon"]),
            percentiles=tuple(float(v) for v in d["costo"]["percentiles"]),
            componentes_referencia=tuple(d["costo"]["componentes_referencia"]),
            componentes_ampliado=tuple(d["costo"]["componentes_ampliado"]),
            vecindad=int(d["costo"]["vecindad"]),
            rugosidad_percentil=float(
                d.get("restricciones", {}).get("rugosidad_percentil", 99.0)),
            ceremonial_archivo=str(
                d.get("ceremonial", {}).get("archivo") or ""),
            ceremonial_saturacion=float(
                d.get("ceremonial", {}).get("distancia_saturacion", 5000)),
            ceremonial_radio_extremos=float(
                d.get("ceremonial", {}).get("radio_extremos", 500)),
            visibilidad_radio=float(
                d.get("visibilidad", {}).get("radio", 8000)),
            visibilidad_puntos=tuple(
                d.get("visibilidad", {}).get("puntos") or ()),
            altura_observador=float(
                d.get("visibilidad", {}).get("altura_observador", 1.65)),
            altura_objetivo=float(
                d.get("visibilidad", {}).get("altura_objetivo", 0.0)),
            buffer_corredor=float(d["dominio"]["buffer_corredor"]),
            area_min_laguna=float(
                d.get("restricciones", {}).get("area_min_laguna", 50000)),
            umbral_quebrada=float(d["dominio"]["umbral_quebrada"]),
            n_simplex=int(d["barrido"]["n_simplex"]),
            unidad=str(d["barrido"].get("unidad", "tramo")),
            largo_min_unidad=float(d["barrido"].get("largo_min_unidad", 8000)),
            n_sectores=int(d["barrido"]["n_sectores"]),
            n_bloques=int(d["barrido"].get("n_bloques", 4)),
            largo_min_bloque=float(
                d["barrido"].get("largo_min_bloque", 500)),
            m_nulos=int(d["barrido"]["m_nulos"]),
            tau_max=float(d["barrido"]["tau_max"]),
            semilla=int(d["barrido"]["semilla"]),
            n_trabajos=int(d["barrido"]["n_trabajos"]),
            parada_radio=float(
                d.get("trayectorias", {}).get("radio_parada", 20.0)),
            parada_min_s=float(
                d.get("trayectorias", {}).get("min_parada_s", 120.0)),
            parada_criterio=str(
                d.get("trayectorias", {}).get("criterio") or "ambos"),
            trayectoria_paso=float(
                d.get("trayectorias", {}).get("paso", 30.0)),
            trayectoria_hueco_s=float(
                d.get("trayectorias", {}).get("hueco_s", 300.0)),
            v_max_a_pie=float(
                d.get("trayectorias", {}).get("v_max_a_pie", 4.0)),
        )

    # ----------------------------------------------------------- derivados

    @property
    def dir_datos(self) -> pathlib.Path:
        return self._dir("datos")

    @property
    def dir_derivados(self) -> pathlib.Path:
        return self._dir("derivados")

    @property
    def dir_resultados(self) -> pathlib.Path:
        return self._dir("resultados")

    def _dir(self, nombre: str) -> pathlib.Path:
        p = self.raiz / nombre
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def vecinos(self):
        if self.vecindad == 16:
            return grafo.VECINOS_16
        if self.vecindad == 8:
            return grafo.VECINOS_8
        raise ValueError("la vecindad tiene que ser 8 o 16")

    @property
    def modelos(self) -> dict[str, tuple[str, ...]]:
        """Los dos modelos que se comparan, por nombre."""
        return {"referencia": self.componentes_referencia,
                "ampliado": self.componentes_ampliado}

    @property
    def componentes(self) -> tuple[str, ...]:
        """Union de las componentes de los dos modelos, 'fisico' primera.

        El grafo se construye UNA vez con todas; cada modelo se evalua
        poniendo a cero los pesos de las que no usa. Asi los dos comparten
        exactamente el mismo espacio de transito, que es lo que el proyecto
        exige para que la diferencia sea atribuible a las componentes.
        """
        vistas = list(self.componentes_referencia)
        for c in self.componentes_ampliado:
            if c not in vistas:
                vistas.append(c)
        if "fisico" in vistas:
            vistas.remove("fisico")
        return ("fisico",) + tuple(vistas)

    @property
    def k(self) -> int:
        return len(self.componentes)

    @property
    def componentes_simetricas(self) -> tuple[str, ...]:
        """Las que son propiedad de la celda, no del paso."""
        return tuple(c for c in self.componentes if c != "fisico")

    def exige_llave(self) -> str:
        if not self.api_key:
            raise SystemExit(
                "Falta la llave de OpenTopography.\n"
                "  1. Entra a https://portal.opentopography.org/ -> My Account\n"
                "  2. Pide una llave (es gratis e inmediata)\n"
                "  3. En la consola de Anaconda:\n"
                "       Windows:  set OPENTOPOGRAPHY_API_KEY=tu_llave\n"
                "       Linux/Mac: export OPENTOPOGRAPHY_API_KEY=tu_llave\n"
                "     o pegala en config.yaml, en datos.api_key_opentopography")
        return self.api_key

    def fuente_geocam(self) -> tuple[str, str]:
        """Por donde bajar el camino: ('wfs', url) o ('rest', url).

        El WFS tiene prioridad: es el estandar OGC que el propio portal
        publica, no una URL interna sacada del trafico del navegador.
        """
        if self.geocam_wfs:
            return "wfs", self.geocam_wfs.split("?")[0].rstrip("/")
        if self.geocam_servicio:
            return "rest", self.geocam_servicio.rstrip("/").removesuffix("/query")
        raise SystemExit(
            "Falta la direccion de GeoCAM. Hay dos vias, de mas a menos comoda:\n"
            "\n"
            "  A) WFS, la estandar. En https://geocam.cultura.gob.pe/ hay una\n"
            "     seccion 'Servicios web' con iconos de WMS, WFS y KML. Haz clic\n"
            "     en el de WFS y copia la direccion que te de (lleva '/wfs' o\n"
            "     'service=WFS' dentro). Pegala en config.yaml, en la linea\n"
            "     'geocam_wfs'. Luego corre:  python -m camino buscar\n"
            "     para que te liste las capas y elija la del camino.\n"
            "\n"
            "  B) ArcGIS REST, si el WFS no responde. Esta en el README,\n"
            "     paso 3, opcion C. Va en la linea 'geocam_servicio'.")

    def exige_geocam(self) -> str:
        """La URL de ArcGIS REST, para el camino alternativo."""
        clase, url = self.fuente_geocam()
        if clase != "rest":
            raise SystemExit("esta configurado el WFS, no el servicio REST")
        return url
