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
FROM_EMAIL = os.getenv("ALURA_ALERT_FROM", "Alura Quant <updates@aluraquant.es>").strip()
SCORE_MIN = float(os.getenv("ALURA_ALERT_SCORE_MIN", "55"))
LOOKBACK_HOURS = int(os.getenv("ALURA_ALERT_LOOKBACK_HOURS", "1248"))
DRY_RUN = os.getenv("ALURA_ALERT_DRY_RUN", "false").lower() == "true"
IA_DELAY = float(os.getenv("ALURA_ALERT_IA_DELAY", "1.5"))
REPEAT_COOLDOWN_DAYS = int(os.getenv("ALURA_ALERT_REPEAT_COOLDOWN_DAYS", "30"))

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


def get_sent_tickers():
    """Tickers enviados dentro del periodo de enfriamiento configurable."""
    tickers = set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=REPEAT_COOLDOWN_DAYS)
    page_size = 1000
    offset = 0
    while True:
        r = (supabase.table("cola_envios_alertas").select("ticker")
             .gte("fecha_envio", cutoff.isoformat())
             .range(offset, offset + page_size - 1).execute())
        rows = r.data or []
        tickers.update(str(row.get("ticker", "")).strip().upper() for row in rows if row.get("ticker"))
        if len(rows) < page_size:
            break
        offset += page_size
    return tickers

def get_new_alerts(excluded_tickers):
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    cols = ("id,fecha,ticker,empresa,sector,icono,modo,precio_alerta,score_entrada,score_actual,pnl_actual_pct,rvol_entrada,"
            "rsi_entrada,roc20_entrada,atr_entrada,ema50_entrada,ema200_entrada,razones_entrada,"
            "soporte_entrada,resistencia_entrada,analisis_ia_entrada,analisis_ia_actual,stop_loss,take_profit,ratio_rr,"
            "riesgo_euros,acciones,nominal,estado_estrategia,fecha_mercado_actual,estado,precio_actual")
    r = (supabase.table("historial_alertas").select(cols).eq("estado", "ACTIVA")
         .gte("fecha", since.isoformat())
         .order("score_actual", desc=True).execute())
    df = pd.DataFrame(r.data or [])
    if df.empty:
        return []
    df["fecha_dt"] = pd.to_datetime(df["fecha"], errors="coerce", utc=True)
    df["score_n"] = pd.to_numeric(df["score_entrada"], errors="coerce")
    df["score_actual_n"] = pd.to_numeric(df["score_actual"], errors="coerce")
    df["score_filtro"] = df["score_actual_n"].fillna(df["score_n"])
    df["pnl_actual_n"] = pd.to_numeric(df["pnl_actual_pct"], errors="coerce")
    df["ticker_key"] = df["ticker"].astype(str).str.strip().str.upper()
    has_current_score = df["score_actual_n"].notna()
    current_score_has_upside = df["pnl_actual_n"].between(-1.5, 2, inclusive="both")
    df = df[(df["fecha_dt"] >= pd.Timestamp(since)) & (df["score_filtro"] >= SCORE_MIN)
            & (df["estado"].astype(str).str.upper() == "ACTIVA")
            & (~df["ticker_key"].isin(excluded_tickers))
            & (~has_current_score | current_score_has_upside)]
    if df.empty:
        return []
    df = df.sort_values(["score_filtro", "fecha_dt"], ascending=[False, False], na_position="last")
    winner = df.iloc[0].to_dict()
    if pd.notna(winner.get("score_actual_n")):
        winner["score_entrada"] = winner.get("score_actual_n")
        winner["analisis_ia_entrada"] = winner.get("analisis_ia_actual")
    return [winner]

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
        raw = re.sub(r"```(?:json)?|```", "", r.choices[0].message.content or "", flags=re.IGNORECASE).strip()
        try: return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.S)
            return json.loads(m.group(0)) if m else {}
    except Exception as e:
        log.warning("IA %s: %s", safe(a.get("ticker")), e)
        return {"empresa_contexto": f"{safe(a.get('empresa'))} pertenece al sector {safe(a.get('sector'))}.",
                "sector_contexto": "El contexto sectorial debe analizarse junto con la evolución del mercado.",
                "noticias_contexto": "No se pudo generar un resumen de noticias verificadas.",
                "comentario_contexto": "La tesis principal de esta alerta procede del modelo cuantitativo.",
                "riesgos_contexto": "Conviene vigilar la evolución del precio, volumen y niveles de gestión de riesgo.",
                "titular_contexto": f"Nueva alerta cuantitativa en {safe(a.get('ticker'))}"}


