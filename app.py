import os
import re
import html
import math
from datetime import datetime, timedelta
import gspread
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
from google.oauth2.service_account import Credentials
from supabase import create_client


# ============================================================
# ALURA QUANT — INVESTMENT INTELLIGENCE UI
# ============================================================
st.set_page_config(
    page_title="Alura Quant",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# SUSCRIPCIONES — SUPABASE
# ============================================================

TABLA_FREE = "suscriptores_free"
TABLA_VIP = "suscriptores_vip"

def normalizar_email(email):
    return str(email or "").strip().lower()

def email_valido(email):
    email = normalizar_email(email)
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email))

def guardar_suscriptor_supabase(email, tipo="free"):
    email = normalizar_email(email)
    tabla = TABLA_VIP if tipo == "vip" else TABLA_FREE
    if not email_valido(email):
        return "invalid"
    try:
        existente = supabase.table(tabla).select("id,email").eq("email", email).limit(1).execute()
        if getattr(existente, "data", None):
            return "exists"
        supabase.table(tabla).insert({"email": email}).execute()
        return "success"
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            return "exists"
        print(f"Error guardando suscriptor {tipo}: {e}")
        return "error"

def comprobar_suscripcion(email):
    email = normalizar_email(email)
    if not email_valido(email):
        return "none"
    try:
        free = supabase.table(TABLA_FREE).select("id").eq("email", email).limit(1).execute()
        vip = supabase.table(TABLA_VIP).select("id").eq("email", email).limit(1).execute()
        has_free = bool(getattr(free, "data", None))
        has_vip = bool(getattr(vip, "data", None))
        if has_vip and has_free: return "both"
        if has_vip: return "vip"
        if has_free: return "free"
    except Exception as e:
        print(f"Error comprobando suscripción: {e}")
    return "none"

# ============================================================
# CONFIGURACIÓN SUPABASE
# ============================================================

CAPITAL_POR_ALERTA = 300.0  # Fallback únicamente para registros históricos sin Acciones/Nominal.
CAPITAL_REFERENCIA = 10000.0

MAPEO_COLUMNAS_SUPABASE = {
    "Fecha": "fecha", "Ticker": "ticker", "Empresa": "empresa", "Sector": "sector", "Icono": "icono", "Modo": "modo",
    "Precio_Alerta": "precio_alerta", "Score_Entrada": "score_entrada", "RVOL_Entrada": "rvol_entrada",
    "RSI_Entrada": "rsi_entrada", "ROC20_Entrada": "roc20_entrada", "ATR_Entrada": "atr_entrada",
    "EMA50_Entrada": "ema50_entrada", "EMA200_Entrada": "ema200_entrada", "Razones_Entrada": "razones_entrada",
    "Soporte_Entrada": "soporte_entrada", "Resistencia_Entrada": "resistencia_entrada", "Analisis_IA_Entrada": "analisis_ia_entrada",
    "Stop_Loss": "stop_loss", "Stop_Loss_Inicial": "stop_loss_inicial", "Fecha_Activacion_Breakeven": "fecha_activacion_breakeven",
    "Take_Profit": "take_profit", "Ratio_RR": "ratio_rr", "Riesgo_Euros": "riesgo_euros",
    "Acciones": "acciones", "Nominal": "nominal", "Precio_Actual": "precio_actual", "Score_Actual": "score_actual",
    "RVOL_Actual": "rvol_actual", "RSI_Actual": "rsi_actual", "ROC20_Actual": "roc20_actual", "ATR_Actual": "atr_actual",
    "EMA50_Actual": "ema50_actual", "EMA200_Actual": "ema200_actual", "Razones_Actuales": "razones_actuales",
    "Soporte_Actual": "soporte_actual", "Resistencia_Actual": "resistencia_actual", "Distancia_SL_Pct": "distancia_sl_pct",
    "Distancia_TP_Pct": "distancia_tp_pct", "P&L_Actual_Pct": "pnl_actual_pct", "Estado_Estrategia": "estado_estrategia",
    "Ultima_Actualizacion": "ultima_actualizacion", "Fecha_Mercado_Actual": "fecha_mercado_actual",
    "Analisis_IA_Actual": "analisis_ia_actual", "Estado": "estado", "Fecha_Salida": "fecha_salida",
    "Resultado_R": "resultado_r", "MAE_R": "mae_r", "MFE_R": "mfe_r"
}
CAMPOS_HISTORIAL = list(MAPEO_COLUMNAS_SUPABASE.keys())

