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
    """
    Renderiza HTML directamente cuando la versión de Streamlit
    lo permite y utiliza markdown como fallback.
    """
    if hasattr(st, "html"):
        st.html(content)
    else:
        st.markdown(content, unsafe_allow_html=True)


def safe_text(value, default="—"):
    """
    Escapa texto para evitar problemas cuando los datos vienen
    directamente desde CSV.
    """
    if value is None or pd.isna(value):
        return default

    value = str(value).strip()

    if not value:
        return default

    return html.escape(value)


def safe_float(value, default=None):
    """
    Conversión segura a float.
    """
    try:

        if value is None or pd.isna(value):
            return default

        return float(value)

    except Exception:

        return default


def preparar_fecha(df):
    """Normaliza las columnas de fecha del historial."""
    if df is None:
        return pd.DataFrame()
    df = df.copy()
    for col in ("Fecha", "Ultima_Actualizacion", "Fecha_Mercado_Actual", "Ultima_Ejecucion"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def formatear_numero(valor, decimales=2, sufijo="", signo=False):
    """Formatea un número con separador de miles (.) y decimal (,) para España."""
    if valor is None or pd.isna(valor):
        return "—"
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return "—"
    
    prefijo = "+" if signo and valor > 0 else ("−" if signo and valor < 0 else "")
    
    # Formateo estándar en formato inglés para extraer partes
    num_str = f"{abs(valor):,.{decimales}f}"
    
    # Reemplazos para notación española: comas de miles por puntos, punto decimal por coma
    num_str = num_str.replace(",", "X").replace(".", ",").replace("X", ".")
    
    return f"{prefijo}{num_str}{sufijo}"


def calcular_pnl_posicion(precio_actual, precio_entrada, capital=300.0):
    """Devuelve P&L monetario y porcentual de una posición."""
    if precio_actual is None or precio_entrada is None or precio_entrada <= 0:
        return None, None
    porcentaje = (float(precio_actual) - float(precio_entrada)) / float(precio_entrada) * 100
    beneficio = float(capital) * porcentaje / 100
    return beneficio, porcentaje


def calcular_metricas(df):
    """Calcula métricas globales del historial."""
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
    """Limpia y escapa el comentario de IA para HTML."""
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

        data = yf.Ticker(
            str(ticker)
        ).history(
            period="1d",
            auto_adjust=False
        )

        if not data.empty:

            close = data["Close"].iloc[-1]

            if pd.notna(close):
                return float(close)

    except Exception:
        pass

    return None


# ============================================================
# PRECIOS ACTUALES DE POSICIONES
# ============================================================

def obtener_precios_activos(df):
    """
    Usa primero Precio_Actual persistido por bot.py.
    Solo consulta Yahoo como fallback cuando Supabase no tiene precio.
    Así la web no inventa una actualización durante fines de semana/festivos.
    """
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


# ============================================================
# BENEFICIO REALIZADO
# ============================================================

def calcular_beneficio_realizado(df):

    """
    Calcula únicamente operaciones cerradas utilizando 300€ por posición.
    """

    beneficio = 0.0

    if df.empty:
        return beneficio

    for _, row in df.iterrows():

        estado = str(
            row.get(
                "Estado",
                ""
            )
        )

        precio_entrada = safe_float(
            row.get(
                "Precio_Alerta"
            ),
            100.0
        )

        stop_loss = safe_float(
            row.get(
                "Stop_Loss"
            ),
            precio_entrada * 0.96
            if precio_entrada is not None
            else None
        )

        take_profit = safe_float(
            row.get(
                "Take_Profit"
            ),
            precio_entrada * 1.10
            if precio_entrada is not None
            else None
        )

        if (
            precio_entrada is None
            or precio_entrada <= 0
        ):
            continue

        pct_ganancia = (
            take_profit -
            precio_entrada
        ) / precio_entrada

        pct_perdida = (
            precio_entrada -
            stop_loss
        ) / precio_entrada

        if "OBJETIVO_CUMPLIDO" in estado:

            beneficio += (
                CAPITAL_POR_ALERTA *
                pct_ganancia
            )

        elif "STOP_SALTADO" in estado:

            beneficio -= (
                CAPITAL_POR_ALERTA *
                pct_perdida
            )

    return beneficio


# ============================================================
# BENEFICIO NO REALIZADO
# ============================================================

def calcular_beneficio_no_realizado(
    df_activas,
    precios_actuales
):

    """
    Calcula el beneficio/pérdida actual de todas las posiciones
    abiertas basándose en 300€ por posición.
    """

    beneficio_total = 0.0
    posiciones_ganadoras = 0
    posiciones_perdedoras = 0

    if df_activas.empty:
        return (
            0.0,
            0,
            0
        )

    for _, row in df_activas.iterrows():

        ticker = str(
            row.get(
                "Ticker",
                ""
            )
        ).strip()

        if not ticker:
            continue

        precio_actual = precios_actuales.get(
            ticker
        )

        precio_entrada = safe_float(
            row.get(
                "Precio_Alerta"
            )
        )

        beneficio, porcentaje = (
            calcular_pnl_posicion(
                precio_actual,
                precio_entrada,
                CAPITAL_POR_ALERTA
            )
        )

        if beneficio is None:
            continue

        beneficio_total += beneficio

        if beneficio > 0:
            posiciones_ganadoras += 1

        elif beneficio < 0:
            posiciones_perdedoras += 1

    return (
        beneficio_total,
        posiciones_ganadoras,
        posiciones_perdedoras
    )


# ============================================================
# RESULTADOS HISTÓRICOS
# ============================================================

def calcular_resultados(
    df,
    beneficio_no_realizado=0.0
):

    """
    Calcula la curva de beneficio histórico escalada a 300€ por posición.
    """

    beneficio_realizado = 0.0

    fechas_curva = []
    beneficios_curva = []

    if df.empty:

        return (
            beneficio_realizado,
            fechas_curva,
            beneficios_curva
        )

    df_sim = df.copy()

    if "Fecha" not in df_sim.columns:

        return (
            beneficio_realizado,
            fechas_curva,
            beneficios_curva
        )

    df_sim = (
        df_sim
        .dropna(subset=["Fecha"])
        .sort_values("Fecha")
    )

    if df_sim.empty:

        return (
            beneficio_realizado,
            fechas_curva,
            beneficios_curva
        )

    df_sim["Fecha_Dia"] = (
        df_sim["Fecha"]
        .dt.strftime("%Y-%m-%d")
    )

    for fecha, grupo in df_sim.groupby(
        "Fecha_Dia"
    ):

        beneficio_dia = 0.0

        for _, row in grupo.iterrows():

            estado = str(
                row.get(
                    "Estado",
                    ""
                )
            )

            precio_entrada = safe_float(
                row.get(
                    "Precio_Alerta"
                ),
                100.0
            )

            stop_loss = safe_float(
                row.get(
                    "Stop_Loss"
                ),
                precio_entrada * 0.96
                if precio_entrada is not None
                else None
            )

            take_profit = safe_float(
                row.get(
                    "Take_Profit"
                ),
                precio_entrada * 1.10
                if precio_entrada is not None
                else None
            )

            if (
                precio_entrada is None
                or precio_entrada <= 0
            ):
                continue

            pct_ganancia = (
                take_profit -
                precio_entrada
            ) / precio_entrada

            pct_perdida = (
                precio_entrada -
                stop_loss
            ) / precio_entrada

            if "OBJETIVO_CUMPLIDO" in estado:

                beneficio_dia += (
                    CAPITAL_POR_ALERTA *
                    pct_ganancia
                )

            elif "STOP_SALTADO" in estado:

                beneficio_dia -= (
                    CAPITAL_POR_ALERTA *
                    pct_perdida
                )

        beneficio_realizado += (
            beneficio_dia
        )

        fechas_curva.append(
            fecha
        )

        beneficios_curva.append(
            beneficio_realizado
        )

    # --------------------------------------------------------
    # P&L ACTUAL DE POSICIONES ABIERTAS
    # --------------------------------------------------------

    beneficio_total_actual = (
        beneficio_realizado +
        beneficio_no_realizado
    )

    if (
        beneficio_no_realizado != 0
        or not fechas_curva
    ):

        fecha_actual = (
            datetime.now()
            .strftime("%Y-%m-%d")
        )

        if (
            fechas_curva
            and fechas_curva[-1] == fecha_actual
        ):

            beneficios_curva[-1] = (
                beneficio_total_actual
            )

        else:

            fechas_curva.append(
                fecha_actual
            )

            beneficios_curva.append(
                beneficio_total_actual
            )

    return (
        beneficio_realizado,
        fechas_curva,
        beneficios_curva
    )


# ============================================================
# POSITION METRICS
# ============================================================

def calcular_position_percentages(
    stop_loss,
    entrada,
    actual,
    take_profit
):

    """
    Calcula la posición relativa de SL /
    Entrada / Actual / TP dentro de una
    escala visual.
    """

    values = [
        v
        for v in [
            stop_loss,
            entrada,
            actual,
            take_profit
        ]
        if v is not None
    ]

    if len(values) < 2:
        return None

    minimum = min(values)
    maximum = max(values)

    rango = (
        maximum -
        minimum
    )

    if rango <= 0:
        return None

    margen = rango * 0.08

    minimum -= margen
    maximum += margen

    rango = (
        maximum -
        minimum
    )

    def position(value):

        if value is None:
            return None

        pct = (
            (
                value -
                minimum
            )
            /
            rango
            * 100
        )

        return max(
            3,
            min(
                97,
                pct
            )
        )

    return {
        "sl": position(stop_loss),
        "entry": position(entrada),
        "current": position(actual),
        "tp": position(take_profit),
    }


# ============================================================
# DESIGN SYSTEM
# ============================================================

st.markdown(
    """
<style>

@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap');


/* =========================================================
   ROOT
   ========================================================= */

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

    --shadow:
        0 1px 2px rgba(15,23,42,.02),
        0 8px 30px rgba(15,23,42,.035);

    --shadow-hover:
        0 12px 35px rgba(15,23,42,.07);

}


/* =========================================================
   GLOBAL
   ========================================================= */

html,
body,
[class*="css"] {

    font-family:
        'DM Sans',
        sans-serif;

}

html {
    scroll-behavior: smooth;
}

.stApp {

    background:
        var(--bg);

    color:
        var(--text);

}

/* Ocultar barra superior y menú desplegable de Streamlit */
header[data-testid="stHeader"] {
    display: none !important;
}

#MainMenu,
footer,
section[data-testid="stSidebar"] {

    display:
        none !important;

}

/* Ocultar widget inferior derecho (GitHub / Streamlit branding) */
div[data-testid="stStatusWidget"] {
    display: none !important;
}

.block-container {

    max-width:
        1380px;

    padding-top:
        30px;

    padding-bottom:
        60px;

    padding-left:
        38px;

    padding-right:
        38px;

}


/* =========================================================
   SCROLL TO TOP
   ========================================================= */

.scroll-top {

    position:
        fixed;

    right:
        24px;

    bottom:
        24px;

    width:
        42px;

    height:
        42px;

    display:
        flex;

    align-items:
        center;

    justify-content:
        center;

    background:
        var(--surface);

    color:
        var(--blue);

    border:
        1px solid var(--border);

    border-radius:
        12px;

    box-shadow:
        0 8px 25px rgba(15,23,42,.12);

    text-decoration:
        none;

    font-family:
        'Plus Jakarta Sans';

    font-size:
        18px;

    font-weight:
        800;

    z-index:
        9999;

    transition:
        all .2s ease;

}

.scroll-top:hover {

    transform:
        translateY(-3px);

    background:
        var(--blue);

    color:
        white;

    border-color:
        var(--blue);

}


/* =========================================================
   HERO
   ========================================================= */

.hero {

    margin-bottom:
        10px;

}

.hero-title {

    margin:
        0;

    font-family:
        'Plus Jakarta Sans';

    font-size:
        32px;

    line-height:
        1.1;

    letter-spacing:
        -.045em;

    font-weight:
        800;

    color:
        var(--text);

}

.hero-subtitle {

    margin-top:
        8px;

    color:
        var(--text-secondary);

    font-size:
        13px;

}


/* =========================================================
   PORTFOLIO SUMMARY
   ========================================================= */

.portfolio-summary {

    display:
        grid;

    grid-template-columns:
        repeat(4, 1fr);

    gap:
        12px;

    margin-bottom:
        32px;

}

.summary-card {

    background:
        var(--surface);

    border:
        1px solid var(--border);

    border-radius:
        16px;

    padding:
        17px 18px;

    box-shadow:
        var(--shadow);

    min-width:
        0;

    transition:
        .2s ease;

}

.summary-card:hover {

    transform:
        translateY(-2px);

    box-shadow:
        var(--shadow-hover);

}

.summary-label {

    color:
        var(--text-tertiary);

    font-size:
        9px;

    text-transform:
        uppercase;

    letter-spacing:
        .07em;

    font-weight:
        800;

    margin-bottom:
        8px;

}

.summary-value {

    font-family:
        'Plus Jakarta Sans';

    font-size:
        21px;

    line-height:
        1.05;

    font-weight:
        800;

    letter-spacing:
        -.035em;

    color:
        var(--text);

}

.summary-detail {

    margin-top:
        6px;

    color:
        var(--text-secondary);

    font-size:
        10px;

    font-weight:
        600;

}


/* =========================================================
   SECTION HEADER
   ========================================================= */

.section-header {

    display:
        flex;

    align-items:
        flex-end;

    justify-content:
        space-between;

    margin:
        4px 0 16px;

}

.section-title {

    font-family:
        'Plus Jakarta Sans';

    font-size:
        18px;

    font-weight:
        800;

    letter-spacing:
        -.025em;

    color:
        var(--text);

}

.section-subtitle {

    font-size:
        11px;

    color:
        var(--text-tertiary);

    margin-top:
        3px;

}


/* =========================================================
   TABS
   ========================================================= */

.stTabs [data-baseweb="tab-list"] {

    background:
        transparent !important;

    gap:
        5px !important;

    border-bottom:
        1px solid var(--border) !important;

    margin-bottom:
        27px !important;

}

.stTabs button[data-baseweb="tab"] {

    background:
        transparent !important;

    border:
        0 !important;

    height:
        43px !important;

    padding:
        0 16px !important;

    color:
        var(--text-secondary) !important;

}

.stTabs button[data-baseweb="tab"] p {

    font-family:
        'Plus Jakarta Sans' !important;

    font-size:
        12px !important;

    font-weight:
        700 !important;

}

.stTabs button[aria-selected="true"] {

    color:
        var(--blue) !important;

    border-bottom:
        2px solid var(--blue) !important;

}

.stTabs button[aria-selected="true"] p {

    color:
        var(--blue) !important;

    font-weight:
        800 !important;

}


/* =========================================================
   ASSET CARD
   ========================================================= */

.asset-card {

    background:
        var(--surface);

    border:
        1px solid var(--border);

    border-radius:
        20px;

    padding:
        22px;

    margin-bottom:
        15px;

    box-shadow:
        var(--shadow);

    transition:
        all .22s ease;

}

.asset-card:hover {

    transform:
        translateY(-2px);

    box-shadow:
        var(--shadow-hover);

    border-color:
        #dce3ed;

}


/* =========================================================
   ASSET HEADER
   ========================================================= */

.asset-header {

    display:
        flex;

    align-items:
        flex-start;

    justify-content:
        space-between;

    gap:
        20px;

    margin-bottom:
        16px;

}

.asset-left {

    display:
        flex;

    flex-direction:
        column;

    align-items:
        flex-start;

    min-width:
        0;

    flex: 1;

}

.asset-new-row {

    min-height:
        20px;

    margin-bottom:
        5px;

}

.asset-identity {

    display:
        flex;

    align-items:
        center;

    gap:
        12px;

    min-width:
        0;

}

.asset-icon {

    width:
        46px;

    height:
        46px;

    min-width:
        46px;

    border-radius:
        14px;

    background:
        var(--blue-soft);

    display:
        flex;

    align-items:
        center;

    justify-content:
        center;

    font-size:
        20px;

}

.asset-company {

    font-family:
        'Plus Jakarta Sans';

    font-size:
        16px;

    font-weight:
        800;

    color:
        var(--text);

    line-height:
        1.2;

}

.asset-ticker {

    color:
        var(--text-tertiary);

    font-size:
        11px;

    font-weight:
        700;

    margin-left:
        5px;

}

.asset-sector {

    color:
        var(--text-secondary);

    font-size:
        11px;

    margin-top:
        3px;

}

.asset-right {

    text-align:
        right;

    flex-shrink:
        0;

    padding-top:
        25px;

}

.new-badge {

    display:
        inline-flex;

    align-items:
        center;

    gap:
        4px;

    background:
        var(--green-soft);

    color:
        #15803d;

    border:
        1px solid #dcfce7;

    padding:
        4px 8px;

    border-radius:
        999px;

    font-size:
        8px;

    font-weight:
        800;

    letter-spacing:
        .07em;

}

.current-price {

    font-family:
        'Plus Jakarta Sans';

    font-size:
        22px;

    font-weight:
        800;

    color:
        var(--text);

    letter-spacing:
        -.03em;

}

.price-label {

    font-size:
        9px;

    color:
        var(--text-tertiary);

    text-transform:
        uppercase;

    letter-spacing:
        .08em;

    font-weight:
        800;

}


/* =========================================================
   V4 POLISH — OPPORTUNITY CARD
   ========================================================= */

.opportunity-card-landing {
    position: relative;
    overflow: hidden;
}

.example-alert-ribbon {
    position: absolute;
    top: 20px;
    right: -42px;
    z-index: 20;
    width: 155px;
    padding: 7px 0;
    transform: rotate(38deg);
    background: var(--aq-blue);
    color: #fff;
    text-align: center;
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 9px;
    font-weight: 800;
    letter-spacing: .1em;
    box-shadow: 0 8px 20px rgba(37,99,235,.18);
}

.asset-header {
    position: relative;
}

.asset-right {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    justify-content: center;
    min-width: 118px;
    padding-top: 0;
}

.asset-score {
    display: inline-flex;
    flex-direction: column;
    align-items: flex-start;
    margin-bottom: 8px;
}

.asset-score strong {
    color: var(--aq-blue);
}

.asset-score small {
    margin-top: 3px;
    color: #7b8ba7;
}

.asset-score strong {
    color: var(--aq-blue);
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 20px;
    line-height: 1;
    font-weight: 800;
}

.asset-score small {
    margin-top: 3px;
    color: #7b8ba7;
    font-size: 7px;
    line-height: 1;
    font-weight: 800;
    letter-spacing: .08em;
}

.performance-row {
    width: 100%;
    margin: 0 0 18px;
    padding: 11px 18px;
    box-sizing: border-box;
    border: 1px solid #dbe7ff;
    border-radius: 12px;
    background: #f8fbff;
}

.performance-row .performance-rr,
.performance-row .performance-left {
    min-width: 0;
}

.performance-row .performance-value,
.performance-row .performance-rr-value {
    white-space: nowrap;
}

.aq-demo-wrap {
    position: relative;
    width: min(100%, 920px);
    margin: 0 auto;
}

.aq-demo-card {
    position: relative;
    overflow: hidden;
    border: 1px solid #dce5f2;
    border-radius: 22px;
    background: #fff;
    box-shadow: 0 16px 45px rgba(15,23,42,.07);
}

.aq-demo-card-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 24px;
    padding: 24px 28px 18px;
}

.aq-demo-company {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 20px;
    font-weight: 800;
    letter-spacing: -.025em;
}

.aq-demo-company span {
    margin-left: 7px;
    color: #94a3b8;
    font-size: 11px;
    font-weight: 700;
}

.aq-demo-sector {
    margin-top: 5px;
    color: #64748b;
    font-size: 11px;
}

.aq-demo-score {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    padding: 9px 12px;
    border: 1px solid #dbe7ff;
    border-radius: 11px;
    background: #f4f7ff;
}

.aq-demo-score strong {
    color: var(--aq-blue);
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 25px;
    line-height: 1;
}

.aq-demo-score span {
    margin-top: 4px;
    color: #7b8ba7;
    font-size: 7px;
    font-weight: 800;
    letter-spacing: .08em;
}

.aq-demo-card-body {
    padding: 0 14px 14px;
}

.aq-demo-card-body .asset-card {
    margin: 0;
    box-shadow: none;
    border-color: #e5eaf1;
}

@media (max-width: 650px) {
    .example-alert-ribbon {
        top: 15px;
        right: -48px;
    }

    .performance-row {
        width: 100%;
        padding: 10px 14px;
    }

    .asset-right {
        min-width: 100px;
        padding-top: 31px;
    }

    .asset-score strong {
        font-size: 17px;
    }

    .aq-demo-card-head {
        padding: 20px 18px 14px;
    }

    .aq-demo-card-body {
        padding: 0 8px 8px;
    }
}

/* =========================================================
   PERFORMANCE / RISK REWARD
   ========================================================= */

.performance-row {

    display:
        flex;

    align-items:
        center;

    justify-content:
        space-between;

    gap:
        20px;

    padding:
        10px 12px;

    background:
        var(--surface-soft);

    border-radius:
        11px;

    margin-bottom:
        18px;

}

.performance-left {

    display:
        flex;

    flex-direction:
        column;

    align-items:
        flex-end;

    text-align:
        right;

    min-width:
        0;

    order:
        2;

}

.performance-label {

    font-size:
        10px;

    color:
        var(--text-secondary);

    font-weight:
        700;

}

.performance-value {

    font-family:
        'Plus Jakarta Sans';

    font-size:
        13px;

    font-weight:
        800;

}

.performance-positive {

    color:
        var(--green);

}

.performance-negative {

    color:
        var(--red);

}

.performance-neutral {

    color:
        var(--text-secondary);

}

.performance-rr {

    display:
        flex;

    flex-direction:
        column;

    align-items:
        flex-start;

    flex-shrink:
        0;

    order:
        1;

}

.performance-rr-label {

    font-size:
        8px;

    color:
        var(--text-tertiary);

    text-transform:
        uppercase;

    letter-spacing:
        .07em;

    font-weight:
        800;

}

.performance-rr-value {

    margin-top:
        2px;

    font-family:
        'Plus Jakarta Sans';

    font-size:
        13px;

    font-weight:
        800;

    color:
        var(--blue);

}


/* =========================================================
   POSITION TRACKER
   ========================================================= */

.position-wrapper {

    margin:
        3px 3px 22px;

}

.position-labels {

    display:
        grid;

    grid-template-columns:
        repeat(4, 1fr);

    gap:
        8px;

    margin-bottom:
        3px;

}

.position-label-item {

    display:
        flex;

    flex-direction:
        column;

    gap:
        2px;

    min-width:
        0;

}

.position-label-item:nth-child(1) {

    text-align:
        left;

    align-items:
        flex-start;

}

.position-label-item:nth-child(2),
.position-label-item:nth-child(3) {

    text-align:
        center;

    align-items:
        center;

}

.position-label-item:nth-child(4) {

    text-align:
        right;

    align-items:
        flex-end;

}

.position-label {

    font-size:
        8px;

    font-weight:
        800;

    text-transform:
        uppercase;

    letter-spacing:
        .06em;

    color:
        var(--text-tertiary);

    white-space:
        nowrap;

}

.position-price {

    margin-top:
        3px;

    font-family:
        'Plus Jakarta Sans';

    font-size:
        10px;

    font-weight:
        800;

    color:
        var(--text);

    white-space:
        nowrap;

}

.position-track {

    height:
        6px;

    background:
        #e8edf4;

    border-radius:
        999px;

    position:
        relative;

    margin-top:
        7px;

}

.position-risk {

    position:
        absolute;

    left:
        0;

    top:
        0;

    bottom:
        0;

    background:
        #fecaca;

    border-radius:
        999px;

}

.position-reward {

    position:
        absolute;

    top:
        0;

    bottom:
        0;

    background:
        #bbf7d0;

    border-radius:
        999px;

}

.position-marker {

    position:
        absolute;

    top:
        50%;

    width:
        12px;

    height:
        12px;

    transform:
        translate(-50%, -50%);

    border-radius:
        50%;

    background:
        white;

    border:
        3px solid;

    box-shadow:
        0 1px 5px
        rgba(15,23,42,.15);

}

.marker-sl {

    border-color:
        var(--red);

}

.marker-entry {

    border-color:
        var(--blue);

}

.marker-current {

    width:
        16px;

    height:
        16px;

    border:
        4px solid white;

    background:
        var(--blue);

    box-shadow:
        0 0 0 2px var(--blue),
        0 2px 7px
        rgba(37,99,235,.3);

}

.marker-tp {

    border-color:
        var(--green);

}


/* =========================================================
   AI INSIGHT
   ========================================================= */

.ai-box {

    background:
        linear-gradient(
            135deg,
            #f7faff,
            #f8fafc
        );

    border:
        1px solid #e6edff;

    border-radius:
        14px;

    padding:
        14px 16px;

}

.ai-header {

    display:
        flex;

    align-items:
        center;

    gap:
        7px;

    color:
        var(--blue);

    font-size:
        9px;

    font-weight:
        800;

    text-transform:
        uppercase;

    letter-spacing:
        .08em;

    margin-bottom:
        6px;

}

.ai-text {

    color:
        #475569;

    font-size:
        12px;

    line-height:
        1.65;

}


/* =========================================================
   RESULTADOS
   ========================================================= */

.result-card {

    background:
        var(--surface);

    border:
        1px solid var(--border);

    border-radius:
        20px;

    padding:
        22px;

    box-shadow:
        var(--shadow);

}

.result-header {

    display:
        flex;

    align-items:
        flex-start;

    justify-content:
        space-between;

    margin-bottom:
        20px;

}

.result-title {

    font-family:
        'Plus Jakarta Sans';

    font-size:
        16px;

    font-weight:
        800;

}

.result-subtitle {

    color:
        var(--text-secondary);

    font-size:
        11px;

    margin-top:
        3px;

}

.result-number {

    font-family:
        'Plus Jakarta Sans';

    font-size:
        23px;

    font-weight:
        800;

    text-align:
        right;

}

.result-percent {

    font-size:
        10px;

    color:
        var(--text-secondary);

    text-align:
        right;

    margin-top:
        2px;

}


/* =========================================================
   METRICS
   ========================================================= */

.metric-list {

    display:
        flex;

    flex-direction:
        column;

}

.metric-row {

    display:
        flex;

    align-items:
        center;

    justify-content:
        space-between;

    padding:
        14px 0;

    border-bottom:
        1px solid var(--border-soft);

}

.metric-row:last-child {

    border-bottom:
        0;

}

.metric-name {

    color:
        var(--text-secondary);

    font-size:
        11px;

    font-weight:
        600;

}

.metric-value {

    font-family:
        'Plus Jakarta Sans';

    font-size:
        13px;

    font-weight:
        800;

}


/* =========================================================
   EMPTY STATE
   ========================================================= */

.empty-state {

    background:
        var(--surface);

    border:
        1px dashed #dce3ed;

    border-radius:
        18px;

    padding:
        45px 20px;

    text-align:
        center;

}

.empty-icon {

    font-size:
        28px;

    margin-bottom:
        10px;

}

.empty-title {

    font-family:
        'Plus Jakarta Sans';

    font-weight:
        800;

    font-size:
        15px;

}

.empty-text {

    color:
        var(--text-secondary);

    font-size:
        12px;

    margin-top:
        5px;

}


/* =========================================================
   HISTORIAL
   ========================================================= */

.history-header {

    background:
        var(--surface);

    border:
        1px solid var(--border);

    border-radius:
        18px;

    padding:
        20px;

    margin-bottom:
        16px;

    box-shadow:
        var(--shadow);

}

.history-title {

    font-family:
        'Plus Jakarta Sans';

    font-size:
        16px;

    font-weight:
        800;

}

.history-subtitle {

    color:
        var(--text-secondary);

    font-size:
        11px;

    margin-top:
        4px;

}


/* =========================================================
   FOOTER
   ========================================================= */

.app-footer {

    display:
        flex;

    justify-content:
        space-between;

    gap:
        15px;

    margin-top:
        48px;

    padding-top:
        18px;

    border-top:
        1px solid var(--border);

    color:
        var(--text-tertiary);

    font-size:
        9px;

    font-weight:
        600;

}


/* =========================================================
   STREAMLIT INPUTS
   ========================================================= */

div[data-baseweb="select"] > div,
div[data-testid="stTextInput"] input {

    border-radius:
        11px !important;

    border-color:
        var(--border) !important;

    background:
        white !important;

}

div[data-baseweb="select"] > div:hover,
div[data-testid="stTextInput"] input:focus {

    border-color:
        #bfd0f8 !important;

    box-shadow:
        0 0 0 3px
        rgba(37,99,235,.07) !important;

}


/* =========================================================
   DATAFRAME
   ========================================================= */

div[data-testid="stDataFrame"] {

    border:
        1px solid var(--border);

    border-radius:
        14px;

    overflow:
        hidden;

}


/* =========================================================
   MOBILE
   ========================================================= */

@media (max-width: 1000px) {

    .block-container {

        padding-left:
            20px;

        padding-right:
            20px;

    }

    .portfolio-summary {

        grid-template-columns:
            repeat(2, 1fr);

    }

}


@media (max-width: 650px) {

    .block-container {

        padding-top:
            18px;

        padding-left:
            12px;

        padding-right:
            12px;

    }

    .hero-title {

        font-size:
            27px;

    }

    .hero {

        margin-bottom:
            20px;

    }

    .portfolio-summary {

        grid-template-columns:
            1fr 1fr;

        gap:
            9px;

        margin-bottom:
            20px;

    }

    .summary-card {

        padding:
            14px;

        border-radius:
            14px;

    }

    .summary-label {

        font-size:
            8px;

        margin-bottom:
            7px;

    }

    .summary-value {

        font-size:
            18px;

    }

    .summary-detail {

        font-size:
            9px;

    }

    .asset-card {

        padding:
            17px;

        border-radius:
            17px;

    }

    .asset-header {

        gap:
            10px;

    }

    .asset-company {

        font-size:
            14px;

    }

    .asset-icon {

        width:
            42px;

        height:
            42px;

        min-width:
            42px;

        font-size:
            18px;

    }

    .current-price {

        font-size:
            18px;

    }

    .asset-right {

        padding-top:
            25px;

    }

    .performance-row {

        margin-bottom:
            15px;

        gap:
            10px;

    }

    .performance-value {

        font-size:
            12px;

    }

    .performance-rr-value {

        font-size:
            12px;

    }

    .position-label {

        font-size:
            7px;

    }

    .position-price {

        font-size:
            9px;

    }

    .scroll-top {

        right:
            14px;

        bottom:
            14px;

        width:
            38px;

        height:
            38px;

        border-radius:
            11px;

    }

    .app-footer {

        display:
            block;

        line-height:
            1.8;

    }

}


/* V2 PRODUCT / PRICING UI */
.pricing-hero{text-align:center;padding:28px 20px 18px;margin:8px 0 24px}.pricing-hero .eyebrow{font-size:11px;font-weight:800;letter-spacing:.16em;color:var(--blue);margin-bottom:10px}.pricing-hero h2{font-family:'Plus Jakarta Sans',sans-serif;font-size:34px;line-height:1.1;margin:0 0 10px}.pricing-hero p{max-width:680px;margin:0 auto;color:var(--text-secondary);font-size:15px;line-height:1.65}.pricing-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;margin:0 0 28px}.pricing-card{background:var(--surface);border:1px solid var(--border);border-radius:20px;padding:28px;box-shadow:var(--shadow);position:relative}.pricing-card-pro{border:1.5px solid #2563eb;box-shadow:0 14px 40px rgba(37,99,235,.10)}.pricing-badge{display:inline-flex;padding:6px 10px;border-radius:999px;background:var(--surface-soft);color:var(--text-secondary);font-size:10px;font-weight:800;letter-spacing:.1em}.pricing-badge.pro{background:var(--blue-soft);color:var(--blue)}.pricing-card h3{font-family:'Plus Jakarta Sans',sans-serif;font-size:22px;margin:18px 0 10px}.pricing-price{font-family:'Plus Jakarta Sans',sans-serif;font-size:34px;font-weight:800;margin-bottom:8px}.pricing-price span{font-family:'DM Sans',sans-serif;font-size:13px;color:var(--text-tertiary);font-weight:500}.pricing-description{color:var(--text-secondary);min-height:44px;line-height:1.5}.pricing-card ul{list-style:none;padding:0;margin:20px 0 0;color:var(--text-secondary);line-height:2;font-size:14px}.stripe-cta{margin-top:10px;text-align:center}.stripe-cta a{display:block;padding:12px 18px;border-radius:10px;background:var(--blue);color:white!important;text-decoration:none!important;font-weight:700}.subscription-note{margin-top:24px;padding:14px 16px;border:1px solid var(--border);background:var(--surface-soft);border-radius:12px;color:var(--text-secondary);font-size:12px;line-height:1.6}@media(max-width:800px){.pricing-grid{grid-template-columns:1fr}.pricing-hero h2{font-size:28px}}

.hero-v2{display:grid!important;grid-template-columns:minmax(0,1.35fr) minmax(260px,.65fr);gap:30px;align-items:center;padding:52px 48px!important;min-height:300px!important;background:radial-gradient(circle at 80% 20%,rgba(37,99,235,.10),transparent 34%),linear-gradient(135deg,#ffffff,#f5f8ff)!important;border:1px solid var(--border);border-radius:24px;overflow:hidden}.hero-eyebrow{font-size:10px;letter-spacing:.16em;font-weight:800;color:var(--blue);margin-bottom:14px}.hero-v2 .hero-title{font-family:'Plus Jakarta Sans',sans-serif!important;font-size:clamp(34px,4vw,54px)!important;line-height:1.04!important;letter-spacing:-.045em!important;max-width:760px}.hero-v2 .hero-subtitle{max-width:680px!important;font-size:16px!important;line-height:1.65!important;margin-top:18px!important}.hero-actions{display:flex;gap:10px;margin-top:24px;flex-wrap:wrap}.hero-btn{display:inline-flex;padding:11px 16px;border-radius:10px;text-decoration:none!important;font-weight:700;font-size:13px}.hero-btn.primary{background:var(--blue);color:#fff!important}.hero-btn.secondary{background:#fff;color:var(--text)!important;border:1px solid var(--border)}.hero-orbit{display:flex;justify-content:center;align-items:center;min-height:220px;position:relative}.orbit-card{width:190px;height:190px;border-radius:50%;background:#fff;border:1px solid var(--border);box-shadow:0 20px 55px rgba(15,23,42,.10);display:flex;flex-direction:column;justify-content:center;align-items:center;position:relative;z-index:2}.orbit-card span{font-size:9px;font-weight:800;letter-spacing:.12em;color:var(--text-tertiary)}.orbit-card strong{font-family:'Plus Jakarta Sans',sans-serif;font-size:56px;line-height:1;margin:7px 0}.orbit-card small{font-size:11px;color:var(--green);font-weight:700}.orbit-line{position:absolute;width:245px;height:245px;border:1px dashed #cbd5e1;border-radius:50%;}.hero-v2 + .portfolio-summary{margin-top:18px}@media(max-width:800px){.hero-v2{grid-template-columns:1fr;padding:34px 24px!important}.hero-orbit{display:none}}

/* V3 — opportunity / performance polish */
.opportunity-count{
    margin:8px 0 14px;color:#94a3b8;font-size:10px;font-weight:800;letter-spacing:.08em;
}
.asset-score{display:block;margin:0 0 8px;text-align:left}
.asset-score strong{display:block;font-family:'Plus Jakarta Sans';font-size:18px;line-height:1;color:var(--blue)}
.asset-score small{display:block;margin-top:3px;color:var(--text-tertiary);font-size:8px;letter-spacing:.09em;font-weight:800}
.position-empty{padding:12px 0;color:var(--text-tertiary);font-size:11px}
.opportunity-card-landing{max-width:980px;margin:0 auto 10px}

.aq-engine-labels{
    display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:28px
}
.aq-engine-labels div{
    background:#fff;border:1px solid var(--aq-border);border-radius:16px;
    padding:18px 16px;text-align:left;font-family:'Plus Jakarta Sans';
    font-size:14px;font-weight:800;box-shadow:var(--aq-shadow)
}
.aq-engine-labels span{
    display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;
    margin-right:9px;border-radius:9px;background:#eff6ff;color:#2563eb;font-size:10px
}
.aq-ai-process{
    display:flex;align-items:center;justify-content:center;gap:14px;flex-wrap:wrap;
    margin:30px auto 0;max-width:900px
}
.aq-ai-process div{
    padding:13px 18px;background:#fff;border:1px solid var(--aq-border);
    border-radius:12px;font-size:11px;font-weight:800;letter-spacing:.06em;
    box-shadow:var(--aq-shadow)
}
.aq-ai-process span{color:#94a3b8;font-weight:800}
.aq-home-stats .summary-card{padding:22px 21px;border-radius:18px}
.aq-home-stats .summary-value{font-size:25px}
.aq-home-stats .summary-label{font-size:9px}
.aq-home-stats .summary-detail{font-size:10px}
.equity-chart{
    margin-top:18px;border:1px solid #edf1f6;border-radius:16px;background:#fbfcfe;
    overflow:hidden;height:330px
}
.equity-chart svg{width:100%;height:100%;display:block}
.equity-grid{stroke:#e9eef5;stroke-width:1}
.equity-label{font-family:'DM Sans';font-size:11px;fill:#94a3b8}
.equity-date{font-family:'DM Sans';font-size:11px;fill:#94a3b8}
.equity-line{fill:none;stroke:#2563eb;stroke-width:4;stroke-linecap:round;stroke-linejoin:round}
.equity-area{fill:rgba(37,99,235,.07)}
.equity-dot{fill:#fff;stroke:#2563eb;stroke-width:4}
.equity-final{font-family:'Plus Jakarta Sans';font-size:12px;font-weight:800}
.equity-empty{height:100%;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:13px}
.performance-page-head{
    display:flex;justify-content:space-between;align-items:flex-end;gap:30px;
    padding:20px 0 25px;border-bottom:1px solid var(--border);margin-bottom:20px
}
.performance-page-head h2{
    font-family:'Plus Jakarta Sans';font-size:36px;letter-spacing:-.045em;margin:6px 0 7px
}
.performance-page-head p{margin:0;color:var(--text-secondary);font-size:13px}
.performance-total{text-align:right;min-width:190px}
.performance-total span{display:block;font-size:9px;color:#94a3b8;letter-spacing:.1em;font-weight:800}
.performance-total strong{display:block;font-family:'Plus Jakarta Sans';font-size:29px;letter-spacing:-.04em;margin-top:4px}
.performance-total small{display:block;color:#64748b;font-size:10px;margin-top:5px}
.performance-kpis{
    display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:18px
}
.performance-kpi{
    background:#fff;border:1px solid var(--border);border-radius:16px;padding:17px 15px;
    box-shadow:var(--shadow);min-width:0
}
.performance-kpi span{display:block;color:#64748b;font-size:9px;text-transform:uppercase;letter-spacing:.07em;font-weight:800}
.performance-kpi strong{display:block;font-family:'Plus Jakarta Sans';font-size:22px;line-height:1.1;margin-top:8px}
.performance-kpi small{display:block;color:#94a3b8;font-size:9px;margin-top:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.performance-kpi.positive strong{color:#16a34a}
.performance-kpi.negative strong{color:#dc2626}
.performance-chart-card{
    background:#fff;border:1px solid var(--border);border-radius:20px;padding:24px;
    box-shadow:var(--shadow)
}
.performance-chart-head{display:flex;justify-content:space-between;align-items:center;gap:20px}
.performance-chart-title{font-family:'Plus Jakarta Sans';font-size:18px;font-weight:800}
.performance-chart-subtitle{color:#94a3b8;font-size:11px;margin-top:4px}
.chart-legend{font-size:10px;color:#64748b;font-weight:700}
.chart-legend i{display:inline-block;width:8px;height:8px;background:#2563eb;border-radius:50%;margin-right:6px}
.performance-chart-footer{
    display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap;
    margin-top:14px;padding-top:14px;border-top:1px solid #eef1f5;
    color:#64748b;font-size:10px
}
.performance-chart-footer strong{color:#334155}
.performance-disclaimer{
    margin:14px 0;color:#94a3b8;font-size:10px;line-height:1.6
}
@media(max-width:1000px){
    .performance-kpis{grid-template-columns:repeat(3,1fr)}
    .aq-engine-labels{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:650px){
    .performance-page-head{align-items:flex-start;flex-direction:column}
    .performance-total{text-align:left}
    .performance-kpis{grid-template-columns:repeat(2,1fr)}
    .performance-chart-card{padding:16px}
    .performance-chart-head{align-items:flex-start;flex-direction:column}
    .equity-chart{height:270px}
    .aq-engine-labels{grid-template-columns:1fr}
    .aq-ai-process{gap:8px}
    .aq-ai-process span{display:none}
}



html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stAppViewBlockContainer"] {
    max-width: 100%;
    overflow-x: hidden !important;
}
.aq-wrap, .aq-section, .aq-hero, .aq-kpis {
    max-width: 100%;
    box-sizing: border-box;
}
@media (max-width: 650px) {
    .aq-wrap {
        width: 100%;
        overflow-x: hidden;
    }
    .aq-hero {
        padding-left: 8px;
        padding-right: 8px;
    }
    .aq-hero h1, .aq-hero p {
        max-width: 100%;
        overflow-wrap: anywhere;
    }
    .aq-hero:before {
        width: 100vw;
        max-width: 100%;
    }
}

/* FINAL CARD POLISH */
.opportunity-card-landing .asset-header {
    min-height: 74px;
}

.opportunity-card-landing .asset-right {
    padding-top: 0;
}

.opportunity-card-landing .asset-score {
    margin: 0 0 8px;
    text-align: left;
}

.opportunity-card-landing .performance-row {
    width: calc(100% - 32px);
    margin-left: auto;
    margin-right: auto;
}

.opportunity-card-landing .ai-box {
    margin-left: 0;
    margin-right: 0;
}


/* FINAL REQUESTED LAYOUT OVERRIDES */
.asset-header {
    align-items: flex-start !important;
}
.asset-right {
    justify-content: flex-start !important;
    padding-top: 35px !important;
}
.asset-score {
    margin: 0 0 8px !important;
    text-align: left !important;
}
.performance-row {
    width: 100% !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
    padding-left: 18px !important;
    padding-right: 18px !important;
}
.performance-rr {
    align-items: flex-start !important;
    text-align: left !important;
}
.performance-left {
    align-items: flex-end !important;
    text-align: right !important;
}
.opportunity-card-landing .asset-right {
    padding-top: 35px !important;
}
.opportunity-card-landing .performance-row {
    width: 100% !important;
}
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stAppViewBlockContainer"] {
    max-width: 100% !important;
    overflow-x: hidden !important;
}
@media (max-width: 650px) {
    .asset-right, .opportunity-card-landing .asset-right {
        padding-top: 31px !important;
        min-width: 92px;
    }
    .performance-row, .opportunity-card-landing .performance-row {
        width: 100% !important;
        padding-left: 14px !important;
        padding-right: 14px !important;
    }
    .aq-wrap, .aq-section, .aq-hero, .aq-kpis {
        max-width: 100% !important;
        box-sizing: border-box !important;
    }
    .aq-hero {
        padding-left: 8px;
        padding-right: 8px;
    }
    .aq-hero h1, .aq-hero p {
        max-width: 100%;
        overflow-wrap: anywhere;
    }
    .aq-hero:before {
        width: 100%;
        max-width: 100%;
    }
}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# CARGAR HISTÓRICO
# ============================================================

df_hist = preparar_fecha(
    cargar_datos()
)

metricas = calcular_metricas(
    df_hist
)

total_alertas = metricas[
    "total_alertas"
]

exitos = metricas[
    "exitos"
]

fallos = metricas[
    "fallos"
]

activas = metricas[
    "activas"
]

win_rate = metricas[
    "win_rate"
]


# ============================================================
# POSICIONES ACTIVAS
# ============================================================

if (
    not df_hist.empty
    and "Estado" in df_hist.columns
):

    df_activas_global = df_hist[
        df_hist["Estado"]
        .astype(str)
        .str.contains(
            "ACTIVA",
            na=False,
            regex=False
        )
    ].copy()

else:

    df_activas_global = pd.DataFrame()


# ============================================================
# PRECIOS ACTUALES
# ============================================================

precios_actuales = obtener_precios_activos(
    df_activas_global
)


# ============================================================
# BENEFICIO REALIZADO
# ============================================================

beneficio_realizado = (
    calcular_beneficio_realizado(
        df_hist
    )
)


# ============================================================
# BENEFICIO NO REALIZADO
# ============================================================

(
    beneficio_no_realizado,
    posiciones_con_beneficio,
    posiciones_con_perdida
) = calcular_beneficio_no_realizado(
    df_activas_global,
    precios_actuales
)


# ============================================================
# BENEFICIO TOTAL Y CAPITAL DINÁMICO
# ============================================================

beneficio_acumulado = (
    beneficio_realizado +
    beneficio_no_realizado
)

total_operaciones_historicas = max(
    1,
    len(df_hist)
)

CAPITAL_INICIAL = max(
    3600.0,
    total_operaciones_historicas *
    CAPITAL_POR_ALERTA
)

rentabilidad_pct = (
    beneficio_acumulado
    /
    CAPITAL_INICIAL
    *
    100
    if CAPITAL_INICIAL
    else 0
)


color_resultado = (
    "#16a34a"
    if beneficio_acumulado >= 0
    else "#dc2626"
)


# ============================================================
# CURVA DE RESULTADOS
# ============================================================

(
    beneficio_realizado_curva,
    fechas_curva,
    beneficios_curva
) = calcular_resultados(
    df_hist,
    beneficio_no_realizado
)


# ============================================================
# OBTENER FECHA DE ÚLTIMA ACTUALIZACIÓN DEL SISTEMA
# ============================================================

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
# ALURA QUANT — LANDING + PRODUCT UI V2
# ============================================================

# Datos globales

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

# ------------------------------------------------------------

# ============================================================
# ALURA QUANT — PREMIUM PRODUCT UI
# ============================================================

render_html("""
<style>
:root{
    --aq-bg:#f7f9fc;
    --aq-surface:#ffffff;
    --aq-surface-2:#fbfcfe;
    --aq-text:#0b1220;
    --aq-muted:#667085;
    --aq-subtle:#98a2b3;
    --aq-border:#e7ebf2;
    --aq-border-strong:#d9e0ea;
    --aq-blue:#2563eb;
    --aq-blue-dark:#1d4ed8;
    --aq-blue-soft:#eff6ff;
    --aq-green:#16a34a;
    --aq-red:#dc2626;
    --aq-shadow:0 16px 50px rgba(15,23,42,.055);
    --aq-shadow-soft:0 8px 28px rgba(15,23,42,.035);
}

.stApp{
    background:
        radial-gradient(circle at 50% -10%, rgba(37,99,235,.045), transparent 34%),
        var(--aq-bg);
}

.block-container{
    max-width:1320px !important;
    padding-top:1rem !important;
    padding-bottom:2rem !important;
}

.aq-wrap{max-width:1180px;margin:0 auto}
.aq-eyebrow{
    color:var(--aq-blue);
    font-size:11px;
    font-weight:800;
    letter-spacing:.16em;
    text-transform:uppercase;
}
.aq-section{padding:78px 0}
.aq-section.center{text-align:center}
.aq-section h2{
    color:var(--aq-text);
    font-family:'Plus Jakarta Sans',sans-serif;
    font-size:clamp(30px,3.5vw,46px);
    line-height:1.08;
    letter-spacing:-.045em;
    margin:10px 0 15px;
}
.aq-section-intro{
    max-width:690px;
    margin:0 auto;
    color:var(--aq-muted);
    font-size:16px;
    line-height:1.75;
}

/* ---------- TOP BAR ---------- */
.aq-topbar{
    height:62px;
    display:flex;
    align-items:center;
    justify-content:space-between;
    border-bottom:1px solid var(--aq-border);
}
.aq-brand{
    font-family:'Plus Jakarta Sans',sans-serif;
    font-size:19px;
    font-weight:800;
    letter-spacing:-.045em;
    color:var(--aq-text);
}
.aq-brand span{color:var(--aq-blue)}
.aq-topmeta{
    color:var(--aq-subtle);
    font-size:10px;
    font-weight:700;
    letter-spacing:.08em;
    text-transform:uppercase;
}

/* ---------- HERO ---------- */
.aq-hero{
    padding:92px 0 72px;
    text-align:center;
    position:relative;
}
.aq-hero:before{
    content:"";
    position:absolute;
    width:680px;
    height:320px;
    left:50%;
    top:15px;
    transform:translateX(-50%);
    background:radial-gradient(circle,rgba(37,99,235,.10),transparent 68%);
    pointer-events:none;
}
.aq-hero > *{position:relative}
.aq-hero-badge{
    display:inline-flex;
    align-items:center;
    gap:8px;
    padding:7px 11px;
    border:1px solid #dce7fb;
    border-radius:999px;
    background:rgba(255,255,255,.78);
    color:#4b6da8;
    font-size:10px;
    font-weight:800;
    letter-spacing:.12em;
    text-transform:uppercase;
    box-shadow:0 4px 18px rgba(37,99,235,.05);
}
.aq-hero-badge i{
    width:6px;height:6px;border-radius:50%;
    background:#22c55e;display:inline-block;
    box-shadow:0 0 0 4px rgba(34,197,94,.10);
}
.aq-hero h1{
    max-width:920px;
    margin:24px auto 22px;
    color:var(--aq-text);
    font-family:'Plus Jakarta Sans',sans-serif;
    font-size:clamp(44px,6.2vw,78px);
    line-height:.99;
    letter-spacing:-.065em;
    font-weight:800;
}
.aq-hero h1 span{color:var(--aq-blue)}
.aq-hero p{
    max-width:680px;
    margin:0 auto 31px;
    color:var(--aq-muted);
    font-size:18px;
    line-height:1.7;
}
.aq-actions{
    display:flex;
    justify-content:center;
    gap:10px;
    flex-wrap:wrap;
}
.aq-btn{
    display:inline-flex;
    align-items:center;
    justify-content:center;
    min-height:45px;
    padding:0 18px;
    border-radius:11px;
    border:1px solid var(--aq-border-strong);
    background:#fff;
    color:var(--aq-text);
    text-decoration:none;
    font-size:13px;
    font-weight:800;
    transition:.18s ease;
}
.aq-btn:hover{transform:translateY(-1px);box-shadow:0 8px 22px rgba(15,23,42,.08)}
.aq-btn.primary{background:var(--aq-blue);border-color:var(--aq-blue);color:#fff}
.aq-btn.primary:hover{background:var(--aq-blue-dark)}

/* ---------- KPI STRIP ---------- */
.aq-kpis{
    display:grid;
    grid-template-columns:repeat(4,1fr);
    background:#fff;
    border:1px solid var(--aq-border);
    border-radius:18px;
    box-shadow:var(--aq-shadow-soft);
    overflow:hidden;
}
.aq-kpi{
    padding:25px 26px 23px;
    position:relative;
}
.aq-kpi + .aq-kpi{border-left:1px solid var(--aq-border)}
.aq-kpi-label{
    color:#7b8798;
    font-size:10px;
    font-weight:800;
    letter-spacing:.11em;
    text-transform:uppercase;
}
.aq-kpi-value{
    margin-top:9px;
    color:var(--aq-text);
    font-family:'Plus Jakarta Sans',sans-serif;
    font-size:28px;
    line-height:1;
    font-weight:800;
    letter-spacing:-.045em;
}
.aq-kpi-detail{
    margin-top:8px;
    color:#98a2b3;
    font-size:11px;
}

/* ---------- SECTION HEAD ---------- */
.aq-section-head{
    display:flex;
    align-items:flex-end;
    justify-content:space-between;
    gap:20px;
    margin-bottom:25px;
}
.aq-section-head h2{margin:7px 0 0}
.aq-section-head p{
    max-width:510px;
    margin:0;
    color:var(--aq-muted);
    line-height:1.65;
    font-size:14px;
}

/* ---------- PROBLEM / POSITIONING ---------- */
.aq-positioning{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:18px;
}
.aq-positioning-card{
    min-height:250px;
    padding:32px;
    border:1px solid var(--aq-border);
    border-radius:22px;
    background:#fff;
    box-shadow:var(--aq-shadow-soft);
}
.aq-positioning-card.dark{
    background:#0c1424;
    border-color:#0c1424;
    color:#fff;
}
.aq-positioning-card h3{
    font-family:'Plus Jakarta Sans',sans-serif;
    font-size:24px;
    line-height:1.15;
    letter-spacing:-.035em;
    margin:13px 0 13px;
}
.aq-positioning-card p{
    margin:0;
    color:var(--aq-muted);
    line-height:1.75;
    font-size:14px;
}
.aq-positioning-card.dark p{color:#b7c2d2}
.aq-mini-list{margin-top:23px;display:grid;gap:10px}
.aq-mini-list div{
    display:flex;align-items:center;gap:10px;
    color:#dbe4f0;font-size:12px;font-weight:700;
}
.aq-mini-list i{
    width:7px;height:7px;border-radius:50%;
    background:#60a5fa;display:inline-block;
}

/* ---------- ENGINE: ONLY FOUR LABELS ---------- */
.aq-engine-line{
    display:grid;
    grid-template-columns:repeat(4,1fr);
    border-top:1px solid var(--aq-border);
    border-bottom:1px solid var(--aq-border);
}
.aq-engine-item{
    padding:22px 10px;
    color:var(--aq-text);
    font-family:'Plus Jakarta Sans',sans-serif;
    font-size:13px;
    font-weight:800;
    letter-spacing:-.01em;
    text-align:center;
}
.aq-engine-item + .aq-engine-item{border-left:1px solid var(--aq-border)}
.aq-engine-item span{
    color:var(--aq-blue);
    font-size:10px;
    letter-spacing:.14em;
    margin-right:7px;
}

/* ---------- FEATURE / SIGNAL ---------- */
.aq-feature-card{
    border:1px solid var(--aq-border);
    border-radius:25px;
    background:#fff;
    box-shadow:var(--aq-shadow);
    overflow:hidden;
}
.aq-feature-intro{
    padding:27px 30px 0;
}
.aq-feature-intro .aq-eyebrow{margin-bottom:6px}
.aq-feature-intro h3{
    margin:0;
    font-family:'Plus Jakarta Sans',sans-serif;
    font-size:22px;
    letter-spacing:-.035em;
}
.aq-feature-intro p{
    margin:7px 0 0;
    color:var(--aq-muted);
    font-size:13px;
}
.aq-feature-body{padding:4px 16px 16px}
.aq-feature-body .asset-card{
    box-shadow:none !important;
    border:0 !important;
    margin-bottom:0 !important;
    background:transparent !important;
}

/* ---------- AI ---------- */
.aq-ai-section{
    padding:78px 0;
}
.aq-ai-panel{
    display:grid;
    grid-template-columns:.85fr 1.15fr;
    gap:0;
    overflow:hidden;
    border-radius:25px;
    background:#0c1424;
    box-shadow:var(--aq-shadow);
}
.aq-ai-side{
    padding:42px;
    border-right:1px solid rgba(255,255,255,.09);
}
.aq-ai-side .aq-eyebrow{color:#60a5fa}
.aq-ai-side h2{
    color:#fff;
    font-family:'Plus Jakarta Sans',sans-serif;
    font-size:35px;
    line-height:1.05;
    letter-spacing:-.045em;
    margin:12px 0 14px;
}
.aq-ai-side p{color:#aebbd0;line-height:1.75;font-size:14px}
.aq-ai-chain{
    padding:42px;
    display:grid;
    align-content:center;
    gap:10px;
}
.aq-ai-chain-row{
    display:flex;
    align-items:center;
    gap:10px;
}
.aq-ai-chain-row .node{
    flex:1;
    padding:15px 14px;
    border:1px solid rgba(255,255,255,.10);
    background:rgba(255,255,255,.045);
    border-radius:12px;
    color:#e9eef7;
    font-size:11px;
    font-weight:800;
    letter-spacing:.08em;
    text-align:center;
}
.aq-ai-chain-row .arrow{color:#64748b;font-size:16px}
.aq-ai-state{
    margin-top:12px;
    padding:14px 16px;
    border-radius:13px;
    background:rgba(37,99,235,.12);
    border:1px solid rgba(96,165,250,.18);
    color:#cfe0ff;
    font-size:12px;
    line-height:1.55;
}

/* ---------- CTA ---------- */
.aq-final-cta{
    padding:62px 35px;
    border-radius:27px;
    background:linear-gradient(135deg,#0b1220 0%,#142d65 100%);
    text-align:center;
    color:#fff;
    box-shadow:0 20px 60px rgba(15,23,42,.13);
}
.aq-final-cta .aq-eyebrow{color:#8db6ff}
.aq-final-cta h2{
    color:#fff;
    margin:10px 0 13px;
    font-family:'Plus Jakarta Sans',sans-serif;
    font-size:clamp(32px,4vw,49px);
    letter-spacing:-.05em;
}
.aq-final-cta p{
    max-width:620px;margin:0 auto 24px;
    color:#c6d3e8;line-height:1.7;font-size:15px;
}

/* ---------- OPPORTUNITY LIST ---------- */
.aq-list-head{
    display:flex;justify-content:space-between;align-items:end;
    margin:32px 0 20px;
}
.aq-list-head h2{
    margin:0;font-family:'Plus Jakarta Sans',sans-serif;
    font-size:34px;letter-spacing:-.045em;
}
.aq-list-head p{margin:6px 0 0;color:var(--aq-muted);font-size:13px}
.aq-count{
    color:#7b8798;font-size:10px;font-weight:800;
    letter-spacing:.12em;text-transform:uppercase;
}
.opportunity-count{
    color:#7b8798;
    font-size:10px;
    font-weight:800;
    letter-spacing:.12em;
    text-transform:uppercase;
    margin:20px 0 12px;
}

/* ---------- UPGRADE ORIGINAL ASSET CARD ---------- */
.asset-card{
    border-radius:22px !important;
    border:1px solid #e4e9f1 !important;
    background:#fff !important;
    box-shadow:0 8px 28px rgba(15,23,42,.035) !important;
    padding:25px !important;
    transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease !important;
}
.asset-card:hover{
    transform:translateY(-2px);
    border-color:#d5deeb !important;
    box-shadow:0 18px 42px rgba(15,23,42,.075) !important;
}
.asset-company{font-size:17px !important}
.current-price{font-size:25px !important}
.performance-row{
    margin-top:2px !important;
    border:1px solid #dbe7ff !important;
    padding:16px 28px !important;
}
.ai-box{
    margin-top:20px !important;
    border-radius:15px !important;
    background:linear-gradient(135deg,#f7faff,#fbfcfe) !important;
    border:1px solid #e4ebfa !important;
    padding:17px 18px !important;
}
.ai-header{
    font-size:10px !important;
    letter-spacing:.10em !important;
    text-transform:uppercase !important;
    color:#315ea8 !important;
    font-weight:800 !important;
}
.ai-text{
    margin-top:8px !important;
    color:#435066 !important;
    font-size:13px !important;
    line-height:1.7 !important;
}
.position-wrapper{margin:20px 2px 3px !important}
.position-label{font-size:9px !important;letter-spacing:.06em}
.position-price{font-size:10px !important}
.position-track{height:7px !important;background:#edf1f6 !important}
.position-risk{background:#fca5a5 !important}
.position-reward{background:#86efac !important}
.marker-current{
    background:#fff !important;
    box-shadow:0 0 0 2px #2563eb,0 2px 8px rgba(37,99,235,.25) !important;
}
.asset-score strong{font-size:24px !important}
.asset-score small{font-size:8px !important}

/* ---------- PERFORMANCE ---------- */
.performance-page-head{
    display:flex;justify-content:space-between;align-items:flex-end;
    gap:30px;padding:55px 0 30px;
    border-bottom:1px solid var(--aq-border);
}
.performance-page-head h2{
    font-family:'Plus Jakarta Sans',sans-serif;
    font-size:43px;letter-spacing:-.05em;margin:8px 0 8px;
}
.performance-page-head p{color:var(--aq-muted);font-size:14px;margin:0}
.performance-total{text-align:right}
.performance-total span{
    display:block;color:#98a2b3;font-size:9px;
    letter-spacing:.12em;font-weight:800;
}
.performance-total strong{
    display:block;font-family:'Plus Jakarta Sans',sans-serif;
    font-size:38px;letter-spacing:-.05em;margin:5px 0;
}
.performance-total small{color:#7b8798;font-size:11px}
.performance-kpis{
    display:grid;grid-template-columns:repeat(3,1fr);
    gap:12px;margin:22px 0;
}
.performance-kpi{
    min-height:112px;padding:20px 21px;
    background:#fff;border:1px solid var(--aq-border);
    border-radius:16px;box-shadow:var(--aq-shadow-soft);
}
.performance-kpi span{
    display:block;color:#7b8798;font-size:10px;
    font-weight:800;letter-spacing:.09em;text-transform:uppercase;
}
.performance-kpi strong{
    display:block;color:var(--aq-text);
    font-family:'Plus Jakarta Sans',sans-serif;
    font-size:28px;line-height:1;margin-top:11px;
    letter-spacing:-.04em;
}
.performance-kpi small{display:block;color:#98a2b3;font-size:10px;margin-top:8px}
.performance-kpi.positive strong{color:var(--aq-green)}
.performance-kpi.negative strong{color:var(--aq-red)}
.performance-chart-card{
    margin-top:12px;background:#fff;
    border:1px solid var(--aq-border);
    border-radius:22px;box-shadow:var(--aq-shadow-soft);
    overflow:hidden;
}
.performance-chart-head{
    display:flex;justify-content:space-between;align-items:center;
    padding:24px 25px 12px;
}
.performance-chart-title{
    font-family:'Plus Jakarta Sans',sans-serif;
    font-size:16px;font-weight:800;color:var(--aq-text);
}
.performance-chart-subtitle{color:#98a2b3;font-size:11px;margin-top:4px}
.chart-legend{
    color:#7b8798;font-size:10px;font-weight:700;
    display:flex;align-items:center;gap:7px;
}
.chart-legend i{
    width:8px;height:8px;border-radius:50%;background:var(--aq-blue);display:inline-block;
}
.equity-chart{padding:5px 18px 0}
.equity-chart svg{width:100%;height:360px;display:block}
.equity-grid{stroke:#edf1f5;stroke-width:1}
.equity-line{fill:none;stroke:#2563eb;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}
.equity-area{fill:url(#equityGradient);opacity:.12}
.equity-dot{fill:#fff;stroke:#2563eb;stroke-width:3}
.equity-label{fill:#98a2b3;font-size:10px}
.equity-date{fill:#98a2b3;font-size:10px}
.equity-final{font-size:11px;font-weight:800}
.performance-chart-footer{
    display:grid;grid-template-columns:repeat(3,1fr);
    border-top:1px solid #edf0f5;
}
.performance-chart-footer span{
    padding:16px 20px;color:#7b8798;font-size:11px;
}
.performance-chart-footer span+span{border-left:1px solid #edf0f5}
.performance-chart-footer strong{color:var(--aq-text)}
.performance-disclaimer{
    padding:18px 2px 40px;color:#98a2b3;
    font-size:10px;line-height:1.6;
}

/* ---------- PRICING ---------- */
.aq-pricing-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;max-width:940px;margin:32px auto 0}
.aq-price{
    background:#fff;border:1px solid var(--aq-border);
    border-radius:22px;padding:30px;box-shadow:var(--aq-shadow-soft);
}
.aq-price.pro{
    border:1.5px solid #b9cdfb;
    box-shadow:0 18px 50px rgba(37,99,235,.10);
}
.aq-price-badge{font-size:10px;font-weight:800;letter-spacing:.14em;color:var(--aq-blue)}
.aq-price h3{font-family:'Plus Jakarta Sans',sans-serif;font-size:24px;margin:10px 0}
.aq-price-num{font-family:'Plus Jakarta Sans',sans-serif;font-size:40px;font-weight:800;letter-spacing:-.05em}
.aq-price-num span{font-family:'DM Sans',sans-serif;font-size:12px;color:var(--aq-muted);font-weight:500}
.aq-price p{color:var(--aq-muted);line-height:1.65;font-size:13px}
.aq-price ul{padding:0;margin:20px 0 0;list-style:none}
.aq-price li{padding:8px 0;color:#334155;font-size:13px;border-bottom:1px solid #f0f2f6}
.aq-price li:last-child{border-bottom:0}
.aq-note{
    max-width:940px;margin:18px auto 0;
    color:#7b8798;font-size:10px;line-height:1.65;
    padding:12px 14px;border-radius:10px;background:#f9fafb;
    border:1px solid #edf0f4;
}
.aq-footer{
    margin-top:55px;padding:22px 0 10px;
    border-top:1px solid var(--aq-border);
    display:flex;justify-content:space-between;gap:20px;
    color:#98a2b3;font-size:10px;
    letter-spacing:.04em;
}

/* ---------- STREAMLIT TABS ---------- */
.stTabs [data-baseweb="tab-list"]{
    gap:3px;
    border-bottom:1px solid var(--aq-border);
}
.stTabs [data-baseweb="tab"]{
    padding:13px 15px !important;
    color:#7b8798 !important;
    font-size:12px !important;
    font-weight:700 !important;
}
.stTabs [aria-selected="true"]{
    color:var(--aq-blue) !important;
}
.stTabs [data-baseweb="tab-highlight"]{
    background:var(--aq-blue) !important;
    height:2px !important;
}

/* ---------- RESPONSIVE ---------- */
@media(max-width:900px){
    .aq-kpis{grid-template-columns:repeat(2,1fr)}
    .aq-kpi + .aq-kpi{border-left:0}
    .aq-kpi:nth-child(2n){border-left:1px solid var(--aq-border)}
    .aq-positioning,.aq-ai-panel{grid-template-columns:1fr}
    .aq-ai-side{border-right:0;border-bottom:1px solid rgba(255,255,255,.09)}
    .performance-page-head{align-items:flex-start;flex-direction:column}
    .performance-total{text-align:left}
}
@media(max-width:650px){
    .aq-hero{padding:60px 0 50px}
    .aq-hero h1{font-size:43px}
    .aq-hero p{font-size:16px}
    .aq-kpis,.performance-kpis,.aq-pricing-grid{grid-template-columns:1fr}
    .aq-kpi + .aq-kpi,.aq-kpi:nth-child(2n){border-left:0;border-top:1px solid var(--aq-border)}
    .aq-engine-line{grid-template-columns:1fr 1fr}
    .aq-engine-item:nth-child(3){border-left:0;border-top:1px solid var(--aq-border)}
    .aq-engine-item:nth-child(4){border-top:1px solid var(--aq-border)}
    .performance-chart-footer{grid-template-columns:1fr}
    .performance-chart-footer span+span{border-left:0;border-top:1px solid #edf0f5}
    .equity-chart svg{height:280px}
    .aq-topmeta{display:none}
    .asset-header{gap:10px}
    .asset-card{padding:19px !important}
}
</style>
""")

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

# ============================================================
# SHARED UI — OPPORTUNITY CARD
# ============================================================

# SHARED UI — OPPORTUNITY CARD
# ------------------------------------------------------------

def render_opportunity_card(row, compact=False, ribbon=False):
    """Renderiza la ficha visual clásica de Alura Quant."""
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

    stop_loss_text = formatear_numero(stop_loss, 2) if stop_loss is not None else "—"
    entrada_text = formatear_numero(precio_entrada, 2) if precio_entrada is not None else "—"
    actual_text = formatear_numero(precio_actual, 2) if precio_actual is not None else "—"
    take_profit_text = formatear_numero(take_profit, 2) if take_profit is not None else "—"

    positions = calcular_position_percentages(
        stop_loss, precio_entrada, precio_actual, take_profit
    )

    if positions:
        sl_pct = positions["sl"] if positions["sl"] is not None else 0
        entry_pct = positions["entry"] if positions["entry"] is not None else 25
        current_pct = positions["current"] if positions["current"] is not None else entry_pct
        tp_pct = positions["tp"] if positions["tp"] is not None else 100

        risk_width = max(0, min(entry_pct, current_pct) - sl_pct)
        reward_width = max(0, tp_pct - max(entry_pct, current_pct))

        position_tracker = f"""
        <div class="position-wrapper">
            <div class="position-labels">
                <div class="position-label-item"><span class="position-label">Stop</span><span class="position-price">{stop_loss_text}</span></div>
                <div class="position-label-item"><span class="position-label">Entrada</span><span class="position-price">{entrada_text}</span></div>
                <div class="position-label-item"><span class="position-label">Actual</span><span class="position-price">{actual_text}</span></div>
                <div class="position-label-item"><span class="position-label">Take Profit</span><span class="position-price">{take_profit_text}</span></div>
            </div>
            <div class="position-track">
                <div class="position-risk" style="left:{sl_pct:.2f}%;width:{risk_width:.2f}%;"></div>
                <div class="position-reward" style="left:{current_pct:.2f}%;width:{reward_width:.2f}%;"></div>
                <div class="position-marker marker-sl" style="left:{sl_pct:.2f}%;"></div>
                <div class="position-marker marker-entry" style="left:{entry_pct:.2f}%;"></div>
                <div class="position-marker marker-current" style="left:{current_pct:.2f}%;"></div>
                <div class="position-marker marker-tp" style="left:{tp_pct:.2f}%;"></div>
            </div>
        </div>
        """
    else:
        position_tracker = """
        <div class="position-wrapper">
            <div class="position-empty">Información de riesgo/objetivo no disponible.</div>
        </div>
        """

    analisis_ia_raw = row.get("Analisis_IA_Actual", "")
    if pd.isna(analisis_ia_raw) or not str(analisis_ia_raw).strip():
        analisis_ia_raw = row.get("Analisis_IA_Entrada", "")
    if pd.isna(analisis_ia_raw) or not str(analisis_ia_raw).strip():
        analisis_ia_raw = row.get("Analisis_IA", "")
    analisis_ia = formatear_tesis_ia(analisis_ia_raw)

    score = safe_float(row.get("Score_Entrada"), safe_float(row.get("Score_Actual")))
    score_html = (
        f"<div class='asset-score'><strong>{formatear_numero(score,0)}</strong><small>QUANT SCORE</small></div>"
        if score is not None else ""
    )

    card_class = "asset-card opportunity-card-landing" if compact else "asset-card"

    render_html(f"""
    <div class="{card_class}">
        {"<div class='example-alert-ribbon'>EJEMPLO ALERTA</div>" if ribbon else ""}
        <div class="asset-header">
            <div class="asset-left">
                {score_html}
                <div class="asset-identity">
                    <div class="asset-icon">{icono}</div>
                    <div>
                        <div class="asset-company">{empresa} <span class="asset-ticker">{ticker}</span></div>
                        <div class="asset-sector">{sector}</div>
                    </div>
                </div>
            </div>
            <div class="asset-right">
                <div class="current-price">{actual_text}</div>
                <div class="price-label">Precio actual</div>
            </div>
        </div>

        <div class="performance-row">
            <div class="performance-rr">
                <div class="performance-rr-label">Risk / Reward</div>
                <div class="performance-rr-value">{ratio_rr_text}</div>
            </div>
            <div class="performance-left">
                <div class="performance-label">Rendimiento desde entrada</div>
                <div class="performance-value {performance_class}">{performance_text}</div>
            </div>
        </div>

        {position_tracker}

        <div class="ai-box">
            <div class="ai-header">✦ Tesis del analista</div>
            <div class="ai-text">{analisis_ia}</div>
        </div>
    </div>
    """)


def render_equity_chart_svg(fechas, valores):
    """Gráfico de equity ligero y visual, sin depender de una librería adicional."""
    if not fechas or not valores or len(valores) < 2:
        return '<div class="equity-empty">Se requieren más operaciones para construir la curva.</div>'

    vals = [safe_float(v, 0) or 0 for v in valores]
    width, height = 1000, 330
    left, right, top, bottom = 56, 24, 24, 48
    plot_w = width - left - right
    plot_h = height - top - bottom
    vmin, vmax = min(vals), max(vals)
    if abs(vmax - vmin) < 1e-9:
        vmax += 1
        vmin -= 1
    pad = (vmax - vmin) * 0.10
    vmin -= pad
    vmax += pad

    points = []
    for i, value in enumerate(vals):
        x = left + (plot_w * i / max(1, len(vals)-1))
        y = top + (vmax - value) / (vmax - vmin) * plot_h
        points.append((x, y))

    path = " ".join(
        (f"M {x:.1f} {y:.1f}" if i == 0 else f"L {x:.1f} {y:.1f}")
        for i, (x, y) in enumerate(points)
    )
    area = f"M {points[0][0]:.1f} {height-bottom:.1f} " + " ".join(
        f"L {x:.1f} {y:.1f}" for x,y in points
    ) + f" L {points[-1][0]:.1f} {height-bottom:.1f} Z"

    grid = []
    for i in range(5):
        y = top + plot_h * i / 4
        val = vmax - (vmax-vmin) * i / 4
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" class="equity-grid"/>'
            f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end" class="equity-label">{formatear_numero(val,0," €")}</text>'
        )

    first_date = pd.to_datetime(fechas[0], errors="coerce")
    last_date = pd.to_datetime(fechas[-1], errors="coerce")
    date_a = first_date.strftime("%d/%m/%y") if pd.notna(first_date) else ""
    date_b = last_date.strftime("%d/%m/%y") if pd.notna(last_date) else ""

    final_value = vals[-1]
    final_color = "#16a34a" if final_value >= 0 else "#dc2626"

    return f"""
    <div class="equity-chart">
      <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" role="img" aria-label="Curva de resultados">
        {''.join(grid)}
        <path d="{area}" class="equity-area"/>
        <path d="{path}" class="equity-line"/>
        <circle cx="{points[-1][0]:.1f}" cy="{points[-1][1]:.1f}" r="6" class="equity-dot"/>
        <text x="{points[-1][0]-8:.1f}" y="{max(18,points[-1][1]-13):.1f}" text-anchor="end" class="equity-final" style="fill:{final_color}">{formatear_numero(final_value,0," €",True)}</text>
        <text x="{left}" y="{height-14}" class="equity-date">{date_a}</text>
        <text x="{width-right}" y="{height-14}" text-anchor="end" class="equity-date">{date_b}</text>
      </svg>
    </div>
    """



# ============================================================
# 01. INICIO
# ============================================================

with tab_inicio:
    render_html(f"""
      <section class="aq-hero">
        <h1>El mercado genera miles de señales.<br><span>Nosotros filtramos el ruido.</span></h1>
        <p>Algoritmos cuantitativos, análisis técnico e inteligencia artificial para detectar, puntuar y monitorizar oportunidades de mercado.</p>
        <div class="aq-actions">
          <a class="aq-btn primary" href="#oportunidad-demo">Ver una oportunidad →</a>
          <a class="aq-btn" href="#por-que-existe">Cómo funciona</a>
      </section>

      <section class="aq-kpis">
        <div class="aq-kpi">
          <div class="aq-kpi-label">Beneficio total</div>
          <div class="aq-kpi-value" style="color:{color_resultado};">{formatear_numero(beneficio_acumulado,2," €",True)}</div>
          <div class="aq-kpi-detail">Realizado + posiciones abiertas</div>
        </div>
        <div class="aq-kpi">
          <div class="aq-kpi-label">Rentabilidad</div>
          <div class="aq-kpi-value" style="color:{color_resultado};">{formatear_numero(rentabilidad_pct,2,"%",True)}</div>
          <div class="aq-kpi-detail">Sobre {formatear_numero(CAPITAL_INICIAL,0," €")}</div>
        </div>
        <div class="aq-kpi">
          <div class="aq-kpi-label">Posiciones activas</div>
          <div class="aq-kpi-value">{activas}</div>
          <div class="aq-kpi-detail">{TOTAL_ACTIVOS_UNIVERSO} activos monitorizados</div>
        </div>
        <div class="aq-kpi">
          <div class="aq-kpi-label">Win Rate</div>
          <div class="aq-kpi-value">{formatear_numero(win_rate,1,"%")}</div>
          <div class="aq-kpi-detail">{exitos} TP · {fallos} SL</div>
        </div>
      </section>

      <section class="aq-section" id="oportunidad-demo">
        <div class="aq-section-head">
          <div>
            <div class="aq-eyebrow">PRODUCTO</div>
            <h2>Una oportunidad, de un vistazo.</h2>
          </div>
        </div>
        <div class="aq-demo-wrap">
    """)

    # Preferimos BBVA para la demo; si no existe en los datos, usamos la primera señal disponible.
    _demo_rows = df_hist.copy()
    _bbva_mask = pd.Series(False, index=_demo_rows.index)
    if not _demo_rows.empty:
        _ticker_series = _demo_rows["Ticker"].astype(str).str.upper() if "Ticker" in _demo_rows.columns else pd.Series("", index=_demo_rows.index)
        _empresa_series = _demo_rows["Empresa"].astype(str).str.upper() if "Empresa" in _demo_rows.columns else pd.Series("", index=_demo_rows.index)
        _bbva_mask = _ticker_series.str.contains("A3M", na=False) | _empresa_series.str.contains("A3M", na=False)

    if _bbva_mask.any():
        _demo_row = _demo_rows[_bbva_mask].iloc[0]
    elif not df_activas_global.empty:
        _demo_row = df_activas_global.iloc[0]
    elif not df_hist.empty:
        _demo_row = df_hist.iloc[0]
    else:
        _demo_row = None

    if _demo_row is not None:
        render_opportunity_card(_demo_row, compact=True, ribbon=True)
    else:
        render_html("""
            <div class="empty-state">
              <div class="empty-title">Todavía no hay señales registradas</div>
              <div class="empty-text">Cuando Alura Quant genere señales aparecerá aquí un ejemplo real.</div>
            </div>
        """)

    render_html("""
        </div>
      </section>

      <section class="aq-section" id="por-que-existe">
        <div class="aq-section-head">
          <div>
            <div class="aq-eyebrow">POR QUÉ EXISTE</div>
            <h2>El problema no es encontrar información.</h2>
          </div>
          <p>Es decidir qué merece tu atención cuando el mercado produce más información de la que una persona puede procesar.</p>
        </div>
        <div class="aq-positioning">
          <div class="aq-positioning-card">
            <div class="aq-eyebrow">EL MERCADO</div>
            <h3>Demasiadas señales. Demasiado ruido.</h3>
            <p>Precio, volumen, momentum, volatilidad, rupturas y cientos de activos compiten por la misma atención.</p>
            <div class="aq-mini-list">
              <div><i></i> Miles de activos</div>
              <div><i></i> Múltiples variables técnicas</div>
              <div><i></i> Información que cambia constantemente</div>
            </div>
          </div>
          <div class="aq-positioning-card dark">
            <div class="aq-eyebrow" style="color:#7fb0ff;">ALURA QUANT</div>
            <h3>Filtrar primero. Analizar después.</h3>
            <p>El sistema reduce el universo mediante reglas cuantitativas y concentra la atención en las configuraciones que cumplen los criterios definidos.</p>
            <div class="aq-mini-list">
              <div><i></i> Liquidez y tendencia</div>
              <div><i></i> Momentum y volumen</div>
              <div><i></i> Score + tesis de IA</div>
            </div>
          </div>
        </div>
      </section>

      <section class="aq-section" style="padding-top:0;">
        <div class="aq-final-cta">
          <div class="aq-eyebrow">ALURA QUANT</div>
          <h2>El mercado no necesita más ruido.</h2>
          <p>Necesita mejores filtros. Explora el sistema y decide qué nivel de información quieres recibir.</p>
          <div class="aq-actions">
            <a class="aq-btn primary" href="#planes-top" onclick="(function(){var b=[...document.querySelectorAll('button[data-baseweb=\"tab\"]')].find(function(x){return x.innerText.trim()==='Planes';});if(b)b.click();})();" style="background:#fff;color:#0b1220;border-color:#fff;">Ver planes y suscripción →</a>
          </div>
        </div>
      </section>
    </div>
    """)

# ============================================================
# 02. OPORTUNIDADES
# ============================================================

with tab_oportunidades:
    render_html("""
    <div class="aq-wrap">
      <div class="aq-list-head">
        <div>
          <div class="aq-eyebrow">LIVE MARKET</div>
          <h2>Oportunidades activas</h2>
          <p>La lectura completa de cada configuración detectada por el sistema.</p>
        </div>
      </div>
    </div>
    """)
    if df_activas_global.empty:
        render_html("""
        <div class="aq-wrap">
          <div class="empty-state">
            <div class="empty-icon">◌</div>
            <div class="empty-title">No hay oportunidades activas</div>
            <div class="empty-text">Las nuevas señales aparecerán automáticamente en esta sección.</div>
          </div>
        </div>
        """)
    else:
        col_filtro_1, col_filtro_2 = st.columns([1, 1], gap="small")
        with col_filtro_1:
            sectores = sorted(df_activas_global["Sector"].dropna().astype(str).unique().tolist()) if "Sector" in df_activas_global.columns else []
            filtro_sector = st.selectbox("Sector", ["Todos los sectores"] + sectores, key="opp_sector")
        with col_filtro_2:
            busqueda = st.text_input("Buscar", placeholder="⌕  Buscar empresa o ticker...", key="opp_search")

        dfo = df_activas_global.copy()
        if filtro_sector != "Todos los sectores" and "Sector" in dfo.columns:
            dfo = dfo[dfo["Sector"].astype(str) == filtro_sector]
        if busqueda:
            q = busqueda.strip().lower()
            dfo = dfo[dfo.apply(
                lambda r: q in str(r.get("Ticker","")).lower() or q in str(r.get("Empresa","")).lower(),
                axis=1
            )]

        render_html(f'<div class="aq-wrap"><div class="opportunity-count">MOSTRANDO {len(dfo)} OPORTUNIDADES</div></div>')
        for _, row in dfo.iterrows():
            render_opportunity_card(row)


# ============================================================
# 03. CARTERA
# ============================================================

with tab_cartera:
    render_html("""
    <div class="aq-wrap">
      <div class="aq-list-head">
        <div>
          <div class="aq-eyebrow">PORTFOLIO</div>
          <h2>Cartera</h2>
          <p>Vista operativa de las posiciones activas monitorizadas.</p>
        </div>
      </div>
    </div>
    """)
    if df_activas_global.empty:
        render_html("<div class='aq-wrap'><div class='empty-state'><div class='empty-title'>No hay posiciones activas</div><div class='empty-text'>Las nuevas señales aparecerán automáticamente.</div></div></div>")
    else:
        cols = [c for c in ['Ticker','Empresa','Sector','Precio_Alerta','Precio_Actual','Stop_Loss','Take_Profit','Score_Actual','P&L_Actual_Pct','Estado_Estrategia'] if c in df_activas_global.columns]
        render_html("<div class='aq-wrap'><div class='aq-panel'><div class='aq-panel-title'>Posiciones monitorizadas</div><div class='aq-panel-sub'>Vista resumida de las operaciones abiertas.</div></div></div>")
        st.dataframe(df_activas_global[cols], use_container_width=True, hide_index=True)


# ============================================================
# 04. PERFORMANCE
# ============================================================

with tab_resultados:
    render_html(f"""
    <div class="aq-wrap">
      <div class="performance-page-head">
        <div>
          <div class="aq-eyebrow">PERFORMANCE</div>
          <h2>Resultados del sistema</h2>
          <p>Beneficio realizado y valoración actual de las posiciones abiertas.</p>
        </div>
        <div class="performance-total">
          <span>BENEFICIO TOTAL</span>
          <strong style="color:{color_resultado};">{formatear_numero(beneficio_acumulado,2," €",True)}</strong>
          <small>{formatear_numero(rentabilidad_pct,2,"%",True)} sobre {formatear_numero(CAPITAL_INICIAL,0," €")}</small>
        </div>
      </div>

      <div class="performance-kpis">
        <div class="performance-kpi">
          <span>Señales activas</span><strong>{activas}</strong><small>posiciones monitorizadas</small>
        </div>
        <div class="performance-kpi positive">
          <span>Posiciones en beneficio</span><strong>{posiciones_con_beneficio}</strong><small>de las posiciones abiertas</small>
        </div>
        <div class="performance-kpi positive">
          <span>Take Profit</span><strong>{exitos}</strong><small>objetivos alcanzados</small>
        </div>
        <div class="performance-kpi negative">
          <span>Stop Loss</span><strong>{fallos}</strong><small>stops ejecutados</small>
        </div>
        <div class="performance-kpi">
          <span>Win Rate</span><strong>{formatear_numero(win_rate,1,"%")}</strong><small>sobre operaciones cerradas</small>
        </div>
        <div class="performance-kpi">
          <span>Beneficio realizado</span><strong style="color:{'#16a34a' if beneficio_realizado >= 0 else '#dc2626'};">{formatear_numero(beneficio_realizado,2," €",True)}</strong><small>operaciones cerradas</small>
        </div>
      </div>

      <div class="performance-chart-card">
        <div class="performance-chart-head">
          <div>
            <div class="performance-chart-title">Curva acumulada</div>
            <div class="performance-chart-subtitle">Evolución del resultado registrado por el sistema</div>
          </div>
          <div class="chart-legend"><i></i> Resultado acumulado</div>
        </div>
        {render_equity_chart_svg(fechas_curva, beneficios_curva)}
        <div class="performance-chart-footer">
          <span>Realizado: <strong>{formatear_numero(beneficio_realizado,2," €",True)}</strong></span>
          <span>Abierto: <strong>{formatear_numero(beneficio_no_realizado,2," €",True)}</strong></span>
          <span>Capital de referencia: <strong>{formatear_numero(CAPITAL_INICIAL,0," €")}</strong></span>
        </div>
      </div>

      <div class="performance-disclaimer">
        Resultados históricos calculados a partir de las operaciones registradas. No constituyen una garantía de resultados futuros ni asesoramiento financiero.
      </div>
    </div>
    """)


# ============================================================
# 05. HISTÓRICO
# ============================================================

with tab_historial:
    render_html("""
    <div class="aq-wrap">
      <div class="aq-list-head">
        <div>
          <div class="aq-eyebrow">DATA</div>
          <h2>Histórico</h2>
          <p>Registro completo de señales y operaciones procesadas.</p>
        </div>
      </div>
    </div>
    """)
    if df_hist.empty:
        render_html("<div class='aq-wrap'><div class='empty-state'><div class='empty-title'>Todavía no hay señales registradas.</div></div></div>")
    else:
        cols = [c for c in ['Fecha','Ticker','Empresa','Score_Entrada','Precio_Alerta','Stop_Loss','Take_Profit','Estado','Resultado_R','Fecha_Salida'] if c in df_hist.columns]
        st.dataframe(df_hist.sort_values('Fecha', ascending=False)[cols], use_container_width=True, hide_index=True)


# ============================================================
# 06. PLANES
# ============================================================

with tab_planes:
    render_html("""
    <div class="aq-wrap" id="planes-top">
      <section class="aq-section center" style="padding-bottom:25px;">
        <div class="aq-eyebrow">ALURA QUANT MEMBERSHIP</div>
        <h2>Elige cómo quieres utilizar Alura Quant.</h2>
        <p class="aq-section-intro">Empieza gratis para conocer la plataforma o accede a Pro cuando quieras profundizar en las oportunidades y el análisis.</p>

        <div class="aq-pricing-grid" id="planes-top">
          <div class="aq-price">
            <div class="aq-price-badge">FREE</div>
            <h3>Explora Alura Quant</h3>
            <div class="aq-price-num">0 € <span>/ mes</span></div>
            <p>Una forma sencilla de conocer la plataforma y seguir una selección del sistema.</p>
            <ul>
              <li>✓ Acceso al dashboard</li>
              <li>✓ Resumen de mercado</li>
              <li>✓ Señales seleccionadas</li>
              <li>✓ Métricas cuantitativas básicas</li>
            </ul>
          </div>

          <div class="aq-price pro">
            <div class="aq-price-badge">PRO</div>
            <h3>Alura Quant Pro</h3>
            <div class="aq-price-num">19 € <span>/ mes</span></div>
            <p>Para acceder a las oportunidades de mayor convicción y al análisis completo.</p>
            <ul>
              <li>✓ Alertas con Score &gt; 80</li>
              <li>✓ Envío prioritario</li>
              <li>✓ Tesis cuantitativa + IA</li>
              <li>✓ Histórico de tesis detalladas</li>
              <li>✓ Informe semanal</li>
            </ul>
          </div>
        </div>
      </section>
    </div>
    """)

    col_free, col_vip = st.columns(2, gap="large")

    with col_free:
        st.markdown("### Crear acceso gratuito")
        email_free = st.text_input("Email", placeholder="tu@email.com", key="landing_free_email", label_visibility="collapsed")
        if st.button("Crear acceso Free", use_container_width=True, key="landing_free_button"):
            resultado = guardar_suscriptor_supabase(email_free, "free")
            if resultado == "success":
                st.success("Registro completado. Ya formas parte de Alura Quant Free.")
            elif resultado == "exists":
                st.info("Este email ya está registrado en Free.")
            elif resultado == "invalid":
                st.error("Introduce un email válido.")
            else:
                st.error("No hemos podido completar el registro.")

    with col_vip:
        st.markdown("### Activar Alura Quant Pro")
        email_vip = st.text_input("Email Pro", placeholder="El email que usarás para tu suscripción", key="landing_vip_email", label_visibility="collapsed")
        url_stripe = os.getenv("STRIPE_PAYMENT_LINK", "").strip()

        if st.button("Continuar con Pro · 19 €/mes", use_container_width=True, type="primary", key="landing_vip_button"):
            resultado = guardar_suscriptor_supabase(email_vip, "vip")
            if resultado in ("success", "exists"):
                if url_stripe:
                    url_segura = html.escape(url_stripe, quote=True)
                    render_html(f"<div class='aq-actions' style='margin-top:12px;'><a class='aq-btn primary' href='{url_segura}' target='_blank' rel='noopener noreferrer'>Continuar al pago seguro →</a></div>")
                st.success("Email preparado para Pro. Completa el pago en Stripe." if resultado == "success" else "Este email ya estaba preparado. Puedes continuar al pago.")
            elif resultado == "invalid":
                st.error("Introduce un email válido.")
            else:
                st.error("No hemos podido preparar tu suscripción.")

    render_html("""
    <div class="aq-wrap">
      <div class="aq-note"><strong>Suscripción:</strong> el registro en <code>suscriptores_vip</code> no confirma por sí solo un pago. En producción, el estado Pro debería activarse mediante un webhook de Stripe después de confirmar el pago.</div>
    </div>
    """)


# ============================================================
# FOOTER
# ============================================================

render_html(f"""
<div class="aq-wrap">
  <div class="aq-footer">
    <span>Última actualización: <strong>{html.escape(fecha_actualizacion_sistema)}</strong></span>
  </div>
</div>
""")
