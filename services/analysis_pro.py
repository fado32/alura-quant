"""Descarga de datos, métricas y exportación para Análisis Pro."""

import os
import html
import smtplib
import ssl
import unicodedata
from email.message import EmailMessage
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
                metrics: dict, use_ai: bool = False) -> bytes:
    """Crea un PDF de una página con identidad visual sobria de Alura Quant."""
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
    story.extend([table, Paragraph("Lectura técnica", section_style)])
    latest = indicators.iloc[-1] if indicators is not None and not indicators.empty else {}
    story.append(Paragraph(
        f"Cierre: {_fmt(metrics.get('precio'))}. EMA20: {_fmt(metrics.get('ema20'))}; "
        f"EMA50: {_fmt(metrics.get('ema50'))}; EMA200: {_fmt(metrics.get('ema200'))}. "
        f"RSI(14): {_fmt(metrics.get('rsi14'))}. La volatilidad anualizada estimada es "
        f"{_fmt(metrics.get('volatilidad_anualizada_pct'), '%')} y el drawdown máximo del periodo "
        f"{_fmt(metrics.get('max_drawdown_pct'), '%')}.", body_style))

    summary = info.get("longBusinessSummary")
    if summary:
        story.append(Paragraph("Perfil de la compañía", section_style))
        story.append(Paragraph(_ascii(summary)[:1300], body_style))
    story.append(Paragraph("Cobertura y limitaciones", section_style))
    story.append(Paragraph(
        "Informe generado con datos de mercado y fundamentales disponibles en el proveedor. "
        "La cobertura puede variar por activo y los datos pueden contener retrasos u omisiones. "
        "Este documento es informativo y no constituye asesoramiento financiero.", body_style))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("ALURA QUANT", ParagraphStyle(
        "AQFooter", parent=body_style, textColor=colors.HexColor("#64748b"),
        fontName="Helvetica-Bold", fontSize=8)))
    doc.build(story)
    return output.getvalue()


def enviar_pdf_email(email: str, symbol: str, pdf: bytes):
    """Envía el PDF por SMTP usando las variables configuradas en Streamlit."""
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    sender = os.getenv("SMTP_FROM", user).strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    if not all((host, user, password, sender)):
        return False, "Configura SMTP_HOST, SMTP_USER, SMTP_PASSWORD y SMTP_FROM en Secrets."

    message = EmailMessage()
    message["Subject"] = f"Alura Quant | Informe de {symbol}"
    message["From"] = sender
    message["To"] = email
    message.set_content(f"Adjuntamos el informe de Alura Quant para {symbol}.")
    message.add_attachment(pdf, maintype="application", subtype="pdf",
                           filename=f"AluraQuant_{symbol}.pdf")
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=25) as server:
                server.login(user, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=25) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.login(user, password)
                server.send_message(message)
        return True, f"Informe enviado a {email}."
    except Exception as exc:
        return False, f"No se pudo enviar el correo: {exc}"
