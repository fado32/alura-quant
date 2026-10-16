"""Descarga de datos, métricas y exportación para Análisis Pro."""

import os
import html
import base64
import unicodedata
from io import BytesIO
from typing import Any

import pandas as pd
import yfinance as yf
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


PERIODOS = {
    "6 meses": "6mo",
    "1 año": "1y",
    "3 años": "3y",
    "5 años": "5y",
    "Máximo disponible": "max",
}


def descargar_datos(ticker: str, periodo: str):
    """Obtiene histórico, fundamentales disponibles y noticias de Yahoo Finance."""
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        raise ValueError("Introduce un ticker válido.")
    ticker_obj = yf.Ticker(symbol)
    history = ticker_obj.history(period=periodo, auto_adjust=True, actions=False)
    if history is None or history.empty or "Close" not in history:
        raise ValueError(f"No se encontraron datos históricos para {symbol}.")
    history = history.copy()
    history.index = pd.to_datetime(history.index)
    try:
        info = ticker_obj.info or {}
    except Exception:
        info = {}
    try:
        news = ticker_obj.news or []
    except Exception:
        news = []
    return history, info, news


def calcular_metricas(history: pd.DataFrame):
    """Calcula indicadores técnicos y devuelve (histórico, métricas, indicadores)."""
    if history is None or history.empty or "Close" not in history:
        raise ValueError("No hay histórico de precios suficiente para calcular el informe.")
    d = history.copy().sort_index()
    close = pd.to_numeric(d["Close"], errors="coerce").dropna()
    if close.empty:
        raise ValueError("El proveedor no devolvió precios de cierre válidos.")

    indicators = pd.DataFrame(index=d.index)
    indicators["Close"] = pd.to_numeric(d["Close"], errors="coerce")
    for span in (20, 50, 200):
        indicators[f"EMA{span}"] = indicators["Close"].ewm(span=span, adjust=False).mean()

    delta = indicators["Close"].diff()
    gains = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    losses = -delta.clip(upper=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = gains / losses.replace(0, float("nan"))
    indicators["RSI14"] = 100 - 100 / (1 + rs)

    if all(col in d.columns for col in ("High", "Low", "Close")):
        prev_close = pd.to_numeric(d["Close"], errors="coerce").shift(1)
        high = pd.to_numeric(d["High"], errors="coerce")
        low = pd.to_numeric(d["Low"], errors="coerce")
        tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        indicators["ATR14"] = tr.rolling(14, min_periods=1).mean()
    else:
        indicators["ATR14"] = float("nan")
    indicators["ROC20"] = indicators["Close"].pct_change(20) * 100
    if "Volume" in d.columns:
        vol = pd.to_numeric(d["Volume"], errors="coerce")
        indicators["RVOL20"] = vol / vol.rolling(20, min_periods=1).mean().replace(0, float("nan"))
    else:
        indicators["RVOL20"] = float("nan")

    first = close.iloc[0]
    last = close.iloc[-1]
    returns = close.pct_change().dropna()
    drawdown = close / close.cummax() - 1
    one_year_start = close.index[-1] - pd.Timedelta(days=365)
    one_year = close[close.index >= one_year_start]
    return_1y = (one_year.iloc[-1] / one_year.iloc[0] - 1) * 100 if len(one_year) > 1 else float("nan")
    latest = indicators.iloc[-1]
    metrics = {
        "precio": float(last),
        "retorno_periodo_pct": float((last / first - 1) * 100) if first else float("nan"),
        "retorno_1y_pct": float(return_1y),
        "rsi14": float(latest["RSI14"]) if pd.notna(latest["RSI14"]) else float("nan"),
        "atr14": float(latest["ATR14"]) if pd.notna(latest["ATR14"]) else float("nan"),
        "roc20_pct": float(latest["ROC20"]) if pd.notna(latest["ROC20"]) else float("nan"),
        "rvol20": float(latest["RVOL20"]) if pd.notna(latest["RVOL20"]) else float("nan"),
        "volatilidad_anualizada_pct": float(returns.std() * (252 ** 0.5) * 100) if len(returns) > 1 else float("nan"),
        "max_drawdown_pct": float(drawdown.min() * 100),
        "ema20": float(latest["EMA20"]),
        "ema50": float(latest["EMA50"]),
        "ema200": float(latest["EMA200"]),
        "fecha_inicio": close.index[0].strftime("%Y-%m-%d"),
        "fecha_fin": close.index[-1].strftime("%Y-%m-%d"),
    }
    return d, metrics, indicators


def calcular_semaforo_alura(history: pd.DataFrame):
    """Aplica el score y los filtros de entrada estructurales definidos en bot.py."""
    def result_unavailable(reason: str) -> dict:
        return {
            "eligible": None, "status": "gray", "label": "NO EVALUABLE",
            "score": None, "checks": [{"category": "Cobertura de datos", "status": "gray", "detail": reason}],
            "pre_ruptura": False,
        }

    if history is None or history.empty or len(history) < 220:
        return result_unavailable("El algoritmo requiere al menos 220 sesiones de datos.")
    if not all(col in history.columns for col in ("Close", "High", "Low", "Volume")):
        return result_unavailable("Faltan OHLCV para calcular los filtros del bot.")

    d = history[["Close", "High", "Low", "Volume"]].apply(pd.to_numeric, errors="coerce").dropna()
    d["E20"] = d.Close.ewm(span=20, adjust=False).mean()
    d["E20_5"] = d.E20.shift(5)
    d["E50"] = d.Close.ewm(span=50, adjust=False).mean()
    d["E200"] = d.Close.ewm(span=200, adjust=False).mean()

    delta = d.Close.diff()
    avg_gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = -delta.clip(upper=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    d["RSI"] = 100 - 100 / (1 + avg_gain / avg_loss.replace(0, float("nan")))

    def atr(series: pd.DataFrame, period: int) -> pd.Series:
        prev = series.Close.shift()
        tr = pd.concat([series.High - series.Low, (series.High - prev).abs(),
                        (series.Low - prev).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    d["ATR"] = atr(d, 14)
    d["ATR10"] = atr(d, 10)
    d["ATR30"] = atr(d, 30)
    d["COMPRESION_ATR"] = d.ATR10.shift(1) / d.ATR30.shift(1).replace(0, float("nan"))
    d["VM20"] = d.Volume.rolling(20).mean()
    d["TO20"] = (d.Close * d.Volume).rolling(20).mean()
    d["ROC20"] = d.Close.pct_change(20) * 100
    d["H20"] = d.High.rolling(20).max().shift(1)
    d["CLV"] = ((d.Close - d.Low) / (d.High - d.Low).replace(0, float("nan"))).fillna(0.0)

    required = ["Close", "E20", "E20_5", "E50", "E200", "RSI", "ATR", "ATR10", "ATR30",
                "COMPRESION_ATR", "VM20", "TO20", "ROC20", "H20", "Volume", "CLV"]
    usable = d.dropna(subset=required)
    if usable.empty:
        return result_unavailable("No hay una sesión completa para calcular el score.")
    x = usable.iloc[-1]
    price, e20, e20_5 = float(x.Close), float(x.E20), float(x.E20_5)
    e50, e200, rsi = float(x.E50), float(x.E200), float(x.RSI)
    roc20, atr14 = float(x.ROC20), float(x.ATR)
    rvol = float(x.Volume / x.VM20) if x.VM20 > 0 else 0.0
    clv, compression = float(x.CLV), float(x.COMPRESION_ATR)
    h20 = float(x.H20)
    breakout = price > h20
    distance_high_pct = ((h20 - price) / h20 * 100) if h20 > 0 else 0.0
    short_trend = price >= e20 and e20 > e20_5

    # Puntuación 0-100, siguiendo los pesos de calcular_score_cuantitativo en bot.py.
    score = 0.0
    if price > e50: score += 12
    if e50 > e200: score += 18
    if price >= e20: score += 2
    if e20 > e20_5: score += 3
    if 50 <= rsi <= 68:
        score += 12 * min(1.0, max(0.0, (rsi - 50) / 18))
    elif 68 < rsi <= 78:
        score += max(0.0, 12 * (78 - rsi) / 10)
    score += min(8.0, max(0.0, roc20))
    if rvol >= 0.8:
        score += min(12.0, 4.0 + (rvol - 0.8) / 0.7 * 8.0)
    if clv >= 0.55:
        score += min(5.0, (clv - 0.55) / 0.25 * 5.0)
    if not breakout and 0 <= distance_high_pct <= 6.0:
        score += 10.0 * (1.0 - distance_high_pct / 6.0)
    if compression <= 0.8:
        score += 8.0
    elif compression < 1.2:
        score += 8.0 * (1.2 - compression) / 0.4
    if breakout:
        score += 6.0
    pre_breakout = (not breakout and 0 <= distance_high_pct <= 6.0 and
                    compression <= 0.95 and short_trend)
    atr_pct = atr14 / price if price else 0.0
    if 0.015 <= atr_pct <= 0.05:
        score += 5.0
    elif atr_pct > 0.08:
        score -= min(8.0, (atr_pct - 0.08) / 0.02 * 4.0)
    score = int(round(max(0.0, min(100.0, score))))

    # Los filtros de entrada del bot, con stop y R:R calculados de la misma manera.
    turnover20 = float(x.TO20)
    rvol_minimum = 0.9 if pre_breakout else 1.2
    trend_ok = price > e50 and e50 > e200
    liquidity_ok = turnover20 >= 500000
    score_ok = score >= 60
    volume_ok = rvol >= rvol_minimum
    support = float(usable.Low.iloc[-16:-1].min())
    resistance = float(usable.High.iloc[-61:-1].max())
    atr_multiplier = 1.5 if atr_pct < 0.02 else (2.0 if atr_pct > 0.05 else 1.75)
    stop = min(price - atr_multiplier * atr14, support * 0.99)
    risk_unit = price - stop
    risk_ok = risk_unit > 0 and risk_unit <= price * 0.20
    theoretical_target = price + 2.5 * risk_unit
    target = resistance if resistance > price and resistance < theoretical_target else theoretical_target
    rr = (target - price) / risk_unit if risk_unit > 0 else 0.0
    rr_ok = risk_ok and rr >= 1.5
    eligible = liquidity_ok and score_ok and volume_ok and trend_ok and rr_ok

    momentum_status = "green" if (50 <= rsi <= 78 and roc20 > 0) else (
        "yellow" if (rsi >= 50 or roc20 > 0) else "red")
    checks = [
        {"category": "Tendencia", "status": "green" if trend_ok else "red",
         "detail": f"Precio {'>' if price > e50 else '≤'} EMA50; EMA50 {'>' if e50 > e200 else '≤'} EMA200."},
        {"category": "Score cuantitativo", "status": "green" if score_ok else ("yellow" if score >= 50 else "red"),
         "detail": f"{score}/100; umbral del bot: 60."},
        {"category": "Momentum", "status": momentum_status,
         "detail": f"RSI {rsi:.1f}; ROC20 {roc20:+.1f}%."},
        {"category": "Volumen relativo", "status": "green" if volume_ok else ("yellow" if rvol >= 0.8 else "red"),
         "detail": f"RVOL {rvol:.2f}x; mínimo aplicable: {rvol_minimum:.1f}x."},
        {"category": "Liquidez", "status": "green" if liquidity_ok else "red",
         "detail": f"Turnover medio 20 sesiones {_fmt(turnover20)}; umbral del bot: 500.000."},
        {"category": "Riesgo / beneficio", "status": "green" if rr_ok else "red",
         "detail": f"Stop {_fmt(stop)}; objetivo {_fmt(target)}; ratio R:R {rr:.2f} (mínimo 1,50)."},
    ]
    return {
        "eligible": eligible,
        "status": "green" if eligible else "red",
        "label": "CUMPLE FILTROS DEL BOT" if eligible else "NO CUMPLE TODOS LOS FILTROS",
        "score": score, "rvol": rvol, "rvol_minimum": rvol_minimum,
        "liquidity_20d": turnover20, "pre_ruptura": pre_breakout,
        "stop": stop, "target": target, "rr": rr,
        "checks": checks,
    }


def _ascii(value: Any) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    return html.escape(value.encode("ascii", "ignore").decode("ascii"))


def _fmt(value: Any, suffix: str = "") -> str:
    try:
        number = float(value)
        if pd.isna(number):
            return "N/D"
        return f"{number:,.2f}{suffix}"
    except (TypeError, ValueError):
        return "N/D"


def generar_pdf(symbol: str, periodo_label: str, data: pd.DataFrame,
                info: dict, news: Any, indicators: pd.DataFrame,
                metrics: dict, use_ai: bool = False,
                commentary: dict | None = None, semaforo: dict | None = None) -> bytes:
    """Crea un informe PDF Alura Quant con la lectura de Gemini y el semáforo."""
    commentary = commentary or {}
    semaforo = semaforo or {}
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=18 * mm,
                            leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=17 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("AQTitle", parent=styles["Title"], fontName="Helvetica-Bold",
                                 fontSize=21, leading=25, textColor=colors.HexColor("#0b1220"), alignment=TA_LEFT)
    body_style = ParagraphStyle("AQBody", parent=styles["BodyText"], fontName="Helvetica",
                                fontSize=9, leading=13, textColor=colors.HexColor("#475569"))
    section_style = ParagraphStyle("AQSection", parent=styles["Heading2"], fontName="Helvetica-Bold",
                                   fontSize=12, leading=15, textColor=colors.HexColor("#173a78"), spaceBefore=9)
    story = [
        Paragraph("ALURA QUANT  |  ANALISIS PRO", ParagraphStyle(
            "AQBrand", parent=body_style, textColor=colors.HexColor("#2563eb"),
            fontName="Helvetica-Bold", fontSize=9, leading=12)),
        Spacer(1, 4 * mm),
        Paragraph(_ascii(info.get("longName") or info.get("shortName") or symbol), title_style),
        Paragraph(f"{_ascii(symbol)}  |  {_ascii(periodo_label)}  |  {_ascii(metrics.get('fecha_inicio'))} - {_ascii(metrics.get('fecha_fin'))}", body_style),
        Spacer(1, 5 * mm),
    ]

    rows = [
        ["Precio", "Retorno 1 año", "RSI (14)", "Drawdown máx."],
        [_fmt(metrics.get("precio")), _fmt(metrics.get("retorno_1y_pct"), "%"),
         _fmt(metrics.get("rsi14")), _fmt(metrics.get("max_drawdown_pct"), "%")],
        ["Volatilidad anual", "ATR (14)", "ROC (20)", "RVOL (20)"],
        [_fmt(metrics.get("volatilidad_anualizada_pct"), "%"), _fmt(metrics.get("atr14")),
         _fmt(metrics.get("roc20_pct"), "%"), _fmt(metrics.get("rvol20"))],
    ]
    table = Table(rows, colWidths=[43 * mm] * 4, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#f1f5f9")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1e293b")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    status_colors = {"green": "#15803d", "red": "#b91c1c", "yellow": "#a16207", "gray": "#64748b"}
    checks = semaforo.get("checks", [])
    counts = {key: sum(1 for item in checks if item.get("status") == key)
              for key in ("green", "yellow", "red")}
    eligible = semaforo.get("eligible")
    decision = "CUMPLE FILTROS DE ENTRADA" if eligible is True else (
        "NO CUMPLE FILTROS DE ENTRADA" if eligible is False else "NO EVALUABLE")
    overall_color = status_colors["green"] if eligible is True else (
        status_colors["red"] if eligible is False else status_colors["gray"])
    decision_style = ParagraphStyle("AQDecision", parent=body_style, fontName="Helvetica-Bold",
                                    fontSize=13, leading=16, textColor=colors.white)
    count_style = ParagraphStyle("AQCount", parent=body_style, fontName="Helvetica-Bold",
                                 fontSize=9, leading=12, textColor=colors.white)
    decision_banner = Table([
        [Paragraph("ALURA QUANT  |  LECTURA DEL ALGORITMO", ParagraphStyle(
            "AQBannerEyebrow", parent=body_style, fontName="Helvetica-Bold", fontSize=7,
            leading=9, textColor=colors.HexColor("#a9c8ff")))],
        [Paragraph(f'<font color="{overall_color}">{_ascii(decision)}</font>', decision_style)],
        [Paragraph(
            f'<font color="#36c275">● {counts["green"]} VERDES</font>  '
            f'<font color="#f2b84b">● {counts["yellow"]} ÁMBAR</font>  '
            f'<font color="#ff7777">● {counts["red"]} ROJOS</font>', count_style)],
    ], colWidths=[172 * mm])
    decision_banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#102344")),
        ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#203d68")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(decision_banner)
    story.append(Spacer(1, 3 * mm))
    commentary = commentary or {}
    card_title_style = ParagraphStyle("AQCardTitle", parent=body_style, fontName="Helvetica-Bold", fontSize=8, leading=10)
    card_body_style = ParagraphStyle("AQCardBody", parent=body_style, fontSize=7.5, leading=10)
    check_cards = []
    for check in semaforo.get("checks", []):
        check_status = check.get("status", "gray")
        check_color = status_colors.get(check_status, "#64748b")
        check_label = {"green": "VERDE", "yellow": "ÁMBAR", "red": "ROJO", "gray": "N/D"}.get(check_status, "N/D")
        card = Table([
            [Paragraph(f'<font color="{check_color}"><b>{_ascii(check.get("category", ""))}</b></font>', card_title_style),
             Paragraph(f'<font color="{check_color}"><b>● {check_label}</b></font>', card_title_style)],
            [Paragraph(_ascii(check.get("detail", "")), card_body_style), ""],
        ], colWidths=[70 * mm, 14 * mm])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), .7, colors.HexColor("#dbe4f0")),
            ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(check_color)),
            ("SPAN", (0, 1), (1, 1)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        check_cards.append(card)
    if check_cards:
        card_rows = [check_cards[i:i + 2] for i in range(0, len(check_cards), 2)]
        for row in card_rows:
            if len(row) == 1:
                row.append("")
        cards_table = Table(card_rows, colWidths=[86 * mm, 86 * mm], hAlign="LEFT")
        cards_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(cards_table)

    story.append(Paragraph("Resumen ejecutivo", section_style))
    story.append(Paragraph(_ascii(commentary.get("resumen_ejecutivo") or commentary.get("resumen") or "No disponible."), body_style))
    story.append(Paragraph("Perfil de la compañía", section_style))
    story.append(Paragraph(_ascii(commentary.get("perfil_compania") or "No disponible."), body_style))
    story.append(Paragraph("Métricas de mercado", section_style))
    story.append(table)

    story.append(Paragraph("Lectura técnica", section_style))
    story.append(Paragraph(_ascii(commentary.get("lectura_tecnica") or "No disponible."), body_style))
    risks = commentary.get("riesgos", [])
    if isinstance(risks, str):
        risks = [line.strip(" •-\t") for line in risks.splitlines() if line.strip(" •-\t")]
    story.append(Paragraph("Riesgos y limitaciones", section_style))
    story.append(Paragraph(_ascii(" • ".join(map(str, risks)) or "No se han identificado riesgos adicionales con los datos disponibles."), body_style))
    story.append(Paragraph("Conclusión", section_style))
    story.append(Paragraph(_ascii(commentary.get("conclusion") or "No disponible en esta generación del análisis."), body_style))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("ALURA QUANT", ParagraphStyle(
        "AQFooter", parent=body_style, textColor=colors.HexColor("#64748b"),
        fontName="Helvetica-Bold", fontSize=8)))
    doc.build(story)
    return output.getvalue()


def enviar_pdf_email(email: str, symbol: str, pdf: bytes,
                     semaforo: dict | None = None, commentary: dict | None = None,
                     metrics: dict | None = None):
    """Envía el informe con Resend, siguiendo el flujo de la newsletter."""
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("RESEND_FROM", "Alura Quant <updates@aluraquant.es>").strip()
    if not api_key:
        return False, 'Falta RESEND_API_KEY en Streamlit Secrets.'
    try:
        import resend
        resend.api_key = api_key
        commentary = commentary or {}
        metrics = metrics or {}
        semaforo = semaforo or {}
        colors_by_status = {"green": "#16834a", "red": "#c43d45", "yellow": "#d49426", "gray": "#8792a2"}
        checks = semaforo.get("checks", [])
        counts = {key: sum(1 for item in checks if item.get("status") == key)
                  for key in ("green", "yellow", "red")}
        eligible = semaforo.get("eligible")
        decision = "CUMPLE FILTROS DE ENTRADA" if eligible is True else (
            "NO CUMPLE FILTROS DE ENTRADA" if eligible is False else "NO EVALUABLE")
        overall = colors_by_status["green"] if eligible is True else (
            colors_by_status["red"] if eligible is False else colors_by_status["gray"])
        check_cards = []
        for check in semaforo.get("checks", []):
            color = colors_by_status.get(check.get("status"), "#8792a2")
            label = {"green": "VERDE", "yellow": "ÁMBAR", "red": "ROJO", "gray": "N/D"}.get(check.get("status"), "N/D")
            check_cards.append(
                "<td width='50%' valign='top' style='padding:5px'>"
                f"<div style='background:#f7f9fc;border:1px solid #e5eaf1;border-top:3px solid {color};border-radius:10px;padding:12px'>"
                f"<div style='font-size:12px;font-weight:700;color:#15243a'>{html.escape(str(check.get('category', '')))}</div>"
                f"<div style='font-size:10px;font-weight:800;color:{color};margin:5px 0'>{html.escape(label)}</div>"
                f"<div style='font-size:11px;line-height:1.5;color:#64748b'>{html.escape(str(check.get('detail', '')))}</div></div></td>"
            )
        check_rows = []
        for index in range(0, len(check_cards), 2):
            pair = check_cards[index:index + 2]
            if len(pair) == 1:
                pair.append("<td width='50%'></td>")
            check_rows.append("<tr>" + "".join(pair) + "</tr>")
        semaforo_html = (
            "<div style='margin:0 0 22px;padding:20px;background:#102344;border:1px solid #203d68;border-radius:14px'>"
            "<div style='font-size:10px;letter-spacing:.15em;font-weight:800;color:#a9c8ff'>ALURA QUANT · FILTROS DE ENTRADA</div>"
            f"<div style='font-size:21px;line-height:1.25;font-weight:800;color:{overall};margin:9px 0 13px'>{html.escape(decision)}</div>"
            "<div style='margin-bottom:14px'>"
            f"<span style='display:inline-block;background:#173b35;color:#70e2a0;padding:6px 9px;border-radius:20px;font-size:11px;font-weight:800;margin:0 5px 5px 0'>● {counts['green']} VERDES</span>"
            f"<span style='display:inline-block;background:#493c20;color:#ffd16a;padding:6px 9px;border-radius:20px;font-size:11px;font-weight:800;margin:0 5px 5px 0'>● {counts['yellow']} ÁMBAR</span>"
            f"<span style='display:inline-block;background:#48292d;color:#ff8c91;padding:6px 9px;border-radius:20px;font-size:11px;font-weight:800;margin:0 5px 5px 0'>● {counts['red']} ROJOS</span>"
            "</div>"
            f"<table role='presentation' width='100%' cellspacing='0' cellpadding='0'>{''.join(check_rows)}</table>"
            "<div style='margin-top:12px;color:#b9c7d9;font-size:10px;line-height:1.5'>Verde: cumple · Ámbar: atención · Rojo: no cumple. Lectura del algoritmo, no recomendación personalizada.</div></div>"
        )
        summary = commentary.get("resumen_ejecutivo") or commentary.get("resumen") or "No disponible."
        profile = commentary.get("perfil_compania") or "No disponible."
        metric_pairs = [
            ("Precio", _fmt(metrics.get("precio"))),
            ("Retorno 1 año", _fmt(metrics.get("retorno_1y_pct"), "%")),
            ("RSI (14)", _fmt(metrics.get("rsi14"))),
            ("Drawdown máx.", _fmt(metrics.get("max_drawdown_pct"), "%")),
            ("Volatilidad anual", _fmt(metrics.get("volatilidad_anualizada_pct"), "%")),
            ("ATR (14)", _fmt(metrics.get("atr14"))),
            ("ROC (20)", _fmt(metrics.get("roc20_pct"), "%")),
            ("RVOL (20)", _fmt(metrics.get("rvol20"))),
        ]
        metric_cells = [
            "<td width='25%' style='padding:10px;border:1px solid #e5eaf1;background:#f7f9fc'>"
            f"<div style='font-size:10px;color:#64748b'>{html.escape(label)}</div>"
            f"<div style='font-size:15px;font-weight:700;color:#15243a;margin-top:4px'>{html.escape(str(value))}</div></td>"
            for label, value in metric_pairs
        ]
        metric_rows = "".join("<tr>" + "".join(metric_cells[i:i + 4]) + "</tr>" for i in range(0, len(metric_cells), 4))

        def email_section(title: str, text: Any) -> str:
            return ("<div style='margin:22px 0 0'>"
                    f"<div style='font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#2563eb;font-weight:800;margin-bottom:7px'>{html.escape(title)}</div>"
                    f"<div style='font-size:14px;line-height:1.7;color:#334155'>{html.escape(str(text or 'No disponible.'))}</div></div>")

        risks = commentary.get("riesgos", [])
        if isinstance(risks, str):
            risks = [line.strip(" •-\t") for line in risks.splitlines() if line.strip(" •-\t")]
        risks_html = "<ul style='padding-left:20px;margin:0;color:#334155;line-height:1.7'>" + "".join(
            f"<li>{html.escape(str(item))}</li>" for item in risks
        ) + "</ul>"
        email_body = (
            "<div style='max-width:680px;margin:auto;padding:20px;font-family:Arial,sans-serif;color:#172033'>"
            "<div style='padding:22px 24px;background:#0b1220;border-radius:14px;color:white;margin-bottom:22px'>"
            "<div style='font-size:10px;letter-spacing:.16em;color:#9bbcff;font-weight:bold'>ALURA QUANT · RESEARCH</div>"
            f"<h1 style='margin:9px 0 0;font-size:24px'>Informe de {html.escape(symbol)}</h1></div>"
            + semaforo_html
            + email_section("Resumen ejecutivo", summary)
            + email_section("Perfil de la compañía", profile)
            + "<div style='margin-top:22px'><div style='font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#2563eb;font-weight:800;margin-bottom:8px'>Métricas de mercado</div>"
              f"<table role='presentation' width='100%' cellspacing='0' cellpadding='0' style='border-collapse:collapse'>{metric_rows}</table></div>"
            + email_section("Lectura técnica", commentary.get("lectura_tecnica"))
            + "<div style='margin:22px 0 0'><div style='font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#2563eb;font-weight:800;margin-bottom:7px'>Riesgos y limitaciones</div>" + risks_html + "</div>"
            + email_section("Conclusión", commentary.get("conclusion"))
            + "<div style='margin-top:24px;padding-top:12px;border-top:1px solid #e5eaf1;font-size:11px;color:#8792a2'>ALURA QUANT · Informe informativo; no constituye asesoramiento financiero.</div></div>"
        )
        params = {
            "from": sender,
            "to": [email],
            "subject": f"Alura Quant | Informe de {symbol}",
            "html": email_body,
            "attachments": [{"filename": f"AluraQuant_{symbol}.pdf",
                             "content": base64.b64encode(pdf).decode("ascii"),
                             "content_type": "application/pdf"}],
        }
        resend.Emails.send(params)
        return True, f"Informe enviado a {email}."
    except Exception as exc:
        return False, f"No se pudo enviar el correo: {exc}"
