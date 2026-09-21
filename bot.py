# ============================================================
# ALURA QUANT V4.5
# ============================================================
#
# ARQUITECTURA
#
# 1. Cada alerta guarda una TESIS ORIGINAL INMUTABLE.
#
# 2. Cada ejecución actualiza únicamente el ESTADO ACTUAL.
#
# 3. La IA compara:
#
#       TESIS ORIGINAL
#             vs
#       SITUACIÓN ACTUAL
#
# 4. Stop Loss y Take Profit originales no se modifican.
#
# 5. Estado operativo:
#
#       ACTIVA
#       STOP_SALTADO
#       OBJETIVO_CUMPLIDO
#
# 6. Estado_Estrategia:
#
#       TESIS_REFORZADA
#       TESIS_ESTABLE
#       TESIS_DEBILITADA
#       TESIS_INVALIDADA
#
# 7. YAHOO / FECHAS
#
#    Nunca se utiliza:
#
#       hoy + 1 día
#
#    Nunca se utiliza una fecha futura como "end".
#
#    Tampoco se utiliza "start" para determinar la última
#    sesión disponible.
#
#    Yahoo descarga un periodo amplio y el programa determina
#    LOCALMENTE cuál es la última vela real disponible.
#
# 8. Un DataFrame vacío o un error de conexión de Yahoo
#    NO significa que el ticker esté delisted.
#
# 9. AUDITORÍA
#
#    Se descarga histórico amplio y posteriormente se filtran
#    localmente las velas posteriores a la entrada.
#
# ============================================================


import os
import subprocess
import time

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from openai import OpenAI


# ============================================================
# CONFIGURACIÓN
# ============================================================

TZ = ZoneInfo("Europe/Madrid")

# Directorio del propio script. Así el bot encuentra siempre los CSV
# aunque se ejecute desde otra carpeta (cron, Task Scheduler, IDE, etc.).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODO_EJECUCION = os.getenv("ALURA_MODO", "AUTO").strip()
# AUTO | 14 | 18 | 22
# En GitHub Actions se usa AUTO y el bot determina el modo por hora local.

def _resolver_archivo(nombre_principal, patron_fallback):
    """
    Usa el nombre estándar si existe. Si no, permite trabajar con una
    copia exportada/descargada con sufijos como '(1)'.
    """
    principal = os.path.join(BASE_DIR, nombre_principal)

    if os.path.exists(principal):
        return principal

    candidatos = sorted(
        [
            os.path.join(BASE_DIR, nombre)
            for nombre in os.listdir(BASE_DIR)
            if nombre.startswith(patron_fallback)
            and nombre.lower().endswith(".csv")
        ]
    )

    return candidatos[0] if candidatos else principal


ARCHIVO_HISTORIAL = _resolver_archivo(
    "historial_alertas.csv",
    "historial_alertas"
)

ARCHIVO_UNIVERSO = _resolver_archivo(
    "universo_activos.csv",
    "universo_activos"
)

CAPITAL = 100000.0

RIESGO_POR_OPERACION = 0.005

ATR_MULTIPLICADOR = 1.75

RR_TARGET = 2.5

UMBRAL_SCORE_18 = 55
UMBRAL_SCORE_14 = 50

LIQUIDEZ_MIN_EUR = 500000

CUARENTENA_STOP_DIAS = 15

TAMANO_LOTE = 50

# ------------------------------------------------------------
# YAHOO
# ------------------------------------------------------------

MAX_REINTENTOS_YAHOO = 3

ESPERA_REINTENTO_YAHOO = 2

# Histórico utilizado para indicadores actuales.
PERIODO_ACTUAL = "1y"

# Histórico utilizado para auditoría.
# Se utiliza un periodo amplio y después se filtra LOCALMENTE.
PERIODO_AUDITORIA = "5y"


# ============================================================
# IA
# ============================================================
#
# Por defecto usamos Gemini 3.5 Flash-Lite mediante la capa de
# compatibilidad OpenAI de Google. La clave NUNCA se guarda en el código:
# se obtiene de GEMINI_API_KEY (GitHub Secret o variable de entorno local).
#
# También se mantiene Ollama como opción local para pruebas: 
#   IA_PROVIDER=ollama
#
IA_PROVIDER = os.getenv("IA_PROVIDER", "gemini").strip().lower()
MODELO_GEMINI = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
).strip()
MODELO_LOCAL = os.getenv(
    "OLLAMA_MODEL",
    "llama3.2"
).strip()

GEMINI_BASE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/openai/"
)

def cliente_ia():
    """Crea el cliente de IA solo cuando realmente se necesita."""
    if IA_PROVIDER == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()

        if not api_key:
            raise RuntimeError(
                "Falta GEMINI_API_KEY. Configúrala como variable de entorno "
                "o como GitHub Secret."
            )

        return OpenAI(
            api_key=api_key,
            base_url=GEMINI_BASE_URL,
        )

    if IA_PROVIDER == "ollama":
        return OpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama",
        )

    raise RuntimeError(
        f"IA_PROVIDER no válido: {IA_PROVIDER}. Usa 'gemini' u 'ollama'."
    )

def modelo_ia():
    """Devuelve el modelo configurado para el proveedor activo."""
    return (
        MODELO_GEMINI
        if IA_PROVIDER == "gemini"
        else MODELO_LOCAL
    )


# ============================================================
# UNIVERSO BASE
# ============================================================

MAESTRO_ACTIVOS_BASE = {

    "TLGO.MC": (
        "Talgo",
        "Industrial",
        "🚆"
    ),

    "SAN.MC": (
        "Banco Santander",
        "Banca",
        "🏦"
    ),

    "BBVA.MC": (
        "BBVA",
        "Banca",
        "🏦"
    ),

    "ITX.MC": (
        "Inditex",
        "Consumo Cíclico",
        "👗"
    ),
}


def cargar_universo():

    universo = dict(
        MAESTRO_ACTIVOS_BASE
    )

    if os.path.exists(
        ARCHIVO_UNIVERSO
    ):

        try:

            df = pd.read_csv(
                ARCHIVO_UNIVERSO,
                dtype=str,
                keep_default_na=False
            )

            for _, r in df.iterrows():

                ticker = str(
                    r.get(
                        "Ticker",
                        ""
                    )
                ).strip()

                if ticker:

                    universo[ticker] = (

                        str(
                            r.get(
                                "Empresa",
                                ticker
                            )
                        ),

                        str(
                            r.get(
                                "Sector",
                                "General"
                            )
                        ),

                        str(
                            r.get(
                                "Icono",
                                "📈"
                            )
                        )
                    )

        except Exception as e:

            print(
                f"⚠️ Error cargando universo: {e}"
            )

    return universo


MAESTRO_ACTIVOS = cargar_universo()

activos = list(
    MAESTRO_ACTIVOS.keys()
)


# ============================================================
# CAMPOS DEL HISTORIAL
# ============================================================

CAMPOS_HISTORIAL = [

    # --------------------------------------------------------
    # IDENTIFICACIÓN
    # --------------------------------------------------------

    "Fecha",
    "Ticker",
    "Empresa",
    "Sector",
    "Icono",
    "Modo",

    # --------------------------------------------------------
    # TESIS / SNAPSHOT ORIGINAL
    # --------------------------------------------------------

    "Precio_Alerta",

    "Score_Entrada",
    "RVOL_Entrada",
    "RSI_Entrada",
    "ROC20_Entrada",
    "ATR_Entrada",

    "EMA50_Entrada",
    "EMA200_Entrada",

    "Razones_Entrada",

    "Soporte_Entrada",
    "Resistencia_Entrada",

    "Analisis_IA_Entrada",

    # --------------------------------------------------------
    # ESTRATEGIA ORIGINAL
    # --------------------------------------------------------

    "Stop_Loss",
    "Take_Profit",

    "Ratio_RR",

    "Riesgo_Euros",
    "Acciones",
    "Nominal",

    # --------------------------------------------------------
    # ESTADO ACTUAL
    # --------------------------------------------------------

    "Precio_Actual",

    "Score_Actual",
    "RVOL_Actual",
    "RSI_Actual",
    "ROC20_Actual",
    "ATR_Actual",

    "EMA50_Actual",
    "EMA200_Actual",

    "Razones_Actuales",

    "Soporte_Actual",
    "Resistencia_Actual",

    "Distancia_SL_Pct",
    "Distancia_TP_Pct",

    "P&L_Actual_Pct",

    "Estado_Estrategia",

    "Ultima_Actualizacion",

    "Fecha_Mercado_Actual",

    "Analisis_IA_Actual",

    # --------------------------------------------------------
    # ESTADO OPERATIVO
    # --------------------------------------------------------

    "Estado",

    "Fecha_Salida",

    "Resultado_R",

    "MAE_R",

    "MFE_R"
]


# ============================================================
# TIPOS DE COLUMNAS
# ============================================================

CAMPOS_TEXTO = [

    "Fecha",
    "Ticker",
    "Empresa",
    "Sector",
    "Icono",
    "Modo",

    "Razones_Entrada",

    "Analisis_IA_Entrada",

    "Razones_Actuales",

    "Estado_Estrategia",

    "Ultima_Actualizacion",

    "Fecha_Mercado_Actual",

    "Analisis_IA_Actual",

    "Estado",

    "Fecha_Salida"
]


