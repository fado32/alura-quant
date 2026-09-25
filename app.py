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
# ANCLA SUPERIOR
# ============================================================

render_html(
    """
<div id="top"></div>
""",
    unsafe_allow_html=True,
)


# ============================================================
# HERO
# ============================================================

render_html(
    """
<div class="hero hero-v2">
    <div class="hero-copy">
        <div class="hero-eyebrow">ALURA QUANT · INVESTMENT INTELLIGENCE</div>
        <h1 class="hero-title">
            Inteligencia cuantitativa<br>para encontrar oportunidades.
        </h1>
        <div class="hero-subtitle">
            Monitorizamos el mercado, filtramos el ruido y combinamos métricas cuantitativas con IA para detectar y seguir oportunidades de inversión.
        </div>
        <div class="hero-actions">
            <a href="#oportunidades" class="hero-btn primary">Explorar oportunidades →</a>
            <a href="#metodologia" class="hero-btn secondary">Cómo funciona</a>
        </div>
    </div>
    <div class="hero-orbit" aria-hidden="true">
        <div class="orbit-card"><span>QUANT SCORE</span><strong>82</strong><small>Alta convicción</small></div>
        <div class="orbit-line"></div>
    </div>
</div>
""",
    unsafe_allow_html=True,
)


# ============================================================
# PORTFOLIO SUMMARY
# ============================================================

render_html(
    f"""
<div class="portfolio-summary">

    <div class="summary-card">

        <div class="summary-label">
            Beneficio total
        </div>

        <div
            class="summary-value"
            style="color:{color_resultado};"
        >
            {formatear_numero(
                beneficio_acumulado,
                2,
                " €",
                True
            )}
        </div>

        <div class="summary-detail">
            Realizado + abierto
        </div>

    </div>


    <div class="summary-card">

        <div class="summary-label">
            Rentabilidad
        </div>

        <div
            class="summary-value"
            style="color:{color_resultado};"
        >
            {formatear_numero(
                rentabilidad_pct,
                2,
                "%",
                True
            )}
        </div>

        <div class="summary-detail">
            Sobre {formatear_numero(
                CAPITAL_INICIAL,
                0,
                " €"
            )}
        </div>

    </div>


    <div class="summary-card">

        <div class="summary-label">
            Posiciones activas
        </div>

        <div class="summary-value">
            {activas}
        </div>

        <div class="summary-detail">
            {TOTAL_ACTIVOS_UNIVERSO} activos monitorizados
        </div>

    </div>


    <div class="summary-card">

        <div class="summary-label">
            Win Rate
        </div>

        <div class="summary-value">
            {formatear_numero(
                win_rate,
                1,
                "%"
            )}
        </div>

        <div class="summary-detail">
            {exitos} TP · {fallos} SL
        </div>

    </div>

</div>
""",
    unsafe_allow_html=True,
)


# ============================================================
# SI NO HAY DATOS
# ============================================================

if df_hist.empty:

    render_html(
        """
<div class="empty-state">

    <div class="empty-icon">
        ◌
    </div>

    <div class="empty-title">
        Todavía no hay señales registradas
    </div>

    <div class="empty-text">
        Cuando Alura Quant genere señales aparecerán aquí.
    </div>

</div>
""",
        unsafe_allow_html=True,
    )

    st.stop()


# ============================================================
# NAVEGACIÓN
# ============================================================

tab_cartera, tab_resultados, tab_historial, tab_planes = st.tabs(
    [
        "Cartera",
        "Resultados",
        "Histórico",
        "Planes y Suscripción"
    ]
)


# ============================================================
# 1. CARTERA
# ============================================================

