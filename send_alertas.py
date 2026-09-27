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


def position_pct(sl, entry, current, tp):
    vals=[v for v in (sl,entry,current,tp) if v is not None]
    if len(vals)<2: return None
    lo,hi=min(vals),max(vals)
    if hi<=lo: return None
    margin=(hi-lo)*0.08; lo-=margin; hi+=margin; span=hi-lo
    def pos(v):
        return None if v is None else max(3,min(97,(v-lo)/span*100))
    return {"sl":pos(sl),"entry":pos(entry),"current":pos(current),"tp":pos(tp)}


def opportunity_chart(a):
    def f(k):
        try: return float(a[k]) if a.get(k) is not None else None
        except: return None
    sl,entry,current,tp=f("stop_loss"),f("precio_alerta"),f("precio_actual"),f("take_profit")
    if current is None: current=entry
    pos=position_pct(sl,entry,current,tp)
    if not pos: return ""
    risk=max(0,(pos["entry"] or 25)-(pos["sl"] or 3))
    reward=max(0,(pos["tp"] or 97)-max(pos["entry"] or 25,pos["current"] or 25))
    return f'''<div class="tracker">
      <div class="tracker-labels">
        <div><span>STOP</span><b>{esc(eur(sl))}</b></div>
        <div><span>ENTRADA</span><b>{esc(eur(entry))}</b></div>
        <div class="cur"><span>ACTUAL</span><b>{esc(eur(current))}</b></div>
        <div><span>TAKE PROFIT</span><b>{esc(eur(tp))}</b></div>
      </div>
      <div class="trackline">
        <i class="riskbar" style="left:{pos['sl']:.2f}%;width:{risk:.2f}%"></i>
        <i class="rewardbar" style="left:{pos['current']:.2f}%;width:{reward:.2f}%"></i>
        <i class="mark sl" style="left:{pos['sl']:.2f}%"></i>
        <i class="mark entry" style="left:{pos['entry']:.2f}%"></i>
        <i class="mark current" style="left:{pos['current']:.2f}%"></i>
        <i class="mark tp" style="left:{pos['tp']:.2f}%"></i>
      </div>
    </div>'''