CAMPOS_NUMERICOS = [

    "Precio_Alerta",

    "Score_Entrada",
    "RVOL_Entrada",
    "RSI_Entrada",
    "ROC20_Entrada",
    "ATR_Entrada",

    "EMA50_Entrada",
    "EMA200_Entrada",

    "Soporte_Entrada",
    "Resistencia_Entrada",

    "Stop_Loss",
    "Take_Profit",

    "Ratio_RR",

    "Riesgo_Euros",
    "Acciones",
    "Nominal",

    "Precio_Actual",

    "Score_Actual",
    "RVOL_Actual",
    "RSI_Actual",
    "ROC20_Actual",
    "ATR_Actual",

    "EMA50_Actual",
    "EMA200_Actual",

    "Soporte_Actual",
    "Resistencia_Actual",

    "Distancia_SL_Pct",
    "Distancia_TP_Pct",

    "P&L_Actual_Pct",

    "Resultado_R",
    "MAE_R",
    "MFE_R"
]


# ============================================================
# UTILIDADES
# ============================================================

def ahora():

    return datetime.now(TZ)


def modo_actual():

    if MODO_EJECUCION in (
        "14",
        "18",
        "22"
    ):

        return MODO_EJECUCION

    # AUTO: tres ventanas diarias de análisis.
    # 14:00 -> primera ejecución
    # 18:00 -> cierre europeo / seguimiento
    # 22:30 -> seguimiento posterior al cierre regular de EE. UU.
    hora = ahora().hour
    minuto = ahora().minute

    if hora < 16:
        return "14"

    if hora < 21 or (hora == 21 and minuto < 30):
        return "18"

    return "22"


def limpiar_fecha_indice(datos):

    """
    Normaliza el índice temporal de Yahoo.

    No intenta adivinar fechas futuras.
    Únicamente limpia y ordena las fechas que Yahoo realmente
    devolvió.
    """

    if datos is None or datos.empty:

        return datos

    datos = datos.copy()

    try:

        idx = pd.to_datetime(
            datos.index,
            errors="coerce"
        )

        datos.index = idx

        datos = datos[
            ~datos.index.isna()
        ]

        datos = datos.sort_index()

    except Exception:

        pass

    return datos


def norm(df):

    """
    Normaliza columnas procedentes de yfinance.

    Soporta tanto:

        Open / High / Low / Close / Volume

    como MultiIndex.
    """

    if df is None:

        return df

    df = df.copy()

    if isinstance(
        df.columns,
        pd.MultiIndex
    ):

        posibles = {
            "Open",
            "High",
            "Low",
            "Close",
            "Adj Close",
            "Volume"
        }

        nivel_encontrado = None

        for nivel in range(
            df.columns.nlevels
        ):

            valores = set(

                str(x)

                for x in
                df.columns.get_level_values(
                    nivel
                )
            )

            if (
                len(
                    posibles.intersection(
                        valores
                    )
                )
                >= 3
            ):

                nivel_encontrado = nivel

                break

        if nivel_encontrado is not None:

            df.columns = (
                df.columns
                .get_level_values(
                    nivel_encontrado
                )
            )

        else:

            df.columns = (
                df.columns
                .get_level_values(0)
            )

    return limpiar_fecha_indice(
        df
    )


# ============================================================
# VALIDACIÓN DE DATOS
# ============================================================

def validar_datos_mercado(
    datos
):

    if datos is None:

        return False, "Yahoo devolvió None"

    if datos.empty:

        return False, (
            "Yahoo devolvió un DataFrame vacío"
        )

    datos = norm(
        datos
    )

    columnas_necesarias = [

        "Close",
        "High",
        "Low",
        "Volume"
    ]

    faltan = [

        c

        for c in columnas_necesarias

        if c not in datos.columns
    ]

    if faltan:

        return False, (
            "Faltan columnas: "
            +
            ", ".join(faltan)
        )

    datos = datos.dropna(
        subset=columnas_necesarias
    )

    if datos.empty:

        return False, (
            "No existen velas válidas "
            "después de eliminar NaN"
        )

    return True, datos


# ============================================================
# ESCRITURA SEGURA DEL HISTORIAL
# ============================================================

def guardar_csv_seguro(df, ruta):
    """
    Escribe primero en un archivo temporal y después reemplaza
    el CSV original. Evita dejar historial_alertas.csv corrupto
    si el proceso se interrumpe durante la escritura.
    """
    ruta = os.path.abspath(ruta)
    directorio = os.path.dirname(ruta) or "."
    os.makedirs(directorio, exist_ok=True)

    temporal = ruta + ".tmp"

    try:
        df.to_csv(temporal, index=False, encoding="utf-8-sig")
        os.replace(temporal, ruta)
    finally:
        if os.path.exists(temporal):
            try:
                os.remove(temporal)
            except OSError:
                pass


# ============================================================
# DESCARGA ROBUSTA YAHOO
# ============================================================

def obtener_precio_tiempo_real(ticker):
    """
    Obtiene el último precio disponible independientemente de que exista
    una nueva vela diaria.

    Prioridad:
    1. fast_info.last_price
    2. histórico intradía de 5 minutos
    3. histórico intradía de 1 minuto

    Si Yahoo no devuelve precio intradía, devuelve None. Esto NO se
    interpreta como ticker delisted ni como nueva sesión diaria.
    """
    # Vía rápida de yfinance.
    try:
        info = yf.Ticker(ticker).fast_info
        precio = info.get("last_price")
        if precio is not None and pd.notna(precio) and float(precio) > 0:
            return float(precio)
    except Exception:
        pass

    # Fallback intradía. 5m suele ser más tolerante que 1m.
    for intervalo in ("5m", "1m"):
        try:
            datos = yf.Ticker(ticker).history(
                period="1d",
                interval=intervalo,
                auto_adjust=True,
                actions=False,
            )
            if datos is None or datos.empty or "Close" not in datos.columns:
                continue
            serie = pd.to_numeric(datos["Close"], errors="coerce").dropna()
            if not serie.empty and float(serie.iloc[-1]) > 0:
                return float(serie.iloc[-1])
        except Exception:
            continue

    return None


def descargar_historico_ticker(
    ticker,
    period=PERIODO_ACTUAL
):
    """
    Descarga el histórico disponible para un ticker.

    Estrategia:
    1. yf.download()
    2. Si falla, Ticker.history()
    3. Reintentos entre ambas vías.

    No utiliza start/end, evitando errores de rango temporal.
    """

    ultimo_error = None

    for intento in range(1, MAX_REINTENTOS_YAHOO + 1):
        # --------------------------------------------------------
        # VÍA 1: yf.download
        # --------------------------------------------------------
        try:
            datos = yf.download(
                ticker,
                period=period,
                interval="1d",
                auto_adjust=True,
                actions=False,
                progress=False,
                threads=False,
                group_by="column",
                timeout=30,
            )

            valido, resultado = validar_datos_mercado(datos)

            if valido:
                return resultado, "OK"

            ultimo_error = resultado

        except TypeError:
            # Compatibilidad con versiones antiguas de yfinance
            # que no acepten alguno de los argumentos anteriores.
            try:
                datos = yf.download(
                    ticker,
                    period=period,
                    interval="1d",
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                )

                valido, resultado = validar_datos_mercado(datos)

                if valido:
                    return resultado, "OK"

                ultimo_error = resultado

            except Exception as e:
                ultimo_error = str(e)

        except Exception as e:
            ultimo_error = str(e)

        # --------------------------------------------------------
        # VÍA 2: Ticker.history como fallback
        # --------------------------------------------------------
        try:
            datos = yf.Ticker(ticker).history(
                period=period,
                interval="1d",
                auto_adjust=True,
                actions=False,
            )

            valido, resultado = validar_datos_mercado(datos)

            if valido:
                return resultado, "OK"

            ultimo_error = resultado

        except Exception as e:
            ultimo_error = str(e)

        if intento < MAX_REINTENTOS_YAHOO:
            time.sleep(ESPERA_REINTENTO_YAHOO)

    mensaje = str(ultimo_error or "error desconocido")

    if (
        "empty" in mensaje.lower()
        or "no price data" in mensaje.lower()
        or "possibly delisted" in mensaje.lower()
    ):
        return None, "SIN_DATOS: " + mensaje

    return None, "ERROR_YAHOO: " + mensaje


# ============================================================
# FILTRADO LOCAL POR FECHA
# ============================================================

def filtrar_desde_fecha(
    datos,
    fecha_inicio
):

    """
    Filtra LOCALMENTE un histórico ya descargado.

    No hace ninguna petición adicional a Yahoo.

    Esto elimina completamente el problema de:

        start date cannot be after end date
    """

    if datos is None or datos.empty:

        return datos

    datos = norm(
        datos
    )

    try:

        fecha_inicio = pd.Timestamp(
            fecha_inicio
        ).normalize()

    except Exception:

        return datos.iloc[0:0]

    indice = pd.to_datetime(
        datos.index,
        errors="coerce"
    )

    mascara = (
        indice.normalize()
        >=
        fecha_inicio
    )

    resultado = datos.loc[
        mascara
    ].copy()

    return resultado


def ultima_fecha_datos(
    datos
):

    if datos is None or datos.empty:

        return None

    try:

        fecha = datos.index[-1]

        return pd.Timestamp(
            fecha
        )

    except Exception:

        return None


def ultima_sesion_real(
    datos
):

    """
    Devuelve exclusivamente la última fecha que Yahoo
    realmente devolvió.

    Nunca calcula:

        hoy + 1
        hoy
        mañana
        próximo lunes

    si esas fechas no existen en el DataFrame.
    """

    if datos is None or datos.empty:

        return None

    datos = norm(
        datos
    )

    datos = datos.dropna(
        subset=[
            "Close",
            "High",
            "Low",
            "Volume"
        ]
    )

    if datos.empty:

        return None

    return datos.index[-1]


# ============================================================
# DESCARGA POR LOTES
# ============================================================

