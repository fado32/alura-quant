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
# Detecta nuevas alertas ACTIVA con Score >= 80 y envía una
# ficha cuantitativa + contexto de empresa/sector/noticias.
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
LOOKBACK_HOURS = int(os.getenv("ALURA_ALERT_LOOKBACK_HOURS", "224"))
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
            "riesgo_euros,acciones,nominal,estado_estrategia,fecha_mercado_actual,estado")
    r = (supabase.table("historial_alertas").select(cols).eq("estado", "ACTIVA")
         .gte("fecha", since.isoformat()).gte("score_entrada", SCORE_MIN)
         .order("fecha", desc=True).execute())
    df = pd.DataFrame(r.data or [])
    if df.empty: return []
    df["fecha_dt"] = pd.to_datetime(df["fecha"], errors="coerce", utc=True)
    df["score_n"] = pd.to_numeric(df["score_entrada"], errors="coerce")
    df = df[(df["fecha_dt"] >= pd.Timestamp(since)) & (df["score_n"] >= SCORE_MIN)
            & (df["estado"].astype(str).str.upper() == "ACTIVA")]
    # Una alerta nueva por ticker dentro de la ventana.
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


def reasons(v):
    items = [x.strip() for x in str(v or "").split(";") if x.strip()]
    return "".join(f'<span class="pill">✓ {esc(x)}</span>' for x in items) or '<span class="muted">Sin detalle.</span>'


def news_html(news):
    if not news: return '<div class="muted">No se han encontrado noticias recientes relevantes.</div>'
    out=[]
    for n in news:
        link=n.get("link", "")
        href=esc(link) if str(link).startswith(("http://","https://")) else "#"
        out.append(f'<a class="news" href="{href}"><b>{esc(n.get("title"))}</b><small>{esc(n.get("source"))} · {esc(n.get("date"))}</small></a>')
    return "".join(out)


