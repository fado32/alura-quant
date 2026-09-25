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
        25px;

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
.asset-score{display:block;margin-top:9px;text-align:right}
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
# LANDING / APP CSS
# ------------------------------------------------------------
render_html("""
<style>
:root{
    --aq-bg:#f6f8fb; --aq-surface:#fff; --aq-text:#0f172a; --aq-muted:#64748b;
    --aq-border:#e5eaf1; --aq-blue:#2563eb; --aq-blue-dark:#1d4ed8;
    --aq-blue-soft:#eff6ff; --aq-green:#16a34a; --aq-red:#dc2626;
    --aq-shadow:0 18px 55px rgba(15,23,42,.07);
}
.aq-wrap{max-width:1240px;margin:0 auto}.aq-eyebrow{font-size:12px;letter-spacing:.16em;font-weight:800;color:var(--aq-blue);text-transform:uppercase;margin-bottom:14px}
.aq-hero{padding:54px 0 34px;position:relative;overflow:hidden}.aq-hero:before{content:"";position:absolute;inset:-140px 15% auto;height:360px;background:radial-gradient(circle,rgba(37,99,235,.12),transparent 68%);pointer-events:none}
.aq-hero-grid{display:grid;grid-template-columns:1.03fr .97fr;gap:48px;align-items:center;position:relative}.aq-hero h1{font-family:'Plus Jakarta Sans',sans-serif;font-size:clamp(42px,5.5vw,72px);line-height:1.02;letter-spacing:-.055em;margin:0 0 22px;color:#0b1220;font-weight:800}.aq-hero h1 span{color:var(--aq-blue)}.aq-hero p{font-size:19px;line-height:1.65;color:var(--aq-muted);max-width:650px;margin:0 0 28px}.aq-actions{display:flex;gap:12px;flex-wrap:wrap}.aq-btn{display:inline-flex;align-items:center;justify-content:center;padding:13px 19px;border-radius:12px;font-weight:700;text-decoration:none;border:1px solid var(--aq-border);background:#fff;color:var(--aq-text);box-shadow:0 3px 12px rgba(15,23,42,.04)}.aq-btn.primary{background:var(--aq-blue);border-color:var(--aq-blue);color:#fff}.aq-btn.primary:hover{background:var(--aq-blue-dark)}
.aq-terminal{background:#0b1220;border:1px solid #1e293b;border-radius:22px;padding:20px;box-shadow:var(--aq-shadow);color:#e2e8f0}.aq-terminal-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;color:#94a3b8;font-size:12px}.aq-live{display:inline-flex;gap:7px;align-items:center}.aq-live i{width:7px;height:7px;border-radius:50%;background:#22c55e;display:inline-block}.aq-scan{font-family:'Plus Jakarta Sans',sans-serif;font-size:28px;font-weight:800;margin-bottom:3px}.aq-terminal-muted{color:#94a3b8;font-size:12px}.aq-mini-row{display:grid;grid-template-columns:1fr 70px 64px;gap:12px;align-items:center;padding:13px 0;border-top:1px solid #1e293b}.aq-mini-ticker{font-weight:700}.aq-mini-score{font-weight:800;text-align:right}.aq-mini-state{font-size:12px;text-align:right;color:#4ade80}.aq-mini-bar{height:5px;background:#1e293b;border-radius:99px;overflow:hidden;margin-top:7px}.aq-mini-bar span{display:block;height:100%;background:#60a5fa;border-radius:99px}
.aq-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--aq-border);border:1px solid var(--aq-border);border-radius:18px;overflow:hidden;margin:28px 0 76px}.aq-stat{background:#fff;padding:25px 22px}.aq-stat-value{font-family:'Plus Jakarta Sans',sans-serif;font-size:30px;font-weight:800;letter-spacing:-.03em}.aq-stat-label{font-size:13px;color:var(--aq-muted);margin-top:5px}.aq-section{padding:34px 0 82px}.aq-section.center{text-align:center}.aq-section h2{font-family:'Plus Jakarta Sans',sans-serif;font-size:clamp(30px,4vw,46px);letter-spacing:-.045em;line-height:1.08;margin:0 0 16px}.aq-section-intro{color:var(--aq-muted);font-size:17px;line-height:1.7;max-width:700px;margin:0 auto 38px}.aq-problem{display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:stretch}.aq-problem-card{background:#fff;border:1px solid var(--aq-border);border-radius:20px;padding:32px;box-shadow:0 8px 28px rgba(15,23,42,.035)}.aq-problem-card h3{font-family:'Plus Jakarta Sans',sans-serif;font-size:23px;margin:0 0 13px}.aq-problem-card p{color:var(--aq-muted);line-height:1.7;margin:0}.aq-problem-card.accent{background:linear-gradient(145deg,#0f172a,#172554);color:#fff;border-color:#172554}.aq-problem-card.accent p{color:#cbd5e1}
.aq-flow{display:grid;grid-template-columns:repeat(7,1fr);gap:8px;align-items:center}.aq-flow-item{background:#fff;border:1px solid var(--aq-border);border-radius:16px;padding:19px 12px;text-align:center;min-height:100px;display:flex;flex-direction:column;justify-content:center}.aq-flow-item strong{font-size:14px}.aq-flow-item span{font-size:11px;color:var(--aq-muted);margin-top:6px}.aq-arrow{text-align:center;color:#94a3b8;font-size:20px}
.aq-engine{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.aq-engine-card{background:#fff;border:1px solid var(--aq-border);border-radius:18px;padding:24px;min-height:190px}.aq-engine-number{font-size:12px;color:var(--aq-blue);font-weight:800;letter-spacing:.12em}.aq-engine-card h3{font-family:'Plus Jakarta Sans',sans-serif;margin:14px 0 9px;font-size:19px}.aq-engine-card p{font-size:14px;color:var(--aq-muted);line-height:1.65;margin:0}
.aq-opportunity{display:grid;grid-template-columns:1.1fr .9fr;gap:22px}.aq-op-card{background:#fff;border:1px solid var(--aq-border);border-radius:22px;padding:28px;box-shadow:var(--aq-shadow)}.aq-op-head{display:flex;justify-content:space-between;gap:15px;align-items:flex-start}.aq-ticker{font-family:'Plus Jakarta Sans',sans-serif;font-size:28px;font-weight:800}.aq-company{font-size:13px;color:var(--aq-muted);margin-top:4px}.aq-score{font-family:'Plus Jakarta Sans',sans-serif;font-size:30px;font-weight:800;color:var(--aq-blue);text-align:right}.aq-score small{display:block;font-size:10px;letter-spacing:.12em;color:#94a3b8}.aq-op-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:24px 0}.aq-metric{background:#f8fafc;border-radius:12px;padding:12px}.aq-metric label{display:block;color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:.08em}.aq-metric strong{display:block;margin-top:5px;font-size:15px}.aq-bar{height:7px;background:#e8edf4;border-radius:99px;position:relative;margin:28px 0 20px}.aq-bar:before{content:"";position:absolute;left:0;top:0;height:100%;width:36%;background:#ef4444;border-radius:99px}.aq-bar:after{content:"";position:absolute;right:0;top:0;height:100%;width:22%;background:#22c55e;border-radius:99px}.aq-op-copy{color:var(--aq-muted);line-height:1.7;font-size:14px}.aq-ai{background:#0f172a;color:#fff;border-radius:22px;padding:30px}.aq-ai .aq-eyebrow{color:#60a5fa}.aq-ai h3{font-family:'Plus Jakarta Sans',sans-serif;font-size:26px;margin:0 0 15px}.aq-ai p{color:#cbd5e1;line-height:1.75}.aq-ai-state{display:inline-flex;border:1px solid #334155;border-radius:99px;padding:7px 11px;color:#86efac;font-size:12px;font-weight:700;margin-bottom:18px}
.aq-steps{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.aq-step{padding:26px;border:1px solid var(--aq-border);background:#fff;border-radius:18px}.aq-step strong{font-family:'Plus Jakarta Sans',sans-serif;font-size:16px}.aq-step p{font-size:14px;color:var(--aq-muted);line-height:1.65}.aq-cta{background:linear-gradient(135deg,#0f172a,#1d4ed8);border-radius:26px;color:#fff;padding:58px 45px;text-align:center;box-shadow:var(--aq-shadow)}.aq-cta h2{margin-bottom:12px}.aq-cta p{color:#dbeafe;max-width:650px;margin:0 auto 24px;line-height:1.7}.aq-cta .aq-btn{background:#fff;color:#0f172a;border-color:#fff}
.aq-pricing-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;max-width:940px;margin:0 auto}.aq-price{background:#fff;border:1px solid var(--aq-border);border-radius:22px;padding:30px}.aq-price.pro{border:2px solid var(--aq-blue);box-shadow:0 18px 50px rgba(37,99,235,.12)}.aq-price-badge{font-size:11px;font-weight:800;letter-spacing:.14em;color:var(--aq-blue)}.aq-price h3{font-family:'Plus Jakarta Sans',sans-serif;font-size:25px;margin:10px 0}.aq-price-num{font-family:'Plus Jakarta Sans',sans-serif;font-size:38px;font-weight:800}.aq-price-num span{font-family:'DM Sans',sans-serif;font-size:13px;color:var(--aq-muted);font-weight:500}.aq-price p{color:var(--aq-muted);line-height:1.6}.aq-price ul{padding:0;margin:20px 0 24px;list-style:none}.aq-price li{padding:8px 0;color:#334155;font-size:14px}.aq-sub-box{margin-top:20px;padding-top:20px;border-top:1px solid var(--aq-border)}
.aq-note{font-size:12px;color:#64748b;line-height:1.6;margin-top:14px}.aq-footer{border-top:1px solid var(--aq-border);padding:24px 0 10px;color:#94a3b8;font-size:12px;display:flex;justify-content:space-between;gap:15px}
.aq-dashboard-head{display:flex;justify-content:space-between;align-items:end;gap:20px;margin:25px 0}.aq-dashboard-head h2{font-family:'Plus Jakarta Sans',sans-serif;font-size:34px;letter-spacing:-.04em;margin:0}.aq-dashboard-head p{color:var(--aq-muted);margin:6px 0 0}.aq-panel{background:#fff;border:1px solid var(--aq-border);border-radius:18px;padding:22px;margin-bottom:18px}.aq-panel-title{font-family:'Plus Jakarta Sans',sans-serif;font-size:18px;font-weight:700;margin-bottom:5px}.aq-panel-sub{font-size:13px;color:var(--aq-muted);margin-bottom:18px}
@media(max-width:900px){.aq-hero-grid,.aq-problem,.aq-opportunity{grid-template-columns:1fr}.aq-stats{grid-template-columns:repeat(2,1fr)}.aq-engine{grid-template-columns:repeat(2,1fr)}.aq-flow{grid-template-columns:1fr}.aq-arrow{display:none}.aq-pricing-grid{grid-template-columns:1fr}.aq-hero{padding-top:30px}}
@media(max-width:600px){.aq-stats,.aq-engine,.aq-steps{grid-template-columns:1fr}.aq-hero h1{font-size:42px}.aq-op-metrics{grid-template-columns:repeat(2,1fr)}.aq-footer{flex-direction:column}.block-container{padding-left:18px;padding-right:18px}}
</style>
""")

