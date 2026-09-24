import os
import time
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client, Client
from google import genai
from google.genai import types
import resend

# 1. Configuración de Credenciales
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
resend.api_key = os.environ.get("RESEND_API_KEY")

# Inicializar clientes
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)

def obtener_suscriptores():
    """Extrae la lista de correos electrónicos desde la tabla suscriptores_free de Supabase"""
    print("Consultando lista de suscriptores en Supabase...")
    response = supabase.table("suscriptores_free").select("email").execute()
    
    if not response.data:
        print("No se encontraron suscriptores en la tabla suscriptores_free.")
        return []
    
    emails = [sub['email'] for sub in response.data]
    print(f"Se han encontrado {len(emails)} suscriptor(es).")
    return emails

def extraer_datos_supabase():
    """Extrae los snapshots de la última semana desde la tabla backtesting_diario_alertas"""
    hoy = datetime.now().date()
    inicio_semana = hoy - timedelta(days=7)
    
    print(f"Extrayendo datos de Supabase desde {inicio_semana} al {hoy}...")
    
    response = supabase.table("backtesting_diario_alertas") \
        .select("*") \
        .gte("fecha_snapshot", inicio_semana.isoformat()) \
        .execute()
    
    df = pd.DataFrame(response.data)
    if df.empty:
        return None, "No hay registros en la tabla para este periodo."
    
    # Procesar métricas clave
    operaciones_cerradas = df[df['estado'].isin(['WIN', 'LOSS'])]
    total_cerradas = len(operaciones_cerradas)
    
    win_rate = 0.0
    pnl_medio = 0.0
    if total_cerradas > 0:
        wins = len(operaciones_cerradas[operaciones_cerradas['estado'] == 'WIN'])
        win_rate = round((wins / total_cerradas) * 100, 2)
        pnl_medio = round(operaciones_cerradas['pnl_actual_pct'].mean(), 2)
        
    metricas = {
        "periodo": f"Del {inicio_semana} al {hoy}",
        "total_operaciones_semana": total_cerradas,
        "win_rate_semanal": win_rate,
        "pnl_medio_semanal": pnl_medio,
        "alertas_activas_actuales": len(df[df['estado'] == 'OPEN'])
    }
    
    return metricas, df.to_string()

def generar_html_newsletter(metricas):
    """Redacta la newsletter aplicando una pausa para estabilizar la API y genera el comentario cuantitativo de IA"""
    
    prompt = f"""
    Eres el gestor cuantitativo senior de Alura Quant. Tienes que redactar la newsletter semanal para los suscriptores en formato HTML limpio, moderno y profesional.
    
    ESTAMOS EN EL PRESENTE (Fecha actual: {datetime.now().strftime('%Y-%m-%d')}).
    
    Por favor, redacta el informe combinando un comentario analítico experto con los datos reales de nuestra cartera cuantitativa de esta semana:
       - Periodo: {metricas['periodo']}
       - Operaciones cerradas: {metricas['total_operaciones_semana']}
       - Win Rate semanal: {metricas['win_rate_semanal']}%
       - PnL medio por operación: {metricas['pnl_medio_semanal']}%
       - Posiciones/Alertas activas al cierre: {metricas['alertas_activas_actuales']}
       
    Estructura requerida para el HTML (usa etiquetas <h2>, <p>, <ul>, <li>, <strong>, etc., con un estilo sobrio, tipografía sans-serif, fondo blanco, contenedores limpios y colores corporativos elegantes como azul marino y gris):
    - **Cabecera**: Título del reporte ("Alura Quant — Informe Semanal de Inversores") y fechas.
    - **Contexto Global**: Breve comentario experto sobre la evolución de los mercados.
    - **Radiografía de Cartera**: Análisis detallado de las métricas cuantitativas y del comportamiento del algoritmo.
    - **Outlook**: Perspectiva y objetivos para la próxima semana.
    
    IMPORTANTE: Devuelve **únicamente** el código HTML puro dentro de un bloque de texto, sin explicaciones adicionales, listo para ser inyectado en el cuerpo de un email.
    """

    print("Esperando 5 segundos para estabilizar conexión con la API...")
    time.sleep(5)  # Pausa de cortesía para evitar restricciones de IP en GitHub Actions

    print("Generando el comentario y el HTML de la newsletter con IA...")
    
    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
        ),
    )
    
    html_content = response.text.replace("```html", "").replace("```", "").strip()
    return html_content

def enviar_correo(html_content, destinatarios):
    """Envía el correo utilizando la API de Resend a todos los suscriptores de la tabla"""
    if not destinatarios:
        print("No hay destinatarios a los que enviar el correo.")
        return

    print(f"Enviando newsletter a {len(destinatarios)} suscriptor(es)...")
    
    params = {
        "from": "Alura Quant <updates@aluraquant.com>",
        "to": destinatarios,
        "subject": f"Alura Quant | Informe Semanal — {datetime.now().strftime('%d/%m/%Y')}",
        "html": html_content,
    }

    try:
        email = resend.Emails.send(params)
        print("¡Correo enviado con éxito! ID:", email)
    except Exception as e:
        print("Error al enviar el correo:", e)

if __name__ == "__main__":
    lista_suscriptores = obtener_suscriptores()
    
    if lista_suscriptores:
        metricas, datos_str = extraer_datos_supabase()
        
        if metricas:
            html_newsletter = generar_html_newsletter(metricas)
            print("\n--- HTML GENERADO CORRECTAMENTE ---\n")
            enviar_correo(html_newsletter, lista_suscriptores)
        else:
            print(datos_str)
    else:
        print("Operación cancelada: la tabla de suscriptores está vacía.")