# ============================================================
# COMPONENTES HTML INTEGRADOS (Ficha Robusta y Responsive)
# ============================================================
def build_html_opportunity_card(a):
    empresa = esc(a.get("empresa"))
    ticker = esc(a.get("ticker"))
    sector = esc(a.get("sector"))
    score = num(a.get("score_entrada"), 0)
    rr = safe(num(a.get("ratio_rr")))

    try: sl = float(a.get("stop_loss"))
    except: sl = 0.0
    try: entry = float(a.get("precio_alerta"))
    except: entry = 0.0
    try: current = float(a.get("precio_actual")) if a.get("precio_actual") else entry
    except: current = entry
    try: tp = float(a.get("take_profit"))
    except: tp = 0.0

    # Rendimiento desde la entrada
    if entry > 0 and current > 0:
        perf_pct = ((current - entry) / entry) * 100
        perf_eur = current - entry
        perf_str = f"{perf_pct:+.2f}% · {perf_eur:+.2f} €"
        perf_color = "#16a34a" if perf_pct >= 0 else "#dc2626"
    else:
        perf_str = "0,00% · 0,00 €"
        perf_color = "#16a34a"

    # Proporción dinámica del ancho para reflejar la distancia real entre niveles
    risk_dist = abs(entry - sl)
    reward_dist = abs(tp - entry)
    total_dist = risk_dist + reward_dist

    if total_dist > 0 and risk_dist > 0 and reward_dist > 0:
        # Ponderación porcentual según las distancias reales
        risk_pct = round((risk_dist / total_dist) * 100, 1)
        reward_pct = round((reward_dist / total_dist) * 100, 1)
    else:
        # Proporción genérica si los niveles no son válidos (30% riesgo / 70% beneficio)
        risk_pct, reward_pct = 30.0, 70.0

    return f'''
    <!-- FICHA ESTILO DASHBOARD RESPONSIVE -->
    <table width="100%" border="0" cellspacing="0" cellpadding="0" class="mobile-card" style="background-color:#ffffff;border:1px solid #e2e8f0;border-radius:16px;padding:24px;margin-bottom:24px;box-shadow:0 2px 6px rgba(0,0,0,0.03);">
      
      <!-- Cabecera: Score + Empresa + Precio -->
      <tr>
        <td valign="top" width="20%">
          <div style="font-size:28px;font-weight:900;color:#2563eb;line-height:1;" class="mobile-score">{score}</div>
          <div style="font-size:9px;font-weight:800;color:#94a3b8;letter-spacing:0.05em;margin-top:4px;">QUANT SCORE</div>
        </td>
        <td valign="top" align="left" width="50%">
          <div style="font-size:18px;font-weight:800;color:#0f172a;line-height:1.2;" class="mobile-title">{empresa} <span style="font-size:12px;color:#94a3b8;font-weight:600;">{ticker}</span></div>
          <div style="font-size:12px;color:#64748b;margin-top:2px;">{sector}</div>
        </td>
        <td valign="top" align="right" width="30%">
          <div style="font-size:24px;font-weight:900;color:#0f172a;line-height:1;" class="mobile-price">{num(current)}</div>
          <div style="font-size:9px;font-weight:800;color:#94a3b8;letter-spacing:0.05em;margin-top:4px;">PRECIO ACTUAL</div>
        </td>
      </tr>

      <!-- Banner Risk / Reward -->
      <tr>
        <td colspan="3" style="padding-top:20px;">
          <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color:#f8fafc;border:1px solid #f1f5f9;border-radius:12px;padding:12px 16px;">
            <tr>
              <td>
                <div style="font-size:8px;font-weight:800;color:#94a3b8;letter-spacing:0.05em;">RISK / REWARD</div>
                <div style="font-size:15px;font-weight:800;color:#2563eb;margin-top:2px;">{rr}x</div>
              </td>
              <td align="right">
                <div style="font-size:8px;font-weight:800;color:#94a3b8;letter-spacing:0.05em;">Rendimiento desde entrada</div>
                <div style="font-size:15px;font-weight:800;color:{perf_color};margin-top:2px;">{perf_str}</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Gráfico de Rango Proporcional (Stop Loss -> Entrada -> Take Profit) -->
      <tr>
        <td colspan="3" style="padding-top:24px;">
          
          <!-- Etiquetas superiores con alineación acorde a la posición de los puntos -->
          <table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom:8px;">
            <tr>
              <td width="{risk_pct}%" align="left">
                <div style="font-size:9px;font-weight:800;color:#94a3b8;">STOP LOSS</div>
                <div style="font-size:12px;font-weight:800;color:#0f172a;margin-top:2px;">{num(sl)}</div>
              </td>
              <td width="1%" align="center" style="white-space:nowrap;">
                <div style="font-size:9px;font-weight:800;color:#94a3b8;">ENTRADA</div>
                <div style="font-size:12px;font-weight:800;color:#0f172a;margin-top:2px;">{num(entry)}</div>
              </td>
              <td width="{reward_pct}%" align="right">
                <div style="font-size:9px;font-weight:800;color:#94a3b8;">TAKE PROFIT</div>
                <div style="font-size:12px;font-weight:800;color:#0f172a;margin-top:2px;">{num(tp)}</div>
              </td>
            </tr>
          </table>

          <!-- Componente Visual del Rango Proporcional con Alineación Exacta al Medio -->
          <table width="100%" border="0" cellspacing="0" cellpadding="0" style="table-layout:fixed;">
            <tr height="16" style="height:16px;line-height:0px;font-size:0px;">
              <!-- Punto Stop Loss -->
              <td width="14" align="center" valign="middle" style="height:16px;vertical-align:middle;padding:0;">
                <div style="width:12px;height:12px;border:3px solid #dc2626;background:#ffffff;border-radius:50%;box-sizing:border-box;margin:0 auto;"></div>
              </td>
              
              <!-- Tramo Stop -> Entrada (Rojo, ancho proporcional al riesgo) -->
              <td width="{risk_pct}%" border="0" valign="middle" style="height:16px;vertical-align:middle;padding:0;">
                <div style="height:3px;background-color:#fca5a5;font-size:1px;line-height:1px;">&nbsp;</div>
              </td>
              
              <!-- Punto Entrada -->
              <td width="14" align="center" valign="middle" style="height:16px;vertical-align:middle;padding:0;">
                <div style="width:12px;height:12px;border:3px solid #2563eb;background:#ffffff;border-radius:50%;box-sizing:border-box;margin:0 auto;"></div>
              </td>
              
              <!-- Tramo Entrada -> Take Profit (Verde, ancho proporcional al beneficio) -->
              <td width="{reward_pct}%" border="0" valign="middle" style="height:16px;vertical-align:middle;padding:0;">
                <div style="height:3px;background-color:#86efac;font-size:1px;line-height:1px;">&nbsp;</div>
              </td>
              
              <!-- Punto Take Profit -->
              <td width="14" align="center" valign="middle" style="height:16px;vertical-align:middle;padding:0;">
                <div style="width:12px;height:12px;border:3px solid #16a34a;background:#ffffff;border-radius:50%;box-sizing:border-box;margin:0 auto;"></div>
              </td>
            </tr>
          </table>

        </td>
      </tr>

      <!-- Tesis del Analista -->
      <tr>
        <td colspan="3" style="padding-top:20px;">
          <div style="background-color:#f8fafc;border:1px solid #f1f5f9;border-radius:12px;padding:16px;">
            <div style="font-size:10px;font-weight:800;color:#2563eb;letter-spacing:0.05em;margin-bottom:6px;">✦ TESIS DEL ANALISTA</div>
            <div style="font-size:12px;color:#334155;line-height:1.6;">{esc(a.get('analisis_ia_entrada') or 'Sin tesis adicional disponible.')}</div>
          </div>
        </td>
      </tr>

    </table>
    '''


