from __future__ import annotations

import io
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
    PageBreak, KeepTogether,
)


PERIODOS = {"1 año": "1y", "2 años": "2y", "5 años": "5y", "10 años": "10y"}


def _safe_num(value: Any, default: float = np.nan) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_num(value: Any, decimals: int = 2, suffix: str = "") -> str:
    n = _safe_num(value)
    if not np.isfinite(n):
        return "N/D"
    return f"{n:,.{decimals}f}{suffix}".replace(",", "X").replace(".", ",").replace("X", ".")


def descargar_datos(ticker: str, periodo: str = "5y") -> tuple[pd.DataFrame, dict, list[dict]]:
    """Descarga velas ajustadas, perfil fundamental y noticias disponibles en Yahoo Finance."""
    simbolo = ticker.strip().upper()
    if not simbolo or len(simbolo) > 30 or any(ch.isspace() for ch in simbolo):
        raise ValueError("Introduce un ticker válido, por ejemplo AAPL, SAN.MC o MSFT.")
    activo = yf.Ticker(simbolo)
    historico = activo.history(period=periodo, auto_adjust=True, actions=False)
    if historico is None or historico.empty or "Close" not in historico:
        raise ValueError(f"Yahoo Finance no ha devuelto precios para {simbolo}. Comprueba el ticker o prueba su sufijo de mercado, por ejemplo .MC o .L.")
    historico = historico.dropna(subset=["Close"]).copy()
    info: dict = {}
    try:
        info = activo.get_info() or {}
    except Exception:
        try:
            info = activo.info or {}
        except Exception:
            info = {}
    try:
        news = activo.news or []
    except Exception:
        news = []
    return historico, info, news[:12]


