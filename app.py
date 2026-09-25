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


def formatear_tesis_ia(texto):
    if texto is None or pd.isna(texto):
        return "Sin información disponible."
    texto = str(texto).strip()
    if not texto:
        return "Sin información disponible."
    return html.escape(texto).replace("\n", "<br>")


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

def obtener_total_activos():
    return int(len(cargar_universo_supabase()))

TOTAL_ACTIVOS_UNIVERSO = obtener_total_activos()


# ============================================================
# CARGA DE DATOS
# ============================================================

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
        stop_loss = safe_float(row.get("Stop_Loss"), precio_entrada * 0.96 if precio_entrada is not None else None)
        take_profit = safe_float(row.get("Take_Profit"), precio_entrada * 1.10 if precio_entrada is not None else None)
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
    if df.empty:
        return beneficio_realizado, fechas_curva, beneficios_curva
    df_sim = df.copy()
    if "Fecha" not in df_sim.columns:
        return beneficio_realizado, fechas_curva, beneficios_curva
    df_sim = df_sim.dropna(subset=["Fecha"]).sort_values("Fecha")
    if df_sim.empty:
        return beneficio_realizado, fechas_curva, beneficios_curva
    df_sim["Fecha_Dia"] = df_sim["Fecha"].dt.strftime("%Y-%m-%d")
    for fecha, grupo in df_sim.groupby("Fecha_Dia"):
        beneficio_dia = 0.0
        for _, row in grupo.iterrows():
            estado = str(row.get("Estado", ""))
            precio_entrada = safe_float(row.get("Precio_Alerta"), 100.0)
            stop_loss = safe_float(row.get("Stop_Loss"), precio_entrada * 0.96 if precio_entrada is not None else None)
            take_profit = safe_float(row.get("Take_Profit"), precio_entrada * 1.10 if precio_entrada is not None else None)
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
    minimum = min(values)
    maximum = max(values)
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
        pct = ((value - minimum) / rango) * 100
        return max(3, min(97, pct))

    return {
        "sl": position(stop_loss),
        "entry": position(entrada),
        "current": position(actual),
        "tp": position(take_profit),
    }


# ============================================================
# DESIGN SYSTEM (MODIFICADO PARA REDUCIR ESPACIOS EN BLANCO)
# ============================================================

