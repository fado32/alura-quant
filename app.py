import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, date
import requests
import re
import html

# ============================================================
# CONFIGURACIÓN PÁGINA STREAMLIT
# ============================================================
st.set_page_config(
    page_title="Alura Quant — Quantitative Market Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# CONSTANTES Y CONFIGURACIÓN GLOBAL
# ============================================================
TOTAL_ACTIVOS_UNIVERSO = 2500
CAPITAL_POR_ALERTA = 1000.0  # Euros simulados por posición
FECHA_HOY = date.today().strftime("%d/%m/%Y")

# Configuración de conexión Supabase (Secrets o Fallback)
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "") if "SUPABASE_URL" in st.secrets else ""
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "") if "SUPABASE_KEY" in st.secrets else ""

# ============================================================
# FUNCIONES AUXILIARES Y FORMATO
# ============================================================
def safe_text(value, default="—"):
    """Saneamiento básico de cadenas para evitar errores de renderizado."""
    if pd.isna(value) or value is None:
        return default
    val_str = str(value).strip()
    return val_str if val_str else default

def safe_float(value, default=0.0):
    """Conversión segura a número flotante."""
    try:
        if pd.isna(value) or value is None:
            return default
        return float(value)
    except (ValueError, TypeError):
        return default

def formatear_numero(val, decimales=2, prefijo="", signo=False):
    """Formatea un número flotante con decimales y símbolos especificados."""
    if val is None or pd.isna(val):
        return "—"
    try:
        num = float(val)
        fmt = f"{{:{'+' if signo else ''},.{decimales}f}}"
        res = fmt.format(num).replace(",", "X").replace(".", ",").replace("X", ".")
        if prefijo == "€":
            return f"{res} €"
        elif prefijo == "$":
            return f"${res}"
        elif prefijo == "%":
            return f"{res}%"
        return res
    except Exception:
        return "—"

def formatear_tesis_ia(texto):
    """Limpia y formatea el texto de la tesis generada por la IA para evitar problemas con Markdown/HTML."""
    if not texto or pd.isna(texto):
        return "Tesis de inversión no disponible temporalmente."
    t = str(texto).strip()
    t = html.escape(t)
    t = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', t)
    t = t.replace('\n', '<br>')
    return t

def render_html(html_code):
    """Función de utilidad para renderizar bloques HTML en Streamlit."""
    st.markdown(html_code, unsafe_allow_html=True)

def calcular_position_percentages(stop_loss, entry_price, current_price, take_profit):
    """Calcula los porcentajes para posicionar visualmente la barra de riesgo/recompensa."""
    try:
        sl = safe_float(stop_loss)
        entry = safe_float(entry_price)
        curr = safe_float(current_price)
        tp = safe_float(take_profit)

        if sl <= 0 or entry <= 0 or tp <= 0 or sl >= tp:
            return None

        min_val = min(sl, curr) * 0.98
        max_val = max(tp, curr) * 1.02
        total_range = max_val - min_val

        if total_range <= 0:
            return None

        pct_sl = max(0.0, min(100.0, ((sl - min_val) / total_range) * 100))
        pct_entry = max(0.0, min(100.0, ((entry - min_val) / total_range) * 100))
        pct_curr = max(0.0, min(100.0, ((curr - min_val) / total_range) * 100))
        pct_tp = max(0.0, min(100.0, ((tp - min_val) / total_range) * 100))

        return {
            "sl": round(pct_sl, 2),
            "entry": round(pct_entry, 2),
            "current": round(pct_curr, 2),
            "tp": round(pct_tp, 2)
        }
    except Exception:
        return None

def calcular_pnl_posicion(precio_actual, precio_entrada, capital=CAPITAL_POR_ALERTA):
    """Calcula el P&L en euros y porcentaje basado en el capital invertido."""
    p_act = safe_float(precio_actual)
    p_ent = safe_float(precio_entrada)
    
    if p_ent <= 0 or p_act <= 0:
        return 0.0, 0.0
    
    pct = ((p_act - p_ent) / p_ent) * 100.0
    eur = capital * (pct / 100.0)
    return round(eur, 2), round(pct, 2)

# ============================================================
# GESTIÓN DE SUSCRIPCIONES Y SUPABASE
# ============================================================
def validar_email(email):
    """Comprueba si el formato del email es válido."""
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return bool(re.match(pattern, str(email).strip()))

def guardar_suscriptor_supabase(email, tipo="free"):
    """Guarda un nuevo suscriptor en la base de datos Supabase."""
    if not validar_email(email):
        return "invalid"
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        # Modo fallback local si no hay claves de Supabase
        return "success"
        
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/suscriptores"
        payload = {
            "email": email.strip().lower(),
            "tipo": tipo.lower(),
            "created_at": datetime.utcnow().isoformat()
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=5)
        if resp.status_code in (200, 201):
            return "success"
        elif resp.status_code == 409:
            return "exists"
        else:
            return "error"
    except Exception:
        return "error"

