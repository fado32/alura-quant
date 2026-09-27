import os, re, json, html, time, logging, io, base64
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import pandas as pd
from supabase import create_client, Client
from openai import OpenAI
import resend

from PIL import Image, ImageDraw, ImageFont

# ============================================================
# ALURA QUANT — ALERTAS PREMIUM
# Detecta nuevas alertas ACTIVA con Score >= 80 y envía una
# ficha cuantitativa visual + contexto de empresa/sector/noticias.
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
# RENDERIZADO DE LA FICHA EN IMAGEN PNG (Pillow)
# ============================================================
def get_font(size=14, bold=False):
    try:
        font_name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        return ImageFont.truetype(font_name, size)
    except Exception:
        return ImageFont.load_default()

def generate_opportunity_card_image(a):
    """
    Genera en imagen exactamente la Ficha de Oportunidades de Alura Quant
    con el diseño pixel-perfect de la plataforma.
    """
    w, h = 680, 480
    bg_color = (255, 255, 255)
    img = Image.new("RGB", (w, h), bg_color)
    draw = ImageDraw.Draw(img)

    # Colores
    c_border = (231, 235, 242)
    c_text_main = (17, 24, 39)
    c_text_sub = (100, 116, 139)
    c_text_muted = (148, 163, 184)
    c_blue = (37, 99, 235)
    c_red = (220, 38, 38)
    c_green = (22, 163, 74)
    c_card_bg = (248, 250, 252)

    # Borde exterior de la tarjeta
    draw.rounded_rectangle([1, 1, w - 2, h - 2], radius=16, outline=c_border, width=2)

    # --- Header Ficha ---
    empresa = safe(a.get("empresa"), "Empresa")
    ticker = safe(a.get("ticker"), "TICKER")
    sector = safe(a.get("sector"), "Sector")
    score = safe(num(a.get("score_entrada"), 0))

    # Título empresa y meta
    f_title = get_font(18, bold=True)
    f_sub = get_font(12, bold=False)
    draw.text((24, 20), f"{empresa} ({ticker})", fill=c_text_main, font=f_title)
    draw.text((24, 46), f"Sector: {sector}", fill=c_text_sub, font=f_sub)

    # Score Box Right
    f_score_lbl = get_font(9, bold=True)
    f_score_val = get_font(20, bold=True)
    draw.text((w - 110, 20), "SCORE", fill=c_text_muted, font=f_score_lbl)
    draw.text((w - 110, 34), f"{score}/100", fill=c_blue, font=f_score_val)

    # Linea divisoria
    draw.line([(24, 76), (w - 24, 76)], fill=c_border, width=1)

    # --- Position Tracker ---
    try: sl = float(a.get("stop_loss"))
    except: sl = 0.0
    try: entry = float(a.get("precio_alerta"))
    except: entry = 0.0
    try: current = float(a.get("precio_actual")) if a.get("precio_actual") else entry
    except: current = entry
    try: tp = float(a.get("take_profit"))
    except: tp = 0.0

    vals = [v for v in [sl, entry, current, tp] if v > 0]
    lo, hi = (min(vals), max(vals)) if len(vals) >= 2 else (0, 1)
    span = max(0.001, hi - lo)
    lo_margin = lo - span * 0.08
    hi_margin = hi + span * 0.08
    full_span = hi_margin - lo_margin

    def get_x(v):
        pct_v = (v - lo_margin) / full_span
        return int(24 + max(0, min(1, pct_v)) * (w - 48))

    x_sl = get_x(sl)
    x_entry = get_x(entry)
    x_curr = get_x(current)
    x_tp = get_x(tp)

    # Etiquetas de la barra
    f_lbl = get_font(9, bold=True)
    f_val = get_font(11, bold=True)

    draw.text((24, 90), "STOP", fill=c_text_muted, font=f_lbl)
    draw.text((24, 104), eur(sl), fill=c_red, font=f_val)

    draw.text((170, 90), "ENTRADA", fill=c_text_muted, font=f_lbl)
    draw.text((170, 104), eur(entry), fill=c_blue, font=f_val)

    draw.text((320, 90), "ACTUAL", fill=c_text_muted, font=f_lbl)
    draw.text((320, 104), eur(current), fill=c_text_main, font=f_val)

    draw.text((w - 120, 90), "TAKE PROFIT", fill=c_text_muted, font=f_lbl)
    draw.text((w - 120, 104), eur(tp), fill=c_green, font=f_val)

    # Pista de la barra
    track_y = 138
    draw.rounded_rectangle([24, track_y, w - 24, track_y + 6], radius=3, fill=(238, 242, 247))
    draw.rounded_rectangle([x_sl, track_y, x_entry, track_y + 6], radius=3, fill=(254, 226, 226))
    draw.rounded_rectangle([x_curr, track_y, x_tp, track_y + 6], radius=3, fill=(220, 252, 231))

    # Puntos de nivel
    for x_p, col in [(x_sl, c_red), (x_entry, c_blue), (x_tp, c_green)]:
        draw.ellipse([x_p - 4, track_y + 3 - 4, x_p + 4, track_y + 3 + 4], fill=(255, 255, 255), outline=col, width=2)
    # Marcador Actual
    draw.ellipse([x_curr - 6, track_y + 3 - 6, x_curr + 6, track_y + 3 + 6], fill=c_blue, outline=(255, 255, 255), width=2)

    # --- Bloques de Métricas Técnico-Cuantitativas ---
    box_w = (w - 48 - 24) // 4
    box_h = 58
    y_m1 = 165

    metrics1 = [
        ("PRECIO", eur(a.get("precio_alerta")), c_text_main),
        ("RVOL", f"{num(a.get('rvol_entrada'))}x", c_text_main),
        ("RSI", safe(num(a.get('rsi_entrada'))), c_text_main),
        ("ROC20", safe(pct(a.get('roc20_entrada'))), c_text_main)
    ]

    for i, (m_lbl, m_val, m_col) in enumerate(metrics1):
        bx = 24 + i * (box_w + 8)
        draw.rounded_rectangle([bx, y_m1, bx + box_w, y_m1 + box_h], radius=8, fill=c_card_bg, outline=c_border, width=1)
        draw.text((bx + 10, y_m1 + 8), m_lbl, fill=c_text_muted, font=get_font(8, bold=True))
        draw.text((bx + 10, y_m1 + 26), m_val, fill=m_col, font=get_font(12, bold=True))

    y_m2 = y_m1 + box_h + 10
    metrics2 = [
        ("STOP LOSS", eur(a.get("stop_loss")), c_red),
        ("TAKE PROFIT", eur(a.get("take_profit")), c_green),
        ("RATIO R:R", safe(num(a.get("ratio_rr"))), c_blue),
        ("ACTUAL", eur(current), c_text_main)
    ]

    for i, (m_lbl, m_val, m_col) in enumerate(metrics2):
        bx = 24 + i * (box_w + 8)
        draw.rounded_rectangle([bx, y_m2, bx + box_w, y_m2 + box_h], radius=8, fill=c_card_bg, outline=c_border, width=1)
        draw.text((bx + 10, y_m2 + 8), m_lbl, fill=c_text_muted, font=get_font(8, bold=True))
        draw.text((bx + 10, y_m2 + 26), m_val, fill=m_col, font=get_font(12, bold=True))

    # --- Razones / Pills ---
    y_pills = y_m2 + box_h + 14
    razones = [x.strip() for x in str(a.get("razones_entrada") or "").split(";") if x.strip()]
    curr_x = 24
    f_pill = get_font(9, bold=False)

    for r in razones[:3]:
        p_text = f"✓ {r}"
        bbox = draw.textbbox((0, 0), p_text, font=f_pill)
        pw = bbox[2] - bbox[0] + 16
        if curr_x + pw < w - 24:
            draw.rounded_rectangle([curr_x, y_pills, curr_x + pw, y_pills + 24], radius=12, fill=c_card_bg, outline=c_border)
            draw.text((curr_x + 8, y_pills + 5), p_text, fill=c_text_sub, font=f_pill)
            curr_x += pw + 8

    # Exportar a Bytes
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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


