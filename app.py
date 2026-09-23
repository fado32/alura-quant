import os
import re
import html
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
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


def guardar_suscriptor_supabase(email, tipo="free"):
    """Registra un email en la tabla Supabase correspondiente."""
    email = str(email or "").strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return "invalid"

    tabla = "suscriptores_vip" if tipo == "vip" else "suscriptores_free"

    try:
        # on_conflict evita errores si el usuario ya está registrado.
        response = (
            supabase
            .table(tabla)
            .upsert(
                {"email": email},
                on_conflict="email",
                ignore_duplicates=True
            )
            .execute()
        )
        return "success" if response.data is not None else "exists"
    except Exception as e:
        # Algunos clientes/versiones de postgrest pueden no soportar
        # ignore_duplicates de la misma forma; hacemos fallback a insert.
        try:
            supabase.table(tabla).insert({"email": email}).execute()
            return "success"
        except Exception as inner:
            if "duplicate" in str(inner).lower() or "unique" in str(inner).lower():
                return "exists"
            print(f"Error registrando suscriptor en {tabla}: {inner}")
            return "error"


def validar_email(email):
    email = str(email or "").strip()
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email))


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
# BACKTESTING DIARIO — CURVA DE BENEFICIO
# ============================================================

@st.cache_data(ttl=120)
def cargar_backtesting_diario():
    """Carga snapshots diarios de backtesting_diario_alertas desde Supabase."""
    columnas = [
        "fecha_snapshot", "alerta_id", "ticker", "estado",
        "precio_alerta", "precio_actual", "pnl_actual_pct",
        "mae_r", "mfe_r", "score_actual", "rsi_actual",
        "atr_actual", "distancia_sl_pct", "distancia_tp_pct",
        "ultima_actualizacion"
    ]

    try:
        registros = []
        inicio = 0
        tamano = 1000

        while True:
            response = (
                supabase
                .table("backtesting_diario_alertas")
                .select(",".join(columnas))
                .order("fecha_snapshot", desc=False)
                .range(inicio, inicio + tamano - 1)
                .execute()
            )
            lote = response.data or []
            registros.extend(lote)

            if len(lote) < tamano:
                break
            inicio += tamano

        if not registros:
            return pd.DataFrame(columns=columnas)

        df = pd.DataFrame(registros)

        df["fecha_snapshot"] = pd.to_datetime(
            df["fecha_snapshot"], errors="coerce"
        ).dt.normalize()

        for col in [
            "pnl_actual_pct", "mae_r", "mfe_r", "score_actual",
            "rsi_actual", "atr_actual", "distancia_sl_pct",
            "distancia_tp_pct", "precio_alerta", "precio_actual"
        ]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df.dropna(subset=["fecha_snapshot"])

    except Exception as e:
        print(f"Error cargando backtesting diario: {e}")
        return pd.DataFrame(columns=columnas)


def calcular_curva_backtesting(df_backtest):
    """
    Construye una curva diaria a partir del último snapshot disponible
    de cada alerta en cada fecha.

    pnl_actual_pct representa el P&L actual de cada alerta frente a su
    entrada. Por tanto, el agregado diario es un P&L mark-to-market
    de la cartera, no una suma de operaciones cerradas.
    """
    if df_backtest is None or df_backtest.empty:
        return pd.DataFrame()

    df = df_backtest.copy()

    required = {"fecha_snapshot", "alerta_id", "pnl_actual_pct"}
    if not required.issubset(df.columns):
        return pd.DataFrame()

    df = df.dropna(subset=["fecha_snapshot", "alerta_id"])
    df["pnl_eur"] = df["pnl_actual_pct"].fillna(0) * CAPITAL_POR_ALERTA / 100

    # Una fila por alerta y día. La constraint unique de Supabase ya
    # garantiza esto, pero mantenemos la deduplicación por robustez.
    df = (
        df.sort_values(["fecha_snapshot", "alerta_id"])
          .drop_duplicates(["fecha_snapshot", "alerta_id"], keep="last")
    )

    diario = (
        df.groupby("fecha_snapshot", as_index=False)
          .agg(
              pnl_eur=("pnl_eur", "sum"),
              pnl_pct_total=("pnl_actual_pct", "sum"),
              alertas=("alerta_id", "nunique"),
          )
          .sort_values("fecha_snapshot")
    )

    if diario.empty:
        return diario

    diario["variacion_dia_eur"] = diario["pnl_eur"].diff().fillna(diario["pnl_eur"])
    diario["fecha"] = diario["fecha_snapshot"].dt.strftime("%Y-%m-%d")

    return diario


