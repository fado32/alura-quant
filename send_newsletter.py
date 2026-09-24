# Lectura explícita y depuración de la clave de Resend
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()

print(f"--- DEPURACIÓN DE CLAVE ---")
print(f"¿Existe la variable?: {bool(RESEND_API_KEY)}")
print(f"Longitud de la clave: {len(RESEND_API_KEY) if RESEND_API_KEY else 0}")
if RESEND_API_KEY:
    print(f"Empieza con: {RESEND_API_KEY[:4]}... y termina con: {RESEND_API_KEY[-4:]}")
print(f"---------------------------")

if not RESEND_API_KEY:
    raise RuntimeError("Falta RESEND_API_KEY en las variables de entorno o GitHub Secrets.")

resend.api_key = RESEND_API_KEY
