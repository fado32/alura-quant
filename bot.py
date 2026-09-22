# ============================================================
# ALURA QUANT V5.0 - SUPABASE EDITION
# ============================================================
#
# ARQUITECTURA
#
# 1. Cada alerta guarda una TESIS ORIGINAL INMUTABLE.
# 2. Cada ejecución actualiza únicamente el ESTADO ACTUAL.
# 3. La IA compara TESIS ORIGINAL vs SITUACIÓN ACTUAL.
# 4. Stop Loss y Take Profit originales no se modifican.
# 5. Estado operativo: ACTIVA, STOP_SALTADO, OBJETIVO_CUMPLIDO.
# 6. Estado_Estrategia: TESIS_REFORZADA, TESIS_ESTABLE, 
#                      TESIS_DEBILITADA, TESIS_INVALIDADA.
# 7. Integración nativa con Supabase (Base de datos en la nube).
# ============================================================

import os
import subprocess
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from openai import OpenAI
from supabase import create_client


# ============================================================
# CONFIGURACIÓN SUPABASE Y ENTORNO
# ============================================================

TZ = ZoneInfo("Europe/Madrid")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ ADVERTENCIA: Faltan SUPABASE_URL o SUPABASE_KEY en las variables de entorno.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

MODO_EJECUCION = os.getenv("ALURA_MODO", "AUTO").strip()
# AUTO | 14 | 18 | 22

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
PERIODO_ACTUAL = "1y"
PERIODO_AUDITORIA = "5y"


# ============================================================
# IA
# ============================================================
IA_PROVIDER = os.getenv("IA_PROVIDER", "gemini").strip().lower()
MODELO_GEMINI = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
MODELO_LOCAL = os.getenv("OLLAMA_MODEL", "llama3.2").strip()
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

def cliente_ia():
    if IA_PROVIDER == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Falta GEMINI_API_KEY. Configúrala como variable de entorno o GitHub Secret.")
        return OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)
    if IA_PROVIDER == "ollama":
        return OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
    raise RuntimeError(f"IA_PROVIDER no válido: {IA_PROVIDER}. Usa 'gemini' u 'ollama'.")

def modelo_ia():
    return MODELO_GEMINI if IA_PROVIDER == "gemini" else MODELO_LOCAL


# ============================================================
# UNIVERSO BASE (DESDE SUPABASE)
# ============================================================

MAESTRO_ACTIVOS_BASE = {
    "TLGO.MC": ("Talgo", "Industrial", "🚆"),
    "SAN.MC": ("Banco Santander", "Banca", "🏦"),
    "BBVA.MC": ("BBVA", "Banca", "🏦"),
    "ITX.MC": ("Inditex", "Consumo Cíclico", "👗"),
}

def cargar_universo():
    universo = dict(MAESTRO_ACTIVOS_BASE)
    
    if supabase:
        try:
            response = supabase.table("universo_activos").select("ticker, empresa, sector, icono, activo").execute()
            if response.data:
                for r in response.data:
                    # Opcional: puedes omitir si activo es False, o cargarlos todos
                    ticker = str(r.get("ticker", "")).strip()
                    if ticker and r.get("activo", True):
                        universo[ticker] = (
                            str(r.get("empresa", ticker)),
                            str(r.get("sector", "General")),
                            str(r.get("icono", "📈"))
                        )
                print(f"✅ Universo cargado desde Supabase: {len(universo)} activos.")
                return universo
        except Exception as e:
            print(f"⚠️ Error cargando universo desde Supabase, usando respaldo base: {e}")

    # Fallback archivo local si Supabase no responde
    archivo_universo = os.path.join(BASE_DIR, "universo_activos.csv")
    if os.path.exists(archivo_universo):
        try:
            df = pd.read_csv(archivo_universo, dtype=str, keep_default_na=False)
            for _, r in df.iterrows():
                ticker = str(r.get("Ticker", "")).strip()
                if ticker:
                    universo[ticker] = (
                        str(r.get("Empresa", ticker)),
                        str(r.get("Sector", "General")),
                        str(r.get("Icono", "📈"))
                    )
        except Exception as e:
            print(f"⚠️ Error cargando universo local: {e}")

    return universo

MAESTRO_ACTIVOS = cargar_universo()
activos = list(MAESTRO_ACTIVOS.keys())


# ============================================================
# CAMPOS DEL HISTORIAL (MAPEO CON SUPABASE)
# ============================================================

