import os
import re
import html
from datetime import datetime, timedelta
import gspread
import pandas as pd
import streamlit as st
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

CAPITAL_POR_ALERTA = 300.0

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
# UTILIDADES Y FUNCIONES AUXILIARES
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
    return html.escape(value) if value else default

def safe_float(value, default=None):
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
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
        return {"total_alertas": 0, "exitos": 0, "fallos": 0, "activas": 0, "win_rate": 0.0}
    estados = df["Estado"].astype(str) if "Estado" in df.columns else pd.Series("", index=df.index)
    activos = estados.str.contains("ACTIVA", na=False, regex=False)
    exitos = estados.str.contains("OBJETIVO_CUMPLIDO", na=False, regex=False)
    fallos = estados.str.contains("STOP_SALTADO", na=False, regex=False)
    cerradas = int(exitos.sum() + fallos.sum())
    win_rate = float(exitos.sum() / cerradas * 100) if cerradas else 0.0
    return {
        "total_alertas": int(len(df)),
        "exitos": int(exitos.sum()),
        "fallos": int(fallos.sum()),
        "activas": int(activos.sum()),
        "win_rate": win_rate,
    }

@st.cache_data(ttl=60)
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

@st.cache_data(ttl=30)
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

def calcular_beneficio_realizado(df):
    beneficio = 0.0
    if df.empty:
        return beneficio
    for _, row in df.iterrows():
        estado = str(row.get("Estado", ""))
        precio_entrada = safe_float(row.get("Precio_Alerta"), 100.0)
        stop_loss = safe_float(row.get("Stop_Loss"), precio_entrada * 0.96 if precio_entrada else None)
        take_profit = safe_float(row.get("Take_Profit"), precio_entrada * 1.10 if precio_entrada else None)
        if precio_entrada is None or precio_entrada <= 0:
            continue
        pct_ganancia = (take_profit - precio_entrada) / precio_entrada
        pct_perdida = (precio_entrada - stop_loss) / precio_entrada
        if "OBJETIVO_CUMPLIDO" in estado:
            beneficio += (CAPITAL_POR_ALERTA * pct_ganancia)
        elif "STOP_SALTADO" in estado:
            beneficio -= (CAPITAL_POR_ALERTA * pct_perdida)
    return beneficio

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
        beneficio, porcentaje = calcular_pnl_posicion(precio_actual, precio_entrada, CAPITAL_POR_ALERTA)
        if beneficio is None:
            continue
        beneficio_total += beneficio
        if beneficio > 0:
            posiciones_ganadoras += 1
        elif beneficio < 0:
            posiciones_perdedoras += 1
    return beneficio_total, posiciones_ganadoras, posiciones_perdedoras

def calcular_resultados(df, beneficio_no_realizado=0.0):
    beneficio_realizado = 0.0
    fechas_curva = []
    beneficios_curva = []
    if df.empty or "Fecha" not in df.columns:
        return beneficio_realizado, fechas_curva, beneficios_curva
    df_sim = df.dropna(subset=["Fecha"]).sort_values("Fecha")
    if df_sim.empty:
        return beneficio_realizado, fechas_curva, beneficios_curva
    df_sim["Fecha_Dia"] = df_sim["Fecha"].dt.strftime("%Y-%m-%d")
    for fecha, grupo in df_sim.groupby("Fecha_Dia"):
        beneficio_dia = 0.0
        for _, row in grupo.iterrows():
            estado = str(row.get("Estado", ""))
            precio_entrada = safe_float(row.get("Precio_Alerta"), 100.0)
            stop_loss = safe_float(row.get("Stop_Loss"), precio_entrada * 0.96 if precio_entrada else None)
            take_profit = safe_float(row.get("Take_Profit"), precio_entrada * 1.10 if precio_entrada else None)
            if precio_entrada is None or precio_entrada <= 0:
                continue
            pct_ganancia = (take_profit - precio_entrada) / precio_entrada
            pct_perdida = (precio_entrada - stop_loss) / precio_entrada
            if "OBJETIVO_CUMPLIDO" in estado:
                beneficio_dia += (CAPITAL_POR_ALERTA * pct_ganancia)
            elif "STOP_SALTADO" in estado:
                beneficio_dia -= (CAPITAL_POR_ALERTA * pct_perdida)
        beneficio_realizado += beneficio_dia
        fechas_curva.append(fecha)
        beneficios_curva.append(beneficio_realizado)

    beneficio_total_actual = beneficio_realizado + beneficio_no_realizado
    if beneficio_no_realizado != 0 or not fechas_curva:
        fecha_actual = datetime.now().strftime("%Y-%m-%d")
        if fechas_curva and fechas_curva[-1] == fecha_actual:
            beneficios_curva[-1] = beneficio_total_actual
        else:
            fechas_curva.append(fecha_actual)
            beneficios_curva.append(beneficio_total_actual)
    return beneficio_realizado, fechas_curva, beneficios_curva

def calcular_position_percentages(stop_loss, entrada, actual, take_profit):
    values = [v for v in [stop_loss, entrada, actual, take_profit] if v is not None]
    if len(values) < 2:
        return None
    minimum, maximum = min(values), max(values)
    rango = maximum - minimum
    if rango <= 0:
        return None
    margen = rango * 0.08
    minimum -= margen
    maximum += margen
    rango = maximum - minimum
    def position(value):
        if value is None:
            return None
        pct = (value - minimum) / rango * 100
        return max(3, min(97, pct))
    return {
        "sl": position(stop_loss),
        "entry": position(entrada),
        "current": position(actual),
        "tp": position(take_profit),
    }

def obtener_fecha_ultima_actualizacion(df):
    try:
        candidatos = []
        for col in ("Ultima_Actualizacion", "Fecha", "Fecha_Mercado_Actual"):
            if col in df.columns:
                serie = pd.to_datetime(df[col], errors="coerce").dropna()
                if not serie.empty:
                    candidatos.append(serie.max())
        if candidatos:
            return max(candidatos).strftime("%d/%m/%Y %H:%M")
    except Exception:
        pass
    return datetime.now().strftime("%d/%m/%Y %H:%M")


# ============================================================
# CARGA ÚNICA DE DATOS Y CÁLCULOS GLOBALES
# ============================================================

df_hist = preparar_fecha(cargar_datos())
metricas = calcular_metricas(df_hist)
total_alertas = metricas["total_alertas"]
exitos = metricas["exitos"]
fallos = metricas["fallos"]
activas = metricas["activas"]
win_rate = metricas["win_rate"]

if not df_hist.empty and "Estado" in df_hist.columns:
    df_activas_global = df_hist[
        df_hist["Estado"].astype(str).str.contains("ACTIVA", na=False, regex=False)
    ].copy()
else:
    df_activas_global = pd.DataFrame()

precios_actuales = obtener_precios_activos(df_activas_global)
beneficio_realizado = calcular_beneficio_realizado(df_hist)
beneficio_no_realizado, posiciones_con_beneficio, posiciones_con_perdida = calcular_beneficio_no_realizado(
    df_activas_global, precios_actuales
)
beneficio_acumulado = beneficio_realizado + beneficio_no_realizado
capital_inicial = max(3600.0, max(1, len(df_hist)) * CAPITAL_POR_ALERTA)
rentabilidad_pct = (beneficio_acumulado / capital_inicial * 100) if capital_inicial else 0
beneficio_realizado_curva, fechas_curva, beneficios_curva = calcular_resultados(
    df_hist, beneficio_no_realizado
)
fecha_actualizacion_sistema = obtener_fecha_ultima_actualizacion(df_hist)
