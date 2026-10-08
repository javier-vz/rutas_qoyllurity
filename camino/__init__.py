"""Optimizacion inversa de pesos de terreno sobre un recorrido observado.

El paquete no es de una zona: la zona la define el `config.yaml` del
proyecto (bbox, CRS, fuente del camino observado), y cada estudio vive en su
propia carpeta. Los ejemplos concretos que aparecen en los comentarios son
eso, ejemplos de corridas reales que explican por que una decision esta
tomada asi.

La pregunta no es "por donde paso el camino" (eso ya esta registrado, o
grabado) sino "que variables explican por donde paso, y si esas variables
son las mismas a lo largo de todo el recorrido".

Se comparan DOS modelos sobre el mismo espacio de transito: el de referencia,
que solo usa el costo fisico del terreno, y el ampliado, que le suma la
relacion con los espacios ceremoniales. El de referencia es el caso
restringido del ampliado con esos pesos en cero.

Modulos, en el orden en que se usan:

    config         parametros del proyecto, leidos de config.yaml
    descarga       DEM, camino registrado en GeoCAM, agua
    registro       categorias del registro: observado frente a proyectado
    preparar       alinear rasteres, mascara del corredor, unidades
    superficies    pendiente, aspecto, rugosidad (VRM), TWI, proximidad
    hidrologia     relleno de depresiones, D8, acumulacion
    costo          Minetti y la normalizacion por percentiles
    sitios         espacios ceremoniales y las reglas de diseno del proyecto
    visibilidad    cuenca visual: intervisibilidad con esos sitios
    grafo          grafo dirigido de vecindad 16 y la matriz Phi
    barrido        red del simplex y el barrido de pesos
    metricas       distancia media simetrica y Frechet discreta
    nulos          campos gaussianos y el valor p empirico
    equifinalidad  conjuntos casi-optimos y el perfil de Jaccard
    figuras        las dos figuras del articulo
    red            el Qhapaq Nan como RED (no la rejilla): otra pregunta
    campo          de la razon de costo a una salida de campo: estaciones
    trayectoria    tracks grabados: el camino CON reloj, marcha y permanencia
                   y, como fuente de 'ruta', el recorrido como camino observado
"""

__version__ = "0.21.0"
FECHA = "2026-10-08"