CAMPOS_HISTORIAL = [
    "Fecha", "Ticker", "Empresa", "Sector", "Icono", "Modo",
    "Precio_Alerta", "Score_Entrada", "RVOL_Entrada", "RSI_Entrada", "ROC20_Entrada", "ATR_Entrada",
    "EMA50_Entrada", "EMA200_Entrada", "Razones_Entrada", "Soporte_Entrada", "Resistencia_Entrada", "Analisis_IA_Entrada",
    "Stop_Loss", "Take_Profit", "Ratio_RR", "Riesgo_Euros", "Acciones", "Nominal",
    "Precio_Actual", "Score_Actual", "RVOL_Actual", "RSI_Actual", "ROC20_Actual", "ATR_Actual",
    "EMA50_Actual", "EMA200_Actual", "Razones_Actuales", "Soporte_Actual", "Resistencia_Actual",
    "Distancia_SL_Pct", "Distancia_TP_Pct", "P&L_Actual_Pct", "Estado_Estrategia",
    "Ultima_Actualizacion", "Fecha_Mercado_Actual", "Analisis_IA_Actual",
    "Estado", "Fecha_Salida", "Resultado_R", "MAE_R", "MFE_R"
]

# Mapeo exacto de nombres de columnas en Python a snake_case en Supabase
MAPEO_COLUMNAS_SUPABASE = {
    "Fecha": "fecha", "Ticker": "ticker", "Empresa": "empresa", "Sector": "sector", "Icono": "icono", "Modo": "modo",
    "Precio_Alerta": "precio_alerta", "Score_Entrada": "score_entrada", "RVOL_Entrada": "rvol_entrada",
    "RSI_Entrada": "rsi_entrada", "ROC20_Entrada": "roc20_entrada", "ATR_Entrada": "atr_entrada",
    "EMA50_Entrada": "ema50_entrada", "EMA200_Entrada": "ema200_entrada", "Razones_Entrada": "razones_entrada",
    "Soporte_Entrada": "soporte_entrada", "Resistencia_Entrada": "resistencia_entrada", "Analisis_IA_Entrada": "analisis_ia_entrada",
    "Stop_Loss": "stop_loss", "Take_Profit": "take_profit", "Ratio_RR": "ratio_rr", "Riesgo_Euros": "riesgo_euros",
    "Acciones": "acciones", "Nominal": "nominal", "Precio_Actual": "precio_actual", "Score_Actual": "score_actual",
    "RVOL_Actual": "rvol_actual", "RSI_Actual": "rsi_actual", "ROC20_Actual": "roc20_actual", "ATR_Actual": "atr_actual",
    "EMA50_Actual": "ema50_actual", "EMA200_Actual": "ema200_actual", "Razones_Actuales": "razones_actuales",
    "Soporte_Actual": "soporte_actual", "Resistencia_Actual": "resistencia_actual", "Distancia_SL_Pct": "distancia_sl_pct",
    "Distancia_TP_Pct": "distancia_tp_pct", "P&L_Actual_Pct": "p_l_actual_pct", "Estado_Estrategia": "estado_estrategia",
    "Ultima_Actualizacion": "ultima_actualizacion", "Fecha_Mercado_Actual": "fecha_mercado_actual",
    "Analisis_IA_Actual": "analisis_ia_actual", "Estado": "estado", "Fecha_Salida": "fecha_salida",
    "Resultado_R": "resultado_r", "MAE_R": "mae_r", "MFE_R": "mfe_r"
}


# ============================================================
# UTILIDADES
# ============================================================

def ahora():
    return datetime.now(TZ)

def modo_actual():
    if MODO_EJECUCION in ("14", "18", "22"):
        return MODO_EJECUCION
    hora = ahora().hour
    minuto = ahora().minute
    if hora < 16:
        return "14"
    if hora < 21 or (hora == 21 and minuto < 30):
        return "18"
    return "22"

def limpiar_fecha_indice(datos):
    if datos is None or datos.empty:
        return datos
    datos = datos.copy()
    try:
        idx = pd.to_datetime(datos.index, errors="coerce")
        datos.index = idx
        datos = datos[~datos.index.isna()]
        datos = datos.sort_index()
    except Exception:
        pass
    return datos

def norm(df):
    if df is None:
        return df
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        posibles = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
        nivel_encontrado = None
        for nivel in range(df.columns.nlevels):
            valores = set(str(x) for x in df.columns.get_level_values(nivel))
            if len(posibles.intersection(valores)) >= 3:
                nivel_encontrado = nivel
                break
        if nivel_encontrado is not None:
            df.columns = df.columns.get_level_values(nivel_encontrado)
        else:
            df.columns = df.columns.get_level_values(0)
    return limpiar_fecha_indice(df)


# ============================================================
# VALIDACIÓN DE DATOS
# ============================================================

