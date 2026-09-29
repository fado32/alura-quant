import html
import logging
import os
from datetime import datetime, timedelta, timezone

import resend
from supabase import Client, create_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("alura-campanas")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
FROM_EMAIL = os.getenv("ALURA_CAMPAIGN_FROM", "Alura Quant <updates@aluraquant.es>").strip()
PRO_URL = os.getenv("STRIPE_PAYMENT_LINK", "https://aluraquant.es/#planes-top").strip()
HERO_IMAGE_URL = os.getenv(
    "ALURA_EMAIL_HERO_IMAGE_URL",
    "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?auto=format&fit=crop&w=1200&q=80",
).strip()
COOLDOWN_DAYS = int(os.getenv("ALURA_CAMPAIGN_COOLDOWN_DAYS", "30"))
DRY_RUN = os.getenv("ALURA_CAMPAIGN_DRY_RUN", "false").strip().lower() == "true"
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
                    .select("id,email,fecha_ultima_campana_enviada")
                    .order("id").range(offset, offset + PAGE_SIZE - 1).execute())
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def escapar(value):
    return html.escape(str(value or ""), quote=True)


def html_campana():
    image = escapar(HERO_IMAGE_URL)
    pro_url = escapar(PRO_URL)
    return f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#f3f6fb;font-family:Arial,sans-serif;color:#172033;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:24px 10px;background:#f3f6fb;"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;background:#fff;border-radius:18px;overflow:hidden;">
<tr><td><img src="{image}" alt="Análisis de mercados" width="640" style="display:block;width:100%;max-width:640px;height:auto;border:0;"></td></tr>
<tr><td style="padding:30px 32px 12px;"><div style="font-size:12px;font-weight:bold;letter-spacing:2px;color:#2563eb;text-transform:uppercase;">Alura Quant Pro</div><h1 style="font-size:27px;line-height:1.2;margin:10px 0;color:#10213a;">Más profundidad para analizar cada oportunidad</h1><p style="font-size:15px;line-height:1.65;color:#526176;margin:0;">Si quieres ir más allá de la selección gratuita, Pro reúne señales de mayor convicción y herramientas para seguir la tesis con más detalle.</p></td></tr>
<tr><td style="padding:14px 32px 26px;">
<div style="padding:17px;margin:10px 0;background:#f8faff;border:1px solid #e7edf7;border-radius:12px;"><strong style="color:#2563eb;">Alertas con Score superior a 80</strong><p style="margin:7px 0 0;font-size:14px;line-height:1.6;color:#526176;">Acceso a oportunidades que superan el umbral de convicción establecido por el sistema.</p></div>
<div style="padding:17px;margin:10px 0;background:#f8faff;border:1px solid #e7edf7;border-radius:12px;"><strong style="color:#2563eb;">Envío prioritario y tesis cuantitativa + IA</strong><p style="margin:7px 0 0;font-size:14px;line-height:1.6;color:#526176;">Recibe la alerta con sus métricas, niveles y contexto para facilitar tu propia evaluación.</p></div>
<div style="padding:17px;margin:10px 0;background:#f8faff;border:1px solid #e7edf7;border-radius:12px;"><strong style="color:#2563eb;">Histórico detallado e informe semanal</strong><p style="margin:7px 0 0;font-size:14px;line-height:1.6;color:#526176;">Consulta la evolución de las tesis y revisa un resumen semanal de señales y mercado.</p></div>
<div style="text-align:center;padding:18px 0 8px;"><a href="{pro_url}" style="display:inline-block;padding:13px 22px;background:#2563eb;color:#fff;text-decoration:none;border-radius:9px;font-weight:bold;">Conocer Alura Quant Pro · 19 €/mes</a></div>
<p style="font-size:11px;line-height:1.55;color:#8793a5;margin-top:16px;">La suscripción es opcional y no garantiza resultados. El contenido es informativo y educativo; no constituye asesoramiento ni recomendación personalizada de inversión. La renta variable conlleva riesgo de pérdida.</p>
</td></tr><tr><td style="padding:18px 32px;background:#f8fafc;color:#8793a5;font-size:11px;">Alura Quant · Información sobre el plan Pro.</td></tr>
</table></td></tr></table></body></html>'''


def fecha_utc(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def enviar(destinatario, content):
    if DRY_RUN:
        with open("preview_campana.html", "w", encoding="utf-8") as file:
            file.write(content)
        log.info("DRY_RUN activo; vista previa generada. No se enviaron correos.")
        return False
    resend.Emails.send({
        "from": FROM_EMAIL,
        "to": destinatario,
        "subject": "Alura Quant Pro | Más herramientas para seguir el mercado",
        "html": content,
    })
    return True


def main():
    cutoff = datetime.now(timezone.utc) - timedelta(days=COOLDOWN_DAYS)
    elegibles = []
    for row in listar_suscriptores():
        email = str(row.get("email") or "").strip().lower()
        if not email:
            continue
        try:
            last_sent = fecha_utc(row.get("fecha_ultima_campana_enviada"))
        except (TypeError, ValueError):
            log.warning("Fecha de campaña no válida para %s; se omite.", email)
            continue
        if last_sent is None or last_sent <= cutoff:
            elegibles.append(row)

    log.info("Suscriptores elegibles para campaña: %s (cooldown=%s días)", len(elegibles), COOLDOWN_DAYS)
    if DRY_RUN:
        html_campana()
        enviar("", html_campana())
        return

    content = html_campana()
    for subscriber in elegibles:
        email = str(subscriber["email"]).strip().lower()
        try:
            if enviar(email, content):
                sent_at = datetime.now(timezone.utc).isoformat()
                supabase.table("suscriptores_free").update({
                    "fecha_ultima_campana_enviada": sent_at
                }).eq("id", subscriber["id"]).execute()
                log.info("Campaña enviada a %s", email)
        except Exception as exc:
            log.exception("Error con el suscriptor %s: %s", email, exc)


if __name__ == "__main__":
    main()