with tab_cartera:

    render_html(
        """
<div id="oportunidades"></div>
<div class="section-header">

    <div>

        <div class="section-title">
            Posiciones activas
        </div>

        <div class="section-subtitle">
            Señales actualmente monitorizadas por el sistema cuantitativo.
        </div>

    </div>

</div>
""",
        unsafe_allow_html=True,
    )


    df_activas = df_activas_global.copy()


    if df_activas.empty:

        render_html(
            """
<div class="empty-state">

    <div class="empty-icon">
        ◌
    </div>

    <div class="empty-title">
        No hay posiciones activas
    </div>

    <div class="empty-text">
        Las nuevas señales aparecerán automáticamente en esta sección.
    </div>

</div>
""",
            unsafe_allow_html=True,
        )

    else:

        # ----------------------------------------------------
        # FILTROS
        # ----------------------------------------------------

        col_filtro_1, col_filtro_2 = st.columns(
            [1, 1],
            gap="small"
        )

        with col_filtro_1:

            if "Sector" in df_activas.columns:

                sectores = (
                    df_activas["Sector"]
                    .dropna()
                    .astype(str)
                    .unique()
                    .tolist()
                )

                sectores = sorted(
                    sectores
                )

            else:

                sectores = []

            sectores_disponibles = [
                "Todos los sectores"
            ] + sectores

            filtro_sector = st.selectbox(
                "Sector",
                sectores_disponibles,
                label_visibility="collapsed"
            )


        with col_filtro_2:

            busqueda_cartera = st.text_input(
                "Buscar",
                placeholder="⌕  Buscar empresa o ticker...",
                label_visibility="collapsed"
            )


        # ----------------------------------------------------
        # FILTRAR
        # ----------------------------------------------------

        df_filtrada = (
            df_activas.copy()
        )


        if (
            filtro_sector
            != "Todos los sectores"
            and "Sector"
            in df_filtrada.columns
        ):

            df_filtrada = df_filtrada[
                df_filtrada["Sector"]
                .astype(str)
                ==
                filtro_sector
            ]


        if busqueda_cartera:

            mask = (
                df_filtrada
                .astype(str)
                .apply(
                    lambda col:
                    col.str.contains(
                        busqueda_cartera,
                        case=False,
                        na=False,
                        regex=False
                    )
                )
                .any(axis=1)
            )

            df_filtrada = (
                df_filtrada[mask]
            )


        # ----------------------------------------------------
        # CONTADOR
        # ----------------------------------------------------

        render_html(
            f"""
<div style="
    margin:8px 0 14px;
    color:#94a3b8;
    font-size:10px;
    font-weight:700;
">
    MOSTRANDO {len(df_filtrada)} POSICIONES
</div>
""",
            unsafe_allow_html=True,
        )


        # ----------------------------------------------------
        # ASSET CARDS
        # ----------------------------------------------------

        for _, row in df_filtrada.iterrows():

            icono = safe_text(
                row.get("Icono"),
                "📈"
            )

            empresa = safe_text(
                row.get(
                    "Empresa",
                    row.get(
                        "Ticker",
                        "Activo"
                    )
                ),
                "Activo"
            )

            ticker = safe_text(
                row.get(
                    "Ticker"
                ),
                ""
            )

            ticker_raw = str(
                row.get(
                    "Ticker",
                    ""
                )
            ).strip()

            sector = safe_text(
                row.get(
                    "Sector"
                ),
                "Mercado Continuo"
            )


            # ------------------------------------------------
            # NUEVO
            # ------------------------------------------------

            es_nuevo = False

            if (
                "Fecha" in row
                and pd.notna(row["Fecha"])
            ):

                try:

                    fecha_alerta = (
                        row["Fecha"]
                        .to_pydatetime()
                        .replace(
                            tzinfo=None
                        )
                    )

                    delta = (
                        datetime.now()
                        -
                        fecha_alerta
                    )

                    if delta <= timedelta(
                        hours=48
                    ):

                        es_nuevo = True

                except Exception:
                    pass


            badge_nuevo = (
                '<span class="new-badge">'
                '✦ NUEVO'
                '</span>'
                if es_nuevo
                else ""
            )


            # ------------------------------------------------
            # PRECIOS
            # ------------------------------------------------

            precio_actual = (
                precios_actuales.get(
                    ticker_raw
                )
                if ticker_raw
                else None
            )


            precio_entrada = safe_float(
                row.get(
                    "Precio_Alerta"
                )
            )

            stop_loss = safe_float(
                row.get(
                    "Stop_Loss"
                )
            )

            take_profit = safe_float(
                row.get(
                    "Take_Profit"
                )
            )

            ratio_rr = safe_float(
                row.get(
                    "Ratio_RR"
                )
            )


            # ------------------------------------------------
            # P&L ACTUAL
            # ------------------------------------------------

            (
                beneficio_posicion,
                porcentaje_posicion
            ) = calcular_pnl_posicion(
                precio_actual,
                precio_entrada,
                CAPITAL_POR_ALERTA
            )


            # ------------------------------------------------
            # PERFORMANCE
            # ------------------------------------------------

            if (
                beneficio_posicion is None
                or porcentaje_posicion is None
            ):

                performance_text = "—"

                performance_class = (
                    "performance-neutral"
                )

            else:

                performance_text = (
                    f"{formatear_numero(
                        porcentaje_posicion,
                        2,
                        '%',
                        True
                    )}"
                    f" · "
                    f"{formatear_numero(
                        beneficio_posicion,
                        2,
                        ' €',
                        True
                    )}"
                )

                performance_class = (
                    "performance-positive"
                    if beneficio_posicion >= 0
                    else "performance-negative"
                )


            # ------------------------------------------------
            # RISK / REWARD
            # ------------------------------------------------

            ratio_rr_text = (
                formatear_numero(
                    ratio_rr,
                    1,
                    "x"
                )
                if ratio_rr is not None
                else "—"
            )


            # ------------------------------------------------
            # PRECIOS DEL TRACKER
            # ------------------------------------------------

            stop_loss_text = (
                formatear_numero(
                    stop_loss,
                    2
                )
                if stop_loss is not None
                else "—"
            )

            entrada_text = (
                formatear_numero(
                    precio_entrada,
                    2
                )
                if precio_entrada is not None
                else "—"
            )

            actual_text = (
                formatear_numero(
                    precio_actual,
                    2
                )
                if precio_actual is not None
                else "—"
            )

            take_profit_text = (
                formatear_numero(
                    take_profit,
                    2
                )
                if take_profit is not None
                else "—"
            )


            # ------------------------------------------------
            # POSITION TRACKER
            # ------------------------------------------------

            positions = (
                calcular_position_percentages(
                    stop_loss,
                    precio_entrada,
                    precio_actual,
                    take_profit
                )
            )


            if positions:

                sl_pct = (
                    positions["sl"]
                    if positions["sl"]
                    is not None
                    else 0
                )

                entry_pct = (
                    positions["entry"]
                    if positions["entry"]
                    is not None
                    else 25
                )

                current_pct = (
                    positions["current"]
                    if positions["current"]
                    is not None
                    else entry_pct
                )

                tp_pct = (
                    positions["tp"]
                    if positions["tp"]
                    is not None
                    else 100
                )


                risk_left = (
                    min(
                        entry_pct,
                        current_pct
                    )
                    -
                    sl_pct
                )

                reward_left = (
                    tp_pct
                    -
                    max(
                        entry_pct,
                        current_pct
                    )
                )

                risk_width = max(
                    0,
                    risk_left
                )

                reward_width = max(
                    0,
                    reward_left
                )


                position_tracker = f"""
<div class="position-wrapper">

    <div class="position-labels">

        <div class="position-label-item">

            <span class="position-label">
                Stop
            </span>

            <span class="position-price">
                {stop_loss_text}
            </span>

        </div>


        <div class="position-label-item">

            <span class="position-label">
                Entrada
            </span>

            <span class="position-price">
                {entrada_text}
            </span>

        </div>


        <div class="position-label-item">

            <span class="position-label">
                Actual
            </span>

            <span class="position-price">
                {actual_text}
            </span>

        </div>


        <div class="position-label-item">

            <span class="position-label">
                Take Profit
            </span>

            <span class="position-price">
                {take_profit_text}
            </span>

        </div>

    </div>


    <div class="position-track">

        <div
            class="position-risk"
            style="
                left:{sl_pct:.2f}%;
                width:{risk_width:.2f}%;
            "
        ></div>

        <div
            class="position-reward"
            style="
                left:{current_pct:.2f}%;
                width:{reward_width:.2f}%;
            "
        ></div>


        <div
            class="position-marker marker-sl"
            style="
                left:{sl_pct:.2f}%;
            "
        ></div>

        <div
            class="position-marker marker-entry"
            style="
                left:{entry_pct:.2f}%;
            "
        ></div>

        <div
            class="position-marker marker-current"
            style="
                left:{current_pct:.2f}%;
            "
        ></div>

        <div
            class="position-marker marker-tp"
            style="
                left:{tp_pct:.2f}%;
            "
        ></div>

    </div>

</div>
"""

            else:

                position_tracker = ""


            # ------------------------------------------------
            # PRECIO ACTUAL
            # ------------------------------------------------

            precio_actual_text = (
                formatear_numero(
                    precio_actual,
                    2
                )
                if precio_actual is not None
                else "—"
            )


            # ------------------------------------------------
            # TESIS IA
            # ------------------------------------------------

            analisis_ia_raw = row.get("Analisis_IA_Actual", "")
            if pd.isna(analisis_ia_raw) or not str(analisis_ia_raw).strip():
                analisis_ia_raw = row.get("Analisis_IA_Entrada", "")
            if pd.isna(analisis_ia_raw) or not str(analisis_ia_raw).strip():
                analisis_ia_raw = row.get("Analisis_IA", "")

            analisis_ia = formatear_tesis_ia(analisis_ia_raw)


            # ------------------------------------------------
            # CARD
            # ------------------------------------------------

            render_html(
                f"""
<div class="asset-card">

    <div class="asset-header">

        <!-- IZQUIERDA: NUEVO + IDENTIDAD -->

        <div class="asset-left">

            <div class="asset-new-row">

                {badge_nuevo}

            </div>


            <div class="asset-identity">

                <div class="asset-icon">
                    {icono}
                </div>

                <div>

                    <div class="asset-company">

                        {empresa}

                        <span class="asset-ticker">
                            {ticker}
                        </span>

                    </div>

                    <div class="asset-sector">
                        {sector}
                    </div>

                </div>

            </div>

        </div>


        <!-- DERECHA: PRECIO -->

        <div class="asset-right">

            <div class="current-price">
                {precio_actual_text}
            </div>

            <div class="price-label">
                Precio actual
            </div>

        </div>

    </div>


    <!-- ================================================
         RISK / REWARD + RENDIMIENTO
         ================================================ -->

    <div class="performance-row">

        <!-- IZQUIERDA: RISK / REWARD -->

        <div class="performance-rr">

            <div class="performance-rr-label">
                Risk / Reward
            </div>

            <div class="performance-rr-value">
                {ratio_rr_text}
            </div>

        </div>


        <!-- DERECHA: RENDIMIENTO -->

        <div class="performance-left">

            <div class="performance-label">
                Rendimiento desde entrada
            </div>

            <div class="performance-value {performance_class}">
                {performance_text}
            </div>

        </div>

    </div>


    {position_tracker}


    <div class="ai-box">

        <div class="ai-header">
            ✦ Tesis del analista
        </div>

        <div class="ai-text">
            {analisis_ia}
        </div>

    </div>

</div>
""",
                unsafe_allow_html=True,
            )


