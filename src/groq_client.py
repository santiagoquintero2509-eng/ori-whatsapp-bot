import json
import os
import urllib.error
import urllib.request


GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqClientError(RuntimeError):
    pass


def is_groq_enabled():
    use_groq = os.getenv("USE_GROQ", "false").strip().lower()
    if use_groq not in {"1", "true", "yes", "si"}:
        return False

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    return bool(api_key) and not api_key.startswith("pega_aqui")


def polish_with_groq(user_message, base_reply, feria_context, memory=None):
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key or api_key.startswith("pega_aqui"):
        raise GroqClientError("GROQ_API_KEY no esta configurada")

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip()
    timeout = int(os.getenv("GROQ_TIMEOUT", "18"))

    payload = {
        "model": model,
        "temperature": 0.35,
        "max_tokens": 260,
        "messages": [
            {"role": "system", "content": build_system_prompt(feria_context)},
            {"role": "user", "content": build_user_prompt(user_message, base_reply, memory or {})},
        ],
    }

    request = urllib.request.Request(
        GROQ_CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OriWhatsAppBot/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise GroqClientError(f"Groq respondio {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise GroqClientError(f"No se pudo conectar con Groq: {error}") from error

    text = extract_message_text(data)
    if not text:
        raise GroqClientError("Groq no devolvio texto")

    return text.strip()


def build_system_prompt(feria_context):
    return f"""
Eres Ori, asistente virtual oficial de Feria Origen Colombia.
Tu tarea es conversar de forma mas humana, clara y contextual, usando la respuesta base como verdad principal.
Puedes reordenar, suavizar, hacer seguimiento y adaptar el tono al contexto de la conversacion.
Responde siempre en espanol para WhatsApp.
Se breve, calida, util y profesional. Puedes usar 2 o 3 parrafos cortos si ayuda.
No uses markdown complejo.
No digas que eres una IA, Groq, Llama ni ChatGPT.
No agregues precios, horarios, telefonos, direcciones exactas, agenda detallada ni datos no confirmados.
Si falta informacion, dilo con naturalidad y ofrece escribir "asesor".
Si hay numeros de stands, estados o medidas, conservalos exactamente.
Si la respuesta base incluye un enlace, debes conservarlo.
No cambies el sentido de la respuesta base.

Contexto oficial cargado en Ori:
{feria_context}
""".strip()


def build_user_prompt(user_message, base_reply, memory):
    role = memory.get("role") or "sin rol definido"
    last_intent = memory.get("last_intent") or "sin intencion previa"
    selected_stand = memory.get("selected_stand") or "ninguno"

    return f"""
Mensaje recibido:
{user_message}

Contexto de conversacion:
- Rol detectado: {role}
- Intencion previa: {last_intent}
- Stand seleccionado: {selected_stand}

Respuesta base de Ori, con datos oficiales que debes respetar:
{base_reply}

Redacta una sola respuesta final de WhatsApp, natural y cercana.
""".strip()


def extract_message_text(data):
    choices = data.get("choices") or []
    if not choices:
        return ""

    message = choices[0].get("message") or {}
    return str(message.get("content") or "").strip()