def descargar_lote(
    tickers,
    period=PERIODO_ACTUAL
):
    """
    Intenta una descarga por lotes. Si Yahoo no devuelve correctamente
    el lote, hace fallback ticker por ticker para que un fallo puntual
    no bloquee toda la actualización.
    """

    if not tickers:
        return {}

    resultado = {}
    ultimo_error = None

    # ------------------------------------------------------------
    # PRIMER INTENTO: lote completo
    # ------------------------------------------------------------
    for intento in range(1, MAX_REINTENTOS_YAHOO + 1):
        try:
            datos_lote = yf.download(
                tickers,
                period=period,
                interval="1d",
                auto_adjust=True,
                actions=False,
                group_by="ticker",
                progress=False,
                threads=True,
                timeout=30,
            )

            if datos_lote is not None and not datos_lote.empty:

                # Un solo ticker
                if len(tickers) == 1:
                    ticker = tickers[0]
                    datos = norm(datos_lote)
                    valido, datos_validos = validar_datos_mercado(datos)

                    if valido:
                        return {ticker: (datos_validos, "OK")}

                    ultimo_error = datos_validos

                # Varios tickers
                else:
                    for ticker in tickers:
                        try:
                            datos = datos_lote[ticker]
                            datos = norm(datos)

                            valido, datos_validos = validar_datos_mercado(datos)

                            if valido:
                                resultado[ticker] = (datos_validos, "OK")
                            else:
                                resultado[ticker] = (None, datos_validos)

                        except Exception as e:
                            resultado[ticker] = (
                                None,
                                "ERROR_EXTRACCION: " + str(e)
                            )

                    # Si al menos un ticker funcionó, conservamos los
                    # resultados y hacemos fallback solo de los que faltan.
                    faltantes = [
                        t for t in tickers
                        if resultado.get(t, (None, ""))[0] is None
                    ]

                    if not faltantes:
                        return resultado

                    for ticker in faltantes:
                        datos, estado = descargar_historico_ticker(
                            ticker,
                            period=period
                        )
                        resultado[ticker] = (datos, estado)

                    return resultado

            else:
                ultimo_error = "Yahoo devolvió el lote vacío"

        except TypeError:
            # Compatibilidad con versiones antiguas de yfinance.
            try:
                datos_lote = yf.download(
                    tickers,
                    period=period,
                    interval="1d",
                    auto_adjust=True,
                    group_by="ticker",
                    progress=False,
                    threads=True,
                )

                if datos_lote is not None and not datos_lote.empty:
                    if len(tickers) == 1:
                        ticker = tickers[0]
                        datos = norm(datos_lote)
                        valido, datos_validos = validar_datos_mercado(datos)
                        if valido:
                            return {ticker: (datos_validos, "OK")}
                        ultimo_error = datos_validos
                    else:
                        for ticker in tickers:
                            try:
                                datos = norm(datos_lote[ticker])
                                valido, datos_validos = validar_datos_mercado(datos)
                                resultado[ticker] = (
                                    (datos_validos, "OK")
                                    if valido
                                    else (None, datos_validos)
                                )
                            except Exception as e:
                                resultado[ticker] = (
                                    None,
                                    "ERROR_EXTRACCION: " + str(e)
                                )

                        faltantes = [
                            t for t in tickers
                            if resultado.get(t, (None, ""))[0] is None
                        ]

                        for ticker in faltantes:
                            datos, estado = descargar_historico_ticker(
                                ticker,
                                period=period
                            )
                            resultado[ticker] = (datos, estado)

                        return resultado

            except Exception as e:
                ultimo_error = str(e)

        except Exception as e:
            ultimo_error = str(e)

        if intento < MAX_REINTENTOS_YAHOO:
            time.sleep(ESPERA_REINTENTO_YAHOO)

    # ------------------------------------------------------------
    # FALLBACK FINAL: ticker por ticker
    # ------------------------------------------------------------
    for ticker in tickers:
        if ticker in resultado and resultado[ticker][0] is not None:
            continue

        datos, estado = descargar_historico_ticker(
            ticker,
            period=period
        )

        resultado[ticker] = (
            datos,
            estado if datos is not None else (
                "ERROR_YAHOO: " + str(
                    ultimo_error or estado or "error desconocido"
                )
            )
        )

    return resultado


# ============================================================
# INDICADORES
# ============================================================

def rsi(
    s,
    n=14
):

    z = s.diff()

    g = z.clip(
        lower=0
    )

    l = -z.clip(
        upper=0
    )

    ag = g.ewm(
        alpha=1 / n,
        adjust=False,
        min_periods=n
    ).mean()

    al = l.ewm(
        alpha=1 / n,
        adjust=False,
        min_periods=n
    ).mean()

    rs = (
        ag
        /
        al.replace(
            0,
            pd.NA
        )
    )

    return (
        100
        -
        100 / (1 + rs)
    )


def atr(
    d,
    n=14
):

    p = d.Close.shift()

    tr = pd.concat(
        [
            d.High - d.Low,
            (d.High - p).abs(),
            (d.Low - p).abs()
        ],
        axis=1
    ).max(axis=1)

    return tr.ewm(
        alpha=1 / n,
        adjust=False,
        min_periods=n
    ).mean()


# ============================================================
# INDICADORES COMPLETOS
# ============================================================

def preparar_indicadores(
    d
):

    d = d.copy()

    d["E20"] = (
        d.Close
        .ewm(
            span=20,
            adjust=False
        )
        .mean()
    )

    d["E50"] = (
        d.Close
        .ewm(
            span=50,
            adjust=False
        )
        .mean()
    )

    d["E200"] = (
        d.Close
        .ewm(
            span=200,
            adjust=False
        )
        .mean()
    )

    d["RSI"] = rsi(
        d.Close
    )

    d["ATR"] = atr(
        d
    )

    d["VM20"] = (
        d.Volume
        .rolling(20)
        .mean()
    )

    d["TO20"] = (
        d.Close
        *
        d.Volume
    ).rolling(20).mean()

    d["ROC20"] = (
        d.Close
        .pct_change(20)
        * 100
    )

    d["H20"] = (
        d.High
        .rolling(20)
        .max()
        .shift(1)
    )

    d["CLV"] = (

        (
            d.Close
            -
            d.Low
        )

        /

        (
            d.High
            -
            d.Low
        ).replace(
            0,
            pd.NA
        )

    ).astype("float64").fillna(0.0)

    return d


# ============================================================
# ESTADO ACTUAL
# ============================================================