# ============================================================
# 2. RESULTADOS
# ============================================================

with tab_resultados:

    render_html(
        """
<div class="section-header">

    <div>

        <div class="section-title">
            Rendimiento
        </div>

        <div class="section-subtitle">
            Beneficio realizado + valoración actual de posiciones abiertas.
        </div>

    </div>

</div>
""",
        unsafe_allow_html=True,
    )


    col_g1, col_g2 = st.columns(
        [1.55, 0.75],
        gap="large"
    )


    # --------------------------------------------------------
    # CHART
    # --------------------------------------------------------

    with col_g1:

        render_html(
            f"""
<div class="result-card">

    <div class="result-header">

        <div>

            <div class="result-title">
                Evolución de beneficios
            </div>

            <div class="result-subtitle">
                Resultado simulado de la cartera
            </div>

        </div>


        <div>

            <div
                class="result-number"
                style="
                    color:{color_resultado};
                "
            >
                {formatear_numero(
                    beneficio_acumulado,
                    2,
                    " €",
                    True
                )}
            </div>

            <div class="result-percent">

                {formatear_numero(
                    rentabilidad_pct,
                    2,
                    "%",
                    True
                )}
                de retorno

            </div>

        </div>

    </div>


    <div style="
        display:flex;
        gap:16px;
        font-size:10px;
        color:#94a3b8;
        font-weight:600;
        margin-bottom:3px;
        flex-wrap:wrap;
    ">

        <span>
            ● Realizado:
            {formatear_numero(
                beneficio_realizado,
                2,
                " €",
                True
            )}
        </span>

        <span>
            ● Abierto:
            {formatear_numero(
                beneficio_no_realizado,
                2,
                " €",
                True
            )}
        </span>

    </div>

</div>
""",
            unsafe_allow_html=True,
        )


        if fechas_curva:

            df_beneficio = pd.DataFrame(
                {
                    "Beneficio Neto (€)":
                        beneficios_curva
                },
                index=fechas_curva
            )

            st.line_chart(
                df_beneficio,
                height=320
            )

        else:

            render_html(
                """
<div class="empty-state">

    <div class="empty-title">
        Sin suficientes datos
    </div>

    <div class="empty-text">
        Se requieren registros históricos para construir la curva.
    </div>

</div>
""",
                unsafe_allow_html=True,
            )


    # --------------------------------------------------------
    # METRICS
    # --------------------------------------------------------

    with col_g2:

        render_html(
            f"""
<div class="result-card">

    <div class="result-title">
        Métricas clave
    </div>

    <div class="result-subtitle">
        Estado operativo del sistema
    </div>


    <div class="metric-list">


        <div class="metric-row">

            <span class="metric-name">
                Señales activas
            </span>

            <span
                class="metric-value"
                style="
                    color:#2563eb;
                "
            >
                {activas}
            </span>

        </div>


        <div class="metric-row">

            <span class="metric-name">
                Posiciones en beneficio
            </span>

            <span
                class="metric-value"
                style="
                    color:#16a34a;
                "
            >
                {posiciones_con_beneficio}
            </span>

        </div>


        <div class="metric-row">

            <span class="metric-name">
                Take Profit alcanzado
            </span>

            <span
                class="metric-value"
                style="
                    color:#16a34a;
                "
            >
                {exitos}
            </span>

        </div>


        <div class="metric-row">

            <span class="metric-name">
                Stop Loss saltado
            </span>

            <span
                class="metric-value"
                style="
                    color:#dc2626;
                "
            >
                {fallos}
            </span>

        </div>


        <div class="metric-row">

            <span class="metric-name">
                Win Rate
            </span>

            <span class="metric-value">
                {formatear_numero(
                    win_rate,
                    1,
                    "%"
                )}
            </span>

        </div>


        <div class="metric-row">

            <span class="metric-name">
                Beneficio realizado
            </span>

            <span
                class="metric-value"
                style="
                    color:{
                        '#16a34a'
                        if beneficio_realizado >= 0
                        else '#dc2626'
                    };
                "
            >
                {formatear_numero(
                    beneficio_realizado,
                    2,
                    " €",
                    True
                )}
            </span>

        </div>


        <div class="metric-row">

            <span class="metric-name">
                P&L posiciones abiertas
            </span>

            <span
                class="metric-value"
                style="
                    color:{
                        '#16a34a'
                        if beneficio_no_realizado >= 0
                        else '#dc2626'
                    };
                "
            >
                {formatear_numero(
                    beneficio_no_realizado,
                    2,
                    " €",
                    True
                )}
            </span>

        </div>


        <div class="metric-row">

            <span class="metric-name">
                Beneficio total simulado
            </span>

            <span
                class="metric-value"
                style="
                    color:{color_resultado};
                "
            >
                {formatear_numero(
                    beneficio_acumulado,
                    2,
                    " €",
                    True
                )}
            </span>

        </div>


        <div class="metric-row">

            <span class="metric-name">
                Capital simulado
            </span>

            <span class="metric-value">
                {formatear_numero(
                    CAPITAL_INICIAL,
                    0,
                    " €"
                )}
            </span>

        </div>

    </div>

</div>
""",
            unsafe_allow_html=True,
        )


