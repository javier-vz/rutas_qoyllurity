"""Linea de comandos: `python -m camino <paso>`.

El orden de los pasos no es decorativo y la ayuda lo dice.
"""

from __future__ import annotations

import argparse
import sys
import time

from . import (FECHA, __version__, buscar, caja, campo, config, pipeline,
               red, ruta as _ruta, trayectoria)

PASOS = {
    "bajar": (pipeline.bajar, "DEM (dos fuentes) y cuerpos de agua"),
    "ruta": (None, "el camino observado: de GeoCAM, de un archivo tuyo o de OSM"),
    "preparar": (pipeline.preparar_rasteres, "alinear los DEM y armar la mascara del corredor"),
    "superficies": (pipeline.construir_superficies,
                    "pendiente; la rugosidad recorta la mascara; drenaje "
                    "de diagnostico"),
    "grafo": (pipeline.construir_grafo,
              "el grafo dirigido y la matriz Phi, una columna por componente"),
    "revisar": (pipeline.revisar_grafo,
                "un camino por unidad, para MIRARLOS antes de seguir"),
    "nulos": (pipeline.correr_nulos,
              "el nulo por unidad; va ANTES del barrido"),
    "barrido": (pipeline.barrer,
                "los DOS modelos sobre cada unidad, sobre el simplex"),
    "validar": (pipeline.validar,
                "validacion bloqueada: la prueba que decide si el modelo "
                "ampliado aporta"),
    "resultados": (pipeline.resultados, "el perfil de equifinalidad y su figura"),
}

ORDEN = ("bajar", "ruta", "preparar", "superficies", "grafo", "revisar",
         "nulos", "barrido", "validar", "resultados")

# Ayudas que no son parte del pipeline: se corren cuando hacen falta.
AYUDAS = {
    "buscar": (buscar.informe,
               "encuentra la direccion del servicio de GeoCAM y la guarda"),
    "caja": (caja.informe,
             "que caja haria falta para que los tramos entren completos"),
    "campo": (campo.informe,
              "desarma la razon de costo por zonas y arma las estaciones de "
              "campo, con su GPX"),
    "red": (red.informe,
            "el Qhapaq Nan como RED: da el registro para medir centralidad?"),
    "sensibilidad": (pipeline.sensibilidad_sectores,
                     "repite el barrido con otros cortes: dice si la "
                     "estructura por sectores es real o del corte"),
    "trayectorias": (trayectoria.informe,
                     "tracks grabados: separa marcha de permanencia y dice "
                     "donde se va el tiempo"),
}

_FORZABLES = {"bajar"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m camino",
        description="Optimizacion inversa de pesos de terreno, "
                    "tramo Leimebamba - Chachapoyas.",
        epilog="Pasos en orden: " + " -> ".join(ORDEN)
               + ".  'todo' los corre todos.\n"
               + "Ayuda aparte: 'buscar' encuentra la direccion de GeoCAM "
                 "antes del paso 'ruta'.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paso", choices=(*ORDEN, "todo", *AYUDAS),
                    help="; ".join(f"{k}: {v[1]}"
                                   for k, v in (*PASOS.items(), *AYUDAS.items())))
    ap.add_argument("--config", default=None, help="ruta de config.yaml")
    ap.add_argument("--forzar", action="store_true",
                    help="vuelve a bajar lo que ya esta en disco")
    ap.add_argument("--fuente", choices=_ruta.FUENTES, default="auto",
                    help="solo con 'ruta': de donde sacar el camino observado. auto = usa el archivo que haya en datos/, y si no, GeoCAM")
    ap.add_argument("--archivo", default=None,
                    help="solo con 'ruta --fuente archivo': el .gpx/.kml/.shp")
    args = ap.parse_args(argv)

    cfg = config.Config.cargar(args.config)

    # El encabezado existe por una razon practica: cuando se pega la salida
    # de una corrida para comentarla, hay que poder saber QUE version la
    # produjo y DESDE QUE carpeta. Dos veces se discutieron numeros de una
    # version vieja sin darnos cuenta, y una de ellas fue porque el zip
    # traia otro nombre de carpeta y se descomprimio al lado.
    print(f"camino {__version__} ({FECHA})")
    print(f"proyecto: {cfg.raiz}")

    if args.paso in AYUDAS:
        fn, texto = AYUDAS[args.paso]
        print(f"=== {args.paso}: {texto} ===")
        fn(cfg)
        return 0

    pasos = ORDEN if args.paso == "todo" else (args.paso,)

    for nombre in pasos:
        fn, texto = PASOS[nombre]
        print(f"\n=== {nombre}: {texto} ===")
        t0 = time.perf_counter()
        if nombre == "ruta":
            _ruta.importar(cfg, args.fuente, args.archivo, forzar=args.forzar)
        elif nombre in _FORZABLES:
            fn(cfg, forzar=args.forzar)
        else:
            fn(cfg)
        print(f"    ({time.perf_counter() - t0:.1f} s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
