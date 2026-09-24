import os
import requests

# Carga las credenciales directamente desde las variables de entorno
api_key = os.environ.get("MAILJET_API_KEY")
secret_key = os.environ.get("MAILJET_SECRET_KEY")

url = "https://api.mailjet.com/v3.1/send"

# Pon aquí el correo donde quieres recibir la prueba (tu propio email)
correo_destino = "adelgadosanz@gmail.com"

payload = {
    "Messages": [
        {
            "From": {
                "Email": "updates@aluraquant.com", # O el correo verificado que estés usando en Mailjet
                "Name": "Prueba Alura Quant"
            },
            "To": [
                {
                    "Email": correo_destino,
                    "Name": "Alberto"
                }
            ],
            "Subject": "Prueba de texto plano desde Mailjet",
            "TextPart": "Hola Alberto, este es un mensaje de prueba en texto plano para verificar que los correos de Mailjet llegan correctamente a tu bandeja.",
            "HTMLPart": "<h3>¡Correo de prueba recibido con éxito!</h3><p>Si estás leyendo esto, la API de Mailjet funciona perfectamente y el problema no era ni el texto ni el HTML.</p>"
        }
    ]
}

print("Enviando correo de prueba a Mailjet...")
try:
    response = requests.post(url, json=payload, auth=(api_key, secret_key))
    print(f"Código de respuesta HTTP: {response.status_code}")
    print("Respuesta de Mailjet:", response.text)
except Exception as e:
    print("Error al conectar con Mailjet:", e)