# ============================================================
# 3. HISTÓRICO
# ============================================================

with tab_historial:

    render_html(
        """
<div class="history-header">

    <div class="history-title">
        Registro histórico
    </div>

    <div class="history-subtitle">
        Auditoría completa de las señales generadas por Alura Quant.
    </div>

</div>
""",
        unsafe_allow_html=True,
    )


    df_cerradas = df_hist.copy()


    if not df_cerradas.empty:

        col_f1, col_f2 = st.columns(
            [1, 1],
            gap="small"
        )


        with col_f1:

            if "Estado" in df_cerradas.columns:

                estados_posibles = sorted(
                    df_cerradas["Estado"]
                    .astype(str)
                    .unique()
                    .tolist()
                )

            else:

                estados_posibles = []


            filtro_est = st.multiselect(
                "Estado operativo",
                estados_posibles,
                default=estados_posibles,
                label_visibility="collapsed"
            )


        with col_f2:

            busq_hist = st.text_input(
                "Buscar histórico",
                placeholder="⌕  Buscar empresa, ticker o estado...",
                label_visibility="collapsed"
            )


        df_view = (
            df_cerradas.copy()
        )


        if (
            filtro_est
            and "Estado"
            in df_view.columns
        ):

            df_view = df_view[
                df_view["Estado"]
                .astype(str)
                .isin(
                    filtro_est
                )
            ]


        if busq_hist:

            mask_h = (
                df_view
                .astype(str)
                .apply(
                    lambda col:
                    col.str.contains(
                        busq_hist,
                        case=False,
                        na=False,
                        regex=False
                    )
                )
                .any(axis=1)
            )

            df_view = (
                df_view[mask_h]
            )


        render_html(
            f"""
<div style="
    margin:8px 0 10px;
    color:#94a3b8;
    font-size:10px;
    font-weight:700;
">
    {len(df_view)} REGISTROS
</div>
""",
            unsafe_allow_html=True,
        )


        st.dataframe(
            df_view,
            use_container_width=True,
            height=480,
            hide_index=True
        )


    else:

        render_html(
            """
<div class="empty-state">

    <div class="empty-title">
        No hay registros históricos
    </div>

    <div class="empty-text">
        Las señales cerradas aparecerán aquí.
    </div>

</div>
""",
            unsafe_allow_html=True,
        )