def obtener_estado_actual(
    t,
    d
):

    if d is None:

        return None

    d = norm(
        d
    )

    if len(d) < 220:

        return None

    d = preparar_indicadores(
        d
    )

    x = d.iloc[-1]

    requeridos = [

        "Close",
        "E50",
        "E200",
        "RSI",
        "ATR",
        "VM20",
        "TO20",
        "ROC20",
        "H20"
    ]

    if any(
        pd.isna(
            x[k]
        )
        for k in requeridos
    ):

        return None

    price = float(
        x.Close
    )

    e50 = float(
        x.E50
    )

    e200 = float(
        x.E200
    )

    rsi_actual = float(
        x.RSI
    )

    atr_actual = float(
        x.ATR
    )

    rvol = (

        float(
            x.Volume
            /
            x.VM20
        )

        if float(
            x.VM20
        ) > 0

        else 0
    )

    liquidez = float(
        x.TO20
    )

    roc20 = float(
        x.ROC20
    )

    ruptura = (

        price
        >
        float(
            x.H20
        )
    )

    clv = float(
        x.CLV
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0

    razones = []

    tests = [

        (
            price > e50,
            15,
            "Precio > EMA50"
        ),

        (
            e50 > e200,
            20,
            "EMA50 > EMA200"
        ),

        (
            55 <= rsi_actual <= 75,
            15,
            "RSI 55-75"
        ),

        (
            roc20 > 5,
            10,
            "ROC20 > 5%"
        ),

        (
            rvol >= 1.5,
            15,
            "RVOL >= 1.5x"
        ),

        (
            1.2 <= rvol < 1.5,
            8,
            "RVOL >= 1.2x"
        ),

        (
            clv >= .70,
            5,
            "Cierre cerca de máximos"
        ),

        (
            ruptura,
            15,
            "Ruptura máximo 20 sesiones"
        )
    ]

    for condicion, puntos, texto in tests:

        if condicion:

            score += puntos

            razones.append(
                texto
            )

    info = MAESTRO_ACTIVOS.get(
        t,
        (
            t,
            "General",
            "📈"
        )
    )

    fecha_datos = (
        ultima_sesion_real(
            d
        )
    )

    return {

        "ticker":
            t,

        "empresa":
            info[0],

        "sector":
            info[1],

        "icono":
            info[2],

        "precio":
            round(
                price,
                2
            ),

        "score":
            int(score),

        "rvol":
            round(
                rvol,
                2
            ),

        "rsi":
            round(
                rsi_actual,
                2
            ),

        "roc20":
            round(
                roc20,
                2
            ),

        "atr":
            round(
                atr_actual,
                2
            ),

        "e50":
            round(
                e50,
                2
            ),

        "e200":
            round(
                e200,
                2
            ),

        "razones":
            "; ".join(
                razones
            ),

        "soporte":
            round(
                float(
                    d.Low.iloc[-16:-1].min()
                ),
                2
            ),

        "resistencia":
            round(
                float(
                    d.High.iloc[-61:-1].max()
                ),
                2
            ),

        "liquidez":
            round(
                liquidez,
                2
            ),

        "fecha_datos":
            fecha_datos
    }


# ============================================================
# PROCESAR NUEVA OPORTUNIDAD
# ============================================================

def procesar_dataframe_activo(
    t,
    d
):

    estado = obtener_estado_actual(
        t,
        d
    )

    if estado is None:

        return None

    modo = modo_actual()

    score = estado["score"]

    rvol = estado["rvol"]

    precio = estado["precio"]

    e50 = estado["e50"]

    e200 = estado["e200"]

    liquidez = estado["liquidez"]

    # --------------------------------------------------------
    # FILTRO LIQUIDEZ
    # --------------------------------------------------------

    if liquidez < LIQUIDEZ_MIN_EUR:

        return None

    # --------------------------------------------------------
    # UMBRAL
    # --------------------------------------------------------

    umbral = (

        UMBRAL_SCORE_14

        if modo == "14"

        else UMBRAL_SCORE_18
    )

    if score < umbral:

        return None

    # --------------------------------------------------------
    # VOLUMEN
    # --------------------------------------------------------

    if rvol < 1.2:

        return None

    # --------------------------------------------------------
    # TENDENCIA
    # --------------------------------------------------------

    if not (
        precio > e50
        and
        e50 > e200
    ):

        return None

    # --------------------------------------------------------
    # STOP
    # --------------------------------------------------------

    soporte = estado["soporte"]

    resistencia = estado["resistencia"]

    atr_actual = estado["atr"]

    stop = min(

        precio
        -
        ATR_MULTIPLICADOR
        *
        atr_actual,

        soporte * .99
    )

    riesgo_unitario = (

        precio
        -
        stop
    )

    if riesgo_unitario <= 0:

        return None

    if riesgo_unitario > precio * .20:

        return None

    # --------------------------------------------------------
    # TAMAÑO
    # --------------------------------------------------------

    acciones = int(

        (
            CAPITAL
            *
            RIESGO_POR_OPERACION
        )

        /

        riesgo_unitario
    )

    if acciones < 1:

        return None

    info = MAESTRO_ACTIVOS.get(
        t,
        (
            t,
            "General",
            "📈"
        )
    )

    take_profit = (

        precio
        +
        RR_TARGET
        *
        riesgo_unitario
    )

    return {

        "ticker":
            t,

        "empresa":
            info[0],

        "sector":
            info[1],

        "icono":
            info[2],

        "modo":
            modo,

        # ----------------------------------------------------
        # SNAPSHOT ORIGINAL
        # ----------------------------------------------------

        "precio":
            precio,

        "score":
            estado["score"],

        "rvol":
            estado["rvol"],

        "rsi":
            estado["rsi"],

        "roc20":
            estado["roc20"],

        "atr":
            estado["atr"],

        "e50":
            estado["e50"],

        "e200":
            estado["e200"],

        "razones":
            estado["razones"],

        "soporte":
            soporte,

        "resistencia":
            resistencia,

        # ----------------------------------------------------
        # ESTRATEGIA
        # ----------------------------------------------------

        "stop":
            round(
                stop,
                2
            ),

        "tp":
            round(
                take_profit,
                2
            ),

        "acciones":
            acciones,

        "nominal":
            round(
                acciones * precio,
                2
            ),

        "riesgo":
            round(
                acciones * riesgo_unitario,
                2
            ),

        "fecha_datos":
            estado["fecha_datos"]
    }


# ============================================================
# IA - NUEVA ENTRADA
# ============================================================

def comentario_entrada(
    c
):

    try:

        system_prompt = """
Eres el analista cuantitativo senior de Alura Quant.

Se acaba de detectar una nueva oportunidad mediante
una estrategia sistemática de tendencia, momentum y volumen.

Explica en 2 o 3 frases por qué la acción ha sido
incluida y cuál es la tesis cuantitativa.

Integra tendencia, momentum y volumen.

No uses listas.
No uses títulos.
No uses lenguaje robótico.
No hagas predicciones categóricas.
"""

        user_prompt = f"""

Activo:
{c['empresa']} ({c['ticker']})

Fecha del último dato de mercado:
{c['fecha_datos']}

Precio:
{c['precio']}€

Score:
{c['score']}/100

RVOL:
{c['rvol']}x

RSI:
{c['rsi']}

ROC20:
{c['roc20']}%

ATR:
{c['atr']}€

EMA50:
{c['e50']}€

EMA200:
{c['e200']}€

Razones:
{c['razones']}

Stop Loss:
{c['stop']}€

Take Profit:
{c['tp']}€

R:R:
{RR_TARGET}
"""

        respuesta = cliente_ia().chat.completions.create(

            model=modelo_ia(),

            messages=[

                {
                    "role":
                        "system",

                    "content":
                        system_prompt
                },

                {
                    "role":
                        "user",

                    "content":
                        user_prompt
                }
            ],

            reasoning_effort="low"
        )

        return (
            respuesta
            .choices[0]
            .message
            .content
            .strip()
        )

    except Exception as e:

        print(
            f"⚠️ Error IA entrada: {e}"
        )

        return (

            f"Entrada basada en una estructura "
            f"cuantitativa favorable, con score "
            f"{c['score']}/100 y RVOL de "
            f"{c['rvol']}x."
        )


# ============================================================
# EVALUACIÓN DE EVOLUCIÓN
# ============================================================

def evaluar_evolucion_estrategia(
    original,
    actual
):

    cambios = []

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    delta_score = (

        float(actual["score"])
        -
        float(original["score"])
    )

    if delta_score >= 10:

        cambios.append(
            "score claramente reforzado"
        )

    elif delta_score <= -10:

        cambios.append(
            "score claramente deteriorado"
        )

    else:

        cambios.append(
            "score relativamente estable"
        )

    # --------------------------------------------------------
    # TENDENCIA
    # --------------------------------------------------------

    tendencia_actual = (

        float(actual["precio"])
        >
        float(actual["e50"])

        and

        float(actual["e50"])
        >
        float(actual["e200"])
    )

    if tendencia_actual:

        cambios.append(
            "estructura de tendencia preservada"
        )

    else:

        cambios.append(
            "estructura de tendencia deteriorada"
        )

    # --------------------------------------------------------
    # RVOL
    # --------------------------------------------------------

    rvol_original = float(
        original["rvol"]
    )

    rvol_actual = float(
        actual["rvol"]
    )

    if rvol_actual >= rvol_original * 1.10:

        cambios.append(
            "confirmación por volumen mejorada"
        )

    elif rvol_actual <= rvol_original * .80:

        cambios.append(
            "confirmación por volumen debilitada"
        )

    else:

        cambios.append(
            "volumen relativamente estable"
        )

    # --------------------------------------------------------
    # ROC
    # --------------------------------------------------------

    roc_original = float(
        original["roc20"]
    )

    roc_actual = float(
        actual["roc20"]
    )

    if roc_actual >= roc_original + 2:

        cambios.append(
            "momentum mejorado"
        )

    elif roc_actual <= roc_original - 2:

        cambios.append(
            "momentum debilitado"
        )

    else:

        cambios.append(
            "momentum estable"
        )

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    rsi_actual = float(
        actual["rsi"]
    )

    if rsi_actual > 75:

        cambios.append(
            "RSI actualmente elevado"
        )

    elif rsi_actual < 50:

        cambios.append(
            "RSI por debajo de la zona de fortaleza"
        )

    else:

        cambios.append(
            "RSI compatible con la tesis"
        )

    return "; ".join(
        cambios
    )


# ============================================================
# ESTADO DE LA TESIS
# ============================================================

def estado_estrategia(
    original,
    actual
):

    fuertes = 0

    debiles = 0

    # --------------------------------------------------------
    # TENDENCIA
    # --------------------------------------------------------

    precio = float(
        actual["precio"]
    )

    e50 = float(
        actual["e50"]
    )

    e200 = float(
        actual["e200"]
    )

    if (
        precio > e50
        and
        e50 > e200
    ):

        fuertes += 1

    else:

        debiles += 1

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score_original = float(
        original["score"]
    )

    score_actual = float(
        actual["score"]
    )

    if score_actual >= score_original + 10:

        fuertes += 1

    elif score_actual <= score_original - 10:

        debiles += 1

    # --------------------------------------------------------
    # VOLUMEN
    # --------------------------------------------------------

    rvol_original = float(
        original["rvol"]
    )

    rvol_actual = float(
        actual["rvol"]
    )

    if rvol_actual >= rvol_original * 1.10:

        fuertes += 1

    elif rvol_actual <= rvol_original * .80:

        debiles += 1

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    roc_original = float(
        original["roc20"]
    )

    roc_actual = float(
        actual["roc20"]
    )

    if roc_actual >= roc_original + 2:

        fuertes += 1

    elif roc_actual <= roc_original - 2:

        debiles += 1

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    rsi_actual = float(
        actual["rsi"]
    )

    if 50 <= rsi_actual <= 75:

        fuertes += 1

    elif rsi_actual < 45:

        debiles += 1

    # --------------------------------------------------------
    # RESULTADO
    # --------------------------------------------------------

    if debiles >= 3:

        return "TESIS_INVALIDADA"

    if debiles >= 2:

        return "TESIS_DEBILITADA"

    if fuertes >= 3:

        return "TESIS_REFORZADA"

    return "TESIS_ESTABLE"


# ============================================================
# CREAR COLUMNAS / NORMALIZAR HISTÓRICO
# ============================================================

def preparar_historial():

    if not os.path.exists(
        ARCHIVO_HISTORIAL
    ):

        return

    try:

        df = pd.read_csv(
            ARCHIVO_HISTORIAL,
            dtype=str,
            keep_default_na=False
        )

        columnas_originales = set(
            df.columns
        )

        # ----------------------------------------------------
        # CREAR CAMPOS NUEVOS
        # ----------------------------------------------------

        for col in CAMPOS_HISTORIAL:

            if col not in df.columns:

                df[col] = ""

        # ----------------------------------------------------
        # MIGRACIÓN HISTÓRICO ANTIGUO
        #
        # IMPORTANTE:
        #
        # Solo rellenamos campos de entrada si están vacíos.
        #
        # Nunca copiamos Score_Actual -> Score_Entrada.
        #
        # Así evitamos contaminar la tesis original.
        # ----------------------------------------------------

        MAPEO_ANTIGUO = {

            "Score":
                "Score_Entrada",

            "RVOL":
                "RVOL_Entrada",

            "RSI":
                "RSI_Entrada",

            "ROC20":
                "ROC20_Entrada",

            "ATR":
                "ATR_Entrada",

            "EMA50":
                "EMA50_Entrada",

            "EMA200":
                "EMA200_Entrada",

            "Razones":
                "Razones_Entrada",

            "Analisis_IA":
                "Analisis_IA_Entrada"
        }

        for antiguo, nuevo in MAPEO_ANTIGUO.items():

            if antiguo in columnas_originales:

                mask = (

                    df[nuevo]
                    .astype(str)
                    .str.strip()
                    == ""
                )

                df.loc[
                    mask,
                    nuevo
                ] = df.loc[
                    mask,
                    antiguo
                ]

        # ----------------------------------------------------
        # PRECIO ALERTA
        # ----------------------------------------------------

        if (
            "Precio_Alerta"
            not in columnas_originales
        ):

            if (
                "Precio_Entrada"
                in columnas_originales
            ):

                df["Precio_Alerta"] = (
                    df["Precio_Entrada"]
                )

        # ----------------------------------------------------
        # COPIAR ORIGINAL -> ACTUAL SOLO SI ACTUAL ESTÁ VACÍO
        # ----------------------------------------------------

        pares = [

            (
                "Precio_Alerta",
                "Precio_Actual"
            ),

            (
                "Score_Entrada",
                "Score_Actual"
            ),

            (
                "RVOL_Entrada",
                "RVOL_Actual"
            ),

            (
                "RSI_Entrada",
                "RSI_Actual"
            ),

            (
                "ROC20_Entrada",
                "ROC20_Actual"
            ),

            (
                "ATR_Entrada",
                "ATR_Actual"
            ),

            (
                "EMA50_Entrada",
                "EMA50_Actual"
            ),

            (
                "EMA200_Entrada",
                "EMA200_Actual"
            ),

            (
                "Razones_Entrada",
                "Razones_Actuales"
            ),

            (
                "Soporte_Entrada",
                "Soporte_Actual"
            ),

            (
                "Resistencia_Entrada",
                "Resistencia_Actual"
            )
        ]

        for origen, destino in pares:

            mask = (

                df[destino]
                .astype(str)
                .str.strip()
                == ""
            )

            df.loc[
                mask,
                destino
            ] = df.loc[
                mask,
                origen
            ]

        # ----------------------------------------------------
        # ESTADO ESTRATEGIA
        # ----------------------------------------------------

        mask_estado = (

            df["Estado_Estrategia"]
            .astype(str)
            .str.strip()
            == ""
        )

        df.loc[
            mask_estado,
            "Estado_Estrategia"
        ] = "TESIS_ESTABLE"

        # ----------------------------------------------------
        # RATIO RR
        # ----------------------------------------------------

        mask_rr = (

            df["Ratio_RR"]
            .astype(str)
            .str.strip()
            == ""
        )

        df.loc[
            mask_rr,
            "Ratio_RR"
        ] = str(
            RR_TARGET
        )

        # ----------------------------------------------------
        # ESTADO OPERATIVO
        # ----------------------------------------------------

        mask_estado_op = (

            df["Estado"]
            .astype(str)
            .str.strip()
            == ""
        )

        df.loc[
            mask_estado_op,
            "Estado"
        ] = "ACTIVA"

        # ----------------------------------------------------
        # TEXTO
        # ----------------------------------------------------

        for col in CAMPOS_TEXTO:

            if col in df.columns:

                df[col] = (
                    df[col]
                    .fillna("")
                    .astype(str)
                )

        # ----------------------------------------------------
        # NUMÉRICOS
        # ----------------------------------------------------

        for col in CAMPOS_NUMERICOS:

            if col in df.columns:

                df[col] = pd.to_numeric(
                    df[col],
                    errors="coerce"
                )

        df = df.reindex(
            columns=CAMPOS_HISTORIAL
        )

        df.to_csv(
            ARCHIVO_HISTORIAL,
            index=False
        )

        print(
            "✅ Historial preparado "
            "y columnas normalizadas."
        )

    except Exception as e:

        print(
            f"⚠️ Error preparando historial: {e}"
        )


# ============================================================
# LEER HISTORIAL
# ============================================================

def cargar_historial():

    if not os.path.exists(
        ARCHIVO_HISTORIAL
    ):

        return pd.DataFrame(
            columns=CAMPOS_HISTORIAL
        )

    preparar_historial()

    try:

        df = pd.read_csv(
            ARCHIVO_HISTORIAL,
            dtype=str,
            keep_default_na=False
        )

        for col in CAMPOS_HISTORIAL:

            if col not in df.columns:

                df[col] = ""

        for col in CAMPOS_TEXTO:

            df[col] = (
                df[col]
                .fillna("")
                .astype(str)
            )

        for col in CAMPOS_NUMERICOS:

            # Todos los campos numéricos se fuerzan a float64.
            # Esto evita errores de pandas al actualizar una columna que
            # fue inferida como int64 con un valor decimal (ej. 0.81).
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            ).astype("float64")

        return df

    except Exception as e:

        print(
            f"⚠️ Error leyendo historial: {e}"
        )

        return pd.DataFrame(
            columns=CAMPOS_HISTORIAL
        )