def news_html(news):
    if not news: return '<div style="color:#94a3b8;font-size:11px;">No se han encontrado noticias recientes relevantes.</div>'
    out = []
    for n in news:
        link = n.get("link", "")
        href = esc(link) if str(link).startswith(("http://", "https://")) else "#"
        out.append(f'''<div style="padding:8px 0;border-bottom:1px solid #edf1f5;">
            <a href="{href}" style="text-decoration:none;color:#0f172a;font-weight:700;font-size:12px;" target="_blank">{esc(n.get("title"))}</a>
            <div style="color:#94a3b8;font-size:10px;margin-top:2px;">{esc(n.get("source"))} · {esc(n.get("date"))}</div>
        </div>''')
    return "".join(out)


def html_email(a, ctx, news):
    ticker = safe(a.get("ticker"))
    title = ctx.get("titular_contexto", f"Nueva señal cuantitativa en {ticker}")
    card_html = build_html_opportunity_card(a)

    return f'''<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Alura Quant · {esc(ticker)}</title>
  <style type="text/css">
    @media screen and (max-width: 600px) {{
      .email-container {{ width: 100% !important; padding: 10px !important; }}
      .mobile-card {{ padding: 14px !important; }}
      .mobile-score {{ font-size: 22px !important; }}
      .mobile-title {{ font-size: 15px !important; }}
      .mobile-price {{ font-size: 18px !important; }}
      .mobile-padding {{ padding-left: 14px !important; padding-right: 14px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f5f7fb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#172033;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color:#f5f7fb;padding:20px 0;">
    <tr>
      <td align="center">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" class="email-container" style="max-width:640px;background:#ffffff;border:1px solid #e6ebf2;border-radius:16px;overflow:hidden;box-shadow:0 8px 30px rgba(15,23,42,.07);">
          
          <!-- Header -->
          <tr>
            <td class="mobile-padding" style="padding:20px 28px;border-bottom:1px solid #edf1f5;background:#ffffff;">
              <table width="100%" border="0" cellspacing="0" cellpadding="0">
                <tr>
                  <td style="font-size:16px;font-weight:800;color:#0f172a;">Alura <span style="color:#2563eb;">Quant</span></td>
                  <td align="right" style="font-size:10px;color:#94a3b8;font-weight:700;text-transform:uppercase;letter-spacing:.08em;">Nueva Alerta Cuantitativa</td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Título principal -->
          <tr>
            <td class="mobile-padding" style="padding:24px 28px 16px;">
              <div style="font-size:9px;color:#2563eb;text-transform:uppercase;letter-spacing:.1em;font-weight:800;margin-bottom:4px;">OPORTUNIDAD SELECCIONADA</div>
              <h1 style="font-size:18px;margin:0;color:#0f172a;line-height:1.3;">{esc(title)}</h1>
            </td>
          </tr>

          <!-- Ficha Integrada -->
          <tr>
            <td class="mobile-padding" style="padding:0 28px 10px;">
              {card_html}
            </td>
          </tr>

          <!-- Contexto Empresa / Sector / Riesgos -->
          <tr>
            <td class="mobile-padding" style="padding:0 28px 20px;">
              <div style="background:#f8fafc;border:1px solid #e3eaf4;border-radius:12px;padding:18px;">
                <div style="font-size:9px;color:#2563eb;text-transform:uppercase;letter-spacing:.08em;font-weight:800;margin-bottom:4px;">EMPRESA</div>
                <p style="font-size:12px;line-height:1.6;color:#475569;margin:0 0 12px;">{esc(ctx.get('empresa_contexto'))}</p>
                
                <div style="font-size:9px;color:#2563eb;text-transform:uppercase;letter-spacing:.08em;font-weight:800;margin-bottom:4px;">SECTOR</div>
                <p style="font-size:12px;line-height:1.6;color:#475569;margin:0 0 12px;">{esc(ctx.get('sector_contexto'))}</p>
                
                <div style="font-size:9px;color:#2563eb;text-transform:uppercase;letter-spacing:.08em;font-weight:800;margin-bottom:4px;">LECTURA CONTEXTUAL</div>
                <p style="font-size:12px;line-height:1.6;color:#475569;margin:0 0 12px;">{esc(ctx.get('comentario_contexto'))}</p>
                
                <div style="font-size:9px;color:#dc2626;text-transform:uppercase;letter-spacing:.08em;font-weight:800;margin-bottom:4px;">RIESGOS A VIGILAR</div>
                <p style="font-size:12px;line-height:1.6;color:#475569;margin:0;">{esc(ctx.get('riesgos_contexto'))}</p>
              </div>
            </td>
          </tr>

          <!-- Noticias / Actualidad -->
          <tr>
            <td class="mobile-padding" style="padding:0 28px 20px;">
              <div style="font-size:9px;color:#2563eb;text-transform:uppercase;letter-spacing:.1em;font-weight:800;margin-bottom:6px;">ACTUALIDAD</div>
              <h2 style="font-size:14px;margin:0 0 10px;color:#0f172a;">Noticias recientes</h2>
              {news_html(news)}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td class="mobile-padding" style="border-top:1px solid #edf1f5;background:#fafbfc;padding:20px 28px;color:#94a3b8;font-size:10px;line-height:1.6;">
              <b>Alura Quant</b> · Aviso legal y descargo de responsabilidad:<br>
              Alura Quant es una herramienta tecnológica de análisis cuantitativo y educación financiera. Los datos, scores, niveles técnicos
              y análisis generados por algoritmos o inteligencia artificial no constituyen, ni deben interpretarse como, un servicio de
              asesoramiento en inversión, recomendación de compra/venta o análisis financiero personalizado según la Ley del Mercado de Valores.
              La renta variable conlleva riesgos de pérdida de capital. Cada usuario es responsable exclusivo de sus decisiones de inversión.
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


def send(a, content, recipients):
    ticker = safe(a.get("ticker"))
    score = num(a.get("score_entrada"), 0)
    subject = f"Alura Quant | Nueva alerta: {ticker} · Score {score}/100"

    if DRY_RUN:
        fn_html = f"preview_alerta_{ticker.replace('.', '_')}.html"
        open(fn_html, "w", encoding="utf-8").write(content)
        log.info("DRY_RUN: archivo preview generado en %s", fn_html)
        return

    payload = {
        "from": FROM_EMAIL,
        "to": recipients,
        "subject": subject,
        "html": content,
    }
    
    resend.Emails.send(payload)
    log.info("Email enviado exitosamente: %s", subject)


def main():
    log.info("ALURA QUANT — ALERTAS PREMIUM | score >= %.0f | ventana=%sh", SCORE_MIN, LOOKBACK_HOURS)
    now_utc = datetime.now(timezone.utc)
    start_of_day = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    daily = (supabase.table("cola_envios_alertas").select("id")
             .gte("fecha_envio", start_of_day.isoformat())
             .lt("fecha_envio", (start_of_day + timedelta(days=1)).isoformat())
             .limit(1).execute())
    if daily.data:
        log.info("El cupo diario ya está cubierto; ya hay un envío registrado hoy (UTC).")
        return

    excluded_tickers = get_sent_tickers()
    recipients = get_subscribers()
    if not recipients:
        log.info("No hay suscriptores.")
        return
    alerts = get_new_alerts(excluded_tickers)
    if not alerts:
        log.info("No hay alertas nuevas que cumplan el filtro.")
        return
    for a in alerts:
        ticker = safe(a.get("ticker"))
        try:
            news = get_news(ticker, safe(a.get("empresa"), ""))
            ctx = ai_context(a, news)
            content = html_email(a, ctx, news)
            send(a, content, recipients)
            if not DRY_RUN:
                supabase.table("cola_envios_alertas").insert({
                    "alerta_id": int(a["id"]),
                    "ticker": ticker,
                }).execute()
                sent_at = datetime.now(timezone.utc).isoformat()
                for recipient in recipients:
                    try:
                        supabase.table("suscriptores_free").update({
                            "fecha_ultima_alerta_enviada": sent_at
                        }).eq("email", recipient).execute()
                    except Exception as update_error:
                        log.warning("No se pudo actualizar fecha de alerta para %s: %s", recipient, update_error)
                log.info("Alerta %s (%s) registrada en cola_envios_alertas.", a["id"], ticker)
        except Exception as e:
            log.exception("Error procesando %s: %s", ticker, e)

if __name__ == "__main__":
    main()