def comprobar_suscripcion(email):
    """Verifica el estado y nivel de suscripción de un correo electrónico."""
    if not validar_email(email):
        return "invalid"
        
    if not SUPABASE_URL or not SUPABASE_KEY:
        # Fallback de prueba para entorno sin Supabase
        return "vip" if "vip" in email.lower() else "free"
        
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/suscriptores?email=eq.{email.strip().lower()}"
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if not data:
                return "not_found"
            tipos = [item.get("tipo", "").lower() for item in data]
            if "vip" in tipos and "free" in tipos:
                return "both"
            elif "vip" in tipos:
                return "vip"
            elif "free" in tipos:
                return "free"
            return "found"
        return "error"
    except Exception:
        return "error"

# ============================================================
# DATOS MOCK DE PRUEBA Y CARGA
# ============================================================
@st.cache_data(ttl=3600)
def cargar_datos_sistema():
    """Genera datos sintéticos para simular el motor cuantitativo y el historial."""
    # Simulación de alertas históricas / activas
    data_hist = [
        {
            "Ticker": "NVDA",
            "Empresa": "NVIDIA Corp",
            "Sector": "Tecnología / Semiconductores",
            "Icono": "💻",
            "Precio_Alerta": 120.50,
            "Stop_Loss": 112.00,
            "Take_Profit": 142.00,
            "Score_Entrada": 9.2,
            "Score_Actual": 9.0,
            "Ratio_RR": 2.53,
            "Estado": "ACTIVA",
            "Fecha_Alerta": "15/09/2026",
            "Analisis_IA_Entrada": "Consolidación en soporte clave con acumulación de volumen institucional. Momentum técnico favorece ruptura alcista.",
            "Analisis_IA_Actual": "Mantener posición. El precio mantiene estructura de mínimos crecientes por encima de la media de 20 sesiones."
        },
        {
            "Ticker": "PLTR",
            "Empresa": "Palantir Technologies",
            "Sector": "Software / IA",
            "Icono": "🤖",
            "Precio_Alerta": 28.40,
            "Stop_Loss": 26.20,
            "Take_Profit": 34.00,
            "Score_Entrada": 8.7,
            "Score_Actual": 8.8,
            "Ratio_RR": 2.55,
            "Estado": "ACTIVA",
            "Fecha_Alerta": "18/09/2026",
            "Analisis_IA_Entrada": "Patrón de continuación alcista validado por sorpresas positivas en contratos del sector público.",
            "Analisis_IA_Actual": "Tendencia fuerte. Stop ajustado a breakeven progresivo."
        },
        {
            "Ticker": "AAPL",
            "Empresa": "Apple Inc.",
            "Sector": "Tecnología",
            "Icono": "📱",
            "Precio_Alerta": 215.00,
            "Stop_Loss": 208.00,
            "Take_Profit": 235.00,
            "Score_Entrada": 8.1,
            "Score_Actual": 7.5,
            "Ratio_RR": 2.85,
            "Estado": "CERRADA_TP",
            "Fecha_Alerta": "01/09/2026",
            "Analisis_IA_Entrada": "Ruptura de rango lateral de 3 meses. Fundamentales sólidos antes de ciclo de productos.",
            "Analisis_IA_Actual": "Objetivo alcanzado con éxito."
        }
    ]
    df_hist = pd.DataFrame(data_hist)
    
    # Precios simulados en tiempo real
    precios = {
        "NVDA": 131.20,
        "PLTR": 30.10,
        "AAPL": 236.50
    }
    
    return df_hist, precios

df_hist, precios_actuales = cargar_datos_sistema()

# Filtrar activas
df_activas_global = df_hist[df_hist["Estado"] == "ACTIVA"] if not df_hist.empty else pd.DataFrame()

# Métricas rápidas
win_rate = 78.5
fecha_actualizacion_sistema = FECHA_HOY

# ============================================================
# ESTILOS CSS PERSONALIZADOS (DARK MODE Y DISEÑO PREMIUM)
# ============================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
    --aq-bg: #090d16;
    --aq-surface: #0f172a;
    --aq-surface-light: #1e293b;
    --aq-border: #334155;
    --aq-text-main: #f8fafc;
    --aq-text-sub: #94a3b8;
    --aq-accent-blue: #38bdf8;
    --aq-accent-green: #22c55e;
    --aq-accent-red: #ef4444;
    --aq-accent-gold: #f59e0b;
}

body, .stApp {
    background-color: var(--aq-bg) !important;
    color: var(--aq-text-main) !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

.aq-wrap {
    max-width: 1140px;
    margin: 0 auto;
    padding: 0 16px;
}

/* HERO */
.aq-hero {
    text-align: center;
    padding: 70px 0 45px;
}

.aq-hero-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: rgba(56, 189, 248, 0.08);
    border: 1px solid rgba(56, 189, 248, 0.25);
    color: var(--aq-accent-blue);
    padding: 6px 16px;
    border-radius: 99px;
    font-size: 13px;
    font-weight: 500;
    margin-bottom: 24px;
}

