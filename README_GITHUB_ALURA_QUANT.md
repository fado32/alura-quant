# Alura Quant — GitHub Actions + Gemini

## 1. Archivos del repositorio

El repositorio debe contener al menos:

- `bot.py`
- `historial_alertas.csv` (o una variante que el bot pueda resolver, aunque se recomienda el nombre estándar)
- `universo_activos.csv` si utilizas un universo externo
- `requirements.txt`
- `.github/workflows/alura_quant.yml`

## 2. API de Gemini

No pongas la clave dentro de `bot.py` ni en ningún archivo que se suba a GitHub.

En GitHub:

`Settings` → `Secrets and variables` → `Actions` → `New repository secret`

Nombre:

`GEMINI_API_KEY`

Valor: tu clave de Google AI Studio.

El workflow la inyecta únicamente durante la ejecución.

## 3. Modelo

El modelo por defecto es:

`gemini-3.5-flash-lite`

También puede cambiarse mediante la variable de entorno `GEMINI_MODEL`.

## 4. Tres ejecuciones diarias

El workflow ejecuta el bot de lunes a viernes a:

- 14:00 Europe/Madrid
- 18:00 Europe/Madrid
- 22:30 Europe/Madrid

GitHub Actions admite zonas horarias IANA en `schedule`, por lo que el horario se adapta al cambio CET/CEST.

También existe `workflow_dispatch` para lanzarlo manualmente.

## 5. Uso de Gemini

Python calcula indicadores, Score, SL, TP y estado de tesis.

Gemini solo interpreta el resultado.

En seguimiento, Gemini no se llama en cada ejecución. Se utiliza cuando hay un cambio material, por ejemplo:

- cambio de Estado_Estrategia
- Score +/-10 puntos o más
- cambio relevante de RVOL
- cambio relevante de ROC20
- cambio de estructura de tendencia
- cambio de zona RSI

Esto reduce llamadas innecesarias y mantiene el cálculo cuantitativo determinista.

## 6. Git automático

Al terminar, el bot añade y confirma:

- `bot.py`
- el CSV de historial utilizado

y hace push a la rama que está ejecutando GitHub Actions.

El workflow proporciona `contents: write` y configura la identidad Git necesaria.
