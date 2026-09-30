import html
import logging
import os
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
HERO_IMAGE_URL = os.getenv(
    "ALURA_EMAIL_HERO_IMAGE_URL",
    "https://unsplash.com/es/fotos/persona-sosteniendo-un-telefono-inteligente-android-negro-xruML_FcCOk",
).strip()
DRY_RUN = os.getenv("ALURA_ONBOARDING_DRY_RUN", "false").strip().lower() == "true"
PAGE_SIZE = 500

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY.")
if not RESEND_API_KEY and not DRY_RUN:
    raise RuntimeError("Falta RESEND_API_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


def listar_suscriptores():
    rows, offset = [], 0
    while True:
        response = (supabase.table("suscriptores_free")
                    .select("id,email,fecha_envio_onboarding")
                    .order("id").range(offset, offset + PAGE_SIZE - 1).execute())
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def escapar(value):
    return html.escape(str(value or ""), quote=True)


def html_onboarding():
    image = escapar(HERO_IMAGE_URL)
    dashboard = escapar(DASHBOARD_URL)
    return f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#f3f6fb;font-family:Arial,sans-serif;color:#172033;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:24px 10px;background:#f3f6fb;"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;background:#fff;border-radius:18px;overflow:hidden;">
<tr><td style="padding:30px 32px 12px;"><div style="font-size:12px;font-weight:bold;letter-spacing:2px;color:#2563eb;text-transform:uppercase;">Bienvenido a Alura Quant</div><h1 style="font-size:27px;line-height:1.2;margin:10px 0;color:#10213a;">Tres formas de entender mejor el mercado</h1><p style="font-size:15px;line-height:1.65;color:#526176;margin:0;">Gracias por unirte. Hemos diseñado una experiencia clara para seguir oportunidades y tener contexto de mercado, sin promesas de rentabilidad.</p></td></tr>
<tr><td style="padding:14px 32px 26px;">
<div style="padding:17px;margin:10px 0;background:#f8faff;border:1px solid #e7edf7;border-radius:12px;"><strong style="color:#2563eb;">01 · Alertas cuantitativas</strong><p style="margin:7px 0 0;font-size:14px;line-height:1.6;color:#526176;">Recibe señales seleccionadas con métricas, niveles técnicos y una explicación de la tesis para que puedas evaluarlas por tu cuenta.</p></div>
<div style="padding:17px;margin:10px 0;background:#f8faff;border:1px solid #e7edf7;border-radius:12px;"><strong style="color:#2563eb;">02 · Newsletter semanal</strong><p style="margin:7px 0 0;font-size:14px;line-height:1.6;color:#526176;">Un resumen periódico de la actividad de la cartera, las señales y los factores de mercado relevantes de la semana.</p></div>
<div style="padding:17px;margin:10px 0;background:#f8faff;border:1px solid #e7edf7;border-radius:12px;"><strong style="color:#2563eb;">03 · Resumen mensual de mercados</strong><p style="margin:7px 0 0;font-size:14px;line-height:1.6;color:#526176;">Una visión de conjunto para repasar tendencias e indicadores de los principales mercados al cierre de cada mes.</p></div>
<div style="text-align:center;padding:18px 0 8px;"><a href="{dashboard}" style="display:inline-block;padding:13px 22px;background:#2563eb;color:#fff;text-decoration:none;border-radius:9px;font-weight:bold;">Explorar Alura Quant</a></div>
<p style="font-size:11px;line-height:1.55;color:#8793a5;margin-top:16px;">Aviso Legal y Descargo de Responsabilidad: Alura Quant es una herramienta tecnológica de análisis cuantitativo y educación financiera. Los datos, scores, niveles técnicos y análisis generados por algoritmos o inteligencia artificial no constituyen, ni deben interpretarse como, un servicio de asesoramiento en inversión, recomendación de compra/venta o análisis financiero personalizado según la Ley del Mercado de Valores. La renta variable conlleva riesgos de pérdida de capital. Cada usuario es responsable exclusivo de sus decisiones de inversión.
</p>
</td></tr><tr><td style="padding:18px 32px;background:#f8fafc;color:#8793a5;font-size:11px;">Alura Quant · Gracias por acompañarnos.</td></tr>
</table></td></tr></table></body></html>'''


def enviar(destinatario, content):
    if DRY_RUN:
        with open("preview_onboarding.html", "w", encoding="utf-8") as file:
            file.write(content)
        log.info("DRY_RUN activo; vista previa generada. No se enviaron correos.")
        return False
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": destinatario,
        "subject": "Bienvenido a Alura Quant | Tu guía para empezar",
        "html": content,
    })
    return True


def main():
    content = html_onboarding()
    pendientes = [r for r in listar_suscriptores()
                  if r.get("email") and not r.get("fecha_envio_onboarding")]
    log.info("Suscriptores pendientes de bienvenida: %s", len(pendientes))
    if DRY_RUN:
        enviar("", content)
        return
    for subscriber in pendientes:
        email = str(subscriber["email"]).strip().lower()
        try:
            if enviar(email, content):
                sent_at = datetime.now(timezone.utc).isoformat()
                supabase.table("suscriptores_free").update({
                    "fecha_envio_onboarding": sent_at
                }).eq("id", subscriber["id"]).execute()
                log.info("Bienvenida enviada a %s", email)
        except Exception as exc:
            log.exception("Error con el suscriptor %s: %s", email, exc)


if __name__ == "__main__":
    main()