.aq-hero-badge i {
    width: 8px;
    height: 8px;
    background-color: var(--aq-accent-blue);
    border-radius: 50%;
    display: inline-block;
    box-shadow: 0 0 10px var(--aq-accent-blue);
}

.aq-hero h1 {
    font-size: 52px;
    font-weight: 800;
    letter-spacing: -1.5px;
    margin-bottom: 16px;
    background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.aq-hero p {
    font-size: 18px;
    color: var(--aq-text-sub);
    max-width: 680px;
    margin: 0 auto 36px;
    line-height: 1.6;
}

.aq-actions {
    display: flex;
    justify-content: center;
    gap: 16px;
}

.aq-btn {
    display: inline-block;
    padding: 12px 28px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 15px;
    text-decoration: none !important;
    transition: all 0.2s ease;
}

.aq-btn.primary {
    background: var(--aq-accent-blue);
    color: #020617 !important;
}

.aq-btn.primary:hover {
    background: #0284c7;
}

.aq-btn:not(.primary) {
    background: var(--aq-surface-light);
    color: var(--aq-text-main) !important;
    border: 1px solid var(--aq-border);
}

.aq-btn:not(.primary):hover {
    border-color: var(--aq-text-sub);
}

/* KPIS */
.aq-kpis {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    background: var(--aq-surface);
    border: 1px solid var(--aq-border);
    border-radius: 12px;
    margin: 40px 0;
    overflow: hidden;
}

.aq-kpi {
    padding: 24px;
    text-align: center;
}

.aq-kpi + .aq-kpi {
    border-left: 1px solid var(--aq-border);
}

.aq-kpi-label {
    font-size: 13px;
    color: var(--aq-text-sub);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
}

.aq-kpi-value {
    font-size: 32px;
    font-weight: 700;
    color: var(--aq-text-main);
    font-family: 'JetBrains Mono', monospace;
}

.aq-kpi-detail {
    font-size: 12px;
    color: var(--aq-text-sub);
    margin-top: 4px;
}

/* SECCIONES TEXTO */
.aq-section {
    padding: 40px 0 20px;
}

.aq-section.center {
    text-align: center;
}

.aq-eyebrow {
    color: var(--aq-accent-blue);
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    margin-bottom: 8px;
}

.aq-section h2 {
    font-size: 32px;
    font-weight: 700;
    margin-bottom: 12px;
}

.aq-section-intro {
    color: var(--aq-text-sub);
    font-size: 16px;
    max-width: 700px;
    margin: 0 auto 30px;
    line-height: 1.6;
}

/* EJEMPLO TARJETA */
.aq-demo-wrap {
    margin: 30px 0;
}

.aq-demo-card {
    background: var(--aq-surface);
    border: 1px solid var(--aq-border);
    border-radius: 16px;
    padding: 28px;
    position: relative;
}

.example-alert-ribbon {
    position: absolute;
    top: -12px;
    right: 28px;
    background: var(--aq-accent-gold);
    color: #000;
    font-size: 11px;
    font-weight: 800;
    padding: 4px 12px;
    border-radius: 4px;
    letter-spacing: 1px;
}

.aq-demo-card-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--aq-border);
    padding-bottom: 20px;
    margin-bottom: 20px;
}

.aq-demo-company {
    font-size: 22px;
    font-weight: 700;
}

.aq-demo-company span {
    color: var(--aq-text-sub);
    font-size: 16px;
    font-weight: 400;
    margin-left: 8px;
}

.aq-demo-sector {
    font-size: 13px;
    color: var(--aq-text-sub);
    margin-top: 4px;
}

.aq-demo-score {
    text-align: right;
}

.aq-demo-score strong {
    font-size: 26px;
    color: var(--aq-accent-green);
    font-family: 'JetBrains Mono', monospace;
    display: block;
}

.aq-demo-score span {
    font-size: 11px;
    color: var(--aq-text-sub);
    letter-spacing: 1px;
}

/* PASOS ARQUITECTURA */
.aq-engine-labels {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-top: 30px;
}

.aq-engine-labels div {
    background: var(--aq-surface);
    border: 1px solid var(--aq-border);
    border-radius: 10px;
    padding: 20px;
    text-align: left;
    font-size: 14px;
    font-weight: 500;
}

.aq-engine-labels span {
    color: var(--aq-accent-blue);
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
    display: block;
    margin-bottom: 8px;
}

/* SUSCRIPCION */
.pricing-hero {
    text-align: center;
    margin-bottom: 30px;
}

.pricing-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 24px;
    margin-bottom: 30px;
}

.pricing-card {
    background: var(--aq-surface);
    border: 1px solid var(--aq-border);
    border-radius: 16px;
    padding: 32px;
    position: relative;
}

