import html
import logging
import os
import re
from datetime import datetime, timezone

import resend
from supabase import Client, create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("alura-onboarding")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
FROM_EMAIL = os.getenv("ALURA_ONBOARDING_FROM", "Alura Quant <updates@aluraquant.es>").strip()
DASHBOARD_URL = os.getenv("ALURA_DASHBOARD_URL", "https://aluraquant.es").strip()
DRY_RUN = os.getenv("ALURA_ONBOARDING_DRY_RUN", "false").strip().lower() == "true"
PAGE_SIZE = 500
SUBJECT = "Bienvenido a Alura Quant | Cómo empezar"

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY.")
if not RESEND_API_KEY and not DRY_RUN:
    raise RuntimeError("Falta RESEND_API_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", re.IGNORECASE)


def escapar(value, default=""):
    if value is None:
        return default
    value = str(value).strip()
    return html.escape(value, quote=True) if value else default


def email_valido(email):
    return bool(email and EMAIL_RE.match(str(email).strip()))


def listar_suscriptores():
    rows, offset = [], 0
    while True:
        response = (
            supabase.table("suscriptores_free")
            .select("id,email,fecha_envio_onboarding")
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def tarjeta_numero(numero, titulo, texto):
    return f"""
    <div class="feature-card">
        <div class="feature-number">{escapar(numero)}</div>
        <div class="feature-content">
            <div class="feature-title">{escapar(titulo)}</div>
            <div class="feature-text">{escapar(texto)}</div>
        </div>
        <div class="feature-arrow">↗</div>
    </div>
    """


def html_onboarding():
    dashboard = escapar(DASHBOARD_URL)
    features = "".join([
        tarjeta_numero("01", "Alertas cuantitativas", "Señales seleccionadas a partir de métricas sistemáticas, niveles técnicos y una lectura cuantitativa de la oportunidad."),
        tarjeta_numero("02", "Newsletter semanal", "Una lectura compacta de la actividad de Alura Quant, el comportamiento de la cartera y el contexto de mercado."),
        tarjeta_numero("03", "Resumen mensual de mercados", "Una visión de conjunto para revisar tendencias, indicadores y movimientos relevantes de los principales mercados."),
    ])

    return f'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Alura Quant · Bienvenido</title>
<style>
body {{ margin:0; padding:0; background:#f5f7fb; color:#172033; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; -webkit-font-smoothing:antialiased; }}
.wrapper {{ width:100%; padding:22px 12px; box-sizing:border-box; }}
.email {{ width:100%; max-width:700px; margin:0 auto; background:#fff; border:1px solid #e6ebf2; border-radius:18px; overflow:hidden; box-shadow:0 8px 30px rgba(15,23,42,.07); }}
.topbar {{ padding:21px 28px 18px; border-bottom:1px solid #edf1f5; }}
.brand {{ color:#0f172a; font-size:14px; line-height:1; font-weight:850; letter-spacing:.01em; }}
.brand span {{ color:#2563eb; }}
.intro {{ padding:34px 28px 27px; }}
.eyebrow {{ color:#2563eb; font-size:9px; line-height:1; text-transform:uppercase; letter-spacing:.12em; font-weight:850; margin-bottom:12px; }}
.headline {{ color:#0f172a; font-size:29px; line-height:1.16; letter-spacing:-.025em; font-weight:850; margin:0; }}
.intro-text {{ max-width:590px; color:#64748b; font-size:13px; line-height:1.7; margin:13px 0 0; }}
.section {{ padding:0 28px 26px; }}
.section-heading {{ color:#0f172a; font-size:13px; line-height:1.3; font-weight:800; margin:0 0 11px; }}
.section-subtitle {{ color:#94a3b8; font-size:10px; line-height:1.5; margin:0 0 13px; }}
.feature-card {{ display:flex; align-items:center; gap:14px; padding:16px; margin-bottom:8px; background:#fff; border:1px solid #e4e9f0; border-radius:14px; }}
.feature-card:last-child {{ margin-bottom:0; }}
.feature-number {{ flex:0 0 auto; width:37px; height:37px; border-radius:11px; background:#f1f5ff; color:#2563eb; display:flex; align-items:center; justify-content:center; font-size:10px; font-weight:850; letter-spacing:.03em; }}
.feature-content {{ min-width:0; flex:1; }}
.feature-title {{ color:#1e293b; font-size:12px; line-height:1.3; font-weight:800; }}
.feature-text {{ color:#64748b; font-size:11px; line-height:1.55; margin-top:4px; }}
.feature-arrow {{ flex:0 0 auto; color:#94a3b8; font-size:16px; font-weight:500; }}
.cta-card {{ margin-top:6px; padding:21px; background:#f7faff; border:1px solid #dbe7fb; border-radius:14px; text-align:center; }}
.cta-title {{ color:#0f172a; font-size:14px; line-height:1.3; font-weight:800; margin:0; }}
.cta-text {{ color:#64748b; font-size:11px; line-height:1.6; margin:7px auto 14px; max-width:470px; }}
.button {{ display:inline-block; padding:12px 21px; background:#2563eb; color:#fff !important; text-decoration:none; border-radius:9px; font-size:11px; font-weight:800; letter-spacing:.01em; }}
.disclaimer {{ padding:0 28px 24px; color:#94a3b8; font-size:9px; line-height:1.65; }}
.footer {{ padding:17px 28px 20px; border-top:1px solid #edf1f5; background:#fafbfc; color:#94a3b8; font-size:9px; line-height:1.55; }}
.footer strong {{ color:#64748b; }}
@media (max-width:600px) {{ .topbar,.intro,.section,.disclaimer,.footer {{ padding-left:18px; padding-right:18px; }} .headline {{ font-size:25px; }} .feature-card {{ padding:14px; }} }}
</style>
</head>
<body>
<div class="wrapper"><div class="email">
<div class="topbar"><div class="brand">Alura <span>Quant</span></div></div>
<div class="intro">
<div class="eyebrow">Bienvenido</div>
<h1 class="headline">Una forma más clara de leer el mercado.</h1>
<p class="intro-text">Gracias por unirte a Alura Quant. Hemos diseñado una experiencia centrada en datos, contexto y disciplina cuantitativa para que puedas seguir el mercado con una perspectiva estructurada.</p>
</div>
<div class="section">
<h2 class="section-heading">Qué encontrarás en Alura Quant</h2>
<p class="section-subtitle">Tres formatos para seguir las oportunidades y el contexto sin convertir el ruido de mercado en ruido informativo.</p>
{features}
</div>
<div class="section"><div class="cta-card">
<h2 class="cta-title">Empieza por explorar Alura Quant</h2>
<p class="cta-text">Accede al dashboard y descubre cómo se presentan las oportunidades, métricas y señales del sistema.</p>
<a class="button" href="{dashboard}">Explorar Alura Quant ↗</a>
</div></div>
<div class="disclaimer">El contenido de Alura Quant es informativo y educativo. No constituye asesoramiento financiero ni una recomendación personalizada de inversión. La inversión en renta variable conlleva riesgo de pérdida.</div>
<div class="footer"><strong>Alura Quant</strong> · Datos, contexto y análisis cuantitativo.<br>Gracias por acompañarnos.</div>
</div></div>
</body></html>'''


def enviar(destinatario, content):
    if DRY_RUN:
        preview_path = "preview_onboarding.html"
        with open(preview_path, "w", encoding="utf-8") as file:
            file.write(content)
        log.info("DRY_RUN activo; vista previa generada en %s. No se enviaron correos.", preview_path)
        return False
    response = resend.Emails.send({"from":FROM_EMAIL,"to":destinatario,"subject":SUBJECT,"html":content})
    log.info("Email enviado a %s. Respuesta Resend: %s", destinatario, response)
    return True


def main():
    log.info("Preparando onboarding de Alura Quant...")
    content = html_onboarding()
    subscribers = listar_suscriptores()
    pendientes = {}
    invalidos = 0

    for subscriber in subscribers:
        raw_email = subscriber.get("email")
        if not raw_email:
            continue
        email = str(raw_email).strip().lower()
        if not email_valido(email):
            invalidos += 1
            log.warning("Email descartado por formato no válido: %s", email)
            continue
        if subscriber.get("fecha_envio_onboarding"):
            continue
        pendientes[email] = subscriber

    log.info("Suscriptores encontrados: %s | Pendientes: %s | Inválidos: %s", len(subscribers), len(pendientes), invalidos)

    if DRY_RUN:
        enviar("", content)
        return

    if not pendientes:
        log.info("No hay suscriptores pendientes de onboarding.")
        return

    enviados, errores = 0, 0
    for email, subscriber in pendientes.items():
        try:
            if enviar(email, content):
                sent_at = datetime.now(timezone.utc).isoformat()
                supabase.table("suscriptores_free").update({"fecha_envio_onboarding":sent_at}).eq("id", subscriber["id"]).execute()
                enviados += 1
                log.info("Onboarding registrado para %s", email)
        except Exception as exc:
            errores += 1
            log.exception("Error procesando %s: %s", email, exc)

    log.info("Proceso terminado | enviados=%s | errores=%s", enviados, errores)


if __name__ == "__main__":
    main()
