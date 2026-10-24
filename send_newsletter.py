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

# Activar para enviar únicamente al correo de pruebas. Cambiar a False para
# volver al envío a todos los suscriptores de Supabase.
MODO_PRUEBAS = False
CORREO_PRUEBAS = "adelgadosanz@gmail.com"

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
    Devuelve el periodo de la semana en curso, desde el lunes hasta hoy,
    incluyendo el sábado o domingo si se ejecuta durante el fin de semana.
    """
    hoy = hoy or datetime.now().date()
    lunes = hoy - timedelta(days=hoy.weekday())
    return lunes, hoy


def limpiar_numero(value: Any, decimals: int = 2) -> Optional[float]:
    if value is None or pd.isna(value):
        return None

    try:
        return round(float(value), decimals)
    except (ValueError, TypeError):
        return None


def fmt_pct(value: Any, decimals: int = 1) -> str:
    number = limpiar_numero(value, decimals)
    if number is None:
        return "N/D"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.{decimals}f}".replace(".", ",") + " %"


def fmt_num(value: Any, decimals: int = 2) -> str:
    number = limpiar_numero(value, decimals)
    return "N/D" if number is None else f"{number:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_eur(value: Any, decimals: int = 2) -> str:
    number = limpiar_numero(value, decimals)
    if number is None:
        return "N/D"
    sign = "+" if number > 0 else ""
    formatted = f"{abs(number):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if number < 0:
        sign = "−"
    return f"{sign}{formatted} €"


def formato_texto_es(text: Any) -> str:
    """Ajusta cifras porcentuales generadas por IA al formato español y a un decimal."""
    value = safe_str(text)
    replacements = [
        (r"\bPnL\b", "resultado"),
        (r"\bwin\s*rate\b", "tasa de acierto"),
        (r"\bprofit\s*factor\b", "factor de beneficio"),
        (r"\bexpectancy\b", "resultado medio"),
        (r"\bbreak\s*even\b|\bbreakeven\b", "equilibrio"),
        (r"\bscore\b", "puntuación interna"),
    ]
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    value = re.sub(
        r"(?<![\w/])([+-]?\d{1,3}(?:[.,]\d+)?)(\s*%)",
        lambda match: f"{float(match.group(1).replace(',', '.')):.1f}".replace(".", ",") + " %",
        value,
    )
    return re.sub(
        r"(?<![\w/])([+-]?\d{1,3}(?:[.,]\d{1,2})?)\s*(€|euros?)(?!\w)",
        lambda match: fmt_eur(float(match.group(1).replace(',', '.'))),
        value,
        flags=re.IGNORECASE,
    )


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

    page_size = 1000
    offset = 0
    snapshot_rows = []
    while True:
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
            .order("id", desc=False)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        page = response.data or []
        snapshot_rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    logger.info(
        "Snapshots recuperados: %s filas, desde %s hasta %s.",
        len(snapshot_rows), desde, hasta
    )
    df = pd.DataFrame(snapshot_rows)

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

    # Carga nominal, riesgo y resultado R para calcular el PnL monetario real.
    df["resultado_r"] = float("nan")
    df["riesgo_euros"] = float("nan")
    df["nominal"] = float("nan")
    alerta_ids = df["alerta_id"].astype(int).unique().tolist()
    try:
        datos_historial = []
        for inicio_lote in range(0, len(alerta_ids), 200):
            lote = alerta_ids[inicio_lote:inicio_lote + 200]
            response_historial = (
                supabase.table("historial_alertas")
                .select("id,nominal,riesgo_euros,resultado_r")
                .in_("id", lote)
                .execute()
            )
            datos_historial.extend(response_historial.data or [])
        historial_por_id = {
            int(row["id"]): row
            for row in datos_historial if row.get("id") is not None
        }
        df["resultado_r"] = df["alerta_id"].astype(int).map(
            lambda alerta_id: pd.to_numeric(
                historial_por_id.get(alerta_id, {}).get("resultado_r"), errors="coerce"
            )
        )
        df["riesgo_euros"] = df["alerta_id"].astype(int).map(
            lambda alerta_id: pd.to_numeric(
                historial_por_id.get(alerta_id, {}).get("riesgo_euros"), errors="coerce"
            )
        )
        df["nominal"] = df["alerta_id"].astype(int).map(
            lambda alerta_id: pd.to_numeric(
                historial_por_id.get(alerta_id, {}).get("nominal"), errors="coerce"
            )
        )
    except Exception as e:
        logger.warning(
            "No se pudieron recuperar nominal, riesgo_euros y resultado_r de historial_alertas: %s",
            e
        )

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
    """
    df = df.sort_values(["alerta_id", "fecha_snapshot"]).copy()

    # Reproducir los filtros SQL de los snapshots sin deduplicar filas:
    # cerradas = estado distinto de ACTIVA entre lunes y viernes;
    # abiertas = estado ACTIVA en el snapshot exacto del viernes.
    viernes_referencia = fin - timedelta(days=max(0, fin.weekday() - 4))
    snapshots_semana = df[
        (df["fecha_snapshot"] >= inicio)
        & (df["fecha_snapshot"] <= viernes_referencia)
    ].copy()

    cerradas = snapshots_semana[
        snapshots_semana["estado"].notna()
        & snapshots_semana["estado"].ne("")
        & snapshots_semana["estado"].ne("ACTIVA")
    ].copy()
    activas = df[
        (df["fecha_snapshot"] == viernes_referencia)
        & (df["estado"].eq("ACTIVA"))
    ].copy()

    cerradas["resultado_r"] = pd.to_numeric(
        cerradas.get("resultado_r", pd.Series(index=cerradas.index, dtype=float)),
        errors="coerce"
    )
    cerradas["riesgo_euros"] = pd.to_numeric(
        cerradas.get("riesgo_euros", pd.Series(index=cerradas.index, dtype=float)),
        errors="coerce"
    )
    cerradas["nominal"] = pd.to_numeric(
        cerradas.get("nominal", pd.Series(index=cerradas.index, dtype=float)),
        errors="coerce"
    )
    cerradas["pnl_euros"] = cerradas["riesgo_euros"] * cerradas["resultado_r"]
    cerradas["pnl_actual_pct"] = (
        cerradas["pnl_euros"] / cerradas["nominal"].replace(0, float("nan")) * 100
    )

    activas["nominal"] = pd.to_numeric(
        activas.get("nominal", pd.Series(index=activas.index, dtype=float)),
        errors="coerce"
    )
    activas["pnl_actual_pct"] = pd.to_numeric(
        activas.get("pnl_actual_pct", pd.Series(index=activas.index, dtype=float)),
        errors="coerce"
    )
    activas["pnl_euros"] = activas["nominal"] * activas["pnl_actual_pct"] / 100

    # Se mantienen los conteos de snapshots solicitados (13 cerradas y 174 activas).
    # Para rendimientos y ratios se usan solo filas con los datos monetarios necesarios.
    cerradas_validas = cerradas.dropna(subset=["pnl_euros", "nominal"]).copy()
    activas_validas = activas.dropna(subset=["pnl_euros", "nominal"]).copy()

    def rendimiento_ponderado(frame: pd.DataFrame) -> Optional[float]:
        if frame.empty:
            return None
        nominal_total = pd.to_numeric(frame["nominal"], errors="coerce").sum()
        pnl_total = pd.to_numeric(frame["pnl_euros"], errors="coerce").sum()
        if not nominal_total or pd.isna(nominal_total):
            return None
        return float(pnl_total / nominal_total * 100)

    total_cerradas = len(cerradas)
    resultado_cerradas = cerradas_validas["pnl_euros"]
    break_even_mask = resultado_cerradas.abs() <= 1e-9
    break_even = int(break_even_mask.sum())
    wins_mask = resultado_cerradas > 1e-9
    losses_mask = resultado_cerradas < -1e-9
    wins = int(wins_mask.sum())
    losses = int(losses_mask.sum())
    operaciones_con_resultado = wins + losses
    win_rate = (
        wins / operaciones_con_resultado * 100
        if operaciones_con_resultado else None
    )

    pnl_cerradas = pd.to_numeric(
        cerradas_validas["pnl_actual_pct"], errors="coerce"
    ).dropna()
    pnl_mediana = pnl_cerradas.median() if not pnl_cerradas.empty else None
    pnl_medio = rendimiento_ponderado(cerradas_validas)

    ganadoras = cerradas_validas.loc[wins_mask]
    perdedoras = cerradas_validas.loc[losses_mask]
    avg_win = rendimiento_ponderado(ganadoras)
    avg_loss = rendimiento_ponderado(perdedoras)

    gross_profit = float(ganadoras["pnl_euros"].sum()) if not ganadoras.empty else 0.0
    gross_loss = abs(float(perdedoras["pnl_euros"].sum())) if not perdedoras.empty else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    expectancy = pnl_medio

    pnl_activas = pd.to_numeric(
        activas_validas["pnl_actual_pct"], errors="coerce"
    ).dropna()
    combined = pd.concat([cerradas_validas, activas_validas], ignore_index=True)
    pnl_medio_combinado = rendimiento_ponderado(combined)
    pnl_cerradas_eur = float(cerradas_validas["pnl_euros"].sum()) if not cerradas_validas.empty else 0.0
    pnl_activas_eur = float(activas_validas["pnl_euros"].sum()) if not activas_validas.empty else 0.0
    pnl_total_eur = pnl_cerradas_eur + pnl_activas_eur
    nominal_total_eur = float(combined["nominal"].sum()) if not combined.empty else 0.0

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

    common_ids = set(snapshot_inicio["alerta_id"]).intersection(
        set(activas["alerta_id"])
    )

    delta_pnl_activos = None

    if common_ids:
        ini = snapshot_inicio[
            snapshot_inicio["alerta_id"].isin(common_ids)
        ][["alerta_id", "pnl_actual_pct", "nominal"]].copy()

        fin_df = activas[
            activas["alerta_id"].isin(common_ids)
        ][["alerta_id", "pnl_actual_pct", "nominal"]].copy()

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
                nominal_fin = pd.to_numeric(merged["nominal_fin"], errors="coerce")
                delta_fin = (
                    pd.to_numeric(merged["pnl_actual_pct_fin"], errors="coerce")
                    - pd.to_numeric(merged["pnl_actual_pct_inicio"], errors="coerce")
                )
                delta_frame = pd.DataFrame({
                    "nominal": nominal_fin,
                    "pnl_euros": nominal_fin * delta_fin / 100,
                }).dropna()
                delta_pnl_activos = (
                    rendimiento_ponderado(delta_frame)
                    if not delta_frame.empty else None
                )

    score_actual = pd.to_numeric(
        activas.get("score_actual", pd.Series(dtype=float)),
        errors="coerce"
    ).dropna()

    rsi_actual = pd.to_numeric(
        activas.get("rsi_actual", pd.Series(dtype=float)),
        errors="coerce"
    ).dropna()

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

    snapshots_seleccionados = pd.concat(
        [cerradas, activas], ignore_index=True
    )
    estado_counts = (
        snapshots_seleccionados["estado"]
        .replace("", "SIN_ESTADO")
        .value_counts()
        .to_dict()
    )

    return {
        "inicio": inicio.isoformat(),
        "fin": fin.isoformat(),
        "total_operaciones_cerradas": total_cerradas,
        "wins": wins,
        "break_even": break_even,
        "losses": losses,
        "win_rate": win_rate,
        "pnl_medio_cerradas": pnl_medio,
        "pnl_mediana_cerradas": pnl_mediana,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "expectancy": expectancy,
        "posiciones_activas": len(activas),
        "pnl_medio_activas": rendimiento_ponderado(activas_validas),
        "pnl_medio_combinado": pnl_medio_combinado,
        "pnl_cerradas_eur": pnl_cerradas_eur,
        "pnl_activas_eur": pnl_activas_eur,
        "pnl_total_eur": pnl_total_eur,
        "nominal_total_eur": nominal_total_eur,
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
    try:
        import yfinance as yf
    except ImportError:
        logger.warning(
            "yfinance no está instalado. Se omitirá el benchmark de mercado."
        )
        return {}

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

            if len(semana) >= 2:
                first = float(semana.iloc[0])
                last = float(semana.iloc[-1])
                weekly_return = ((last / first) - 1) * 100
            else:
                weekly_return = None

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
            logger.warning("Error descargando %s (%s): %s", nombre, ticker, exc)

    return result


# ============================================================
# CONTEXTO DE NOTICIAS
# ============================================================

def obtener_noticias_semana(
    inicio: date,
    fin: date,
    max_items: int = NEWS_MAX_ITEMS
) -> List[Dict[str, str]]:
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
            "breakeven": metricas["break_even"],
            "tasa_acierto_operaciones_cerradas_pct": limpiar_numero(metricas["win_rate"], 1),
            "rendimiento_ponderado_operaciones_cerradas_pct": limpiar_numero(
                metricas["pnl_medio_cerradas"]
            ),
            "pnl_mediana_operacion_cerrada_pct": limpiar_numero(
                metricas["pnl_mediana_cerradas"]
            ),
            "rendimiento_ponderado_ganadoras_pct": limpiar_numero(metricas["avg_win"], 1),
            "rendimiento_ponderado_perdedoras_pct": limpiar_numero(metricas["avg_loss"], 1),
            "factor_beneficio": limpiar_numero(metricas["profit_factor"]),
        "resultado_cerrado_eur": limpiar_numero(metricas["pnl_cerradas_eur"]),
        "resultado_abierto_no_realizado_eur": limpiar_numero(metricas["pnl_activas_eur"]),
        "resultado_conjunto_eur": limpiar_numero(metricas["pnl_total_eur"]),
        "nominal_conjunto_eur": limpiar_numero(metricas["nominal_total_eur"]),
            "posiciones_activas_al_cierre": metricas["posiciones_activas"],
            "rendimiento_ponderado_posiciones_abiertas_pct": limpiar_numero(
                metricas["pnl_medio_activas"]
            ),
            "rendimiento_ponderado_conjunto_pct": limpiar_numero(
                metricas["pnl_medio_combinado"]
            ),
            "pnl_medio_combinado_cerrado_y_abierto_pct": limpiar_numero(
                metricas["pnl_medio_combinado"]
            ),
            "cambio_ponderado_posiciones_abiertas_pct": limpiar_numero(
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
            "El resultado de posiciones abiertas es provisional y puede cambiar mientras sigan abiertas."
        ],
    }