def conectar_supabase():
    url = key = ""
    try:
        if "supabase" in st.secrets:
            bloque = st.secrets["supabase"]
            url = str(bloque.get("url", "")).strip()
            key = str(bloque.get("key", "")).strip()
    except Exception:
        pass
    if not url or not key:
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_KEY", "").strip()
    if not url or not key:
        st.error("Supabase no está configurado. Comprueba Streamlit Secrets: [supabase] con url y key.")
        st.stop()
    try:
        return create_client(url, key)
    except Exception as e:
        st.error(f"No se pudo inicializar Supabase: {e}")
        st.stop()

supabase = conectar_supabase()


# ============================================================
# UTILIDADES
# ============================================================

def render_html(content, **kwargs):
    if hasattr(st, "html"):
        st.html(content)
    else:
        st.markdown(content, unsafe_allow_html=True)

def safe_text(value, default="—"):
    if value is None or pd.isna(value):
        return default
    value = str(value).strip()
    if not value:
        return default
    return html.escape(value)

def safe_float(value, default=None):
    try:
        if value is None or pd.isna(value):
            return default
        numero = float(value)
        return numero if math.isfinite(numero) else default
    except (TypeError, ValueError, OverflowError):
        return default

def preparar_fecha(df):
    if df is None:
        return pd.DataFrame()
    df = df.copy()
    for col in ("Fecha", "Ultima_Actualizacion", "Fecha_Mercado_Actual", "Ultima_Ejecucion"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df

def formatear_numero(valor, decimales=2, sufijo="", signo=False):
    if valor is None or pd.isna(valor):
        return "—"
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return "—"
    prefijo = "+" if signo and valor > 0 else ("−" if signo and valor < 0 else "")
    num_str = f"{abs(valor):,.{decimales}f}"
    num_str = num_str.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{prefijo}{num_str}{sufijo}"

def calcular_pnl_posicion(precio_actual, precio_entrada, capital=300.0):
    if precio_actual is None or precio_entrada is None or precio_entrada <= 0:
        return None, None
    porcentaje = (float(precio_actual) - float(precio_entrada)) / float(precio_entrada) * 100
    beneficio = float(capital) * porcentaje / 100
    return beneficio, porcentaje

def calcular_metricas(df):
    if df is None or df.empty:
        return {"total_alertas": 0, "exitos": 0, "fallos": 0, "break_even": 0, "activas": 0, "win_rate": 0.0}
    estados = df["Estado"].astype(str) if "Estado" in df.columns else pd.Series("", index=df.index)
    activos = estados.str.contains("ACTIVA", na=False, regex=False)
    exitos = estados.str.contains("OBJETIVO_CUMPLIDO", na=False, regex=False)
    stops = estados.str.contains("STOP_SALTADO", na=False, regex=False)
    resultado_r = pd.to_numeric(df.get("Resultado_R", pd.Series(index=df.index, dtype=float)), errors="coerce")
    fecha_be = pd.to_datetime(df.get("Fecha_Activacion_Breakeven", pd.Series(index=df.index, dtype=object)), errors="coerce")
    break_even = stops & (resultado_r.eq(0) | fecha_be.notna())
    fallos = stops & ~break_even
    operaciones_decisivas = int(exitos.sum() + fallos.sum())
    win_rate = float(exitos.sum() / operaciones_decisivas * 100) if operaciones_decisivas else 0.0
    return {
        "total_alertas": int(len(df)),
        "exitos": int(exitos.sum()),
        "fallos": int(fallos.sum()),
        "break_even": int(break_even.sum()),
        "activas": int(activos.sum()),
        "win_rate": win_rate,
    }

def formatear_tesis_ia(texto):
    if texto is None or pd.isna(texto):
        return "Sin información disponible."
    texto = str(texto).strip()
    if not texto:
        return "Sin información disponible."
    return html.escape(texto).replace("\n", "<br>")

@st.cache_data(ttl=600)
def cargar_universo_supabase():
    try:
        response = supabase.table("universo_activos").select("ticker, empresa, sector, icono, activo").eq("activo", True).execute()
        df = pd.DataFrame(response.data or [])
        if df.empty:
            return pd.DataFrame(columns=["Ticker", "Empresa", "Sector", "Icono", "Activo"])
        return df.rename(columns={"ticker":"Ticker", "empresa":"Empresa", "sector":"Sector", "icono":"Icono", "activo":"Activo"})
    except Exception as e:
        st.error(f"Error cargando universo desde Supabase: {e}")
        return pd.DataFrame(columns=["Ticker", "Empresa", "Sector", "Icono", "Activo"])

def obtener_total_activos():
    return int(len(cargar_universo_supabase()))

TOTAL_ACTIVOS_UNIVERSO = obtener_total_activos()


# ============================================================
# CARGA DE DATOS
# ============================================================

@st.cache_data(ttl=600)
def cargar_datos():
    try:
        registros = []
        inicio = 0
        tamano = 1000
        while True:
            response = supabase.table("historial_alertas").select("*").range(inicio, inicio + tamano - 1).execute()
            lote = response.data or []
            registros.extend(lote)
            if len(lote) < tamano:
                break
            inicio += tamano
        if not registros:
            return pd.DataFrame(columns=CAMPOS_HISTORIAL)
        df = pd.DataFrame(registros)
        df = df.rename(columns={v:k for k,v in MAPEO_COLUMNAS_SUPABASE.items()})
        for col in CAMPOS_HISTORIAL:
            if col not in df.columns:
                df[col] = None
        return df
    except Exception as e:
        st.error(f"Error cargando historial desde Supabase: {e}")
        return pd.DataFrame(columns=CAMPOS_HISTORIAL)

@st.cache_data(ttl=300)
def obtener_precio_actual(ticker):
    if not ticker:
        return None
    try:
        data = yf.Ticker(str(ticker)).history(period="1d", auto_adjust=False)
        if not data.empty:
            close = data["Close"].iloc[-1]
            if pd.notna(close):
                return float(close)
    except Exception:
        pass
    return None

def obtener_precios_activos(df):
    precios = {}
    if df.empty or "Ticker" not in df.columns:
        return precios
    for _, row in df.iterrows():
        ticker = str(row.get("Ticker", "")).strip()
        if not ticker:
            continue
        precio_persistido = safe_float(row.get("Precio_Actual"))
        if precio_persistido is not None:
            precios[ticker] = precio_persistido
            continue
        precio = obtener_precio_actual(ticker)
        if precio is not None:
            precios[ticker] = precio
    return precios

def calcular_beneficio_fila_cerrada(row):
    entrada = safe_float(row.get("Precio_Alerta"))
    if entrada is None or entrada <= 0:
        return 0.0
    resultado_r = safe_float(row.get("Resultado_R"))
    stop_inicial = safe_float(row.get("Stop_Loss_Inicial"), safe_float(row.get("Stop_Loss")))
    riesgo_euros = safe_float(row.get("Riesgo_Euros"))
    if resultado_r is not None and riesgo_euros is not None:
        return riesgo_euros * resultado_r
    if resultado_r is not None and stop_inicial is not None:
        riesgo_pct = abs(entrada - stop_inicial) / entrada
        nominal = safe_float(row.get("Nominal"))
        capital_base = nominal if nominal is not None and nominal > 0 else CAPITAL_POR_ALERTA
        return capital_base * riesgo_pct * resultado_r
    estado = str(row.get("Estado", ""))
    if "OBJETIVO_CUMPLIDO" in estado:
        objetivo = safe_float(row.get("Take_Profit"), entrada * 1.10)
        return CAPITAL_POR_ALERTA * (objetivo - entrada) / entrada if objetivo is not None else 0.0
    if "STOP_SALTADO" in estado:
        fecha_be = row.get("Fecha_Activacion_Breakeven")
        if fecha_be is not None and not pd.isna(fecha_be) and str(fecha_be).strip():
            return 0.0
        stop = safe_float(row.get("Stop_Loss_Inicial"), safe_float(row.get("Stop_Loss"), entrada * 0.96))
        return -CAPITAL_POR_ALERTA * (entrada - stop) / entrada if stop is not None else 0.0
    return 0.0

def calcular_beneficio_realizado(df):
    if df is None or df.empty:
        return 0.0
    return float(sum(calcular_beneficio_fila_cerrada(row) for _, row in df.iterrows()))

def calcular_beneficio_no_realizado(df_activas, precios_actuales):
    beneficio_total = 0.0
    posiciones_ganadoras = 0
    posiciones_perdedoras = 0
    if df_activas.empty:
        return 0.0, 0, 0
    for _, row in df_activas.iterrows():
        ticker = str(row.get("Ticker", "")).strip()
        if not ticker:
            continue
        precio_actual = precios_actuales.get(ticker)
        precio_entrada = safe_float(row.get("Precio_Alerta"))
        precio_actual = safe_float(precio_actual)
        acciones = safe_float(row.get("Acciones"))
        nominal = safe_float(row.get("Nominal"))
        if precio_actual is not None and precio_entrada is not None and precio_entrada > 0 and acciones is not None and acciones > 0:
            beneficio = (precio_actual - precio_entrada) * acciones
            porcentaje = (precio_actual - precio_entrada) / precio_entrada * 100
        else:
            beneficio, porcentaje = calcular_pnl_posicion(
                precio_actual,
                precio_entrada,
                nominal if nominal is not None and nominal > 0 else CAPITAL_POR_ALERTA
            )
        if beneficio is None:
            continue
        beneficio_total += beneficio
        if beneficio > 0:
            posiciones_ganadoras += 1
        elif beneficio < 0:
            posiciones_perdedoras += 1
    return beneficio_total, posiciones_ganadoras, posiciones_perdedoras


# ============================================================
# CARGAR HISTÓRICO Y MÉTRICAS FINALES
# ============================================================

df_hist = preparar_fecha(cargar_datos())
metricas = calcular_metricas(df_hist)

total_alertas = metricas["total_alertas"]
exitos = metricas["exitos"]
fallos = metricas["fallos"]
activas = metricas["activas"]
win_rate = metricas["win_rate"]

if not df_hist.empty and "Estado" in df_hist.columns:
    df_activas_global = df_hist[df_hist["Estado"].astype(str).str.contains("ACTIVA", na=False, regex=False)].copy()
else:
    df_activas_global = pd.DataFrame()

precios_actuales = obtener_precios_activos(df_activas_global)

beneficio_realizado = calcular_beneficio_realizado(df_hist)
beneficio_no_realizado, posiciones_con_beneficio, posiciones_con_perdida = calcular_beneficio_no_realizado(df_activas_global, precios_actuales)

beneficio_acumulado = beneficio_realizado + beneficio_no_realizado
CAPITAL_INICIAL = CAPITAL_REFERENCIA

rentabilidad_pct = (beneficio_acumulado / CAPITAL_INICIAL) * 100 if CAPITAL_INICIAL > 0 else 0.0

st.success(f"Aplicación cargada correctamente. Rentabilidad actual estimada: {rentabilidad_pct:.2f}%")