# ============================================================
# CONSTRUIR SNAPSHOT ORIGINAL
# ============================================================

def construir_original_desde_fila(
    r
):

    def num(
        campo,
        default=0
    ):

        try:

            value = r.get(
                campo,
                default
            )

            if pd.isna(
                value
            ):

                return default

            return float(
                value
            )

        except Exception:

            return default

    return {

        "ticker":
            str(
                r.get(
                    "Ticker",
                    ""
                )
            ),

        "empresa":
            str(
                r.get(
                    "Empresa",
                    ""
                )
            ),

        "precio":
            num(
                "Precio_Alerta"
            ),

        "score":
            num(
                "Score_Entrada"
            ),

        "rvol":
            num(
                "RVOL_Entrada"
            ),

        "rsi":
            num(
                "RSI_Entrada"
            ),

        "roc20":
            num(
                "ROC20_Entrada"
            ),

        "atr":
            num(
                "ATR_Entrada"
            ),

        "e50":
            num(
                "EMA50_Entrada"
            ),

        "e200":
            num(
                "EMA200_Entrada"
            ),

        "razones":
            str(
                r.get(
                    "Razones_Entrada",
                    ""
                )
            ),

        "soporte":
            num(
                "Soporte_Entrada"
            ),

        "resistencia":
            num(
                "Resistencia_Entrada"
            ),

        "analisis_ia":
            str(
                r.get(
                    "Analisis_IA_Entrada",
                    ""
                )
            )
    }


# ============================================================
# IA - SEGUIMIENTO
# ============================================================

def comentario_seguimiento(
    original,
    actual,
    fila,
    evolucion
):

    pnl_pct = 0.0

    score_actual = actual.get(
        "score",
        0
    )

    score_original = original.get(
        "score",
        0
    )

    try:

        precio_entrada = float(
            fila["Precio_Alerta"]
        )

        precio_actual = float(
            actual["precio"]
        )

        sl = float(
            fila["Stop_Loss"]
        )

        tp = float(
            fila["Take_Profit"]
        )

        pnl_pct = (

            (
                precio_actual
                /
                precio_entrada
            )
            - 1

        ) * 100

        distancia_sl = (

            (
                precio_actual
                -
                sl
            )
            /
            precio_actual

        ) * 100

        distancia_tp = (

            (
                tp
                -
                precio_actual
            )
            /
            precio_actual

        ) * 100

        delta_score = (

            actual["score"]
            -
            original["score"]
        )

        delta_rvol = (

            actual["rvol"]
            -
            original["rvol"]
        )

        delta_rsi = (

            actual["rsi"]
            -
            original["rsi"]
        )

        delta_roc = (

            actual["roc20"]
            -
            original["roc20"]
        )

        system_prompt = """
Eres el analista cuantitativo senior de Alura Quant.

Estás monitorizando una estrategia YA ABIERTA.

NO estás buscando una nueva entrada.

Tu tarea es comparar la tesis original que justificó
la entrada con los datos actuales y explicar cómo está
evolucionando esa estrategia.

Debes considerar:

- precio desde entrada
- tendencia
- score
- volumen
- momentum
- RSI
- soporte y resistencia
- proximidad al Stop Loss
- proximidad al Take Profit
- tesis original
- análisis IA original

Debes señalar divergencias importantes.

Si el precio mejora pero los factores que justificaron
la entrada se deterioran, debes señalarlo.

No debes:

- crear una nueva estrategia
- modificar Stop Loss
- modificar Take Profit
- recomendar una nueva entrada
- ordenar cerrar la operación

El Estado_Estrategia es una lectura analítica,
no una orden operativa.

Máximo 3 frases.
Sin listas.
Sin títulos.
Sin lenguaje robótico.
"""

        user_prompt = f"""

========================
ACTIVO
========================

{original['empresa']}
{original['ticker']}

Último dato de mercado disponible:
{actual.get('fecha_datos', '')}


========================
TESIS ORIGINAL
========================

Precio:
{precio_entrada:.2f}€

Score:
{original['score']}

RVOL:
{original['rvol']}x

RSI:
{original['rsi']}

ROC20:
{original['roc20']}%

ATR:
{original['atr']}€

EMA50:
{original['e50']}€

EMA200:
{original['e200']}€

Soporte:
{original['soporte']:.2f}€

Resistencia:
{original['resistencia']:.2f}€

Razones:
{original['razones']}

Análisis IA original:
{original['analisis_ia']}


========================
ESTADO ACTUAL
========================

Precio:
{precio_actual:.2f}€

Score:
{actual['score']}

RVOL:
{actual['rvol']}x

RSI:
{actual['rsi']}

ROC20:
{actual['roc20']}%

ATR:
{actual['atr']}€

EMA50:
{actual['e50']}€

EMA200:
{actual['e200']}€

Soporte actual:
{actual['soporte']:.2f}€

Resistencia actual:
{actual['resistencia']:.2f}€

Razones actuales:
{actual['razones']}


========================
EVOLUCIÓN
========================

P&L:
{pnl_pct:+.2f}%

Cambio Score:
{delta_score:+.0f}

Cambio RVOL:
{delta_rvol:+.2f}x

Cambio RSI:
{delta_rsi:+.2f}

Cambio ROC20:
{delta_roc:+.2f} puntos


Lectura cuantitativa:

{evolucion}


========================
ESTRATEGIA ORIGINAL
========================

Entrada:
{precio_entrada:.2f}€

Stop Loss:
{sl:.2f}€

Take Profit:
{tp:.2f}€

Distancia actual al SL:
{distancia_sl:.2f}%

Distancia actual al TP:
{distancia_tp:.2f}%


INSTRUCCIÓN

Explica cómo está evolucionando la tesis original.

Determina si está:

- reforzada
- estable
- debilitada
- invalidada

y explica brevemente por qué.

Prioriza los cambios relevantes frente a repetir
simplemente los datos.
"""

        respuesta = cliente_ia().chat.completions.create(

            model=modelo_ia(),

            messages=[

                {
                    "role":
                        "system",

                    "content":
                        system_prompt
                },

                {
                    "role":
                        "user",

                    "content":
                        user_prompt
                }
            ],

            reasoning_effort="low"
        )

        return (
            respuesta
            .choices[0]
            .message
            .content
            .strip()
        )

    except Exception as e:

        print(
            f"⚠️ Error IA seguimiento: {e}"
        )

        return (

            f"La posición presenta una evolución "
            f"del {pnl_pct:+.2f}% desde la entrada, "
            f"con un score actual de "
            f"{score_actual} frente a "
            f"{score_original} en la entrada."
        )