def html_email(a, ctx, news):
    score=float(a.get("score_entrada") or 0)
    ticker=safe(a.get("ticker")); company=safe(a.get("empresa")); sector=safe(a.get("sector")); icon=safe(a.get("icono"),"📈")
    price=eur(a.get("precio_alerta")); current=eur(a.get("precio_actual")); stop=eur(a.get("stop_loss")); tp=eur(a.get("take_profit")); rr=num(a.get("ratio_rr"))
    dist_sl=pct((float(a["precio_alerta"])-float(a["stop_loss"]))/float(a["precio_alerta"])*100) if a.get("precio_alerta") and a.get("stop_loss") else "—"
    dist_tp=pct((float(a["take_profit"])-float(a["precio_alerta"]))/float(a["precio_alerta"])*100) if a.get("precio_alerta") and a.get("take_profit") else "—"
    title=ctx.get("titular_contexto",f"Nueva señal cuantitativa en {ticker}")
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Alura Quant · {esc(ticker)}</title><style>
body{{margin:0;background:#f5f7fb;color:#172033;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}}.wrap{{padding:22px 12px}}.mail{{max-width:700px;margin:auto;background:#fff;border:1px solid #e6ebf2;border-radius:18px;overflow:hidden;box-shadow:0 8px 30px rgba(15,23,42,.07)}}
.top{{padding:19px 28px;border-bottom:1px solid #edf1f5;display:flex;justify-content:space-between;align-items:center}}.brand{{font-size:14px;font-weight:800;color:#0f172a}}.brand em{{color:#2563eb;font-style:normal}}.top small{{font-size:9px;color:#94a3b8;font-weight:700}}
.asset{{padding:24px 28px 16px;display:flex;justify-content:space-between;align-items:center;gap:15px}}.identity{{display:flex;align-items:center;gap:11px}}.icon{{width:42px;height:42px;border-radius:12px;background:#f1f5f9;display:flex;align-items:center;justify-content:center;font-size:18px}}.company{{font-size:18px;font-weight:800;color:#0f172a}}.meta{{font-size:10px;color:#64748b;margin-top:4px}}.scorebox{{text-align:right}}.scorelabel{{font-size:8px;color:#94a3b8;letter-spacing:.08em;font-weight:800}}.score{{font-size:22px;color:#2563eb;font-weight:850;margin-top:2px}}.scoretrack{{width:90px;height:4px;background:#e8eef7;border-radius:99px;margin-top:5px;overflow:hidden}}.scorefill{{height:100%;width:{min(100,max(0,score)):.0f}%;background:#2563eb}}
.section{{padding:0 28px 22px}}.kicker{{font-size:9px;color:#2563eb;text-transform:uppercase;letter-spacing:.1em;font-weight:850;margin-bottom:5px}}h2{{font-size:15px;margin:0 0 10px;color:#0f172a}}.card{{border:1px solid #e4e9f0;border-radius:15px;padding:16px}}.tracker-labels{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:11px}}.tracker-labels div:nth-child(2),.tracker-labels div:nth-child(3){{text-align:center}}.tracker-labels div:last-child{{text-align:right}}.tracker-labels span{{display:block;font-size:7px;color:#94a3b8;letter-spacing:.07em;font-weight:850}}.tracker-labels b{{display:block;font-size:10px;color:#334155;margin-top:3px;white-space:nowrap}}.tracker-labels .cur b{{color:#2563eb}}.trackline{{position:relative;height:7px;background:#eef2f7;border-radius:99px;margin:0 7px}}.riskbar,.rewardbar{{position:absolute;top:1px;height:5px;border-radius:99px}}.riskbar{{background:#fee2e2}}.rewardbar{{background:#dcfce7}}.mark{{position:absolute;top:50%;transform:translate(-50%,-50%);width:8px;height:8px;background:#fff;border:2px solid;border-radius:50%;box-sizing:border-box}}.mark.sl{{border-color:#dc2626}}.mark.entry{{border-color:#2563eb}}.mark.tp{{border-color:#16a34a}}.mark.current{{width:12px;height:12px;background:#2563eb;border:3px solid #fff;box-shadow:0 0 0 2px #2563eb}}.metrics,.levels{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:11px}}.metric,.level{{background:#f8fafc;border:1px solid #e7ebf1;border-radius:11px;padding:10px}}.label{{font-size:8px;color:#94a3b8;text-transform:uppercase;letter-spacing:.06em;font-weight:850}}.value{{font-size:13px;color:#0f172a;font-weight:850;margin-top:4px}}.stop{{color:#dc2626}}.target{{color:#16a34a}}.pills{{display:flex;flex-wrap:wrap;gap:6px;margin-top:11px}}.pill{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:999px;padding:5px 8px;font-size:9px;color:#475569;font-weight:700}}.note{{font-size:9px;color:#94a3b8;line-height:1.5;margin-top:10px}}
.context,.analysis{{background:linear-gradient(135deg,#f8fafc,#f7faff);border:1px solid #e3eaf4;border-radius:14px;padding:15px}}.ctxlabel,.ailabel{{font-size:8px;color:#2563eb;text-transform:uppercase;letter-spacing:.08em;font-weight:850;margin-bottom:5px}}p{{font-size:12px;line-height:1.65;color:#475569;margin:0 0 11px}}p:last-child{{margin-bottom:0}}.news{{border:1px solid #e4e9f0;border-radius:14px;padding:3px 15px}}.news a{{display:block;text-decoration:none;color:#172033;padding:12px 0;border-bottom:1px solid #edf1f5}}.news a:last-child{{border:0}}.news b{{font-size:11px;line-height:1.45}}.news small{{display:block;color:#94a3b8;font-size:9px;margin-top:4px}}.footer{{border-top:1px solid #edf1f5;background:#fafbfc;padding:18px 28px;color:#94a3b8;font-size:9px;line-height:1.6}}@media(max-width:600px){{.top,.asset,.section,.footer{{padding-left:18px;padding-right:18px}}.metrics,.levels{{grid-template-columns:repeat(2,1fr)}}.company{{font-size:16px}}}}
</style></head><body><div class="wrap"><div class="mail">
<div class="top"><div class="brand">Alura <em>Quant</em></div><small>Nueva señal cuantitativa</small></div>
<div class="asset"><div class="identity"><div class="icon">{esc(icon)}</div><div><div class="company">{esc(company)}</div><div class="meta">{esc(ticker)} · {esc(sector)}</div></div></div><div class="scorebox"><div class="scorelabel">SCORE</div><div class="score">{score:.0f}/100</div><div class="scoretrack"><div class="scorefill"></div></div></div></div>
<div class="section"><div class="kicker">Oportunidad</div><h2>{esc(title)}</h2><div class="card">{opportunity_chart(a)}<div class="metrics"><div class="metric"><div class="label">Precio</div><div class="value">{esc(price)}</div></div><div class="metric"><div class="label">RVOL</div><div class="value">{esc(num(a.get('rvol_entrada')))}x</div></div><div class="metric"><div class="label">RSI</div><div class="value">{esc(num(a.get('rsi_entrada')))}</div></div><div class="metric"><div class="label">ROC20</div><div class="value">{esc(pct(a.get('roc20_entrada')))}</div></div></div><div class="levels"><div class="level"><div class="label">Stop Loss</div><div class="value stop">{esc(stop)}</div></div><div class="level"><div class="label">Take Profit</div><div class="value target">{esc(tp)}</div></div><div class="level"><div class="label">Ratio R:R</div><div class="value">{esc(rr)}</div></div><div class="level"><div class="label">Actual</div><div class="value">{esc(current)}</div></div></div><div class="pills">{reasons(a.get('razones_entrada'))}</div><div class="note">Visual de niveles basado en la ficha de oportunidades de Alura Quant: Stop, Entrada, Actual y Take Profit.</div></div></div>
<div class="section"><div class="kicker">Contexto</div><h2>Más allá del gráfico</h2><div class="context"><div class="ctxlabel">Empresa</div><p>{esc(ctx.get('empresa_contexto'))}</p><div class="ctxlabel">Sector</div><p>{esc(ctx.get('sector_contexto'))}</p><div class="ctxlabel">Lectura contextual</div><p>{esc(ctx.get('comentario_contexto'))}</p><div class="ctxlabel">Riesgos a vigilar</div><p>{esc(ctx.get('riesgos_contexto'))}</p></div></div>
<div class="section"><div class="kicker">Actualidad</div><h2>Noticias recientes</h2><div class="news">{news_html(news)}</div></div>
<div class="section"><div class="kicker">Tesis del modelo</div><h2>Análisis cuantitativo de entrada</h2><div class="analysis"><div class="ailabel">IA · Tesis de entrada</div><p>{esc(a.get('analisis_ia_entrada') or 'Sin análisis IA de entrada disponible.')}</p></div></div>
<div class="footer"><b>Alura Quant</b> · Señales cuantitativas generadas mediante reglas sistemáticas e inteligencia artificial.<br>Esta comunicación es informativa y no constituye asesoramiento financiero personalizado. Los niveles corresponden a la señal registrada al generarse.</div>
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
