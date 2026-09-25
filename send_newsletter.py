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

# Lectura explícita y limpieza de la clave de Resend
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
if not RESEND_API_KEY:
    raise RuntimeError("Falta RESEND_API_KEY en las variables de entorno o GitHub Secrets.")

resend.api_key = RESEND_API_KEY

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
    """Extrae los snapshots de la última semana y procesa tanto cerradas/saltadas como el ranking de activas"""
    hoy = datetime.now().date()
    inicio_semana = hoy - timedelta(days=7)
    
    print(f"Extrayendo datos de Supabase desde {inicio_semana} al {hoy}...")
    
    # 1. Extraer registros de la última semana para operaciones cerradas/saltadas
    response_semana = supabase.table("backtesting_diario_alertas") \
        .select("*") \
        .gte("fecha_snapshot", inicio_semana.isoformat()) \
        .execute()
    
    df_semana = pd.DataFrame(response_semana.data)
    
    # 2. Extraer TODAS las posiciones en estado 'ACTIVA' para evaluar el ranking global actual
    response_activas = supabase.table("backtesting_diario_alertas") \
        .select("*") \
        .eq("estado", "ACTIVA") \
        .execute()
    
    df_activas = pd.DataFrame(response_activas.data)
    
    if df_semana.empty and df_activas.empty:
        return None, "No hay registros en la tabla para este periodo."
    
    # Identificar campo de activo (ticker o symbol)
    col_ticker = 'ticker' if 'ticker' in df_semana.columns else ('symbol' if 'symbol' in df_semana.columns else None)
    if df_activas.empty and not df_semana.empty:
        df_activas = df_semana.copy()

    # Procesar operaciones cerradas o con stop saltado en la semana
    operaciones_cerradas = pd.DataFrame()
    if not df_semana.empty and 'estado' in df_semana.columns:
        operaciones_cerradas = df_semana[df_semana['estado'].str.upper().isin(['STOP_SALTADO', 'WIN', 'LOSS', 'CERRADA', 'CLOSED', 'TP', 'SL'])]
    
    total_cerradas = len(operaciones_cerradas)
    win_rate = 0.0
    pnl_medio_cerradas = 0.0
    
    if total_cerradas > 0:
        # Consideramos éxito (Win) si el PnL es positivo o el estado es WIN/TP
        wins = len(operaciones_cerradas[(operaciones_cerradas['estado'].str.upper().isin(['WIN', 'TP'])) | (operaciones_cerradas['pnl_actual_pct'] > 0)])
        win_rate = round((wins / total_cerradas) * 100, 2)
        if 'pnl_actual_pct' in operaciones_cerradas.columns:
            pnl_medio_cerradas = round(operaciones_cerradas['pnl_actual_pct'].mean(), 2)

    # Procesar posiciones activas para Top 3 y Worst 3
    top_3_str = "No hay suficientes datos de posiciones activas."
    worst_3_str = "No hay suficientes datos de posiciones activas."
    
    if not df_activas.empty and 'pnl_actual_pct' in df_activas.columns and col_ticker:
        # Nos quedamos con el snapshot más reciente por activo
        df_activas_unicas = df_activas.sort_values('fecha_snapshot').drop_duplicates(subset=[col_ticker], keep='last')
        
        open_sorted = df_activas_unicas.sort_values(by='pnl_actual_pct', ascending=False)
        top_3 = open_sorted.head(3)
        worst_3 = open_sorted.tail(3).sort_values(by='pnl_actual_pct', ascending=True)
        
        top_3_str = "\n".join([f"- **{row.get(col_ticker, 'Activo')}**: PnL actual **{row.get('pnl_actual_pct', 0)}%** (RSI: {row.get('rsi_actual', 'N/A')}, Score: {row.get('score_actual', 'N/A')})" for _, row in top_3.iterrows()])
        worst_3_str = "\n".join([f"- **{row.get(col_ticker, 'Activo')}**: PnL actual **{row.get('pnl_actual_pct', 0)}%** (RSI: {row.get('rsi_actual', 'N/A')}, Distancia SL: {row.get('distancia_sl_pct', 'N/A')}%)" for _, row in worst_3.iterrows()])

    metricas = {
        "periodo": f"Del {inicio_semana} al {hoy}",
        "total_operaciones_semana": total_cerradas,
        "win_rate_semanal": win_rate,
        "pnl_medio_semanal": pnl_medio_cerradas,
        "alertas_activas_actuales": len(df_activas_unicas) if not df_activas.empty else 0,
        "top_3_abiertas": top_3_str,
        "worst_3_abiertas": worst_3_str
    }
    
    return metricas, df_semana.to_string() if not df_semana.empty else "Sin datos semanales"

