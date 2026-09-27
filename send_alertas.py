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
        raw = re.sub(r"```(?:json)?|```", "", r.choices[0].message.content or "", flags=re.I).strip()
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
# COMPONENTES HTML INTEGRADOS (Sin adjuntos / Sin imágenes)
# ============================================================
def build_html_opportunity_card(a):
    """
    Construye la ficha de oportunidad mediante tablas HTML nativas
    e inline CSS compatible con todos los clientes de email.
    """
    empresa = esc(a.get("empresa"))
    ticker = esc(a.get("ticker"))
    sector = esc(a.get("sector"))
    score = num(a.get("score_entrada"), 0)

    try: sl = float(a.get("stop_loss"))
    except: sl = 0.0
    try: entry = float(a.get("precio_alerta"))
    except: entry = 0.0
    try: current = float(a.get("precio_actual")) if a.get("precio_actual") else entry
    except: current = entry
    try: tp = float(a.get("take_profit"))
    except: tp = 0.0

    # Cálculo dinámico de proporciones para la barra visual en HTML
    vals = [v for v in [sl, entry, current, tp] if v > 0]
    lo, hi = (min(vals), max(vals)) if len(vals) >= 2 else (0, 1)
    span = max(0.001, hi - lo)
    
    pct_sl = max(0, min(100, int(((sl - lo) / span) * 100)))
    pct_entry = max(0, min(100, int(((entry - lo) / span) * 100)))
    pct_tp = max(0, min(100, int(((tp - lo) / span) * 100)))

    # Razones / Pills
    razones = [x.strip() for x in str(a.get("razones_entrada") or "").split(";") if x.strip()]
    pills_html = "".join([
        f'<span style="display:inline-block;background-color:#f1f5f9;border:1px solid #e2e8f0;border-radius:12px;padding:4px 10px;font-size:11px;color:#475569;margin-right:6px;margin-bottom:6px;">✓ {esc(r)}</span>'
        for r in razones[:3]
    ])

    return f'''
    <!-- FICHA OPORTUNIDAD CONTENEDOR PRINCIPAL -->
    <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color:#ffffff;border:1px solid #e2e8f0;border-radius:16px;padding:20px;margin-bottom:20px;box-shadow:0 2px 4px rgba(0,0,0,0.02);">
      
      <!-- Cabecera Tarjeta: Nombre + Score -->
      <tr>
        <td>
          <table width="100%" border="0" cellspacing="0" cellpadding="0">
            <tr>
              <td valign="top">
                <div style="font-size:18px;font-weight:700;color:#0f172a;line-height:1.2;">{empresa} ({ticker})</div>
                <div style="font-size:12px;color:#64748b;margin-top:4px;">Sector: {sector}</div>
              </td>
              <td align="right" valign="top">
                <div style="background-color:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:6px 12px;text-align:center;display:inline-block;">
                  <div style="font-size:9px;font-weight:800;color:#2563eb;letter-spacing:0.05em;">SCORE</div>
                  <div style="font-size:18px;font-weight:800;color:#1e40af;">{score}/100</div>
                </div>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Separador -->
      <tr><td style="padding-top:14px;border-bottom:1px solid #f1f5f9;"></td></tr>

      <!-- Seccion Tracker Visual -->
      <tr>
        <td style="padding-top:16px;">
          <!-- Valores del Tracker -->
          <table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom:8px;">
            <tr>
              <td width="25%" align="left">
                <div style="font-size:9px;font-weight:700;color:#94a3b8;text-transform:uppercase;">STOP</div>
                <div style="font-size:12px;font-weight:700;color:#dc2626;">{eur(sl)}</div>
              </td>
              <td width="25%" align="center">
                <div style="font-size:9px;font-weight:700;color:#94a3b8;text-transform:uppercase;">ENTRADA</div>
                <div style="font-size:12px;font-weight:700;color:#2563eb;">{eur(entry)}</div>
              </td>
              <td width="25%" align="center">
                <div style="font-size:9px;font-weight:700;color:#94a3b8;text-transform:uppercase;">ACTUAL</div>
                <div style="font-size:12px;font-weight:700;color:#0f172a;">{eur(current)}</div>
              </td>
              <td width="25%" align="right">
                <div style="font-size:9px;font-weight:700;color:#94a3b8;text-transform:uppercase;">TAKE PROFIT</div>
                <div style="font-size:12px;font-weight:700;color:#16a34a;">{eur(tp)}</div>
              </td>
            </tr>
          </table>

          <!-- Barra Visual Rango (Nativa HTML/CSS) -->
          <div style="background-color:#e2e8f0;height:8px;border-radius:4px;position:relative;width:100%;margin-bottom:18px;">
            <div style="background-color:#16a34a;height:8px;border-radius:4px;width:{pct_tp}%;max-width:100%;"></div>
          </div>
        </td>
      </tr>

      <!-- Grilla de Métricas Técnico-Cuantitativas -->
      <tr>
        <td>
          <table width="100%" border="0" cellspacing="0" cellpadding="0">
            <tr>
              <!-- Fila 1 de Métricas -->
              <td width="23%" style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;">
                <div style="font-size:8px;font-weight:700;color:#94a3b8;">PRECIO</div>
                <div style="font-size:12px;font-weight:700;color:#0f172a;margin-top:2px;">{eur(a.get("precio_alerta"))}</div>
              </td>
              <td width="2%"></td>
              <td width="23%" style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;">
                <div style="font-size:8px;font-weight:700;color:#94a3b8;">RVOL</div>
                <div style="font-size:12px;font-weight:700;color:#0f172a;margin-top:2px;">{num(a.get("rvol_entrada"))}x</div>
              </td>
              <td width="2%"></td>
              <td width="23%" style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;">
                <div style="font-size:8px;font-weight:700;color:#94a3b8;">RSI</div>
                <div style="font-size:12px;font-weight:700;color:#0f172a;margin-top:2px;">{safe(num(a.get("rsi_entrada")))}</div>
              </td>
              <td width="2%"></td>
              <td width="23%" style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;">
                <div style="font-size:8px;font-weight:700;color:#94a3b8;">ROC20</div>
                <div style="font-size:12px;font-weight:700;color:#0f172a;margin-top:2px;">{safe(pct(a.get("roc20_entrada")))}</div>
              </td>
            </tr>
            <tr><td height="8"></td></tr>
            <tr>
              <!-- Fila 2 de Métricas -->
              <td width="23%" style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;">
                <div style="font-size:8px;font-weight:700;color:#94a3b8;">STOP LOSS</div>
                <div style="font-size:12px;font-weight:700;color:#dc2626;margin-top:2px;">{eur(sl)}</div>
              </td>
              <td width="2%"></td>
              <td width="23%" style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;">
                <div style="font-size:8px;font-weight:700;color:#94a3b8;">TAKE PROFIT</div>
                <div style="font-size:12px;font-weight:700;color:#16a34a;margin-top:2px;">{eur(tp)}</div>
              </td>
              <td width="2%"></td>
              <td width="23%" style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;">
                <div style="font-size:8px;font-weight:700;color:#94a3b8;">RATIO R:R</div>
                <div style="font-size:12px;font-weight:700;color:#2563eb;margin-top:2px;">{safe(num(a.get("ratio_rr")))}</div>
              </td>
              <td width="2%"></td>
              <td width="23%" style="background-color:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;">
                <div style="font-size:8px;font-weight:700;color:#94a3b8;">ACTUAL</div>
                <div style="font-size:12px;font-weight:700;color:#0f172a;margin-top:2px;">{eur(current)}</div>
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- Pills de Razones -->
      {f'<tr><td style="padding-top:14px;">{pills_html}</td></tr>' if pills_html else ''}

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
</head>
<body style="margin:0;padding:0;background-color:#f5f7fb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#172033;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color:#f5f7fb;padding:20px 10px;">
    <tr>
      <td align="center">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width:640px;background:#ffffff;border:1px solid #e6ebf2;border-radius:16px;overflow:hidden;box-shadow:0 8px 30px rgba(15,23,42,.07);">
          
          <!-- Header -->
          <tr>
            <td style="padding:20px 28px;border-bottom:1px solid #edf1f5;background:#ffffff;">
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
            <td style="padding:24px 28px 16px;">
              <div style="font-size:9px;color:#2563eb;text-transform:uppercase;letter-spacing:.1em;font-weight:800;margin-bottom:4px;">OPORTUNIDAD SELECCIONADA</div>
              <h1 style="font-size:18px;margin:0;color:#0f172a;line-height:1.3;">{esc(title)}</h1>
            </td>
          </tr>

          <!-- Ficha Integrada Nativa (HTML/CSS) -->
          <tr>
            <td style="padding:0 28px 10px;">
              {card_html}
            </td>
          </tr>

          <!-- Contexto Empresa / Sector -->
          <tr>
            <td style="padding:0 28px 20px;">
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

          <!-- Noticias -->
          <tr>
            <td style="padding:0 28px 20px;">
              <div style="font-size:9px;color:#2563eb;text-transform:uppercase;letter-spacing:.1em;font-weight:800;margin-bottom:6px;">ACTUALIDAD</div>
              <h2 style="font-size:14px;margin:0 0 10px;color:#0f172a;">Noticias recientes</h2>
              {news_html(news)}
            </td>
          </tr>

          <!-- Tesis de Entrada -->
          <tr>
            <td style="padding:0 28px 24px;">
              <div style="background:#f4f7ff;border:1px solid #dbe7ff;border-radius:12px;padding:16px;">
                <div style="font-size:9px;color:#2563eb;text-transform:uppercase;letter-spacing:.08em;font-weight:800;margin-bottom:4px;">TESIS SISTEMÁTICA ENTRADA</div>
                <p style="font-size:12px;line-height:1.6;color:#334155;margin:0;">{esc(a.get('analisis_ia_entrada') or 'Sin análisis adicional disponible.')}</p>
              </div>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="border-top:1px solid #edf1f5;background:#fafbfc;padding:20px 28px;color:#94a3b8;font-size:10px;line-height:1.6;">
              <b>Alura Quant</b> · Alertas cuantitativas generadas de forma automática.<br>
              Esta comunicación es de carácter exclusivamente informativo y no representa asesoramiento financiero personalizado.
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
    recipients = get_subscribers()
    if not recipients:
        log.info("No hay suscriptores.")
        return
    alerts = get_new_alerts()
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
        except Exception as e:
            log.exception("Error procesando %s: %s", ticker, e)

if __name__ == "__main__":
    main()