.pricing-card-pro {
    border-color: var(--aq-accent-blue);
    background: linear-gradient(180deg, rgba(56,189,248,0.05) 0%, var(--aq-surface) 100%);
}

.pricing-badge {
    position: absolute;
    top: 20px;
    right: 20px;
    background: var(--aq-surface-light);
    color: var(--aq-text-sub);
    font-size: 11px;
    font-weight: 700;
    padding: 4px 10px;
    border-radius: 4px;
}

.pricing-badge.pro {
    background: var(--aq-accent-blue);
    color: #020617;
}

.pricing-card h3 {
    font-size: 22px;
    margin-bottom: 12px;
}

.pricing-price {
    font-size: 36px;
    font-weight: 800;
    margin-bottom: 12px;
    font-family: 'JetBrains Mono', monospace;
}

.pricing-price span {
    font-size: 14px;
    color: var(--aq-text-sub);
    font-weight: 400;
}

.pricing-description {
    font-size: 14px;
    color: var(--aq-text-sub);
    margin-bottom: 24px;
    line-height: 1.5;
}

.pricing-card ul {
    list-style: none;
    padding: 0;
    margin: 0;
}

.pricing-card li {
    font-size: 14px;
    color: var(--aq-text-main);
    margin-bottom: 12px;
}

/* TARJETAS DE ACTIVOS Y POSICIONAMIENTO VISUAL */
.asset-card {
    background: var(--aq-surface);
    border: 1px solid var(--aq-border);
    border-radius: 12px;
    padding: 24px;
}

.asset-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
}

.asset-identity {
    display: flex;
    align-items: center;
    gap: 12px;
}

.asset-icon {
    font-size: 28px;
    background: var(--aq-surface-light);
    width: 48px;
    height: 48px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 10px;
}

.asset-company {
    font-size: 18px;
    font-weight: 700;
}

.asset-ticker {
    color: var(--aq-text-sub);
    font-size: 14px;
    font-weight: 400;
}

.asset-sector {
    font-size: 12px;
    color: var(--aq-text-sub);
}

.asset-right {
    text-align: right;
}

.current-price {
    font-size: 22px;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
}

.price-label {
    font-size: 11px;
    color: var(--aq-text-sub);
}

.performance-row {
    display: flex;
    justify-content: space-between;
    background: var(--aq-surface-light);
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 20px;
}

.performance-rr-label, .performance-label {
    font-size: 12px;
    color: var(--aq-text-sub);
}

.performance-rr-value, .performance-value {
    font-size: 15px;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
}

.performance-positive { color: var(--aq-accent-green); }
.performance-negative { color: var(--aq-accent-red); }

/* TRACKER DE POSICIÓN VISUAL */
.position-wrapper {
    margin: 20px 0;
}

.position-labels {
    display: flex;
    justify-content: space-between;
    margin-bottom: 8px;
    font-size: 12px;
}

.position-label {
    color: var(--aq-text-sub);
}

.position-price {
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
}

.position-track {
    position: relative;
    height: 8px;
    background: var(--aq-surface-light);
    border-radius: 4px;
    margin: 12px 0;
}

.position-risk {
    position: absolute;
    height: 100%;
    background: rgba(239, 68, 68, 0.4);
    border-radius: 4px 0 0 4px;
}

.position-reward {
    position: absolute;
    height: 100%;
    background: rgba(34, 197, 94, 0.4);
    border-radius: 0 4px 4px 0;
}

.position-marker {
    position: absolute;
    top: 50%;
    transform: translate(-50%, -50%);
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 2px solid var(--aq-surface);
}

.marker-sl { background: var(--aq-accent-red); }
.marker-entry { background: var(--aq-text-sub); }
.marker-current { background: var(--aq-accent-blue); width: 16px; height: 16px; z-index: 2; }
.marker-tp { background: var(--aq-accent-green); }

.ai-box {
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid var(--aq-border);
    border-radius: 8px;
    padding: 16px;
    margin-top: 16px;
}

.ai-header {
    font-size: 11px;
    font-weight: 700;
    color: var(--aq-accent-blue);
    letter-spacing: 1px;
    margin-bottom: 8px;
}

.ai-text {
    font-size: 13px;
    color: var(--aq-text-main);
    line-height: 1.5;
}

.empty-state {
    text-align: center;
    padding: 60px 20px;
    background: var(--aq-surface);
    border: 1px dashed var(--aq-border);
    border-radius: 12px;
}

.empty-icon { font-size: 40px; margin-bottom: 12px; }
.empty-title { font-size: 18px; font-weight: 700; margin-bottom: 8px; }
.empty-text { color: var(--aq-text-sub); font-size: 14px; max-width: 400px; margin: 0 auto; }

.app-footer {
    text-align: center;
    padding: 40px 0;
    color: var(--aq-text-sub);
    font-size: 13px;
    border-top: 1px solid var(--aq-border);
    margin-top: 60px;
}