def generar_html_newsletter(metricas):
    """Redacta la newsletter analizando el comportamiento de la cartera y generando el HTML corporativo"""
    
    prompt = f"""
    Eres el gestor cuantitativo senior de Alura Quant. Tienes que redactar la newsletter semanal para los inversores en formato HTML limpio, moderno y profesional.
    
    Utiliza un diseño corporativo elegante: fondo blanco, contenedores limpios, tipografía sans-serif, y una paleta de colores sobria con azul marino (#1e293b) y gris claro (#f8fafc).
    
    ESTAMOS EN EL PRESENTE (Fecha actual: {datetime.now().strftime('%Y-%m-%d')}).
    
    Por favor, redacta el informe combinando un comentario analítico experto con los datos reales de nuestra cartera cuantitativa de esta semana:
       - Periodo: {metricas['periodo']}
       - Alertas cerradas / saltadas esta semana: {metricas['total_operaciones_semana']}
       - Win Rate semanal: {metricas['win_rate_semanal']}%
       - PnL medio por operación cerrada: {metricas['pnl_medio_semanal']}%
       - Alertas activas totales en cartera: {metricas['alertas_activas_actuales']}
       
       - TOP 3 POSICIONES ACTIVAS CON MEJOR RENDIMIENTO:
       {metricas['top_3_abiertas']}
       
       - TOP 3 POSICIONES ACTIVAS CON PEOR RENDIMIENTO / RETRASO:
       {metricas['worst_3_abiertas']}
       
    Estructura requerida para el HTML (usa etiquetas <h2>, <p>, <ul>, <li>, <strong>, etc.):
    - **Cabecera**: Título del reporte ("Alura Quant — Informe Semanal de Cartera") y fechas.
    - **Contexto Global**: Breve comentario experto sobre la evolución de los mercados financieros y el comportamiento macro de la semana.
    - **Radiografía de Cartera (Beneficios y Alertas)**: Análisis detallado del rendimiento global, nuevas alertas, estado de las operaciones cerradas/saltadas y Win Rate.
    - **Foco en Activos Destacados (Top 3 Mejores y Top 3 Peores)**: Un análisis cualitativo y crítico personalizado por parte de la IA explicando individualmente el comportamiento, los indicadores técnicos (como RSI o Score) y la perspectiva de las 3 mejores y las 3 peores posiciones de la semana.
    - **Outlook Estratégico**: Perspectiva, gestión de riesgo y objetivos para la próxima semana.
    
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

    destinatarios_limpios = [str(email).strip() for email in destinatarios if email]
    
    print(f"Enviando newsletter a través de Resend a {len(destinatarios_limpios)} suscriptor(es)...")
    
    params = {
        "from": "adelgadosanz@gmail.com", 
        "to": "adelgadosanz@gmail.com",
        "bcc": destinatarios_limpios,
        "subject": f"Alura Quant | Informe Semanal de Cartera — {datetime.now().strftime('%d/%m/%Y')}",
        "html": html_content,
    }

    try:
        email = resend.Emails.send(params)
        print("¡Correo enviado con éxito a través de Resend! Respuesta:", email)
    except Exception as e:
        print(f"Error detallado al enviar el correo con Resend: {type(e).__name__} - {e}")

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
