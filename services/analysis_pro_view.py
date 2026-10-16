"""Vista integrada de Análisis Pro para la aplicación Alura Quant."""

import html
import json
import math
import os
import re
from typing import Any

import pandas as pd
import streamlit as st
from openai import OpenAI

from services.analysis_pro import (
    PERIODOS,
    calcular_metricas,
    descargar_datos,
    enviar_pdf_email,
    generar_pdf,
)


GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
REPORT_KEY = "_alura_analysis_pro_report"


def _load_secrets() -> None:
    """Carga secretos de Streamlit a entorno sin mostrarlos en pantalla."""
    try:
        for key in ("GEMINI_API_KEY", "GEMINI_MODEL", "SMTP_HOST", "SMTP_PORT",
                    "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
            if key in st.secrets and not os.getenv(key):
                os.environ[key] = str(st.secrets[key])
    except Exception:
        pass


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _news_for_prompt(news: Any) -> list:
    if news is None:
        return []
    if isinstance(news, pd.DataFrame):
        return news.head(8).to_dict(orient="records")
    if isinstance(news, dict):
        return [news]
    if isinstance(news, (list, tuple)):
        return list(news[:8])
    return [str(news)[:1200]]


def _gemini_commentary(symbol: str, period: str, info: dict,
                       metrics: dict, news: Any) -> dict:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Falta GEMINI_API_KEY en Streamlit Secrets o en el entorno.")

    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
    client = OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)
    company = {
        key: info.get(key)
        for key in ("longName", "shortName", "sector", "industry", "country",
                    "longBusinessSummary")
        if info.get(key) not in (None, "")
    }
    context = {
        "ticker": symbol,
        "periodo": period,
        "perfil_empresa": company,
        "metricas": _clean(metrics),
        "noticias_disponibles": _clean(_news_for_prompt(news)),
    }
    system_prompt = """Eres analista cuantitativo de Alura Quant. Escribe en español, con tono sobrio y claro.
Usa únicamente los datos entregados; no inventes hechos, cifras, catalizadores ni noticias.
Distingue los datos observados de su interpretación. Señala las limitaciones de cobertura.
No des recomendaciones personalizadas ni instrucciones de compra o venta.
Devuelve exclusivamente JSON válido con estas claves: resumen (2-3 frases),
lectura_tecnica (un párrafo), contexto_fundamental (un párrafo), riesgos (lista de 2-4 puntos),
conclusion (un párrafo)."""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, default=str)},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)


def _fmt(value: Any, suffix: str = "", decimals: int = 2) -> str:
    try:
        number = float(value)
        if not math.isfinite(number):
            return "N/D"
        return f"{number:,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "N/D"


def _section(title: str, text: Any) -> None:
    if text:
        st.markdown(f"#### {title}")
        st.markdown(str(text))


def _render_report(report: dict) -> None:
    symbol = html.escape(report["symbol"])
    company = html.escape(str(report["info"].get("longName") or
                              report["info"].get("shortName") or report["symbol"]))
    st.markdown(f"""
    <div style="background:linear-gradient(120deg,#0b1220,#173a78);padding:28px 32px;
      border-radius:20px;color:#fff;margin:14px 0 20px">
      <div style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#9bbcff;font-weight:700">
        ALURA QUANT · INFORME DE ANÁLISIS
      </div>
      <div style="font-size:30px;font-weight:800;letter-spacing:-.04em;margin-top:8px">{company}</div>
      <div style="color:#cbd5e1;margin-top:5px">{symbol} · {html.escape(report['period_label'])}</div>
    </div>
    """, unsafe_allow_html=True)

    metrics = report["metrics"]
    metric_keys = [
        ("Último precio", "precio", "", 2),
        ("Retorno 1 año", "retorno_1y_pct", "%", 2),
        ("RSI (14)", "rsi14", "", 1),
        ("Drawdown máximo", "max_drawdown_pct", "%", 2),
    ]
    cols = st.columns(4, gap="small")
    for col, (label, key, suffix, decimals) in zip(cols, metric_keys):
        with col:
            st.metric(label, _fmt(metrics.get(key), suffix, decimals))

    commentary = report.get("commentary") or {}
    if commentary:
        with st.container():
            st.markdown("### Lectura de Alura Quant")
            _section("Resumen ejecutivo", commentary.get("resumen"))
            left, right = st.columns(2, gap="large")
            with left:
                _section("Lectura técnica", commentary.get("lectura_tecnica"))
            with right:
                _section("Contexto fundamental", commentary.get("contexto_fundamental"))
            _section("Riesgos y limitaciones", "\n".join(
                f"- {item}" for item in commentary.get("riesgos", [])
            ))
            _section("Conclusión", commentary.get("conclusion"))
    elif report.get("ai_error"):
        st.info(f"No se generó el comentario de Gemini: {report['ai_error']}")

    history = report.get("history")
    if isinstance(history, pd.DataFrame) and not history.empty and "Close" in history:
        with st.container():
            st.markdown("### Evolución del precio")
            st.line_chart(history[["Close"]], use_container_width=True)

    info = report["info"]
    summary = info.get("longBusinessSummary")
    if summary:
        with st.expander("Perfil de la compañía"):
            st.write(summary)
            st.caption("Sector: " + str(info.get("sector") or "N/D") +
                       " · Industria: " + str(info.get("industry") or "N/D"))

    news = report.get("news")
    if news:
        with st.expander("Noticias y datos incluidos"):
            if isinstance(news, pd.DataFrame):
                st.dataframe(news, use_container_width=True, hide_index=True)
            elif isinstance(news, (list, dict)):
                st.json(_clean(news))
            else:
                st.write(news)

    st.download_button(
        "⬇ Descargar informe PDF",
        data=report["pdf"],
        file_name=f"AluraQuant_{report['symbol']}.pdf",
        mime="application/pdf",
        type="primary",
    )
    with st.expander("Enviar el PDF por email"):
        email = st.text_input("Email destinatario", key="analysis_pro_email",
                              placeholder="nombre@dominio.com")
        if st.button("Enviar informe", key="send_analysis_pro_email"):
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip()):
                st.error("Introduce un email válido.")
            else:
                ok, message = enviar_pdf_email(email.strip(), report["symbol"], report["pdf"])
                st.success(message) if ok else st.warning(message)

    st.caption("Datos de proveedores externos, sujetos a retrasos y omisiones. Este informe es informativo y no constituye asesoramiento financiero.")