# ============================================================
# GUARDAR NUEVA ALERTA
# ============================================================

def guardar(
    c,
    comentario
):

    preparar_historial()

    df = cargar_historial()

    nueva_fila = {

        "Fecha":
            ahora().strftime(
                "%Y-%m-%d %H:%M"
            ),

        "Ticker":
            c["ticker"],

        "Empresa":
            c["empresa"],

        "Sector":
            c["sector"],

        "Icono":
            c["icono"],

        "Modo":
            c["modo"],

        # ----------------------------------------------------
        # ORIGINAL
        # ----------------------------------------------------

        "Precio_Alerta":
            c["precio"],

        "Score_Entrada":
            c["score"],

        "RVOL_Entrada":
            c["rvol"],

        "RSI_Entrada":
            c["rsi"],

        "ROC20_Entrada":
            c["roc20"],

        "ATR_Entrada":
            c["atr"],

        "EMA50_Entrada":
            c["e50"],

        "EMA200_Entrada":
            c["e200"],

        "Razones_Entrada":
            c["razones"],

        "Soporte_Entrada":
            c["soporte"],

        "Resistencia_Entrada":
            c["resistencia"],

        "Analisis_IA_Entrada":
            comentario.replace(
                "\n",
                " "
            ),

        # ----------------------------------------------------
        # ESTRATEGIA
        # ----------------------------------------------------

        "Stop_Loss":
            c["stop"],

        "Take_Profit":
            c["tp"],

        "Ratio_RR":
            RR_TARGET,

        "Riesgo_Euros":
            c["riesgo"],

        "Acciones":
            c["acciones"],

        "Nominal":
            c["nominal"],

        # ----------------------------------------------------
        # ACTUAL
        # ----------------------------------------------------

        "Precio_Actual":
            c["precio"],

        "Score_Actual":
            c["score"],

        "RVOL_Actual":
            c["rvol"],

        "RSI_Actual":
            c["rsi"],

        "ROC20_Actual":
            c["roc20"],

        "ATR_Actual":
            c["atr"],

        "EMA50_Actual":
            c["e50"],

        "EMA200_Actual":
            c["e200"],

        "Razones_Actuales":
            c["razones"],

        "Soporte_Actual":
            c["soporte"],

        "Resistencia_Actual":
            c["resistencia"],

        "Distancia_SL_Pct":
            round(
                (
                    (
                        c["precio"]
                        -
                        c["stop"]
                    )
                    /
                    c["precio"]
                )
                * 100,
                2
            ),

        "Distancia_TP_Pct":
            round(
                (
                    (
                        c["tp"]
                        -
                        c["precio"]
                    )
                    /
                    c["precio"]
                )
                * 100,
                2
            ),

        "P&L_Actual_Pct":
            0,

        "Estado_Estrategia":
            "TESIS_ESTABLE",

        "Ultima_Actualizacion":
            ahora().strftime(
                "%Y-%m-%d %H:%M"
            ),

        "Fecha_Mercado_Actual":
            str(c.get("fecha_datos", "")),

        "Analisis_IA_Actual":
            comentario.replace(
                "\n",
                " "
            ),

        # ----------------------------------------------------
        # OPERATIVO
        # ----------------------------------------------------

        "Estado":
            "ACTIVA",

        "Fecha_Salida":
            "",

        "Resultado_R":
            "",

        "MAE_R":
            "",

        "MFE_R":
            ""
    }

    nueva_df = pd.DataFrame(
        [nueva_fila]
    )

    df = pd.concat(
        [
            df,
            nueva_df
        ],
        ignore_index=True
    )

    for col in CAMPOS_TEXTO:

        df[col] = (
            df[col]
            .fillna("")
            .astype(str)
        )

    for col in CAMPOS_NUMERICOS:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    df = df.reindex(
        columns=CAMPOS_HISTORIAL
    )

    guardar_csv_seguro(
        df,
        ARCHIVO_HISTORIAL
    )


# ============================================================
# BLOQUEADOS
# ============================================================

def bloqueados():

    df = cargar_historial()

    if df.empty:

        return set()

    bloqueados_set = set()

    hoy = ahora().date()

    for _, r in df.iterrows():

        estado = str(
            r.get(
                "Estado",
                ""
            )
        )

        if estado == "ACTIVA":

            ticker = str(
                r.get(
                    "Ticker",
                    ""
                )
            ).strip()

            if ticker:

                bloqueados_set.add(
                    ticker
                )

            continue

        if estado == "STOP_SALTADO":

            try:

                fecha_alerta = (
                    pd.to_datetime(
                        r["Fecha"]
                    ).date()
                )

                dias = (
                    hoy
                    -
                    fecha_alerta
                ).days

                if (
                    dias
                    <
                    CUARENTENA_STOP_DIAS
                ):

                    ticker = str(
                        r["Ticker"]
                    ).strip()

                    if ticker:

                        bloqueados_set.add(
                            ticker
                        )

            except Exception:

                continue

    return bloqueados_set


# ============================================================
# ACTUALIZAR ALERTAS ACTIVAS
# ============================================================

def normalizar_fecha_mercado(valor):
    """Devuelve YYYY-MM-DD para comparar sesiones reales de mercado."""
    if valor is None or str(valor).strip() in ("", "nan", "NaT"):
        return ""

    try:
        ts = pd.Timestamp(valor)

        if pd.isna(ts):
            return ""

        # Si Yahoo entrega timestamp con zona horaria, solo nos interesa
        # la fecha de la sesión, no la hora de ejecución.
        return ts.strftime("%Y-%m-%d")

    except Exception:
        texto = str(valor).strip()
        return texto[:10] if len(texto) >= 10 else texto


def debe_llamar_ia_seguimiento(
    original,
    actual,
    estado_tesis_anterior,
    estado_tesis_nuevo
):
    """
    Decide si merece la pena consumir una llamada a Gemini.

    La IA no se llama en cada ejecución por defecto. Solo se invoca cuando
    existe un cambio material en la tesis:
      - cambio de Estado_Estrategia;
      - score +/-10 puntos o más;
      - deterioro/refuerzo relevante de volumen;
      - cambio de momentum >= 2 puntos;
      - pérdida de la estructura de tendencia;
      - cruce de RSI de zonas relevantes.

    Así las 3 ejecuciones diarias pueden actualizar los datos cuantitativos
    sin generar innecesariamente llamadas a Gemini.
    """
    if estado_tesis_anterior and estado_tesis_nuevo != estado_tesis_anterior:
        return True, "cambio de estado de tesis"

    try:
        delta_score = float(actual["score"]) - float(original["score"])
        if abs(delta_score) >= 10:
            return True, f"cambio de score {delta_score:+.0f}"

        rvol_original = float(original["rvol"])
        rvol_actual = float(actual["rvol"])
        if rvol_original > 0:
            ratio_rvol = rvol_actual / rvol_original
            if ratio_rvol >= 1.10 or ratio_rvol <= 0.80:
                return True, f"cambio relevante de RVOL {rvol_original:.2f}→{rvol_actual:.2f}"

        delta_roc = float(actual["roc20"]) - float(original["roc20"])
        if abs(delta_roc) >= 2:
            return True, f"cambio de ROC20 {delta_roc:+.2f}"

        tendencia_actual = (
            float(actual["precio"]) > float(actual["e50"])
            and float(actual["e50"]) > float(actual["e200"])
        )
        tendencia_original = (
            float(original["precio"]) > float(original["e50"])
            and float(original["e50"]) > float(original["e200"])
        )
        if tendencia_actual != tendencia_original:
            return True, "cambio de estructura de tendencia"

        rsi_original = float(original["rsi"])
        rsi_actual = float(actual["rsi"])

        zona_original = (
            "fuerte" if 50 <= rsi_original <= 75
            else "elevado" if rsi_original > 75
            else "débil"
        )
        zona_actual = (
            "fuerte" if 50 <= rsi_actual <= 75
            else "elevado" if rsi_actual > 75
            else "débil"
        )
        if zona_actual != zona_original:
            return True, f"cambio de zona RSI {rsi_original:.1f}→{rsi_actual:.1f}"

    except Exception:
        # Si los datos no permiten decidir con seguridad, no generamos una
        # llamada extra: el seguimiento cuantitativo seguirá actualizándose.
        return False, "sin cambio material detectable"

    return False, "sin cambio material"


