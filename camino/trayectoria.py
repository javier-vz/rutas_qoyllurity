"""Trayectorias observadas: el camino que viene con reloj.

Todo lo que el paquete sabia leer hasta ahora son LINEAS: el registro del
Ministerio, un KMZ, unas trazas de OSM. Una linea tiene forma y no tiene
tiempo, asi que de ella solo se puede preguntar por donde va. Un track
grabado tiene las dos cosas, y eso cambia la pregunta: se puede preguntar
tambien CUANDO se paso por cada parte, cuanto se tardo y donde se estuvo
quieto.

Eso importa porque hay recorridos cuyo costo no esta en los metros. En la
peregrinacion de Qoyllur Rit'i cerca de la mitad del tiempo a pie se pasa
parado. Una ruta de minimo costo no puede producir eso: es una curva que
minimiza una integral de linea y no tiene reloj. Si el recorrido esta
organizado por estaciones y por horas, entonces lo que hay que medir es
tiempo y lugar, no distancia y pendiente, y para eso hace falta separar la
MARCHA de la PERMANENCIA.

SEPARAR MARCHA DE PERMANENCIA NO ES PONER UN UMBRAL AL DESPLAZAMIENTO
------------------------------------------------------------------------
Es la tentacion obvia y esta mal. Con 16 s entre puntos, un receptor quieto
produce fixes que bailan dentro de su propia precision -- aqui el hdop
mediano es 3, o sea varios metros-- asi que cualquier umbral por debajo de
ese ruido clasifica las paradas como marcha, y cualquiera por encima se come
la marcha lenta. Yo mismo lo hice primero con 2 m y el numero que salio no
se podia defender.

Hay dos maneras buenas, y conviene usar las dos porque son independientes:

  1. LO QUE DICE EL APARATO. OsmAnd escribe en cada punto su propia
     estimacion de velocidad, que viene del Doppler del GNSS y NO de
     diferenciar posiciones, asi que no arrastra el ruido de la posicion.
     Y cuando decide que estas quieto congela el fix: en esos puntos omite
     la etiqueta <osmand:speed> y repite la coordenada exacta del anterior
     (desplazamiento 0.00 m, comprobado). O sea el aparato ya marca la
     permanencia, y la marca con informacion que nosotros no tenemos
     (Doppler crudo, acelerometro). Falta de etiqueta = velocidad cero.

     El limite de esto: el umbral interno de OsmAnd no esta documentado, y
     puede congelar tambien durante marcha muy lenta -- arrastrar los pies
     en una procesion a 0.1 m/s. Entonces no alcanza solo.

  2. LA DISPERSION EN UNA VENTANA DE TIEMPO. Un receptor quieto se queda
     dentro de un circulo del tamano de su precision por mucho que uno
     espere; el ruido no se acumula. Uno que camina sale del circulo. Asi
     que una parada es un intervalo maximo cuyos fixes caben todos en un
     circulo de radio R y que dura al menos T. Esto es robusto al baile
     precisamente porque mira la dispersion y no el paso a paso.

     Con R = 20 m y T = 120 s, alguien que avanza a 0.25 m/s -- mas lento
     que cualquier marcha de verdad-- recorre 30 m en la ventana y queda
     bien clasificado como marcha. El margen es comodo.

El borde de una parada por dispersion queda difuso en del orden de un
radio: el ultimo punto de marcha antes de llegar ya esta dentro del circulo
y el detector no tiene como distinguirlo de los de la parada. Es el precio
de no mirar el paso a paso, y se traduce en que las paradas salen unos
segundos mas largas de lo que fueron. Para la fraccion de tiempo parado, con
paradas de minutos, es despreciable; para medir la duracion de UNA parada en
particular, no.

El intervalo se mide contra el PUNTO DE ANCLAJE y no contra el centroide,
que es la definicion publicada y es lineal en el numero de puntos. Tiene una
consecuencia que hay que conocer: si la gente se desplaza despacio dentro de
la estacion, el anclaje la parte en varias paradas seguidas. Por eso despues
se UNEN las paradas consecutivas cuyos centros caen dentro de R y entre las
que hay menos de T de marcha. Sin ese paso, una estacion donde la gente se
mueve queda contada como cinco paradas cortas en vez de una larga.

Y EL NUMERO DEPENDE DE R Y DE T, ASI QUE SE INFORMA EL BARRIDO
--------------------------------------------------------------
"La mitad del tiempo parado" no es un hecho, es un hecho dado R y T. El paso
imprime la tabla de sensibilidad junto con el resultado, igual que
`sensibilidad` hace con los cortes por sector. Un resultado que se mueve
mucho con R y T no se puede contar sin decir cual se uso.

LOS HUECOS DE GRABACION NO SON PARADAS
--------------------------------------
Si la grabacion se pauso, el tiempo que falta no es ni marcha ni
permanencia: es tiempo del que no sabemos nada. Se corta la traza en los
huecos y ese tiempo se informa aparte. Contarlo como permanencia infla
justamente el numero que mas interesa.

LA PENDIENTE DE AQUI ES PROVISIONAL
-----------------------------------
Mientras no haya DEM, la pendiente sale del perfil del propio GPS, que
tiene ruido de orden del metro: sobre un paso de 30 m eso ya son 3 puntos
de pendiente. Sirve para mirar, no para publicar. `pasos()` devuelve las
coordenadas justamente para que, cuando el raster este, la pendiente se tome
del DEM y no de la altimetria del aparato.

Y LA VELOCIDAD SE MIDE SOBRE PASO DE DISTANCIA FIJA
---------------------------------------------------
Si uno calcula la pendiente como dz/d con d = v*dt y dt constante, entonces
d es proporcional a v, y cualquier ruido en dz produce pendiente grande
justo donde la velocidad es chica. La correlacion velocidad-pendiente sale
sola, de la aritmetica. Remuestrear a paso de distancia fija deja la
distancia fuera del numerador y del denominador a la vez, y recien ahi la
relacion que quede es del terreno y no del algebra.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import pathlib
import xml.etree.ElementTree as ET

import numpy as np

GPX = "{http://www.topografix.com/GPX/1/1}"
OSMAND = ("{https://osmand.net/docs/technical/osmand-file-formats/"
          "osmand-gpx}")

# Hueco de grabacion a partir del cual la traza se corta. Por debajo de esto
# el tiempo se atribuye al intervalo donde cae; por encima, no sabemos que
# paso y se informa aparte.
HUECO_S = 300.0

# Radio del circulo que tiene que contener todos los fixes de una parada.
# Varias veces el error horizontal tipico: aqui el hdop mediano es 3, que a
# 5 m por unidad de hdop son unos 15 m de error esperable.
RADIO_PARADA_M = 20.0

# Duracion minima para que un intervalo quieto cuente como parada. Por
# debajo de dos minutos es atarse un cordon, no una estacion.
MIN_PARADA_S = 120.0

# Paso del remuestreo. La celda del DEM, para que la pendiente de aqui y la
# del raster hablen de la misma escala.
PASO_M = 30.0

# Fix peor que esto se descarta: con hdop 10 el error horizontal esperable
# pasa de 50 m y la posicion no sirve ni para la dispersion.
HDOP_MAX = 10.0

# Velocidad por encima de la cual la traza no es de alguien caminando.
#
# No es un numero a ojo: en estos doce tracks el percentil 95 de la velocidad
# durante la marcha da entre 0.9 y 1.8 m/s en los ocho a pie, y entre 10.3 y
# 14.0 m/s en los cuatro en carro. El umbral cae en un hueco de casi un orden
# de magnitud, asi que la clasificacion no es sensible a donde se ponga.
#
# Hace falta porque parte de la peregrinacion de hoy se hace en camion, y
# mezclar los dos modos en la tabla de velocidad contra pendiente la vuelve
# ininteligible: 10 m/s en la clase de pendiente llana es un camion, no un
# peregrino.
V_MAX_A_PIE = 4.0


@dataclasses.dataclass(frozen=True)
class Traza:
    """Un track grabado, ya proyectado al CRS de trabajo.

    `t` va en segundos desde el primer punto, y `hora_cero` guarda el sello
    absoluto para poder volver a la hora del dia, que es lo que importa
    cuando el recorrido tiene horario.

    `v_aparato` trae la velocidad que declaro el receptor, con 0.0 donde la
    etiqueta falta -- que en OsmAnd significa cero, no desconocido. `declara`
    distingue los dos casos para quien quiera tratarlos aparte.
    """

    nombre: str
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    t: np.ndarray
    hora_cero: _dt.datetime
    hdop: np.ndarray
    v_aparato: np.ndarray
    declara: np.ndarray

    def __len__(self) -> int:
        return int(self.x.size)

    @property
    def duracion_s(self) -> float:
        return float(self.t[-1] - self.t[0]) if len(self) > 1 else 0.0

    @property
    def largo_m(self) -> float:
        return float(np.hypot(np.diff(self.x), np.diff(self.y)).sum())

    def horas(self) -> list[_dt.datetime]:
        return [self.hora_cero + _dt.timedelta(seconds=float(s))
                for s in self.t]

    def trozo(self, i0: int, i1: int) -> "Traza":
        r = slice(i0, i1 + 1)
        return dataclasses.replace(
            self, x=self.x[r], y=self.y[r], z=self.z[r], t=self.t[r],
            hdop=self.hdop[r], v_aparato=self.v_aparato[r],
            declara=self.declara[r])


# --------------------------------------------------------------- lectura

def lee(ruta, crs: str, hdop_max: float = HDOP_MAX) -> Traza:
    """Un GPX con sello de tiempo, proyectado al CRS de trabajo.

    Se concatenan los <trkseg> en el orden en que vienen: el corte en
    segmentos es de la aplicacion, no del recorrido, y los huecos de verdad
    los encuentra `corta_en_huecos` mirando el tiempo.

    Un punto sin <time> no sirve para nada de lo que hace este modulo, asi
    que si el archivo no trae tiempo se para con un mensaje claro en vez de
    devolver una traza medio vacia.
    """
    from pyproj import Transformer

    ruta = pathlib.Path(ruta)
    raiz = ET.parse(ruta).getroot()
    lat, lon, ele, sellos, hdop, vel, dec = [], [], [], [], [], [], []
    sin_tiempo = 0
    for p in raiz.iter(GPX + "trkpt"):
        st = p.find(GPX + "time")
        if st is None or not (st.text or "").strip():
            sin_tiempo += 1
            continue
        e = p.find(GPX + "ele")
        h = p.find(GPX + "hdop")
        v = p.find(GPX + "extensions/" + OSMAND + "speed")
        lat.append(float(p.get("lat")))
        lon.append(float(p.get("lon")))
        ele.append(float(e.text) if e is not None and e.text else np.nan)
        sellos.append(_dt.datetime.fromisoformat(
            st.text.strip().replace("Z", "+00:00")))
        hdop.append(float(h.text) if h is not None and h.text else np.nan)
        vel.append(float(v.text) if v is not None and v.text else 0.0)
        dec.append(v is not None and bool(v.text))

    if len(sellos) < 2:
        raise SystemExit(
            f"{ruta.name} no trae puntos con <time>.\n"
            "Este paso necesita el tiempo: sin el, un track es una linea y\n"
            "para lineas ya estan 'ruta' y 'revisar'.")
    if sin_tiempo:
        print(f"    ({ruta.name}: {sin_tiempo} puntos sin <time>, omitidos)")

    orden = np.argsort(np.array(sellos))
    sellos = [sellos[i] for i in orden]
    lat = np.array(lat)[orden]
    lon = np.array(lon)[orden]
    ele = np.array(ele)[orden]
    hdop = np.array(hdop)[orden]
    vel = np.array(vel)[orden]
    dec = np.array(dec)[orden]

    # Los fixes malos se van ANTES de proyectar y antes de medir cualquier
    # cosa: un hdop de 30 mete un salto de cien metros que se suma al largo
    # y rompe la deteccion de paradas por dispersion.
    malo = np.isfinite(hdop) & (hdop > hdop_max)
    if malo.any():
        print(f"    ({ruta.name}: {int(malo.sum())} fixes con hdop > "
              f"{hdop_max:g}, descartados)")
        bueno = ~malo
        sellos = [s for s, b in zip(sellos, bueno) if b]
        lat, lon, ele = lat[bueno], lon[bueno], ele[bueno]
        hdop, vel, dec = hdop[bueno], vel[bueno], dec[bueno]

    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = tr.transform(lon, lat)
    t0 = sellos[0]
    t = np.array([(s - t0).total_seconds() for s in sellos], dtype=float)
    return Traza(nombre=ruta.stem, x=np.asarray(x, dtype=float),
                 y=np.asarray(y, dtype=float), z=ele, t=t, hora_cero=t0,
                 hdop=hdop, v_aparato=vel, declara=dec)


def corta_en_huecos(traza: Traza, hueco: float = HUECO_S):
    """Parte la traza donde la grabacion se interrumpio.

    Devuelve (trozos, segundos_de_hueco). El tiempo del hueco se devuelve
    para informarlo, no para repartirlo: no es marcha ni permanencia.
    """
    if len(traza) < 2:
        return [traza], 0.0
    dt = np.diff(traza.t)
    cortes = np.where(dt > hueco)[0]
    perdido = float(dt[dt > hueco].sum())
    bordes = [0, *(int(c) + 1 for c in cortes), len(traza)]
    trozos = [traza.trozo(bordes[i], bordes[i + 1] - 1)
              for i in range(len(bordes) - 1)]
    return [z for z in trozos if len(z) >= 2], perdido


# --------------------------------------------------------------- paradas

def paradas_por_aparato(traza: Traza, minimo: float = MIN_PARADA_S):
    """Intervalos que el receptor declaro a velocidad cero.

    Independiente de la posicion: la velocidad de OsmAnd viene del Doppler.
    Es el criterio primario, y `paradas_por_dispersion` lo comprueba.
    """
    quieto = traza.v_aparato <= 0.0
    return _intervalos(quieto, traza.t, minimo)


def paradas_por_dispersion(traza: Traza, radio: float = RADIO_PARADA_M,
                           minimo: float = MIN_PARADA_S):
    """Intervalos maximos que caben en un circulo de radio `radio`.

    Se ancla en el primer punto del intervalo y se extiende mientras todos
    los siguientes caigan dentro del circulo. Lineal en el numero de puntos.
    """
    n = len(traza)
    salida, i = [], 0
    while i < n:
        j = i
        while j + 1 < n:
            d = np.hypot(traza.x[j + 1] - traza.x[i],
                         traza.y[j + 1] - traza.y[i])
            if d > radio:
                break
            j += 1
        if j > i and traza.t[j] - traza.t[i] >= minimo:
            salida.append((i, j))
            i = j + 1
        else:
            i += 1
    return salida


def une_paradas(intervalos, traza: Traza, radio: float = RADIO_PARADA_M,
                minimo: float = MIN_PARADA_S):
    """Junta paradas consecutivas que son la misma estacion.

    Dos paradas se unen si sus centros caen dentro de `radio` y entre ellas
    hay menos de `minimo` de marcha. Sin esto, una estacion donde la gente
    se mueve despacio sale partida en varias paradas cortas y el conteo de
    estaciones queda inflado.
    """
    if not intervalos:
        return []

    def centro(iv):
        r = slice(iv[0], iv[1] + 1)
        return float(np.mean(traza.x[r])), float(np.mean(traza.y[r]))

    salida = [intervalos[0]]
    for iv in intervalos[1:]:
        prev = salida[-1]
        hueco_marcha = traza.t[iv[0]] - traza.t[prev[1]]
        cx0, cy0 = centro(prev)
        cx1, cy1 = centro(iv)
        if (hueco_marcha < minimo
                and np.hypot(cx1 - cx0, cy1 - cy0) <= radio):
            salida[-1] = (prev[0], iv[1])
        else:
            salida.append(iv)
    return salida


def paradas(traza: Traza, radio: float = RADIO_PARADA_M,
            minimo: float = MIN_PARADA_S, criterio: str = "ambos"):
    """Las paradas de la traza.

    `criterio`:
        'aparato'    solo lo que declaro el receptor
        'dispersion' solo la dispersion en ventana
        'ambos'      la union de los dos, que es lo que se usa por omision

    La UNION y no la interseccion: cada criterio ve un modo de estar quieto
    que el otro se pierde. El aparato detecta el estar parado de verdad
    aunque el fix baile; la dispersion detecta el arrastrarse dentro de una
    estacion, que el aparato puede dar como marcha. Pedir que los dos
    coincidan se queda corto a proposito, y eso se ve en la tabla de
    sensibilidad, donde los dos criterios van por separado.
    """
    if criterio == "aparato":
        brutas = paradas_por_aparato(traza, minimo)
    elif criterio == "dispersion":
        brutas = paradas_por_dispersion(traza, radio, minimo)
    elif criterio == "ambos":
        a = np.zeros(len(traza), dtype=bool)
        for i0, i1 in paradas_por_aparato(traza, minimo):
            a[i0:i1 + 1] = True
        for i0, i1 in paradas_por_dispersion(traza, radio, minimo):
            a[i0:i1 + 1] = True
        brutas = _intervalos(a, traza.t, minimo)
    else:
        raise ValueError(f"criterio desconocido: {criterio!r}")
    return une_paradas(brutas, traza, radio, minimo)


def tramos_de_marcha(traza: Traza, paradas_):
    """Lo que queda entre parada y parada, con al menos dos puntos."""
    n = len(traza)
    if not paradas_:
        return [(0, n - 1)] if n >= 2 else []
    salida, i = [], 0
    for i0, i1 in paradas_:
        if i0 - i >= 1:
            salida.append((i, i0))
        i = i1
    if n - 1 - i >= 1:
        salida.append((i, n - 1))
    return salida


# Separacion maxima entre el final de un track y el principio del siguiente
# para que sean el MISMO trecho.
#
# Sale de los datos: en el circuito de Qoyllur Rit'i los empalmes entre
# tracks consecutivos son de 78, 10 y 12 m... y uno de 1888 m. Ese ultimo no
# es un empalme, es un pedazo sin grabar, y pegarlo dibuja una recta de 2 km
# por terreno del que no hay dato. Cien metros deja pasar los tres primeros y
# corta el cuarto.
SALTO_MAX_M = 100.0

# Y lo mismo en tiempo. Los tres empalmes buenos tienen 0.76, 3.21 y 2.72 h
# de pausa -- son noches y esperas en la estacion, no interrupciones del
# recorrido-- y el malo tiene 5.15 h. Cuatro horas los separa.
#
# Las DOS condiciones tienen que cumplirse: una pausa larga en el mismo sitio
# sigue siendo el mismo trecho, y un salto de dos kilometros no deja de serlo
# por ser rapido.
SALTO_MAX_H = 4.0


def modo(traza: Traza, paradas_, umbral: float = V_MAX_A_PIE) -> str:
    """'pie' o 'vehiculo', mirando la velocidad durante la MARCHA.

    Durante la marcha y no en toda la traza: un camion detenido una hora
    tiene mediana cero igual que un peregrino sentado, y lo que distingue a
    los dos es la velocidad que alcanzan cuando se mueven.

    Se usa el percentil 95 y no el maximo: un solo fix malo no puede
    convertir una caminata en un viaje en camion.

    Importa para dos cosas. Una, la tabla de velocidad contra pendiente solo
    tiene sentido a pie. Dos, el remuestreo a 30 m queda por DEBAJO de la
    resolucion de muestreo en un vehiculo -- a 13 m/s y 16 s entre fixes hay
    200 m de un punto al siguiente-- y entonces interpolar cada 30 m inventa
    detalle que no se midio.
    """
    mov = np.ones(len(traza), dtype=bool)
    for i0, i1 in paradas_:
        mov[i0:i1 + 1] = False
    if not mov.any():
        return "pie"
    return ("vehiculo"
            if float(np.percentile(traza.v_aparato[mov], 95)) > umbral
            else "pie")


def _intervalos(mascara, t, minimo: float):
    """Tramos contiguos de True que duran al menos `minimo`."""
    salida, i, n = [], 0, len(mascara)
    while i < n:
        if not mascara[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and mascara[j + 1]:
            j += 1
        if j > i and t[j] - t[i] >= minimo:
            salida.append((i, j))
        i = j + 1
    return salida


# ----------------------------------------------------------- remuestreo

def remuestrea(traza: Traza, i0: int, i1: int, paso: float = PASO_M):
    """El trecho [i0, i1] a paso de distancia fija.

    Devuelve (s, x, y, z, t). Si el trecho es mas corto que un paso, no hay
    nada que remuestrear y vuelve vacio.
    """
    r = slice(i0, i1 + 1)
    x, y, z, t = traza.x[r], traza.y[r], traza.z[r], traza.t[r]
    d = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    if d[-1] < paso:
        v = np.empty(0)
        return v, v, v, v, v
    s = np.arange(0.0, d[-1], paso)
    return (s, np.interp(s, d, x), np.interp(s, d, y),
            np.interp(s, d, z), np.interp(s, d, t))


def pasos(traza: Traza, paradas_, paso: float = PASO_M):
    """Pares pendiente-velocidad sobre los tramos de marcha.

    Un registro por paso de `paso` metros, con:

        pendiente   del perfil del GPS -- PROVISIONAL, ver el encabezado
        v_posicion  paso / tiempo transcurrido
        v_aparato   la del receptor, promediada sobre el mismo intervalo
        x, y        para poder tomar la pendiente del DEM cuando lo haya
        z, hora_s   altitud y segundo del dia, para cortar por altitud y
                    por hora

    La velocidad va contra un paso FIJO, que es lo que evita el artefacto
    descrito en el encabezado. Las dos velocidades se devuelven para poder
    compararlas: si no concuerdan, el que manda es el aparato.
    """
    cols = {k: [] for k in ("pendiente", "v_posicion", "v_aparato",
                            "x", "y", "z", "hora_s", "largo_m")}
    for i0, i1 in tramos_de_marcha(traza, paradas_):
        s, x, y, z, t = remuestrea(traza, i0, i1, paso)
        if s.size < 2:
            continue
        dt = np.diff(t)
        bueno = dt > 0
        dz = np.diff(z)
        # La velocidad del aparato INTERPOLADA en el punto medio del paso.
        #
        # Antes esto promediaba los fixes que cayeran en la ventana de tiempo
        # del paso, y estaba mal cuando el paso es mas corto que el intervalo
        # de muestreo: la ventana se quedaba sin puntos y la columna salia
        # vacia o con el fix que pasara por ahi. Con 30 m de paso eso pasa en
        # cuanto se supera 1.9 m/s. Interpolar esta bien definido siempre.
        medio = (t[:-1] + t[1:]) / 2.0
        va = np.interp(medio, traza.t, traza.v_aparato)
        cols["pendiente"].append((dz / paso)[bueno])
        cols["v_posicion"].append((paso / dt)[bueno])
        cols["v_aparato"].append(va[bueno])
        cols["x"].append(x[:-1][bueno])
        cols["y"].append(y[:-1][bueno])
        cols["z"].append(z[:-1][bueno])
        # `t` sale de interpolar traza.t, asi que ya va en segundos desde
        # hora_cero: no hay que sumarle nada.
        cols["hora_s"].append(t[:-1][bueno])
        cols["largo_m"].append(np.full(int(bueno.sum()), float(paso)))
    vacio = np.empty(0)
    return {k: (np.concatenate(v) if v else vacio) for k, v in cols.items()}


# ------------------------------------------------------------- anatomia

def anatomia(traza: Traza, radio: float = RADIO_PARADA_M,
             minimo: float = MIN_PARADA_S, criterio: str = "ambos",
             hueco: float = HUECO_S,
             v_max_a_pie: float = V_MAX_A_PIE) -> dict:
    """Donde se va el tiempo de un recorrido.

    Se trabaja por trozos entre huecos de grabacion y se suma; el tiempo de
    los huecos se informa aparte y no se reparte.
    """
    trozos, perdido = corta_en_huecos(traza, hueco)
    tot = par = largo = sub = baj = 0.0
    n_paradas = 0
    duraciones, altitudes, modos = [], [], []
    for z in trozos:
        ps = paradas(z, radio, minimo, criterio)
        modos.append(modo(z, ps, v_max_a_pie))
        tot += z.duracion_s
        largo += z.largo_m
        dz = np.diff(z.z)
        sub += float(np.nansum(dz[dz > 0]))
        baj += float(-np.nansum(dz[dz < 0]))
        for i0, i1 in ps:
            d = float(z.t[i1] - z.t[i0])
            par += d
            duraciones.append(d)
            altitudes.append(float(np.nanmean(z.z[i0:i1 + 1])))
        n_paradas += len(ps)

    marcha_s = tot - par
    paso_fix = float(np.median(np.hypot(np.diff(traza.x), np.diff(traza.y))))
    return {
        "traza": traza.nombre,
        "modo": "vehiculo" if "vehiculo" in modos else "pie",
        "d_entre_fixes_m": round(paso_fix, 1),
        "inicio": traza.hora_cero.isoformat(),
        "horas_total": round(tot / 3600, 3),
        "horas_marcha": round(marcha_s / 3600, 3),
        "horas_parado": round(par / 3600, 3),
        "fraccion_parado": round(par / tot, 4) if tot > 0 else float("nan"),
        "horas_sin_grabar": round(perdido / 3600, 3),
        "km": round(largo / 1000, 3),
        "subida_m": round(sub),
        "bajada_m": round(baj),
        "n_paradas": n_paradas,
        "parada_mediana_min": (round(float(np.median(duraciones)) / 60, 1)
                               if duraciones else float("nan")),
        "parada_mas_larga_min": (round(max(duraciones) / 60, 1)
                                 if duraciones else float("nan")),
        "altitud_media_paradas_m": (round(float(np.mean(altitudes)))
                                    if altitudes else float("nan")),
        "v_marcha_media_kmh": (round(largo / marcha_s * 3.6, 2)
                               if marcha_s > 0 else float("nan")),
    }


def sensibilidad(trazas, radios=(10.0, 20.0, 40.0),
                 minimos=(60.0, 120.0, 300.0)):
    """La fraccion de tiempo parado, en funcion de R y de T.

    Esta es la tabla que decide si el resultado se puede contar. La
    fraccion de tiempo parado es el numero principal del paso y depende de
    dos parametros que elegimos nosotros; si se mueve mucho con ellos, hay
    que decir cual se uso y por que, o no decir el numero.
    """
    filas = []
    for criterio in ("aparato", "dispersion", "ambos"):
        for radio in radios:
            if criterio == "aparato" and radio != radios[0]:
                continue        # el aparato no usa el radio
            for minimo in minimos:
                tot = par = 0.0
                n = 0
                for tz in trazas:
                    for z in corta_en_huecos(tz)[0]:
                        ps = paradas(z, radio, minimo, criterio)
                        tot += z.duracion_s
                        par += sum(float(z.t[b] - z.t[a]) for a, b in ps)
                        n += len(ps)
                filas.append({
                    "criterio": criterio,
                    "radio_m": radio if criterio != "aparato" else None,
                    "min_s": minimo,
                    "fraccion_parado": round(par / tot, 4) if tot else None,
                    "n_paradas": n,
                })
    return filas


# ---------------------------------------------------------------- informe

def trechos(trazas, salto_max_m: float = SALTO_MAX_M,
            salto_max_h: float = SALTO_MAX_H):
    """Agrupa los tracks en TRECHOS continuos del recorrido.

    Un track es un archivo, y eso lo decide quien aprieta el boton de grabar:
    se para a dormir, se apaga el telefono, se cambia de dia. El recorrido no
    se corta donde se cortan los archivos. Entonces antes de medir nada hay
    que decidir cuales archivos son el mismo trecho.

    La regla: dos tracks consecutivos en el tiempo son el mismo trecho si el
    final de uno esta a menos de `salto_max_m` del principio del siguiente Y
    la pausa entre los dos es de menos de `salto_max_h`. Las dos cosas, no
    una: una pausa larga en el mismo sitio sigue siendo el mismo trecho (es
    la noche en la estacion), y un salto de dos kilometros no deja de serlo
    por ser rapido.

    Esto no es una comodidad de programacion. Pegar un track que empieza a
    dos kilometros del anterior dibuja una recta por terreno del que no se
    grabo nada, y esa recta entra en el costo como si se hubiera caminado.

    Devuelve [[Traza, ...]], en orden de tiempo.
    """
    if not trazas:
        return []
    ordenadas = sorted(trazas, key=lambda z: z.hora_cero)
    grupos = [[ordenadas[0]]]
    for z in ordenadas[1:]:
        a = grupos[-1][-1]
        salto = float(np.hypot(z.x[0] - a.x[-1], z.y[0] - a.y[-1]))
        pausa = (z.hora_cero - (a.hora_cero + _dt.timedelta(
            seconds=float(a.t[-1])))).total_seconds() / 3600.0
        if salto <= salto_max_m and abs(pausa) <= salto_max_h:
            grupos[-1].append(z)
        else:
            grupos.append([z])
    return grupos


def nombre_de_trecho(grupo) -> str:
    """Nombre legible de un trecho, a partir de los nombres de sus tracks.

    Los nombres de OsmAnd traen fecha y un rotulo escrito a mano
    ("2026-06-02_20-00_Tue tayancani"), asi que el rotulo sirve. Se toma el
    del primero y el del ultimo, que es como se nombra un tramo: "A - B".
    """
    def limpia(n):
        t = n.split("_")
        trozo = t[-1] if len(t) > 1 else n
        for dia in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            trozo = trozo.replace(dia, "")
        return " ".join(trozo.split()).strip(" -_") or n

    a, b = limpia(grupo[0].nombre), limpia(grupo[-1].nombre)
    return a if a == b else f"{a} - {b}"


def como_camino(cfg, trazas, solo_a_pie: bool = True,
                tolerancia: float | None = None):
    """Los trechos como camino observado, en el formato que usa el pipeline.

    Devuelve un GeoDataFrame con una fila por trecho, columna `tramnomb` y
    una LineString por geometria -- lo mismo que entrega el registro del
    Ministerio. Con eso `preparar.unidades`, `revisar`, `nulos` y el barrido
    funcionan sin tocarse: el recorrido grabado entra como camino observado y
    no como un caso aparte.

    DOS DECISIONES QUE HAY QUE CONOCER:

    `solo_a_pie`. Los tramos en vehiculo se dejan fuera por omision. No es
    limpieza: una carretera moderna esta trazada buscando ahorro con
    maquinaria, asi que su razon de costo mide la ingenieria vial de hoy y
    no la eleccion de nadie que camine. Medir el tiempo de esos tramos si
    tiene sentido, y `trayectorias` los mide; modelarlos como camino, no.

    `tolerancia`. La linea se simplifica con Douglas-Peucker. El motivo no
    es el costo -- `costo_de_seguir_el_trazado` resuelve el optimo dentro de
    una franja alrededor del trazado, asi que el serpenteo del GPS ya queda
    absorbido ahi-- sino las metricas de forma: sobre un track crudo,
    `giro_maximo` sale cerca de 180 grados en cualquier trecho porque el fix
    baila, y la sinuosidad mide el baile y no el recorrido.

    Por omision la tolerancia es UNA CELDA del DEM. El modelo no puede
    distinguir nada mas fino que su propia celda, asi que un vertice a menos
    de eso del anterior no aporta informacion que el modelo pueda usar.
    """
    import geopandas as gpd
    from shapely.geometry import LineString

    tol = cfg.resolucion if tolerancia is None else float(tolerancia)
    radio = getattr(cfg, "parada_radio", RADIO_PARADA_M)
    minimo = getattr(cfg, "parada_min_s", MIN_PARADA_S)
    criterio = getattr(cfg, "parada_criterio", "ambos")
    v_max = getattr(cfg, "v_max_a_pie", V_MAX_A_PIE)

    usables = []
    for z in trazas:
        m = modo(z, paradas(z, radio, minimo, criterio), v_max)
        if solo_a_pie and m == "vehiculo":
            continue
        usables.append(z)
    fuera = len(trazas) - len(usables)
    if fuera:
        print(f"  {fuera} trazas en vehiculo fuera del camino observado "
              "(se miden en 'trayectorias', no se modelan).")
    if not usables:
        raise SystemExit(
            "Ninguna traza a pie. Si de verdad quieres modelar los tramos\n"
            "en vehiculo, llama a como_camino con solo_a_pie=False, pero\n"
            "una carretera moderna mide la ingenieria de hoy y no una\n"
            "eleccion de recorrido.")

    filas, geoms = [], []
    for grupo in trechos(usables):
        xs = np.concatenate([z.x for z in grupo])
        ys = np.concatenate([z.y for z in grupo])
        cruda = LineString(_sin_repetidos(np.column_stack([xs, ys])))
        linea = cruda if tol <= 0 else cruda.simplify(tol)
        linea = LineString(_sin_repetidos(np.asarray(linea.coords)))
        if linea.length < cfg.resolucion:
            continue
        filas.append({
            "tramnomb": nombre_de_trecho(grupo),
            # Marca el origen para `preparar.lineas_unidas`: un recorrido ya
            # viene unido y no se puede pasar por unary_union, que lo partiria
            # en sus autointersecciones.
            "origen": "trayectoria",
            "tracks": len(grupo),
            "vertices_crudos": len(cruda.coords),
            "vertices": len(linea.coords),
            "largo_km": round(linea.length / 1000, 3),
        })
        geoms.append(linea)

    gdf = gpd.GeoDataFrame(filas, geometry=geoms, crs=cfg.crs)
    print(f"\n  --- trechos del recorrido (tolerancia {tol:g} m) ---")
    print(f"  {'trecho':38s} {'tracks':>6s} {'km':>7s} "
          f"{'vertices':>9s} {'crudos':>8s}")
    for f in filas:
        print(f"  {f['tramnomb'][:38]:38s} {f['tracks']:6d} "
              f"{f['largo_km']:7.2f} {f['vertices']:9d} "
              f"{f['vertices_crudos']:8d}")
    corto = [f for f in filas if f["largo_km"] * 1000 < cfg.largo_min_unidad]
    if corto:
        print(f"\n  {len(corto)} trechos no llegan a "
              f"{cfg.largo_min_unidad / 1000:.1f} km y 'preparar.unidades' "
              "los va a dejar")
        print(f"  fuera: {', '.join(f['tramnomb'][:24] for f in corto)}.")
        print("  Si los quieres dentro, baja 'barrido.largo_min_unidad'.")
    return gdf


def _sin_repetidos(xy, eps: float = 0.01):
    """Quita vertices consecutivos que son el mismo punto.

    UN VERTICE REPETIDO PARTE LA LINEA. `preparar.lineas_unidas` pasa por
    `unary_union` y `linemerge`, y un punto duplicado en medio de una
    polilinea produce un segmento de largo cero: el union lo trata como un
    nodo y la linea sale en tres piezas, de las que `unidades` se queda con
    la mayor. En el circuito de Qoyllur Rit'i eso convertia 20.5 km de
    trecho en 13.2, sin ningun aviso.

    Aparece al pegar tracks: el final de uno y el principio del siguiente
    estan a unos metros, y al simplificar colapsan al mismo punto.
    """
    xy = np.asarray(xy, dtype=float)[:, :2]
    if len(xy) < 2:
        return xy
    d = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
    queda = np.concatenate([[True], d > eps])
    salida = xy[queda]
    return salida if len(salida) >= 2 else xy[[0, -1]]


def camino_observado(cfg, solo_a_pie: bool = True, tolerancia=None):
    """Lee los GPX de datos/trayectorias/ y los devuelve como camino."""
    trazas = []
    for p in _archivos(cfg):
        try:
            trazas.append(lee(p, cfg.crs))
        except SystemExit as e:
            print(f"    (se omite {p.name}: {e})")
    if not trazas:
        raise SystemExit("ninguna traza utilizable en datos/trayectorias/")
    return como_camino(cfg, trazas, solo_a_pie, tolerancia)


def _archivos(cfg):
    carpeta = cfg.dir_datos / "trayectorias"
    if not carpeta.is_dir():
        raise SystemExit(
            f"No hay carpeta {carpeta}.\n"
            "Pon ahi los GPX grabados (con <time>) y vuelve a correr esto.\n"
            "Son los tracks del recorrido, no el registro: el registro va\n"
            "por 'ruta'.")
    hay = sorted(p for p in carpeta.glob("*.gpx"))
    if not hay:
        raise SystemExit(f"{carpeta} esta vacia de .gpx")
    return hay


def informe(cfg) -> dict:
    import csv

    radio = getattr(cfg, "parada_radio", RADIO_PARADA_M)
    minimo = getattr(cfg, "parada_min_s", MIN_PARADA_S)
    criterio = getattr(cfg, "parada_criterio", "ambos")
    paso = getattr(cfg, "trayectoria_paso", PASO_M)
    hueco = getattr(cfg, "trayectoria_hueco_s", HUECO_S)

    trazas = []
    for p in _archivos(cfg):
        try:
            trazas.append(lee(p, cfg.crs))
        except SystemExit as e:
            print(f"    (se omite {p.name}: {e})")
    if not trazas:
        raise SystemExit("ninguna traza utilizable")

    print(f"\n  R = {radio:g} m, T = {minimo:g} s, criterio '{criterio}', "
          f"paso de {paso:g} m")

    # --- la anatomia, traza por traza
    v_max = getattr(cfg, "v_max_a_pie", V_MAX_A_PIE)
    filas = [anatomia(t, radio, minimo, criterio, hueco, v_max)
             for t in trazas]
    print(f"\n  --- donde se va el tiempo ---")
    print(f"  {'traza':32s} {'modo':>9s} {'h tot':>6s} {'h march':>8s} "
          f"{'h par':>6s} {'% par':>6s} {'km':>6s} {'km/h':>5s} "
          f"{'n par':>5s} {'par med':>8s}")
    for f in filas:
        print(f"  {f['traza'][:32]:32s} {f['modo']:>9s} "
              f"{f['horas_total']:6.2f} "
              f"{f['horas_marcha']:8.2f} {f['horas_parado']:6.2f} "
              f"{100 * f['fraccion_parado']:6.0f} {f['km']:6.2f} "
              f"{f['v_marcha_media_kmh']:5.2f} {f['n_paradas']:5d} "
              f"{f['parada_mediana_min']:7.1f}m")

    for etiqueta in ("pie", "vehiculo"):
        sub = [f for f in filas if f["modo"] == etiqueta]
        if not sub:
            continue
        tot = sum(f["horas_total"] for f in sub)
        par = sum(f["horas_parado"] for f in sub)
        km = sum(f["km"] for f in sub)
        print(f"  {'  subtotal ' + etiqueta:32s} {'':>9s} {tot:6.2f} "
              f"{tot - par:8.2f} {par:6.2f} "
              f"{100 * par / tot if tot else 0:6.0f} {km:6.2f} "
              f"{km / (tot - par) if tot > par else 0:5.2f} "
              f"{sum(f['n_paradas'] for f in sub):5d}")

    tot = sum(f["horas_total"] for f in filas)
    par = sum(f["horas_parado"] for f in filas)
    km = sum(f["km"] for f in filas)
    npar = sum(f["n_paradas"] for f in filas)
    perdido = sum(f["horas_sin_grabar"] for f in filas)
    print(f"  {'TOTAL':32s} {'':>9s} {tot:6.2f} {tot - par:8.2f} {par:6.2f} "
          f"{100 * par / tot if tot else 0:6.0f} {km:6.2f} "
          f"{km / (tot - par) if tot > par else 0:5.2f} {npar:5d}")
    print(f"\n  El modo sale del percentil 95 de la velocidad DURANTE LA "
          f"MARCHA, con umbral {v_max:g} m/s.")
    print("  No es una etiqueta puesta a mano: parte del recorrido de hoy se")
    print("  hace en camion y eso es un dato del recorrido, no un estorbo.")
    if perdido > 0.01:
        print(f"\n  {perdido:.2f} h sin grabar (huecos > {hueco:g} s). No "
              "van en ninguna de las dos columnas:")
        print("  no sabemos si en ese tiempo se camino o se estuvo quieto.")

    # --- la tabla que decide si el numero se puede contar
    print(f"\n  --- sensibilidad de 'fraccion de tiempo parado' a R y T ---")
    sens = sensibilidad(trazas)
    print(f"  {'criterio':12s} {'R (m)':>6s} {'T (s)':>6s} "
          f"{'% parado':>9s} {'n paradas':>10s}")
    for s in sens:
        r = "-" if s["radio_m"] is None else f"{s['radio_m']:.0f}"
        print(f"  {s['criterio']:12s} {r:>6s} {s['min_s']:6.0f} "
              f"{100 * s['fraccion_parado']:9.1f} {s['n_paradas']:10d}")
    anchos = [s["fraccion_parado"] for s in sens]
    print(f"\n  El numero va de {100 * min(anchos):.0f}% a "
          f"{100 * max(anchos):.0f}% segun como se defina una parada.")
    print("  Lo que no se mueve es el orden entre trazas, y eso es lo que")
    print("  sostiene cualquier comparacion entre tramos del recorrido.")

    # --- velocidad contra pendiente, con paso fijo, SOLO A PIE
    print(f"\n  --- velocidad contra pendiente, paso fijo de {paso:g} m, "
          "solo a pie ---")
    a_pie = [t for t, f in zip(trazas, filas) if f["modo"] == "pie"]
    fuera = [f for f in filas if f["modo"] != "pie"]
    if fuera:
        print(f"  ({len(fuera)} trazas en vehiculo fuera de esta tabla: a "
              "13 m/s hay 200 m entre")
        print(f"   fixes y un paso de {paso:g} m interpolaria detalle que no "
              "se midio.)")
    anchas = [f for f in filas
              if f["modo"] == "pie" and f["d_entre_fixes_m"] > paso]
    if anchas:
        print(f"  AVISO: {len(anchas)} trazas a pie tienen mas de {paso:g} m "
              "entre fixes, asi que ahi")
        print("  el remuestreo interpola por dentro del muestreo: "
              + ", ".join(f["traza"][:28] for f in anchas))
    tabla = _tabla_velocidad(cfg, a_pie, radio, minimo, criterio, paso)

    # --- salidas
    dest = cfg.dir_resultados
    with open(dest / "trayectorias.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)
    with open(dest / "trayectorias_sensibilidad.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(sens[0].keys()))
        w.writeheader()
        w.writerows(sens)
    _escribe_paradas(cfg, trazas, radio, minimo, criterio)
    print(f"\n  -> {dest / 'trayectorias.csv'}")
    print(f"  -> {dest / 'trayectorias_sensibilidad.csv'}")
    print(f"  -> {dest / 'paradas.gpkg'}  (capa 'paradas', para QGIS)")

    return {"anatomia": filas, "sensibilidad": sens,
            "velocidad_pendiente": tabla}


def _tabla_velocidad(cfg, a_pie, radio, minimo, criterio, paso) -> list:
    """Velocidad mediana por clase de pendiente, sobre los tramos de marcha.

    Dos columnas de velocidad a proposito: la que sale de dividir el paso
    por el tiempo, y la que declaro el receptor. Si no concuerdan, la que
    vale es la del aparato, porque no depende de la posicion -- y entonces
    hay un problema con el remuestreo que conviene mirar.
    """
    if not a_pie:
        print("  (ninguna traza a pie: no hay tabla)")
        return []

    cols = {k: [] for k in ("pendiente", "v_posicion", "v_aparato")}
    for t in a_pie:
        d = pasos(t, paradas(t, radio, minimo, criterio), paso)
        for k in cols:
            cols[k].append(d[k])
    arr = {k: (np.concatenate([v for v in c if v.size])
               if any(v.size for v in c) else np.empty(0))
           for k, c in cols.items()}
    g, vp, va = arr["pendiente"], arr["v_posicion"], arr["v_aparato"]
    if g.size == 0:
        print("  (ningun tramo de marcha dio para un paso completo)")
        return []

    ok = (np.abs(g) <= cfg.g_max) & np.isfinite(g) & (vp > 0)
    g, vp, va = g[ok], vp[ok], va[ok]
    print(f"  {int(ok.sum())} pasos de marcha dentro de |g| <= {cfg.g_max:g}")

    bordes = np.arange(-0.45, 0.50, 0.05)
    print(f"  {'pendiente':>14s} {'n':>6s} {'v posicion':>11s} "
          f"{'v aparato':>10s}")
    tabla = []
    for i in range(len(bordes) - 1):
        k = (g >= bordes[i]) & (g < bordes[i + 1])
        if k.sum() >= 25:
            mp = float(np.median(vp[k]))
            ma = float(np.nanmedian(va[k]))
            print(f"  {bordes[i]:+.2f} a {bordes[i+1]:+.2f} "
                  f"{int(k.sum()):6d} {mp:11.3f} {ma:10.3f}")
            tabla.append({"g_centro": round((bordes[i] + bordes[i + 1]) / 2,
                                            3),
                          "n": int(k.sum()), "v_posicion": round(mp, 3),
                          "v_aparato": round(ma, 3)})
    if not tabla:
        print("  (ninguna clase de pendiente llego a 25 pasos)")
        return tabla

    difs = [abs(f["v_posicion"] - f["v_aparato"]) for f in tabla
            if f["v_aparato"] == f["v_aparato"]]
    if difs:
        print(f"\n  Las dos velocidades difieren a lo mas {max(difs):.2f} "
              "m/s por clase.")
        if max(difs) > 0.3:
            print("  Eso es MUCHO: la que vale es la del aparato, que no "
                  "depende de la posicion,")
            print("  y conviene mirar si el paso quedo por debajo del "
                  "muestreo.")
    print("\n  La pendiente de esta tabla sale del perfil del GPS y es")
    print("  PROVISIONAL: ruido de orden del metro sobre un paso de "
          f"{paso:g} m son")
    print(f"  unos {100 / paso:.0f} puntos de pendiente. Con el DEM encima "
          "se recalcula del raster.")
    return tabla


def _escribe_paradas(cfg, trazas, radio, minimo, criterio) -> None:
    """Las paradas como puntos, para poder cruzarlas con las estaciones.

    Es la capa que importa del paso: si el recorrido esta organizado por
    estaciones, las paradas tienen que caer sobre ellas, y eso se mira en
    QGIS antes de modelar nada.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    filas, geoms = [], []
    for tz in trazas:
        for z in corta_en_huecos(tz)[0]:
            for k, (i0, i1) in enumerate(
                    paradas(z, radio, minimo, criterio), start=1):
                r = slice(i0, i1 + 1)
                cx, cy = float(np.mean(z.x[r])), float(np.mean(z.y[r]))
                inicio = z.hora_cero + _dt.timedelta(seconds=float(z.t[i0]))
                filas.append({
                    "traza": tz.nombre,
                    "n": k,
                    "inicio": inicio.isoformat(),
                    "minutos": round(float(z.t[i1] - z.t[i0]) / 60, 1),
                    "altitud_m": round(float(np.nanmean(z.z[r])), 1),
                    "fixes": int(i1 - i0 + 1),
                    "radio_m": round(float(np.max(np.hypot(
                        z.x[r] - cx, z.y[r] - cy))), 1),
                })
                geoms.append(Point(cx, cy))
    if not filas:
        print("    (no hubo paradas con estos parametros: no se escribe GPKG)")
        return
    gdf = gpd.GeoDataFrame(filas, geometry=geoms, crs=cfg.crs)
    gdf.to_file(cfg.dir_resultados / "paradas.gpkg", layer="paradas",
                driver="GPKG")