st.markdown(
    """
<style>

@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap');

:root {
    --bg: #f6f8fb;
    --surface: #ffffff;
    --surface-soft: #f8fafc;
    --surface-blue: #f2f6ff;
    --border: #e7ebf2;
    --border-soft: #eef1f5;
    --text: #111827;
    --text-secondary: #64748b;
    --text-tertiary: #94a3b8;
    --blue: #2563eb;
    --blue-dark: #1d4ed8;
    --blue-soft: #eff6ff;
    --green: #16a34a;
    --green-soft: #ecfdf3;
    --red: #dc2626;
    --red-soft: #fef2f2;
    --amber: #d97706;
    --amber-soft: #fffbeb;
    --shadow: 0 1px 2px rgba(15,23,42,.02), 0 8px 30px rgba(15,23,42,.035);
    --shadow-hover: 0 12px 35px rgba(15,23,42,.07);
}

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

html {
    scroll-behavior: smooth;
}

.stApp {
    background: var(--bg);
    color: var(--text);
}

header[data-testid="stHeader"] {
    display: none !important;
}

#MainMenu, footer, section[data-testid="stSidebar"] {
    display: none !important;
}

div[data-testid="stStatusWidget"] {
    display: none !important;
}

.block-container {
    max-width: 1380px;
    padding-top: 15px; /* Reducido para disminuir espacio superior */
    padding-bottom: 30px; /* Reducido */
    padding-left: 38px;
    padding-right: 38px;
}

/* MODIFICACIÓN 1 Y 2: Reducción de espaciados en secciones y héroe */
.aq-section {
    padding: 30px 0 !important; /* Reducido de 78px a 30px para acortar espacios antes y después */
}

.hero {
    margin-bottom: 12px !important; /* Reducido */
}

.aq-hero {
    padding: 40px 0 30px !important; /* Reducido para acercar los elementos introductorios */
}

.scroll-top {
    position: fixed;
    right: 24px;
    bottom: 24px;
    width: 42px;
    height: 42px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--surface);
    color: var(--blue);
    border: 1px solid var(--border);
    border-radius: 12px;
    box-shadow: 0 8px 25px rgba(15,23,42,.12);
    text-decoration: none;
    font-family: 'Plus Jakarta Sans';
    font-size: 18px;
    font-weight: 800;
    z-index: 9999;
    transition: all .2s ease;
}

.scroll-top:hover {
    transform: translateY(-3px);
    background: var(--blue);
    color: white;
    border-color: var(--blue);
}

.hero-title {
    margin: 0;
    font-family: 'Plus Jakarta Sans';
    font-size: 32px;
    line-height: 1.1;
    letter-spacing: -.045em;
    font-weight: 800;
    color: var(--text);
}

.hero-subtitle {
    margin-top: 4px;
    color: var(--text-secondary);
    font-size: 13px;
}

.portfolio-summary {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 16px; /* Reducido */
}

.summary-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 17px 18px;
    box-shadow: var(--shadow);
    min-width: 0;
    transition: .2s ease;
}

.summary-card:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-hover);
}

.summary-label {
    color: var(--text-tertiary);
    font-size: 9px;
    text-transform: uppercase;
    letter-spacing: .07em;
    font-weight: 800;
    margin-bottom: 8px;
}

.summary-value {
    font-family: 'Plus Jakarta Sans';
    font-size: 21px;
    line-height: 1.05;
    font-weight: 800;
    letter-spacing: -.035em;
    color: var(--text);
}

.summary-detail {
    margin-top: 6px;
    color: var(--text-secondary);
    font-size: 10px;
    font-weight: 600;
}

.section-header {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    margin: 2px 0 10px; /* Reducido */
}

.section-title {
    font-family: 'Plus Jakarta Sans';
    font-size: 18px;
    font-weight: 800;
    letter-spacing: -.025em;
    color: var(--text);
}

.section-subtitle {
    font-size: 11px;
    color: var(--text-tertiary);
    margin-top: 3px;
}

.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    gap: 5px !important;
    border-bottom: 1px solid var(--border) !important;
    margin-bottom: 15px !important; /* Reducido */
}

.stTabs button[data-baseweb="tab"] {
    background: transparent !important;
    border: 0 !important;
    height: 43px !important;
    padding: 0 16px !important;
    color: var(--text-secondary) !important;
}

.stTabs button[data-baseweb="tab"] p {
    font-family: 'Plus Jakarta Sans' !important;
    font-size: 12px !important;
    font-weight: 700 !important;
}

.stTabs button[aria-selected="true"] {
    color: var(--blue) !important;
    border-bottom: 2px solid var(--blue) !important;
}

.stTabs button[aria-selected="true"] p {
    color: var(--blue) !important;
    font-weight: 800 !important;
}

.asset-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 22px;
    margin-bottom: 15px;
    box-shadow: var(--shadow);
    transition: all .22s ease;
}

.asset-card:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-hover);
    border-color: #dce3ed;
}

.asset-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 20px;
    margin-bottom: 16px;
}

.asset-left {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    min-width: 0;
    flex: 1;
}

.asset-identity {
    display: flex;
    align-items: center;
    gap: 12px;
    min-width: 0;
}

.asset-icon {
    width: 46px;
    height: 46px;
    min-width: 46px;
    border-radius: 14px;
    background: var(--blue-soft);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 20px;
}

.asset-company {
    font-family: 'Plus Jakarta Sans';
    font-size: 16px;
    font-weight: 800;
    color: var(--text);
    line-height: 1.2;
}

.asset-ticker {
    color: var(--text-tertiary);
    font-size: 11px;
    font-weight: 700;
    margin-left: 5px;
}

.asset-sector {
    color: var(--text-secondary);
    font-size: 11px;
    margin-top: 3px;
}

.asset-right {
    text-align: right;
    flex-shrink: 0;
    padding-top: 25px;
}

.new-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: var(--green-soft);
    color: #15803d;
    border: 1px solid #dcfce7;
    padding: 4px 8px;
    border-radius: 999px;
    font-size: 8px;
    font-weight: 800;
    letter-spacing: .07em;
}

.current-price {
    font-family: 'Plus Jakarta Sans';
    font-size: 22px;
    font-weight: 800;
    color: var(--text);
    letter-spacing: -.03em;
}

.price-label {
    font-size: 9px;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: .08em;
    font-weight: 800;
}

.performance-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    padding: 10px 12px;
    background: var(--surface-soft);
    border-radius: 11px;
    margin-bottom: 18px;
}

.performance-left {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    text-align: right;
    min-width: 0;
    order: 2;
}

.performance-label {
    font-size: 10px;
    color: var(--text-secondary);
    font-weight: 700;
}

.performance-value {
    font-family: 'Plus Jakarta Sans';
    font-size: 13px;
    font-weight: 800;
}

.performance-positive { color: var(--green); }
.performance-negative { color: var(--red); }
.performance-neutral { color: var(--text-secondary); }

.performance-rr {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    flex-shrink: 0;
    order: 1;
}

.performance-rr-label {
    font-size: 8px;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: .07em;
    font-weight: 800;
}

.performance-rr-value {
    margin-top: 2px;
    font-family: 'Plus Jakarta Sans';
    font-size: 13px;
    font-weight: 800;
    color: var(--blue);
}

.app-footer {
    display: flex;
    justify-content: space-between;
    gap: 15px;
    margin-top: 30px; /* Reducido */
    padding-top: 15px;
    border-top: 1px solid var(--border);
    color: var(--text-tertiary);
    font-size: 9px;
    font-weight: 600;
}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# CARGAR HISTÓRICO Y CÁLCULOS
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
total_operaciones_historicas = max(1, len(df_hist))
CAPITAL_INICIAL = max(3600.0, total_operaciones_historicas * CAPITAL_POR_ALERTA)
rentabilidad_pct = (beneficio_acumulado / CAPITAL_INICIAL * 100) if CAPITAL_INICIAL else 0

color_resultado = "#16a34a" if beneficio_acumulado >= 0 else "#dc2626"

beneficio_realizado_curva, fechas_curva, beneficios_curva = calcular_resultados(
    df_hist, beneficio_no_realizado
)

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

fecha_actualizacion_sistema = obtener_fecha_ultima_actualizacion(df_hist)


# ============================================================
# LAYOUT Y PESTAÑAS PRINCIPALES
# ============================================================

render_html(f"""
<div class="aq-wrap">
  <div class="aq-topbar">
    <div class="aq-brand">ALURA <span>QUANT</span></div>
    <div class="aq-topmeta">INVESTMENT INTELLIGENCE · ACTUALIZADO {html.escape(fecha_actualizacion_sistema)}</div>
  </div>
</div>
""")

tab_inicio, tab_oportunidades, tab_cartera, tab_resultados, tab_historial, tab_planes = st.tabs([
    "Inicio", "Oportunidades", "Cartera", "Performance", "Histórico", "Planes"
])


def render_opportunity_card(row, compact=False, ribbon=False):
    icono = safe_text(row.get("Icono"), "📈")
    empresa = safe_text(row.get("Empresa", row.get("Ticker", "Activo")), "Activo")
    ticker = safe_text(row.get("Ticker"), "")
    ticker_raw = str(row.get("Ticker", "")).strip()
    sector = safe_text(row.get("Sector"), "Mercado Continuo")

    es_nuevo = False
    if "Fecha" in row and pd.notna(row["Fecha"]):
        try:
            fecha_alerta = row["Fecha"].to_pydatetime().replace(tzinfo=None)
            es_nuevo = datetime.now() - fecha_alerta <= timedelta(hours=48)
        except Exception:
            pass

    badge_nuevo = '<span class="new-badge">✦ NUEVO</span>' if es_nuevo else ""

    precio_actual = precios_actuales.get(ticker_raw) if ticker_raw else safe_float(row.get("Precio_Actual"))
    if precio_actual is None:
        precio_actual = safe_float(row.get("Precio_Actual"))

    precio_entrada = safe_float(row.get("Precio_Alerta"))
    if precio_entrada is None:
        precio_entrada = safe_float(row.get("Precio_Actual"))

    stop_loss = safe_float(row.get("Stop_Loss"))
    take_profit = safe_float(row.get("Take_Profit"))
    ratio_rr = safe_float(row.get("Ratio_RR"))

    beneficio_posicion, porcentaje_posicion = calcular_pnl_posicion(
        precio_actual, precio_entrada, CAPITAL_POR_ALERTA
    )

    if beneficio_posicion is None or porcentaje_posicion is None:
        performance_text = "—"
        performance_class = "performance-neutral"
    else:
        performance_text = (
            f"{formatear_numero(porcentaje_posicion, 2, '%', True)}"
            f" · {formatear_numero(beneficio_posicion, 2, ' €', True)}"
        )
        performance_class = (
            "performance-positive" if beneficio_posicion >= 0
            else "performance-negative"
        )

    ratio_rr_text = formatear_numero(ratio_rr, 1, "x") if ratio_rr is not None else "—"
    
    st.markdown(f"""
    <div class="asset-card">
        <div class="asset-header">
            <div class="asset-left">
                <div class="asset-identity">
                    <div class="asset-icon">{icono}</div>
                    <div>
                        <div class="asset-company">{empresa} <span class="asset-ticker">{ticker}</span></div>
                        <div class="asset-sector">{sector}</div>
                    </div>
                </div>
            </div>
            <div class="asset-right">
                <div class="price-label">Precio Actual</div>
                <div class="current-price">{formatear_numero(precio_actual, 2, ' €')}</div>
                {badge_nuevo}
            </div>
        </div>
        <div class="performance-row">
            <div class="performance-rr">
                <span class="performance-rr-label">Ratio R:R</span>
                <span class="performance-rr-value">{ratio_rr_text}</span>
            </div>
            <div class="performance-left">
                <span class="performance-label">Rentabilidad</span>
                <span class="performance-value {performance_class}">{performance_text}</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