def actualizar_alertas_activas():
    """
    Actualiza el seguimiento de alertas ACTIVA separando dos capas:

    1. PRECIO OPERATIVO: se actualiza en cada ejecución si Yahoo ofrece
       un precio actual/intradía válido. Esto permite actualizar P&L,
       distancia a SL y distancia a TP aunque no exista una nueva vela
       diaria.

    2. SNAPSHOT DIARIO: Score, RSI, ROC20, RVOL, EMAs, tesis y comentario
       IA solo se recalculan cuando Yahoo entrega una sesión diaria nueva.

    La tesis original y los campos de entrada permanecen INMUTABLES.
    """
    df = cargar_historial()
    if df.empty:
        return

    indices = df.index[df["Estado"].astype(str) == "ACTIVA"]
    if len(indices) == 0:
        print("ℹ️ No hay alertas ACTIVA para actualizar.")
        return

    print(f"\n🔄 Revisando {len(indices)} alerta(s) ACTIVA...")
    changed = False
    changed_price = False
    changed_daily = False

    for i in indices:
        ticker = str(df.at[i, "Ticker"]).strip()
        try:
            # --------------------------------------------------------
            # 1) Histórico diario: indicadores / sesión de mercado
            # --------------------------------------------------------
            datos, estado_descarga = descargar_historico_ticker(
                ticker, period=PERIODO_ACTUAL
            )
            if datos is None:
                print(f"⚠️ {ticker}: sin actualización de histórico diario. Motivo: {estado_descarga}")
                continue

            actual = obtener_estado_actual(ticker, datos)
            if actual is None:
                print(f"⚠️ {ticker}: no se pudo calcular estado actual.")
                continue

            fecha_mercado = normalizar_fecha_mercado(actual.get("fecha_datos"))
            fecha_guardada = normalizar_fecha_mercado(df.at[i, "Fecha_Mercado_Actual"])

            if not fecha_mercado:
                print(f"⚠️ {ticker}: Yahoo no devolvió una fecha de mercado válida.")
                continue

            # --------------------------------------------------------
            # 2) Precio operativo: independiente de la vela diaria
            # --------------------------------------------------------
            precio_operativo = obtener_precio_tiempo_real(ticker)
            if precio_operativo is None:
                # Si no hay intradía, usamos el último cierre diario real.
                # Esto mantiene el bot funcional sin inventar un precio.
                precio_operativo = float(actual["precio"])
                fuente_precio = "cierre diario"
            else:
                fuente_precio = "precio actual"

            entrada = float(df.at[i, "Precio_Alerta"])
            sl = float(df.at[i, "Stop_Loss"])
            tp = float(df.at[i, "Take_Profit"])

            pnl_pct = ((precio_operativo / entrada) - 1) * 100
            distancia_sl = ((precio_operativo - sl) / precio_operativo) * 100
            distancia_tp = ((tp - precio_operativo) / precio_operativo) * 100

            # Precio/P&L/SL/TP se actualizan SIEMPRE que tenemos un precio.
            df.at[i, "Precio_Actual"] = precio_operativo
            df.at[i, "Distancia_SL_Pct"] = round(distancia_sl, 2)
            df.at[i, "Distancia_TP_Pct"] = round(distancia_tp, 2)
            df.at[i, "P&L_Actual_Pct"] = round(pnl_pct, 2)
            df.at[i, "Ultima_Actualizacion"] = ahora().strftime("%Y-%m-%d %H:%M")
            changed = True
            changed_price = True

            # --------------------------------------------------------
            # 3) Si NO hay nueva vela diaria, no tocamos indicadores,
            #    Score ni tesis. Solo queda actualizado el precio.
            # --------------------------------------------------------
            if fecha_guardada and fecha_mercado <= fecha_guardada:
                print(
                    f"📍 {ticker}: {fuente_precio} {precio_operativo:.2f} | "
                    f"P&L {pnl_pct:+.2f}% | sin nueva sesión diaria "
                    f"({fecha_mercado}). Score/tesis conservados."
                )
                continue

            # --------------------------------------------------------
            # 4) Nueva sesión diaria: recalcular snapshot completo.
            # --------------------------------------------------------
            original = construir_original_desde_fila(df.loc[i])
            evolucion = evaluar_evolucion_estrategia(original, actual)
            estado_tesis = estado_estrategia(original, actual)
            estado_tesis_anterior = str(
                df.at[i, "Estado_Estrategia"]
            ).strip()

            llamada_ia, motivo_ia = debe_llamar_ia_seguimiento(
                original,
                actual,
                estado_tesis_anterior,
                estado_tesis
            )

            comentario = ""
            if llamada_ia:
                comentario = comentario_seguimiento(
                    original, actual, df.loc[i], evolucion
                )
                comentario = str(comentario or "").replace("\n", " ").strip()

            # Los indicadores se basan en la nueva vela diaria real.
            df.at[i, "Score_Actual"] = actual["score"]
            df.at[i, "RVOL_Actual"] = actual["rvol"]
            df.at[i, "RSI_Actual"] = actual["rsi"]
            df.at[i, "ROC20_Actual"] = actual["roc20"]
            df.at[i, "ATR_Actual"] = actual["atr"]
            df.at[i, "EMA50_Actual"] = actual["e50"]
            df.at[i, "EMA200_Actual"] = actual["e200"]
            df.at[i, "Razones_Actuales"] = actual["razones"]
            df.at[i, "Soporte_Actual"] = actual["soporte"]
            df.at[i, "Resistencia_Actual"] = actual["resistencia"]
            df.at[i, "Estado_Estrategia"] = estado_tesis
            df.at[i, "Fecha_Mercado_Actual"] = fecha_mercado

            if comentario:
                df.at[i, "Analisis_IA_Actual"] = comentario

            changed_daily = True

            icono = {
                "TESIS_REFORZADA": "🟢",
                "TESIS_ESTABLE": "🟡",
                "TESIS_DEBILITADA": "🟠",
                "TESIS_INVALIDADA": "🔴",
            }.get(estado_tesis, "⚪")

            print(
                f"{icono} {ticker} | Mercado {fecha_mercado} | "
                f"Actual {precio_operativo:.2f} | P&L {pnl_pct:+.2f}% | "
                f"Score {original['score']:.0f}→{actual['score']} | "
                f"Tesis: {estado_tesis} | "
                f"IA: {'OK' if comentario else 'NO NECESARIA'} "
                f"({motivo_ia})"
            )

        except Exception as e:
            print(f"⚠️ Error actualizando {ticker}: {e}")

    if changed:
        for col in CAMPOS_TEXTO:
            df[col] = df[col].fillna("").astype(str)
        for col in CAMPOS_NUMERICOS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.reindex(columns=CAMPOS_HISTORIAL)
        guardar_csv_seguro(df, ARCHIVO_HISTORIAL)

        if changed_daily:
            print("✅ Precio operativo actualizado y nuevas sesiones diarias procesadas.")
        elif changed_price:
            print("✅ Precio operativo/P&L actualizados. No había nuevas sesiones diarias.")
    else:
        print("ℹ️ No hubo datos de precio actualizables.")


# ============================================================
# AUDITORÍA SL / TP
# ============================================================

