import os
import re
import html
import json
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import requests
from supabase import create_client, Client
from openai import OpenAI
import resend


# ============================================================
# CONFIGURACIÓN
# ============================================================

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
if not RESEND_API_KEY:
    raise RuntimeError("Falta RESEND_API_KEY en las variables de entorno o GitHub Secrets.")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Faltan SUPABASE_URL y/o SUPABASE_KEY.")

resend.api_key = RESEND_API_KEY

IA_PROVIDER = os.getenv("IA_PROVIDER", "gemini").strip().lower()
MODELO_GEMINI = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Activos de referencia para el contexto de mercado.
# HYGH se incluye como referencia del segmento high yield / crédito,
# no como una medida pura de liquidez de mercado.
MARKET_TICKERS = {
    "S&P 500": "^GSPC",
    "Nasdaq 100": "^NDX",
    "Euro Stoxx 50": "^STOXX50E",
    "IBEX 35": "^IBEX",
    "VIX": "^VIX",
    "HYGH": "HYGH",
    "EUR/USD": "EURUSD=X",
}

REQUEST_TIMEOUT = int(os.getenv("MARKET_REQUEST_TIMEOUT", "15"))
NEWS_TIMEOUT = int(os.getenv("NEWS_REQUEST_TIMEOUT", "15"))
NEWS_MAX_ITEMS = int(os.getenv("NEWS_MAX_ITEMS", "12"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("alura_quant_newsletter")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================================
# UTILIDADES
# ============================================================

def cliente_ia() -> OpenAI:
    if IA_PROVIDER != "gemini":
        raise RuntimeError(
            f"IA_PROVIDER no válido: {IA_PROVIDER}. Actualmente el newsletter usa 'gemini'."
        )

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Falta GEMINI_API_KEY.")

    return OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)


def semana_referencia(hoy: Optional[date] = None) -> Tuple[date, date]:
    """
    Devuelve la semana bursátil de referencia:
    - Si se ejecuta sábado/domingo, toma el lunes-viernes anterior.
    - Si se ejecuta lunes-viernes, toma desde el lunes hasta hoy.
    """
    hoy = hoy or datetime.now().date()
    lunes = hoy - timedelta(days=hoy.weekday())

    if hoy.weekday() >= 5:
        inicio = lunes 
        fin = lunes + timedelta(days=4)
    else:
        inicio = lunes
        fin = hoy

    return inicio, fin


def limpiar_numero(value: Any, decimals: int = 2) -> Optional[float]:
    if value is None or pd.isna(value):
        return None

    try:
        return round(float(value), decimals)
    except (ValueError, TypeError):
        return None


def fmt_pct(value: Any, decimals: int = 2) -> str:
    number = limpiar_numero(value, decimals)
    if number is None:
        return "N/D"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.{decimals}f}%"


def fmt_num(value: Any, decimals: int = 2) -> str:
    number = limpiar_numero(value, decimals)
    return "N/D" if number is None else f"{number:.{decimals}f}"