def obtener_snapshot_backtesting_actual(df_backtest):
    """Obtiene el último snapshot de cada alerta y suma su P&L actual."""
    if df_backtest is None or df_backtest.empty:
        return 0.0, 0, 0

    df = df_backtest.dropna(subset=["fecha_snapshot", "alerta_id"]).copy()
    if df.empty:
        return 0.0, 0, 0

    latest_date = df["fecha_snapshot"].max()
    latest = df[df["fecha_snapshot"] == latest_date].copy()

    latest["pnl_eur"] = latest["pnl_actual_pct"].fillna(0) * CAPITAL_POR_ALERTA / 100

    total = float(latest["pnl_eur"].sum())
    positivas = int((latest["pnl_eur"] > 0).sum())
    negativas = int((latest["pnl_eur"] < 0).sum())

    return total, positivas, negativas


def calcular_metricas_resultados(df_historial, df_curva):
    """Métricas de presentación para el cuadro de mando de Resultados."""
    resultado = {
        "profit_factor": None,
        "avg_win": None,
        "avg_loss": None,
        "max_drawdown": 0.0,
        "mejor_dia": None,
        "peor_dia": None,
        "dias": 0,
    }

    if df_curva is not None and not df_curva.empty:
        resultado["dias"] = int(len(df_curva))
        cambios = pd.to_numeric(df_curva["variacion_dia_eur"], errors="coerce").dropna()
        if not cambios.empty:
            resultado["mejor_dia"] = float(cambios.max())
            resultado["peor_dia"] = float(cambios.min())

        equity = pd.to_numeric(df_curva["pnl_eur"], errors="coerce").fillna(0)
        peak = equity.cummax()
        drawdown = equity - peak
        resultado["max_drawdown"] = float(drawdown.min())

    if df_historial is not None and not df_historial.empty:
        ganancias = []
        perdidas = []

        for _, row in df_historial.iterrows():
            estado = str(row.get("Estado", ""))
            entrada = safe_float(row.get("Precio_Alerta"))
            sl = safe_float(row.get("Stop_Loss"))
            tp = safe_float(row.get("Take_Profit"))

            if entrada is None or entrada <= 0:
                continue

            if "OBJETIVO_CUMPLIDO" in estado and tp is not None:
                ganancias.append(CAPITAL_POR_ALERTA * (tp - entrada) / entrada)
            elif "STOP_SALTADO" in estado and sl is not None:
                perdidas.append(CAPITAL_POR_ALERTA * (sl - entrada) / entrada)

        resultado["avg_win"] = float(pd.Series(ganancias).mean()) if ganancias else None
        resultado["avg_loss"] = float(pd.Series(perdidas).mean()) if perdidas else None

        gross_profit = sum(v for v in ganancias if v > 0)
        gross_loss = abs(sum(v for v in perdidas if v < 0))
        resultado["profit_factor"] = (
            gross_profit / gross_loss if gross_loss > 0 else None
        )

    return resultado


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

