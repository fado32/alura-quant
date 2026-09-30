import html
import logging
import os
import re
from datetime import datetime, timezone

import resend
from supabase import Client, create_client


# ============================================================
# CONFIGURACIÓN
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("alura-onboarding")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()

FROM_EMAIL = os.getenv(
    "ALURA_ONBOARDING_FROM",
    "Alura Quant <updates@aluraquant.es>",
).strip()

DASHBOARD_URL = os.getenv(
    "ALURA_DASHBOARD_URL",
    "https://aluraquant.es",
).strip()

DRY_RUN = (
    os.getenv("ALURA_ONBOARDING_DRY_RUN", "false")
    .strip()
    .lower()
    == "true"
)

PAGE_SIZE = 500
SUBJECT = "Bienvenido a Alura Quant | Cómo empezar"

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY.")

if not RESEND_API_KEY and not DRY_RUN:
    raise RuntimeError("Falta RESEND_API_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY


# ============================================================
# HELPERS
# ============================================================

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", re.IGNORECASE)


def escapar(value, default=""):
    if value is None:
        return default

    value = str(value).strip()
    return html.escape(value, quote=True) if value else default


def email_valido(email):
    return bool(email and EMAIL_RE.match(str(email).strip()))


def listar_suscriptores():
    rows = []
    offset = 0

    while True:
        response = (
            supabase
            .table("suscriptores_free")
            .select("id,email,fecha_envio_onboarding")
            .order("id")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )

        batch = response.data or []
        rows.extend(batch)

        if len(batch) < PAGE_SIZE:
            return rows

        offset += PAGE_SIZE


# ============================================================
# BLOQUES VISUALES
# ============================================================

def feature_card(numero, titulo, texto):
    return f"""
    <tr>
      <td style="padding:0 0 10px 0;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
               style="border:1px solid #cbd5e1;border-radius:12px;background:#ffffff;">
          <tr>
            <td width="54" valign="top" style="padding:16px 0 16px 16px;">
              <div style="
                width:38px;
                height:38px;
                line-height:38px;
                text-align:center;
                border-radius:10px;
                background:#f1f5ff;
                color:#2563eb;
                font-size:11px;
                font-weight:800;
                letter-spacing:.04em;
              ">{escapar(numero)}</div>
            </td>

            <td valign="middle" style="padding:16px 16px 16px 12px;">
              <div style="
                color:#172033;
                font-size:13px;
                line-height:18px;
                font-weight:800;
              ">{escapar(titulo)}</div>

              <div style="
                color:#64748b;
                font-size:11px;
                line-height:17px;
                padding-top:4px;
              ">{escapar(texto)}</div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    """


def html_onboarding():
    dashboard = escapar(DASHBOARD_URL)

    features = "".join(
        [
            feature_card(
                "01",
                "Alertas cuantitativas",
                "Señales con métricas, niveles técnicos y una lectura cuantitativa de la oportunidad.",
            ),
            feature_card(
                "02",
                "Newsletter semanal",
                "Actividad de la cartera, señales abiertas y contexto de mercado relevante de la semana.",
            ),
            feature_card(
                "03",
                "Resumen mensual de mercados",
                "Una visión de conjunto sobre tendencias e indicadores de los principales mercados.",
            ),
        ]
    )

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta name="color-scheme" content="light">
<title>Alura Quant · Bienvenido</title>

<style>
  html, body {{
    margin:0 !important;
    padding:0 !important;
    width:100% !important;
    background:#f4f6fa;
  }}

  body {{
    -webkit-font-smoothing:antialiased;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
  }}

  table {{
    border-collapse:collapse;
  }}

  @media only screen and (max-width:600px) {{
    .outer-pad {{
      padding:14px 8px !important;
    }}

    .email-shell {{
      border-radius:14px !important;
    }}

    .content-pad {{
      padding-left:20px !important;
      padding-right:20px !important;
    }}

    .headline {{
      font-size:25px !important;
      line-height:30px !important;
    }}

    .intro-copy {{
      font-size:12px !important;
      line-height:19px !important;
    }}

    .mobile-hide {{
      display:none !important;
    }}
  }}
</style>
</head>

<body>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0">
  <tr>
    <td class="outer-pad" align="center" style="padding:24px 12px;">

      <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
             class="email-shell"
             style="
               max-width:680px;
               background:#ffffff;
               border:1px solid #e2e8f0;
               border-radius:16px;
               overflow:hidden;
             ">

        <!-- =================================================
             BRAND
             ================================================= -->
        <tr>
          <td class="content-pad" style="padding:20px 28px 18px;border-bottom:1px solid #edf1f5;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
              <tr>
                <td>
                  <div style="
                    color:#172033;
                    font-size:14px;
                    line-height:18px;
                    font-weight:850;
                    letter-spacing:-.01em;
                  ">
                    Alura <span style="color:#2563eb;">Quant</span>
                  </div>
                </td>

                <td align="right">
                  <div style="
                    color:#94a3b8;
                    font-size:9px;
                    line-height:18px;
                    font-weight:700;
                    letter-spacing:.08em;
                    text-transform:uppercase;
                  ">
                    Bienvenido
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- =================================================
             INTRO
             ================================================= -->
        <tr>
          <td class="content-pad" style="padding:31px 28px 22px;">

            <div style="
              color:#2563eb;
              font-size:9px;
              line-height:12px;
              font-weight:850;
              letter-spacing:.12em;
              text-transform:uppercase;
              padding-bottom:10px;
            ">
              Alura Quant
            </div>

            <h1 class="headline" style="
              margin:0;
              color:#111827;
              font-size:28px;
              line-height:33px;
              letter-spacing:-.035em;
              font-weight:850;
            ">
              Una forma más clara<br class="mobile-hide">
              de leer el mercado.
            </h1>

            <p class="intro-copy" style="
              max-width:570px;
              margin:11px 0 0;
              color:#64748b;
              font-size:12px;
              line-height:19px;
            ">
              Gracias por unirte a Alura Quant. Una experiencia centrada en
              datos, contexto y disciplina cuantitativa para seguir el mercado
              con una perspectiva estructurada.
            </p>

          </td>
        </tr>

        <!-- =================================================
             FEATURES
             ================================================= -->
        <tr>
          <td class="content-pad" style="padding:0 28px 23px;">

            <div style="
              color:#172033;
              font-size:12px;
              line-height:17px;
              font-weight:850;
              padding-bottom:4px;
            ">
              Qué encontrarás
            </div>

            <div style="
              color:#94a3b8;
              font-size:10px;
              line-height:15px;
              padding-bottom:13px;
            ">
              Tres formatos para seguir oportunidades y contexto sin ruido.
            </div>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
              {features}
            </table>

          </td>
        </tr>

        <!-- =================================================
             CTA
             ================================================= -->
        <tr>
          <td class="content-pad" style="padding:0 28px 24px;">

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
                   style="
                     border:1px solid #dbe7fb;
                     border-radius:13px;
                     background:#f7faff;
                   ">
              <tr>
                <td align="center" style="padding:20px 18px 19px;">

                  <div style="
                    color:#172033;
                    font-size:13px;
                    line-height:18px;
                    font-weight:850;
                  ">
                    Empieza por explorar Alura Quant
                  </div>

                  <div style="
                    max-width:470px;
                    margin:5px auto 13px;
                    color:#64748b;
                    font-size:10px;
                    line-height:16px;
                  ">
                    Accede al dashboard y descubre cómo presentamos las
                    oportunidades, métricas y señales del sistema.
                  </div>

                  <a href="{dashboard}"
                     style="
                       display:inline-block;
                       background:#2563eb;
                       color:#ffffff;
                       text-decoration:none;
                       border-radius:8px;
                       padding:10px 18px;
                       font-size:10px;
                       line-height:15px;
                       font-weight:800;
                     ">
                    Explorar Alura Quant&nbsp; ↗
                  </a>

                </td>
              </tr>
            </table>

          </td>
        </tr>

        <!-- =================================================
             DISCLAIMER
             ================================================= -->
        <tr>
          <td class="content-pad" style="padding:0 28px 20px;">

            <div style="
              border-top:1px solid #edf1f5;
              padding-top:15px;
              color:#94a3b8;
              font-size:9px;
              line-height:14px;
            ">
              El contenido de Alura Quant es informativo y educativo.
              No constituye asesoramiento financiero ni recomendación
              personalizada de inversión. La inversión en renta variable
              conlleva riesgo de pérdida.
            </div>

          </td>
        </tr>

        <!-- =================================================
             FOOTER
             ================================================= -->
        <tr>
          <td class="content-pad" style="
            padding:15px 28px 17px;
            background:#fafbfc;
            border-top:1px solid #edf1f5;
          ">
            <div style="
              color:#94a3b8;
              font-size:9px;
              line-height:14px;
            ">
              <strong style="color:#64748b;">Alura Quant</strong>
              · Datos, contexto y análisis cuantitativo.
            </div>
          </td>
        </tr>

      </table>

    </td>
  </tr>
</table>
</body>
</html>
"""


# ============================================================
# ENVÍO
# ============================================================

def enviar(destinatario, content):
    if DRY_RUN:
        preview_path = "preview_onboarding.html"

        with open(preview_path, "w", encoding="utf-8") as file:
            file.write(content)

        log.info(
            "DRY_RUN activo; vista previa generada en %s. "
            "No se enviaron correos.",
            preview_path,
        )
        return False

    response = resend.Emails.send(
        {
            "from": FROM_EMAIL,
            "to": destinatario,
            "subject": SUBJECT,
            "html": content,
        }
    )

    log.info(
        "Email enviado a %s. Respuesta Resend: %s",
        destinatario,
        response,
    )
    return True


# ============================================================
# MAIN
# ============================================================

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

        # Deduplicación por email.
        pendientes[email] = subscriber

    log.info(
        "Suscriptores: %s | Pendientes: %s | Inválidos: %s",
        len(subscribers),
        len(pendientes),
        invalidos,
    )

    if DRY_RUN:
        enviar("", content)
        return

    if not pendientes:
        log.info("No hay suscriptores pendientes de onboarding.")
        return

    enviados = 0
    errores = 0

    for email, subscriber in pendientes.items():
        try:
            if enviar(email, content):
                sent_at = datetime.now(timezone.utc).isoformat()

                (
                    supabase
                    .table("suscriptores_free")
                    .update({"fecha_envio_onboarding": sent_at})
                    .eq("id", subscriber["id"])
                    .execute()
                )

                enviados += 1
                log.info("Onboarding registrado para %s", email)

        except Exception as exc:
            errores += 1
            log.exception("Error procesando %s: %s", email, exc)

    log.info(
        "Proceso terminado | enviados=%s | errores=%s",
        enviados,
        errores,
    )


if __name__ == "__main__":
    main()