def safe_str(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


# ============================================================
# SUSCRIPTORES
# ============================================================

def obtener_suscriptores() -> List[str]:
    logger.info("Consultando suscriptores en Supabase...")

    response = (
        supabase
        .table("suscriptores_free")
        .select("email")
        .execute()
    )

    emails = []
    seen = set()

    for row in response.data or []:
        email = safe_str(row.get("email")).lower()
        if email and email not in seen:
            emails.append(email)
            seen.add(email)

    logger.info("Suscriptores encontrados: %s", len(emails))
    return emails


# ============================================================
# DATOS HISTÓRICOS DE ALURA QUANT
# ============================================================

def obtener_backtesting(
    inicio: date,
    fin: date,
    margen_dias: int = 7
) -> pd.DataFrame:
    """
    Obtiene snapshots de backtesting_diario_alertas.

    Se utiliza esta tabla como histórico porque historial_alertas
    representa el estado actual y puede sobrescribirse.
    """
    desde = inicio - timedelta(days=margen_dias)
    hasta = fin

    logger.info(
        "Extrayendo backtesting_diario_alertas desde %s hasta %s...",
        desde,
        hasta
    )

    response = (
        supabase
        .table("backtesting_diario_alertas")
        .select(
            "id,fecha_snapshot,alerta_id,ticker,estado,"
            "precio_alerta,precio_actual,pnl_actual_pct,"
            "score_actual,rsi_actual,atr_actual,"
            "distancia_sl_pct,distancia_tp_pct,ultima_actualizacion"
        )
        .gte("fecha_snapshot", desde.isoformat())
        .lte("fecha_snapshot", hasta.isoformat())
        .order("fecha_snapshot", desc=False)
        .execute()
    )

    df = pd.DataFrame(response.data or [])

    if df.empty:
        raise RuntimeError(
            f"No hay snapshots en backtesting_diario_alertas entre {desde} y {hasta}."
        )

    df["fecha_snapshot"] = pd.to_datetime(
        df["fecha_snapshot"],
        errors="coerce"
    ).dt.date

    df["estado"] = df["estado"].fillna("").astype(str).str.upper().str.strip()
    df["alerta_id"] = pd.to_numeric(df["alerta_id"], errors="coerce")

    numeric_cols = [
        "precio_alerta",
        "precio_actual",
        "pnl_actual_pct",
        "score_actual",
        "rsi_actual",
        "atr_actual",
        "distancia_sl_pct",
        "distancia_tp_pct",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["fecha_snapshot", "alerta_id"])
    return df


def ultimo_snapshot_por_alerta(df: pd.DataFrame, hasta: date) -> pd.DataFrame:
    subset = df[df["fecha_snapshot"] <= hasta].copy()

    if subset.empty:
        return subset

    return (
        subset
        .sort_values(["alerta_id", "fecha_snapshot"])
        .drop_duplicates("alerta_id", keep="last")
    )


def construir_metricas_cartera(
    df: pd.DataFrame,
    inicio: date,
    fin: date
) -> Dict[str, Any]:
    """
    Reconstruye la evolución semanal a partir de los snapshots diarios.

    Importante:
    - No usa MAE/MFE.
    - Las operaciones cerradas se identifican por transición a estado terminal.
    - Una alerta_id se trata como una operación.
    """
    estados_terminales = {
        "STOP_SALTADO",
        "OBJETIVO_CUMPLIDO",
        "WIN",
        "LOSS",
        "CERRADA",
        "CLOSED",
        "TP",
        "SL",
    }

    df = df.sort_values(["alerta_id", "fecha_snapshot"]).copy()

    # Estado anterior para detectar transiciones reales.
    df["estado_anterior"] = df.groupby("alerta_id")["estado"].shift(1)

    terminales_semana = df[
        (df["fecha_snapshot"] >= inicio)
        & (df["fecha_snapshot"] <= fin)
        & (df["estado"].isin(estados_terminales))
        & (~df["estado_anterior"].isin(estados_terminales))
    ].copy()

    # Si la operación aparece por primera vez ya en estado terminal,
    # también debe contabilizarse.
    terminales_semana.loc[
        terminales_semana["estado_anterior"].isna(),
        "estado_anterior"
    ] = ""

    cerradas = terminales_semana.drop_duplicates(
        subset=["alerta_id"],
        keep="first"
    ).copy()

    # Clasificación robusta de resultado.
    def es_win(row: pd.Series) -> bool:
        estado = safe_str(row.get("estado")).upper()
        pnl = row.get("pnl_actual_pct")

        if estado in {"OBJETIVO_CUMPLIDO", "WIN", "TP"}:
            return True

        if estado in {"STOP_SALTADO", "LOSS", "SL"}:
            return False

        return bool(pd.notna(pnl) and float(pnl) > 0)

    cerradas["es_win"] = cerradas.apply(es_win, axis=1)

    total_cerradas = len(cerradas)
    wins = int(cerradas["es_win"].sum()) if total_cerradas else 0
    losses = total_cerradas - wins
    win_rate = (wins / total_cerradas * 100) if total_cerradas else None

    pnl_cerradas = pd.to_numeric(
        cerradas.get("pnl_actual_pct", pd.Series(dtype=float)),
        errors="coerce"
    ).dropna()

    pnl_medio = pnl_cerradas.mean() if not pnl_cerradas.empty else None
    pnl_mediana = pnl_cerradas.median() if not pnl_cerradas.empty else None

    ganancias = pnl_cerradas[pnl_cerradas > 0]
    perdidas = pnl_cerradas[pnl_cerradas < 0]

    avg_win = ganancias.mean() if not ganancias.empty else None
    avg_loss = perdidas.mean() if not perdidas.empty else None

    gross_profit = ganancias.sum() if not ganancias.empty else 0.0
    gross_loss = abs(perdidas.sum()) if not perdidas.empty else 0.0

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

    expectancy = pnl_medio

    # Última fotografía disponible al cierre de la semana.
    snapshot_fin = ultimo_snapshot_por_alerta(df, fin)

    activas = snapshot_fin[
        snapshot_fin["estado"].eq("ACTIVA")
    ].copy()

    pnl_activas = pd.to_numeric(
        activas.get("pnl_actual_pct", pd.Series(dtype=float)),
        errors="coerce"
    ).dropna()

    # Snapshot inicial de la semana.
    snapshot_inicio = (
        df[df["fecha_snapshot"] < inicio]
        .sort_values(["alerta_id", "fecha_snapshot"])
        .drop_duplicates("alerta_id", keep="last")
    )

    if snapshot_inicio.empty:
        snapshot_inicio = (
            df[df["fecha_snapshot"] >= inicio]
            .sort_values(["alerta_id", "fecha_snapshot"])
            .drop_duplicates("alerta_id", keep="first")
        )

    # Cambios de PnL de alertas que estaban activas tanto al inicio como al final.
    common_ids = set(snapshot_inicio["alerta_id"]).intersection(
        set(activas["alerta_id"])
    )

    delta_pnl_activos = None

    if common_ids:
        ini = snapshot_inicio[
            snapshot_inicio["alerta_id"].isin(common_ids)
        ][["alerta_id", "pnl_actual_pct"]].copy()

        fin_df = activas[
            activas["alerta_id"].isin(common_ids)
        ][["alerta_id", "pnl_actual_pct"]].copy()

        merged = ini.merge(
            fin_df,
            on="alerta_id",
            suffixes=("_inicio", "_fin")
        )

        if not merged.empty:
            delta = (
                pd.to_numeric(merged["pnl_actual_pct_fin"], errors="coerce")
                - pd.to_numeric(merged["pnl_actual_pct_inicio"], errors="coerce")
            ).dropna()

            if not delta.empty:
                delta_pnl_activos = delta.mean()

    # Estado de tesis: solo se puede aproximar con los estados disponibles.
    # La tabla backtesting_diario_alertas no contiene Estado_Estrategia.
    # Por ello NO inventamos TESIS_REFORZADA/DEBILITADA.
    score_actual = pd.to_numeric(
        activas.get("score_actual", pd.Series(dtype=float)),
        errors="coerce"
    ).dropna()

    rsi_actual = pd.to_numeric(
        activas.get("rsi_actual", pd.Series(dtype=float)),
        errors="coerce"
    ).dropna()

    rvol = None  # No existe en la estructura proporcionada.
    roc20 = None  # No existe en la estructura proporcionada.

    top_3 = (
        activas.sort_values("pnl_actual_pct", ascending=False)
        .head(3)
        .copy()
    )

    worst_3 = (
        activas.sort_values("pnl_actual_pct", ascending=True)
        .head(3)
        .copy()
    )

    # Distribución de estados al cierre.
    estado_counts = (
        snapshot_fin["estado"]
        .replace("", "SIN_ESTADO")
        .value_counts()
        .to_dict()
    )

    return {
        "inicio": inicio.isoformat(),
        "fin": fin.isoformat(),
        "total_operaciones_cerradas": total_cerradas,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "pnl_medio_cerradas": pnl_medio,
        "pnl_mediana_cerradas": pnl_mediana,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "posiciones_activas": len(activas),
        "pnl_medio_activas": pnl_activas.mean() if not pnl_activas.empty else None,
        "delta_pnl_medio_activas": delta_pnl_activos,
        "score_medio_activas": score_actual.mean() if not score_actual.empty else None,
        "rsi_medio_activas": rsi_actual.mean() if not rsi_actual.empty else None,
        "estado_counts": estado_counts,
        "top_3": dataframe_a_posiciones(top_3),
        "worst_3": dataframe_a_posiciones(worst_3),
        "cerradas": dataframe_a_cerradas(cerradas),
    }


def dataframe_a_posiciones(df: pd.DataFrame) -> List[Dict[str, Any]]:
    result = []

    for _, row in df.iterrows():
        result.append({
            "alerta_id": int(row["alerta_id"]) if pd.notna(row["alerta_id"]) else None,
            "ticker": safe_str(row.get("ticker")) or "N/D",
            "estado": safe_str(row.get("estado")) or "N/D",
            "pnl_pct": limpiar_numero(row.get("pnl_actual_pct")),
            "score": limpiar_numero(row.get("score_actual")),
            "rsi": limpiar_numero(row.get("rsi_actual")),
            "distancia_sl_pct": limpiar_numero(row.get("distancia_sl_pct")),
            "distancia_tp_pct": limpiar_numero(row.get("distancia_tp_pct")),
            "precio_actual": limpiar_numero(row.get("precio_actual"), 4),
            "precio_alerta": limpiar_numero(row.get("precio_alerta"), 4),
        })

    return result


def dataframe_a_cerradas(df: pd.DataFrame) -> List[Dict[str, Any]]:
    result = []

    for _, row in df.iterrows():
        result.append({
            "alerta_id": int(row["alerta_id"]) if pd.notna(row["alerta_id"]) else None,
            "ticker": safe_str(row.get("ticker")) or "N/D",
            "estado": safe_str(row.get("estado")) or "N/D",
            "pnl_pct": limpiar_numero(row.get("pnl_actual_pct")),
            "fecha_cierre_detectada": (
                row["fecha_snapshot"].isoformat()
                if pd.notna(row.get("fecha_snapshot"))
                else None
            ),
        })

    return result


# ============================================================
# MERCADO: BENCHMARK + HYGH
# ============================================================

def descargar_mercado_yfinance(
    inicio: date,
    fin: date
) -> Dict[str, Dict[str, Any]]:
    """
    Descarga datos semanales mediante yfinance.

    Se importa aquí para mantener la ejecución compatible con entornos
    donde el paquete esté instalado en GitHub Actions.
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning(
            "yfinance no está instalado. Se omitirá el benchmark de mercado."
        )
        return {}

    # Añadimos margen porque algunos índices tienen calendarios distintos.
    start = inicio - timedelta(days=5)
    end = fin + timedelta(days=2)

    result = {}

    for nombre, ticker in MARKET_TICKERS.items():
        try:
            df = yf.download(
                ticker,
                start=start.isoformat(),
                end=end.isoformat(),
                progress=False,
                auto_adjust=False,
                threads=False,
            )

            if df is None or df.empty:
                logger.warning("Sin datos para %s (%s)", nombre, ticker)
                continue

            if isinstance(df.columns, pd.MultiIndex):
                close = df["Close"].iloc[:, 0]
            else:
                close = df["Close"]

            close = pd.to_numeric(close, errors="coerce").dropna()

            if close.empty:
                continue

            close.index = pd.to_datetime(close.index).tz_localize(None)

            inicio_ts = pd.Timestamp(inicio)
            fin_ts = pd.Timestamp(fin)

            semana = close[
                (close.index >= inicio_ts)
                & (close.index <= fin_ts + pd.Timedelta(days=1))
            ]

            # Para índices/ETFs se usa el primer y último cierre disponible.
            if len(semana) >= 2:
                first = float(semana.iloc[0])
                last = float(semana.iloc[-1])
                weekly_return = ((last / first) - 1) * 100
            else:
                weekly_return = None

            # Volatilidad aproximada semanal a partir de retornos diarios.
            daily_returns = close.pct_change().dropna() * 100
            daily_week = daily_returns[
                (daily_returns.index >= inicio_ts)
                & (daily_returns.index <= fin_ts + pd.Timedelta(days=1))
            ]

            volatility = (
                float(daily_week.std())
                if len(daily_week) >= 2
                else None
            )

            result[nombre] = {
                "ticker": ticker,
                "close_inicio": float(semana.iloc[0]) if not semana.empty else None,
                "close_fin": float(semana.iloc[-1]) if not semana.empty else None,
                "weekly_return_pct": weekly_return,
                "daily_volatility_pct": volatility,
            }

        except Exception as exc:
            logger.warning(
                "Error descargando %s (%s): %s",
                nombre,
                ticker,
                exc
            )

    return result


# ============================================================
# CONTEXTO DE NOTICIAS
# ============================================================

def obtener_noticias_semana(
    inicio: date,
    fin: date,
    max_items: int = NEWS_MAX_ITEMS
) -> List[Dict[str, str]]:
    """
    Obtiene titulares mediante Google News RSS.

    La IA recibe titulares/enlaces como contexto, no se le pide que
    invente el contexto macro de la semana.
    """
    queries = [
        "stock market S&P Nasdaq Europe markets economy",
        "Federal Reserve ECB interest rates inflation markets",
        "credit high yield HYGH liquidity spreads",
        "oil gold bonds currencies markets",
    ]

    noticias = []
    vistos = set()

    for query in queries:
        url = (
            "https://news.google.com/rss/search?"
            f"q={quote(query)}"
            f"&hl=en-US&gl=US&ceid=US:en"
        )

        try:
            response = requests.get(
                url,
                timeout=NEWS_TIMEOUT,
                headers={"User-Agent": "AluraQuantNewsletter/1.0"}
            )
            response.raise_for_status()

            root = ET.fromstring(response.content)

            for item in root.findall(".//item"):
                title = safe_str(item.findtext("title"))
                link = safe_str(item.findtext("link"))
                pub_date = safe_str(item.findtext("pubDate"))

                if not title or title in vistos:
                    continue

                published = ""
                if pub_date:
                    try:
                        published = parsedate_to_datetime(pub_date).date().isoformat()
                    except Exception:
                        published = pub_date

                # Intentamos filtrar por semana. Si Google RSS no aporta
                # una fecha interpretable, conservamos el titular.
                if published and re.match(r"^\d{4}-\d{2}-\d{2}$", published):
                    pub = date.fromisoformat(published)
                    if pub < inicio - timedelta(days=1) or pub > fin + timedelta(days=2):
                        continue

                noticias.append({
                    "title": title,
                    "link": link,
                    "published": published,
                })
                vistos.add(title)

                if len(noticias) >= max_items:
                    return noticias

        except Exception as exc:
            logger.warning("No se pudieron obtener noticias para '%s': %s", query, exc)

    return noticias[:max_items]


# ============================================================
# CONTEXTO PARA IA
# ============================================================

def construir_contexto_ia(
    metricas: Dict[str, Any],
    mercado: Dict[str, Dict[str, Any]],
    noticias: List[Dict[str, str]]
) -> Dict[str, Any]:

    return {
        "periodo": {
            "inicio": metricas["inicio"],
            "fin": metricas["fin"],
        },
        "cartera": {
            "operaciones_cerradas": metricas["total_operaciones_cerradas"],
            "wins": metricas["wins"],
            "losses": metricas["losses"],
            "win_rate_pct": limpiar_numero(metricas["win_rate"]),
            "pnl_medio_operacion_cerrada_pct": limpiar_numero(
                metricas["pnl_medio_cerradas"]
            ),
            "pnl_mediana_operacion_cerrada_pct": limpiar_numero(
                metricas["pnl_mediana_cerradas"]
            ),
            "average_win_pct": limpiar_numero(metricas["avg_win"]),
            "average_loss_pct": limpiar_numero(metricas["avg_loss"]),
            "profit_factor": limpiar_numero(metricas["profit_factor"]),
            "expectancy_pct": limpiar_numero(metricas["expectancy"]),
            "posiciones_activas_al_cierre": metricas["posiciones_activas"],
            "pnl_medio_posiciones_activas_pct": limpiar_numero(
                metricas["pnl_medio_activas"]
            ),
            "cambio_medio_pnl_posiciones_activas_pct": limpiar_numero(
                metricas["delta_pnl_medio_activas"]
            ),
            "score_medio_posiciones_activas": limpiar_numero(
                metricas["score_medio_activas"]
            ),
            "rsi_medio_posiciones_activas": limpiar_numero(
                metricas["rsi_medio_activas"]
            ),
            "distribucion_estados": metricas["estado_counts"],
        },
        "mejores_posiciones_activas": metricas["top_3"],
        "posiciones_a_vigilar": metricas["worst_3"],
        "operaciones_cerradas": metricas["cerradas"],
        "benchmark": mercado,
        "noticias_semana": noticias,
        "limitaciones_datos": [
            "La tabla backtesting_diario_alertas no contiene RVOL.",
            "La tabla backtesting_diario_alertas no contiene ROC20.",
            "La tabla backtesting_diario_alertas no contiene Estado_Estrategia.",
            "No se utilizan MAE ni MFE en el newsletter.",
            "No se infiere una rentabilidad monetaria de cartera porque no se proporciona tamaño/peso de posición."
        ],
    }


# ============================================================
# IA
# ============================================================

def generar_analisis_ia(contexto: Dict[str, Any]) -> Dict[str, Any]:
    """
    La IA genera narrativa estructurada.
    NO genera HTML.
    """
    client = cliente_ia()

    system_prompt = """
Eres el analista cuantitativo senior de Alura Quant.

Tu trabajo es transformar datos reales de mercado y de la cartera en
un informe semanal profesional.

REGLAS:
1. Utiliza únicamente los datos proporcionados.
2. No inventes cifras, movimientos de mercado, noticias, indicadores
   ni acontecimientos.
3. Si un dato no está disponible, indícalo de forma natural.
4. Diferencia claramente hechos de interpretación.
5. El contexto de mercado debe resumir los principales acontecimientos
   de la semana a partir de los titulares proporcionados.
6. HYGH debe tratarse como referencia del segmento high yield/crédito
   y de las condiciones de riesgo/liquidez, NO como un indicador puro
   de liquidez.
7. No uses MAE ni MFE.
8. No conviertas PnL medio por operación en rentabilidad total de cartera.
9. No hagas recomendaciones personalizadas de compra/venta.
10. Las posiciones "a vigilar" no deben calificarse automáticamente
    como malas: explica si el deterioro se observa en PnL, RSI, Score,
    distancia a SL/TP u otros datos disponibles.
11. No inventes un Estado_Estrategia porque no existe en esta tabla.
12. Escribe en español, con tono financiero profesional, claro y sobrio.

Devuelve exclusivamente JSON válido con esta estructura:

{
  "executive_summary": "3-5 frases",
  "market_context": "2-4 párrafos breves",
  "portfolio_analysis": "2-4 párrafos breves",
  "best_positions_analysis": [
    {
      "ticker": "...",
      "analysis": "..."
    }
  ],
  "watchlist_analysis": [
    {
      "ticker": "...",
      "analysis": "..."
    }
  ],
  "risk_monitor": "1-3 párrafos",
  "next_week_outlook": "2-4 párrafos",
  "key_takeaways": [
    "...",
    "...",
    "..."
  ]
}
"""

    user_prompt = (
        "DATOS DE LA SEMANA:\n"
        + json.dumps(contexto, ensure_ascii=False, indent=2, default=str)
        + "\n\n"
        "Redacta el análisis semanal siguiendo exactamente las reglas anteriores."
    )

    logger.info("Generando análisis con %s...", MODELO_GEMINI)

    response = client.chat.completions.create(
        model=MODELO_GEMINI,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or "{}"

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Fallback por si el proveedor devuelve markdown.
        cleaned = (
            content
            .replace("```json", "")
            .replace("```", "")
            .strip()
        )
        return json.loads(cleaned)


# ============================================================
# HTML
# ============================================================

def esc(value: Any) -> str:
    return html.escape(safe_str(value))


def render_market_table(mercado: Dict[str, Dict[str, Any]]) -> str:
    rows = []

    order = [
        "S&P 500",
        "Nasdaq 100",
        "Euro Stoxx 50",
        "IBEX 35",
        "HYGH",
        "VIX",
        "EUR/USD",
    ]

    for nombre in order:
        data = mercado.get(nombre)
        if not data:
            continue

        rows.append(
            f"""
            <tr>
                <td>{esc(nombre)}</td>
                <td style="text-align:right;font-weight:600;">
                    {esc(fmt_pct(data.get("weekly_return_pct")))}
                </td>
            </tr>
            """
        )

    if not rows:
        return "<p>No se han podido recuperar datos de benchmark para esta semana.</p>"

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;margin:14px 0 8px 0;">
        <thead>
            <tr>
                <th align="left" style="padding:9px;border-bottom:1px solid #e2e8f0;color:#64748b;font-size:12px;text-transform:uppercase;">
                    Indicador
                </th>
                <th align="right" style="padding:9px;border-bottom:1px solid #e2e8f0;color:#64748b;font-size:12px;text-transform:uppercase;">
                    Semana
                </th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
    <p style="font-size:12px;color:#64748b;margin-top:4px;">
        HYGH se utiliza como referencia del segmento high yield/crédito y de las
        condiciones de riesgo, no como medida directa y aislada de liquidez.
    </p>
    """


def render_positions_table(
    positions: List[Dict[str, Any]],
    title: str
) -> str:

    if not positions:
        return f"""
        <h3 style="margin:20px 0 8px;color:#1e293b;">{esc(title)}</h3>
        <p style="color:#64748b;">No hay posiciones disponibles para este apartado.</p>
        """

    rows = []

    for p in positions:
        pnl = p.get("pnl_pct")
        pnl_display = fmt_pct(pnl)

        score = fmt_num(p.get("score"))
        rsi = fmt_num(p.get("rsi"))
        sl = fmt_pct(p.get("distancia_sl_pct"))
        tp = fmt_pct(p.get("distancia_tp_pct"))

        rows.append(
            f"""
            <tr>
                <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;font-weight:700;">
                    {esc(p.get("ticker"))}
                </td>
                <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;text-align:right;">
                    {esc(pnl_display)}
                </td>
                <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;text-align:right;">
                    {esc(score)}
                </td>
                <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;text-align:right;">
                    {esc(rsi)}
                </td>
                <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;text-align:right;">
                    {esc(sl)}
                </td>
                <td style="padding:10px 8px;border-bottom:1px solid #e2e8f0;text-align:right;">
                    {esc(tp)}
                </td>
            </tr>
            """
        )

    return f"""
    <h3 style="margin:20px 0 8px;color:#1e293b;">{esc(title)}</h3>

    <table width="100%" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse;">
        <thead>
            <tr>
                <th align="left" style="padding:8px;color:#64748b;font-size:11px;text-transform:uppercase;">Activo</th>
                <th align="right" style="padding:8px;color:#64748b;font-size:11px;text-transform:uppercase;">PnL</th>
                <th align="right" style="padding:8px;color:#64748b;font-size:11px;text-transform:uppercase;">Score</th>
                <th align="right" style="padding:8px;color:#64748b;font-size:11px;text-transform:uppercase;">RSI</th>
                <th align="right" style="padding:8px;color:#64748b;font-size:11px;text-transform:uppercase;">SL</th>
                <th align="right" style="padding:8px;color:#64748b;font-size:11px;text-transform:uppercase;">TP</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
    """


def render_analysis_list(
    title: str,
    analyses: List[Dict[str, Any]]
) -> str:

    if not analyses:
        return ""

    blocks = []

    for item in analyses:
        ticker = esc(item.get("ticker"))
        analysis = esc(item.get("analysis")).replace("\n", "<br>")

        blocks.append(
            f"""
            <div style="margin:12px 0;padding:12px 14px;background:#f8fafc;border-radius:8px;">
                <div style="font-weight:700;color:#1e293b;margin-bottom:5px;">
                    {ticker}
                </div>
                <div style="font-size:14px;line-height:1.55;color:#475569;">
                    {analysis}
                </div>
            </div>
            """
        )

    return f"""
    <h3 style="margin:22px 0 10px;color:#1e293b;">{esc(title)}</h3>
    {''.join(blocks)}
    """


def generar_html_newsletter(
    metricas: Dict[str, Any],
    mercado: Dict[str, Dict[str, Any]],
    analisis: Dict[str, Any],
    inicio: date,
    fin: date
) -> str:

    summary = esc(analisis.get("executive_summary", ""))
    market_context = esc(analisis.get("market_context", "")).replace("\n", "<br><br>")
    portfolio_analysis = esc(analisis.get("portfolio_analysis", "")).replace("\n", "<br><br>")
    risk_monitor = esc(analisis.get("risk_monitor", "")).replace("\n", "<br><br>")
    next_week = esc(analisis.get("next_week_outlook", "")).replace("\n", "<br><br>")

    active = metricas["posiciones_activas"]
    closed = metricas["total_operaciones_cerradas"]
    win_rate = metricas["win_rate"]

    pnl_mean = metricas["pnl_medio_cerradas"]
    pf = metricas["profit_factor"]
    expectancy = metricas["expectancy"]

    key_takeaways = analisis.get("key_takeaways", []) or []
    takeaway_html = "".join(
        f"<li style='margin-bottom:7px;'>{esc(item)}</li>"
        for item in key_takeaways[:5]
    )

    market_html = render_market_table(mercado)

    top_html = render_positions_table(
        metricas["top_3"],
        "Posiciones activas destacadas"
    )

    watch_html = render_positions_table(
        metricas["worst_3"],
        "Posiciones a vigilar"
    )

    best_analysis_html = render_analysis_list(
        "Lectura de las posiciones destacadas",
        analisis.get("best_positions_analysis", [])
    )

    watch_analysis_html = render_analysis_list(
        "Lectura de las posiciones a vigilar",
        analisis.get("watchlist_analysis", [])
    )

    return f"""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Alura Quant — Weekly Intelligence</title>
</head>

<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#1e293b;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;">
<tr>
<td align="center" style="padding:28px 12px;">

<table width="680" cellpadding="0" cellspacing="0"
       style="max-width:680px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;">

<!-- HEADER -->
<tr>
<td style="background:#1e293b;padding:30px 32px;color:#ffffff;">
    <div style="font-size:12px;letter-spacing:1.5px;text-transform:uppercase;color:#cbd5e1;">
        Alura Quant
    </div>
    <div style="font-size:27px;font-weight:700;margin-top:7px;">
        Weekly Intelligence
    </div>
    <div style="font-size:13px;color:#cbd5e1;margin-top:8px;">
        {esc(inicio.strftime("%d/%m/%Y"))} — {esc(fin.strftime("%d/%m/%Y"))}
    </div>
</td>
</tr>

<!-- EXECUTIVE SUMMARY -->
<tr>
<td style="padding:28px 32px 10px;">
    <div style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#64748b;font-weight:700;">
        Resumen ejecutivo
    </div>

    <p style="font-size:16px;line-height:1.65;color:#334155;margin:12px 0 0;">
        {summary}
    </p>
</td>
</tr>

<!-- KPIs -->
<tr>
<td style="padding:16px 32px 20px;">

<table width="100%" cellpadding="0" cellspacing="0">
<tr>
<td width="25%" style="padding:12px 6px;background:#f8fafc;border-radius:8px;">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Cerradas</div>
    <div style="font-size:23px;font-weight:700;margin-top:5px;">{closed}</div>
</td>
<td width="25%" style="padding:12px 6px 12px 12px;">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Win Rate</div>
    <div style="font-size:23px;font-weight:700;margin-top:5px;">{esc(fmt_pct(win_rate))}</div>
</td>
<td width="25%" style="padding:12px 6px 12px 12px;">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;">Activas</div>
    <div style="font-size:23px;font-weight:700;margin-top:5px;">{active}</div>
</td>
<td width="25%" style="padding:12px 6px 12px 12px;">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;">PnL medio</div>
    <div style="font-size:23px;font-weight:700;margin-top:5px;">{esc(fmt_pct(pnl_mean))}</div>
</td>
</tr>
</table>

<div style="margin-top:12px;font-size:12px;color:#64748b;">
    Profit Factor: <strong>{esc(fmt_num(pf))}</strong>
    &nbsp;·&nbsp;
    Expectancy media: <strong>{esc(fmt_pct(expectancy))}</strong>
</div>

</td>
</tr>

<!-- MARKET -->
<tr>
<td style="padding:8px 32px 20px;">
    <h2 style="font-size:19px;margin:12px 0;color:#1e293b;">
        Contexto de mercado
    </h2>

    <p style="font-size:14px;line-height:1.65;color:#475569;">
        {market_context}
    </p>

    {market_html}
</td>
</tr>

<!-- PORTFOLIO -->
<tr>
<td style="padding:20px 32px;">
    <h2 style="font-size:19px;margin:0 0 10px;color:#1e293b;">
        Radiografía de cartera
    </h2>

    <p style="font-size:14px;line-height:1.65;color:#475569;">
        {portfolio_analysis}
    </p>
</td>
</tr>

<!-- POSITIONS -->
<tr>
<td style="padding:4px 32px 20px;">
    {top_html}
    {best_analysis_html}

    {watch_html}
    {watch_analysis_html}
</td>
</tr>

<!-- RISK -->
<tr>
<td style="padding:20px 32px;background:#f8fafc;">
    <h2 style="font-size:19px;margin:0 0 10px;color:#1e293b;">
        Monitor de riesgo
    </h2>

    <p style="font-size:14px;line-height:1.65;color:#475569;margin-bottom:0;">
        {risk_monitor}
    </p>
</td>
</tr>

<!-- OUTLOOK -->
<tr>
<td style="padding:24px 32px 20px;">
    <h2 style="font-size:19px;margin:0 0 10px;color:#1e293b;">
        Próxima semana
    </h2>

    <p style="font-size:14px;line-height:1.65;color:#475569;">
        {next_week}
    </p>

    <h3 style="font-size:15px;margin:22px 0 9px;color:#1e293b;">
        Puntos clave
    </h3>

    <ul style="padding-left:20px;font-size:14px;line-height:1.55;color:#475569;">
        {takeaway_html}
    </ul>
</td>
</tr>

<!-- FOOTER -->
<tr>
<td style="padding:20px 32px;background:#1e293b;color:#cbd5e1;font-size:11px;line-height:1.55;">
    <strong style="color:#ffffff;">Alura Quant</strong><br>
    Informe generado automáticamente a partir de snapshots históricos
    de <em>backtesting_diario_alertas</em> y datos de mercado de referencia.
    Este informe es informativo y no constituye asesoramiento financiero.
</td>
</tr>

</table>

</td>
</tr>
</table>

</body>
</html>
"""


# ============================================================
# ENVÍO
# ============================================================

def enviar_correo(
    html_content: str,
    destinatarios: List[str],
    inicio: date,
    fin: date
) -> None:

    if not destinatarios:
        logger.warning("No hay destinatarios.")
        return

    asunto = (
        f"Alura Quant | Weekly Intelligence "
        f"— {inicio.strftime('%d/%m')} → {fin.strftime('%d/%m/%Y')}"
    )

    params = {
        "from": os.getenv(
            "RESEND_FROM",
            "Alura Quant <onboarding@resend.dev>"
        ),
        "to": destinatarios,
        "subject": asunto,
        "html": html_content,
    }

    try:
        response = resend.Emails.send(params)
        logger.info(
            "Newsletter enviada correctamente. Respuesta Resend: %s",
            response
        )
    except Exception as exc:
        logger.exception("Error enviando newsletter: %s", exc)
        raise


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    inicio, fin = semana_referencia()

    logger.info(
        "Preparando Alura Quant Weekly Intelligence: %s → %s",
        inicio,
        fin
    )

    destinatarios = obtener_suscriptores()

    if not destinatarios:
        logger.info("No hay suscriptores. Proceso finalizado.")
        return

    # 1. Histórico de snapshots.
    df_backtest = obtener_backtesting(inicio, fin)

    # 2. Métricas deterministas de cartera.
    metricas = construir_metricas_cartera(
        df_backtest,
        inicio,
        fin
    )

    # 3. Benchmark y contexto de mercado.
    mercado = descargar_mercado_yfinance(inicio, fin)

    # 4. Titulares de la semana.
    noticias = obtener_noticias_semana(inicio, fin)

    # 5. Contexto estructurado para la IA.
    contexto = construir_contexto_ia(
        metricas,
        mercado,
        noticias
    )

    # 6. IA: únicamente narrativa/análisis.
    analisis = generar_analisis_ia(contexto)

    # 7. Python: HTML determinista.
    html_content = generar_html_newsletter(
        metricas,
        mercado,
        analisis,
        inicio,
        fin
    )

    # 8. Envío.
    enviar_correo(
        html_content,
        destinatarios,
        inicio,
        fin
    )

    logger.info("Newsletter completada correctamente.")


if __name__ == "__main__":
    main()
