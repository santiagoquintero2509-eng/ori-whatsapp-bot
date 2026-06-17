# Publicar Ori en Render

Este archivo deja la ruta clara para que Ori quede activo 24/7 con una URL publica.

## 1. Subir el codigo a GitHub

Sube esta carpeta `whatsapp-bot` a un repositorio privado o publico de GitHub.

No subas el archivo `.env`. Ese archivo contiene secretos.

## 2. Crear el servicio en Render

En Render crea un nuevo **Web Service** conectado al repositorio de GitHub.

Usa estos comandos:

```text
Build Command: pip install -r requirements.txt
Start Command: python src/server.py
Health Check Path: /health
```

Render entregara una URL parecida a:

```text
https://ori-whatsapp-bot.onrender.com
```

## 3. Variables de entorno

En Render agrega estas variables con los mismos valores de tu `.env` local:

```text
VERIFY_TOKEN
WHATSAPP_TOKEN
PHONE_NUMBER_ID
GRAPH_API_VERSION
WHATSAPP_BUSINESS_ACCOUNT_ID
META_APP_ID
DRY_RUN=false
OPENAI_API_KEY
OPENAI_MODEL
OPENAI_TIMEOUT
```

## 4. Conectar Meta WhatsApp

En Meta Developers configura el webhook:

```text
Callback URL: https://tu-url-de-render.onrender.com/webhook
Verify Token: el valor de VERIFY_TOKEN
```

Luego suscribe el evento:

```text
messages
```

Desde ese momento, las personas podran escribirle a Ori por WhatsApp y recibir respuestas.