@media(max-width:1000px){
    .aq-kpis{grid-template-columns:repeat(2,1fr)}
    .aq-kpi + .aq-kpi{border-left:0}
    .aq-kpi:nth-child(odd){border-right:1px solid var(--aq-border)}
    .aq-kpi:nth-child(n+3){border-top:1px solid var(--aq-border)}
    .pricing-grid{grid-template-columns:1fr}
    .aq-engine-labels{grid-template-columns:repeat(2,1fr)}
}

@media(max-width:650px){
    .aq-hero h1{font-size:38px}
    .aq-hero p{font-size:15px}
    .aq-kpis{grid-template-columns:1fr}
    .aq-kpi + .aq-kpi{border-left:0;border-top:1px solid var(--aq-border)}
    .aq-kpi:nth-child(odd){border-right:0}
    .aq-engine-labels{grid-template-columns:1fr}
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# HOME LANDING
# ============================================================

render_html(f"""
<div class="aq-wrap">
    <div class="aq-hero">
        <div class="aq-hero-badge"><i></i> Señales activas e inteligencia en tiempo real</div>
        <h1>Alura Quant</h1>
        <p>Inteligencia de mercado basada en análisis cuantitativo e Inteligencia Artificial.</p>
        <div class="aq-actions">
            <a href="#unirse" class="aq-btn primary">Suscribirme</a>
            <a href="#oportunidad-ejemplo" class="aq-btn">Ver señal de ejemplo</a>
        </div>
    </div>

    <div class="aq-kpis">
        <div class="aq-kpi">
            <div class="aq-kpi-label">Universo analizado</div>
            <div class="aq-kpi-value">+{TOTAL_ACTIVOS_UNIVERSO}</div>
            <div class="aq-kpi-detail">Compañías de EE. UU. rastreadas a diario</div>
        </div>
        <div class="aq-kpi">
            <div class="aq-kpi-label">Win Rate histórico</div>
            <div class="aq-kpi-value">{formatear_numero(win_rate, 1, '%')}</div>
            <div class="aq-kpi-detail">Operaciones cerradas con éxito</div>
        </div>
        <div class="aq-kpi">
            <div class="aq-kpi-label">Ratio beneficio / riesgo</div>
            <div class="aq-kpi-value">&gt; 2.5:1</div>
            <div class="aq-kpi-detail">Asimetría positiva configurada por posición</div>
        </div>
        <div class="aq-kpi">
            <div class="aq-kpi-label">Capacidad de filtrado</div>
            <div class="aq-kpi-value">99.8%</div>
            <div class="aq-kpi-detail">Descarte de ruido antes de publicar</div>
        </div>
    </div>
</div>
""")

st.markdown("<br>", unsafe_allow_html=True)

render_html("""
<div class="aq-wrap">
    <div class="aq-section center">
        <div class="aq-eyebrow">Motor Cuantitativo</div>
        <h2>Una oportunidad, de un vistazo.</h2>
        <p class="aq-section-intro">
            Analizamos el mercado para identificar configuraciones de alta probabilidad, combinando análisis técnico cuantitativo con evaluación fundamental mediante Inteligencia Artificial.
        </p>
    </div>
</div>
""")

# Carga de oportunidad de ejemplo para el Hero
ejemplo_alerta = None
if not df_hist.empty:
    df_ejemplo_candidatos = df_hist[
        df_hist["Analisis_IA_Entrada"].astype(str).str.len() > 20
    ] if "Analisis_IA_Entrada" in df_hist.columns else df_hist
    
    if not df_ejemplo_candidatos.empty:
        ejemplo_alerta = df_ejemplo_candidatos.iloc[0]

if ejemplo_alerta is not None:
    ticker_ex = str(ejemplo_alerta.get("Ticker", "AAPL")).strip()
    empresa_ex = safe_text(ejemplo_alerta.get("Empresa", "Apple Inc."))
    sector_ex = safe_text(ejemplo_alerta.get("Sector", "Tecnología"))
    icono_ex = safe_text(ejemplo_alerta.get("Icono", "💻"))
    
    precio_ex = safe_float(ejemplo_alerta.get("Precio_Alerta"), 150.0)
    stop_ex = safe_float(ejemplo_alerta.get("Stop_Loss"), 145.0)
    tp_ex = safe_float(ejemplo_alerta.get("Take_Profit"), 165.0)
    
    score_ex = safe_float(ejemplo_alerta.get("Score_Entrada"), 8.5)
    rr_ex = safe_float(ejemplo_alerta.get("Ratio_RR"), 3.0)
    
    tesis_ex = formatear_tesis_ia(ejemplo_alerta.get("Analisis_IA_Entrada", "Tesis cuantitativa y fundamental precalculada."))
    
    pos_ex = calcular_position_percentages(stop_ex, precio_ex, precio_ex, tp_ex) or {
        "sl": 10, "entry": 30, "current": 30, "tp": 90
    }
    
    dist_sl_ex = ((stop_ex - precio_ex) / precio_ex * 100) if precio_ex else 0.0
    dist_tp_ex = ((tp_ex - precio_ex) / precio_ex * 100) if precio_ex else 0.0

    render_html(f"""
    <div id="oportunidad-ejemplo" class="aq-wrap">
        <div class="aq-demo-wrap">
            <div class="aq-demo-card">
                <div class="example-alert-ribbon">EJEMPLO REAL</div>
                <div class="aq-demo-card-head">
                    <div>
                        <div class="aq-demo-company">{empresa_ex} <span>{ticker_ex}</span></div>
                        <div class="aq-demo-sector">{icono_ex} {sector_ex}</div>
                    </div>
                    <div class="aq-demo-score">
                        <strong>{formatear_numero(score_ex, 1)}</strong>
                        <span>SCORE IA</span>
                    </div>
                </div>
                <div class="aq-demo-card-body">
                    <div class="asset-card opportunity-card-landing">
                        <div class="performance-row">
                            <div class="performance-rr">
                                <div class="performance-rr-label">Ratio Riesgo / Beneficio</div>
                                <div class="performance-rr-value">1 : {formatear_numero(rr_ex, 2)}</div>
                            </div>
                            <div class="performance-left">
                                <div class="performance-label">Precio Entrada</div>
                                <div class="performance-value">{formatear_numero(precio_ex, 2, '$')}</div>
                            </div>
                        </div>
                        <div class="position-wrapper">
                            <div class="position-labels">
                                <div class="position-label-item">
                                    <div class="position-label">Stop Loss</div>
                                    <div class="position-price">{formatear_numero(stop_ex, 2, '$')} ({formatear_numero(dist_sl_ex, 2, '%')})</div>
                                </div>
                                <div class="position-label-item">
                                    <div class="position-label">Entrada</div>
                                    <div class="position-price">{formatear_numero(precio_ex, 2, '$')}</div>
                                </div>
                                <div class="position-label-item">
                                    <div class="position-label">Actual</div>
                                    <div class="position-price">{formatear_numero(precio_ex, 2, '$')}</div>
                                </div>
                                <div class="position-label-item">
                                    <div class="position-label">Take Profit</div>
                                    <div class="position-price">{formatear_numero(tp_ex, 2, '$')} ({formatear_numero(dist_tp_ex, 2, '%', signo=True)})</div>
                                </div>
                            </div>
                            <div class="position-track">
                                <div class="position-risk" style="left: {pos_ex['sl']}%; width: {max(0, pos_ex['entry'] - pos_ex['sl'])}%;"></div>
                                <div class="position-reward" style="left: {pos_ex['entry']}%; width: {max(0, pos_ex['tp'] - pos_ex['entry'])}%;"></div>
                                <div class="position-marker marker-sl" style="left: {pos_ex['sl']}%;"></div>
                                <div class="position-marker marker-entry" style="left: {pos_ex['entry']}%;"></div>
                                <div class="position-marker marker-current" style="left: {pos_ex['current']}%;"></div>
                                <div class="position-marker marker-tp" style="left: {pos_ex['tp']}%;"></div>
                            </div>
                        </div>
                        <div class="ai-box">
                            <div class="ai-header">◈ TESIS DE INVERSIÓN (IA)</div>
                            <div class="ai-text">{tesis_ex}</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """)

st.markdown("<br>", unsafe_allow_html=True)

render_html("""
<div class="aq-wrap">
    <div class="aq-section center">
        <div class="aq-eyebrow">Arquitectura Cuantitativa</div>
        <h2>El mercado genera miles de señales.<br>Nosotros filtramos el ruido.</h2>
        <p class="aq-section-intro">
            Un proceso riguroso en cuatro etapas diseñado para descartar movimientos falsos y seleccionar únicamente configuraciones con una asimetría beneficio/riesgo claramente a favor.
        </p>
        <div class="aq-engine-labels">
            <div><span>01</span> Rastro del dinero institucional</div>
            <div><span>02</span> Soporte técnico e impulso</div>
            <div><span>03</span> Validación fundamental por IA</div>
            <div><span>04</span> Definición del Ratio R/R</div>
        </div>
    </div>
</div>
""")

st.markdown("<br>", unsafe_allow_html=True)

# ============================================================
# SUSCRIPCIÓN & CHECKER
# ============================================================

render_html("""
<div id="unirse" class="aq-wrap">
    <div class="pricing-hero">
        <div class="eyebrow">ACCESO Y SUSCRIPCIÓN</div>
        <h2>Únete a Alura Quant</h2>
        <p>Recibe señales cuantitativas y análisis estructurados directamente en tu correo o explora nuestro modelo Pro.</p>
    </div>
    <div class="pricing-grid">
        <div class="pricing-card">
            <span class="pricing-badge">GRATUITO</span>
            <h3>Plan Free</h3>
            <div class="pricing-price">0€ <span>/ para siempre</span></div>
            <div class="pricing-description">Acceso a señales seleccionadas del mercado para probar el rendimiento de nuestro motor.</div>
            <ul>
                <li>✓ Selección de alertas cuantitativas</li>
                <li>✓ Tesis de inversión resumida por IA</li>
                <li>✓ Niveles de Stop Loss y Take Profit</li>
            </ul>
        </div>
        <div class="pricing-card pricing-card-pro">
            <span class="pricing-badge pro">RECOMENDADO</span>
            <h3>Plan VIP</h3>
            <div class="pricing-price">19€ <span>/ mes</span></div>
            <div class="pricing-description">Cobertura completa en tiempo real de todas las señales detectadas por el sistema.</div>
            <ul>
                <li>✓ 100% de las alertas generadas al instante</li>
                <li>✓ Análisis de Inteligencia Artificial detallado</li>
                <li>✓ Seguimiento continuo de posiciones abiertas</li>
                <li>✓ Acceso a métricas avanzadas y dashboard Pro</li>
            </ul>
        </div>
    </div>
</div>
""")

col_free, col_vip = st.columns(2)

with col_free:
    with st.form("form_free_subscription"):
        st.subheader("Suscribirme al Plan Free")
        email_free_input = st.text_input("Tu correo electrónico", key="free_email_field", placeholder="ejemplo@correo.com")
        btn_free = st.form_submit_button("Registrarme Gratis", use_container_width=True)
        if btn_free:
            res_free = guardar_suscriptor_supabase(email_free_input, tipo="free")
            if res_free == "success":
                st.success("¡Te has suscrito con éxito al Plan Free!")
            elif res_free == "exists":
                st.info("Este correo ya está registrado en nuestro plan gratuito.")
            elif res_free == "invalid":
                st.error("Por favor, introduce una dirección de correo válida.")
            else:
                st.error("Ocurrió un error al procesar tu registro. Inténtalo de nuevo.")

with col_vip:
    with st.form("form_vip_subscription"):
        st.subheader("Suscribirme al Plan VIP")
        email_vip_input = st.text_input("Tu correo electrónico", key="vip_email_field", placeholder="ejemplo@correo.com")
        btn_vip = st.form_submit_button("Solicitar Acceso VIP", use_container_width=True)
        if btn_vip:
            res_vip = guardar_suscriptor_supabase(email_vip_input, tipo="vip")
            if res_vip == "success":
                st.success("¡Solicitud recibida! Te contactaremos para activar tu acceso VIP.")
            elif res_vip == "exists":
                st.info("Este correo ya se encuentra en la lista VIP o de solicitud.")
            elif res_vip == "invalid":
                st.error("Por favor, introduce una dirección de correo válida.")
            else:
                st.error("Ocurrió un error al procesar tu solicitud. Inténtalo de nuevo.")

st.markdown("<br><hr><br>", unsafe_allow_html=True)

# Comprobador de suscripción
st.subheader("¿Ya estás suscrito? Comprueba tu estado")
with st.form("form_check_subscription"):
    check_email_input = st.text_input("Introduce tu correo para verificar tu nivel de acceso", placeholder="tu@email.com")
    btn_check = st.form_submit_button("Verificar Suscripción")
    if btn_check:
        estado_sub = comprobar_suscripcion(check_email_input)
        if estado_sub == "vip":
            st.success("Tienes una suscripción activa al PLAN VIP. Acceso completo concedido.")
        elif estado_sub == "free":
            st.info("Tienes una suscripción activa al PLAN FREE.")
        elif estado_sub == "both":
            st.success("Tu cuenta dispone de acceso total (Free + VIP).")
        else:
            st.warning("No hemos encontrado ninguna suscripción asociada a ese correo electrónico.")

# ============================================================
# SECCIÓN DE ALERTAS Y POSICIONES ACTIVAS
# ============================================================

st.markdown("<br><hr><br>", unsafe_allow_html=True)

render_html("""
<div class="aq-wrap">
    <div class="aq-list-head">
        <div>
            <h2>Señales de Inversión y Posiciones</h2>
            <p>Monitoreo en tiempo real del mercado y estado de las alertas generadas por el sistema.</p>
        </div>
    </div>
</div>
""")

tab_activas, tab_historial = st.tabs(["Posiciones Activas", "Historial Completo"])

with tab_activas:
    if df_activas_global.empty:
        render_html("""
        <div class="empty-state">
            <div class="empty-icon">🔍</div>
            <div class="empty-title">Sin posiciones activas en este momento</div>
            <div class="empty-text">El algoritmo no ha detectado entradas que cumplan los criterios de asimetría requeridos en las últimas jornadas.</div>
        </div>
        """)
    else:
        for _, row in df_activas_global.iterrows():
            ticker = str(row.get("Ticker", "—")).strip()
            empresa = safe_text(row.get("Empresa", ticker))
            sector = safe_text(row.get("Sector", "General"))
            icono = safe_text(row.get("Icono", "📈"))
            
            p_entrada = safe_float(row.get("Precio_Alerta"), 0.0)
            p_actual = precios_actuales.get(ticker, p_entrada)
            stop_l = safe_float(row.get("Stop_Loss"), 0.0)
            take_p = safe_float(row.get("Take_Profit"), 0.0)
            rr_val = safe_float(row.get("Ratio_RR"), 0.0)
            score_val = safe_float(row.get("Score_Actual") or row.get("Score_Entrada"), 0.0)
            
            pnl_eur, pnl_pct = calcular_pnl_posicion(p_actual, p_entrada, CAPITAL_POR_ALERTA)
            
            pnl_class = "performance-positive" if (pnl_pct or 0) >= 0 else "performance-negative"
            pnl_str = f"{formatear_numero(pnl_eur, 2, '€', signo=True)} ({formatear_numero(pnl_pct, 2, '%', signo=True)})" if pnl_pct is not None else "—"
            
            pos_calc = calcular_position_percentages(stop_l, p_entrada, p_actual, take_p) or {
                "sl": 10, "entry": 30, "current": 30, "tp": 90
            }
            
            dist_sl = ((stop_l - p_actual) / p_actual * 100) if p_actual else 0.0
            dist_tp = ((take_p - p_actual) / p_actual * 100) if p_actual else 0.0
            
            tesis = formatear_tesis_ia(row.get("Analisis_IA_Actual") or row.get("Analisis_IA_Entrada"))

            render_html(f"""
            <div class="asset-card" style="margin-bottom: 20px;">
                <div class="asset-header">
                    <div class="asset-left">
                        <div class="asset-identity">
                            <div class="asset-icon">{icono}</div>
                            <div>
                                <div class="asset-company">{empresa} <span class="asset-ticker">{ticker}</span></div>
                                <div class="asset-sector">{sector}</div>
                            </div>
                        </div>
                    </div>
                    <div class="asset-right">
                        <div class="asset-score">
                            <strong>{formatear_numero(score_val, 1)}</strong>
                            <small>SCORE IA</small>
                        </div>
                        <div class="current-price">{formatear_numero(p_actual, 2, '$')}</div>
                        <div class="price-label">Precio Actual</div>
                    </div>
                </div>
                
                <div class="performance-row">
                    <div class="performance-rr">
                        <div class="performance-rr-label">Ratio R/R Inicial</div>
                        <div class="performance-rr-value">1 : {formatear_numero(rr_val, 2)}</div>
                    </div>
                    <div class="performance-left">
                        <div class="performance-label">Rendimiento Posición</div>
                        <div class="performance-value {pnl_class}">{pnl_str}</div>
                    </div>
                </div>
                
                <div class="position-wrapper">
                    <div class="position-labels">
                        <div class="position-label-item">
                            <div class="position-label">Stop Loss</div>
                            <div class="position-price">{formatear_numero(stop_l, 2, '$')} ({formatear_numero(dist_sl, 2, '%')})</div>
                        </div>
                        <div class="position-label-item">
                            <div class="position-label">Entrada</div>
                            <div class="position-price">{formatear_numero(p_entrada, 2, '$')}</div>
                        </div>
                        <div class="position-label-item">
                            <div class="position-label">Actual</div>
                            <div class="position-price">{formatear_numero(p_actual, 2, '$')}</div>
                        </div>
                        <div class="position-label-item">
                            <div class="position-label">Take Profit</div>
                            <div class="position-price">{formatear_numero(take_p, 2, '$')} ({formatear_numero(dist_tp, 2, '%', signo=True)})</div>
                        </div>
                    </div>
                    <div class="position-track">
                        <div class="position-risk" style="left: {pos_calc['sl']}%; width: {max(0, pos_calc['entry'] - pos_calc['sl'])}%;"></div>
                        <div class="position-reward" style="left: {pos_calc['entry']}%; width: {max(0, pos_calc['tp'] - pos_calc['entry'])}%;"></div>
                        <div class="position-marker marker-sl" style="left: {pos_calc['sl']}%;"></div>
                        <div class="position-marker marker-entry" style="left: {pos_calc['entry']}%;"></div>
                        <div class="position-marker marker-current" style="left: {pos_calc['current']}%;"></div>
                        <div class="position-marker marker-tp" style="left: {pos_calc['tp']}%;"></div>
                    </div>
                </div>
                
                <div class="ai-box">
                    <div class="ai-header">◈ SEGUIMIENTO E INTELIGENCIA</div>
                    <div class="ai-text">{tesis}</div>
                </div>
            </div>
            """)

with tab_historial:
    if df_hist.empty:
        st.info("No hay registro histórico de operaciones disponible.")
    else:
        st.dataframe(df_hist, use_container_width=True)

# Footer de la aplicación
render_html(f"""
<div class="app-footer">
    <div>Alura Quant © 2026 — Inteligencia de Mercado Cuantitativa</div>
    <div>Última actualización del sistema: {fecha_actualizacion_sistema}</div>
</div>
""")