def html_email(a, ctx, news):
    score=float(a.get("score_entrada") or 0)
    ticker=safe(a.get("ticker")); company=safe(a.get("empresa")); sector=safe(a.get("sector")); icon=safe(a.get("icono"),"📈")
    price=eur(a.get("precio_alerta")); stop=eur(a.get("stop_loss")); tp=eur(a.get("take_profit")); rr=num(a.get("ratio_rr"));
    dist_sl = pct((float(a["precio_alerta"])-float(a["stop_loss"]))/float(a["precio_alerta"])*100) if a.get("precio_alerta") and a.get("stop_loss") else "—"
    dist_tp = pct((float(a["take_profit"])-float(a["precio_alerta"]))/float(a["precio_alerta"])*100) if a.get("precio_alerta") and a.get("take_profit") else "—"
    title=ctx.get("titular_contexto", f"Nueva alerta cuantitativa en {ticker}")
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{{margin:0;background:#eef2f7;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}}.wrap{{padding:28px 12px}}.mail{{max-width:720px;margin:auto;background:#fff;border-radius:20px;overflow:hidden;box-shadow:0 12px 40px rgba(15,23,42,.1)}}.hero{{padding:34px;background:linear-gradient(135deg,#0f172a,#172554,#1e3a8a);color:#fff}}.brand{{font-size:11px;letter-spacing:2px;text-transform:uppercase;opacity:.7;font-weight:800}}.eyebrow{{color:#93c5fd;font-size:11px;text-transform:uppercase;letter-spacing:1.4px;font-weight:800;margin-top:22px}}h1{{font-size:30px;margin:7px 0}}.company{{color:#cbd5e1}}.score{{margin-top:22px;padding:15px;background:#ffffff12;border:1px solid #ffffff1c;border-radius:14px}}.scoreline{{display:flex;justify-content:space-between;font-weight:800}}.track{{height:8px;background:#ffffff22;border-radius:99px;margin-top:9px}}.fill{{height:100%;width:{min(100,max(0,score)):.0f}%;background:#60a5fa;border-radius:99px}}.section{{padding:26px 34px 0}}.kicker{{font-size:10px;text-transform:uppercase;letter-spacing:1.2px;color:#64748b;font-weight:800}}h2{{font-size:18px;margin:5px 0 13px}}p{{font-size:13px;line-height:1.65;color:#475569}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-top:15px}}.card{{padding:13px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px}}.label{{font-size:9px;text-transform:uppercase;letter-spacing:.6px;color:#64748b;font-weight:800}}.value{{font-size:17px;font-weight:800;margin-top:5px}}.panel{{margin-top:14px;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden}}.ph{{padding:12px 15px;background:#f8fafc;border-bottom:1px solid #e2e8f0;font-size:10px;text-transform:uppercase;letter-spacing:1px;font-weight:800}}.pb{{padding:15px}}.row{{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid #f1f5f9;font-size:13px}}.row:last-child{{border:0}}.muted{{color:#64748b;font-size:12px;line-height:1.6}}.pills{{display:flex;flex-wrap:wrap;gap:6px}}.pill{{padding:7px 9px;border-radius:999px;background:#f1f5f9;border:1px solid #e2e8f0;font-size:10px;font-weight:700}}.risk{{color:#dc2626}}.target{{color:#059669}}.dark{{background:#0f172a;color:#fff;border-radius:15px;padding:18px}}.dark .label{{color:#94a3b8}}.dark .value{{color:#f8fafc}}.dgrid{{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}}.ditem{{padding:11px;background:#ffffff0d;border:1px solid #ffffff12;border-radius:10px}}.ai{{background:linear-gradient(135deg,#f8fafc,#eff6ff);border:1px solid #dbeafe;border-radius:14px;padding:17px}}.ailabel{{font-size:10px;color:#2563eb;text-transform:uppercase;letter-spacing:1px;font-weight:800;margin-top:10px}}.ailabel:first-child{{margin-top:0}}.news{{display:block;text-decoration:none;color:#172033;padding:12px 0;border-bottom:1px solid #e2e8f0}}.news b{{font-size:12px;line-height:1.45}}.news small{{display:block;color:#94a3b8;font-size:9px;margin-top:4px}}.footer{{margin-top:28px;padding:22px 34px;background:#f8fafc;border-top:1px solid #e2e8f0;color:#94a3b8;font-size:9px;line-height:1.6}}@media(max-width:600px){{.section,.hero,.footer{{padding-left:20px;padding-right:20px}}.grid{{grid-template-columns:repeat(2,1fr)}}.dgrid{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:25px}}}}
</style></head><body><div class="wrap"><div class="mail">
<div class="hero"><div class="brand">Alura Quant · Quantitative Intelligence</div><div class="eyebrow">Nueva alerta cuantitativa</div><h1>{esc(icon)} {esc(ticker)}</h1><div class="company">{esc(company)} · {esc(sector)}</div><div class="score"><div class="scoreline"><span>ALURA QUANT SCORE</span><span>{score:.0f}/100</span></div><div class="track"><div class="fill"></div></div></div></div>
<div class="section"><div class="kicker">La señal</div><h2>{esc(title)}</h2><p>Nueva señal cuantitativa registrada con Score <b>{score:.0f}/100</b>. La ficha técnica procede de los datos de entrada almacenados por el motor de Alura Quant.</p><div class="grid"><div class="card"><div class="label">Precio</div><div class="value">{esc(price)}</div></div><div class="card"><div class="label">RVOL</div><div class="value">{esc(num(a.get('rvol_entrada')))}x</div></div><div class="card"><div class="label">RSI</div><div class="value">{esc(num(a.get('rsi_entrada')))}</div></div><div class="card"><div class="label">ROC20</div><div class="value">{esc(pct(a.get('roc20_entrada')))}</div></div></div></div>
<div class="section"><div class="panel"><div class="ph">Ficha cuantitativa · Entrada</div><div class="pb"><div class="pills">{reasons(a.get('razones_entrada'))}</div><div class="row"><span>ATR</span><b>{esc(eur(a.get('atr_entrada')))}</b></div><div class="row"><span>EMA50</span><b>{esc(eur(a.get('ema50_entrada')))}</b></div><div class="row"><span>EMA200</span><b>{esc(eur(a.get('ema200_entrada')))}</b></div><div class="row"><span>Soporte</span><b>{esc(eur(a.get('soporte_entrada')))}</b></div><div class="row"><span>Resistencia</span><b>{esc(eur(a.get('resistencia_entrada')))}</b></div></div></div></div>
<div class="section"><div class="dark"><div class="label">Gestión de la operación</div><div class="dgrid" style="margin-top:12px"><div class="ditem"><div class="label">Entrada</div><div class="value">{esc(price)}</div></div><div class="ditem"><div class="label">Stop Loss</div><div class="value risk">{esc(stop)}</div></div><div class="ditem"><div class="label">Take Profit</div><div class="value target">{esc(tp)}</div></div><div class="ditem"><div class="label">R:R</div><div class="value">{esc(rr)}</div></div><div class="ditem"><div class="label">Distancia SL</div><div class="value">{esc(dist_sl)}</div></div><div class="ditem"><div class="label">Distancia TP</div><div class="value">{esc(dist_tp)}</div></div><div class="ditem"><div class="label">Acciones modelo</div><div class="value">{esc(num(a.get('acciones'),0))}</div></div><div class="ditem"><div class="label">Nominal</div><div class="value">{esc(eur(a.get('nominal')))}</div></div><div class="ditem"><div class="label">Riesgo</div><div class="value">{esc(eur(a.get('riesgo_euros')))}</div></div></div></div></div>
<div class="section"><div class="kicker">Contexto empresarial</div><h2>Más allá del gráfico</h2><div class="ai"><div class="ailabel">Empresa</div><p>{esc(ctx.get('empresa_contexto'))}</p><div class="ailabel">Sector</div><p>{esc(ctx.get('sector_contexto'))}</p><div class="ailabel">Lectura contextual</div><p>{esc(ctx.get('comentario_contexto'))}</p><div class="ailabel">Riesgos a vigilar</div><p>{esc(ctx.get('riesgos_contexto'))}</p></div></div>
<div class="section"><div class="kicker">Actualidad</div><h2>Noticias recientes</h2><div class="panel"><div class="pb">{news_html(news)}</div></div></div>
<div class="section"><div class="kicker">Tesis del modelo</div><h2>Análisis cuantitativo de entrada</h2><p>{esc(a.get('analisis_ia_entrada') or 'Sin análisis IA de entrada disponible.')}</p></div>
<div class="section"><div class="panel"><div class="ph">Metadatos de la señal</div><div class="pb"><div class="row"><span>Fecha alerta</span><b>{esc(a.get('fecha'))}</b></div><div class="row"><span>Fecha mercado</span><b>{esc(a.get('fecha_mercado_actual'))}</b></div><div class="row"><span>Modo</span><b>{esc(a.get('modo'))}</b></div><div class="row"><span>Estado estrategia</span><b>{esc(a.get('estado_estrategia'))}</b></div></div></div></div>
<div class="footer"><b>Alura Quant</b> · Sistema cuantitativo de generación y seguimiento de señales.<br><br>Esta comunicación presenta datos generados por un modelo cuantitativo y herramientas de inteligencia artificial. No constituye asesoramiento financiero personalizado. Los niveles mostrados corresponden a la señal registrada en el momento de generación y pueden quedar desactualizados.</div>
</div></div></body></html>'''


def send(a, content, recipients):
    ticker=safe(a.get("ticker")); score=num(a.get("score_entrada"),0)
    subject=f"Alura Quant | Nueva alerta: {ticker} · Score {score}/100"
    if DRY_RUN:
        fn=f"preview_alerta_{ticker.replace('.', '_')}.html"
        open(fn,"w",encoding="utf-8").write(content)
        log.info("DRY_RUN: generado %s", fn)
        return
    resend.Emails.send({"from":FROM_EMAIL,"to":recipients,"subject":subject,"html":content})
    log.info("Email enviado: %s", subject)


def main():
    log.info("ALURA QUANT — ALERTAS PREMIUM | score >= %.0f | ventana=%sh", SCORE_MIN, LOOKBACK_HOURS)
    recipients=get_subscribers()
    if not recipients:
        log.info("No hay suscriptores.")
        return
    alerts=get_new_alerts()
    if not alerts:
        log.info("No hay alertas nuevas que cumplan el filtro.")
        return
    for a in alerts:
        ticker=safe(a.get("ticker"))
        try:
            news=get_news(ticker, safe(a.get("empresa"),""))
            ctx=ai_context(a, news)
            content=html_email(a,ctx,news)
            send(a,content,recipients)
        except Exception as e:
            log.exception("Error procesando %s: %s",ticker,e)

if __name__ == "__main__":
    main()