def validar_datos_mercado(datos):
    if datos is None:
        return False, "Yahoo devolvió None"
    if datos.empty:
        return False, "Yahoo devolvió un DataFrame vacío"
    datos = norm(datos)
    columnas_necesarias = ["Close", "High", "Low", "Volume"]
    faltan = [c for c in columnas_necesarias if c not in datos.columns]
    if faltan:
        return False, "Faltan columnas: " + ", ".join(faltan)
    datos = datos.dropna(subset=columnas_necesarias)
    if datos.empty:
        return False, "No existen velas válidas después de eliminar NaN"
    return True, datos


# ============================================================
# DESCARGA ROBUSTA YAHOO
# ============================================================

def obtener_precio_tiempo_real(ticker):
    try:
        info = yf.Ticker(ticker).fast_info
        precio = info.get("last_price")
        if precio is not None and pd.notna(precio) and float(precio) > 0:
            return float(precio)
    except Exception:
        pass

    for intervalo in ("5m", "1m"):
        try:
            datos = yf.Ticker(ticker).history(period="1d", interval=intervalo, auto_adjust=True, actions=False)
            if datos is None or datos.empty or "Close" not in datos.columns:
                continue
            serie = pd.to_numeric(datos["Close"], errors="coerce").dropna()
            if not serie.empty and float(serie.iloc[-1]) > 0:
                return float(serie.iloc[-1])
        except Exception:
            continue
    return None

def descargar_historico_ticker(ticker, period=PERIODO_ACTUAL):
    ultimo_error = None
    for intento in range(1, MAX_REINTENTOS_YAHOO + 1):
        try:
            datos = yf.download(ticker, period=period, interval="1d", auto_adjust=True, actions=False, progress=False, threads=False, timeout=30)
            valido, resultado = validar_datos_mercado(datos)
            if valido:
                return resultado, "OK"
            ultimo_error = resultado
        except Exception as e:
            ultimo_error = str(e)

        try:
            datos = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True, actions=False)
            valido, resultado = validar_datos_mercado(datos)
            if valido:
                return resultado, "OK"
            ultimo_error = resultado
        except Exception as e:
            ultimo_error = str(e)

        if intento < MAX_REINTENTOS_YAHOO:
            time.sleep(ESPERA_REINTENTO_YAHOO)

    mensaje = str(ultimo_error or "error desconocido")
    if "empty" in mensaje.lower() or "no price data" in mensaje.lower() or "possibly delisted" in mensaje.lower():
        return None, "SIN_DATOS: " + mensaje
    return None, "ERROR_YAHOO: " + mensaje


# ============================================================
# FILTRADO LOCAL Y FECHAS
# ============================================================

def filtrar_desde_fecha(datos, fecha_inicio):
    if datos is None or datos.empty:
        return datos
    datos = norm(datos)
    try:
        fecha_inicio = pd.Timestamp(fecha_inicio).normalize()
    except Exception:
        return datos.iloc[0:0]
    indice = pd.to_datetime(datos.index, errors="coerce")
    mascara = indice.normalize() >= fecha_inicio
    return datos.loc[mascara].copy()

def ultima_sesion_real(datos):
    if datos is None or datos.empty:
        return None
    datos = norm(datos)
    datos = datos.dropna(subset=["Close", "High", "Low", "Volume"])
    if datos.empty:
        return None
    return datos.index[-1]


# ============================================================
# DESCARGA POR LOTES
# ============================================================

def descargar_lote(tickers, period=PERIODO_ACTUAL):
    if not tickers:
        return {}
    resultado = {}
    ultimo_error = None

    for intento in range(1, MAX_REINTENTOS_YAHOO + 1):
        try:
            datos_lote = yf.download(tickers, period=period, interval="1d", auto_adjust=True, actions=False, group_by="ticker", progress=False, threads=True, timeout=30)
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
                            if valido:
                                resultado[ticker] = (datos_validos, "OK")
                            else:
                                resultado[ticker] = (None, datos_validos)
                        except Exception as e:
                            resultado[ticker] = (None, "ERROR_EXTRACCION: " + str(e))
                    
                    faltantes = [t for t in tickers if resultado.get(t, (None, ""))[0] is None]
                    if not faltantes:
                        return resultado
                    for ticker in faltantes:
                        datos, estado = descargar_historico_ticker(ticker, period=period)
                        resultado[ticker] = (datos, estado)
                    return resultado
            else:
                ultimo_error = "Yahoo devolvió el lote vacío"
        except Exception as e:
            ultimo_error = str(e)

        if intento < MAX_REINTENTOS_YAHOO:
            time.sleep(ESPERA_REINTENTO_YAHOO)

    for ticker in tickers:
        if ticker in resultado and resultado[ticker][0] is not None:
            continue
        datos, estado = descargar_historico_ticker(ticker, period=period)
        resultado[ticker] = (datos, estado if datos is not None else ("ERROR_YAHOO: " + str(ultimo_error or estado)))
    return resultado