def auditar():

    """
    AUDITORÍA CORREGIDA.

    Antes:

        descargar_historico_ticker(
            ticker,
            start=inicio
        )

    podía acabar provocando errores de rango temporal
    en yfinance.

    Ahora:

        1. descargamos period=5y
        2. filtramos LOCALMENTE desde la entrada
        3. recorremos solamente las velas reales devueltas

    No se solicita nunca una fecha futura.
    """

    df = cargar_historial()

    if df.empty:

        return

    changed = False

    hoy = ahora().date()

    for i, r in df.iterrows():

        if str(
            r.get(
                "Estado",
                ""
            )
        ) != "ACTIVA":

            continue

        ticker = str(
            r.get(
                "Ticker",
                ""
            )
        ).strip()

        if not ticker:

            continue

        try:

            fecha_alerta = (
                pd.to_datetime(
                    r["Fecha"]
                ).date()
            )

            inicio = (
                fecha_alerta
                +
                timedelta(days=1)
            )

            # ------------------------------------------------
            # Si todavía no existe ninguna sesión posterior
            # a la entrada, no auditamos.
            # ------------------------------------------------

            if inicio > hoy:

                continue

            # ------------------------------------------------
            # DESCARGA SIN START NI END
            # ------------------------------------------------

            datos, estado_descarga = (
                descargar_historico_ticker(
                    ticker,
                    period=PERIODO_AUDITORIA
                )
            )

            if datos is None:

                print(
                    f"⚠️ Auditoría {ticker}: "
                    f"sin datos disponibles. "
                    f"Motivo: {estado_descarga}"
                )

                continue

            # ------------------------------------------------
            # FILTRADO LOCAL
            # ------------------------------------------------

            datos_auditoria = (
                filtrar_desde_fecha(
                    datos,
                    inicio
                )
            )

            if (
                datos_auditoria is None
                or
                datos_auditoria.empty
            ):

                print(
                    f"ℹ️ Auditoría {ticker}: "
                    f"no hay sesiones posteriores "
                    f"a {inicio} en los datos "
                    f"descargados."
                )

                continue

            sl = float(
                r["Stop_Loss"]
            )

            tp = float(
                r["Take_Profit"]
            )

            # ------------------------------------------------
            # RECORRER VELAS
            # ------------------------------------------------

            for fecha, vela in (
                datos_auditoria.iterrows()
            ):

                try:

                    fecha_comparable = (
                        pd.Timestamp(
                            fecha
                        ).date()
                    )

                except Exception:

                    continue

                if fecha_comparable < inicio:

                    continue

                # ------------------------------------------------
                # VALIDACIÓN DE OHLC
                # ------------------------------------------------

                try:

                    low = float(
                        vela.Low
                    )

                    high = float(
                        vela.High
                    )

                except Exception:

                    continue

                if pd.isna(low) or pd.isna(high):

                    continue

                # ------------------------------------------------
                # CRITERIO CONSERVADOR
                #
                # Si la misma vela toca SL y TP,
                # asumimos STOP primero.
                # ------------------------------------------------

                if low <= sl:

                    estado = (
                        "STOP_SALTADO"
                    )

                    resultado = -1.0

                elif high >= tp:

                    estado = (
                        "OBJETIVO_CUMPLIDO"
                    )

                    resultado = RR_TARGET

                else:

                    continue

                # ------------------------------------------------
                # ACTUALIZAR ESTADO OPERATIVO
                #
                # NO TOCAMOS:
                #
                # Precio_Alerta
                # Score_Entrada
                # RVOL_Entrada
                # ...
                # Stop_Loss
                # Take_Profit
                # ------------------------------------------------

                df.at[
                    i,
                    "Estado"
                ] = estado

                df.at[
                    i,
                    "Fecha_Salida"
                ] = pd.Timestamp(
                    fecha
                ).strftime(
                    "%Y-%m-%d"
                )

                df.at[
                    i,
                    "Resultado_R"
                ] = resultado

                changed = True

                print(

                    f"{'🔴' if resultado < 0 else '🟢'} "

                    f"{ticker} -> "

                    f"{estado} | "

                    f"{pd.Timestamp(fecha):%Y-%m-%d}"
                )

                break

        except Exception as e:

            print(
                f"⚠️ Error auditando "
                f"{ticker}: {e}"
            )

            continue

    # ========================================================
    # GUARDAR CAMBIOS
    # ========================================================

    if changed:

        for col in CAMPOS_TEXTO:

            df[col] = (
                df[col]
                .fillna("")
                .astype(str)
            )

        for col in CAMPOS_NUMERICOS:

            # Todos los campos numéricos se fuerzan a float64.
            # Esto evita errores de pandas al actualizar una columna que
            # fue inferida como int64 con un valor decimal (ej. 0.81).
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            ).astype("float64")

        df = df.reindex(
            columns=CAMPOS_HISTORIAL
        )

        df.to_csv(
            ARCHIVO_HISTORIAL,
            index=False
        )

    # ========================================================
    # ESTADÍSTICAS
    # ========================================================

    cerradas = df[
        df["Estado"]
        .astype(str)
        .str.contains(
            "OBJETIVO|STOP",
            regex=True,
            na=False
        )
    ]

    if len(cerradas):

        resultados = pd.to_numeric(
            cerradas["Resultado_R"],
            errors="coerce"
        )

        expectancy = (
            resultados
            .dropna()
            .mean()
        )

        if pd.notna(
            expectancy
        ):

            print(
                f"📊 Cerradas "
                f"{len(cerradas)} | "
                f"Expectancy "
                f"{expectancy:.2f} R"
            )


# ============================================================
# GIT
# ============================================================

def git():

    try:
        # Git debe ejecutarse sobre el repositorio del bot, no sobre
        # la carpeta desde la que se lanzó Python.
        repo_dir = BASE_DIR

        subprocess.run(
            [
                "git",
                "-C",
                repo_dir,
                "add",
                "bot.py",
                os.path.basename(ARCHIVO_HISTORIAL),
            ],
            check=True
        )

        status = subprocess.run(

            [
                "git",
                "-C",
                repo_dir,
                "status",
                "--porcelain"
            ],

            capture_output=True,

            text=True
        )

        if status.stdout.strip():

            subprocess.run(

                [
                    "git",
                    "-C",
                    repo_dir,
                    "commit",
                    "-m",
                    f"Alura Quant {modo_actual()} "
                    "actualización automática"
                ],

                check=True
            )

            try:

                branch = os.getenv("GITHUB_REF_NAME", "").strip()

                if not branch:
                    branch_result = subprocess.run(
                        [
                            "git",
                            "-C",
                            repo_dir,
                            "branch",
                            "--show-current"
                        ],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    branch = branch_result.stdout.strip() or "main"

                subprocess.run(

                    [
                        "git",
                        "-C",
                        repo_dir,
                        "push",
                        "origin",
                        f"HEAD:{branch}"
                    ],

                    check=True
                )

                print(
                    "✅ Git push completado."
                )

            except Exception as e:

                print(
                    "⚠️ Commit local realizado, "
                    "pero GitHub no respondió: "
                    f"{e}"
                )

        else:

            print(
                "ℹ️ Git: no hay cambios."
            )

    except Exception as e:

        print(
            f"ℹ️ Git: {e}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    modo = modo_actual()

    print(
        "\n"
        "============================================================\n"
        "ALURA QUANT V4.4\n"
        "============================================================"
    )

    print(
        f"Fecha ejecución: "
        f"{ahora():%Y-%m-%d %H:%M}"
    )

    print(
        f"Modo: "
        f"{modo}"
    )

    print(
        f"Activos universo: "
        f"{len(activos)}"
    )

    print(
        f"IA: {IA_PROVIDER} / {modelo_ia()}"
    )

    if IA_PROVIDER == "gemini":
        print(
            "IA Gemini: comentarios bajo demanda "
            "solo ante cambios materiales de tesis."
        )

    # ========================================================
    # 1. PREPARAR HISTORIAL
    # ========================================================

    print(
        "\n📁 1. PREPARANDO HISTORIAL"
    )

    preparar_historial()

    # ========================================================
    # 2. AUDITORÍA
    # ========================================================

    print(
        "\n🔎 2. AUDITORÍA SL / TP"
    )

    auditar()

    # ========================================================
    # 3. SEGUIMIENTO ACTIVAS
    # ========================================================

    print(
        "\n🧠 3. SEGUIMIENTO DE TESIS ACTIVAS"
    )

    actualizar_alertas_activas()

    # ========================================================
    # 4. BLOQUEADOS
    # ========================================================

    blocked = bloqueados()

    print(
        f"\n🔒 Tickers bloqueados: "
        f"{len(blocked)}"
    )

    # ========================================================
    # 5. NUEVAS OPORTUNIDADES
    # ========================================================

    activos_a_analizar = [

        t

        for t in activos

        if t not in blocked
    ]

    print(
        f"🔍 Tickers a analizar: "
        f"{len(activos_a_analizar)}"
    )

    nuevas_alertas = []

    # ========================================================
    # 6. DESCARGA POR LOTES
    # ========================================================

    for inicio in range(

        0,

        len(activos_a_analizar),

        TAMANO_LOTE
    ):

        lote = activos_a_analizar[
            inicio:
            inicio + TAMANO_LOTE
        ]

        print(

            f"\n📥 Lote "
            f"{inicio // TAMANO_LOTE + 1} "
            f"| "
            f"{len(lote)} activos"
        )

        resultados_lote = descargar_lote(
            lote,
            period=PERIODO_ACTUAL
        )

        for ticker in lote:

            try:

                datos, estado_descarga = (
                    resultados_lote.get(
                        ticker,
                        (
                            None,
                            "SIN_RESULTADO"
                        )
                    )
                )

                if datos is None:

                    print(
                        f"⚠️ {ticker}: "
                        f"sin datos disponibles. "
                        f"No se marcará como delisted. "
                        f"Motivo: "
                        f"{estado_descarga}"
                    )

                    continue

                resultado = (
                    procesar_dataframe_activo(
                        ticker,
                        datos
                    )
                )

                if resultado:

                    nuevas_alertas.append(
                        resultado
                    )

            except Exception as e:

                print(
                    f"⚠️ Error "
                    f"{ticker}: {e}"
                )

    # ========================================================
    # 7. ORDENAR
    # ========================================================

    nuevas_alertas.sort(

        key=lambda x: (

            x["score"],
            x["rvol"]
        ),

        reverse=True
    )

    print(
        f"\n📊 Nuevas señales: "
        f"{len(nuevas_alertas)}"
    )

    # ========================================================
    # 8. GUARDAR NUEVAS ALERTAS
    # ========================================================

    for c in nuevas_alertas:

        comentario = (
            comentario_entrada(c)
        )

        guardar(
            c,
            comentario
        )

        print(
            "\n"
            f"{c['icono']} "
            f"{c['empresa']} "
            f"({c['ticker']})"
        )

        print(
            f"Datos mercado: "
            f"{c['fecha_datos']}"
        )

        print(
            f"Score: "
            f"{c['score']}"
        )

        print(
            f"Entrada: "
            f"{c['precio']:.2f}€"
        )

        print(
            f"SL: "
            f"{c['stop']:.2f}€"
        )

        print(
            f"TP: "
            f"{c['tp']:.2f}€"
        )

        print(
            f"Acciones: "
            f"{c['acciones']}"
        )

        print(
            f"Riesgo: "
            f"{c['riesgo']:.2f}€"
        )

        print(
            f"IA: "
            f"{comentario}"
        )

    # ========================================================
    # 9. GIT
    # ========================================================

    print(
        "\n💾 Guardando cambios..."
    )

    git()

    print(
        "\n============================================================"
    )

    print(
        "✅ ALURA QUANT V4.3 FINALIZADO"
    )

    print(
        "============================================================"
    )


# ============================================================
# EJECUCIÓN
# ============================================================

if __name__ == "__main__":

    main()