def calcular_position_percentages(stop_loss, entrada, actual, take_profit):
    """
    Escala VISUAL FIJA basada exclusivamente en SL / Entrada / TP.

    El precio actual nunca redefine el rango. Esto evita el bug visual
    por el que la zona verde se desplazaba o cambiaba de tamaño cuando
    el precio se acercaba al stop loss.
    """
    values = [
        safe_float(stop_loss),
        safe_float(entrada),
        safe_float(take_profit),
    ]

    if any(v is None for v in values):
        return None

    sl, entry, tp = values

    if not (sl < entry < tp):
        return None

    # Pequeño margen visual, pero fijo para cada operación.
    rango = tp - sl
    margen = rango * 0.08
    minimum = sl - margen
    maximum = tp + margen
    escala = maximum - minimum

    def position(value, clamp=True):
        value = safe_float(value)
        if value is None:
            return None
        pct = (value - minimum) / escala * 100
        return max(0, min(100, pct)) if clamp else pct

    return {
        "sl": position(sl),
        "entry": position(entry),
        "current": position(actual),
        "tp": position(tp),
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

</style>
""",
    unsafe_allow_html=True,
)



# ============================================================
# PREMIUM UI OVERRIDES
# ============================================================

st.markdown(
    """
<style>
/* Dashboard header */
.results-hero{
    display:flex;
    align-items:flex-end;
    justify-content:space-between;
    gap:24px;
    padding:24px 26px;
    margin:4px 0 18px;
    background:linear-gradient(135deg,#0f172a 0%,#172554 58%,#1d4ed8 100%);
    border-radius:22px;
    color:white;
    box-shadow:0 18px 45px rgba(15,23,42,.12);
}
.eyebrow{
    font-size:9px;
    letter-spacing:.13em;
    font-weight:800;
    opacity:.68;
    margin-bottom:7px;
}
.results-title{
    font-family:'Plus Jakarta Sans';
    font-size:25px;
    font-weight:800;
    letter-spacing:-.04em;
}
.results-subtitle{
    margin-top:6px;
    font-size:11px;
    line-height:1.5;
    color:rgba(255,255,255,.72);
}
.results-source{
    display:flex;
    align-items:center;
    gap:7px;
    white-space:nowrap;
    padding:8px 11px;
    border:1px solid rgba(255,255,255,.14);
    background:rgba(255,255,255,.08);
    border-radius:999px;
    font-size:9px;
    font-weight:700;
}
.source-dot{
    width:6px;height:6px;border-radius:50%;
    background:#86efac;
    box-shadow:0 0 0 4px rgba(134,239,172,.12);
}

/* Premium top cards */
.premium-summary{gap:14px!important;}
.summary-card{
    position:relative;
    overflow:hidden;
    min-height:132px;
    padding:18px 19px!important;
    border-radius:18px!important;
    border:1px solid #e5eaf2!important;
}
.summary-card::after{
    content:"";
    position:absolute;
    right:-26px;
    top:-30px;
    width:90px;height:90px;
    border-radius:50%;
    background:#f8fafc;
}
.summary-card-primary{
    border-color:#dbe7ff!important;
    background:linear-gradient(145deg,#ffffff,#f5f8ff)!important;
}
.summary-card-primary::after{background:#e9f1ff;}
.summary-topline{
    position:relative;
    z-index:1;
    display:flex;
    align-items:center;
    gap:7px;
    min-height:18px;
}
.summary-icon{
    display:inline-flex;
    align-items:center;
    justify-content:center;
    width:23px;height:23px;
    border-radius:8px;
    background:#eff6ff;
    color:#2563eb;
    font-size:12px;
    font-weight:800;
}
.summary-label{
    font-size:9px!important;
    letter-spacing:.09em!important;
    margin:0!important;
}
.summary-status{
    margin-left:auto;
    padding:3px 7px;
    border-radius:999px;
    background:#ecfdf3;
    color:#15803d;
    font-size:7px;
    font-weight:800;
    letter-spacing:.08em;
}
.summary-value{
    position:relative;
    z-index:1;
    margin-top:16px!important;
    font-size:24px!important;
}
.summary-detail{
    position:relative;
    z-index:1;
    margin-top:7px!important;
    font-size:10px!important;
}

/* Result KPI cards */
.results-kpi-grid{
    display:grid;
    grid-template-columns:1.35fr repeat(5,1fr);
    gap:10px;
    margin:0 0 18px;
}
.results-kpi{
    min-width:0;
    background:#fff;
    border:1px solid #e7ebf2;
    border-radius:16px;
    padding:15px 16px;
    box-shadow:0 5px 20px rgba(15,23,42,.025);
}
.results-kpi-main{
    background:linear-gradient(145deg,#ffffff,#f6f9ff);
    border-color:#dbe7ff;
}
.kpi-label{
    color:#94a3b8;
    font-size:8px;
    letter-spacing:.09em;
    font-weight:800;
}
.kpi-value{
    margin-top:9px;
    font-family:'Plus Jakarta Sans';
    font-size:19px;
    font-weight:800;
    letter-spacing:-.035em;
    white-space:nowrap;
}
.kpi-meta{
    margin-top:5px;
    color:#64748b;
    font-size:9px;
    line-height:1.35;
}

/* Result panels */
.dashboard-panel{
    background:#fff;
    border:1px solid #e7ebf2;
    border-radius:20px;
    padding:20px;
    box-shadow:0 8px 30px rgba(15,23,42,.035);
    margin-bottom:14px;
}
.chart-panel{padding-bottom:14px;}
.panel-heading{
    display:flex;
    align-items:flex-start;
    justify-content:space-between;
    gap:12px;
    margin-bottom:12px;
}
.panel-title{
    font-family:'Plus Jakarta Sans';
    font-size:15px;
    font-weight:800;
    letter-spacing:-.02em;
}
.panel-subtitle{
    color:#94a3b8;
    font-size:9px;
    margin-top:4px;
}
.panel-badge{
    padding:5px 8px;
    border-radius:999px;
    background:#eff6ff;
    color:#2563eb;
    font-size:7px;
    font-weight:800;
    letter-spacing:.07em;
}
.mini-table-title{
    margin:4px 0 8px;
    color:#64748b;
    font-size:9px;
    font-weight:800;
    text-transform:uppercase;
    letter-spacing:.07em;
}
.insight-panel{padding:19px;}
.insight-item{
    display:flex;
    align-items:center;
    gap:11px;
    padding:13px 0;
    border-bottom:1px solid #eef1f5;
}
.insight-item:last-of-type{border-bottom:0;}
.insight-icon{
    display:flex;
    align-items:center;
    justify-content:center;
    width:31px;height:31px;
    flex:0 0 31px;
    border-radius:10px;
    font-size:13px;
    font-weight:800;
}
.insight-green{background:#ecfdf3;color:#16a34a;}
.insight-red{background:#fef2f2;color:#dc2626;}
.insight-blue{background:#eff6ff;color:#2563eb;}
.insight-amber{background:#fffbeb;color:#d97706;}
.insight-label{font-size:9px;color:#64748b;font-weight:600;}
.insight-value{
    margin-top:2px;
    font-family:'Plus Jakarta Sans';
    font-size:13px;
    font-weight:800;
    color:#111827;
}
.insight-footer{
    margin-top:13px;
    padding:10px 11px;
    background:#f8fafc;
    border-radius:11px;
    color:#64748b;
    font-size:8px;
    line-height:1.55;
}
.methodology-panel{padding:16px 18px;}
.methodology-title{
    font-family:'Plus Jakarta Sans';
    font-size:11px;
    font-weight:800;
    margin-bottom:7px;
}
.methodology-row{
    display:flex;
    justify-content:space-between;
    gap:10px;
    padding:7px 0;
    color:#64748b;
    font-size:9px;
    border-bottom:1px solid #eef1f5;
}
.methodology-row:last-child{border-bottom:0;}
.methodology-row strong{color:#111827;}

/* Cleaner Streamlit table */
div[data-testid="stDataFrame"]{
    border:1px solid #e7ebf2!important;
    border-radius:12px!important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"]{
    gap:4px!important;
    padding:5px!important;
    border:1px solid #e7ebf2!important;
    background:#f1f5f9!important;
    border-radius:13px!important;
}
.stTabs button[data-baseweb="tab"]{
    height:36px!important;
    padding:0 15px!important;
    border-radius:9px!important;
    border:0!important;
}
.stTabs button[aria-selected="true"]{
    background:#fff!important;
    color:#2563eb!important;
    border:1px solid #e1e8f4!important;
    box-shadow:0 2px 8px rgba(15,23,42,.06);
}

/* Portfolio cards */
.asset-card{
    border-radius:20px!important;
    padding:21px!important;
}
.position-track{
    height:8px!important;
    background:#e9eef5!important;
    overflow:visible;
}
.position-risk{
    background:linear-gradient(90deg,#fee2e2,#fecaca)!important;
}
.position-reward{
    background:linear-gradient(90deg,#dcfce7,#bbf7d0)!important;
}

/* Subscription */
.subscription-hero{
    padding:24px;
    margin-bottom:16px;
    border:1px solid #dbe7ff;
    border-radius:20px;
    background:linear-gradient(135deg,#f8fbff,#eef4ff);
}
.plan-grid{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:14px;
}
.plan-card{
    padding:22px;
    border:1px solid #e7ebf2;
    border-radius:20px;
    background:#fff;
    box-shadow:0 8px 30px rgba(15,23,42,.035);
}
.plan-card-vip{
    border-color:#c7d7fe;
    background:linear-gradient(145deg,#ffffff,#f7f9ff);
}
.plan-kicker{
    color:#64748b;
    font-size:8px;
    font-weight:800;
    letter-spacing:.1em;
}
.plan-name{
    margin-top:5px;
    font-family:'Plus Jakarta Sans';
    font-size:20px;
    font-weight:800;
}
.plan-price{
    margin-top:5px;
    font-family:'Plus Jakarta Sans';
    font-size:26px;
    font-weight:800;
}
.plan-copy{
    margin:9px 0 14px;
    color:#64748b;
    font-size:10px;
    line-height:1.6;
}
.plan-list{
    margin:0 0 17px;
    padding-left:17px;
    color:#334155;
    font-size:10px;
    line-height:1.9;
}
@media(max-width:1100px){
    .results-kpi-grid{grid-template-columns:repeat(3,1fr);}
    .results-kpi-main{grid-column:span 2;}
}
@media(max-width:700px){
    .results-hero{display:block;padding:19px;}
    .results-source{display:inline-flex;margin-top:13px;}
    .results-kpi-grid{grid-template-columns:1fr 1fr;}
    .results-kpi-main{grid-column:span 2;}
    .plan-grid{grid-template-columns:1fr;}
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
# BACKTESTING DIARIO
# ============================================================

df_backtest = cargar_backtesting_diario()
df_curva_backtest = calcular_curva_backtesting(df_backtest)

(
    beneficio_backtest_actual,
    backtest_ganadoras,
    backtest_perdedoras
) = obtener_snapshot_backtesting_actual(df_backtest)


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

metricas_resultados = calcular_metricas_resultados(
    df_hist,
    df_curva_backtest
)

# Si existe backtesting diario, la cifra principal de Resultados
# utiliza el último snapshot disponible de Supabase.
beneficio_dashboard = (
    beneficio_backtest_actual
    if not df_backtest.empty
    else beneficio_acumulado
)
rentabilidad_dashboard = (
    beneficio_dashboard / CAPITAL_INICIAL * 100
    if CAPITAL_INICIAL else 0
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
<div class="hero">
    <div>
        <h1 class="hero-title">
            Alura Quant | Inteligencia Financiera
        </h1>
        <div class="hero-subtitle">
            Procesamos todo el mercado con rigor matematico, para identificar oportunidades de valor
        </div>
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
<div class="portfolio-summary premium-summary">

    <div class="summary-card summary-card-primary">
        <div class="summary-topline">
            <span class="summary-icon">↗</span>
            <span class="summary-label">P&amp;L DE CARTERA</span>
            <span class="summary-status">LIVE</span>
        </div>
        <div class="summary-value" style="color:{color_resultado};">
            {formatear_numero(beneficio_dashboard, 2, " €", True)}
        </div>
        <div class="summary-detail">
            Snapshot diario · {formatear_numero(rentabilidad_dashboard, 2, "%", True)}
        </div>
    </div>

    <div class="summary-card">
        <div class="summary-topline">
            <span class="summary-icon">◒</span>
            <span class="summary-label">EFICIENCIA</span>
        </div>
        <div class="summary-value">
            {formatear_numero(win_rate, 1, "%")}
        </div>
        <div class="summary-detail">
            {exitos} objetivos · {fallos} stops · {total_alertas} señales
        </div>
    </div>

    <div class="summary-card">
        <div class="summary-topline">
            <span class="summary-icon">◎</span>
            <span class="summary-label">EXPOSICIÓN</span>
        </div>
        <div class="summary-value">
            {activas}
        </div>
        <div class="summary-detail">
            Posiciones activas · {TOTAL_ACTIVOS_UNIVERSO} activos monitorizados
        </div>
    </div>

    <div class="summary-card">
        <div class="summary-topline">
            <span class="summary-icon">◆</span>
            <span class="summary-label">RIESGO / RETORNO</span>
        </div>
        <div class="summary-value">
            {formatear_numero(metricas_resultados["profit_factor"], 2, "x") if metricas_resultados["profit_factor"] is not None else "—"}
        </div>
        <div class="summary-detail">
            Profit Factor · DD máx. {formatear_numero(abs(metricas_resultados["max_drawdown"]), 0, " €") if metricas_resultados["max_drawdown"] else "0 €"}
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


                # Las zonas de riesgo y recompensa son FIJAS.
                # Solo se mueve el marcador del precio actual.
                risk_width = max(0, entry_pct - sl_pct)
                reward_width = max(0, tp_pct - entry_pct)


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
                left:{entry_pct:.2f}%;
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
        f"""
<div class="results-hero">
    <div>
        <div class="eyebrow">PERFORMANCE CENTER · ALURA QUANT</div>
        <div class="results-title">Resultados de la estrategia</div>
        <div class="results-subtitle">
            Seguimiento cuantitativo del rendimiento, exposición y evolución diaria del P&amp;L.
        </div>
    </div>
    <div class="results-source">
        <span class="source-dot"></span>
        Supabase · backtesting diario
    </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # --------------------------------------------------------
    # KPI STRIP
    # --------------------------------------------------------

    ultimo_snapshot = (
        df_backtest["fecha_snapshot"].max().strftime("%d/%m/%Y")
        if not df_backtest.empty
        else "—"
    )

    pnl_color = "#16a34a" if beneficio_dashboard >= 0 else "#dc2626"
    dd_abs = abs(metricas_resultados["max_drawdown"])

    render_html(
        f"""
<div class="results-kpi-grid">

    <div class="results-kpi results-kpi-main">
        <div class="kpi-label">P&amp;L ACTUAL</div>
        <div class="kpi-value" style="color:{pnl_color};">
            {formatear_numero(beneficio_dashboard, 2, " €", True)}
        </div>
        <div class="kpi-meta">
            {formatear_numero(rentabilidad_dashboard, 2, "%", True)} sobre capital simulado
        </div>
    </div>

    <div class="results-kpi">
        <div class="kpi-label">WIN RATE</div>
        <div class="kpi-value">{formatear_numero(win_rate, 1, "%")}</div>
        <div class="kpi-meta">{exitos} TP · {fallos} SL</div>
    </div>

    <div class="results-kpi">
        <div class="kpi-label">PROFIT FACTOR</div>
        <div class="kpi-value">
            {formatear_numero(metricas_resultados["profit_factor"], 2, "x") if metricas_resultados["profit_factor"] is not None else "—"}
        </div>
        <div class="kpi-meta">Ganancia bruta / pérdida bruta</div>
    </div>

    <div class="results-kpi">
        <div class="kpi-label">DRAWDOWN MÁX.</div>
        <div class="kpi-value" style="color:#dc2626;">
            {formatear_numero(dd_abs, 2, " €") if dd_abs else "0 €"}
        </div>
        <div class="kpi-meta">Desde máximo de la curva diaria</div>
    </div>

    <div class="results-kpi">
        <div class="kpi-label">EXPOSICIÓN</div>
        <div class="kpi-value">{activas}</div>
        <div class="kpi-meta">{backtest_ganadoras} abiertas en positivo</div>
    </div>

    <div class="results-kpi">
        <div class="kpi-label">SNAPSHOT</div>
        <div class="kpi-value">{ultimo_snapshot}</div>
        <div class="kpi-meta">{metricas_resultados["dias"]} días monitorizados</div>
    </div>

</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    col_chart, col_side = st.columns([1.65, 0.75], gap="large")

    # --------------------------------------------------------
    # CURVA DIARIA
    # --------------------------------------------------------

    with col_chart:

        render_html(
            """
<div class="dashboard-panel chart-panel">
    <div class="panel-heading">
        <div>
            <div class="panel-title">Evolución diaria del P&amp;L</div>
            <div class="panel-subtitle">Valoración mark-to-market agregada desde backtesting_diario_alertas</div>
        </div>
        <div class="panel-badge">CURVA SUAVIZADA</div>
    </div>
""",
            unsafe_allow_html=True,
        )

        if not df_curva_backtest.empty:

            chart_df = df_curva_backtest.copy()
            chart_df["fecha_snapshot"] = pd.to_datetime(chart_df["fecha_snapshot"])

            fig = go.Figure()

            fig.add_trace(
                go.Scatter(
                    x=chart_df["fecha_snapshot"],
                    y=chart_df["pnl_eur"],
                    mode="lines",
                    name="P&L",
                    line=dict(
                        width=3,
                        shape="spline",
                        smoothing=1.15,
                    ),
                    fill="tozeroy",
                    fillcolor="rgba(37,99,235,0.07)",
                    hovertemplate=(
                        "<b>%{x|%d %b %Y}</b><br>"
                        "P&L: <b>%{y:.2f} €</b><extra></extra>"
                    ),
                )
            )

            fig.add_hline(
                y=0,
                line_width=1,
                line_dash="dot",
                line_color="#cbd5e1",
            )

            fig.update_layout(
                height=390,
                margin=dict(l=10, r=10, t=8, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(
                    family="DM Sans, sans-serif",
                    color="#64748b",
                    size=11,
                ),
                hovermode="x unified",
                showlegend=False,
                xaxis=dict(
                    showgrid=False,
                    linecolor="#e7ebf2",
                    tickfont=dict(size=10),
                ),
                yaxis=dict(
                    title=None,
                    showgrid=True,
                    gridcolor="#eef1f5",
                    zeroline=False,
                    tickfont=dict(size=10),
                ),
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                config={
                    "displayModeBar": False,
                    "responsive": True,
                },
            )

            # Tabla-resumen de últimos días, útil para lectura rápida.
            ultimos = chart_df.tail(5).copy()
            ultimos["Fecha"] = ultimos["fecha_snapshot"].dt.strftime("%d/%m/%Y")
            ultimos["P&L"] = ultimos["pnl_eur"].map(
                lambda x: formatear_numero(x, 2, " €", True)
            )
            ultimos["Variación"] = ultimos["variacion_dia_eur"].map(
                lambda x: formatear_numero(x, 2, " €", True)
            )

            render_html(
                """
<div class="mini-table-title">Últimos snapshots</div>
""",
                unsafe_allow_html=True,
            )

            st.dataframe(
                ultimos[["Fecha", "P&L", "Variación", "alertas"]].rename(
                    columns={"alertas": "Alertas"}
                ),
                use_container_width=True,
                hide_index=True,
                height=205,
            )

        else:
            render_html(
                """
<div class="empty-state">
    <div class="empty-icon">⌁</div>
    <div class="empty-title">Aún no hay snapshots diarios</div>
    <div class="empty-text">
        La curva se activará automáticamente cuando backtesting_diario_alertas tenga registros.
    </div>
</div>
""",
                unsafe_allow_html=True,
            )

        render_html("</div>", unsafe_allow_html=True)

    # --------------------------------------------------------
    # PANEL LATERAL DE LECTURA
    # --------------------------------------------------------

    with col_side:

        mejor_dia = metricas_resultados["mejor_dia"]
        peor_dia = metricas_resultados["peor_dia"]
        avg_win = metricas_resultados["avg_win"]
        avg_loss = metricas_resultados["avg_loss"]

        render_html(
            f"""
<div class="dashboard-panel insight-panel">

    <div class="panel-heading">
        <div>
            <div class="panel-title">Lectura del sistema</div>
            <div class="panel-subtitle">Indicadores operativos</div>
        </div>
    </div>

    <div class="insight-item">
        <div class="insight-icon insight-green">↗</div>
        <div>
            <div class="insight-label">Mejor variación diaria</div>
            <div class="insight-value">
                {formatear_numero(mejor_dia, 2, " €", True) if mejor_dia is not None else "—"}
            </div>
        </div>
    </div>

    <div class="insight-item">
        <div class="insight-icon insight-red">↘</div>
        <div>
            <div class="insight-label">Peor variación diaria</div>
            <div class="insight-value">
                {formatear_numero(peor_dia, 2, " €", True) if peor_dia is not None else "—"}
            </div>
        </div>
    </div>

    <div class="insight-item">
        <div class="insight-icon insight-blue">+</div>
        <div>
            <div class="insight-label">Ganancia media por TP</div>
            <div class="insight-value">
                {formatear_numero(avg_win, 2, " €", True) if avg_win is not None else "—"}
            </div>
        </div>
    </div>

    <div class="insight-item">
        <div class="insight-icon insight-amber">−</div>
        <div>
            <div class="insight-label">Pérdida media por SL</div>
            <div class="insight-value">
                {formatear_numero(avg_loss, 2, " €", True) if avg_loss is not None else "—"}
            </div>
        </div>
    </div>

    <div class="insight-footer">
        <strong>Fuente:</strong> snapshots diarios de Supabase.
        El P&amp;L de la curva es mark-to-market y no sustituye al resultado contable de operaciones cerradas.
    </div>

</div>
""",
            unsafe_allow_html=True,
        )

        render_html(
            f"""
<div class="dashboard-panel methodology-panel">
    <div class="methodology-title">Cómo leer el dashboard</div>
    <div class="methodology-row">
        <span>Capital por alerta</span>
        <strong>{formatear_numero(CAPITAL_POR_ALERTA, 0, " €")}</strong>
    </div>
    <div class="methodology-row">
        <span>Alertas históricas</span>
        <strong>{total_alertas}</strong>
    </div>
    <div class="methodology-row">
        <span>Posiciones activas</span>
        <strong>{activas}</strong>
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
        """
<div class="subscription-hero">
    <div class="eyebrow" style="color:#2563eb;">ALURA QUANT · MEMBERSHIP</div>
    <div class="results-title" style="color:#111827;">Convierte señales cuantitativas en una experiencia premium.</div>
    <div class="results-subtitle" style="color:#64748b;">
        Registra tu acceso directamente en Supabase y mantén la gestión de suscriptores centralizada.
    </div>
</div>
""",
        unsafe_allow_html=True,
    )

    plan_col1, plan_col2 = st.columns(2, gap="large")

    with plan_col1:
        render_html(
            """
<div class="plan-card">
    <div class="plan-kicker">ACCESO ABIERTO</div>
    <div class="plan-name">Free</div>
    <div class="plan-price">0 € <span style="font-size:11px;color:#94a3b8;font-weight:600;">/ mes</span></div>
    <div class="plan-copy">
        Una primera capa de inteligencia cuantitativa para conocer el sistema y recibir señales seleccionadas.
    </div>
    <ul class="plan-list">
        <li>Alertas con score moderado</li>
        <li>Resumen de mercado básico</li>
        <li>Acceso a informes públicos</li>
        <li>Registro gestionado desde Supabase</li>
    </ul>
</div>
""",
            unsafe_allow_html=True,
        )

        email_free = st.text_input(
            "Email Free",
            placeholder="tu@email.com",
            key="input_free",
            label_visibility="collapsed",
        )

        if st.button(
            "Crear acceso gratuito",
            key="btn_free",
            use_container_width=True,
        ):
            if not validar_email(email_free):
                st.error("Introduce un email válido.")
            else:
                resultado = guardar_suscriptor_supabase(email_free, "free")
                if resultado == "success":
                    st.success("Acceso registrado correctamente.")
                elif resultado == "exists":
                    st.info("Este email ya está registrado en Free.")
                else:
                    st.error("No se pudo registrar el email. Revisa la conexión con Supabase.")

    with plan_col2:
        render_html(
            """
<div class="plan-card plan-card-vip">
    <div class="plan-kicker" style="color:#2563eb;">ACCESO PREMIUM</div>
    <div class="plan-name">VIP</div>
    <div class="plan-price">19 € <span style="font-size:11px;color:#94a3b8;font-weight:600;">/ mes</span></div>
    <div class="plan-copy">
        Acceso premium para usuarios que quieren recibir las señales con mayor profundidad y contexto.
    </div>
    <ul class="plan-list">
        <li>Alertas exclusivas con Score &gt; 80</li>
        <li>Envío prioritario en tiempo real</li>
        <li>Informe semanal cuantitativo completo</li>
        <li>Histórico de tesis detalladas</li>
    </ul>
</div>
""",
            unsafe_allow_html=True,
        )

        email_vip = st.text_input(
            "Email VIP",
            placeholder="tu@email.com",
            key="input_vip",
            label_visibility="collapsed",
        )

        if st.button(
            "Registrar interés VIP",
            key="btn_vip",
            use_container_width=True,
        ):
            if not validar_email(email_vip):
                st.error("Introduce un email válido.")
            else:
                resultado = guardar_suscriptor_supabase(email_vip, "vip")
                if resultado == "success":
                    st.success("Email registrado en la lista VIP.")
                elif resultado == "exists":
                    st.info("Este email ya está registrado en VIP.")
                else:
                    st.error("No se pudo registrar el email. Revisa la conexión con Supabase.")

        # El enlace se obtiene de Secrets para no dejar una URL de pago
        # hardcodeada en el código.
        stripe_url = ""
        try:
            stripe_url = str(
                st.secrets.get("stripe", {}).get("vip_checkout_url", "")
            ).strip()
        except Exception:
            stripe_url = ""

        if stripe_url:
            render_html(
                f"""
<div style="margin-top:10px;">
    <a href="{html.escape(stripe_url)}" target="_blank"
       style="display:block;text-align:center;text-decoration:none;
              padding:11px 14px;border-radius:11px;background:#111827;
              color:white;font-size:10px;font-weight:800;">
        Continuar al pago VIP →
    </a>
</div>
""",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Configura [stripe].vip_checkout_url en Streamlit Secrets para activar el checkout.")

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