# ============================================================
# IA
# ============================================================

def generar_analisis_ia(contexto: Dict[str, Any]) -> Dict[str, Any]:
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
10. distancia_sl_pct es la distancia al stop vigente y puede reflejar protección en breakeven; no la presentes como riesgo inicial.
11. Las salidas con resultado_r = 0 son breakeven, no pérdidas.
12. Las posiciones "a vigilar" no deben calificarse automáticamente
    como malas: explica si el deterioro se observa en PnL, RSI, Score,
    distancia a SL/TP u otros datos disponibles.
13. No inventes un Estado_Estrategia porque no existe en esta tabla.
14. Escribe en español de España, con tono claro, cercano y profesional para lectores con conocimientos financieros básicos.
15. Evita las siglas PnL, win rate, breakeven y expectancy. Usa resultado en euros, tasa de acierto, equilibrio y resultado medio.
16. No repitas ni recalcules en el texto el resultado cerrado, abierto, conjunto ni los porcentajes de cartera: se muestran en tarjetas y pueden cambiar por redondeo.
17. Cuando menciones porcentajes de mercado, usa como máximo un decimal. Usa coma decimal y añade espacio antes de %.
18. Explica términos como stop, score o RSI con palabras sencillas cuando sean necesarios.

Devuelve exclusivamente JSON válido con esta estructura:

{
        "executive_summary": "2-3 frases, sin repetir cifras monetarias ni porcentajes de la cartera",
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


def render_market_table(
    mercado: Dict[str, Dict[str, Any]],
    metricas: Optional[Dict[str, Any]] = None
) -> str:
    rows = []
    if metricas is not None:
        rows.append(
            f"""
            <tr style="background:#fff3bf;">
                <td style="padding:10px 9px;border-bottom:1px solid #f1df91;font-weight:700;color:#1e293b;">
                    Resultado Alura Quant
                </td>
                <td style="padding:10px 9px;text-align:right;border-bottom:1px solid #f1df91;font-weight:700;color:#1e293b;">
                    {esc(fmt_pct(metricas.get("pnl_medio_combinado")))}
                </td>
            </tr>
            """
        )
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
        HYGH sirve de referencia para bonos de alto rendimiento; no mide por sí solo la liquidez.
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

    cards = []
    for p in positions:
        pnl = p.get("pnl_pct")
        pnl_display = fmt_pct(pnl)
        score = fmt_num(p.get("score"), 0)
        rsi = fmt_num(p.get("rsi"), 1)
        sl = fmt_pct(p.get("distancia_sl_pct"))
        tp = fmt_pct(p.get("distancia_tp_pct"))
        pnl_color = "#16845b" if isinstance(pnl, (int, float)) and pnl >= 0 else "#b54747"
        cards.append(
            f"""
            <div style="margin:10px 0;padding:14px 15px;border:1px solid #e5eaf0;border-radius:10px;background:#ffffff;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
                    <tr>
                        <td style="font-size:16px;font-weight:700;color:#1e293b;">{esc(p.get("ticker"))}</td>
                        <td align="right" style="font-size:17px;font-weight:700;color:{pnl_color};">{esc(pnl_display)}</td>
                    </tr>
                    <tr>
                        <td style="padding-top:12px;font-size:12px;line-height:1.45;color:#64748b;">Puntuación interna<br><strong style="color:#334155;">{esc(score)}</strong></td>
                        <td align="right" style="padding-top:12px;font-size:12px;line-height:1.45;color:#64748b;">RSI<br><strong style="color:#334155;">{esc(rsi)}</strong></td>
                    </tr>
                    <tr>
                        <td style="padding-top:8px;font-size:12px;line-height:1.45;color:#64748b;">Distancia al stop<br><strong style="color:#334155;">{esc(sl)}</strong></td>
                        <td align="right" style="padding-top:8px;font-size:12px;line-height:1.45;color:#64748b;">Distancia al objetivo<br><strong style="color:#334155;">{esc(tp)}</strong></td>
                    </tr>
                </table>
            </div>
            """
        )

    return f"""
    <h3 style="margin:20px 0 8px;color:#1e293b;">{esc(title)}</h3>
    <p style="font-size:12px;color:#64748b;line-height:1.5;margin:0 0 8px;">
        La puntuación interna resume varios criterios del análisis. El RSI es un indicador de impulso del precio.
        El stop es un nivel de salida definido para limitar pérdidas. Las distancias indican cuánto falta hasta los niveles actuales de stop y objetivo; no son una garantía.
    </p>
    {''.join(cards)}
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
        analysis = esc(formato_texto_es(item.get("analysis"))).replace("\n", "<br>")

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
    cierre = metricas["pnl_cerradas_eur"]
    abierto = metricas["pnl_activas_eur"]
    total = metricas["pnl_total_eur"]
    estado_cierre = "positivo" if cierre > 0 else "negativo" if cierre < 0 else "en equilibrio"
    estado_abierto = "positivo" if abierto > 0 else "negativo" if abierto < 0 else "en equilibrio"
    estado_total = "positivo" if total > 0 else "negativo" if total < 0 else "en equilibrio"
    summary_text = (
        f"Las operaciones cerradas terminan en {estado_cierre}, mientras que las abiertas "
        f"muestran por ahora un resultado {estado_abierto}. El balance conjunto queda "
        f"{estado_total}; el saldo de las abiertas puede cambiar mientras sigan en cartera."
    )
    summary = esc(summary_text)
    market_context = esc(formato_texto_es(analisis.get("market_context", ""))).replace("\n", "<br><br>")
    portfolio_analysis = esc(formato_texto_es(analisis.get("portfolio_analysis", ""))).replace("\n", "<br><br>")
    risk_monitor = esc(formato_texto_es(analisis.get("risk_monitor", ""))).replace("\n", "<br><br>")
    next_week = esc(formato_texto_es(analisis.get("next_week_outlook", ""))).replace("\n", "<br><br>")

    active = metricas["posiciones_activas"]
    closed = metricas["total_operaciones_cerradas"]
    win_rate = metricas["win_rate"]

    pnl_active = metricas["pnl_medio_activas"]
    pnl_combined = metricas["pnl_medio_combinado"]
    pf = metricas["profit_factor"]
    factor_explicado = (
        f"{fmt_num(pf, 2)} € de ganancia bruta por cada 1 € de pérdida bruta"
        if pf is not None else "no disponible"
    )

    key_takeaways = analisis.get("key_takeaways", []) or []
    takeaway_html = "".join(
        f"<li style='margin-bottom:7px;'>{esc(formato_texto_es(item))}</li>"
        for item in key_takeaways[:5]
    )

    market_html = render_market_table(mercado, metricas)
    top_html = render_positions_table(metricas["top_3"], "Posiciones activas destacadas")
    watch_html = render_positions_table(metricas["worst_3"], "Posiciones a vigilar")

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
<title>Alura Quant — Informe semanal</title>
<style type="text/css">
@media only screen and (max-width:600px) {{
  .outer-pad {{ padding:12px 6px !important; }}
  .content-pad {{ padding-left:17px !important;padding-right:17px !important; }}
  .header-pad {{ padding:24px 19px !important; }}
  .hero-number {{ font-size:30px !important; }}
  .mobile-small {{ font-size:11px !important; }}
  .stack-table {{ border-spacing:0 !important; }}
  .stack-mobile {{ display:block !important;width:100% !important;max-width:100% !important;box-sizing:border-box !important;margin-bottom:8px !important; }}
}}
</style>
</head>

<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#1e293b;">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;">
<tr>
<td align="center" class="outer-pad" style="padding:24px 12px;">

<table width="680" cellpadding="0" cellspacing="0"
       style="max-width:680px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;">

<!-- HEADER -->
<tr>
<td class="header-pad" style="background:#1e293b;padding:30px 32px;color:#ffffff;">
    <div style="font-size:12px;letter-spacing:1.5px;text-transform:uppercase;color:#cbd5e1;">
        Alura Quant
    </div>
    <div style="font-size:27px;font-weight:700;margin-top:7px;">
        Informe semanal
    </div>
    <div style="font-size:13px;color:#cbd5e1;margin-top:8px;">
        {esc(inicio.strftime("%d/%m/%Y"))} — {esc(fin.strftime("%d/%m/%Y"))}
    </div>
</td>
</tr>

<!-- EXECUTIVE SUMMARY -->
<tr>
<td class="content-pad" style="padding:24px 32px 10px;">
    <div style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#64748b;font-weight:700;">
        Lectura rápida
    </div>

    <p style="font-size:16px;line-height:1.65;color:#334155;margin:12px 0 0;">
        {summary}
    </p>
</td>
</tr>

<!-- KPIs -->
<tr>
<td class="content-pad" style="padding:16px 32px 20px;">
<div style="padding:18px 20px;background:#fff8df;border:1px solid #f0df9a;border-radius:12px;">
    <div style="font-size:11px;letter-spacing:.7px;color:#78631b;text-transform:uppercase;font-weight:700;">Balance conjunto de la cartera</div>
    <div class="hero-number" style="font-size:35px;line-height:1.15;font-weight:700;color:#1e293b;margin-top:7px;">{esc(fmt_eur(metricas["pnl_total_eur"]))}</div>
    <div style="font-size:13px;line-height:1.5;color:#475569;margin-top:7px;">Rendimiento ponderado: <strong>{esc(fmt_pct(pnl_combined))}</strong> sobre {esc(fmt_eur(metricas["nominal_total_eur"]))} en posiciones.</div>
</div>

<table role="presentation" class="stack-table" width="100%" cellpadding="0" cellspacing="0" style="margin-top:10px;border-collapse:separate;border-spacing:5px 0;">
<tr>
<td class="stack-mobile" width="50%" valign="top" style="padding:13px 12px;background:#f8fafc;border:1px solid #e8edf2;border-radius:10px;">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;">Cerradas · {closed}</div>
    <div style="font-size:20px;font-weight:700;margin-top:5px;color:#1e293b;">{esc(fmt_eur(metricas["pnl_cerradas_eur"]))}</div>
    <div class="mobile-small" style="font-size:12px;line-height:1.5;color:#64748b;margin-top:4px;">Resultado cerrado · {esc(fmt_pct(metricas["pnl_medio_cerradas"]))}  · {metricas["wins"]} con beneficio · {metricas["losses"]} salidas por stop · {metricas["break_even"]} en equilibrio</div>
</td>
<td class="stack-mobile" width="50%" valign="top" style="padding:13px 12px;background:#f8fafc;border:1px solid #e8edf2;border-radius:10px;">
    <div style="font-size:11px;color:#64748b;text-transform:uppercase;font-weight:700;">Abiertas · {active}</div>
    <div style="font-size:20px;font-weight:700;margin-top:5px;color:#1e293b;">{esc(fmt_eur(metricas["pnl_activas_eur"]))}</div>
    <div class="mobile-small" style="font-size:12px;line-height:1.5;color:#64748b;margin-top:4px;">Saldo actual de operaciones abiertas · {esc(fmt_pct(pnl_active))}</div>
</td>
</tr>
</table>

<div style="margin:10px 4px 0;font-size:12px;line-height:1.5;color:#64748b;">
    Tasa de acierto en cerradas: <strong>{esc(fmt_pct(win_rate))}</strong>
    &nbsp;·&nbsp; Factor de beneficio: <strong>{esc(fmt_num(pf, 2))}</strong>
    <span>({esc(factor_explicado)})</span>
</div>

</td>
</tr>

<!-- MARKET -->
<tr>
<td class="content-pad" style="padding:8px 32px 20px;">
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
<td class="content-pad" style="padding:20px 32px;">
    <h2 style="font-size:19px;margin:0 0 10px;color:#1e293b;">
        Cómo va la cartera
    </h2>

    <p style="font-size:14px;line-height:1.65;color:#475569;">
        {portfolio_analysis}
    </p>
</td>
</tr>

<!-- POSITIONS -->
<tr>
<td class="content-pad" style="padding:4px 32px 20px;">
    {top_html}
    {best_analysis_html}

    {watch_html}
    {watch_analysis_html}
</td>
</tr>

<!-- RISK -->
<tr>
<td class="content-pad" style="padding:20px 32px;background:#f8fafc;">
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
<td class="content-pad" style="padding:24px 32px 20px;">
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
    Informe generado automáticamente. Alura Quant es una herramienta tecnológica de análisis cuantitativo y educación financiera. 
    Los datos, scores, niveles técnicos y análisis generados por algoritmos o inteligencia artificial no constituyen, ni deben interpretarse como,
    un servicio de asesoramiento en inversión, recomendación de compra/venta o análisis financiero personalizado según la Ley del Mercado de Valores.
    La renta variable conlleva riesgos de pérdida de capital. Cada usuario es responsable exclusivo de sus decisiones de inversión.
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
        f"Alura Quant | Informe semanal "
        f"— {inicio.strftime('%d/%m')} → {fin.strftime('%d/%m/%Y')}"
    )

    remitente = os.getenv(
        "RESEND_FROM",
        "Alura Quant <updates@aluraquant.es>"
    )

    for correo in destinatarios:
        # ¡Clave! Se pasa como lista con un único elemento para que cada usuario
        # reciba el correo de forma limpia y privada (sin ver a nadie más en el 'Para').
        params = {
            "from": remitente,
            "to": [correo],
            "subject": asunto,
            "html": html_content,
        }

        try:
            response = resend.Emails.send(params)
            logger.info(
                "Newsletter enviada correctamente a %s. Respuesta Resend: %s",
                correo,
                response
            )
        except Exception as exc:
            logger.exception("Error enviando newsletter a %s: %s", correo, exc)


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

    destinatarios = (
        [CORREO_PRUEBAS]
        if MODO_PRUEBAS
        else obtener_suscriptores()
    )

    if MODO_PRUEBAS:
        logger.warning(
            "MODO_PRUEBAS activo: la newsletter se enviará únicamente a %s.",
            CORREO_PRUEBAS
        )

    if not destinatarios:
        logger.info("No hay suscriptores. Proceso finalizado.")
        return

    df_backtest = obtener_backtesting(inicio, fin)
    metricas = construir_metricas_cartera(df_backtest, inicio, fin)
    viernes_referencia = fin - timedelta(days=max(0, fin.weekday() - 4))
    logger.info(
        "Resumen snapshots %s-%s: no ACTIVAS=%s; ACTIVAS el %s=%s.",
        inicio,
        viernes_referencia,
        metricas["total_operaciones_cerradas"],
        viernes_referencia,
        metricas["posiciones_activas"],
    )
    mercado = descargar_mercado_yfinance(inicio, fin)
    noticias = obtener_noticias_semana(inicio, fin)
    contexto = construir_contexto_ia(metricas, mercado, noticias)
    analisis = generar_analisis_ia(contexto)

    html_content = generar_html_newsletter(
        metricas,
        mercado,
        analisis,
        inicio,
        fin
    )

    enviar_correo(
        html_content,
        destinatarios,
        inicio,
        fin
    )

    logger.info("Newsletter completada correctamente.")


if __name__ == "__main__":
    main()
