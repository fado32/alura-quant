import os, re, json, html, time, logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import pandas as pd
from supabase import create_client, Client
from openai import OpenAI
import resend

# ============================================================
# ALURA QUANT — ALERTAS PREMIUM
# Detecta nuevas alertas ACTIVAS con Score >= 80 y envía una
# ficha cuantitativa integrada en HTML nativo + contexto IA.
# ============================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("alura-alertas")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
IA_PROVIDER = os.getenv("IA_PROVIDER", "gemini").strip().lower()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
FROM_EMAIL = os.getenv("ALURA_ALERT_FROM", "Alura Quant <onboarding@resend.dev>").strip()
SCORE_MIN = float(os.getenv("ALURA_ALERT_SCORE_MIN", "80"))
LOOKBACK_HOURS = int(os.getenv("ALURA_ALERT_LOOKBACK_HOURS", "48"))
DRY_RUN = os.getenv("ALURA_ALERT_DRY_RUN", "false").lower() == "true"
IA_DELAY = float(os.getenv("ALURA_ALERT_IA_DELAY", "1.5"))

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY.")
if not RESEND_API_KEY and not DRY_RUN:
    raise RuntimeError("Falta RESEND_API_KEY. Usa ALURA_ALERT_DRY_RUN=true para probar.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


def ai_client():
    if IA_PROVIDER != "gemini":
        raise RuntimeError(f"IA_PROVIDER no válido: {IA_PROVIDER}. Usa gemini.")
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Falta GEMINI_API_KEY.")
    return OpenAI(api_key=key, base_url=GEMINI_BASE_URL)


def safe(v, default="—"):
    if v is None: return default
    try:
        if pd.isna(v): return default
    except Exception: pass
    s = str(v).strip()
    return s if s else default


def num(v, d=2):
    try:
        if v is None or pd.isna(v): return "—"
        return f"{float(v):,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception: return "—"


def pct(v, d=2):
    try: return f"{float(v):+.{d}f}%"
    except Exception: return "—"


def eur(v):
    try: return num(v, 2) + " €"
    except Exception: return "—"


def esc(v): return html.escape(str(safe(v)), quote=True)


def get_subscribers():
    r = supabase.table("suscriptores_free").select("email").execute()
    return list(dict.fromkeys(str(x.get("email", "")).strip() for x in (r.data or []) if "@" in str(x.get("email", ""))))


def get_new_alerts():
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    cols = ("id,fecha,ticker,empresa,sector,icono,modo,precio_alerta,score_entrada,rvol_entrada,"
            "rsi_entrada,roc20_entrada,atr_entrada,ema50_entrada,ema200_entrada,razones_entrada,"
            "soporte_entrada,resistencia_entrada,analisis_ia_entrada,stop_loss,take_profit,ratio_rr,"
            "riesgo_euros,acciones,nominal,estado_estrategia,fecha_mercado_actual,estado,precio_actual")
    r = (supabase.table("historial_alertas").select(cols).eq("estado", "ACTIVA")
         .gte("fecha", since.isoformat()).gte("score_entrada", SCORE_MIN)
         .order("fecha", desc=True).execute())
    df = pd.DataFrame(r.data or [])
    if df.empty: return []
    df["fecha_dt"] = pd.to_datetime(df["fecha"], errors="coerce", utc=True)
    df["score_n"] = pd.to_numeric(df["score_entrada"], errors="coerce")
    df = df[(df["fecha_dt"] >= pd.Timestamp(since)) & (df["score_n"] >= SCORE_MIN)
            & (df["estado"].astype(str).str.upper() == "ACTIVA")]
    return df.sort_values("fecha_dt", ascending=False).drop_duplicates("ticker").to_dict("records")


def get_news(ticker, company, limit=4):
    news, seen = [], set()
    queries = [f'"{company}" stock', f'"{company}"'] if company else [f'"{ticker}" stock']
    for q in queries:
        if len(news) >= limit: break
        try:
            url = "https://news.google.com/rss/search?q=" + quote_plus(q) + "&hl=en-US&gl=US&ceid=US:en"
            req = Request(url, headers={"User-Agent": "AluraQuant/1.0"})
            root = ET.fromstring(urlopen(req, timeout=10).read())
            for item in root.findall("./channel/item"):
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                key = (title.lower(), link)
                if not title or key in seen: continue
                seen.add(key)
                news.append({"title": title, "link": link, "source": item.findtext("source", "").strip(), "date": item.findtext("pubDate", "").strip()})
                if len(news) >= limit: break
        except Exception as e:
            log.warning("Noticias %s: %s", ticker, e)
    return news


def ai_context(a, news):
    news_txt = "\n".join(f"- {n['title']} | {n['source']} | {n['date']} | {n['link']}" for n in news) or "No se encontraron noticias verificables."
    prompt = f'''Eres analista senior de Alura Quant. Genera el contexto empresarial de una alerta cuantitativa.

EMPRESA: {safe(a.get('empresa'))}
TICKER: {safe(a.get('ticker'))}
SECTOR: {safe(a.get('sector'))}
PRECIO: {eur(a.get('precio_alerta'))}
SCORE: {num(a.get('score_entrada'),0)}/100
RVOL: {num(a.get('rvol_entrada'))}x | RSI: {num(a.get('rsi_entrada'))} | ROC20: {pct(a.get('roc20_entrada'))}
EMA50: {eur(a.get('ema50_entrada'))} | EMA200: {eur(a.get('ema200_entrada'))}
SOPORTE: {eur(a.get('soporte_entrada'))} | RESISTENCIA: {eur(a.get('resistencia_entrada'))}

NOTICIAS:
{news_txt}

Devuelve SOLO JSON válido con:
empresa_contexto, sector_contexto, noticias_contexto, comentario_contexto, riesgos_contexto, titular_contexto.
Empresa_contexto: 2-3 frases sobre qué hace la compañía.
Sector_contexto: 1-2 frases sobre el sector.
Noticias_contexto: 2-4 frases; no inventes noticias y diferencia hechos de interpretación.
Comentario_contexto: 2-3 frases conectando contexto y señal, sin cambiar los datos técnicos.
Riesgos_contexto: 1-2 frases.
Titular_contexto: máximo 90 caracteres.
No inventes cifras. No inventes hechos. No cambies Score, RSI, RVOL, ROC20 ni niveles técnicos.'''
    try:
        r = ai_client().chat.completions.create(
            model=GEMINI_MODEL,
            messages=[{"role":"system","content":"Analista financiero. Devuelve JSON puro."},{"role":"user","content":prompt}],
            temperature=0.25)
        time.sleep(IA_DELAY)
        raw = re.sub(r"```(?:json)?|