def render_analysis_pro() -> None:
    """Pinta Análisis Pro dentro de app.py sin crear una página de sidebar."""
    _load_secrets()
    st.markdown("""
    <style>
      .analysis-pro-shell{max-width:1080px;margin:0 auto}
      div[class*="st-key-analysis_pro_generate"] button{border-radius:10px!important;font-weight:700!important}
      div[data-testid="stMetric"]{background:#fff;border:1px solid #e8edf4;border-radius:15px;padding:16px 18px;box-shadow:0 8px 24px rgba(15,23,42,.04)}
    </style>
    <div style="max-width:1080px;margin:28px auto 8px">
      <div style="color:#2563eb;font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase">RESEARCH · QUANTITATIVE INTELLIGENCE</div>
      <h1 style="margin:7px 0 5px;color:#0b1220;letter-spacing:-.045em">Análisis Pro</h1>
      <p style="margin:0;color:#64748b">Un informe claro y accionable en pantalla, basado en datos de mercado, fundamentales y Gemini.</p>
    </div>
    """, unsafe_allow_html=True)

    if st.button("← Volver a Alura Quant", key="analysis_pro_back"):
        st.session_state["active_page"] = "Inicio"
        st.rerun()

    with st.container():
        c1, c2, c3 = st.columns([1.2, 1.2, 1], gap="medium")
        with c1:
            ticker = st.text_input("Ticker", value="AAPL", max_chars=30,
                                   help="Ejemplos: AAPL, SAN.MC, BMW.DE o BTC-USD")
        with c2:
            period_label = st.selectbox("Periodo", list(PERIODOS.keys()), index=min(2, len(PERIODOS)-1))
        with c3:
            include_ai = st.checkbox("Comentario de Gemini", value=bool(os.getenv("GEMINI_API_KEY")))
        generate = st.button("Generar análisis", key="analysis_pro_generate", type="primary")

    if generate:
        symbol = ticker.strip().upper()
        if not symbol or not re.fullmatch(r"[A-Z0-9.^=_-]{1,30}", symbol):
            st.error("Ticker no válido. Prueba, por ejemplo, SAN.MC o BTC-USD.")
        else:
            try:
                with st.spinner(f"Preparando el informe de {symbol}…"):
                    history, info, news = descargar_datos(symbol, PERIODOS[period_label])
                    dates, metrics, indicators = calcular_metricas(history)
                    pdf = generar_pdf(symbol, period_label, dates, info, news,
                                      indicators, metrics, use_ai=False)
                    report = {
                        "symbol": symbol,
                        "period_label": period_label,
                        "history": history,
                        "info": info,
                        "news": news,
                        "metrics": metrics,
                        "pdf": pdf,
                        "commentary": None,
                        "ai_error": None,
                    }
                    if include_ai:
                        try:
                            report["commentary"] = _gemini_commentary(
                                symbol, period_label, info, metrics, news
                            )
                        except Exception as exc:
                            report["ai_error"] = str(exc)
                    st.session_state[REPORT_KEY] = report
            except Exception as exc:
                st.error(f"No se pudo generar el informe: {exc}")
                st.caption("Comprueba el ticker, la conectividad y la cobertura de datos del proveedor.")

    report = st.session_state.get(REPORT_KEY)
    if report:
        _render_report(report)
    else:
        st.markdown("""
        <div style="max-width:1080px;margin:16px auto;padding:22px 24px;background:#f8fafc;border:1px solid #e8edf4;border-radius:16px;color:#64748b;line-height:1.65">
          Introduce un símbolo y genera el informe. El análisis aparecerá aquí; también podrás descargarlo en PDF.
        </div>
        """, unsafe_allow_html=True)