# ============================================================
# INDICADORES TÉCNICOS
# ============================================================

def rsi(s, n=14):
    z = s.diff()
    g = z.clip(lower=0)
    l = -z.clip(upper=0)
    ag = g.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    al = l.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    rs = ag / al.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))

def atr(d, n=14):
    p = d.Close.shift()
    tr = pd.concat([d.High - d.Low, (d.High - p).abs(), (d.Low - p).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean()

def preparar_indicadores(d):
    d = d.copy()
    d["E20"] = d.Close.ewm(span=20, adjust=False).mean()
    d["E50"] = d.Close.ewm(span=50, adjust=False).mean()
    d["E200"] = d.Close.ewm(span=200, adjust=False).mean()
    d["RSI"] = rsi(d.Close)
    d["ATR"] = atr(d)
    d["VM20"] = d.Volume.rolling(20).mean()
    d["TO20"] = (d.Close * d.Volume).rolling(20).mean()
    d["ROC20"] = d.Close.pct_change(20) * 100
    d["H20"] = d.High.rolling(20).max().shift(1)
    d["CLV"] = ((d.Close - d.Low) / (d.High - d.Low).replace(0, pd.NA)).astype("float64").fillna(0.0)
    return d


# ============================================================
# ESTADO ACTUAL Y PROCESAMIENTO
# ============================================================

def obtener_estado_actual(t, d):
    if d is None:
        return None
    d = norm(d)
    if len(d) < 220:
        return None
    d = preparar_indicadores(d)
    x = d.iloc[-1]
    requeridos = ["Close", "E50", "E200", "RSI", "ATR", "VM20", "TO20", "ROC20", "H20"]
    if any(pd.isna(x[k]) for k in requeridos):
        return None

    price = float(x.Close)
    e50 = float(x.E50)
    e200 = float(x.E200)
    rsi_actual = float(x.RSI)
    atr_actual = float(x.ATR)
    rvol = float(x.Volume / x.VM20) if float(x.VM20) > 0 else 0
    liquidez = float(x.TO20)
    roc20 = float(x.ROC20)
    ruptura = price > float(x.H20)
    clv = float(x.CLV)

    score = 0
    razones = []
    tests = [
        (price > e50, 15, "Precio > EMA50"),
        (e50 > e200, 20, "EMA50 > EMA200"),
        (55 <= rsi_actual <= 75, 15, "RSI 55-75"),
        (roc20 > 5, 10, "ROC20 > 5%"),
        (rvol >= 1.5, 15, "RVOL >= 1.5x"),
        (1.2 <= rvol < 1.5, 8, "RVOL >= 1.2x"),
        (clv >= .70, 5, "Cierre cerca de máximos"),
        (ruptura, 15, "Ruptura máximo 20 sesiones")
    ]

    for condicion, puntos, texto in tests:
        if condicion:
            score += puntos
            razones.append(texto)

    info = MAESTRO_ACTIVOS.get(t, (t, "General", "📈"))
    fecha_datos = ultima_sesion_real(d)

    return {
        "ticker": t, "empresa": info[0], "sector": info[1], "icono": info[2],
        "precio": round(price, 2), "score": int(score), "rvol": round(rvol, 2),
        "rsi": round(rsi_actual, 2), "roc20": round(roc20, 2), "atr": round(atr_actual, 2),
        "e50": round(e50, 2), "e200": round(e200, 2), "razones": "; ".join(razones),
        "soporte": round(float(d.Low.iloc[-16:-1].min()), 2),
        "resistencia": round(float(d.High.iloc[-61:-1].max()), 2),
        "liquidez": round(liquidez, 2), "fecha_datos": fecha_datos
    }

def procesar_dataframe_activo(t, d):
    estado = obtener_estado_actual(t, d)
    if estado is None:
        return None
    modo = modo_actual()
    score = estado["score"]
    rvol = estado["rvol"]
    precio = estado["precio"]
    e50 = estado["e50"]
    e200 = estado["e200"]
    liquidez = estado["liquidez"]

    if liquidez < LIQUIDEZ_MIN_EUR:
        return None
    umbral = UMBRAL_SCORE_14 if modo == "14" else UMBRAL_SCORE_18
    if score < umbral or rvol < 1.2 or not (precio > e50 and e50 > e200):
        return None

    soporte = estado["soporte"]
    resistencia = estado["resistencia"]
    atr_actual = estado["atr"]
    stop = min(precio - ATR_MULTIPLICADOR * atr_actual, soporte * .99)
    riesgo_unitario = precio - stop

    if riesgo_unitario <= 0 or riesgo_unitario > precio * .20:
        return None

    acciones = int((CAPITAL * RIESGO_POR_OPERACION) / riesgo_unitario)
    if acciones < 1:
        return None

    info = MAESTRO_ACTIVOS.get(t, (t, "General", "📈"))
    take_profit = precio + RR_TARGET * riesgo_unitario

    return {
        "ticker": t, "empresa": info[0], "sector": info[1], "icono": info[2], "modo": modo,
        "precio": precio, "score": estado["score"], "rvol": estado["rvol"], "rsi": estado["rsi"],
        "roc20": estado["roc20"], "atr": estado["atr"], "e50": estado["e50"], "e200": estado["e200"],
        "razones": estado["razones"], "soporte": soporte, "resistencia": resistencia,
        "stop": round(stop, 2), "tp": round(take_profit, 2), "acciones": acciones,
        "nominal": round(acciones * precio, 2), "riesgo": round(acciones * riesgo_unitario, 2),
        "fecha_datos": estado["fecha_datos"]
    }


# ============================================================
# IA - ENTRADA Y SEGUIMIENTO
# ============================================================

def comentario_entrada(c):
    try:
        system_prompt = "Eres el analista cuantitativo senior de Alura Quant. Explica en 2 o 3 frases por qué la acción ha sido incluida y cuál es la tesis cuantitativa integrando tendencia, momentum y volumen. Sin listas, sin títulos."
        user_prompt = f"Activo: {c['empresa']} ({c['ticker']})\nPrecio: {c['precio']}€\nScore: {c['score']}/100\nRVOL: {c['rvol']}x\nRSI: {c['rsi']}\nROC20: {c['roc20']}%\nRazones: {c['razones']}\nStop Loss: {c['stop']}€\nTake Profit: {c['tp']}€"
        respuesta = cliente_ia().chat.completions.create(
            model=modelo_ia(),
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            reasoning_effort="low"
        )
        time.sleep(3)
        return respuesta.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ Error IA entrada: {e}")
        return f"Entrada basada en estructura cuantitativa favorable, score {c['score']}/100 y RVOL {c['rvol']}x."

def evaluar_evolucion_estrategia(original, actual):
    cambios = []
    delta_score = float(actual["score"]) - float(original["score"])
    cambios.append("score claramente reforzado" if delta_score >= 10 else ("score claramente deteriorado" if delta_score <= -10 else "score relativamente estable"))
    
    tendencia = float(actual["precio"]) > float(actual["e50"]) and float(actual["e50"]) > float(actual["e200"])
    cambios.append("estructura de tendencia preservada" if tendencia else "estructura de tendencia deteriorada")
    
    rvol_orig, rvol_act = float(original["rvol"]), float(actual["rvol"])
    cambios.append("volumen mejorado" if rvol_act >= rvol_orig * 1.10 else ("volumen debilitado" if rvol_act <= rvol_orig * .80 else "volumen estable"))
    
    return "; ".join(cambios)

def estado_estrategia(original, actual):
    fuertes, debiles = 0, 0
    if float(actual["precio"]) > float(actual["e50"]) > float(actual["e200"]): fuertes += 1
    else: debiles += 1
    
    if float(actual["score"]) >= float(original["score"]) + 10: fuertes += 1
    elif float(actual["score"]) <= float(original["score"]) - 10: debiles += 1

    if debiles >= 3: return "TESIS_INVALIDADA"
    if debiles >= 2: return "TESIS_DEBILITADA"
    if fuertes >= 3: return "TESIS_REFORZADA"
    return "TESIS_ESTABLE"

def comentario_seguimiento(original, actual, fila, evolucion):
    try:
        pnl_pct = ((float(actual["precio"]) / float(fila["precio_alerta"])) - 1) * 100
        system_prompt = "Eres el analista cuantitativo senior de Alura Quant monitorizando una estrategia abierta. Explica en max 3 frases cómo evoluciona la tesis original. Sin listas ni títulos."
        user_prompt = f"Activo: {original['empresa']} ({original['ticker']})\nP&L: {pnl_pct:+.2f}%\nLectura: {evolucion}"
        respuesta = cliente_ia().chat.completions.create(
            model=modelo_ia(),
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            reasoning_effort="low"
        )
        time.sleep(3)
        return respuesta.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ Error IA seguimiento: {e}")
        return f"Evolución con P&L del {pnl_pct:+.2f}% y score actual de {actual['score']}."


# ============================================================
# GESTIÓN SUPABASE (HISTORIAL Y ALERTAS)
# ============================================================

def cargar_historial():
    """Carga todo el historial de alertas desde la tabla de Supabase."""
    if not supabase:
        print("⚠️ Supabase no configurado. Historial vacío.")
        return pd.DataFrame(columns=CAMPOS_HISTORIAL)
    
    try:
        response = supabase.table("historial_alertas").select("*").execute()
        if response.data:
            df = pd.DataFrame(response.data)
            # Renombrar columnas de Supabase (snake_case) a nombres internos del bot
            inv_map = {v: k for k, v in MAPEO_COLUMNAS_SUPABASE.items()}
            df = df.rename(columns=inv_map)
            
            for col in CAMPOS_HISTORIAL:
                if col not in df.columns:
                    df[col] = ""
            return df
    except Exception as e:
        print(f"⚠️ Error cargando historial desde Supabase: {e}")
    
    return pd.DataFrame(columns=CAMPOS_HISTORIAL)

def guardar_en_supabase(fila_dict):
    """Inserta una nueva alerta en la tabla de Supabase."""
    if not supabase:
        return
    try:
        # Convertir claves al formato de Supabase
        registro_db = {}
        for k, v in fila_dict.items():
            db_key = MAPEO_COLUMNAS_SUPABASE.get(k, k.lower())
            if pd.isna(v) or v == "":
                registro_db[db_key] = None
            else:
                registro_db[db_key] = v
                
        supabase.table("historial_alertas").insert(registro_db).execute()
        print(f"☁️ Alerta guardada en Supabase para {fila_dict.get('Ticker')}")
    except Exception as e:
        print(f"⚠️ Error guardando alerta en Supabase: {e}")

def actualizar_fila_en_supabase(ticker, fecha_creacion, cambios_dict):
    """Actualiza una alerta existente en Supabase basada en su Ticker y Fecha."""
    if not supabase:
        return
    try:
        registro_db = {}
        for k, v in cambios_dict.items():
            db_key = MAPEO_COLUMNAS_SUPABASE.get(k, k.lower())
            registro_db[db_key] = None if (pd.isna(v) or v == "") else v

        supabase.table("historial_alertas").update(registro_db).eq("ticker", ticker).eq("fecha", fecha_creacion).execute()
    except Exception as e:
        print(f"⚠️ Error actualizando Supabase para {ticker}: {e}")


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
        estado = str(r.get("Estado", ""))
        if estado == "ACTIVA":
            ticker = str(r.get("Ticker", "")).strip()
            if ticker: bloqueados_set.add(ticker)
            continue
        if estado == "STOP_SALTADO":
            try:
                fecha_alerta = pd.to_datetime(r["Fecha"]).date()
                if (hoy - fecha_alerta).days < CUARENTENA_STOP_DIAS:
                    ticker = str(r["Ticker"]).strip()
                    if ticker: bloqueados_set.add(ticker)
            except Exception:
                continue
    return bloqueados_set


# ============================================================
# ACTUALIZAR ALERTAS ACTIVAS
# ============================================================

def normalizar_fecha_mercado(valor):
    if valor is None or str(valor).strip() in ("", "nan", "NaT"):
        return ""
    try:
        ts = pd.Timestamp(valor)
        return ts.strftime("%Y-%m-%d") if not pd.isna(ts) else ""
    except Exception:
        texto = str(valor).strip()
        return texto[:10] if len(texto) >= 10 else texto

def actualizar_alertas_activas():
    df = cargar_historial()
    if df.empty:
        print("ℹ️ No hay historial de alertas en Supabase.")
        return

    indices = df.index[df["Estado"].astype(str) == "ACTIVA"]
    if len(indices) == 0:
        print("ℹ️ No hay alertas ACTIVA para actualizar.")
        return

    print(f"\n🔄 Revisando {len(indices)} alerta(s) ACTIVA en Supabase...")

    for i in indices:
        ticker = str(df.at[i, "Ticker"]).strip()
        fecha_creacion = str(df.at[i, "Fecha"])
        try:
            datos, estado_descarga = descargar_historico_ticker(ticker, period=PERIODO_ACTUAL)
            if datos is None:
                continue

            actual = obtener_estado_actual(ticker, datos)
            if actual is None:
                continue

            fecha_mercado = normalizar_fecha_mercado(actual.get("fecha_datos"))
            fecha_guardada = normalizar_fecha_mercado(df.at[i, "Fecha_Mercado_Actual"])
            if not fecha_mercado:
                continue

            precio_operativo = obtener_precio_tiempo_real(ticker) or float(actual["precio"])
            entrada = float(df.at[i, "Precio_Alerta"])
            sl = float(df.at[i, "Stop_Loss"])
            tp = float(df.at[i, "Take_Profit"])

            pnl_pct = ((precio_operativo / entrada) - 1) * 100
            distancia_sl = ((precio_operativo - sl) / precio_operativo) * 100
            distancia_tp = ((tp - precio_operativo) / precio_operativo) * 100

            cambios = {
                "Precio_Actual": precio_operativo,
                "Distancia_SL_Pct": round(distancia_sl, 2),
                "Distancia_TP_Pct": round(distancia_tp, 2),
                "P&L_Actual_Pct": round(pnl_pct, 2),
                "Ultima_Actualizacion": ahora().strftime("%Y-%m-%d %H:%M")
            }

            modo = modo_actual()
            if modo == "22" or (not fecha_guardada or fecha_mercado > fecha_guardada):
                original = {
                    "empresa": df.at[i, "Empresa"], "ticker": ticker,
                    "score": float(df.at[i, "Score_Entrada"] or 0),
                    "rvol": float(df.at[i, "RVOL_Entrada"] or 0),
                    "rsi": float(df.at[i, "RSI_Entrada"] or 0),
                    "roc20": float(df.at[i, "ROC20_Entrada"] or 0),
                }
                evolucion = evaluar_evolucion_estrategia(original, actual)
                estado_tesis = estado_estrategia(original, actual)
                
                comentario = ""
                if modo == "22":
                    comentario = comentario_seguimiento(original, actual, df.loc[i], evolucion)
                    comentario = str(comentario or "").replace("\n", " ").strip()

                cambios.update({
                    "Score_Actual": actual["score"],
                    "RVOL_Actual": actual["rvol"],
                    "RSI_Actual": actual["rsi"],
                    "ROC20_Actual": actual["roc20"],
                    "ATR_Actual": actual["atr"],
                    "EMA50_Actual": actual["e50"],
                    "EMA200_Actual": actual["e200"],
                    "Razones_Actuales": actual["razones"],
                    "Soporte_Actual": actual["soporte"],
                    "Resistencia_Actual": actual["resistencia"],
                    "Estado_Estrategia": estado_tesis,
                    "Fecha_Mercado_Actual": fecha_mercado
                })
                if comentario:
                    cambios["Analisis_IA_Actual"] = comentario

            # Actualizar en Supabase
            actualizar_fila_en_supabase(ticker, fecha_creacion, cambios)
            print(f"✅ {ticker} actualizado en Supabase | P&L: {pnl_pct:+.2f}%")

        except Exception as e:
            print(f"⚠️ Error actualizando {ticker}: {e}")


# ============================================================
# AUDITORÍA SL / TP
# ============================================================

def auditar():
    df = cargar_historial()
    if df.empty:
        return

    hoy = ahora().date()
    for _, r in df.iterrows():
        if str(r.get("Estado", "")) != "ACTIVA":
            continue
        ticker = str(r.get("Ticker", "")).strip()
        fecha_creacion = str(r.get("Fecha", ""))
        if not ticker: continue

        try:
            fecha_alerta = pd.to_datetime(r["Fecha"]).date()
            inicio = fecha_alerta + timedelta(days=1)
            if inicio > hoy: continue

            datos, _ = descargar_historico_ticker(ticker, period=PERIODO_AUDITORIA)
            if datos is None: continue

            datos_auditoria = filtrar_desde_fecha(datos, inicio)
            if datos_auditoria is None or datos_auditoria.empty: continue

            sl = float(r["Stop_Loss"])
            tp = float(r["Take_Profit"])

            for fecha, vela in datos_auditoria.iterrows():
                try:
                    fecha_comparable = pd.Timestamp(fecha).date()
                except Exception:
                    continue
                if fecha_comparable < inicio: continue

                try:
                    low, high = float(vela.Low), float(vela.High)
                except Exception:
                    continue

                if pd.isna(low) or pd.isna(high): continue

                if low <= sl:
                    estado, resultado = "STOP_SALTADO", -1.0
                elif high >= tp:
                    estado, resultado = "OBJETIVO_CUMPLIDO", RR_TARGET
                else:
                    continue

                fecha_salida_str = pd.Timestamp(fecha).strftime("%Y-%m-%d")
                actualizar_fila_en_supabase(ticker, fecha_creacion, {
                    "Estado": estado,
                    "Fecha_Salida": fecha_salida_str,
                    "Resultado_R": resultado
                })
                print(f"{'🔴' if resultado < 0 else '🟢'} {ticker} -> {estado} | {fecha_salida_str}")
                break
        except Exception as e:
            print(f"⚠️ Error auditando {ticker}: {e}")


# ============================================================
# GUARDAR NUEVA ALERTA
# ============================================================

def guardar(c, comentario):
    nueva_fila = {
        "Fecha": ahora().strftime("%Y-%m-%d %H:%M"),
        "Ticker": c["ticker"],
        "Empresa": c["empresa"],
        "Sector": c["sector"],
        "Icono": c["icono"],
        "Modo": c["modo"],
        "Precio_Alerta": c["precio"],
        "Score_Entrada": c["score"],
        "RVOL_Entrada": c["rvol"],
        "RSI_Entrada": c["rsi"],
        "ROC20_Entrada": c["roc20"],
        "ATR_Entrada": c["atr"],
        "EMA50_Entrada": c["e50"],
        "EMA200_Entrada": c["e200"],
        "Razones_Entrada": c["razones"],
        "Soporte_Entrada": c["soporte"],
        "Resistencia_Entrada": c["resistencia"],
        "Analisis_IA_Entrada": comentario.replace("\n", " "),
        "Stop_Loss": c["stop"],
        "Take_Profit": c["tp"],
        "Ratio_RR": RR_TARGET,
        "Riesgo_Euros": c["riesgo"],
        "Acciones": c["acciones"],
        "Nominal": c["nominal"],
        "Precio_Actual": c["precio"],
        "Score_Actual": c["score"],
        "RVOL_Actual": c["rvol"],
        "RSI_Actual": c["rsi"],
        "ROC20_Actual": c["roc20"],
        "ATR_Actual": c["atr"],
        "EMA50_Actual": c["e50"],
        "EMA200_Actual": c["e200"],
        "Razones_Actuales": c["razones"],
        "Soporte_Actual": c["soporte"],
        "Resistencia_Actual": c["resistencia"],
        "Distancia_SL_Pct": round(((c["precio"] - c["stop"]) / c["precio"]) * 100, 2),
        "Distancia_TP_Pct": round(((c["tp"] - c["precio"]) / c["precio"]) * 100, 2),
        "P&L_Actual_Pct": 0,
        "Estado_Estrategia": "TESIS_ESTABLE",
        "Ultima_Actualizacion": ahora().strftime("%Y-%m-%d %H:%M"),
        "Fecha_Mercado_Actual": str(c.get("fecha_datos", "")),
        "Analisis_IA_Actual": comentario.replace("\n", " "),
        "Estado": "ACTIVA",
        "Fecha_Salida": "",
        "Resultado_R": None,
        "MAE_R": None,
        "MFE_R": None
    }
    guardar_en_supabase(nueva_fila)


# ============================================================
# GIT (OPCIONAL O PARA LOGS)
# ============================================================

def git():
    try:
        repo_dir = BASE_DIR
        subprocess.run(["git", "-C", repo_dir, "status", "--porcelain"], capture_output=True, text=True, check=False)
        print("ℹ️ Git: Sincronización en la nube con Supabase activa.")
    except Exception as e:
        print(f"ℹ️ Git: {e}")


# ============================================================
# MAIN
# ============================================================

def main():
    modo = modo_actual()
    print("\n============================================================")
    print("ALURA QUANT V5.0 - SUPABASE EDITION")
    print("============================================================")
    print(f"Fecha ejecución: {ahora():%Y-%m-%d %H:%M} | Modo: {modo}")
    print(f"Activos universo: {len(activos)} | IA: {IA_PROVIDER} / {modelo_ia()}")

    print("\n🔎 1. AUDITORÍA SL / TP")
    auditar()

    print("\n🧠 2. SEGUIMIENTO DE TESIS ACTIVAS")
    actualizar_alertas_activas()

    blocked = bloqueados()
    print(f"\n🔒 Tickers bloqueados: {len(blocked)}")

    activos_a_analizar = [t for t in activos if t not in blocked]
    print(f"🔍 Tickers a analizar: {len(activos_a_analizar)}")

    nuevas_alertas = []

    for inicio in range(0, len(activos_a_analizar), TAMANO_LOTE):
        lote = activos_a_analizar[inicio:inicio + TAMANO_LOTE]
        print(f"\n📥 Lote {inicio // TAMANO_LOTE + 1} | {len(lote)} activos")
        resultados_lote = descargar_lote(lote, period=PERIODO_ACTUAL)

        for ticker in lote:
            try:
                datos, estado_descarga = resultados_lote.get(ticker, (None, "SIN_RESULTADO"))
                if datos is None:
                    continue
                resultado = procesar_dataframe_activo(ticker, datos)
                if resultado:
                    nuevas_alertas.append(resultado)
            except Exception as e:
                print(f"⚠️ Error {ticker}: {e}")

    nuevas_alertas.sort(key=lambda x: (x["score"], x["rvol"]), reverse=True)
    print(f"\n📊 Nuevas señales: {len(nuevas_alertas)}")

    for c in nuevas_alertas:
        comentario = comentario_entrada(c)
        guardar(c, comentario)
        print(f"\n{c['icono']} {c['empresa']} ({c['ticker']}) | Score: {c['score']} | Entrada: {c['precio']:.2f}€")

    git()
    print("\n============================================================")
    print("✅ ALURA QUANT V5.0 FINALIZADO")
    print("============================================================")

if __name__ == "__main__":
    main()