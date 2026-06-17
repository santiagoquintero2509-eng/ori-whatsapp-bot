# Ori WhatsApp Bot

Este proyecto es el chatbot de Ori para responder preguntas de la Feria Origen Colombia por WhatsApp.

## Estado actual

La app de Meta ya fue creada con estos datos:

```text
Nombre de la app: Ori
META_APP_ID=1013127661132309
PHONE_NUMBER_ID=1124759997395044
WHATSAPP_BUSINESS_ACCOUNT_ID=2289770658496326
GRAPH_API_VERSION=v25.0
```

El token temporal de WhatsApp ya quedó guardado en `.env`. No lo compartas ni lo publiques.

## Abrir en Visual Studio Code

1. Abre Visual Studio Code.
2. Selecciona la carpeta `whatsapp-bot`.
3. Copia `.env.example` y crea un archivo nuevo llamado `.env`.
4. Llena los datos de WhatsApp Cloud API y OpenAI en `.env`.

Necesitas Python 3.10 o superior. Si la terminal dice que `python` no existe, instala Python y vuelve a abrir VS Code.

Tambien puedes iniciar el bot desde la pestana "Run and Debug" de VS Code usando la configuracion `Iniciar Ori WhatsApp Bot`.

## Probar sin WhatsApp

En la terminal de VS Code:

```bash
python src/server.py
```

Abre:

```text
http://localhost:3000
```

Tambien puedes probar directo:

```text
http://localhost:3000/test?message=stands%20disponibles
```

## Cerebro local de Ori

Ori funciona sin pagar ChatGPT. El archivo `src/ori.py` tiene un motor local que interpreta preguntas, reconoce intenciones y responde con la informacion cargada de la feria.

Puede orientar sobre:

- evento, fechas y ubicacion
- productos y actividades
- expositores y participacion comercial
- stands disponibles, reservados y no disponibles
- paso a asesor cuando falta un dato oficial

La informacion base de la feria esta en:

```text
src/data.py
```

## Activar ChatGPT opcional

En `.env`, agrega tu llave de OpenAI:

```text
USE_OPENAI=true
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.5
```

Con esa llave, Ori puede usar ChatGPT para redactar respuestas naturales con el contexto de la feria. Si `USE_OPENAI` no esta en `true`, o si OpenAI falla, Ori usa automaticamente su cerebro local para no quedarse sin responder.

La llamada a OpenAI esta en:

```text
src/openai_client.py
```

## Conectar con WhatsApp

Necesitas una cuenta de Meta for Developers con WhatsApp Cloud API activado.

1. En Meta, entra a tu app y busca la seccion de WhatsApp.
2. Copia el token de acceso y el `Phone number ID`.
3. Pegalos en `.env`:

```text
WHATSAPP_TOKEN=...
PHONE_NUMBER_ID=...
WHATSAPP_BUSINESS_ACCOUNT_ID=...
META_APP_ID=...
DRY_RUN=false
```

4. Publica este servidor con una URL HTTPS. Para pruebas puedes usar una herramienta como ngrok.
5. En la configuracion del webhook de Meta usa:

```text
Callback URL: https://tu-url-publica/webhook
Verify token: el mismo VERIFY_TOKEN de tu archivo .env
```

6. Suscribe el webhook al evento de mensajes.

Cuando alguien escriba al WhatsApp conectado, Meta enviara el mensaje a `/webhook` y Ori respondera automaticamente.

## Preguntas que Ori entiende

- `hola`
- `informacion del evento`
- `expositores`
- `productos`
- `ubicacion`
- `actividades`
- `stands disponibles`
- `stand 21`
- `precios`
- `asesor`

## Donde editar la informacion

La informacion de la feria esta en:

```text
src/data.py
```

La forma en que Ori interpreta preguntas y actua como asistente de feria esta en:

```text
src/ori.py
```
