import os
import time
import pandas as pd
from datetime import datetime, timedelta
from supabase import create_client, Client
from openai import OpenAI
import resend

# 1. Configuración de Credenciales y Parámetros de IA
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
resend.api_key = os.environ.get("RESEND_API_KEY")

IA_PROVIDER = os.getenv("IA_PROVIDER", "gemini").strip().lower()
MODELO_GEMINI = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# Inicializar cliente de Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def cliente_ia():
    if IA_PROVIDER == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Falta GEMINI_API_KEY. Configúrala como variable de entorno o GitHub Secret.")
        return OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)
    raise RuntimeError(f"IA_PROVIDER no válido: {IA_PROVIDER}. Usa 'gemini'.")

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
    """Extrae los snapshots de la última semana y procesa tanto cerradas como el ranking de abiertas"""
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
    
    # 1. Métricas de operaciones cerradas
    operaciones_cerradas = df[df['estado'].isin(['WIN', 'LOSS'])]
    total_cerradas = len(operaciones_cerradas)
    
    win_rate = 0.0
    pnl_medio = 0.0
    if total_cerradas > 0:
        wins = len(operaciones_cerradas[operaciones_cerradas['estado'] == 'WIN'])
        win_rate = round((wins / total_cerradas) * 100, 2)
        pnl_medio = round(operaciones_cerradas['pnl_actual_pct'].mean(), 2)
        
    # 2. Análisis de posiciones abiertas (Top 3 mejores y Top 3 peores de la semana)
    open_df = df[df['estado'] == 'OPEN']
    top_3_str = "No hay suficientes datos de posiciones abiertas."
    worst_3_str = "No hay suficientes datos de posiciones abiertas."
    
    if not open_df.empty and 'pnl_actual_pct' in open_df.columns:
        if 'symbol' in open_df.columns:
            open_df = open_df.sort_values('fecha_snapshot').drop_duplicates(subset=['symbol'], keep='last')
        
        open_sorted = open_df.sort_values(by='pnl_actual_pct', ascending=False)
        top_3 = open_sorted.head(3)
        worst_3 = open_sorted.tail(3).sort_values(by='pnl_actual_pct', ascending=True)
        
        top_3_str = "\n".join([f"- {row.get('symbol', 'Activo')}: PnL actual {row.get('pnl_actual_pct', 0)}%" for _, row in top_3.iterrows()])
        worst_3_str = "\n".join([f"- {row.get('symbol', 'Activo')}: PnL actual {row.get('pnl_actual_pct', 0)}%" for _, row in worst_3.iterrows()])

    metricas = {
        "periodo": f"Del {inicio_semana} al {hoy}",
        "total_operaciones_semana": total_cerradas,
        "win_rate_semanal": win_rate,
        "pnl_medio_semanal": pnl_medio,
        "alertas_activas_actuales": len(open_df),
        "top_3_abiertas": top_3_str,
        "worst_3_abiertas": worst_3_str
    }
    
    return metricas, df.to_string()

def generar_html_newsletter(metricas):
    """Redacta la newsletter analizando cerradas, abiertas, top/worst y generando el HTML corporativo"""
    
    prompt = f"""
    Eres el gestor cuantitativo senior de Alura Quant. Tienes que redactar la newsletter semanal para los suscriptores en formato HTML limpio, moderno y profesional.
    
    Utiliza un diseño corporativo elegante: fondo blanco, contenedores limpios, tipografía sans-serif, y una paleta de colores sobria con azul marino (#1e293b) y gris claro (#f8fafc).
    
    ESTAMOS EN EL PRESENTE (Fecha actual: {datetime.now().strftime('%Y-%m-%d')}).
    
    Por favor, redacta el informe combinando un comentario analítico experto con los datos reales de nuestra cartera cuantitativa de esta semana:
       - Periodo: {metricas['periodo']}
       - Operaciones cerradas: {metricas['total_operaciones_semana']}
       - Win Rate semanal: {metricas['win_rate_semanal']}%
       - PnL medio por operación: {metricas['pnl_medio_semanal']}%
       - Posiciones/Alertas activas totales: {metricas['alertas_activas_actuales']}
       
       - TOP 3 POSICIONES ABIERTAS CON MEJOR RENDIMIENTO:
       {metricas['top_3_abiertas']}
       
       - TOP 3 POSICIONES ABIERTAS CON PEOR RENDIMIENTO / RETRASO:
       {metricas['worst_3_abiertas']}
       
    Estructura requerida para el HTML (usa etiquetas <h2>, <p>, <ul>, <li>, <strong>, etc.):
    - **Cabecera**: Título del reporte ("Alura Quant — Informe Semanal de Inversores") y fechas.
    - **Contexto Global**: Breve comentario experto sobre la evolución de los mercados financieros.
    - **Radiografía de Cartera Cerrada**: Análisis de las métricas cuantitativas y del comportamiento del algoritmo en las operaciones cerradas.
    - **Comportamiento de Posiciones Abiertas**: Revisión de cómo están evolucionando las posiciones vivas en la cartera global.
    - **Foco en Activos Destacados (Top 3 Mejores y Top 3 Peores)**: Un análisis cualitativo y crítico por parte de la IA explicando el comportamiento de las 3 mejores y las 3 peores posiciones abiertas de la semana.
    - **Outlook**: Perspectiva, riesgos y objetivos para la próxima semana.
    
    IMPORTANTE: Devuelve **únicamente** el código HTML puro dentro de un bloque de texto, sin explicaciones adicionales, listo para ser inyectado en el cuerpo de un email.
    """

    print(f"Generando el comentario y el HTML con el modelo {MODELO_GEMINI}...")
    
    client = cliente_ia()
    
    response = client.chat.completions.create(
        model=MODELO_GEMINI,
        messages=[
            {"role": "system", "content": "Eres un asistente financiero experto cuantitativo y generas código HTML puro de alta calidad visual."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
    )
    
    html_content = response.choices[0].message.content.replace("```html", "").replace("```", "").strip()
    return html_content

def enviar_correo(html_content, destinatarios):
    """Envía el correo utilizando la API de Resend"""
    if not destinatarios:
        print("No hay destinatarios a los que enviar el correo.")
        return

    print(f"Enviando newsletter a través de Resend a {len(destinatarios)} suscriptor(es)...")
    
    params = {
        # Con Resend se recomienda usar el dominio por defecto de pruebas o uno verificado
        "from": "Alura Quant <onboarding@resend.dev>", 
        "to": destinatarios,
        "subject": f"Alura Quant | Informe Semanal — {datetime.now().strftime('%d/%m/%Y')}",
        "html": html_content,
    }

    try:
        email = resend.Emails.send(params)
        print("¡Correo enviado con éxito a través de Resend! Respuesta:", email)
    except Exception as e:
        print("Error al enviar el correo con Resend:", e)

if __name__ == "__main__":
    lista_suscriptores = obtener_suscriptores()
    
    if lista_suscriptores:
        metricas, datos_str = extraer_datos_supabase()
        
        if metricas:
            try:
                html_newsletter = generar_html_newsletter(metricas)
                print("\n--- HTML GENERADO CORRECTAMENTE ---\n")
                enviar_correo(html_newsletter, lista_suscriptores)
            except Exception as e:
                print(f"Error generando o enviando la newsletter: {e}")
        else:
            print(datos_str)
    else:
        print("Operación cancelada: la tabla de suscriptores está vacía.")
