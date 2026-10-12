import os
import re
import streamlit as st

from services.analysis_pro import (
    PERIODOS, calcular_metricas, descargar_datos, enviar_pdf_email, generar_pdf,
)

st.set_page_config(page_title="Alura Quant · Análisis Pro", page_icon="📊", layout="wide")

st.title("📊 Alura Quant Intelligence")
st.caption("Informe cuantitativo y fundamental bajo demanda · cualquier ticker con cobertura de datos")
st.markdown("El informe combina histórico de precios, indicadores técnicos, métricas de riesgo, perfil fundamental disponible y titulares recientes. La calidad y profundidad dependen de la cobertura del proveedor para cada activo.")

with st.sidebar:
    st.subheader("Parámetros del informe")
    ticker = st.text_input("Ticker / símbolo", value="AAPL", max_chars=30, help="Ejemplos: AAPL, MSFT, SAN.MC, BMW.DE, VOD.L, BTC-USD")
    periodo_label = st.selectbox("Ventana histórica", list(PERIODOS.keys()), index=2)
    incluir_ia = st.checkbox("Incluir narrativa generada por IA", value=bool(os.getenv("GEMINI_API_KEY")), help="Requiere GEMINI_API_KEY configurada en Streamlit Secrets o variables de entorno.")
    enviar_email = st.checkbox("Enviar el PDF por email", value=False)
    email_destino = st.text_input("Email destinatario", placeholder="cliente@dominio.com", disabled=not enviar_email)
    generar = st.button("Generar informe PDF", type="primary", use_container_width=True)

# Cargar configuración opcional desde Streamlit Secrets sin imprimir secretos.
try:
    for _key in ("GEMINI_API_KEY", "GEMINI_MODEL", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
        if _key in st.secrets and not os.getenv(_key):
            os.environ[_key] = str(st.secrets[_key])
except Exception:
    pass

if generar:
    symbol = ticker.strip().upper()
    if not symbol or not re.fullmatch(r"[A-Z0-9.^=_-]{1,30}", symbol):
        st.error("Ticker no válido. Usa letras, números y símbolos de mercado habituales, como SAN.MC o BTC-USD.")
    elif enviar_email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email_destino.strip()):
        st.error("Introduce un email válido o desactiva el envío por email.")
    else:
        try:
            with st.spinner(f"Descargando y analizando {symbol}…"):
                history, info, news = descargar_datos(symbol, PERIODOS[periodo_label])
                d, metrics, d_ind = calcular_metricas(history)
                pdf = generar_pdf(symbol, periodo_label, d, info, news, d_ind, metrics, use_ai=incluir_ia)
            st.success(f"Informe generado para {symbol}: {info.get('longName') or info.get('shortName') or symbol}")
            cols = st.columns(4)
            cols[0].metric("Último precio", f"{metrics['precio']:,.2f}")
            cols[1].metric("Retorno 1 año", "N/D" if metrics['retorno_1y_pct'] != metrics['retorno_1y_pct'] else f"{metrics['retorno_1y_pct']:.2f}%")
            cols[2].metric("RSI (14)", "N/D" if metrics['rsi14'] != metrics['rsi14'] else f"{metrics['rsi14']:.1f}")
            cols[3].metric("Drawdown máximo", "N/D" if metrics['max_drawdown_pct'] != metrics['max_drawdown_pct'] else f"{metrics['max_drawdown_pct']:.2f}%")
            st.download_button("⬇️ Descargar informe PDF", data=pdf, file_name=f"AluraQuant_{symbol}.pdf", mime="application/pdf", type="primary", use_container_width=True)
            if enviar_email:
                ok, message = enviar_pdf_email(email_destino.strip(), symbol, pdf)
                st.success(message) if ok else st.warning(message)
            with st.expander("Ver datos cuantitativos incluidos"):
                st.json({k: (None if isinstance(v, float) and (v != v or abs(v) == float("inf")) else v) for k, v in metrics.items()})
            st.info("Nota: los datos de mercado y fundamentales proceden de proveedores externos y pueden contener retrasos, omisiones o errores. Este informe no constituye asesoramiento financiero.")
        except Exception as exc:
            st.error(f"No se pudo generar el informe: {exc}")
            st.caption("Comprueba el ticker y la conectividad del proveedor. Algunos activos requieren sufijos de mercado, por ejemplo .MC, .L o .DE.")
else:
    st.markdown("### Qué incluye el PDF")
    st.markdown("- Resumen ejecutivo y perfil de la compañía.\n- Precio ajustado, EMA20/50/200, RSI(14), ATR(14), ROC20 y volumen relativo.\n- Retornos históricos, CAGR aproximada, volatilidad anualizada y drawdown máximo.\n- Gráficos de precio/medias y distribución de retornos.\n- Fundamentales disponibles, sector/industria y noticias recientes cuando el proveedor los facilita.\n- Lectura narrativa por IA opcional, con riesgos y limitaciones explícitos.")
    st.warning("La primera versión utiliza Yahoo Finance como fuente de datos. Para uso comercial, revisa sus condiciones de uso y considera un proveedor financiero con SLA, cobertura y licencia adecuados.")