# ============================================================
# 4. PLANES Y SUSCRIPCIÓN
# ============================================================

with tab_planes:
    render_html(
        '''
<div class="pricing-hero">
    <div class="eyebrow">ALURA QUANT MEMBERSHIP</div>
    <h2>Más señal. Menos ruido.</h2>
    <p>Accede a la inteligencia cuantitativa de Alura Quant y recibe las oportunidades que cumplen nuestros criterios.</p>
</div>
<div class="pricing-grid">
    <div class="pricing-card">
        <div class="pricing-badge">FREE</div>
        <h3>Explora Alura Quant</h3>
        <div class="pricing-price">0 € <span>/ mes</span></div>
        <p class="pricing-description">Para conocer el sistema y seguir una selección de señales.</p>
        <ul>
            <li>✓ Acceso al dashboard</li>
            <li>✓ Resumen de mercado</li>
            <li>✓ Señales seleccionadas</li>
            <li>✓ Métricas cuantitativas básicas</li>
        </ul>
    </div>
    <div class="pricing-card pricing-card-pro">
        <div class="pricing-badge pro">PRO</div>
        <h3>Alura Quant Pro</h3>
        <div class="pricing-price">19 € <span>/ mes</span></div>
        <p class="pricing-description">Para recibir las señales de mayor convicción y el análisis completo.</p>
        <ul>
            <li>✓ Alertas con Score &gt; 80</li>
            <li>✓ Envío prioritario</li>
            <li>✓ Tesis cuantitativa + IA</li>
            <li>✓ Histórico de tesis detalladas</li>
            <li>✓ Informe semanal</li>
        </ul>
    </div>
</div>
''',
        unsafe_allow_html=True,
    )

    col_free, col_vip = st.columns(2, gap="large")

    with col_free:
        st.markdown("### Crear acceso gratuito")
        email_free = st.text_input(
            "Email",
            placeholder="tu@email.com",
            key="input_free",
            label_visibility="collapsed",
        )
        if st.button("Crear acceso Free", use_container_width=True, type="secondary"):
            resultado = guardar_suscriptor_supabase(email_free, "free")
            if resultado == "success":
                st.success("Registro completado. Ya formas parte de Alura Quant Free.")
            elif resultado == "exists":
                st.info("Este email ya está registrado en el plan Free.")
            elif resultado == "invalid":
                st.error("Introduce un email válido.")
            else:
                st.error("No hemos podido completar el registro. Inténtalo de nuevo.")

    with col_vip:
        st.markdown("### Activar Alura Quant Pro")
        email_vip = st.text_input(
            "Email Pro",
            placeholder="El email que usarás para tu suscripción",
            key="input_vip",
            label_visibility="collapsed",
        )
        url_stripe = os.getenv("STRIPE_PAYMENT_LINK", "https://buy.stripe.com/tu_enlace_de_pago_real")
        if st.button("Continuar con Pro · 19 €/mes", use_container_width=True, type="primary"):
            resultado = guardar_suscriptor_supabase(email_vip, "vip")
            if resultado in ("success", "exists"):
                url_segura = html.escape(url_stripe, quote=True)
                render_html(
                    f'''<div class="stripe-cta"><a href="{url_segura}" target="_blank" rel="noopener noreferrer">Continuar al pago seguro →</a></div>''',
                    unsafe_allow_html=True,
                )
                st.caption(
                    "Tu email ha quedado registrado para Pro. Completa ahora el pago."
                    if resultado == "success"
                    else "Tu email ya estaba registrado. Puedes continuar al pago."
                )
            elif resultado == "invalid":
                st.error("Introduce un email válido antes de continuar.")
            else:
                st.error("No hemos podido preparar tu suscripción. Inténtalo de nuevo.")

    render_html(
        '''<div class="subscription-note"><strong>Importante:</strong> el registro en Supabase identifica tu email. Para considerar una suscripción Pro como <strong>pagada y activa</strong>, conecta Stripe mediante un webhook que confirme el pago y gestione altas, renovaciones y cancelaciones.</div>''',
        unsafe_allow_html=True,
    )

# ============================================================
# FOOTER
# ============================================================

render_html(
    f"""
<div class="app-footer">

    <span>
        ALURA QUANT · INVESTMENT INTELLIGENCE
    </span>

    <span>
        🔄 Última actualización: <strong>{fecha_actualizacion_sistema}</strong>
    </span>

</div>


<a
    href="#top"
    class="scroll-top"
    title="Volver arriba"
    aria-label="Volver arriba"
>
    ↑
</a>
""",
    unsafe_allow_html=True,
)