def html_email(a, ctx, news, cid_card_img="cid:ficha_oportunidad"):
    ticker = safe(a.get("ticker"))
    company = safe(a.get("empresa"))
    title = ctx.get("titular_contexto", f"Nueva señal cuantitativa en {ticker}")

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
        <table width="100%" max-width="660" border="0" cellspacing="0" cellpadding="0" style="max-width:660px;background:#ffffff;border:1px solid #e6ebf2;border-radius:16px;overflow:hidden;box-shadow:0 8px 30px rgba(15,23,42,.07);">
          
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
            <td style="padding:24px 28px 12px;">
              <div style="font-size:9px;color:#2563eb;text-transform:uppercase;letter-spacing:.1em;font-weight:800;margin-bottom:4px;">OPORTUNIDAD SELECCIONADA</div>
              <h1 style="font-size:18px;margin:0;color:#0f172a;line-height:1.3;">{esc(title)}</h1>
            </td>
          </tr>

          <!-- Imagen Ficha Oportunidad (Reconstruida dinámicamente) -->
          <tr>
            <td style="padding:10px 28px 20px;" align="center">
              <img src="{cid_card_img}" alt="Ficha de Oportunidad {esc(ticker)}" style="width:100%;max-width:600px;height:auto;display:block;border-radius:12px;border:1px solid #e2e8f0;" />
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


def send(a, content, card_img_bytes, recipients):
    ticker = safe(a.get("ticker"))
    score = num(a.get("score_entrada"), 0)
    subject = f"Alura Quant | Nueva alerta: {ticker} · Score {score}/100"

    if DRY_RUN:
        fn_html = f"preview_alerta_{ticker.replace('.', '_')}.html"
        fn_img = f"ficha_{ticker.replace('.', '_')}.png"
        open(fn_html, "w", encoding="utf-8").write(content)
        open(fn_img, "wb").write(card_img_bytes)
        log.info("DRY_RUN: generados %s y %s", fn_html, fn_img)
        return

    # Envío mediante Resend adjuntando la imagen embebida/adjunta
    b64_img = base64.b64encode(card_img_bytes).decode("utf-8")
    
    payload = {
        "from": FROM_EMAIL,
        "to": recipients,
        "subject": subject,
        "html": content.replace("cid:ficha_oportunidad", f"data:image/png;base64,{b64_img}"),
        "attachments": [
            {
                "filename": f"ficha_{ticker}.png",
                "content": b64_img,
            }
        ]
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
            card_img_bytes = generate_opportunity_card_image(a)
            content = html_email(a, ctx, news)
            send(a, content, card_img_bytes, recipients)
        except Exception as e:
            log.exception("Error procesando %s: %s", ticker, e)

if __name__ == "__main__":
    main()