def calcular_metricas(df: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    d = df.copy()
    close = d["Close"].astype(float)
    high = d["High"].astype(float) if "High" in d else close
    low = d["Low"].astype(float) if "Low" in d else close
    volume = d["Volume"].astype(float) if "Volume" in d else pd.Series(np.nan, index=d.index)
    d["Retorno diario"] = close.pct_change()
    d["EMA20"] = close.ewm(span=20, adjust=False).mean()
    d["EMA50"] = close.ewm(span=50, adjust=False).mean()
    d["EMA200"] = close.ewm(span=200, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    d["RSI14"] = 100 - (100 / (1 + rs))
    prev_close = close.shift(1)
    tr = pd.concat([(high-low).abs(), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    d["ATR14"] = tr.rolling(14).mean()
    d["ATR_pct"] = d["ATR14"] / close
    d["ROC20"] = close.pct_change(20) * 100
    d["Volumen_medio20"] = volume.rolling(20).mean()
    d["RVOL20"] = volume / d["Volumen_medio20"].replace(0, np.nan)
    d["Máximo histórico ventana"] = close.cummax()
    d["Drawdown"] = close / d["Máximo histórico ventana"] - 1
    latest = d.iloc[-1]
    first_close, last_close = _safe_num(close.iloc[0]), _safe_num(close.iloc[-1])
    returns = d["Retorno diario"].dropna()
    annual_vol = returns.std(ddof=1) * np.sqrt(252) if len(returns) > 1 else np.nan
    years = max((d.index[-1] - d.index[0]).days / 365.25, 1/365.25)
    cagr = ((last_close / first_close) ** (1 / years) - 1) * 100 if first_close > 0 and last_close > 0 else np.nan
    metrics = {
        "precio": last_close,
        "fecha": str(d.index[-1].date()),
        "retorno_1d_pct": _safe_num(d["Retorno diario"].iloc[-1]) * 100,
        "retorno_1m_pct": _safe_num(close.pct_change(21).iloc[-1]) * 100,
        "retorno_3m_pct": _safe_num(close.pct_change(63).iloc[-1]) * 100,
        "retorno_6m_pct": _safe_num(close.pct_change(126).iloc[-1]) * 100,
        "retorno_1y_pct": _safe_num(close.pct_change(252).iloc[-1]) * 100,
        "retorno_periodo_pct": (last_close / first_close - 1) * 100 if first_close else np.nan,
        "cagr_pct": cagr,
        "volatilidad_anual_pct": annual_vol * 100,
        "max_drawdown_pct": _safe_num(d["Drawdown"].min()) * 100,
        "rsi14": _safe_num(latest.get("RSI14")),
        "ema20": _safe_num(latest.get("EMA20")),
        "ema50": _safe_num(latest.get("EMA50")),
        "ema200": _safe_num(latest.get("EMA200")),
        "atr14": _safe_num(latest.get("ATR14")),
        "atr_pct": _safe_num(latest.get("ATR_pct")) * 100,
        "roc20_pct": _safe_num(latest.get("ROC20")),
        "rvol20": _safe_num(latest.get("RVOL20")),
        "max_52w": _safe_num(close.tail(252).max()),
        "min_52w": _safe_num(close.tail(252).min()),
    }
    return d, metrics, d.tail(252).copy()


def construir_lectura_tecnica(m: dict) -> list[str]:
    out = []
    price, e20, e50, e200, rsi = (m.get(k, np.nan) for k in ("precio", "ema20", "ema50", "ema200", "rsi14"))
    if all(np.isfinite(x) for x in (price, e50, e200)):
        if price > e50 > e200:
            out.append("Estructura de tendencia positiva: precio por encima de EMA50 y EMA200, con medias alineadas.")
        elif price < e50 < e200:
            out.append("Estructura de tendencia negativa: precio por debajo de EMA50 y EMA200, con medias alineadas a la baja.")
        else:
            out.append("Estructura de tendencia mixta: el precio y las medias no muestran una alineación completa.")
    if np.isfinite(rsi):
        if rsi >= 70: out.append(f"RSI(14) en {_fmt_num(rsi)}: zona tradicionalmente sobrecomprada; no implica giro por sí sola.")
        elif rsi <= 30: out.append(f"RSI(14) en {_fmt_num(rsi)}: zona tradicionalmente sobrevendida; no implica rebote por sí sola.")
        else: out.append(f"RSI(14) en {_fmt_num(rsi)}: zona intermedia, sin señal extrema clásica.")
    if np.isfinite(m.get("atr_pct", np.nan)):
        out.append(f"ATR(14) equivale aproximadamente al {_fmt_num(m['atr_pct'])}% del precio, como referencia de rango reciente, no como predicción.")
    if np.isfinite(m.get("rvol20", np.nan)):
        out.append(f"Volumen relativo frente a la media de 20 sesiones: {_fmt_num(m['rvol20'])}x.")
    return out


def _ai_narrative(ticker: str, info: dict, m: dict, technical: list[str], news: list[dict]) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "La capa narrativa de IA no está activada (falta GEMINI_API_KEY). El informe se ha generado con métricas calculadas por Python y datos públicos disponibles."
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
        headlines = []
        for item in news[:8]:
            content = item.get("content", item) if isinstance(item, dict) else {}
            title = content.get("title") if isinstance(content, dict) else None
            if title: headlines.append(str(title))
        prompt = f"""Redacta un análisis financiero en español, prudente y basado únicamente en estos datos. No inventes cifras, catalizadores ni hechos. Distingue hechos de hipótesis y no des asesoramiento personalizado ni prometas rentabilidades. Indica limitaciones de los datos. Estructura: lectura ejecutiva, factores favorables, riesgos/invalidaciones, qué vigilar y escenarios condicionales (alcista/base/bajista) sin objetivos de precio inventados.
Ticker: {ticker}
Empresa: {info.get('longName') or info.get('shortName') or ticker}
Sector/industria: {info.get('sector', 'N/D')} / {info.get('industry', 'N/D')}
Métricas calculadas: {m}
Lectura técnica calculada: {technical}
Titulares recientes disponibles (no necesariamente exhaustivos): {headlines}
Descripción de negocio de proveedor: {str(info.get('longBusinessSummary', 'N/D'))[:1800]}
"""
        response = client.chat.completions.create(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return response.choices[0].message.content or "La IA no ha devuelto texto."
    except Exception as exc:
        return f"No se pudo generar la narrativa IA; el análisis cuantitativo sigue disponible. Detalle: {str(exc)[:300]}"


def _make_charts(ticker: str, d: pd.DataFrame) -> list[io.BytesIO]:
    outputs = []
    chart = d.tail(252)
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(chart.index, chart["Close"], label="Precio ajustado", linewidth=1.6)
    for col, label in [("EMA50", "EMA 50"), ("EMA200", "EMA 200")]:
        if col in chart and chart[col].notna().any(): ax.plot(chart.index, chart[col], label=label, linewidth=1.1)
    ax.set_title(f"{ticker} · Precio ajustado y medias móviles")
    ax.set_ylabel("Precio")
    ax.grid(True, alpha=.25); ax.legend(loc="best"); fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=150); plt.close(fig); buf.seek(0); outputs.append(buf)
    fig, ax = plt.subplots(figsize=(10, 3.0))
    returns = d["Retorno diario"].dropna()
    if not returns.empty: ax.hist(returns * 100, bins=45)
    ax.set_title("Distribución de retornos diarios")
    ax.set_xlabel("Retorno diario (%)"); ax.set_ylabel("Frecuencia"); ax.grid(True, alpha=.2); fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=150); plt.close(fig); buf.seek(0); outputs.append(buf)
    return outputs


def generar_pdf(ticker: str, periodo_label: str, d: pd.DataFrame, info: dict, news: list[dict], d_ind: pd.DataFrame, m: dict, use_ai: bool = True) -> bytes:
    technical = construir_lectura_tecnica(m)
    narrative = _ai_narrative(ticker, info, m, technical, news) if use_ai else "Narrativa IA desactivada para este informe. Las métricas y conclusiones técnicas se han calculado localmente a partir de los datos disponibles."
    charts = _make_charts(ticker, d_ind)
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=1.7*cm, leftMargin=1.7*cm, topMargin=1.6*cm, bottomMargin=1.6*cm, title=f"Alura Quant Intelligence · {ticker}", author="Alura Quant")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="AQTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=30, alignment=TA_CENTER, textColor=colors.HexColor("#172554"), spaceAfter=12))
    styles.add(ParagraphStyle(name="AQH1", parent=styles["Heading1"], textColor=colors.HexColor("#1D4ED8"), spaceBefore=10, spaceAfter=7))
    styles.add(ParagraphStyle(name="AQBody", parent=styles["BodyText"], fontSize=9, leading=13, spaceAfter=6))
    styles.add(ParagraphStyle(name="AQSmall", parent=styles["BodyText"], fontSize=7.5, leading=10, textColor=colors.HexColor("#475569")))
    story = [Spacer(1, 1.8*cm), Paragraph("ALURA QUANT", styles["AQTitle"]), Paragraph("INTELLIGENCE · INFORME DE ACTIVO", styles["Heading2"]), Spacer(1, .5*cm), Paragraph(f"{ticker} — {info.get('longName') or info.get('shortName') or ticker}", styles["Heading1"]), Paragraph(f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')} · Ventana histórica: {periodo_label} · Datos de mercado: {m['fecha']}", styles["AQBody"]), Spacer(1, .4*cm)]
    summary = [["Precio último", "Retorno 1 año", "RSI(14)", "Vol. anualizada"], [_fmt_num(m['precio']), _fmt_num(m['retorno_1y_pct'], 2, "%"), _fmt_num(m['rsi14']), _fmt_num(m['volatilidad_anual_pct'], 2, "%")]]
    table = Table(summary, colWidths=[4.1*cm]*4)
    table.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,0),colors.HexColor("#E2E8F0")),("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#334155")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTNAME",(0,1),(-1,1),"Helvetica-Bold"),("ALIGN",(0,0),(-1,-1),"CENTER"),("BOX",(0,0),(-1,-1),.5,colors.HexColor("#CBD5E1")),("INNERGRID",(0,0),(-1,-1),.4,colors.HexColor("#CBD5E1")),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8)]))
    story += [table, Spacer(1, .5*cm), Paragraph("Resumen ejecutivo", styles["AQH1"]), Paragraph(narrative.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>"), styles["AQBody"]), Paragraph("1. Perfil de la compañía", styles["AQH1"])]
    profile_rows = [["Campo", "Dato"], ["Sector", str(info.get("sector", "N/D"))], ["Industria", str(info.get("industry", "N/D"))], ["País", str(info.get("country", "N/D"))], ["Empleados", _fmt_num(info.get("fullTimeEmployees"), 0)], ["Capitalización bursátil", _fmt_num(info.get("marketCap"))], ["PER trailing", _fmt_num(info.get("trailingPE"))], ["PER forward", _fmt_num(info.get("forwardPE"))], ["Precio/valor contable", _fmt_num(info.get("priceToBook"))], ["Margen de beneficio", _fmt_num(_safe_num(info.get("profitMargins"))*100, 2, "%")], ["Ingresos totales", _fmt_num(info.get("totalRevenue"))], ["Flujo de caja libre", _fmt_num(info.get("freeCashflow"))], ["Deuda total", _fmt_num(info.get("totalDebt"))], ["Beta proveedor", _fmt_num(info.get("beta"))]]
    ptable = Table(profile_rows, colWidths=[5.2*cm, 10.5*cm], repeatRows=1)
    ptable.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#E2E8F0")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#CBD5E1")),("VALIGN",(0,0),(-1,-1),"TOP"),("FONTSIZE",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    story += [ptable, Paragraph("Nota: los fundamentales dependen de la cobertura y actualización de Yahoo Finance; N/D significa que el proveedor no ha facilitado el campo.", styles["AQSmall"]), Paragraph("2. Análisis cuantitativo y técnico", styles["AQH1"])]
    for item in technical: story.append(Paragraph("• " + item.replace("&", "&amp;"), styles["AQBody"]))
    tech_rows = [["Métrica", "Valor", "Métrica", "Valor"], ["Retorno 1 mes", _fmt_num(m['retorno_1m_pct'],2,"%"), "Retorno 3 meses", _fmt_num(m['retorno_3m_pct'],2,"%")], ["Retorno 6 meses", _fmt_num(m['retorno_6m_pct'],2,"%"), "Retorno periodo", _fmt_num(m['retorno_periodo_pct'],2,"%")], ["CAGR aprox.", _fmt_num(m['cagr_pct'],2,"%"), "Máx. drawdown", _fmt_num(m['max_drawdown_pct'],2,"%")], ["ROC20", _fmt_num(m['roc20_pct'],2,"%"), "RVOL20", _fmt_num(m['rvol20'],2,"x")], ["EMA20", _fmt_num(m['ema20']), "EMA50 / EMA200", f"{_fmt_num(m['ema50'])} / {_fmt_num(m['ema200'])}"], ["ATR14", _fmt_num(m['atr14']), "ATR / precio", _fmt_num(m['atr_pct'],2,"%")], ["Máximo 52 semanas", _fmt_num(m['max_52w']), "Mínimo 52 semanas", _fmt_num(m['min_52w'])]]
    ttable = Table(tech_rows, colWidths=[3.4*cm,4.4*cm,3.4*cm,4.5*cm], repeatRows=1)
    ttable.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#DBEAFE")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("GRID",(0,0),(-1,-1),.35,colors.HexColor("#CBD5E1")),("FONTSIZE",(0,0),(-1,-1),7.5),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    story += [ttable, Spacer(1,.3*cm), Image(charts[0], width=16.3*cm, height=6.85*cm), Image(charts[1], width=16.3*cm, height=4.9*cm), PageBreak(), Paragraph("3. Sector, contexto y noticias disponibles", styles["AQH1"]), Paragraph(f"Sector: {info.get('sector', 'N/D')} · Industria: {info.get('industry', 'N/D')} · País: {info.get('country', 'N/D')}", styles["AQBody"]), Paragraph("El proveedor no garantiza cobertura exhaustiva de noticias, competidores, estimaciones de analistas ni eventos corporativos. Contrasta los titulares y las fechas con las fuentes originales antes de tomar decisiones.", styles["AQBody"])]
    if news:
        for item in news[:10]:
            content = item.get("content", item) if isinstance(item, dict) else {}
            title = content.get("title", "Titular sin título") if isinstance(content, dict) else "Titular sin título"
            publisher = content.get("publisher") or content.get("provider", {}).get("displayName", "Proveedor no especificado") if isinstance(content, dict) else "Proveedor no especificado"
            story.append(Paragraph(f"• <b>{str(title).replace('&','&amp;').replace('<','&lt;')}</b> — {str(publisher).replace('&','&amp;').replace('<','&lt;')}", styles["AQBody"]))
    else:
        story.append(Paragraph("No se han recibido noticias para este ticker en la consulta actual.", styles["AQBody"]))
    story += [Paragraph("4. Riesgos, interpretación y límites", styles["AQH1"]), Paragraph("• Los retornos históricos no garantizan resultados futuros. Las métricas se calculan sobre precios ajustados descargados en la fecha indicada y pueden cambiar si el proveedor corrige datos.\n• La volatilidad anualizada se estima a partir de retornos diarios y una convención de 252 sesiones; no es una previsión.\n• El drawdown máximo mide la mayor caída desde un máximo previo dentro de la ventana descargada.\n• Este informe es informativo y no constituye asesoramiento financiero, recomendación personalizada ni una oferta de compra o venta. Considera costes, impuestos, liquidez y tolerancia al riesgo.", styles["AQBody"]), Spacer(1,.5*cm), Paragraph(f"Metodología: datos históricos de Yahoo Finance; indicadores calculados localmente con pandas/numpy; narrativa IA opcional basada en el conjunto de datos anterior. Informe generado el {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.", styles["AQSmall"])]
    def footer(canvas, document):
        canvas.saveState(); canvas.setFont("Helvetica", 7); canvas.setFillColor(colors.HexColor("#64748B")); canvas.drawString(1.7*cm, .8*cm, "ALURA QUANT · Material informativo · Ver metodología y limitaciones")
        canvas.drawRightString(A4[0]-1.7*cm, .8*cm, f"Página {document.page}"); canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def enviar_pdf_email(destinatario: str, ticker: str, pdf_bytes: bytes) -> tuple[bool, str]:
    """Envía PDF mediante SMTP si las variables SMTP están configuradas."""
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    sender = os.getenv("SMTP_FROM", user).strip()
    port = int(os.getenv("SMTP_PORT", "465"))
    if not all((host, user, password, sender)):
        return False, "Envío por email no configurado. Descarga el PDF o configura SMTP_HOST, SMTP_USER, SMTP_PASSWORD y SMTP_FROM."
    msg = EmailMessage()
    msg["Subject"] = f"Alura Quant Intelligence · {ticker}"
    msg["From"] = sender
    msg["To"] = destinatario
    msg.set_content(f"Adjuntamos el informe de análisis de {ticker}. Es material informativo y no constituye asesoramiento financiero.")
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=f"AluraQuant_{ticker.replace('/', '-')}.pdf")
    try:
        with smtplib.SMTP_SSL(host, port, timeout=25) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
        return True, "Informe enviado correctamente."
    except Exception as exc:
        return False, f"No se pudo enviar el email: {str(exc)[:250]}"