# ------------------------------------------------------------
# NAV
# ------------------------------------------------------------
render_html(f"""
<div class='aq-wrap' id='top'>
  <div style='display:flex;justify-content:space-between;align-items:center;padding:8px 0 14px;border-bottom:1px solid #e5eaf1;'>
    <div style='font-family:Plus Jakarta Sans,sans-serif;font-weight:800;letter-spacing:-.04em;font-size:20px;'>ALURA <span style='color:#2563eb;'>QUANT</span></div>
    <div style='font-size:12px;color:#64748b;'>INVESTMENT INTELLIGENCE · ACTUALIZADO {html.escape(fecha_actualizacion_sistema)}</div>
  </div>
</div>
""")

# ------------------------------------------------------------
# TABS DE PRODUCTO
# ------------------------------------------------------------
tab_inicio, tab_oportunidades, tab_cartera, tab_resultados, tab_historial, tab_planes = st.tabs([
    "Inicio", "Oportunidades", "Cartera", "Resultados", "Histórico", "Planes"
])

# ------------------------------------------------------------
# ------------------------------------------------------------
# SHARED UI — OPPORTUNITY CARD
# ------------------------------------------------------------

def render_opportunity_card(row, compact=False):
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
        f"<span class='asset-score'><strong>{formatear_numero(score,0)}</strong><small>QUANT SCORE</small></span>"
        if score is not None else ""
    )

    card_class = "asset-card opportunity-card-landing" if compact else "asset-card"

    render_html(f"""
    <div class="{card_class}">
        <div class="asset-header">
            <div class="asset-left">
                <div class="asset-new-row">{badge_nuevo}</div>
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
                {score_html}
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
# NAVEGACIÓN
# ============================================================

tab_inicio, tab_oportunidades, tab_cartera, tab_resultados, tab_historial, tab_planes = st.tabs([
    "Inicio", "Oportunidades", "Cartera", "Resultados", "Histórico", "Planes"
])


# ============================================================
# 01. INICIO
# ============================================================

with tab_inicio:
    render_html(f"""
    <div class="aq-wrap" id="top">
      <section class="hero-v2">
        <div>
          <div class="hero-eyebrow">ALURA QUANT · INVESTMENT INTELLIGENCE</div>
          <h1 class="hero-title">El mercado genera miles de señales.<br><span>Nosotros filtramos el ruido.</span></h1>
          <p class="hero-subtitle">Algoritmos cuantitativos, análisis técnico e inteligencia artificial para detectar, puntuar y monitorizar oportunidades de mercado.</p>
          <div class="hero-actions">
            <a class="hero-btn primary" href="#planes-top">Explorar Alura Quant →</a>
            <a class="hero-btn secondary" href="#motor">Cómo funciona</a>
          </div>
        </div>
        <div class="hero-orbit">
          <div class="orbit-line"></div>
          <div class="orbit-card"><span>QUANT SCORE</span><strong>{formatear_numero(safe_float(df_activas_global.iloc[0].get("Score_Entrada"), safe_float(df_activas_global.iloc[0].get("Score_Actual"), 0)),0) if not df_activas_global.empty else "—"}</strong><small>OPORTUNIDAD ACTIVA</small></div>
        </div>
      </section>

      <section class="portfolio-summary aq-home-stats">
        <div class="summary-card"><div class="summary-label">Beneficio total</div><div class="summary-value" style="color:{color_resultado};">{formatear_numero(beneficio_acumulado,2," €",True)}</div><div class="summary-detail">Realizado + abierto</div></div>
        <div class="summary-card"><div class="summary-label">Rentabilidad</div><div class="summary-value" style="color:{color_resultado};">{formatear_numero(rentabilidad_pct,2,"%",True)}</div><div class="summary-detail">Sobre {formatear_numero(CAPITAL_INICIAL,0," €")}</div></div>
        <div class="summary-card"><div class="summary-label">Posiciones activas</div><div class="summary-value">{activas}</div><div class="summary-detail">{TOTAL_ACTIVOS_UNIVERSO} activos monitorizados</div></div>
        <div class="summary-card"><div class="summary-label">Win Rate</div><div class="summary-value">{formatear_numero(win_rate,1,"%")}</div><div class="summary-detail">{exitos} TP · {fallos} SL</div></div>
      </section>

      <section class="aq-section" id="ejemplo">
        <div class="section-header">
          <div><div class="section-title">Así se presenta una señal</div><div class="section-subtitle">Entrada, riesgo, objetivo, evolución y tesis de IA en una única ficha.</div></div>
        </div>
    </div>
    """)

    demo = df_activas_global.iloc[0] if not df_activas_global.empty else (df_hist.iloc[0] if not df_hist.empty else None)
    if demo is not None:
        render_opportunity_card(demo, compact=True)
    else:
        render_html('<div class="aq-wrap"><div class="empty-state"><div class="empty-title">Todavía no hay señales registradas</div><div class="empty-text">Cuando Alura Quant genere señales aparecerá aquí un ejemplo real.</div></div></div>')

    render_html("""
    <div class="aq-wrap">
      <section class="aq-section center" id="motor">
        <div class="aq-eyebrow">EL MOTOR QUANT</div>
        <h2>Un proceso sistemático para filtrar el mercado.</h2>
        <div class="aq-engine-labels">
          <div><span>01</span> QUANT</div>
          <div><span>02</span> FILTERS</div>
          <div><span>03</span> SCORE</div>
          <div><span>04</span> AI THESIS</div>
        </div>
      </section>

      <section class="aq-section center">
        <div class="aq-eyebrow">CÓMO FUNCIONA</div>
        <h2>Del mercado completo a unas pocas oportunidades.</h2>
        <p class="aq-section-intro">Analizamos el universo, aplicamos filtros cuantitativos, puntuamos cada configuración y utilizamos IA para convertir el contexto en una tesis comprensible y monitorizable.</p>
        <div class="aq-flow">
          <div class="aq-flow-item"><strong>Mercado</strong><span>universo de activos</span></div><div class="aq-arrow">→</div>
          <div class="aq-flow-item"><strong>Filtros</strong><span>liquidez y tendencia</span></div><div class="aq-arrow">→</div>
          <div class="aq-flow-item"><strong>Quant Score</strong><span>factores técnicos</span></div><div class="aq-arrow">→</div>
          <div class="aq-flow-item"><strong>AI Thesis</strong><span>contexto y seguimiento</span></div>
        </div>
      </section>

      <section class="aq-section center">
        <div class="aq-eyebrow">INTELIGENCIA ARTIFICIAL</div>
        <h2>La IA convierte los datos en una tesis.</h2>
        <p class="aq-section-intro">La hipótesis inicial se contrasta con la evolución de la operación para entender si el contexto se mantiene, se refuerza, se debilita o se invalida.</p>
        <div class="aq-ai-process">
          <div>DATOS</div><span>→</span><div>QUANT SCORE</div><span>→</span><div>AI THESIS</div><span>→</span><div>MONITORIZACIÓN</div>
        </div>
      </section>

      <section class="aq-section center">
        <div class="aq-eyebrow">TRANSPARENCIA</div>
        <h2>El sistema muestra el proceso.</h2>
        <p class="aq-section-intro">Alura Quant no elimina el riesgo del mercado. Hace visible la información que hay detrás de cada oportunidad para que puedas evaluar el contexto por ti mismo.</p>
        <div class="aq-steps">
          <div class="aq-step"><strong>01 · Detectar</strong><p>El motor analiza el universo y encuentra configuraciones que cumplen los filtros.</p></div>
          <div class="aq-step"><strong>02 · Entender</strong><p>El Quant Score y la tesis explican por qué una oportunidad ha pasado el filtro.</p></div>
          <div class="aq-step"><strong>03 · Monitorizar</strong><p>La operación continúa evolucionando y el sistema actualiza su estado.</p></div>
        </div>
      </section>

      <section class="aq-section" id="planes">
        <div class="aq-cta"><div class="aq-eyebrow" style="color:#93c5fd;">ALURA QUANT</div><h2>El mercado no necesita más ruido.</h2><p>Necesita mejores filtros. Explora el sistema y decide qué nivel de información quieres recibir.</p><a class="aq-btn" href="#planes-top">Ver planes y suscripción →</a></div>
      </section>
    </div>
    """)


# ============================================================
# 02. OPORTUNIDADES
# ============================================================

with tab_oportunidades:
    render_html("""
    <div class="section-header">
      <div>
        <div class="section-title">Oportunidades activas</div>
        <div class="section-subtitle">Cada ficha muestra la misma lectura visual de riesgo, objetivo y tesis que utilizamos en la cartera.</div>
      </div>
    </div>
    """)

    if df_activas_global.empty:
        render_html("""
        <div class="empty-state">
          <div class="empty-icon">◌</div>
          <div class="empty-title">No hay oportunidades activas</div>
          <div class="empty-text">Las nuevas señales aparecerán automáticamente en esta sección.</div>
        </div>
        """)
    else:
        col_filtro_1, col_filtro_2 = st.columns([1,1], gap="small")
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

        render_html(f'<div class="opportunity-count">MOSTRANDO {len(dfo)} OPORTUNIDADES</div>')
        for _, row in dfo.iterrows():
            render_opportunity_card(row)


# ============================================================
# 03. CARTERA
# ------------------------------------------------------------
with tab_cartera:
    render_html("<div class='aq-dashboard-head'><div><h2>Cartera</h2><p>Vista operativa de las posiciones activas monitorizadas.</p></div></div>")
    if df_activas_global.empty:
        st.info("No hay posiciones activas.")
    else:
        cols=[c for c in ['Ticker','Empresa','Sector','Precio_Alerta','Precio_Actual','Stop_Loss','Take_Profit','Score_Actual','P&L_Actual_Pct','Estado_Estrategia'] if c in df_activas_global.columns]
        st.dataframe(df_activas_global[cols],use_container_width=True,hide_index=True)

# ------------------------------------------------------------
# 04. PERFORMANCE
# ------------------------------------------------------------

with tab_resultados:
    render_html(f"""
    <div class="aq-wrap">
      <div class="performance-page-head">
        <div>
          <div class="aq-eyebrow">PERFORMANCE</div>
          <h2>Resultados del sistema</h2>
          <p>Beneficio realizado + valoración actual de las posiciones abiertas.</p>
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
            <div class="performance-chart-title">Evolución de beneficios</div>
            <div class="performance-chart-subtitle">Curva acumulada del resultado del sistema</div>
          </div>
          <div class="chart-legend"><i></i> Equity curve</div>
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

# 05. HISTÓRICO
# ------------------------------------------------------------
with tab_historial:
    render_html("<div class='aq-dashboard-head'><div><h2>Histórico</h2><p>Registro completo de señales y operaciones procesadas.</p></div></div>")
    if df_hist.empty:
        st.info("Todavía no hay señales registradas.")
    else:
        cols=[c for c in ['Fecha','Ticker','Empresa','Score_Entrada','Precio_Alerta','Stop_Loss','Take_Profit','Estado','Resultado_R','Fecha_Salida'] if c in df_hist.columns]
        st.dataframe(df_hist.sort_values('Fecha',ascending=False)[cols],use_container_width=True,hide_index=True)

# ------------------------------------------------------------
# 06. PLANES Y SUSCRIPCIÓN
# ------------------------------------------------------------
with tab_planes:
    render_html("""
    <div class='aq-wrap' id='planes-top'>
      <section class='aq-section center'>
        <div class='aq-eyebrow'>ALURA QUANT MEMBERSHIP</div>
        <h2>Elige cómo quieres utilizar Alura Quant.</h2>
        <p class='aq-section-intro'>Empieza gratis para conocer el sistema o accede a las funciones Pro cuando quieras profundizar en las oportunidades y el análisis.</p>
        <div class='aq-pricing-grid'>
          <div class='aq-price'><div class='aq-price-badge'>FREE</div><h3>Explora Alura Quant</h3><div class='aq-price-num'>0 € <span>/ mes</span></div><p>Una forma sencilla de conocer la plataforma y seguir una selección del sistema.</p><ul><li>✓ Acceso al dashboard</li><li>✓ Resumen de mercado</li><li>✓ Señales seleccionadas</li><li>✓ Métricas cuantitativas básicas</li></ul></div>
          <div class='aq-price pro'><div class='aq-price-badge'>PRO</div><h3>Alura Quant Pro</h3><div class='aq-price-num'>19 € <span>/ mes</span></div><p>Para acceder a las oportunidades de mayor convicción y al análisis completo.</p><ul><li>✓ Alertas con Score &gt; 80</li><li>✓ Envío prioritario</li><li>✓ Tesis cuantitativa + IA</li><li>✓ Histórico de tesis detalladas</li><li>✓ Informe semanal</li></ul></div>
        </div>
      </section>
    </div>
    """)
    col_free,col_vip=st.columns(2,gap='large')
    with col_free:
        st.markdown('### Crear acceso gratuito')
        email_free=st.text_input('Email',placeholder='tu@email.com',key='landing_free_email',label_visibility='collapsed')
        if st.button('Crear acceso Free',use_container_width=True,key='landing_free_button'):
            resultado=guardar_suscriptor_supabase(email_free,'free')
            if resultado=='success': st.success('Registro completado. Ya formas parte de Alura Quant Free.')
            elif resultado=='exists': st.info('Este email ya está registrado en Free.')
            elif resultado=='invalid': st.error('Introduce un email válido.')
            else: st.error('No hemos podido completar el registro.')
    with col_vip:
        st.markdown('### Activar Alura Quant Pro')
        email_vip=st.text_input('Email Pro',placeholder='El email que usarás para tu suscripción',key='landing_vip_email',label_visibility='collapsed')
        url_stripe=os.getenv('STRIPE_PAYMENT_LINK','').strip()
        if st.button('Continuar con Pro · 19 €/mes',use_container_width=True,type='primary',key='landing_vip_button'):
            resultado=guardar_suscriptor_supabase(email_vip,'vip')
            if resultado in ('success','exists'):
                if url_stripe:
                    url_segura=html.escape(url_stripe,quote=True)
                    render_html(f"<div class='aq-actions' style='margin-top:12px;'><a class='aq-btn primary' href='{url_segura}' target='_blank' rel='noopener noreferrer'>Continuar al pago seguro →</a></div>")
                st.success('Email preparado para Pro. Completa el pago en Stripe.' if resultado=='success' else 'Este email ya estaba preparado. Puedes continuar al pago.')
            elif resultado=='invalid': st.error('Introduce un email válido.')
            else: st.error('No hemos podido preparar tu suscripción.')
    render_html("<div class='aq-note'><strong>Importante:</strong> el registro del email en <code>suscriptores_vip</code> no confirma por sí solo un pago. Para producción, el estado de Pro debería activarse mediante un webhook de Stripe que actualice Supabase tras confirmar el pago.</div>")

# ------------------------------------------------------------
# FOOTER
# ------------------------------------------------------------
render_html(f"""
<div class='aq-wrap'><div class='aq-footer'><span>ALURA QUANT · INVESTMENT INTELLIGENCE</span><span>Última actualización: <strong>{html.escape(fecha_actualizacion_sistema)}</strong></span></div></div>
""")
